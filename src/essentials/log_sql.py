"""Log de cada carga diária em mon_log_execucao e a view mon_falhas (docs/adr/0015).

Princípio: o que aconteceu é TABELA Delta com histórico próprio, gravada por MERGE
idempotente pela chave (rodar de novo a mesma execução não duplica nada); o que é
apresentação é VIEW fina sobre ela (mon_falhas, lida pelo alerta falha_carga).

Grão de mon_log_execucao: uma linha por execução do job e nível:
  job     a execução inteira (início, fim, duração e resultado)
  tarefa  cada tarefa do job (a última tentativa), com o motivo seguro quando falhou
  tabela  cada tabela publicada que o pipeline gravou nesta execução (event log)

Funções puras, sem Spark, testadas pelo pytest. Quem executa: governanca.py (cria a tabela
e a view, na tarefa preparar_governanca) e publicar_monitoramento.py (grava o log).

LGPD: o event log pode trazer o registro que violou uma regra nas mensagens de erro. O texto
de message e error só é lido por sql_erros_dos_fluxos e sql_etapa_e_erros_da_atualizacao,
para virar motivo_seguro (lista de permissões) em Python; nunca é gravado como está.
"""

from __future__ import annotations

from typing import NamedTuple

from essentials.config_fontes import literal_sql, tabelas_da_fonte, validada_publicada
from essentials.governanca_sql import nome_completo
from essentials.monitoramento_sql import CAMADA, ESQUEMA_EXPECTATIONS, EVENT_LOG, definicao_view

TABELA_LOG = "mon_log_execucao"
TIPO_LOG = "observabilidade"
TABELA_FALHAS = "mon_falhas"
# Até esta versão, mon_falhas era uma tabela gravada pela tarefa registrar_falha: ela é
# renomeada (não apagada) para a view poder ter o nome.
TABELA_FALHAS_LEGADO = "mon_falhas_legado"
DURACAO = "DECIMAL(18,1)"

# Tarefas do job (resources/job.yml) que o log trata de um jeito especial.
TAREFA_PIPELINE = "processar_medalhao"
TAREFA_PROPRIA = "publicar_monitoramento"
# Falhou por conta própria; UPSTREAM_FAILED é só consequência de outra falha.
ESTADOS_DE_FALHA = ("FAILED", "TIMEDOUT", "CANCELED")
# Estado final de um fluxo do pipeline que gravou a tabela (event log, flow_progress).
FLUXO_CONCLUIDO = "COMPLETED"
ESQUEMA_TECNICAS = "array<struct<maintenance_type: string, is_chosen: boolean>>"


class Tabela(NamedTuple):
    nome: str
    tipo: str
    comentario: str
    colunas: dict[str, tuple[str, str]]
    chave: tuple[str, ...]
    # Colunas da chave que podem ser vazias: comparadas com coalesce(coluna, '').
    chave_anulavel: tuple[str, ...] = ()


LOG = Tabela(
    TABELA_LOG,
    TIPO_LOG,
    "Log da carga diária: uma linha por execução do job e nível (job, tarefa e cada tabela publicada que o "
    "pipeline gravou), com método de carga, técnica de refresh, tempos, linhas e o motivo seguro das falhas. "
    "qt_linhas_alerta é a soma das violações das regras com ação alerta (uma linha que viola duas regras conta "
    "duas vezes). As regras do snapshot rodam no retrato privado do pipeline: os números dele (gravadas, "
    "descartadas, alertas e a técnica) aparecem na linha da silver que ele alimenta. Na linha da tarefa "
    "publicar_monitoramento, o status é o das etapas dela (ela termina com erro de propósito quando outra "
    "tarefa falhou).",
    {
        "id_execucao_job": ("STRING", "Execução do job da carga diária (run_id do job)."),
        "nm_job": ("STRING", "Nome da execução do job (run_name da API de Jobs)."),
        "cd_nivel": ("STRING", "Nível da linha: job (a execução inteira), tarefa ou tabela."),
        "nm_tarefa": (
            "STRING",
            "Tarefa do job (task_key); nas linhas de tabela, a tarefa do pipeline; vazio na linha do job.",
        ),
        "id_atualizacao_pipeline": (
            "STRING",
            "Atualização do pipeline disparada pela tarefa do pipeline nesta execução (event log).",
        ),
        "nm_schema": ("STRING", "Schema da tabela gravada; vazio nas linhas de job e tarefa."),
        "nm_tabela": ("STRING", "Tabela publicada gravada pelo pipeline; vazio nas linhas de job e tarefa."),
        "ds_metodo_carga": (
            "STRING",
            "Como a tabela foi gravada: APPEND (Auto Loader), AUTO CDC FROM SNAPSHOT SCD2 (ou SCD1), AUTO CDC "
            "SCD2 (ou SCD1), MATERIALIZED VIEW, VIEW ou FULL_REFRESH quando a atualização foi um full refresh.",
        ),
        "cd_tecnica_refresh": (
            "STRING",
            "Técnica de refresh escolhida pelo motor para a materialized view (COMPLETE_RECOMPUTE, "
            "WINDOW_FUNCTION, ROW_BASED, GROUP_AGGREGATE, NO_OP...); na silver de snapshot, a do retrato privado.",
        ),
        "dh_ultima_atualizacao_anterior": (
            "TIMESTAMP",
            "Fim da última carga anterior concluída da mesma tabela, por este próprio log; vazio na primeira.",
        ),
        "dh_inicio": ("TIMESTAMP", "Início da execução, da tarefa ou da gravação da tabela."),
        "dh_fim": ("TIMESTAMP", "Fim da execução, da tarefa ou da gravação da tabela."),
        "qt_duracao_segundos": (DURACAO, "Duração em segundos, com uma casa decimal."),
        "ds_duracao": ("STRING", "Duração no formato hh:mm:ss."),
        "st_execucao": (
            "STRING",
            "Resultado: no job e nas tarefas, o da API de Jobs (SUCCESS, FAILED, EXCLUDED, UPSTREAM_FAILED...); "
            "nas tabelas, o último estado do fluxo no event log (COMPLETED, FAILED...).",
        ),
        "qt_linhas_gravadas": (
            "BIGINT",
            "Linhas gravadas pelo fluxo (num_output_rows do event log); na silver de snapshot, as linhas do "
            "retrato que passaram nas regras e seguiram para o AUTO CDC.",
        ),
        "qt_linhas_descartadas": ("BIGINT", "Linhas descartadas pelas regras com ação drop (dropped_records)."),
        "qt_linhas_alerta": (
            "BIGINT",
            "Soma das violações das regras com ação alerta (failed_records); a linha segue para a tabela.",
        ),
        "qt_linhas_tabela": ("BIGINT", "Linhas da tabela logo depois da carga (count(*))."),
        "ds_motivo_falha": (
            "STRING",
            "Motivo da falha montado por motivo_seguro: só nomes de regra, classe do erro e etapa, nunca o registro.",
        ),
        "ds_link_execucao": ("STRING", "Link da execução do job no Databricks."),
        "dh_registro": ("TIMESTAMP", "Quando a linha foi gravada ou regravada neste log."),
    },
    ("id_execucao_job", "cd_nivel", "nm_tarefa", "nm_tabela"),
    chave_anulavel=("nm_tarefa", "nm_tabela"),
)


# Criação ---------------------------------------------------------------------------------


def definicao_coluna(coluna: str, tipo: str, texto: str) -> str:
    return f"`{coluna}` {tipo} COMMENT {literal_sql(texto)}"


def sql_criar_tabela_log(catalogo: str, schema: str) -> str:
    """CREATE TABLE IF NOT EXISTS com COMMENT em cada coluna, CLUSTER BY AUTO e (camada, tipo)."""
    colunas = ",\n  ".join(definicao_coluna(coluna, tipo, texto) for coluna, (tipo, texto) in LOG.colunas.items())
    return (
        f"CREATE TABLE IF NOT EXISTS {nome_completo(catalogo, schema, LOG.nome)} (\n  {colunas}\n)\n"
        "CLUSTER BY AUTO\n"
        f"COMMENT {literal_sql(LOG.comentario)}\n"
        f"TBLPROPERTIES ('camada' = '{CAMADA}', 'tipo' = '{LOG.tipo}')"
    )


COLUNAS_FALHAS = {
    "dh_falha": "Quando a tarefa falhou (fim da tarefa no log da carga).",
    "id_execucao": "Execução do job que falhou.",
    "nm_tarefa": "Tarefa do job que falhou.",
    "ds_motivo": "Motivo da falha, sem dados do registro (só nomes de regra, classe do erro e etapa).",
    "ds_link": "Link da execução no Databricks.",
}


def sql_view_falhas(catalogo: str, schema: str) -> str:
    """mon_falhas: uma linha por tarefa que falhou, com o motivo seguro (alerta falha_carga)."""
    log = nome_completo(catalogo, schema, LOG.nome)
    consulta = f"""SELECT coalesce(dh_fim, dh_registro) AS dh_falha, id_execucao_job AS id_execucao, nm_tarefa,
  ds_motivo_falha AS ds_motivo, ds_link_execucao AS ds_link
FROM {log}
WHERE cd_nivel = 'tarefa' AND ds_motivo_falha IS NOT NULL"""
    return definicao_view(
        catalogo,
        schema,
        TABELA_FALHAS,
        "falha",
        "Falhas da carga diária com o motivo, para o aviso por e-mail e o relatório mensal (lê mon_log_execucao).",
        COLUNAS_FALHAS,
        consulta,
    )


def precisa_renomear_falhas(tipo_objeto: str | None) -> bool:
    """mon_falhas existe como tabela (versão antiga)? Então é renomeada antes de criar a view.

    tipo_objeto: table_type de mon_falhas no information_schema (None se não existe).
    """
    return tipo_objeto is not None and tipo_objeto != "VIEW"


def sql_renomear_falhas_legado(catalogo: str, schema: str) -> str:
    """Guarda as falhas antigas em mon_falhas_legado: nada é apagado."""
    return (
        f"ALTER TABLE {nome_completo(catalogo, schema, TABELA_FALHAS)} "
        f"RENAME TO {nome_completo(catalogo, schema, TABELA_FALHAS_LEGADO)}"
    )


# MERGE genérico --------------------------------------------------------------------------


def _chave(tabela: Tabela, alias: str, coluna: str) -> str:
    return f"coalesce({alias}.{coluna}, '')" if coluna in tabela.chave_anulavel else f"{alias}.{coluna}"


def condicao_da_chave(tabela: Tabela) -> str:
    return " AND ".join(f"{_chave(tabela, 't', c)} = {_chave(tabela, 's', c)}" for c in tabela.chave)


def sql_merge(catalogo: str, schema: str, tabela: Tabela, origem: str) -> str:
    """MERGE pela chave: regrava a linha que já existe (mesma execução de novo) e insere a nova."""
    colunas = list(tabela.colunas)
    atribuicoes = ",\n    ".join(f"{c} = s.{c}" for c in colunas if c not in tabela.chave)
    return (
        f"MERGE INTO {nome_completo(catalogo, schema, tabela.nome)} AS t\n"
        f"USING (\n{origem}\n) AS s\n"
        f"ON {condicao_da_chave(tabela)}\n"
        f"WHEN MATCHED THEN UPDATE SET\n    {atribuicoes}\n"
        f"WHEN NOT MATCHED THEN INSERT ({', '.join(colunas)})\n"
        f"  VALUES ({', '.join(f's.{c}' for c in colunas)})"
    )


def valor_sql(valor, tipo: str) -> str:
    if valor is None:
        return f"CAST(NULL AS {tipo})"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if tipo == "STRING":
        return literal_sql(str(valor))
    return f"CAST({literal_sql(valor)} AS {tipo})"


def relacao(colunas: dict[str, str], linhas: list[tuple]) -> str:
    """SELECT com as linhas informadas (VALUES tipado); sem linhas, uma relação vazia."""
    if not linhas:
        vazias = ", ".join(f"CAST(NULL AS {tipo}) AS {coluna}" for coluna, tipo in colunas.items())
        return f"SELECT {vazias} WHERE false"
    tipos = list(colunas.values())
    valores = ",\n    ".join(
        "(" + ", ".join(valor_sql(valor, tipo) for valor, tipo in zip(linha, tipos, strict=True)) + ")"
        for linha in linhas
    )
    return f"SELECT * FROM VALUES\n    {valores}\n  AS v({', '.join(colunas)})"


def segundos(expressao_ms: str) -> str:
    """Milissegundos para segundos; os parênteses valem para uma subtração (fim - início)."""
    return f"CAST(({expressao_ms}) / 1000.0 AS {DURACAO})"


def texto_duracao(expressao_segundos: str) -> str:
    """Segundos em hh:mm:ss (horas acima de 99 aparecem com mais dígitos); vazio fica vazio."""
    inteiros = f"CAST(floor({expressao_segundos}) AS BIGINT)"
    return (
        f"CASE WHEN {expressao_segundos} IS NULL THEN NULL ELSE format_string('%02d:%02d:%02d', "
        f"{inteiros} DIV 3600, ({inteiros} % 3600) DIV 60, {inteiros} % 60) END"
    )


# Job e tarefas (API de Jobs) -------------------------------------------------------------


def _valor(enum) -> str | None:
    if enum is None:
        return None
    return getattr(enum, "value", enum)


def milissegundos(valor) -> int | None:
    """A API de Jobs usa 0 para o que não aconteceu (tarefa pulada): vira vazio."""
    return int(valor) if valor else None


def resultado_da_tarefa(tarefa) -> str | None:
    """Resultado final da tarefa (SUCCESS, FAILED, EXCLUDED...); None enquanto não termina."""
    return _valor(getattr(getattr(tarefa, "state", None), "result_state", None))


def ultimas_tentativas(tarefas) -> list:
    """Só a tentativa mais recente de cada tarefa (a que vale para o resultado)."""
    ultimas = {}
    for tarefa in sorted(tarefas or [], key=lambda t: getattr(t, "attempt_number", None) or 0):
        ultimas[tarefa.task_key] = tarefa
    return list(ultimas.values())


def tarefas_com_falha(tarefas) -> list:
    """Tarefas que falharam por conta própria, sem a própria publicar_monitoramento."""
    return [
        tarefa
        for tarefa in ultimas_tentativas(tarefas)
        if tarefa.task_key != TAREFA_PROPRIA and resultado_da_tarefa(tarefa) in ESTADOS_DE_FALHA
    ]


def motivo_das_etapas(etapas_com_erro: list[str]) -> str | None:
    """Motivo da própria publicar_monitoramento: só os nomes das etapas (texto nosso)."""
    if not etapas_com_erro:
        return None
    return f"Etapas da publicação do monitoramento com erro: {', '.join(etapas_com_erro)}. Veja o log da tarefa."


def decidir_encerramento(falhas: list[tuple[str, str]], etapas_com_erro: list[str]) -> str | None:
    """Mensagem de falha da carga que a publicar_monitoramento registra no log; None se a carga
    foi bem.

    falhas: (tarefa, motivo seguro) das tarefas que falharam. A tarefa só termina com erro
    quando etapas_com_erro (dela mesma) não está vazia; a falha das outras é avisada pela
    avisar_falha e deixa o job vermelho pela encerrar_com_falha.
    """
    partes = [f"{tarefa}: {motivo}" for tarefa, motivo in falhas]
    if etapas_com_erro:
        partes.append(f"{TAREFA_PROPRIA}: {motivo_das_etapas(etapas_com_erro)}")
    if not partes:
        return None
    return f"A carga diária falhou ({'; '.join(partes)}). Motivo gravado em {TABELA_LOG} e {TABELA_FALHAS}."


COLUNAS_ENTRADA_EXECUCAO = {
    "cd_nivel": "STRING",
    "nm_tarefa": "STRING",
    "id_atualizacao_pipeline": "STRING",
    "nr_ms_inicio": "BIGINT",
    "nr_ms_fim": "BIGINT",
    "st_execucao": "STRING",
    "ds_motivo_falha": "STRING",
}


def linhas_de_execucao(
    execucao,
    motivos: dict[str, str],
    id_atualizacao: str | None,
    agora_ms: int,
    etapas_com_erro: list[str],
) -> list[tuple]:
    """Linhas de job e de tarefa (COLUNAS_ENTRADA_EXECUCAO) de uma execução do SDK.

    Entra a última tentativa de cada tarefa que já terminou. A publicar_monitoramento ainda está
    rodando: termina agora, com o resultado das etapas dela. As tarefas que rodam depois dela
    (avisar_falha) ainda não terminaram e ficam de fora. O job termina agora: FAILED se alguma
    tarefa falhou ou se alguma etapa desta tarefa deu erro.
    motivos: {tarefa: motivo seguro} das tarefas que falharam.
    """
    linhas = []
    for tarefa in ultimas_tentativas(getattr(execucao, "tasks", None)):
        chave = tarefa.task_key
        atualizacao = id_atualizacao if chave == TAREFA_PIPELINE else None
        if chave == TAREFA_PROPRIA:
            resultado = "FAILED" if etapas_com_erro else "SUCCESS"
            linhas.append(
                ("tarefa", chave, None, milissegundos(tarefa.start_time), agora_ms, resultado,
                 motivo_das_etapas(etapas_com_erro))
            )
            continue
        resultado = resultado_da_tarefa(tarefa)
        if resultado is None:
            continue
        motivo = motivos.get(chave) if resultado in ESTADOS_DE_FALHA else None
        linhas.append(
            ("tarefa", chave, atualizacao, milissegundos(tarefa.start_time), milissegundos(tarefa.end_time),
             resultado, motivo)
        )
    falhou = bool(etapas_com_erro) or any(linha[5] in ESTADOS_DE_FALHA for linha in linhas)
    linhas.insert(
        0, ("job", None, id_atualizacao, milissegundos(execucao.start_time), agora_ms,
            "FAILED" if falhou else "SUCCESS", None)
    )
    return linhas


def sql_merge_execucao(
    catalogo: str, schema: str, id_execucao: str, nm_job: str | None, link: str | None, linhas: list[tuple]
) -> str:
    """Upsert das linhas de job e de tarefa da execução."""
    origem = f"""SELECT {valor_sql(str(id_execucao), "STRING")} AS id_execucao_job,
  {valor_sql(nm_job, "STRING")} AS nm_job, e.cd_nivel, e.nm_tarefa, e.id_atualizacao_pipeline,
  CAST(NULL AS STRING) AS nm_schema, CAST(NULL AS STRING) AS nm_tabela, CAST(NULL AS STRING) AS ds_metodo_carga,
  CAST(NULL AS STRING) AS cd_tecnica_refresh, CAST(NULL AS TIMESTAMP) AS dh_ultima_atualizacao_anterior,
  timestamp_millis(e.nr_ms_inicio) AS dh_inicio, timestamp_millis(e.nr_ms_fim) AS dh_fim,
  {segundos("e.nr_ms_fim - e.nr_ms_inicio")} AS qt_duracao_segundos,
  {texto_duracao(segundos("e.nr_ms_fim - e.nr_ms_inicio"))} AS ds_duracao,
  e.st_execucao, CAST(NULL AS BIGINT) AS qt_linhas_gravadas, CAST(NULL AS BIGINT) AS qt_linhas_descartadas,
  CAST(NULL AS BIGINT) AS qt_linhas_alerta, CAST(NULL AS BIGINT) AS qt_linhas_tabela, e.ds_motivo_falha,
  {valor_sql(link, "STRING")} AS ds_link_execucao, current_timestamp() AS dh_registro
FROM ({relacao(COLUNAS_ENTRADA_EXECUCAO, linhas)}) AS e"""
    return sql_merge(catalogo, schema, LOG, origem)


# Tabelas (event log da atualização do pipeline) ------------------------------------------


def tabelas_privadas(fontes: list[dict]) -> list[tuple[str, str]]:
    """(tabela privada do pipeline, tabela publicada que ela alimenta).

    O retrato do snapshot é privado: as regras rodam nele, mas o log mostra os números na
    silver_<fonte>, a tabela que o negócio e a engenharia enxergam no catálogo.
    """
    pares = []
    for fonte in fontes:
        tabelas = tabelas_da_fonte(fonte)
        if tabelas["validada"] and not validada_publicada(fonte):
            pares.append((tabelas["validada"], tabelas["silver"]))
    return pares


def _parte_do_nome(expressao: str, posicao: int) -> str:
    return f"try_element_at(split(replace({expressao}, '`', ''), '[.]'), {posicao})"


def sql_atualizacao_da_tarefa(catalogo: str, schema: str, id_execucao_tarefa: str) -> str:
    """Atualização do pipeline disparada por uma tentativa da tarefa (create_update.job_task.run_id)."""
    log = nome_completo(catalogo, schema, EVENT_LOG)
    return f"""SELECT origin.update_id AS id_atualizacao
FROM {log}
WHERE event_type = 'create_update' AND details:create_update:job_task:run_id = {literal_sql(str(id_execucao_tarefa))}
ORDER BY timestamp DESC
LIMIT 1"""


def sql_saidas_da_atualizacao(catalogo: str, schema: str, id_atualizacao: str) -> str:
    """Tabelas (schema e nome) que os fluxos da atualização gravam, inclusive as privadas e as views."""
    log = nome_completo(catalogo, schema, EVENT_LOG)
    saida = "details:flow_definition:output_dataset"
    return f"""SELECT DISTINCT {_parte_do_nome(saida, -2)} AS nm_schema, {_parte_do_nome(saida, -1)} AS nm_tabela
FROM {log}
WHERE event_type = 'flow_definition' AND origin.update_id = {literal_sql(str(id_atualizacao))}"""


# Método de carga de cada tabela: a primeira condição verdadeira vale (gera o CASE). Valores
# de flow_type conferidos no event log do dev em 2026-11-04: APPEND (bronze, Auto Loader),
# SNAPSHOT_CHANGE (AUTO CDC FROM SNAPSHOT), MATERIALIZED_VIEW e VIEW. CHANGE (AUTO CDC de
# uma fonte cdc) não foi visto: o exemplo não tem fonte cdc.
METODOS_DE_CARGA = {
    "FULL_REFRESH": "a.fl_full_refresh",
    "APPEND (Auto Loader)": "t.cd_tipo_fluxo = 'APPEND'",
    "AUTO CDC FROM SNAPSHOT SCD2": "t.cd_tipo_fluxo = 'SNAPSHOT_CHANGE' AND p.ds_tipo_tabela = 'historico'",
    "AUTO CDC FROM SNAPSHOT SCD1": "t.cd_tipo_fluxo = 'SNAPSHOT_CHANGE'",
    "AUTO CDC SCD2": "t.cd_tipo_fluxo = 'CHANGE' AND p.ds_tipo_tabela = 'historico'",
    "AUTO CDC SCD1": "t.cd_tipo_fluxo = 'CHANGE'",
    "MATERIALIZED VIEW": "t.cd_tipo_fluxo = 'MATERIALIZED_VIEW'",
    "VIEW": "t.cd_tipo_fluxo = 'VIEW'",
}


def case_metodo_de_carga() -> str:
    casos = "\n    ".join(
        f"WHEN {condicao} THEN {literal_sql(metodo)}" for metodo, condicao in METODOS_DE_CARGA.items()
    )
    return f"CASE\n    {casos}\n    ELSE t.cd_tipo_fluxo\n  END"


COLUNAS_PUBLICADAS = {"nm_schema": "STRING", "nm_tabela": "STRING", "ds_tipo_tabela": "STRING"}
COLUNAS_PRIVADAS = {"nm_tabela_privada": "STRING", "nm_tabela_publicada": "STRING"}
COLUNAS_REGRAS = {"nm_tabela": "STRING", "nm_regra": "STRING", "ds_acao": "STRING"}
COLUNAS_CONTAGENS = {"nm_schema": "STRING", "nm_tabela": "STRING", "qt_linhas_tabela": "BIGINT"}
COLUNAS_MOTIVOS = {"nm_tabela": "STRING", "ds_motivo_falha": "STRING"}


def sql_merge_tabelas(
    catalogo: str,
    schema: str,
    id_execucao: str,
    nm_job: str | None,
    link: str | None,
    id_atualizacao: str,
    publicadas: list[tuple],
    privadas: list[tuple],
    regras: list[tuple],
    contagens: list[tuple] | None = None,
    motivos: list[tuple] | None = None,
) -> str:
    """Upsert de uma linha por tabela publicada que a atualização do pipeline gravou.

    publicadas: (schema, tabela, tipo em TBLPROPERTIES) das tabelas do catálogo; só elas
      entram (a view temporária e o retrato privado não).
    privadas: (privada, publicada) de tabelas_privadas: gravadas, descartadas, alertas e a
      técnica da privada vão para a publicada (a gravada da própria tabela vale antes, se houver).
    regras: (tabela, regra, ação) de regras_monitoradas, para somar só as violações de alerta.
    contagens: (schema, tabela, linhas) com o count(*) depois da carga.
    motivos: (tabela publicada, motivo seguro) dos fluxos que falharam.
    """
    log = nome_completo(catalogo, schema, EVENT_LOG)
    tabela_log = nome_completo(catalogo, schema, LOG.nome)
    atualizacao = literal_sql(str(id_atualizacao))
    saida = "details:flow_definition:output_dataset"
    status = "details:flow_progress:status"
    origem = f"""WITH eventos AS (
  SELECT * FROM {log} WHERE origin.update_id = {atualizacao}
),
atualizacao AS (
  SELECT coalesce(max(CAST(details:create_update:full_refresh AS BOOLEAN)), false) AS fl_full_refresh
  FROM eventos WHERE event_type = 'create_update'
),
publicadas AS ({relacao(COLUNAS_PUBLICADAS, publicadas)}),
privadas AS ({relacao(COLUNAS_PRIVADAS, privadas)}),
regras AS ({relacao(COLUNAS_REGRAS, regras)}),
contagens AS ({relacao(COLUNAS_CONTAGENS, contagens or [])}),
motivos AS ({relacao(COLUNAS_MOTIVOS, motivos or [])}),
fluxos AS (
  SELECT origin.flow_name AS nm_fluxo, max({_parte_do_nome(saida, -2)}) AS nm_schema_saida,
    max({_parte_do_nome(saida, -1)}) AS nm_saida, max(details:flow_definition:flow_type) AS cd_tipo_fluxo
  FROM eventos WHERE event_type = 'flow_definition'
  GROUP BY origin.flow_name
),
progresso AS (
  SELECT origin.flow_name AS nm_fluxo,
    coalesce(min(timestamp) FILTER (WHERE {status} <> 'QUEUED'), min(timestamp) FILTER (WHERE {status} IS NOT NULL))
      AS dh_inicio,
    max(timestamp) FILTER (WHERE {status} IS NOT NULL) AS dh_fim,
    max_by({status}, timestamp) FILTER (WHERE {status} IS NOT NULL) AS st_fluxo,
    sum(CAST(details:flow_progress:metrics:num_output_rows AS BIGINT)) AS qt_linhas_gravadas,
    sum(CAST(details:flow_progress:data_quality:dropped_records AS BIGINT)) AS qt_linhas_descartadas
  FROM eventos WHERE event_type = 'flow_progress'
  GROUP BY origin.flow_name
),
-- Técnica escolhida: a marcada em technique_information ou, sem ela, a da mensagem
-- "has been planned to be executed as X" (as duas são metadado, sem dado de linha).
planejamento AS (
  SELECT origin.flow_name AS nm_fluxo,
    max_by(coalesce(
      regexp_replace(try_element_at(filter(from_json(details:planning_information:technique_information,
        '{ESQUEMA_TECNICAS}'), x -> coalesce(x.is_chosen, false)), 1).maintenance_type, '^MAINTENANCE_TYPE_', ''),
      nullif(regexp_extract(message, 'planned to be executed as ([A-Z_]+)', 1), '')), timestamp) AS cd_tecnica_refresh
  FROM eventos WHERE event_type = 'planning_information'
  GROUP BY origin.flow_name
),
por_fluxo AS (
  SELECT f.*, coalesce(pv.nm_tabela_publicada, f.nm_saida) AS nm_tabela,
    pv.nm_tabela_publicada IS NOT NULL AS fl_privada, p.dh_inicio, p.dh_fim, p.st_fluxo,
    p.qt_linhas_gravadas, p.qt_linhas_descartadas, pl.cd_tecnica_refresh
  FROM fluxos f
  LEFT JOIN privadas pv ON pv.nm_tabela_privada = f.nm_saida
  LEFT JOIN progresso p ON p.nm_fluxo = f.nm_fluxo
  LEFT JOIN planejamento pl ON pl.nm_fluxo = f.nm_fluxo
),
por_tabela AS (
  SELECT nm_tabela,
    max(nm_schema_saida) FILTER (WHERE NOT fl_privada) AS nm_schema,
    max(cd_tipo_fluxo) FILTER (WHERE NOT fl_privada) AS cd_tipo_fluxo,
    coalesce(max(cd_tecnica_refresh) FILTER (WHERE NOT fl_privada), max(cd_tecnica_refresh) FILTER (WHERE fl_privada))
      AS cd_tecnica_refresh,
    min(dh_inicio) AS dh_inicio, max(dh_fim) AS dh_fim,
    CASE WHEN array_contains(collect_list(st_fluxo), 'FAILED') THEN 'FAILED'
      ELSE max_by(st_fluxo, dh_fim) FILTER (WHERE NOT fl_privada) END AS st_execucao,
    coalesce(sum(qt_linhas_gravadas) FILTER (WHERE NOT fl_privada), sum(qt_linhas_gravadas) FILTER (WHERE fl_privada))
      AS qt_linhas_gravadas,
    sum(qt_linhas_descartadas) AS qt_linhas_descartadas
  FROM por_fluxo
  GROUP BY nm_tabela
),
-- Violações das regras com ação alerta, pela tabela em que a regra roda (o retrato, no
-- snapshot) e levadas para a tabela publicada.
alertas AS (
  SELECT coalesce(pv.nm_tabela_publicada, r.nm_tabela) AS nm_tabela, sum(e.regra.failed_records) AS qt_linhas_alerta
  FROM (
    SELECT explode(from_json(details:flow_progress:data_quality:expectations, '{ESQUEMA_EXPECTATIONS}')) AS regra
    FROM eventos
    WHERE event_type = 'flow_progress' AND details:flow_progress:data_quality:expectations IS NOT NULL
  ) AS e
  JOIN regras r ON r.nm_tabela = {_parte_do_nome("e.regra.dataset", -1)} AND r.nm_regra = e.regra.name
    AND r.ds_acao = 'alerta'
  LEFT JOIN privadas pv ON pv.nm_tabela_privada = r.nm_tabela
  GROUP BY 1
),
-- Última carga concluída da mesma tabela, antes desta, pelo próprio log.
anteriores AS (
  SELECT t.nm_schema, t.nm_tabela, max(l.dh_fim) AS dh_ultima_atualizacao_anterior
  FROM por_tabela t
  JOIN {tabela_log} l ON l.cd_nivel = 'tabela' AND l.nm_schema = t.nm_schema AND l.nm_tabela = t.nm_tabela
    AND l.st_execucao = '{FLUXO_CONCLUIDO}' AND l.dh_fim < t.dh_inicio
    AND l.id_execucao_job <> {literal_sql(str(id_execucao))}
  GROUP BY t.nm_schema, t.nm_tabela
)
SELECT {valor_sql(str(id_execucao), "STRING")} AS id_execucao_job, {valor_sql(nm_job, "STRING")} AS nm_job,
  'tabela' AS cd_nivel, '{TAREFA_PIPELINE}' AS nm_tarefa, {atualizacao} AS id_atualizacao_pipeline,
  t.nm_schema, t.nm_tabela, {case_metodo_de_carga()} AS ds_metodo_carga, t.cd_tecnica_refresh,
  an.dh_ultima_atualizacao_anterior, t.dh_inicio, t.dh_fim,
  {segundos("unix_millis(t.dh_fim) - unix_millis(t.dh_inicio)")} AS qt_duracao_segundos,
  {texto_duracao(segundos("unix_millis(t.dh_fim) - unix_millis(t.dh_inicio)"))} AS ds_duracao,
  t.st_execucao, t.qt_linhas_gravadas, coalesce(t.qt_linhas_descartadas, 0) AS qt_linhas_descartadas,
  coalesce(al.qt_linhas_alerta, 0) AS qt_linhas_alerta, c.qt_linhas_tabela, m.ds_motivo_falha,
  {valor_sql(link, "STRING")} AS ds_link_execucao, current_timestamp() AS dh_registro
FROM por_tabela t
JOIN publicadas p ON p.nm_schema = t.nm_schema AND p.nm_tabela = t.nm_tabela
CROSS JOIN atualizacao a
LEFT JOIN alertas al ON al.nm_tabela = t.nm_tabela
LEFT JOIN anteriores an ON an.nm_schema = t.nm_schema AND an.nm_tabela = t.nm_tabela
LEFT JOIN contagens c ON c.nm_schema = t.nm_schema AND c.nm_tabela = t.nm_tabela
LEFT JOIN motivos m ON m.nm_tabela = t.nm_tabela"""
    return sql_merge(catalogo, schema, LOG, origem)


# Texto dos erros (só para motivo_seguro, em Python; nunca gravado como está) ------------


def sql_etapa_e_erros_da_atualizacao(catalogo: str, schema: str, id_atualizacao: str) -> str:
    """Último estado da atualização antes de falhar e o texto bruto de todos os erros dela."""
    log = nome_completo(catalogo, schema, EVENT_LOG)
    return f"""SELECT
  max_by(details:update_progress:state, timestamp) FILTER (
    WHERE event_type = 'update_progress' AND details:update_progress:state NOT IN ('FAILED', 'CANCELED')
  ) AS ds_etapa,
  concat_ws('\\n', transform(array_sort(collect_list(named_struct('dh', timestamp, 'ds',
    concat_ws(' ', message, to_json(error)))) FILTER (WHERE level = 'ERROR')), x -> x.ds)) AS ds_texto_erro
FROM {log}
WHERE origin.update_id = {literal_sql(str(id_atualizacao))}"""


def sql_erros_dos_fluxos(catalogo: str, schema: str, id_atualizacao: str) -> str:
    """Fluxos que falharam com erro, com a tabela que gravam e o texto bruto dos erros.

    O texto pode ter o registro que violou a regra: quem chama só usa o que motivo_seguro
    extrai dele (lista de permissões) e nunca o grava.
    """
    log = nome_completo(catalogo, schema, EVENT_LOG)
    return f"""WITH eventos AS (
  SELECT * FROM {log} WHERE origin.update_id = {literal_sql(str(id_atualizacao))}
),
com_falha AS (
  SELECT DISTINCT origin.flow_name AS nm_fluxo
  FROM eventos
  WHERE event_type = 'flow_progress' AND details:flow_progress:status = 'FAILED' AND error IS NOT NULL
),
saidas AS (
  SELECT origin.flow_name AS nm_fluxo, max({_parte_do_nome("details:flow_definition:output_dataset", -1)}) AS nm_tabela
  FROM eventos WHERE event_type = 'flow_definition' GROUP BY 1
)
SELECT coalesce(s.nm_tabela, {_parte_do_nome("f.nm_fluxo", -1)}) AS nm_tabela,
  concat_ws('\\n', transform(array_sort(collect_list(named_struct('dh', e.timestamp, 'ds',
    concat_ws(' ', e.message, to_json(e.error))))), x -> x.ds)) AS ds_texto_erro
FROM com_falha f
JOIN eventos e ON e.origin.flow_name = f.nm_fluxo AND e.level = 'ERROR'
LEFT JOIN saidas s ON s.nm_fluxo = f.nm_fluxo
GROUP BY 1"""


# Leitura para o log legível --------------------------------------------------------------

ORDEM_DOS_NIVEIS = ("job", "tabela", "tarefa")


def sql_linhas_da_execucao(catalogo: str, schema: str, id_execucao: str) -> str:
    """Linhas gravadas da execução, com as datas em milissegundos (o fuso é aplicado em Python)."""
    ordem = " ".join(f"WHEN '{nivel}' THEN {posicao}" for posicao, nivel in enumerate(ORDEM_DOS_NIVEIS))
    return f"""SELECT cd_nivel, nm_job, id_execucao_job, nm_tarefa, nm_schema, nm_tabela, ds_metodo_carga,
  cd_tecnica_refresh, unix_millis(dh_ultima_atualizacao_anterior) AS nr_ms_ultima_anterior,
  unix_millis(dh_inicio) AS nr_ms_inicio, unix_millis(dh_fim) AS nr_ms_fim, ds_duracao, st_execucao,
  qt_linhas_gravadas, qt_linhas_descartadas, qt_linhas_alerta, qt_linhas_tabela, ds_motivo_falha
FROM {nome_completo(catalogo, schema, LOG.nome)}
WHERE id_execucao_job = {literal_sql(str(id_execucao))}
ORDER BY CASE cd_nivel {ordem} END, dh_inicio, nm_tarefa, nm_tabela"""
