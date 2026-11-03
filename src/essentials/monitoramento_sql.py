"""SQL das views de monitoramento mon_* (docs/adr/0003).

Funções puras, sem Spark, para serem testadas pelo pytest. Quem executa é
src/governanca/governanca.py, na tarefa governanca_depois do job, depois do pipeline:
o event log (mon_log_eventos) só existe depois da primeira atualização do pipeline.

  mon_qualidade_diaria  por dia, tabela e regra: linhas aprovadas, descartadas e alertas
  mon_atualizacao       última atualização do pipeline e última ingestão de cada silver
  mon_custo_diario      DBUs e custo de lista do job e do pipeline, por dia e produto
"""

from __future__ import annotations

from essentials.config_fontes import literal_sql, tabelas_da_fonte
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
    """(tabela, regra, ação) de todas as regras do fontes.yml; a ação vem do YAML."""
    return [
        (tabela_das_regras(fonte, regra), regra["nome"], regra["acao"])
        for fonte in fontes
        for regra in fonte.get("regras", [])
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
SELECT u.dt_execucao, u.id_atualizacao, u.nm_tabela, u.nm_regra, coalesce(r.ds_acao, 'desconhecida') AS ds_acao,
  u.qt_aprovadas,
  CASE WHEN r.ds_acao = 'drop' THEN u.qt_reprovadas ELSE 0 END AS qt_descartadas,
  CASE WHEN r.ds_acao = 'drop' THEN 0 ELSE u.qt_reprovadas END AS qt_alertas
FROM ultima_do_dia u
LEFT JOIN regras r ON r.nm_tabela = u.nm_tabela AND r.nm_regra = u.nm_regra
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


def sql_atualizacao(catalogo: str, schema: str, fontes: list[dict], limite_horas: int) -> str:
    ingestoes = "\n  UNION ALL\n  ".join(
        f"SELECT {literal_sql(tabelas_da_fonte(fonte)['silver'])} AS nm_tabela, max(_ingerido_em) AS dh_ultima_ingestao"
        f" FROM {nome_completo(catalogo, schema, tabelas_da_fonte(fonte)['silver'])}"
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


COLUNAS_CUSTO = {
    "dt_uso": "Dia do consumo.",
    "nm_recurso": "Recurso do projeto que consumiu: job (tarefas Python) ou pipeline.",
    "ds_produto": "Produto de faturamento da Databricks (JOBS, DLT...).",
    "qt_dbus": "Consumo em DBUs no dia.",
    "vl_custo_lista": "Custo estimado pelo preço de lista (sem descontos do contrato).",
    "sg_moeda": "Moeda do preço de lista.",
}


def sql_custo_diario(catalogo: str, schema: str, job_id: str, pipeline_id: str) -> str:
    """Custo do projeto pelas tabelas de sistema, filtrando pelos IDs do job e do pipeline.

    Os IDs funcionam em qualquer workspace; as tags (projeto, cliente, ambiente) só chegam ao
    faturamento serverless do job, não ao do pipeline (conferido no Free Edition).
    """
    job, pipeline = literal_sql(job_id), literal_sql(pipeline_id)
    consulta = f"""SELECT u.usage_date AS dt_uso,
  CASE WHEN u.usage_metadata.job_id = {job} THEN 'job' ELSE 'pipeline' END AS nm_recurso,
  u.billing_origin_product AS ds_produto,
  sum(u.usage_quantity) AS qt_dbus,
  sum(u.usage_quantity * p.pricing.effective_list.default) AS vl_custo_lista,
  first(p.currency_code) AS sg_moeda
FROM system.billing.usage u
LEFT JOIN system.billing.list_prices p
  ON p.cloud = u.cloud AND p.sku_name = u.sku_name AND p.usage_unit = u.usage_unit
  AND u.usage_start_time >= p.price_start_time
  AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
WHERE u.usage_metadata.job_id = {job} OR u.usage_metadata.dlt_pipeline_id = {pipeline}
GROUP BY ALL"""
    return definicao_view(
        catalogo,
        schema,
        "mon_custo_diario",
        "custo",
        "Custo diário do projeto (job e pipeline) pelas tabelas de sistema de faturamento.",
        COLUNAS_CUSTO,
        consulta,
    )
