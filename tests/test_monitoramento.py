"""Testes da observabilidade e dos custos (Fase 4).

Conferem a configuração do bundle (event log, health, alerta, tags, ingestão condicional)
e o SQL das views mon_* gerado por src/essentials/monitoramento_sql.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from essentials.config_fontes import PREFIXOS_POR_TIPO, carregar_fontes
from essentials.monitoramento_sql import (
    EVENT_LOG,
    regras_monitoradas,
    sql_atualizacao,
    sql_custo_diario,
    sql_qualidade_diaria,
)

RAIZ = Path(__file__).resolve().parents[1]
FONTES = carregar_fontes(RAIZ / "config" / "fontes.yml")
PAINEL_SAUDE = RAIZ / "src" / "dashboards" / "saude.lvdash.json"


def carregar_yaml(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def bundle() -> dict:
    return carregar_yaml(RAIZ / "databricks.yml")


def job() -> dict:
    return carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]["essentials_carga_diaria"]


def tarefas() -> dict[str, dict]:
    return {tarefa["task_key"]: tarefa for tarefa in job()["tasks"]}


def views() -> dict[str, str]:
    return {
        "mon_qualidade_diaria": sql_qualidade_diaria("essentials", "portfolio", FONTES),
        "mon_atualizacao": sql_atualizacao("essentials", "portfolio", FONTES, 26),
        "mon_custo_diario": sql_custo_diario("essentials", "portfolio", "123", "abc-def"),
    }


# 4.1 Event log --------------------------------------------------------------------


def test_event_log_publicado_no_schema_do_projeto():
    pipeline = carregar_yaml(RAIZ / "resources" / "pipeline.yml")["resources"]["pipelines"]["essentials_pipeline"]
    assert pipeline["event_log"] == {
        "catalog": "${resources.schemas.projeto.catalog_name}",
        "schema": "${resources.schemas.projeto.name}",
        "name": EVENT_LOG,
    }


# 4.2 e 4.3 Views de monitoramento -------------------------------------------------


def colunas_da_view(sql: str) -> list[str]:
    lista = sql.split("(\n", 1)[1].split("\n)\n", 1)[0]
    return re.findall(r"`(\w+)` COMMENT '", lista)


def test_views_seguem_o_padrao_de_nomes_e_o_dicionario():
    prefixos = "|".join(PREFIXOS_POR_TIPO)
    for nome, sql in views().items():
        assert sql.startswith(f"CREATE OR REPLACE VIEW `essentials`.`portfolio`.`{nome}` (")
        colunas = colunas_da_view(sql)
        assert colunas, nome
        assert all(re.match(rf"^({prefixos})_", coluna) for coluna in colunas), (nome, colunas)
        assert "\nCOMMENT '" in sql
        assert "TBLPROPERTIES ('camada' = 'monitoramento', 'tipo' = '" in sql


def test_select_das_views_devolve_as_colunas_declaradas():
    for nome, sql in views().items():
        selecao_final = sql.rsplit("\nSELECT ", 1)[1]
        for coluna in colunas_da_view(sql):
            assert re.search(rf"\b{coluna}\b", selecao_final), (nome, coluna)


def test_qualidade_le_as_expectations_do_event_log():
    sql = views()["mon_qualidade_diaria"]
    assert "FROM `essentials`.`portfolio`.`mon_log_eventos`" in sql
    assert "event_type = 'flow_progress'" in sql
    assert "details:flow_progress:data_quality:expectations" in sql


def test_toda_regra_do_fontes_yml_tem_tabela_e_acao():
    regras = regras_monitoradas(FONTES)
    assert len(regras) == sum(len(fonte.get("regras", [])) for fonte in FONTES)
    assert ("silver_int_agenda_retrato", "nome_preenchido", "drop") in regras
    assert ("silver_int_agenda_retrato", "telefone_valido", "alerta") in regras
    assert ("silver_int_cargos_unico_ds_prefixo_vaga", "prefixo_unico", "alerta") in regras
    sql = views()["mon_qualidade_diaria"]
    assert all(f"('{tabela}', '{regra}', '{acao}')" in sql for tabela, regra, acao in regras)


def test_regra_de_incremental_fica_na_propria_silver():
    fonte = {"nome": "vendas", "modo_carga": "incremental", "regras": [
        {"nome": "valor_preenchido", "tipo": "nao_nulo", "coluna": "vl_venda", "acao": "drop"}]}
    assert regras_monitoradas([fonte]) == [("silver_vendas", "valor_preenchido", "drop")]


def test_atualizacao_usa_o_pipeline_e_a_ingestao_de_cada_silver():
    sql = views()["mon_atualizacao"]
    assert "details:update_progress:state = 'COMPLETED'" in sql
    for fonte in FONTES:
        assert f"max(_ingerido_em) AS dh_ultima_ingestao FROM `essentials`.`portfolio`.`silver_{fonte['nome']}`" in sql
    assert "coalesce(qt_horas_sem_atualizacao > 26, true) AS fl_atrasada" in sql


def test_custo_filtra_pelos_ids_do_job_e_do_pipeline():
    sql = views()["mon_custo_diario"]
    assert "FROM system.billing.usage u" in sql
    assert "u.usage_metadata.job_id = '123' OR u.usage_metadata.dlt_pipeline_id = 'abc-def'" in sql


def test_views_sao_criadas_depois_do_pipeline_com_os_parametros():
    parametros = tarefas()["governanca_depois"]["spark_python_task"]["parameters"]
    valor = {parametros[i]: parametros[i + 1] for i in range(0, len(parametros), 2)}
    assert valor["--etapa"] == "depois"
    assert valor["--job-id"] == "{{job.id}}"
    assert valor["--pipeline-id"] == "${resources.pipelines.essentials_pipeline.id}"
    assert valor["--limite-atraso-horas"] == "${var.limite_atraso_horas}"


# 4.3 Alerta de atraso -------------------------------------------------------------


def test_alerta_de_atraso_le_a_view_e_avisa_por_email():
    alerta = carregar_yaml(RAIZ / "resources" / "alertas.yml")["resources"]["alerts"]["atraso_carga"]
    assert "mon_atualizacao" in alerta["query_text"]
    assert "${resources.schemas.projeto.name}" in alerta["query_text"]
    avaliacao = alerta["evaluation"]
    assert avaliacao["source"]["name"] in alerta["query_text"]
    assert avaliacao["comparison_operator"] == "GREATER_THAN"
    assert avaliacao["empty_result_state"] == "TRIGGERED"
    # Alert v2 só notifica usuários do workspace: não usa o alert_email do job.
    assert avaliacao["notification"]["subscriptions"] == [{"user_email": "${var.usuario_alerta}"}]
    assert "usuario_alerta" in bundle()["targets"]["prod"]["variables"]
    assert alerta["schedule"]["timezone_id"] == "America/Sao_Paulo"
    assert bundle()["targets"]["dev"]["resources"]["alerts"]["atraso_carga"]["schedule"]["pause_status"] == "PAUSED"


# 4.4 Saúde do job -----------------------------------------------------------------


def test_job_avisa_quando_demora_e_quando_falha():
    assert job()["health"]["rules"] == [
        {"metric": "RUN_DURATION_SECONDS", "op": "GREATER_THAN", "value": "${var.limite_duracao_carga_segundos}"}
    ]
    avisos = job()["email_notifications"]
    assert avisos["on_failure"] == ["${var.alert_email}"]
    assert avisos["on_duration_warning_threshold_exceeded"] == ["${var.alert_email}"]


# 4.5 Tags de custo ----------------------------------------------------------------


def test_recursos_tem_tags_de_projeto_cliente_e_ambiente():
    assert bundle()["presets"]["tags"] == {
        "projeto": "${var.projeto}",
        "cliente": "${var.cliente}",
        "ambiente": "${bundle.target}",
    }
    assert "cliente" in bundle()["targets"]["prod"]["variables"]


# 4.6 Ingestão só quando há fonte --------------------------------------------------


def test_variaveis_de_ingestao_refletem_o_fontes_yml():
    tipos = {fonte["tipo"] for fonte in FONTES}
    variaveis = bundle()["variables"]
    assert variaveis["ingerir_banco"]["default"] == ("true" if "banco" in tipos else "false")
    assert variaveis["ingerir_api"]["default"] == ("true" if "api" in tipos else "false")


def test_ingestao_so_roda_quando_a_condicao_e_verdadeira():
    for tipo in ("banco", "api"):
        condicao = tarefas()[f"tem_fonte_{tipo}"]["condition_task"]
        assert condicao == {"op": "EQUAL_TO", "left": f"${{var.ingerir_{tipo}}}", "right": "true"}
        assert tarefas()[f"ingestao_{tipo}"]["depends_on"] == [{"task_key": f"tem_fonte_{tipo}", "outcome": "true"}]


def test_pipeline_roda_com_as_ingestoes_puladas():
    assert tarefas()["atualizar_lakehouse"]["run_if"] == "NONE_FAILED"


# 4.7 Painel de saúde --------------------------------------------------------------


def painel_saude() -> dict:
    return json.loads(PAINEL_SAUDE.read_text(encoding="utf-8"))


def test_painel_de_saude_le_o_schema_do_projeto():
    recurso = carregar_yaml(RAIZ / "resources" / "dashboard.yml")["resources"]["dashboards"]["painel_saude"]
    assert (RAIZ / "resources" / recurso["file_path"]).resolve() == PAINEL_SAUDE.resolve()
    assert recurso["dataset_catalog"] == "${resources.schemas.projeto.catalog_name}"
    assert recurso["dataset_schema"] == "${resources.schemas.projeto.name}"
    assert recurso["embed_credentials"] is False


def test_painel_de_saude_so_le_views_mon_sem_ambiente_fixo():
    for dataset in painel_saude()["datasets"]:
        sql = "".join(dataset["queryLines"])
        tabelas = re.findall(r"\b(?:FROM|JOIN)\s+([\w.]+)", sql, flags=re.IGNORECASE)
        assert tabelas and all(tabela in views() for tabela in tabelas), (dataset["name"], tabelas)
        assert "essentials" not in sql and "portfolio" not in sql


def test_widgets_do_painel_de_saude_usam_colunas_das_views():
    colunas = {coluna for sql in views().values() for coluna in colunas_da_view(sql)} | {"qt_atrasada"}
    datasets = {d["name"] for d in painel_saude()["datasets"]}
    for pagina in painel_saude()["pages"]:
        for item in pagina["layout"]:
            widget = item["widget"]
            for consulta in widget.get("queries", []):
                assert consulta["query"]["datasetName"] in datasets, widget["name"]
                for campo in consulta["query"]["fields"]:
                    usados = set(re.findall(r"`(\w+)`", campo["expression"]))
                    assert usados <= colunas, (widget["name"], usados - colunas)
