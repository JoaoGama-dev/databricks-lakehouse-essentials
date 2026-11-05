"""Testes da observabilidade e dos custos (Fase 4).

Conferem a configuração do bundle (event log, health, alerta, tags, ingestão condicional)
e o SQL das views mon_* gerado por src/essentials/monitoramento_sql.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from essentials.config_fontes import PREFIXOS_POR_TIPO, carregar_fontes
from essentials.log_sql import COLUNAS_FALHAS, LOG, TABELA_FALHAS
from essentials.monitoramento_sql import (
    AMBIENTE_TOTAL,
    EVENT_LOG,
    SUFIXO_CI,
    booleano_da_variavel,
    projetos_do_custo,
    regras_monitoradas,
    sql_atualizacao,
    sql_custo_diario,
    sql_custo_mensal,
    sql_custo_por_carga,
    sql_estrutura,
    sql_execucoes,
    sql_qualidade_diaria,
    sql_volume,
)
from fontes_ficticias import CADASTRO

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


COLUNAS_BRONZE_EXEMPLO = {"bronze_agenda": ["value", "_fonte", "_arquivo_origem", "_modificado_em", "_ingerido_em"]}
MON = "portfolio_monitoramento"
# Atribuição do custo no dev, com o warehouse compartilhado (o padrão do bundle).
ATRIBUICAO_DEV = ("portfolio", "dev", False, "wh-compartilhado")


def views() -> dict[str, str]:
    return {
        "mon_qualidade_diaria": sql_qualidade_diaria("essentials", MON, FONTES),
        "mon_atualizacao": sql_atualizacao("essentials", MON, "portfolio_silver", FONTES, 26),
        "mon_custo_diario": sql_custo_diario("essentials", MON, *ATRIBUICAO_DEV),
        "mon_custo_por_carga": sql_custo_por_carga("essentials", MON, *ATRIBUICAO_DEV),
        "mon_volume": sql_volume("essentials", MON, FONTES, 50),
        "mon_estrutura": sql_estrutura(
            "essentials", MON, "portfolio_bronze", "portfolio_silver", FONTES, COLUNAS_BRONZE_EXEMPLO
        ),
        "mon_execucoes": sql_execucoes("essentials", MON, "123"),
        "mon_custo_mensal": sql_custo_mensal("essentials", MON, 150),
    }


# 4.1 Event log --------------------------------------------------------------------


def test_event_log_publicado_no_schema_de_monitoramento():
    pipeline = carregar_yaml(RAIZ / "resources" / "pipeline.yml")["resources"]["pipelines"]["essentials_pipeline"]
    assert pipeline["event_log"] == {
        "catalog": "${resources.schemas.monitoramento.catalog_name}",
        "schema": "${resources.schemas.monitoramento.name}",
        "name": EVENT_LOG,
    }


# 4.2 e 4.3 Views de monitoramento -------------------------------------------------


def colunas_da_view(sql: str) -> list[str]:
    lista = sql.split("(\n", 1)[1].split("\n)\n", 1)[0]
    return re.findall(r"`(\w+)` COMMENT '", lista)


def test_views_seguem_o_padrao_de_nomes_e_o_dicionario():
    prefixos = "|".join(PREFIXOS_POR_TIPO)
    for nome, sql in views().items():
        assert sql.startswith(f"CREATE OR REPLACE VIEW `essentials`.`{MON}`.`{nome}` (")
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
    assert f"FROM `essentials`.`{MON}`.`mon_log_eventos`" in sql
    assert "event_type = 'flow_progress'" in sql
    assert "details:flow_progress:data_quality:expectations" in sql


def test_historico_so_mostra_tabelas_e_regras_do_fontes_yml_atual():
    # O event log guarda o histórico do pipeline inteiro: sem o JOIN interno, regras e tabelas
    # que já saíram do fontes.yml voltam ao painel (no dev: silver_int_cargos_retrato com ação
    # 'desconhecida').
    qualidade = views()["mon_qualidade_diaria"]
    assert "\nJOIN regras r ON r.nm_tabela = u.nm_tabela AND r.nm_regra = u.nm_regra" in qualidade
    assert "LEFT JOIN regras" not in qualidade and "desconhecida" not in qualidade
    volume = views()["mon_volume"]
    assert "FROM cargas c JOIN modos m ON m.nm_tabela = c.nm_tabela" in volume


def test_toda_regra_do_fontes_yml_tem_tabela_e_acao():
    regras = regras_monitoradas(FONTES)
    assert len(regras) == sum(len(fonte.get("regras", [])) for fonte in FONTES)
    # O retrato é privado, mas as expectations dele seguem no event log com o nome da tabela.
    assert ("silver_int_agenda_retrato", "nome_preenchido", "drop") in regras
    assert ("silver_int_agenda_retrato", "telefone_valido", "alerta") in regras
    assert ("silver_int_agenda_retrato", "data_plausivel", "falhar") in regras
    sql = views()["mon_qualidade_diaria"]
    assert all(f"('{tabela}', '{regra}', '{acao}')" in sql for tabela, regra, acao in regras)


def test_regra_unico_e_monitorada_na_tabela_da_checagem():
    regras = regras_monitoradas([CADASTRO])
    assert ("silver_int_cadastro_unico_ds_prefixo", "prefixo_unico", "alerta") in regras


def test_regra_de_incremental_fica_na_propria_silver():
    fonte = {"nome": "vendas", "modo_carga": "incremental", "regras": [
        {"nome": "valor_preenchido", "tipo": "nao_nulo", "coluna": "vl_venda", "acao": "drop"}]}
    assert regras_monitoradas([fonte]) == [("silver_vendas", "valor_preenchido", "drop")]


def test_atualizacao_usa_o_pipeline_e_a_ingestao_de_cada_silver():
    sql = views()["mon_atualizacao"]
    assert "details:update_progress:state = 'COMPLETED'" in sql
    for fonte in FONTES:
        silver = f"`essentials`.`portfolio_silver`.`silver_{fonte['nome']}`"
        assert f"max(_ingerido_em) AS dh_ultima_ingestao FROM {silver}" in sql
    assert "coalesce(qt_horas_sem_atualizacao > 26, true) AS fl_atrasada" in sql


def projetos_no_filtro(sql: str) -> set[str]:
    """Valores aceitos da tag projeto no filtro do uso (o IN depois do coalesce das tags)."""
    lista = re.search(r"pl\.tags\['projeto'\]\) IN \(([^)]*)\)", sql)
    assert lista, "filtro pela tag projeto não encontrado"
    return set(re.findall(r"'([^']*)'", lista.group(1)))


@pytest.mark.parametrize(
    ("projeto", "ambiente"), [("portfolio", "dev"), ("portfolio_ci", "ci"), ("portfolio", "prod")]
)
def test_custo_cobre_dev_ci_e_prod_do_projeto_em_qualquer_target(projeto, ambiente):
    # Publicada no dev, no ci ou no prod, a view atribui ao projeto o custo dos três ambientes
    # (o ci roda com var.projeto já com o sufixo).
    for sql in (
        sql_custo_diario("essentials", MON, projeto, ambiente, False, "wh"),
        sql_custo_por_carga("essentials", MON, projeto, ambiente, False, "wh"),
    ):
        assert projetos_no_filtro(sql) == {"portfolio", "portfolio_ci"}


def test_sufixo_do_ci_e_o_mesmo_do_target_ci():
    # Se o target ci mudar o sufixo, o custo do ci sairia da view sem erro nenhum.
    projeto = bundle()["variables"]["projeto"]["default"]
    assert bundle()["targets"]["ci"]["variables"]["projeto"] == f"{projeto}{SUFIXO_CI}"
    assert projetos_do_custo(bundle()["targets"]["ci"]["variables"]["projeto"], "ci") == (
        projeto, f"{projeto}{SUFIXO_CI}"
    )


def test_custo_nao_pega_outro_projeto_com_nome_parecido():
    sql = views()["mon_custo_diario"]
    aceitos = projetos_no_filtro(sql)
    for outro in ("portfolio2", "portfolio_novo", "portfolio_ci_teste", "meu_portfolio", "portfoli"):
        assert outro not in aceitos
    # Comparação exata: nada de prefixo ou padrão.
    assert not re.search(r"\b(LIKE|ILIKE|RLIKE|startswith|regexp)\b", sql, flags=re.IGNORECASE)
    # Um projeto que termina em _ci fora do target ci não perde o sufixo.
    assert projetos_do_custo("vendas_ci", "dev") == ("vendas_ci", "vendas_ci_ci")


def test_custo_usa_as_tags_do_job_e_do_pipeline_quando_o_faturamento_vem_sem():
    # O uso serverless do pipeline vem sem custom_tags, e o do job vinha sem antes das tags
    # entrarem no job: sem a versão atual de jobs e pipelines, esse custo sumiria.
    sql = views()["mon_custo_diario"]
    assert "coalesce(u.custom_tags['projeto'], j.tags['projeto'], pl.tags['projeto']) IN (" in sql
    assert "coalesce(coalesce(u.custom_tags['ambiente'], j.tags['ambiente'], pl.tags['ambiente'])" in sql
    for tabela, chave in (("jobs", "job_id"), ("pipelines", "pipeline_id")):
        assert re.search(
            rf"FROM system\.lakeflow\.{tabela}\s+QUALIFY row_number\(\) OVER \(PARTITION BY workspace_id, {chave} "
            r"ORDER BY change_time DESC\) = 1",
            sql,
        ), tabela
    # O job_id só é único dentro do workspace.
    assert "j.workspace_id = u.workspace_id AND j.job_id = u.usage_metadata.job_id" in sql
    assert "pl.workspace_id = u.workspace_id AND pl.pipeline_id = u.usage_metadata.dlt_pipeline_id" in sql


def test_custo_usa_o_preco_de_lista_vigente_no_uso():
    sql = views()["mon_custo_diario"]
    assert "u.usage_quantity * p.pricing.effective_list.default AS vl_custo_lista" in sql
    assert "AND u.usage_start_time >= p.price_start_time" in sql
    assert "AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)" in sql


def test_warehouse_compartilhado_fica_fora_e_o_comentario_diz():
    sql = views()["mon_custo_diario"]
    assert "warehouse_id = " not in sql
    assert "Fora: o SQL warehouse (compartilhado; warehouse_dedicado: false)" in sql


def test_warehouse_dedicado_entra_no_ambiente_que_publica():
    sql = sql_custo_diario("essentials", MON, "portfolio", "prod", True, "wh-do-projeto")
    assert "OR u.usage_metadata.warehouse_id = 'wh-do-projeto'" in sql
    # Sem tag no faturamento do warehouse: o ambiente é o do target que publica a view.
    assert "CASE WHEN u.usage_metadata.warehouse_id = 'wh-do-projeto' THEN 'prod' ELSE" in sql
    assert "Inclui o warehouse dedicado do projeto" in sql
    # O projeto continua filtrado pela tag: o warehouse não abre a porta para outros projetos.
    assert projetos_no_filtro(sql) == {"portfolio", "portfolio_ci"}


@pytest.mark.parametrize(("valor", "esperado"), [("true", True), ("false", False), ("True", True), (" false ", False)])
def test_warehouse_dedicado_aceita_true_e_false(valor, esperado):
    assert booleano_da_variavel(valor) is esperado


@pytest.mark.parametrize("valor", ["", "sim", "1", "${var.warehouse_dedicado}"])
def test_warehouse_dedicado_invalido_e_erro_e_nao_false(valor):
    with pytest.raises(ValueError):
        booleano_da_variavel(valor)


def test_variavel_warehouse_dedicado_comeca_desligada():
    padrao = bundle()["variables"]["warehouse_dedicado"]["default"]
    assert booleano_da_variavel(padrao) is False


def test_views_sao_criadas_depois_do_pipeline_com_os_parametros():
    parametros = tarefas()["publicar_monitoramento"]["spark_python_task"]["parameters"]
    valor = {parametros[i]: parametros[i + 1] for i in range(0, len(parametros), 2)}
    assert "processar_medalhao" in {d["task_key"] for d in tarefas()["publicar_monitoramento"]["depends_on"]}
    assert valor["--job-id"] == "{{job.id}}"
    assert valor["--limite-atraso-horas"] == "${var.limite_atraso_horas}"
    assert valor["--projeto"] == "${var.projeto}"
    assert valor["--ambiente"] == "${bundle.target}"
    assert valor["--warehouse-id"] == "${var.warehouse_id}"
    assert valor["--warehouse-dedicado"] == "${var.warehouse_dedicado}"
    publicar = (RAIZ / "src" / "governanca" / "publicar_monitoramento.py").read_text(encoding="utf-8")
    for funcao in ("sql_custo_diario(", "sql_custo_mensal(", "sql_custo_por_carga("):
        assert funcao in publicar, funcao


# Custo do mês e projeção -------------------------------------------------------------


def test_custo_mensal_tem_cada_ambiente_e_o_total():
    sql = views()["mon_custo_mensal"]
    assert "GROUP BY GROUPING SETS ((dt_mes, ds_ambiente), (dt_mes))" in sql
    assert f"CASE WHEN grouping(ds_ambiente) = 1 THEN '{AMBIENTE_TOTAL}' ELSE ds_ambiente END AS ds_ambiente" in sql


def test_projecao_e_a_media_dos_dias_com_uso_vezes_os_dias_do_mes():
    sql = views()["mon_custo_mensal"]
    # Dias distintos: mon_custo_diario tem uma linha por ambiente, recurso e produto; count(*)
    # contaria linhas e a média sairia baixa.
    assert "count(DISTINCT dt_uso) AS qt_dias_com_uso" in sql
    assert "day(last_day(dt_mes)) AS qt_dias_mes" in sql
    assert (
        "CASE WHEN dt_mes = date_trunc('MONTH', current_date())\n"
        "    THEN round(vl_custo_lista / nullif(qt_dias_com_uso, 0) * day(last_day(dt_mes)), 2)\n"
        "    ELSE vl_custo_lista END AS vl_projecao_mes"
    ) in sql
    assert "estimativa a preço de lista" in sql


def test_alerta_de_teto_le_so_a_linha_total_com_colunas_da_view():
    # Com uma linha por ambiente, o alerta sem o filtro avaliaria uma linha qualquer.
    alerta = carregar_yaml(RAIZ / "resources" / "alertas.yml")["resources"]["alerts"]["custo_teto"]
    consulta = alerta["query_text"]
    assert f"ds_ambiente = '{AMBIENTE_TOTAL}'" in consulta
    selecionadas = re.search(r"SELECT (.*?)\n\s*FROM", consulta, flags=re.DOTALL).group(1)
    colunas = {coluna.strip() for coluna in selecionadas.split(",")}
    assert colunas <= set(colunas_da_view(views()["mon_custo_mensal"]))
    assert alerta["evaluation"]["source"]["name"] in colunas


# Custo por carga ---------------------------------------------------------------------


def test_custo_por_carga_soma_todas_as_atualizacoes_disparadas_pela_execucao():
    # Uma execução pode disparar várias atualizações (RETRY_ON_FAILURE): ligar pela atualização
    # gravada no log (uma só) perderia o custo das novas tentativas.
    sql = views()["mon_custo_por_carga"]
    assert "FROM system.lakeflow.pipeline_update_timeline" in sql
    assert "trigger_details.job_task.job_task_run_id AS id_execucao_tarefa" in sql
    assert "run_id AS id_execucao_tarefa, job_run_id AS id_execucao_job" in sql
    assert "FROM system.lakeflow.job_task_run_timeline" in sql
    assert "mon_log_execucao" not in sql
    # O job pelo run da execução (no faturamento, job_run_id é o da execução, não o da tarefa).
    assert "WHERE nm_recurso = 'job' AND id_execucao_job IS NOT NULL" in sql


def test_custo_por_carga_rateia_o_uso_do_pipeline_sem_atualizacao():
    # Parte do uso serverless do pipeline vem por hora, sem dlt_update_id: sem o rateio, o custo
    # do pipeline por carga sairia ~37% menor (medido no dev).
    sql = views()["mon_custo_por_carga"]
    assert "date_trunc('HOUR', dh_inicio_uso) AS dh_hora" in sql
    assert "sum(qt_dbus) OVER (PARTITION BY workspace_id, id_pipeline, dh_hora) AS qt_dbus_hora" in sql
    assert "AND s.dh_hora = a.dh_hora AND s.id_atualizacao IS NULL" in sql
    assert "a.vl_custo + coalesce(s.vl_custo * a.qt_dbus / nullif(a.qt_dbus_hora, 0), 0)" in sql


def test_custo_por_carga_so_das_execucoes_do_projeto_e_marca_a_parcial():
    sql = views()["mon_custo_por_carga"]
    assert "WHERE j.tags['projeto'] IN ('portfolio', 'portfolio_ci')" in sql
    assert "coalesce(e.dh_fim > current_timestamp() - INTERVAL 24 HOURS, true) AS fl_custo_parcial" in sql


# 4.3 Alerta de atraso -------------------------------------------------------------


def test_alerta_de_atraso_le_a_view_e_avisa_por_email():
    alerta = carregar_yaml(RAIZ / "resources" / "alertas.yml")["resources"]["alerts"]["atraso_carga"]
    assert "mon_atualizacao" in alerta["query_text"]
    assert "${resources.schemas.monitoramento.name}" in alerta["query_text"]
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
    assert avisos["on_failure"] == ["${var.alert_email}", "${var.email_suporte}"]
    assert avisos["on_duration_warning_threshold_exceeded"] == ["${var.alert_email}"]


# 4.5 Tags de custo ----------------------------------------------------------------


def test_recursos_tem_tags_de_projeto_cliente_e_ambiente():
    assert bundle()["presets"]["tags"] == {
        "projeto": "${var.projeto}",
        "cliente": "${var.cliente}",
        "ambiente": "${bundle.target}",
    }
    assert "cliente" in bundle()["targets"]["prod"]["variables"]


# 4.6 Ingestão só quando há fonte: tests/test_log.py (variável ingerir_fontes_externas) --------


# 4.7 Painel de saúde --------------------------------------------------------------


def painel_saude() -> dict:
    return json.loads(PAINEL_SAUDE.read_text(encoding="utf-8"))


def test_todos_os_alertas_leem_o_schema_de_monitoramento():
    for nome, alerta in carregar_yaml(RAIZ / "resources" / "alertas.yml")["resources"]["alerts"].items():
        tabelas = re.findall(r"\bFROM\s+(\S+)", alerta["query_text"])
        tabelas = [t for t in tabelas if t != "("]
        prefixo = "${resources.schemas.monitoramento.catalog_name}.${resources.schemas.monitoramento.name}.mon_"
        assert tabelas and all(t.startswith(prefixo) for t in tabelas), (nome, tabelas)


def test_painel_de_saude_le_o_schema_de_monitoramento():
    recurso = carregar_yaml(RAIZ / "resources" / "dashboard.yml")["resources"]["dashboards"]["painel_saude"]
    assert (RAIZ / "resources" / recurso["file_path"]).resolve() == PAINEL_SAUDE.resolve()
    assert recurso["dataset_catalog"] == "${resources.schemas.monitoramento.catalog_name}"
    assert recurso["dataset_schema"] == "${resources.schemas.monitoramento.name}"
    assert recurso["embed_credentials"] is False


def test_painel_de_saude_so_le_views_mon_sem_ambiente_fixo():
    for dataset in painel_saude()["datasets"]:
        sql = "".join(dataset["queryLines"])
        tabelas = re.findall(r"\b(?:FROM|JOIN)\s+([\w.]+)", sql, flags=re.IGNORECASE)
        lidas = set(views()) | {TABELA_FALHAS, LOG.nome}
        assert tabelas and all(tabela in lidas for tabela in tabelas), (dataset["name"], tabelas)
        assert "essentials" not in sql and "portfolio" not in sql


def colunas_lidas_pelo_painel() -> dict[str, set[str]]:
    """Colunas de cada view ou tabela que o painel lê."""
    colunas = {nome: set(colunas_da_view(sql)) for nome, sql in views().items()}
    colunas[TABELA_FALHAS] = set(COLUNAS_FALHAS)
    colunas[LOG.nome] = set(LOG.colunas)
    return colunas


def colunas_do_dataset(sql: str) -> tuple[set[str], set[str]]:
    """(colunas que o dataset pode devolver, colunas das views que ele lê) do SQL do dataset."""
    lidas = colunas_lidas_pelo_painel()
    tabelas = re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, flags=re.IGNORECASE)
    das_views = set().union(*(lidas[tabela] for tabela in tabelas))
    calculadas = set(re.findall(r"\bAS\s+(\w+)", sql, flags=re.IGNORECASE))
    return das_views | calculadas, das_views


def test_datasets_do_painel_de_saude_so_citam_colunas_das_views_que_leem():
    # Coluna renomeada ou removida na view quebra o dataset só quando o painel abre.
    prefixos = "|".join(PREFIXOS_POR_TIPO)
    for dataset in painel_saude()["datasets"]:
        sql = "".join(dataset["queryLines"])
        disponiveis, _ = colunas_do_dataset(sql)
        citadas = set(re.findall(rf"\b(?:{prefixos})_\w+\b", sql))
        assert citadas <= disponiveis, (dataset["name"], citadas - disponiveis)


def test_widgets_do_painel_de_saude_usam_colunas_do_proprio_dataset():
    # Campo de outro dataset (ou de uma coluna que saiu da view) deixa o widget em erro.
    datasets = {d["name"]: colunas_do_dataset("".join(d["queryLines"]))[0] for d in painel_saude()["datasets"]}
    for pagina in painel_saude()["pages"]:
        for item in pagina["layout"]:
            widget = item["widget"]
            for consulta in widget.get("queries", []):
                nome = consulta["query"]["datasetName"]
                assert nome in datasets, widget["name"]
                for campo in consulta["query"]["fields"]:
                    usados = set(re.findall(r"`(\w+)`", campo["expression"]))
                    assert usados <= datasets[nome], (widget["name"], usados - datasets[nome])
            nomes_dos_campos = {
                campo["name"] for consulta in widget.get("queries", []) for campo in consulta["query"]["fields"]
            }
            encodings = widget.get("spec", {}).get("encodings", {})
            exibidos = [c["fieldName"] for c in encodings.get("columns", [])]
            exibidos += [e["fieldName"] for e in encodings.values() if isinstance(e, dict) and "fieldName" in e]
            assert set(exibidos) <= nomes_dos_campos, (widget["name"], set(exibidos) - nomes_dos_campos)


def test_painel_de_saude_mostra_o_custo_por_ambiente_projecao_e_carga():
    # O "bundle generate --force" regrava o painel pela tela: confere que o custo continua lá.
    pagina = next(p for p in painel_saude()["pages"] if p["name"] == "saude_plataforma")
    lidos = {
        (consulta["query"]["datasetName"], campo["expression"])
        for item in pagina["layout"]
        for consulta in item["widget"].get("queries", [])
        for campo in consulta["query"]["fields"]
    }
    for esperado in (
        ("ds_custo_mensal", "MAX(`pc_do_teto`)"),
        ("ds_custo_mensal", "MAX(`vl_projecao_mes`)"),
        ("ds_custo_mensal_ambiente", "`ds_ambiente`"),
        ("ds_custo_por_carga", "`vl_custo_medio_carga`"),
        ("ds_custo", "`ds_ambiente_produto`"),
    ):
        assert esperado in lidos, esperado
    datasets = {d["name"]: "".join(d["queryLines"]) for d in painel_saude()["datasets"]}
    # Os contadores leem a linha total; a média por carga, só execuções com o custo completo.
    assert f"ds_ambiente = '{AMBIENTE_TOTAL}'" in datasets["ds_custo_mensal"]
    assert "NOT fl_custo_parcial AND st_execucao = 'SUCCEEDED'" in datasets["ds_custo_por_carga"]
