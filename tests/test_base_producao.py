"""Testes da base de produção (Fase 7): volume, estrutura da origem, falha com motivo,
taxa de sucesso, teto de custo e os alertas que avisam o cliente e o suporte.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from essentials.config_fontes import carregar_fontes, validar_config
from essentials.monitoramento_sql import (
    TAMANHO_MAXIMO_MOTIVO,
    colunas_novas_na_origem,
    motivo_seguro,
    sql_custo_mensal,
    sql_estrutura,
    sql_execucoes,
    sql_tabela_falhas,
    sql_volume,
    tabela_do_volume,
)

RAIZ = Path(__file__).resolve().parents[1]
FONTES = carregar_fontes(RAIZ / "config" / "fontes.yml")


def carregar_yaml(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def tarefas() -> dict[str, dict]:
    job = carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]["essentials_carga_diaria"]
    return {tarefa["task_key"]: tarefa for tarefa in job["tasks"]}


def alertas() -> dict[str, dict]:
    return carregar_yaml(RAIZ / "resources" / "alertas.yml")["resources"]["alerts"]


def bundle() -> dict:
    return carregar_yaml(RAIZ / "databricks.yml")


# 7.2 Volume ---------------------------------------------------------------------------


def test_volume_e_medido_no_retrato_ou_na_silver():
    assert tabela_do_volume({"nome": "agenda", "modo_carga": "snapshot"}) == "silver_int_agenda_retrato"
    assert tabela_do_volume({"nome": "vendas", "modo_carga": "cdc"}) == "silver_int_vendas_mudancas"
    assert tabela_do_volume({"nome": "vendas", "modo_carga": "incremental"}) == "silver_vendas"


def test_volume_so_alerta_no_snapshot_com_retrato_vazio_ou_queda_acima_do_limite():
    sql = sql_volume("essentials", "portfolio", FONTES, 40)
    assert "('silver_int_agenda_retrato', 'snapshot')" in sql
    assert "details:flow_progress:metrics:num_output_rows" in sql
    assert "ds_modo = 'snapshot' AND (qt_linhas = 0 OR coalesce(" in sql
    assert "<= -40) AS fl_alerta" in sql


def test_volume_e_valido_sem_fontes():
    assert "(CAST(NULL AS STRING), CAST(NULL AS STRING))" in sql_volume("c", "s", [], 50)


# 7.3 Estrutura da origem ----------------------------------------------------------------


def test_coluna_nova_na_origem_e_detectada_so_onde_a_bronze_tem_as_colunas_da_origem():
    colunas = {
        "bronze_cargos": ["id_cargo", "prefixo_vaga", "area", "atualizado_em", "_fonte", "_ingerido_em", "cd_novo"],
        # A agenda é texto com preparação: a bronze tem só "value", e isso não é coluna nova.
        "bronze_agenda": ["value", "_fonte", "_arquivo_origem", "_ingerido_em"],
    }
    assert colunas_novas_na_origem(FONTES, colunas) == [("bronze_cargos", "cd_novo")]


def test_estrutura_conta_dado_resgatado_e_e_valida_sem_aviso():
    colunas = {"bronze_cargos": ["id_cargo", "prefixo_vaga", "area", "atualizado_em", "_rescued_data"]}
    sql = sql_estrutura("essentials", "portfolio", FONTES, colunas)
    assert "'dado_resgatado' AS ds_tipo" in sql and "WHERE _rescued_data IS NOT NULL" in sql
    vazia = sql_estrutura("essentials", "portfolio", FONTES, {})
    assert vazia.rstrip().endswith("WHERE false")


def test_bronze_de_arquivo_nao_falha_com_coluna_nova():
    codigo = (RAIZ / "src" / "pipeline" / "bronze.py").read_text(encoding="utf-8")
    assert '.option("cloudFiles.schemaEvolutionMode", "rescue")' in codigo


# 7.7 Planilhas Excel -------------------------------------------------------------------------


def test_fonte_de_planilha_excel_e_aceita_e_lida_pelo_auto_loader():
    config = carregar_yaml(RAIZ / "config" / "fontes.yml")
    planilha = {
        "nome": "metas",
        "descricao": "Metas mensais enviadas em Excel.",
        "tipo": "arquivo",
        "arquivo": {"formato": "excel", "caminho": "metas", "opcoes": {"dataAddress": "Metas!A1:C100"}},
        "modo_carga": "snapshot",
        "chave_primaria": ["dt_mes"],
        "coluna_atualizacao": "_arquivo_origem",
        "colunas": {"dt_mes": {"origem": "mes", "descricao": "Mês da meta.", "tipo": "data"}},
    }
    config["fontes"].append(planilha)
    validar_config(config)
    codigo = (RAIZ / "src" / "pipeline" / "bronze.py").read_text(encoding="utf-8")
    assert '"excel": "excel"' in codigo
    # O Auto Loader de Excel exige schemaEvolutionMode none (documentação da Databricks).
    assert '.option("cloudFiles.schemaEvolutionMode", "none")' in codigo


# 7.4 Falha com motivo -----------------------------------------------------------------------


def test_motivo_de_regra_falhar_traz_so_os_nomes_das_regras():
    # Mensagem no formato do motor, com um registro fictício.
    mensagem = (
        "Flow 'silver_int_agenda_retrato' failed to meet the expectation. "
        "Violated expectations: 'data_plausivel'.\n"
        'Input record: {"nm_candidato":"Maria Exemplo","nr_telefone":"(41) 99999-0000"}'
    )
    motivo = motivo_seguro(mensagem)
    assert motivo == "Regra de qualidade que para a carga foi violada: data_plausivel. Confira o arquivo enviado."
    assert "Maria" not in motivo and "9999" not in motivo


@pytest.mark.parametrize(
    "mensagem",
    [
        'Erro ao ler a origem: {"nm_candidato": "Maria Exemplo"}',
        "Falha na tarefa [nr_telefone=(41) 99999-0000]",
        "Problem with record Maria Exemplo",
    ],
)
def test_motivo_corta_qualquer_trecho_que_pareca_registro(mensagem):
    motivo = motivo_seguro(mensagem)
    assert "Maria" not in motivo and "9999" not in motivo


def test_motivo_tem_tamanho_limitado_e_nunca_vem_vazio():
    assert len(motivo_seguro("x" * 1000)) == TAMANHO_MAXIMO_MOTIVO
    assert motivo_seguro(None).startswith("Falha sem mensagem")
    assert motivo_seguro("Erro na primeira linha\nsegunda linha com detalhe") == "Erro na primeira linha"


def test_tabela_de_falhas_segue_o_dicionario():
    sql = sql_tabela_falhas("essentials", "portfolio")
    assert sql.startswith("CREATE TABLE IF NOT EXISTS `essentials`.`portfolio`.`mon_falhas`")
    assert "`ds_motivo` STRING COMMENT" in sql and "`dh_falha` TIMESTAMP COMMENT" in sql
    assert "TBLPROPERTIES ('camada' = 'monitoramento', 'tipo' = 'falha')" in sql


def test_registrar_falha_roda_so_quando_algo_falha_e_depende_de_todas_as_tarefas():
    tarefa = tarefas()["registrar_falha"]
    assert tarefa["run_if"] == "AT_LEAST_ONE_FAILED"
    outras = set(tarefas()) - {"registrar_falha", "tem_fonte_api", "tem_fonte_banco"}
    assert {d["task_key"] for d in tarefa["depends_on"]} == outras
    parametros = tarefa["spark_python_task"]["parameters"]
    assert parametros[parametros.index("--run-id") + 1] == "{{job.run_id}}"
    assert (RAIZ / "resources" / tarefa["spark_python_task"]["python_file"]).resolve().is_file()


def test_registrar_falha_grava_o_motivo_limpo_e_termina_com_erro():
    codigo = (RAIZ / "src" / "governanca" / "registrar_falha.py").read_text(encoding="utf-8")
    assert "motivo_seguro(" in codigo
    assert "sys.exit(" in codigo
    assert "INSERT INTO" in codigo


def test_aviso_de_falha_do_job_vai_tambem_para_o_suporte():
    job = carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]["essentials_carga_diaria"]
    assert "${var.email_suporte}" in job["email_notifications"]["on_failure"]


# 7.5 e 7.6 Execuções e teto de custo ---------------------------------------------------------


def test_taxa_de_sucesso_vem_das_execucoes_do_job():
    sql = sql_execucoes("essentials", "portfolio", "123")
    assert "FROM system.lakeflow.job_run_timeline" in sql and "WHERE job_id = '123'" in sql
    assert "AS pc_sucesso" in sql


def test_custo_mensal_compara_com_o_teto():
    sql = sql_custo_mensal("essentials", "portfolio", 150)
    assert "FROM `essentials`.`portfolio`.`mon_custo_diario`" in sql
    assert "CAST(150.0 AS DOUBLE) AS vl_teto" in sql and "AS pc_do_teto" in sql


def test_governanca_cria_as_views_novas_e_a_tabela_de_falhas():
    codigo = (RAIZ / "src" / "governanca" / "governanca.py").read_text(encoding="utf-8")
    for funcao in ("sql_tabela_falhas(", "sql_volume(", "sql_estrutura(", "sql_execucoes(", "sql_custo_mensal("):
        assert funcao in codigo, funcao
    parametros = tarefas()["governanca_depois"]["spark_python_task"]["parameters"]
    valor = {parametros[i]: parametros[i + 1] for i in range(0, len(parametros), 2)}
    assert valor["--limite-queda-volume-pct"] == "${var.limite_queda_volume_pct}"
    assert valor["--teto-custo-mensal"] == "${var.teto_custo_mensal_usd}"


# Alertas ----------------------------------------------------------------------------------


def test_alertas_novos_leem_as_views_e_mandam_a_tabela_no_email():
    lidas = {"falha_carga": "mon_falhas", "qualidade_carga": "mon_estrutura", "custo_teto": "mon_custo_mensal"}
    for nome, view in lidas.items():
        alerta = alertas()[nome]
        assert view in alerta["query_text"], nome
        assert "{{QUERY_RESULT_TABLE}}" in alerta["custom_description"], nome
        assert alerta["evaluation"]["notification"]["subscriptions"] == [{"user_email": "${var.usuario_alerta}"}]
    assert "mon_volume" in alertas()["qualidade_carga"]["query_text"]
    assert alertas()["custo_teto"]["evaluation"]["threshold"]["value"]["double_value"] == 80


def test_alertas_pausados_em_dev_e_ci_e_com_suporte_em_prod():
    targets = bundle()["targets"]
    for alvo in ("dev", "ci"):
        for nome in alertas():
            assert targets[alvo]["resources"]["alerts"][nome]["schedule"]["pause_status"] == "PAUSED", (alvo, nome)
    for nome in alertas():
        inscricoes = targets["prod"]["resources"]["alerts"][nome]["evaluation"]["notification"]["subscriptions"]
        assert inscricoes == [{"destination_id": "${var.destino_suporte_id}"}], nome


def test_variaveis_da_base_de_producao():
    variaveis = bundle()["variables"]
    novas = ("limite_queda_volume_pct", "teto_custo_mensal_usd", "email_suporte", "destino_suporte_id", "landing_url")
    assert set(novas) <= set(variaveis)
    prod = bundle()["targets"]["prod"]["variables"]
    assert {"teto_custo_mensal_usd", "email_suporte", "destino_suporte_id", "landing_url"} <= set(prod)
