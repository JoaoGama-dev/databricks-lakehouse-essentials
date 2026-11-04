"""Testes da base de produção (Fase 7): volume, estrutura da origem, falha com motivo,
taxa de sucesso, teto de custo e os alertas que avisam o cliente e o suporte.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

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
    sql_registrar_falhas,
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


COLUNAS_BRONZE_AGENDA = {"bronze_agenda": ["value", "_fonte", "_arquivo_origem", "_ingerido_em"]}


def partes_da_estrutura(sql: str) -> list[str]:
    return sql.split("\nAS\n", 1)[1].split("\nUNION ALL\n")


def parte_do_tipo(sql: str, tipo: str) -> str:
    return next(parte for parte in partes_da_estrutura(sql) if f"'{tipo}' AS ds_tipo" in parte)


def test_arquivo_ignorado_compara_o_ultimo_arquivo_da_bronze_com_o_retrato():
    sql = sql_estrutura("essentials", "portfolio", FONTES, COLUNAS_BRONZE_AGENDA)
    parte = parte_do_tipo(sql, "arquivo_ignorado")
    assert parte.startswith("SELECT 'bronze_agenda' AS nm_tabela, 'arquivo_ignorado' AS ds_tipo, ")
    bronze = "`essentials`.`portfolio`.`bronze_agenda`"
    assert f"WHERE _ingerido_em >= (SELECT max(_ingerido_em) FROM {bronze})) AS b" in parte
    assert (
        "LEFT ANTI JOIN (SELECT DISTINCT _arquivo_origem FROM `essentials`.`portfolio`.`silver_int_agenda_retrato`) "
        "AS r ON b._arquivo_origem = r._arquivo_origem"
    ) in parte


def test_codificacao_invalida_olha_so_o_arquivo_do_retrato_da_fonte_texto():
    sql = sql_estrutura("essentials", "portfolio", FONTES, COLUNAS_BRONZE_AGENDA)
    parte = parte_do_tipo(sql, "codificacao_invalida")
    assert parte.startswith("SELECT DISTINCT 'bronze_agenda' AS nm_tabela, 'codificacao_invalida' AS ds_tipo, ")
    assert "LEFT SEMI JOIN (SELECT DISTINCT _arquivo_origem FROM `essentials`.`portfolio`." in parte
    # Risco: escape errado faria o aviso nunca disparar. O SQL tira uma barra do literal; o que
    # chega à regex Java precisa ser \x{FFFD}, sem o caractere escrito no código.
    literal = re.search(r"RLIKE '([^']*)'", parte).group(1)
    assert literal.replace("\\\\", "\\") == r"\x{FFFD}"
    assert "\N{REPLACEMENT CHARACTER}" not in sql


def test_avisos_de_arquivo_mostram_so_o_nome_do_arquivo():
    # LGPD: nunca o conteúdo (value) nem a pasta da landing, só o nome do arquivo.
    sql = sql_estrutura("essentials", "portfolio", FONTES, COLUNAS_BRONZE_AGENDA)
    for tipo in ("arquivo_ignorado", "codificacao_invalida"):
        selecao = parte_do_tipo(sql, tipo).split(" FROM ", 1)[0]
        assert "element_at(split(b._arquivo_origem, '/'), -1) AS nm_coluna" in selecao, tipo
        assert "value" not in selecao, tipo


def test_avisos_de_arquivo_so_onde_fazem_sentido():
    # Sem a bronze no information_schema, nenhum aviso (a view não pode citar tabela que não existe).
    assert sql_estrutura("essentials", "portfolio", FONTES, {}).rstrip().endswith("WHERE false")
    # A fonte tabela (cargos) não tem arquivo: nenhum dos dois avisos.
    sem_arquivo = sql_estrutura("essentials", "portfolio", FONTES, {"bronze_cargos": ["id_cargo", "_ingerido_em"]})
    assert "arquivo_ignorado" not in sem_arquivo.split("\nAS\n", 1)[1]
    # CSV em snapshot: arquivo ignorado sim; codificação não (o CSV tem a opção encoding).
    csv = {"nome": "metas", "tipo": "arquivo", "modo_carga": "snapshot", "colunas": {"nm_meta": {"origem": "meta"}},
           "arquivo": {"formato": "csv", "caminho": "metas"}}
    consulta = sql_estrutura("c", "s", [csv], {"bronze_metas": ["meta", "_arquivo_origem", "_ingerido_em"]})
    tipos = [parte.split("'")[3] for parte in partes_da_estrutura(consulta)]
    assert tipos == ["arquivo_ignorado"]
    # Texto em modo incremental: sem retrato, a codificação é vista no arquivo da última carga.
    texto = {**csv, "modo_carga": "incremental", "arquivo": {"formato": "texto", "caminho": "metas"}}
    consulta = sql_estrutura("c", "s", [texto], {"bronze_metas": ["value", "_arquivo_origem", "_ingerido_em"]})
    assert [parte.split("'")[3] for parte in partes_da_estrutura(consulta)] == ["codificacao_invalida"]
    assert "LEFT SEMI JOIN (SELECT DISTINCT _arquivo_origem FROM `c`.`s`.`bronze_metas` WHERE _ingerido_em" in consulta


def test_alerta_de_qualidade_le_todos_os_avisos_de_mon_estrutura():
    alerta = alertas()["qualidade_carga"]
    consulta = alerta["query_text"]
    trecho = consulta[consulta.index("SELECT ds_tipo, nm_tabela") :]
    # Sem WHERE no trecho de mon_estrutura: todo tipo de aviso, inclusive os novos, dispara o alerta.
    assert "WHERE" not in trecho


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
    assert "sql_registrar_falhas(" in codigo


def carregar_registrar_falha():
    caminho = RAIZ / "src" / "governanca" / "registrar_falha.py"
    especificacao = importlib.util.spec_from_file_location("registrar_falha", caminho)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


def tarefa_fake(chave: str, estado: str | None):
    resultado = SimpleNamespace(value=estado) if estado else None
    return SimpleNamespace(task_key=chave, state=SimpleNamespace(result_state=resultado))


def test_registrar_falha_ignora_a_si_mesma_e_o_que_so_falhou_por_dependencia():
    # Na nova tentativa, a registrar_falha anterior aparece como FAILED: não é uma falha da carga.
    modulo = carregar_registrar_falha()
    tarefas = [
        tarefa_fake("atualizar_lakehouse", "FAILED"),
        tarefa_fake("governanca_depois", "UPSTREAM_FAILED"),
        tarefa_fake("registrar_falha", "FAILED"),
        tarefa_fake("governanca_antes", "SUCCESS"),
        tarefa_fake("ingestao_api", None),
    ]
    assert [t.task_key for t in modulo.tarefas_com_falha(tarefas)] == ["atualizar_lakehouse"]


def test_registro_de_falha_nao_duplica_na_mesma_execucao():
    sql = sql_registrar_falhas("essentials", "portfolio", "42", [("atualizar_lakehouse", "motivo")], "https://x")
    assert sql.startswith("MERGE INTO `essentials`.`portfolio`.`mon_falhas` AS f")
    assert "ON f.id_execucao = n.id_execucao AND f.nm_tarefa = n.nm_tarefa" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql and "WHEN MATCHED" not in sql
    assert "('42', 'atualizar_lakehouse', 'motivo', 'https://x')" in sql


def test_registrar_falha_nao_e_tentada_de_novo():
    assert tarefas()["registrar_falha"]["max_retries"] == 0


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
