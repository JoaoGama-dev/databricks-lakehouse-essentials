"""SQL das views de monitoramento mon_* (docs/adr/0003).

Funções puras, sem Spark, para serem testadas pelo pytest. Quem executa é
src/governanca/publicar_monitoramento.py, na tarefa publicar_monitoramento do job, depois
do pipeline: o event log (mon_log_eventos) só existe depois da primeira atualização do
pipeline.

As views e o event log ficam no schema de monitoramento (<projeto>_monitoramento); as views
leem a bronze e a silver nos schemas de cada camada. O log de cada carga (mon_log_execucao)
e a view mon_falhas estão em src/essentials/log_sql.py.

  mon_qualidade_diaria  por dia, tabela e regra do fontes.yml: linhas aprovadas, descartadas e alertas
  mon_atualizacao       última atualização do pipeline e última ingestão de cada silver
  mon_custo_diario      DBUs e custo de lista do projeto (todos os ambientes), por dia, ambiente,
                        recurso e produto
  mon_custo_mensal      custo do mês por ambiente e total, teto e projeção do mês
  mon_custo_por_carga   custo de lista de cada execução do job (job e pipeline)

As views de custo trazem o valor em dólar (preço de lista) e a estimativa em reais (dólar
vezes a variável cotacao_usd_brl), porque o cliente no Brasil é faturado em reais.
"""

from __future__ import annotations

import math
import re

from essentials.config_fontes import (
    COLUNAS_CDF,
    COLUNAS_TECNICAS,
    filtro_versao_atual,
    literal_sql,
    regras_efetivas,
    tabelas_da_fonte,
)
from essentials.governanca_sql import nome_completo

EVENT_LOG = "mon_log_eventos"
CAMADA = "monitoramento"

# Esquema das expectations no event log (details:flow_progress:data_quality:expectations).
ESQUEMA_EXPECTATIONS = (
    "array<struct<name: string, dataset: string, passed_records: bigint, failed_records: bigint>>"
)


def definicao_view(
    catalogo: str, schema: str, nome: str, tipo: str, comentario: str, colunas: dict[str, str], consulta: str
) -> str:
    """CREATE OR REPLACE VIEW com COMMENT em cada coluna e TBLPROPERTIES (camada, tipo)."""
    lista = ",\n  ".join(f"`{coluna}` COMMENT {literal_sql(texto)}" for coluna, texto in colunas.items())
    return (
        f"CREATE OR REPLACE VIEW {nome_completo(catalogo, schema, nome)} (\n  {lista}\n)\n"
        f"COMMENT {literal_sql(comentario)}\n"
        f"TBLPROPERTIES ('camada' = '{CAMADA}', 'tipo' = '{tipo}')\n"
        f"AS\n{consulta}"
    )


def tabela_das_regras(fonte: dict, regra: dict) -> str:
    """Tabela em que a regra vira expectation (onde ela aparece no event log)."""
    tabelas = tabelas_da_fonte(fonte)
    if regra["tipo"] == "unico":
        return f"silver_int_{fonte['nome']}_unico_{'_'.join(regra['colunas'])}"
    return tabelas["validada"] or tabelas["silver"]


def regras_monitoradas(fontes: list[dict]) -> list[tuple[str, str, str]]:
    """(tabela, regra, ação) das regras efetivas (as do YAML e as padrão da chave)."""
    return [
        (tabela_das_regras(fonte, regra), regra["nome"], regra["acao"])
        for fonte in fontes
        for regra in regras_efetivas(fonte)
    ]


COLUNAS_QUALIDADE = {
    "dt_execucao": "Dia da atualização do pipeline (a última do dia, quando houver mais de uma).",
    "id_atualizacao": "Identificador da atualização do pipeline no event log.",
    "nm_tabela": "Tabela em que a regra de qualidade é verificada.",
    "nm_regra": "Nome da regra no config/fontes.yml (aba Data quality do pipeline).",
    "ds_acao": "Ação da regra no config/fontes.yml: drop descarta a linha; alerta só conta.",
    "qt_aprovadas": "Linhas que passaram na regra.",
    "qt_descartadas": "Linhas descartadas pela regra (só em regras com drop).",
    "qt_alertas": "Linhas que violaram a regra e seguiram (regras com alerta).",
}


def sql_qualidade_diaria(catalogo: str, schema: str, fontes: list[dict]) -> str:
    regras = ",\n    ".join(
        f"({literal_sql(tabela)}, {literal_sql(regra)}, {literal_sql(acao)})"
        for tabela, regra, acao in regras_monitoradas(fontes)
    )
    log = nome_completo(catalogo, schema, EVENT_LOG)
    consulta = f"""WITH regras (nm_tabela, nm_regra, ds_acao) AS (
  VALUES
    {regras}
),
expectativas AS (
  SELECT timestamp AS dh_evento, origin.update_id AS id_atualizacao,
    explode(from_json(details:flow_progress:data_quality:expectations, '{ESQUEMA_EXPECTATIONS}')) AS regra
  FROM {log}
  WHERE event_type = 'flow_progress' AND details:flow_progress:data_quality:expectations IS NOT NULL
),
por_atualizacao AS (
  SELECT id_atualizacao, max(dh_evento) AS dh_fim,
    element_at(split(replace(regra.dataset, '`', ''), '[.]'), -1) AS nm_tabela, regra.name AS nm_regra,
    sum(regra.passed_records) AS qt_aprovadas, sum(regra.failed_records) AS qt_reprovadas
  FROM expectativas
  GROUP BY id_atualizacao, regra.dataset, regra.name
),
ultima_do_dia AS (
  SELECT *, to_date(dh_fim) AS dt_execucao,
    row_number() OVER (PARTITION BY to_date(dh_fim), nm_tabela, nm_regra ORDER BY dh_fim DESC) AS nr_ordem
  FROM por_atualizacao
)
SELECT u.dt_execucao, u.id_atualizacao, u.nm_tabela, u.nm_regra, r.ds_acao,
  u.qt_aprovadas,
  CASE WHEN r.ds_acao = 'drop' THEN u.qt_reprovadas ELSE 0 END AS qt_descartadas,
  CASE WHEN r.ds_acao = 'drop' THEN 0 ELSE u.qt_reprovadas END AS qt_alertas
FROM ultima_do_dia u
-- Só as regras do fontes.yml atual: as de tabelas e regras que não existem mais (o event log
-- guarda o histórico do pipeline inteiro) não aparecem.
JOIN regras r ON r.nm_tabela = u.nm_tabela AND r.nm_regra = u.nm_regra
WHERE u.nr_ordem = 1"""
    return definicao_view(
        catalogo,
        schema,
        "mon_qualidade_diaria",
        "qualidade",
        "Histórico de qualidade: por dia, tabela e regra, linhas aprovadas, descartadas e alertas.",
        COLUNAS_QUALIDADE,
        consulta,
    )


COLUNAS_ATUALIZACAO = {
    "nm_tabela": "Tabela silver (estado atual) da fonte.",
    "dh_ultima_ingestao": "Quando chegou o dado mais recente da tabela (_ingerido_em); só muda com dado novo.",
    "dh_ultima_atualizacao": "Fim da última atualização do pipeline concluída com sucesso.",
    "qt_horas_sem_atualizacao": "Horas desde a última atualização do pipeline concluída com sucesso.",
    "fl_atrasada": "Verdadeiro quando a última atualização passou do limite de horas (ou nunca houve).",
}


def sql_atualizacao(catalogo: str, schema: str, schema_silver: str, fontes: list[dict], limite_horas: int) -> str:
    ingestoes = "\n  UNION ALL\n  ".join(
        f"SELECT {literal_sql(tabelas_da_fonte(fonte)['silver'])} AS nm_tabela, max(_ingerido_em) AS dh_ultima_ingestao"
        f" FROM {nome_completo(catalogo, schema_silver, tabelas_da_fonte(fonte)['silver'])}"
        for fonte in fontes
    )
    log = nome_completo(catalogo, schema, EVENT_LOG)
    consulta = f"""WITH ultima_atualizacao AS (
  SELECT max(timestamp) AS dh_ultima_atualizacao
  FROM {log}
  WHERE event_type = 'update_progress' AND details:update_progress:state = 'COMPLETED'
),
ingestoes AS (
  {ingestoes}
),
horas AS (
  SELECT i.nm_tabela, i.dh_ultima_ingestao, a.dh_ultima_atualizacao,
    round((unix_timestamp(current_timestamp()) - unix_timestamp(a.dh_ultima_atualizacao)) / 3600, 1)
      AS qt_horas_sem_atualizacao
  FROM ingestoes i CROSS JOIN ultima_atualizacao a
)
SELECT nm_tabela, dh_ultima_ingestao, dh_ultima_atualizacao, qt_horas_sem_atualizacao,
  coalesce(qt_horas_sem_atualizacao > {int(limite_horas)}, true) AS fl_atrasada
FROM horas"""
    return definicao_view(
        catalogo,
        schema,
        "mon_atualizacao",
        "atualizacao",
        f"Atraso da carga: dispara o alerta quando a última atualização passa de {int(limite_horas)} horas.",
        COLUNAS_ATUALIZACAO,
        consulta,
    )


# Custo em reais -----------------------------------------------------------------------------

# Moeda do preço de lista (system.billing.list_prices) que a cotação converte.
MOEDA_DO_PRECO = "USD"
# Número com ponto decimal, sem sinal, expoente, vírgula ou separador de milhar.
FORMATO_COTACAO = re.compile(r"\d+(\.\d+)?")
ESTIMATIVA_EM_REAIS = (
    "Estimativa em reais: preço de lista em USD vezes a cotação da variável cotacao_usd_brl (a mesma para todas "
    "as linhas da view). A fatura do Azure no Brasil vem em reais com a cotação da Microsoft no dia da cobrança e "
    "os descontos do contrato. Vazio quando o preço de lista não é em USD."
)
COMENTARIO_COTACAO = "Cotação USD/BRL usada nas colunas em reais (variável cotacao_usd_brl do bundle)."


def cotacao_da_variavel(valor: str) -> float:
    """Variável cotacao_usd_brl do bundle (ex.: "5.40") como chega no parâmetro da tarefa.

    Só número com ponto e maior que zero: vazio, com vírgula, não resolvido ou zero é erro
    da etapa, nunca um 0 em silêncio (o custo em reais sairia zerado no painel).
    """
    texto = str(valor).strip()
    if not FORMATO_COTACAO.fullmatch(texto) or float(texto) <= 0:
        raise ValueError(
            f"Cotação USD/BRL inválida: esperado número maior que zero com ponto (ex.: 5.40), veio {valor!r}."
        )
    return float(texto)


def literal_cotacao(cotacao: float) -> str:
    """A cotação como literal SQL; zero, negativa, infinita ou NaN é erro, não uma view errada."""
    valor = float(cotacao)
    if not (math.isfinite(valor) and valor > 0):
        raise ValueError(f"Cotação USD/BRL precisa ser um número maior que zero, veio {cotacao!r}.")
    return f"CAST({valor} AS DOUBLE)"


def em_reais(valor_usd: str, cotacao: float, moeda: str = "sg_moeda") -> str:
    """Valor em dólar vezes a cotação; vazio se o preço de lista não estiver em dólar."""
    return f"CASE WHEN {moeda} = '{MOEDA_DO_PRECO}' THEN {valor_usd} * {literal_cotacao(cotacao)} END"


COLUNAS_CUSTO = {
    "dt_uso": "Dia do consumo.",
    "ds_ambiente": "Ambiente do projeto que consumiu (tag ambiente: dev, ci ou prod).",
    "nm_recurso": "Recurso do projeto que consumiu: job (tarefas Python), pipeline ou warehouse (só o dedicado).",
    "ds_produto": "Produto de faturamento da Databricks (JOBS, DLT, SQL...).",
    "qt_dbus": "Consumo em DBUs no dia.",
    "vl_custo_lista": "Custo estimado pelo preço de lista vigente no dia (sem descontos do contrato), em USD.",
    "vl_custo_brl": f"Custo do dia em reais. {ESTIMATIVA_EM_REAIS}",
    "sg_moeda": "Moeda do preço de lista.",
    "vl_cotacao_usd_brl": COMENTARIO_COTACAO,
}

# O target ci usa o projeto do bundle com este sufixo (databricks.yml; um teste confere).
SUFIXO_CI = "_ci"
AMBIENTE_CI = "ci"
# Ambiente de uma linha cujo recurso tem a tag projeto, mas não a tag ambiente.
SEM_AMBIENTE = "sem_tag"

# Versão mais recente de cada job e de cada pipeline: as tags atuais (presets.tags do bundle).
VERSOES_DOS_RECURSOS = """jobs AS (
  SELECT workspace_id, job_id, tags FROM system.lakeflow.jobs
  QUALIFY row_number() OVER (PARTITION BY workspace_id, job_id ORDER BY change_time DESC) = 1
),
pipelines AS (
  SELECT workspace_id, pipeline_id, tags FROM system.lakeflow.pipelines
  QUALIFY row_number() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
)"""


def booleano_da_variavel(valor: str) -> bool:
    """Variável booleana do bundle (warehouse_dedicado) como chega no parâmetro da tarefa.

    Só true ou false: um valor digitado errado não pode virar false em silêncio (o custo do
    warehouse sumiria do painel sem ninguém notar).
    """
    texto = str(valor).strip().lower()
    if texto not in ("true", "false"):
        raise ValueError(f"Esperado true ou false, veio {valor!r}.")
    return texto == "true"


def projetos_do_custo(projeto: str, ambiente: str) -> tuple[str, str]:
    """Valores da tag projeto que são deste projeto: o do bundle e o do target ci.

    No ci, var.projeto já vem com o sufixo (portfolio_ci): o projeto do bundle é ele sem o
    sufixo. A comparação é exata (IN), então outro projeto com o nome parecido (portfolio2,
    portfolio_novo) não entra.
    """
    base = projeto.removesuffix(SUFIXO_CI) if ambiente == AMBIENTE_CI else projeto
    return base, f"{base}{SUFIXO_CI}"


def tag_do_recurso(chave: str) -> str:
    """Tag do uso; sem ela, a da versão atual do job ou do pipeline.

    O faturamento serverless do pipeline não traz custom_tags, e o do job só traz as tags
    depois que elas entraram no job (conferido no Free Edition em 2026-11-05).
    """
    return f"coalesce(u.custom_tags['{chave}'], j.tags['{chave}'], pl.tags['{chave}'])"


def cte_uso_do_projeto(projeto: str, ambiente: str, warehouse_dedicado: bool, warehouse_id: str) -> str:
    """CTEs jobs, pipelines e uso: cada linha de faturamento do projeto, com o custo de lista.

    Entram o job e o pipeline de todos os ambientes do projeto (dev, ci e prod), pela tag
    projeto, inclusive os recriados (o ci ganha IDs novos a cada rodada). O warehouse só
    entra quando é dedicado ao projeto: ele não tem a tag, e o uso dele vai para o ambiente
    que publica a view.
    """
    projetos = ", ".join(literal_sql(nome) for nome in projetos_do_custo(projeto, ambiente))
    do_warehouse = f"u.usage_metadata.warehouse_id = {literal_sql(warehouse_id)}"
    filtro = f"{tag_do_recurso('projeto')} IN ({projetos})"
    ambiente_sql = f"coalesce({tag_do_recurso('ambiente')}, '{SEM_AMBIENTE}')"
    if warehouse_dedicado:
        filtro = f"({filtro})\n    OR {do_warehouse}"
        ambiente_sql = f"CASE WHEN {do_warehouse} THEN {literal_sql(ambiente)} ELSE {ambiente_sql} END"
    return f"""{VERSOES_DOS_RECURSOS},
uso AS (
  SELECT u.usage_date AS dt_uso, u.usage_start_time AS dh_inicio_uso, u.workspace_id,
    {ambiente_sql} AS ds_ambiente,
    CASE
      WHEN u.usage_metadata.dlt_pipeline_id IS NOT NULL THEN 'pipeline'
      WHEN u.usage_metadata.job_id IS NOT NULL THEN 'job'
      WHEN u.usage_metadata.warehouse_id IS NOT NULL THEN 'warehouse'
      ELSE lower(u.billing_origin_product)
    END AS nm_recurso,
    u.billing_origin_product AS ds_produto,
    u.usage_metadata.job_run_id AS id_execucao_job,
    u.usage_metadata.dlt_pipeline_id AS id_pipeline, u.usage_metadata.dlt_update_id AS id_atualizacao,
    u.usage_quantity AS qt_dbus,
    u.usage_quantity * p.pricing.effective_list.default AS vl_custo_lista,
    p.currency_code AS sg_moeda
  FROM system.billing.usage u
  -- Preço de lista vigente quando o uso aconteceu.
  LEFT JOIN system.billing.list_prices p
    ON p.cloud = u.cloud AND p.sku_name = u.sku_name AND p.usage_unit = u.usage_unit
    AND u.usage_start_time >= p.price_start_time
    AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
  LEFT JOIN jobs j ON j.workspace_id = u.workspace_id AND j.job_id = u.usage_metadata.job_id
  LEFT JOIN pipelines pl ON pl.workspace_id = u.workspace_id AND pl.pipeline_id = u.usage_metadata.dlt_pipeline_id
  WHERE {filtro}
)"""


def sql_custo_diario(
    catalogo: str,
    schema: str,
    projeto: str,
    ambiente: str,
    warehouse_dedicado: bool,
    warehouse_id: str,
    cotacao: float,
) -> str:
    """Custo do projeto por dia, ambiente, recurso e produto (tabelas de sistema de faturamento).

    Atribuição pela tag projeto (cte_uso_do_projeto), não pelos IDs do target atual: assim
    entram o dev, o ci e o prod, e os recursos recriados.
    """
    fora = (
        "Inclui o warehouse dedicado do projeto (warehouse_dedicado: true). "
        if warehouse_dedicado
        else "Fora: o SQL warehouse (compartilhado; warehouse_dedicado: false). "
    )
    consulta = f"""WITH {cte_uso_do_projeto(projeto, ambiente, warehouse_dedicado, warehouse_id)},
por_dia AS (
  SELECT dt_uso, ds_ambiente, nm_recurso, ds_produto, sum(qt_dbus) AS qt_dbus, sum(vl_custo_lista) AS vl_custo_lista,
    first(sg_moeda, true) AS sg_moeda
  FROM uso
  GROUP BY dt_uso, ds_ambiente, nm_recurso, ds_produto
)
SELECT dt_uso, ds_ambiente, nm_recurso, ds_produto, qt_dbus, vl_custo_lista,
  {em_reais("vl_custo_lista", cotacao)} AS vl_custo_brl,
  sg_moeda, {literal_cotacao(cotacao)} AS vl_cotacao_usd_brl
FROM por_dia"""
    return definicao_view(
        catalogo,
        schema,
        "mon_custo_diario",
        "custo",
        "Custo diário do projeto em todos os ambientes (dev, ci, prod), pela tag projeto do job e do pipeline, "
        f"a preço de lista, em USD e em reais (pela cotação da variável). {fora}Fora também: armazenamento padrão e "
        "otimização preditiva (sem tag de projeto). "
        "As tabelas de cobrança atrasam algumas horas.",
        COLUNAS_CUSTO,
        consulta,
    )


COLUNAS_CUSTO_POR_CARGA = {
    "dt_execucao": "Dia em que a execução do job começou.",
    "id_execucao_job": "Execução do job da carga diária (run_id).",
    "ds_ambiente": "Ambiente do job (tag ambiente: dev, ci ou prod).",
    "st_execucao": "Resultado da execução em system.lakeflow.job_run_timeline (SUCCEEDED, ERROR...); vazio "
    "enquanto roda.",
    "dh_inicio": "Início da execução do job.",
    "dh_fim": "Fim da execução do job.",
    "qt_atualizacoes_pipeline": "Atualizações do pipeline disparadas pela execução (inclui as novas tentativas).",
    "qt_dbus": "DBUs da execução: tarefas do job e atualizações do pipeline.",
    "vl_custo_job": "Custo de lista das tarefas do job (serverless) da execução, em USD.",
    "vl_custo_job_brl": f"Custo das tarefas do job da execução em reais. {ESTIMATIVA_EM_REAIS}",
    "vl_custo_pipeline": "Custo de lista das atualizações do pipeline da execução, com o rateio do uso cobrado "
    "por hora sem atualização, em USD.",
    "vl_custo_pipeline_brl": f"Custo das atualizações do pipeline da execução em reais. {ESTIMATIVA_EM_REAIS}",
    "vl_custo_lista": "Custo de lista da execução inteira (job e pipeline), em USD.",
    "vl_custo_brl": f"Custo da execução inteira (job e pipeline) em reais. {ESTIMATIVA_EM_REAIS}",
    "sg_moeda": "Moeda do preço de lista.",
    "vl_cotacao_usd_brl": COMENTARIO_COTACAO,
    "fl_custo_parcial": "Verdadeiro quando a execução não terminou ou terminou há menos de 24 horas: a cobrança "
    "atrasa algumas horas e o custo ainda pode subir.",
}

# Horas depois do fim da execução em que o custo dela é dado como completo.
HORAS_ATRASO_COBRANCA = 24


def sql_custo_por_carga(
    catalogo: str,
    schema: str,
    projeto: str,
    ambiente: str,
    warehouse_dedicado: bool,
    warehouse_id: str,
    cotacao: float,
) -> str:
    """Custo de lista de cada execução do job do projeto (todos os ambientes).

    Ligação conferida no Free Edition em 2026-11-05:
      job       usage_metadata.job_run_id é o run_id da execução do job (não o da tarefa);
      pipeline  cada atualização (system.lakeflow.pipeline_update_timeline) traz a tarefa do
                job que a disparou (trigger_details.job_task.job_task_run_id), e a tarefa traz a
                execução (system.lakeflow.job_task_run_timeline.job_run_id). Uma execução pode
                disparar várias atualizações (RETRY_ON_FAILURE): todas entram;
      rateio    parte do uso do pipeline serverless vem por hora, sem dlt_update_id (~37% no
                dev). Ele é rateado entre as atualizações do mesmo pipeline e da mesma hora, na
                proporção do uso de cada uma (no dev, toda hora com esse uso tinha atualização).
    O warehouse (alerta e encerrar_com_falha) não entra: o faturamento dele não diz a execução.
    """
    uso = cte_uso_do_projeto(projeto, ambiente, warehouse_dedicado, warehouse_id)
    projetos = ", ".join(literal_sql(nome) for nome in projetos_do_custo(projeto, ambiente))
    consulta = f"""WITH {uso},
execucoes AS (
  SELECT r.workspace_id, r.job_id, r.run_id AS id_execucao_job,
    coalesce(max(j.tags['ambiente']), '{SEM_AMBIENTE}') AS ds_ambiente,
    min(r.period_start_time) AS dh_inicio,
    max(r.period_end_time) FILTER (WHERE r.result_state IS NOT NULL) AS dh_fim,
    max_by(r.result_state, r.period_end_time) FILTER (WHERE r.result_state IS NOT NULL) AS st_execucao
  FROM system.lakeflow.job_run_timeline r
  JOIN jobs j ON j.workspace_id = r.workspace_id AND j.job_id = r.job_id
  WHERE j.tags['projeto'] IN ({projetos})
  GROUP BY r.workspace_id, r.job_id, r.run_id
),
custo_job AS (
  SELECT workspace_id, id_execucao_job, sum(qt_dbus) AS qt_dbus, sum(vl_custo_lista) AS vl_custo
  FROM uso
  WHERE nm_recurso = 'job' AND id_execucao_job IS NOT NULL
  GROUP BY workspace_id, id_execucao_job
),
pipeline_por_hora AS (
  SELECT workspace_id, id_pipeline, id_atualizacao, date_trunc('HOUR', dh_inicio_uso) AS dh_hora,
    sum(qt_dbus) AS qt_dbus, sum(vl_custo_lista) AS vl_custo
  FROM uso
  WHERE nm_recurso = 'pipeline'
  GROUP BY workspace_id, id_pipeline, id_atualizacao, date_trunc('HOUR', dh_inicio_uso)
),
-- Uso da atualização mais a parte dela no uso da mesma hora sem atualização.
pipeline_rateado AS (
  SELECT a.workspace_id, a.id_atualizacao,
    sum(a.qt_dbus + coalesce(s.qt_dbus * a.qt_dbus / nullif(a.qt_dbus_hora, 0), 0)) AS qt_dbus,
    sum(a.vl_custo + coalesce(s.vl_custo * a.qt_dbus / nullif(a.qt_dbus_hora, 0), 0)) AS vl_custo
  FROM (
    SELECT *, sum(qt_dbus) OVER (PARTITION BY workspace_id, id_pipeline, dh_hora) AS qt_dbus_hora
    FROM pipeline_por_hora WHERE id_atualizacao IS NOT NULL
  ) AS a
  LEFT JOIN pipeline_por_hora s ON s.workspace_id = a.workspace_id AND s.id_pipeline = a.id_pipeline
    AND s.dh_hora = a.dh_hora AND s.id_atualizacao IS NULL
  GROUP BY a.workspace_id, a.id_atualizacao
),
atualizacoes AS (
  SELECT DISTINCT workspace_id, update_id AS id_atualizacao, trigger_details.job_task.job_id AS job_id,
    trigger_details.job_task.job_task_run_id AS id_execucao_tarefa
  FROM system.lakeflow.pipeline_update_timeline
  WHERE trigger_details.job_task.job_task_run_id IS NOT NULL
),
tarefas AS (
  SELECT DISTINCT workspace_id, job_id, run_id AS id_execucao_tarefa, job_run_id AS id_execucao_job
  FROM system.lakeflow.job_task_run_timeline
),
custo_pipeline AS (
  SELECT t.workspace_id, t.id_execucao_job, count(DISTINCT a.id_atualizacao) AS qt_atualizacoes,
    sum(pr.qt_dbus) AS qt_dbus, sum(pr.vl_custo) AS vl_custo
  FROM atualizacoes a
  JOIN tarefas t ON t.workspace_id = a.workspace_id AND t.job_id = a.job_id
    AND t.id_execucao_tarefa = a.id_execucao_tarefa
  LEFT JOIN pipeline_rateado pr ON pr.workspace_id = a.workspace_id AND pr.id_atualizacao = a.id_atualizacao
  GROUP BY t.workspace_id, t.id_execucao_job
),
moeda AS (
  SELECT first(sg_moeda, true) AS sg_moeda FROM uso
),
por_execucao AS (
  SELECT to_date(e.dh_inicio) AS dt_execucao, e.id_execucao_job, e.ds_ambiente, e.st_execucao, e.dh_inicio, e.dh_fim,
    coalesce(cp.qt_atualizacoes, 0) AS qt_atualizacoes_pipeline,
    coalesce(cj.qt_dbus, 0) + coalesce(cp.qt_dbus, 0) AS qt_dbus,
    coalesce(cj.vl_custo, 0) AS vl_custo_job, coalesce(cp.vl_custo, 0) AS vl_custo_pipeline,
    coalesce(cj.vl_custo, 0) + coalesce(cp.vl_custo, 0) AS vl_custo_lista,
    m.sg_moeda,
    coalesce(e.dh_fim > current_timestamp() - INTERVAL {HORAS_ATRASO_COBRANCA} HOURS, true) AS fl_custo_parcial
  FROM execucoes e
  CROSS JOIN moeda m
  LEFT JOIN custo_job cj ON cj.workspace_id = e.workspace_id AND cj.id_execucao_job = e.id_execucao_job
  LEFT JOIN custo_pipeline cp ON cp.workspace_id = e.workspace_id AND cp.id_execucao_job = e.id_execucao_job
)
SELECT dt_execucao, id_execucao_job, ds_ambiente, st_execucao, dh_inicio, dh_fim, qt_atualizacoes_pipeline, qt_dbus,
  vl_custo_job, {em_reais("vl_custo_job", cotacao)} AS vl_custo_job_brl,
  vl_custo_pipeline, {em_reais("vl_custo_pipeline", cotacao)} AS vl_custo_pipeline_brl,
  vl_custo_lista, {em_reais("vl_custo_lista", cotacao)} AS vl_custo_brl,
  sg_moeda, {literal_cotacao(cotacao)} AS vl_cotacao_usd_brl, fl_custo_parcial
FROM por_execucao"""
    return definicao_view(
        catalogo,
        schema,
        "mon_custo_por_carga",
        "custo",
        "Custo de lista de cada execução do job do projeto (todos os ambientes): tarefas do job e atualizações do "
        "pipeline que ela disparou. Estimativa a preço de lista, em USD e em reais (pela cotação da variável); sem "
        "o SQL warehouse e o armazenamento. Use as execuções com fl_custo_parcial falso (a cobrança atrasa algumas "
        "horas).",
        COLUNAS_CUSTO_POR_CARGA,
        consulta,
    )


# Fase 7: volume, estrutura da origem, execuções, teto de custo e falhas -----------------

COLUNAS_VOLUME = {
    "nm_tabela": "Tabela em que o volume da carga é medido (retrato, mudanças ou a própria silver).",
    "ds_modo": "Modo de carga da fonte (snapshot, cdc ou incremental).",
    "dh_carga": "Fim da atualização do pipeline que gravou a tabela.",
    "qt_linhas": "Linhas gravadas na atualização (no snapshot, o retrato inteiro).",
    "qt_linhas_anterior": "Linhas gravadas na atualização anterior.",
    "pc_variacao": "Variação percentual em relação à atualização anterior.",
    "fl_alerta": "Verdadeiro quando o retrato veio vazio ou caiu mais que o limite (só no modo snapshot).",
}


def tabela_do_volume(fonte: dict) -> str:
    """Tabela que mede o volume de cada carga: o retrato ou as mudanças; no incremental, a silver."""
    tabelas = tabelas_da_fonte(fonte)
    return tabelas["validada"] or tabelas["silver"]


def sql_volume(catalogo: str, schema: str, fontes: list[dict], limite_queda_pct: int) -> str:
    """Volume de cada carga pelo event log (num_output_rows de cada fluxo concluído).

    Só o modo snapshot gera alerta: o retrato é a fonte inteira, então vir vazio ou cair muito
    indica arquivo errado. No incremental e no cdc, zero linhas novas num dia é normal.
    """
    modos = ",\n    ".join(
        f"({literal_sql(tabela_do_volume(fonte))}, {literal_sql(fonte['modo_carga'])})" for fonte in fontes
    )
    log = nome_completo(catalogo, schema, EVENT_LOG)
    limite = int(limite_queda_pct)
    queda = "(qt_linhas - qt_linhas_anterior) * 100.0 / nullif(qt_linhas_anterior, 0)"
    consulta = f"""WITH modos (nm_tabela, ds_modo) AS (
  SELECT * FROM VALUES
    {modos or "(CAST(NULL AS STRING), CAST(NULL AS STRING))"}
),
cargas AS (
  SELECT element_at(split(origin.flow_name, '[.]'), -1) AS nm_tabela, origin.update_id AS id_atualizacao,
    max(timestamp) AS dh_carga,
    sum(CAST(details:flow_progress:metrics:num_output_rows AS BIGINT)) AS qt_linhas
  FROM {log}
  WHERE event_type = 'flow_progress' AND details:flow_progress:status = 'COMPLETED'
  GROUP BY 1, 2
),
ordenadas AS (
  SELECT c.*, m.ds_modo,
    lag(c.qt_linhas) OVER (PARTITION BY c.nm_tabela ORDER BY c.dh_carga) AS qt_linhas_anterior
  FROM cargas c JOIN modos m ON m.nm_tabela = c.nm_tabela
  WHERE c.qt_linhas IS NOT NULL
)
SELECT nm_tabela, ds_modo, dh_carga, qt_linhas, qt_linhas_anterior, round({queda}, 1) AS pc_variacao,
  ds_modo = 'snapshot' AND (qt_linhas = 0 OR coalesce({queda}, 0) <= -{limite}) AS fl_alerta
FROM ordenadas"""
    return definicao_view(
        catalogo,
        schema,
        "mon_volume",
        "volume",
        f"Volume de cada carga; alerta quando o retrato vem vazio ou cai mais de {limite}%.",
        COLUNAS_VOLUME,
        consulta,
    )


def confere_colunas_da_bronze(fonte: dict) -> bool:
    """Fontes cuja bronze tem as colunas da origem (sem preparação e sem arquivo de texto)."""
    return not fonte.get("preparacao_sql") and fonte.get("arquivo", {}).get("formato") != "texto"


def colunas_esperadas_na_bronze(fonte: dict) -> set[str]:
    """Colunas que a bronze pode ter: as origens do YAML e as técnicas do pipeline e do Delta."""
    origens = {configuracao["origem"] for configuracao in fonte["colunas"].values()}
    return origens | {*COLUNAS_TECNICAS, "_rescued_data", *COLUNAS_CDF}


def colunas_novas_na_origem(fontes: list[dict], colunas_bronze: dict[str, list[str]]) -> list[tuple[str, str]]:
    """(tabela, coluna) de cada coluna da bronze que o fontes.yml não conhece."""
    novas = []
    for fonte in fontes:
        if not confere_colunas_da_bronze(fonte):
            continue
        bronze = tabelas_da_fonte(fonte)["bronze"]
        esperadas = colunas_esperadas_na_bronze(fonte)
        novas += [(bronze, coluna) for coluna in colunas_bronze.get(bronze, []) if coluna not in esperadas]
    return sorted(novas)


COLUNAS_ESTRUTURA = {
    "nm_tabela": "Tabela da bronze onde a mudança na origem apareceu.",
    "ds_tipo": "coluna_nova (a origem ganhou uma coluna), dado_resgatado (linhas com _rescued_data), "
    "arquivo_ignorado (o último arquivo recebido não virou o retrato) ou codificacao_invalida "
    "(o arquivo do retrato não estava em UTF-8).",
    "nm_coluna": "Coluna nova da origem (coluna_nova) ou só o nome do arquivo, sem a pasta (arquivo_ignorado e "
    "codificacao_invalida); vazio quando o tipo é dado_resgatado.",
    "qt_linhas": "Linhas com dado resgatado na última carga; vazio nos outros tipos.",
}

ESTRUTURA_VAZIA = (
    "SELECT CAST(NULL AS STRING) AS nm_tabela, CAST(NULL AS STRING) AS ds_tipo, "
    "CAST(NULL AS STRING) AS nm_coluna, CAST(NULL AS BIGINT) AS qt_linhas WHERE false"
)

# Só o nome do arquivo, sem a pasta da landing; nunca o conteúdo (LGPD).
NOME_DO_ARQUIVO = "element_at(split(b._arquivo_origem, '/'), -1)"
# O formato texto guarda os bytes do arquivo como chegaram: um arquivo em cp1252 fica com
# bytes que não são UTF-8 válido (não viram U+FFFD; nem regex nem instr os acham). Testado no
# Free Edition em 2026-11-04: is_valid_utf8 dá false na agenda v8 (cp1252) e true na v2.
TEM_CARACTERE_INVALIDO = "NOT is_valid_utf8(b.value)"


def arquivos_do_retrato(catalogo: str, schema_bronze: str, schema_silver: str, fonte: dict) -> str:
    """Arquivos que estão no retrato (snapshot) ou, nos outros modos, os da última carga.

    O retrato é privado do pipeline: os arquivos dele são os das versões vigentes da silver
    (no SCD tipo 2, as colunas técnicas da versão vigente são atualizadas no lugar a cada
    retrato; no SCD tipo 1, a silver é o próprio retrato).
    """
    tabelas = tabelas_da_fonte(fonte)
    if fonte["modo_carga"] == "snapshot":
        vigente = filtro_versao_atual(fonte)
        filtro = f" WHERE {vigente}" if vigente else ""
        return (
            f"SELECT DISTINCT _arquivo_origem FROM {nome_completo(catalogo, schema_silver, tabelas['silver'])}{filtro}"
        )
    bronze = nome_completo(catalogo, schema_bronze, tabelas["bronze"])
    return (
        f"SELECT DISTINCT _arquivo_origem FROM {bronze} "
        f"WHERE _ingerido_em >= (SELECT max(_ingerido_em) FROM {bronze})"
    )


def inicio_da_ultima_carga(catalogo: str, schema_monitoramento: str, bronze: str) -> str:
    """Início da atualização do pipeline que gravou a ingestão mais recente da bronze.

    É a atualização mais recente que começou antes do último _ingerido_em. Vários arquivos
    de uma mesma carga podem cair em micro-batches diferentes (com _ingerido_em diferentes),
    mas todos são ingeridos depois do início da atualização. Sem event log, vale o último
    _ingerido_em (só o último micro-batch).
    """
    log = nome_completo(catalogo, schema_monitoramento, EVENT_LOG)
    ultima_ingestao = f"(SELECT max(_ingerido_em) FROM {bronze})"
    return (
        f"coalesce((SELECT max(u.dh_inicio) FROM (SELECT origin.update_id, min(timestamp) AS dh_inicio FROM {log} "
        f"WHERE origin.update_id IS NOT NULL GROUP BY origin.update_id) AS u "
        f"WHERE u.dh_inicio <= {ultima_ingestao}), {ultima_ingestao})"
    )


def sql_arquivo_ignorado(
    catalogo: str, schema_monitoramento: str, schema_bronze: str, schema_silver: str, fonte: dict
) -> str:
    """Aviso para cada arquivo da última carga de um snapshot que não virou o retrato.

    Ele perdeu para um arquivo com data de referência maior (data_referencia), empatou e
    perdeu no desempate, ou não gerou nenhuma linha (ex.: só o cabeçalho). A última carga
    são os arquivos ingeridos desde o início da atualização que os gravou
    (inicio_da_ultima_carga), não só o último micro-batch.
    """
    bronze = tabelas_da_fonte(fonte)["bronze"]
    tabela = nome_completo(catalogo, schema_bronze, bronze)
    retrato = arquivos_do_retrato(catalogo, schema_bronze, schema_silver, fonte)
    inicio = inicio_da_ultima_carga(catalogo, schema_monitoramento, tabela)
    return (
        f"SELECT {literal_sql(bronze)} AS nm_tabela, 'arquivo_ignorado' AS ds_tipo, "
        f"{NOME_DO_ARQUIVO} AS nm_coluna, CAST(NULL AS BIGINT) AS qt_linhas "
        f"FROM (SELECT DISTINCT _arquivo_origem FROM {tabela} WHERE _ingerido_em >= {inicio}) AS b "
        f"LEFT ANTI JOIN ({retrato}) AS r ON b._arquivo_origem = r._arquivo_origem"
    )


def sql_codificacao_invalida(catalogo: str, schema_bronze: str, schema_silver: str, fonte: dict) -> str:
    """Aviso quando o arquivo que virou o retrato (formato texto) não é UTF-8 válido."""
    bronze = tabelas_da_fonte(fonte)["bronze"]
    retrato = arquivos_do_retrato(catalogo, schema_bronze, schema_silver, fonte)
    return (
        f"SELECT DISTINCT {literal_sql(bronze)} AS nm_tabela, 'codificacao_invalida' AS ds_tipo, "
        f"{NOME_DO_ARQUIVO} AS nm_coluna, CAST(NULL AS BIGINT) AS qt_linhas "
        f"FROM {nome_completo(catalogo, schema_bronze, bronze)} AS b "
        f"LEFT SEMI JOIN ({retrato}) AS r ON b._arquivo_origem = r._arquivo_origem "
        f"WHERE {TEM_CARACTERE_INVALIDO}"
    )


def sql_estrutura(
    catalogo: str,
    schema: str,
    schema_bronze: str,
    schema_silver: str,
    fontes: list[dict],
    colunas_bronze: dict[str, list[str]],
) -> str:
    """Mudanças na origem: colunas novas, linhas com _rescued_data, arquivo ignorado e
    codificação inválida. A view fica em schema (monitoramento).

    colunas_bronze: {tabela: [colunas]} da bronze, lido do information_schema quando a view é
    criada (a cada carga). Cada linha da view é um aviso; vazia, está tudo como esperado.
    """
    partes = [
        f"SELECT {literal_sql(tabela)} AS nm_tabela, 'coluna_nova' AS ds_tipo, "
        f"{literal_sql(coluna)} AS nm_coluna, CAST(NULL AS BIGINT) AS qt_linhas"
        for tabela, coluna in colunas_novas_na_origem(fontes, colunas_bronze)
    ]
    for fonte in fontes:
        bronze = tabelas_da_fonte(fonte)["bronze"]
        colunas = colunas_bronze.get(bronze, [])
        if "_rescued_data" in colunas:
            tabela = nome_completo(catalogo, schema_bronze, bronze)
            partes.append(
                f"SELECT {literal_sql(bronze)} AS nm_tabela, 'dado_resgatado' AS ds_tipo, "
                f"CAST(NULL AS STRING) AS nm_coluna, count(*) AS qt_linhas FROM {tabela} "
                f"WHERE _rescued_data IS NOT NULL AND _ingerido_em >= (SELECT max(_ingerido_em) FROM {tabela}) "
                "HAVING count(*) > 0"
            )
        if "_arquivo_origem" not in colunas:
            continue
        if fonte["modo_carga"] == "snapshot":
            partes.append(sql_arquivo_ignorado(catalogo, schema, schema_bronze, schema_silver, fonte))
        if fonte.get("arquivo", {}).get("formato") == "texto" and "value" in colunas:
            partes.append(sql_codificacao_invalida(catalogo, schema_bronze, schema_silver, fonte))
    return definicao_view(
        catalogo,
        schema,
        "mon_estrutura",
        "estrutura",
        "Mudanças na origem (colunas novas, dados resgatados, arquivo ignorado e codificação inválida); "
        "cada linha é um aviso.",
        COLUNAS_ESTRUTURA,
        "\nUNION ALL\n".join(partes) or ESTRUTURA_VAZIA,
    )


COLUNAS_EXECUCOES = {
    "dt_execucao": "Dia em que a execução do job terminou.",
    "qt_execucoes": "Execuções do job concluídas no dia.",
    "qt_sucessos": "Execuções concluídas com sucesso.",
    "qt_falhas": "Execuções que falharam, foram canceladas ou expiraram.",
    "pc_sucesso": "Percentual de execuções com sucesso no dia.",
}


def sql_execucoes(catalogo: str, schema: str, job_id: str) -> str:
    """Taxa de sucesso das cargas, pela tabela de sistema de execuções de jobs."""
    consulta = f"""WITH execucoes AS (
  SELECT run_id, to_date(max(period_end_time)) AS dt_execucao,
    max_by(result_state, period_end_time) AS ds_resultado
  FROM system.lakeflow.job_run_timeline
  WHERE job_id = {literal_sql(job_id)} AND result_state IS NOT NULL
  GROUP BY run_id
)
SELECT dt_execucao, count(*) AS qt_execucoes,
  count_if(ds_resultado = 'SUCCEEDED') AS qt_sucessos,
  count_if(ds_resultado <> 'SUCCEEDED') AS qt_falhas,
  round(count_if(ds_resultado = 'SUCCEEDED') * 100.0 / count(*), 1) AS pc_sucesso
FROM execucoes
GROUP BY dt_execucao"""
    return definicao_view(
        catalogo,
        schema,
        "mon_execucoes",
        "execucoes",
        "Execuções da carga diária por dia: total, sucessos, falhas e taxa de sucesso.",
        COLUNAS_EXECUCOES,
        consulta,
    )


AMBIENTE_TOTAL = "total"

COLUNAS_CUSTO_MENSAL = {
    "dt_mes": "Primeiro dia do mês do consumo.",
    "ds_ambiente": "Ambiente do projeto (dev, ci, prod) ou total (a soma de todos, comparada com o teto).",
    "vl_custo_lista": "Custo do mês até agora pelo preço de lista, em USD (o que mon_custo_diario atribui ao "
    "projeto).",
    "vl_custo_brl": f"Custo do mês até agora em reais. {ESTIMATIVA_EM_REAIS}",
    "qt_dias_com_uso": "Dias do mês com algum consumo.",
    "qt_dias_mes": "Dias do mês.",
    "vl_projecao_mes": "Estimativa a preço de lista do mês inteiro, em USD: custo médio dos dias com uso vezes os "
    "dias do mês (no mês atual); nos meses fechados, o custo do mês. No total, a soma das projeções dos ambientes.",
    "vl_projecao_brl": f"Projeção do mês inteiro (a de vl_projecao_mes) em reais. {ESTIMATIVA_EM_REAIS}",
    "vl_teto": "Teto mensal de custo do Databricks combinado no diagnóstico, em USD de preço de lista (variável "
    "teto_custo_mensal_usd).",
    "vl_teto_brl": "Teto mensal em reais, só como referência: o teto vale em USD (vl_teto e pc_do_teto). Estimativa: "
    "vl_teto vezes a cotação da variável cotacao_usd_brl; a fatura do Azure no Brasil usa a cotação da Microsoft "
    "no dia da cobrança e os descontos do contrato.",
    "pc_do_teto": "Percentual do teto já consumido no mês, calculado em USD (o que o alerta custo_teto avalia).",
    "sg_moeda": "Moeda do preço de lista.",
    "vl_cotacao_usd_brl": COMENTARIO_COTACAO,
}


def sql_custo_mensal(catalogo: str, schema: str, teto: float, cotacao: float) -> str:
    """Custo do mês por ambiente e no total, contra o teto, com a projeção do mês.

    O alerta custo_teto lê a linha total (dispara a partir de 80% do teto). A projeção
    supõe que os próximos dias custam como a média dos dias com uso: é estimativa. O teto e
    o pc_do_teto ficam em USD; as colunas _brl são a estimativa em reais pela cotação.
    """
    custo = nome_completo(catalogo, schema, "mon_custo_diario")
    teto_sql = f"CAST({float(teto)} AS DOUBLE)"
    cotacao_sql = literal_cotacao(cotacao)
    consulta = f"""WITH diario AS (
  SELECT date_trunc('MONTH', dt_uso) AS dt_mes, dt_uso, ds_ambiente, vl_custo_lista, sg_moeda FROM {custo}
),
por_ambiente AS (
  SELECT dt_mes, ds_ambiente, sum(vl_custo_lista) AS vl_custo_lista, count(DISTINCT dt_uso) AS qt_dias_com_uso,
    first(sg_moeda, true) AS sg_moeda
  FROM diario
  GROUP BY dt_mes, ds_ambiente
),
com_projecao AS (
  SELECT *,
    CASE WHEN dt_mes = date_trunc('MONTH', current_date())
      THEN vl_custo_lista / nullif(qt_dias_com_uso, 0) * day(last_day(dt_mes))
      ELSE vl_custo_lista END AS vl_projecao
  FROM por_ambiente
),
dias_do_total AS (
  SELECT dt_mes, count(DISTINCT dt_uso) AS qt_dias_com_uso FROM diario GROUP BY dt_mes
),
-- Cada ambiente usa os próprios dias com uso; o total soma as projeções (ex.: o ci rodando
-- 3 dias e o dev 5 não pode dar um total menor que a projeção do ci sozinho).
por_mes AS (
  SELECT dt_mes, ds_ambiente, vl_custo_lista, qt_dias_com_uso, vl_projecao, sg_moeda FROM com_projecao
  UNION ALL
  SELECT c.dt_mes, '{AMBIENTE_TOTAL}', sum(c.vl_custo_lista), max(t.qt_dias_com_uso), sum(c.vl_projecao),
    first(c.sg_moeda, true)
  FROM com_projecao c JOIN dias_do_total t ON t.dt_mes = c.dt_mes
  GROUP BY c.dt_mes
)
SELECT dt_mes, ds_ambiente, vl_custo_lista, {em_reais("vl_custo_lista", cotacao)} AS vl_custo_brl,
  qt_dias_com_uso, day(last_day(dt_mes)) AS qt_dias_mes,
  round(vl_projecao, 2) AS vl_projecao_mes,
  round({em_reais("vl_projecao", cotacao)}, 2) AS vl_projecao_brl,
  {teto_sql} AS vl_teto,
  round({teto_sql} * {cotacao_sql}, 2) AS vl_teto_brl,
  round(vl_custo_lista * 100.0 / nullif({teto_sql}, 0), 1) AS pc_do_teto,
  sg_moeda, {cotacao_sql} AS vl_cotacao_usd_brl
FROM por_mes"""
    return definicao_view(
        catalogo,
        schema,
        "mon_custo_mensal",
        "custo",
        "Custo do Databricks no mês por ambiente e no total (linha total, a do alerta) contra o teto do diagnóstico, "
        "com a projeção do mês: estimativa a preço de lista, em USD (o teto e o alerta) e em reais (pela cotação "
        "da variável).",
        COLUNAS_CUSTO_MENSAL,
        consulta,
    )


TAMANHO_MAXIMO_MOTIVO = 300
# Lista de permissões: o motivo é só texto montado aqui. Do erro do motor sai no máximo a
# classe (um identificador), os nomes de regra e a etapa; nunca texto livre (LGPD).
MOTIVO_SEM_CLASSE = "Falha sem classe de erro identificada: veja a mensagem completa pelo link da execução."
# Condição de erro do Databricks no começo de uma mensagem ([CAST_INVALID_INPUT],
# [DELTA_X.Y]): no início do texto, de uma linha, depois de ": " ou do "message" do JSON.
CONDICAO_DE_ERRO = re.compile(r'(?:^|\n|\\n|: |"message":")\[([A-Z][A-Z0-9]*(?:[_.][A-Z0-9]+)+)\]')
# Nome de classe de exceção (AnalysisException, ValueError, SparkNumberFormatException),
# sem o pacote: precisa terminar em Exception ou Error e ter algo antes.
CLASSE_DE_EXCECAO = re.compile(r"(?<![\w$])(?:[\w$]+\.)*([A-Z][A-Za-z0-9]+(?:Exception|Error))(?![\w$])")
ETAPA = re.compile(r"[A-Z][A-Z_]{1,60}")
# Classes reais do Spark, do Delta e do Python cabem com folga; um texto maior que passasse pelo
# formato da regex não é uma classe.
TAMANHO_MAXIMO_CLASSE = 60


def classe_do_erro(mensagem: str | None) -> str | None:
    """Classe do erro (condição do Databricks ou nome da exceção), nunca texto livre."""
    texto = mensagem or ""
    for padrao in (CONDICAO_DE_ERRO, CLASSE_DE_EXCECAO):
        achado = padrao.search(texto)
        if achado and len(achado.group(1)) <= TAMANHO_MAXIMO_CLASSE:
            return achado.group(1)
    return None


def regras_violadas(mensagem: str, regras: set[str] | None = None) -> list[str]:
    """Nomes das regras na lista "Violated expectations: 'a', 'b'" (só identificadores).

    Com a lista de regras conhecida (fontes.yml), fica só o que é nome de regra de verdade.
    """
    nomes = set()
    for lista in re.findall(r"Violated expectations?: ((?:'\w+'(?:,\s*)?)+)", mensagem):
        nomes.update(re.findall(r"'(\w+)'", lista))
    if regras is not None:
        nomes &= set(regras)
    return sorted(nomes)


def motivo_seguro(mensagem: str | None, etapa: str | None = None, regras: set[str] | None = None) -> str:
    """Motivo da falha que pode ser gravado e ir por e-mail: só texto nosso (LGPD).

    1. Regra falhar violada: só os nomes das regras.
    2. Outros erros: só a classe do erro (classe_do_erro) e, se conhecida, a etapa da
       atualização do pipeline (um estado, ex.: SETTING_UP_TABLES).
    3. Sem classe identificável: MOTIVO_SEM_CLASSE.
    Nenhuma palavra da mensagem do motor além disso chega ao motivo.
    """
    texto = mensagem or ""
    violadas = regras_violadas(texto, regras)
    if violadas:
        return f"Regra de qualidade que para a carga foi violada: {', '.join(violadas)}. Confira o arquivo enviado."
    classe = classe_do_erro(texto)
    if not classe:
        return MOTIVO_SEM_CLASSE
    na_etapa = f" na etapa {etapa}" if etapa and ETAPA.fullmatch(etapa) else ""
    return f"Erro {classe}{na_etapa}: veja a mensagem completa pelo link da execução."[:TAMANHO_MAXIMO_MOTIVO]
