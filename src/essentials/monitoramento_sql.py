"""SQL das views de monitoramento mon_* (docs/adr/0003).

Funções puras, sem Spark, para serem testadas pelo pytest. Quem executa é
src/governanca/publicar_monitoramento.py, na tarefa publicar_monitoramento do job, depois
do pipeline: o event log (mon_log_eventos) só existe depois da primeira atualização do
pipeline.

As views e o event log ficam no schema de monitoramento (<projeto>_monitoramento); as views
leem a bronze e a silver nos schemas de cada camada. O log de cada carga (mon_log_execucao)
e a view mon_falhas estão em src/essentials/log_sql.py.

  mon_qualidade_diaria  por dia, tabela e regra: linhas aprovadas, descartadas e alertas
  mon_atualizacao       última atualização do pipeline e última ingestão de cada silver
  mon_custo_diario      DBUs e custo de lista do job e do pipeline, por dia e produto
"""

from __future__ import annotations

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


COLUNAS_CUSTO_MENSAL = {
    "dt_mes": "Primeiro dia do mês do consumo.",
    "vl_custo_lista": "Custo do mês pelo preço de lista (job e pipeline do projeto).",
    "vl_teto": "Teto mensal de custo do Databricks combinado no diagnóstico (preço de lista).",
    "pc_do_teto": "Percentual do teto já consumido no mês.",
    "sg_moeda": "Moeda do preço de lista.",
}


def sql_custo_mensal(catalogo: str, schema: str, teto: float) -> str:
    """Consumo do mês contra o teto do diagnóstico; o alerta dispara a partir de 80%."""
    custo = nome_completo(catalogo, schema, "mon_custo_diario")
    teto_sql = f"CAST({float(teto)} AS DOUBLE)"
    consulta = f"""SELECT date_trunc('MONTH', dt_uso) AS dt_mes, sum(vl_custo_lista) AS vl_custo_lista,
  {teto_sql} AS vl_teto,
  round(sum(vl_custo_lista) * 100.0 / nullif({teto_sql}, 0), 1) AS pc_do_teto,
  first(sg_moeda) AS sg_moeda
FROM {custo}
GROUP BY 1"""
    return definicao_view(
        catalogo,
        schema,
        "mon_custo_mensal",
        "custo",
        "Custo do Databricks no mês contra o teto do diagnóstico.",
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
TAMANHO_MAXIMO_CLASSE = 120


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
