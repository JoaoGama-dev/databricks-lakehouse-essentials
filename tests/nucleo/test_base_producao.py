"""Testes da base de produção (Fase 7): volume, estrutura da origem, falha com motivo,
taxa de sucesso, teto de custo e os alertas que avisam o cliente e o suporte.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from essentials.config_fontes import validar_config
from essentials.monitoramento_sql import (
    MOTIVO_SEM_CLASSE,
    TAMANHO_MAXIMO_MOTIVO,
    colunas_novas_na_origem,
    motivo_seguro,
    sql_custo_mensal,
    sql_estrutura,
    sql_execucoes,
    sql_volume,
    tabela_do_volume,
)
from fontes_ficticias import CADASTRO, EVENTOS, cadastro, config_ficticia

RAIZ = Path(__file__).resolve().parents[2]
FONTES = [EVENTOS]


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
    assert tabela_do_volume({"nome": "eventos", "modo_carga": "snapshot"}) == "silver_int_eventos_retrato"
    assert tabela_do_volume({"nome": "vendas", "modo_carga": "cdc"}) == "silver_int_vendas_mudancas"
    assert tabela_do_volume({"nome": "vendas", "modo_carga": "incremental"}) == "silver_vendas"


def test_volume_so_alerta_no_snapshot_com_retrato_vazio_ou_queda_acima_do_limite():
    sql = sql_volume("essentials", "portfolio_monitoramento", FONTES, 40)
    assert "('silver_int_eventos_retrato', 'snapshot')" in sql
    assert "details:flow_progress:metrics:num_output_rows" in sql
    assert "ds_modo = 'snapshot' AND (qt_linhas = 0 OR coalesce(" in sql
    assert "<= -40) AS fl_alerta" in sql


def test_volume_e_valido_sem_fontes():
    assert "(CAST(NULL AS STRING), CAST(NULL AS STRING))" in sql_volume("c", "s", [], 50)


# 7.3 Estrutura da origem ----------------------------------------------------------------


# Coluna nova na origem: antes conferida na integração (cargos ganhava uma coluna), agora só
# aqui, com a fonte fictícia do tipo tabela, cuja bronze tem as colunas da origem.
COLUNAS_BRONZE_CADASTRO = ["id_item", "prefixo", "grupo", "atualizado_em", "_fonte", "_ingerido_em"]


def test_coluna_nova_na_origem_e_detectada_so_onde_a_bronze_tem_as_colunas_da_origem():
    colunas = {
        "bronze_cadastro": [*COLUNAS_BRONZE_CADASTRO, "cd_centro_custo"],
        # Texto com preparação: a bronze tem só "value", e isso não é coluna nova.
        "bronze_eventos": ["value", "_fonte", "_arquivo_origem", "_modificado_em", "_ingerido_em"],
    }
    assert colunas_novas_na_origem([*FONTES, CADASTRO], colunas) == [("bronze_cadastro", "cd_centro_custo")]


def test_colunas_tecnicas_e_do_delta_nao_sao_coluna_nova():
    # Falso alarme todo dia se a coluna técnica nova (_modificado_em) ou o change data feed
    # contassem como mudança na origem.
    tecnicas = ["_arquivo_origem", "_modificado_em", "_rescued_data", "_change_type", "_commit_version"]
    colunas = {"bronze_cadastro": [*COLUNAS_BRONZE_CADASTRO, *tecnicas]}
    assert colunas_novas_na_origem([CADASTRO], colunas) == []
    csv = cadastro(tipo="arquivo", arquivo={"formato": "csv", "caminho": "cadastro"})
    assert colunas_novas_na_origem([csv], {"bronze_cadastro": [*COLUNAS_BRONZE_CADASTRO, "x"]}) == [
        ("bronze_cadastro", "x")
    ]


def estrutura(fontes: list[dict], colunas: dict) -> str:
    schemas = ("portfolio_monitoramento", "portfolio_bronze", "portfolio_silver")
    return sql_estrutura("essentials", *schemas, fontes, colunas)


def test_coluna_nova_vira_aviso_em_mon_estrutura():
    sql = estrutura([CADASTRO], {"bronze_cadastro": [*COLUNAS_BRONZE_CADASTRO, "cd_centro_custo"]})
    assert "SELECT 'bronze_cadastro' AS nm_tabela, 'coluna_nova' AS ds_tipo, 'cd_centro_custo' AS nm_coluna" in sql


def test_estrutura_conta_dado_resgatado_e_e_valida_sem_aviso():
    colunas = {"bronze_cadastro": [*COLUNAS_BRONZE_CADASTRO, "_rescued_data"]}
    sql = estrutura([CADASTRO], colunas)
    assert "'dado_resgatado' AS ds_tipo" in sql and "WHERE _rescued_data IS NOT NULL" in sql
    assert "FROM `essentials`.`portfolio_bronze`.`bronze_cadastro`" in sql
    vazia = estrutura(FONTES, {})
    assert vazia.rstrip().endswith("WHERE false")


COLUNAS_BRONZE_EVENTOS = {"bronze_eventos": ["value", "_fonte", "_arquivo_origem", "_modificado_em", "_ingerido_em"]}


def partes_da_estrutura(sql: str) -> list[str]:
    return sql.split("\nAS\n", 1)[1].split("\nUNION ALL\n")


def parte_do_tipo(sql: str, tipo: str) -> str:
    return next(parte for parte in partes_da_estrutura(sql) if f"'{tipo}' AS ds_tipo" in parte)


RETRATO_DOS_EVENTOS = (
    "(SELECT DISTINCT _arquivo_origem FROM `essentials`.`portfolio_silver`.`silver_eventos` WHERE __END_AT IS NULL)"
)


def test_arquivo_ignorado_compara_todos_os_arquivos_da_ultima_carga_com_o_retrato():
    # O retrato é privado do pipeline: os arquivos dele são os das versões vigentes da silver.
    sql = estrutura(FONTES, COLUNAS_BRONZE_EVENTOS)
    parte = parte_do_tipo(sql, "arquivo_ignorado")
    assert parte.startswith("SELECT 'bronze_eventos' AS nm_tabela, 'arquivo_ignorado' AS ds_tipo, ")
    bronze = "`essentials`.`portfolio_bronze`.`bronze_eventos`"
    # Vários arquivos da mesma carga podem cair em micro-batches diferentes: comparar só com o
    # último _ingerido_em esconderia os arquivos dos micro-batches anteriores. Vale o início da
    # atualização (event log) que gravou a ingestão mais recente.
    log = "`essentials`.`portfolio_monitoramento`.`mon_log_eventos`"
    inicio = (
        f"coalesce((SELECT max(u.dh_inicio) FROM (SELECT origin.update_id, min(timestamp) AS dh_inicio FROM {log} "
        "WHERE origin.update_id IS NOT NULL GROUP BY origin.update_id) AS u "
        f"WHERE u.dh_inicio <= (SELECT max(_ingerido_em) FROM {bronze})), (SELECT max(_ingerido_em) FROM {bronze}))"
    )
    assert f"FROM (SELECT DISTINCT _arquivo_origem FROM {bronze} WHERE _ingerido_em >= {inicio}) AS b" in parte
    assert f"LEFT ANTI JOIN {RETRATO_DOS_EVENTOS} AS r ON b._arquivo_origem = r._arquivo_origem" in parte
    assert "silver_int_eventos_retrato" not in sql


def test_retrato_de_snapshot_sem_historico_e_a_propria_silver():
    csv = cadastro(tipo="arquivo", arquivo={"formato": "csv", "caminho": "cadastro"})
    sql = estrutura([csv], {"bronze_cadastro": ["prefixo", "_arquivo_origem", "_ingerido_em"]})
    silver = "`essentials`.`portfolio_silver`.`silver_cadastro`"
    assert f"LEFT ANTI JOIN (SELECT DISTINCT _arquivo_origem FROM {silver}) " in sql


def test_codificacao_invalida_olha_so_o_arquivo_do_retrato_da_fonte_texto():
    sql = estrutura(FONTES, COLUNAS_BRONZE_EVENTOS)
    parte = parte_do_tipo(sql, "codificacao_invalida")
    assert parte.startswith("SELECT DISTINCT 'bronze_eventos' AS nm_tabela, 'codificacao_invalida' AS ds_tipo, ")
    assert f"LEFT SEMI JOIN {RETRATO_DOS_EVENTOS} AS r" in parte
    # Risco: procurar U+FFFD nunca dispara, porque a bronze guarda os bytes cp1252 como chegaram
    # (visto na integração de 2026-11-04). Só a validação do UTF-8 acha o arquivo.
    assert parte.endswith("WHERE NOT is_valid_utf8(b.value)")
    assert "FFFD" not in parte


def test_avisos_de_arquivo_mostram_so_o_nome_do_arquivo():
    # LGPD: nunca o conteúdo (value) nem a pasta da landing, só o nome do arquivo.
    sql = estrutura(FONTES, COLUNAS_BRONZE_EVENTOS)
    for tipo in ("arquivo_ignorado", "codificacao_invalida"):
        selecao = parte_do_tipo(sql, tipo).split(" FROM ", 1)[0]
        assert "element_at(split(b._arquivo_origem, '/'), -1) AS nm_coluna" in selecao, tipo
        assert "value" not in selecao, tipo


def test_avisos_de_arquivo_so_onde_fazem_sentido():
    # Sem a bronze no information_schema, nenhum aviso (a view não pode citar tabela que não existe).
    assert estrutura(FONTES, {}).rstrip().endswith("WHERE false")
    # A fonte tabela não tem arquivo: nenhum dos dois avisos.
    sem_arquivo = estrutura([CADASTRO], {"bronze_cadastro": ["id_item", "_ingerido_em"]})
    assert "arquivo_ignorado" not in sem_arquivo.split("\nAS\n", 1)[1]
    # CSV em snapshot: arquivo ignorado sim; codificação não (o CSV tem a opção encoding).
    csv = {"nome": "metas", "tipo": "arquivo", "modo_carga": "snapshot", "colunas": {"nm_meta": {"origem": "meta"}},
           "arquivo": {"formato": "csv", "caminho": "metas"}}
    consulta = sql_estrutura("c", "m", "b", "s", [csv], {"bronze_metas": ["meta", "_arquivo_origem", "_ingerido_em"]})
    tipos = [parte.split("'")[3] for parte in partes_da_estrutura(consulta)]
    assert tipos == ["arquivo_ignorado"]
    # Texto em modo incremental: sem retrato, a codificação é vista no arquivo da última carga.
    texto = {**csv, "modo_carga": "incremental", "arquivo": {"formato": "texto", "caminho": "metas"}}
    colunas = {"bronze_metas": ["value", "_arquivo_origem", "_ingerido_em"]}
    consulta = sql_estrutura("c", "m", "b", "s", [texto], colunas)
    assert [parte.split("'")[3] for parte in partes_da_estrutura(consulta)] == ["codificacao_invalida"]
    assert "LEFT SEMI JOIN (SELECT DISTINCT _arquivo_origem FROM `c`.`b`.`bronze_metas` WHERE _ingerido_em" in consulta


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
    config = config_ficticia()
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
        "Flow 'silver_int_eventos_retrato' failed to meet the expectation. "
        "Violated expectations: 'data_recente'.\n"
        'Input record: {"nm_pessoa":"Maria Exemplo","nr_contato":"(41) 99999-0000"}'
    )
    motivo = motivo_seguro(mensagem)
    assert motivo == "Regra de qualidade que para a carga foi violada: data_recente. Confira o arquivo enviado."
    assert "Maria" not in motivo and "9999" not in motivo


@pytest.mark.parametrize(
    "mensagem",
    [
        'Erro ao ler a origem: {"nm_pessoa": "Maria Exemplo"}',
        "Falha na tarefa [nr_contato=(41) 99999-0000]",
        "Problem with record Maria Exemplo",
    ],
)
def test_motivo_corta_qualquer_trecho_que_pareca_registro(mensagem):
    motivo = motivo_seguro(mensagem)
    assert "Maria" not in motivo and "9999" not in motivo


def test_motivo_tem_tamanho_limitado_e_nunca_repassa_texto_livre():
    assert len(motivo_seguro("Erro " + "x" * 1000 + "Error")) <= TAMANHO_MAXIMO_MOTIVO
    assert motivo_seguro(None) == MOTIVO_SEM_CLASSE
    # Lista de permissões: a primeira linha do erro não passa mais (pode ser um nome).
    assert motivo_seguro("Erro na primeira linha\nsegunda linha com detalhe") == MOTIVO_SEM_CLASSE


def test_aviso_de_falha_do_job_vai_tambem_para_o_suporte():
    job = carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]["essentials_carga_diaria"]
    assert "${var.email_suporte}" in job["email_notifications"]["on_failure"]


# 7.5 e 7.6 Execuções e teto de custo ---------------------------------------------------------


def test_taxa_de_sucesso_vem_das_execucoes_do_job():
    sql = sql_execucoes("essentials", "portfolio", "123")
    assert "FROM system.lakeflow.job_run_timeline" in sql and "WHERE job_id = '123'" in sql
    assert "AS pc_sucesso" in sql


def test_custo_mensal_compara_com_o_teto():
    sql = sql_custo_mensal("essentials", "portfolio", 150, 5.4)
    assert "FROM `essentials`.`portfolio`.`mon_custo_diario`" in sql
    assert "CAST(150.0 AS DOUBLE) AS vl_teto" in sql and "AS pc_do_teto" in sql


def test_log_e_view_de_falhas_existem_antes_do_pipeline_e_as_views_depois():
    # O alerta lê mon_falhas mesmo antes da primeira falha: a view nasce na preparação.
    preparar = (RAIZ / "src" / "governanca" / "governanca.py").read_text(encoding="utf-8")
    for funcao in ("sql_funcao_mascara(", "sql_criar_tabela_log(", "sql_view_falhas("):
        assert funcao in preparar, funcao
    publicar = (RAIZ / "src" / "governanca" / "publicar_monitoramento.py").read_text(encoding="utf-8")
    for funcao in ("sql_volume(", "sql_estrutura(", "sql_execucoes(", "sql_custo_mensal(", "sql_merge_tabelas("):
        assert funcao in publicar, funcao
    parametros = tarefas()["publicar_monitoramento"]["spark_python_task"]["parameters"]
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
            if alvo == "dev" and nome == "falha_carga":
                # Ativo em dev, para o e-mail de falha com o motivo ser conferido (test_log.py).
                continue
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
