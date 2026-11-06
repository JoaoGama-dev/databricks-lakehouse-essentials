"""Publica o monitoramento e o log da carga diária, como tarefa publicar_monitoramento do job.

Roda depois do pipeline com qualquer resultado (run_if: ALL_DONE) e nunca é tentada de novo
(max_retries: 0). Cada etapa tem o seu try: uma etapa com erro não impede as outras.

  views da gold        src/views/gold_vw_*.sql, com a máscara nas colunas sensíveis
  tags pii             colunas sensíveis da silver e da gold (sensivel: true do fontes.yml)
  views mon_*          qualidade, atualização, volume e estrutura, sobre o event log; custo
                       (diário, mensal e por carga) e execuções, se houver acesso às tabelas de
                       sistema (senão, só um aviso)
  tags camada e tipo   copiadas das TBLPROPERTIES de cada tabela e view publicada
  falhas               o motivo de cada tarefa que falhou, por motivo_seguro (LGPD)
  log da carga         mon_log_execucao: job, tarefas e cada tabela que o pipeline gravou
  log legível          o resumo da carga, na saída da tarefa

Se alguma tarefa anterior falhou (FAILED, TIMEDOUT ou CANCELED), ou alguma etapa daqui deu
erro, termina com erro de propósito: a tarefa avisar_falha manda o e-mail com o motivo
(alerta falha_carga) e a execução fica marcada como falha (docs/adr/0015).
"""

from __future__ import annotations

import argparse
import sys
import time


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="caminho do config/fontes.yml")
    parser.add_argument("--codigo", required=True, help="pasta src/ do bundle")
    parser.add_argument("--catalogo", required=True)
    parser.add_argument("--schema-bronze", required=True)
    parser.add_argument("--schema-silver", required=True, help="também guarda a função de máscara")
    parser.add_argument("--schema-gold", required=True)
    parser.add_argument("--schema-monitoramento", required=True, help="event log, log da carga e views mon_*")
    parser.add_argument("--job-id", required=True, help="ID do job ({{job.id}}), para a view mon_execucoes")
    parser.add_argument("--run-id", required=True, help="execução do job ({{job.run_id}})")
    parser.add_argument("--projeto", required=True, help="variável projeto: a tag que atribui o custo")
    parser.add_argument("--ambiente", required=True, help="target do bundle (dev, ci, prod)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse do projeto (variável warehouse_id)")
    parser.add_argument(
        "--warehouse-dedicado", required=True, help="true: o custo do warehouse entra nas views de custo"
    )
    parser.add_argument("--limite-atraso-horas", type=int, default=26, help="limite da view mon_atualizacao")
    parser.add_argument("--limite-queda-volume-pct", type=int, default=50, help="limite da view mon_volume")
    parser.add_argument("--teto-custo-mensal", type=float, default=0, help="teto da view mon_custo_mensal")
    parser.add_argument(
        "--cotacao-usd-brl", required=True, help="cotação das colunas em reais das views de custo (ex.: 5.40)"
    )
    parser.add_argument("--fuso-horario", required=True, help="fuso do log legível (variável fuso_horario)")
    return parser.parse_args()


# Catálogo (information_schema) --------------------------------------------------------------


def objetos_do_schema(spark, catalogo: str, schema: str, prefixo: str = "") -> dict[str, tuple[str, list[str]]]:
    """{tabela ou view: (table_type, [colunas])} do schema, pelo information_schema."""
    from essentials.config_fontes import literal_sql

    linhas = spark.sql(
        f"SELECT t.table_name, t.table_type, c.column_name "
        f"FROM `{catalogo}`.information_schema.tables AS t "
        f"LEFT JOIN `{catalogo}`.information_schema.columns AS c "
        f"ON c.table_schema = t.table_schema AND c.table_name = t.table_name "
        f"WHERE t.table_schema = {literal_sql(schema)} AND t.table_name LIKE {literal_sql(prefixo + '%')} "
        f"ORDER BY t.table_name, c.ordinal_position"
    ).collect()
    objetos: dict[str, tuple[str, list[str]]] = {}
    for linha in linhas:
        _, colunas = objetos.setdefault(linha["table_name"], (linha["table_type"], []))
        if linha["column_name"]:
            colunas.append(linha["column_name"])
    return objetos


def colunas_com_tag(spark, catalogo: str, schema: str, tag: str) -> set[tuple[str, str]]:
    """{(tabela, coluna)} que já têm a tag, pelo information_schema.column_tags."""
    from essentials.config_fontes import literal_sql

    linhas = spark.sql(
        f"SELECT table_name, column_name FROM `{catalogo}`.information_schema.column_tags "
        f"WHERE schema_name = {literal_sql(schema)} AND tag_name = {literal_sql(tag)}"
    ).collect()
    return {(linha["table_name"], linha["column_name"]) for linha in linhas}


def propriedades_da_tabela(spark, catalogo: str, schema: str, tabela: str) -> dict[str, str]:
    from essentials.governanca_sql import nome_completo

    linhas = spark.sql(f"SHOW TBLPROPERTIES {nome_completo(catalogo, schema, tabela)}").collect()
    return {linha["key"]: linha["value"] for linha in linhas}


# Etapas de governança e monitoramento -------------------------------------------------------


def criar_views_gold(spark, args, log) -> None:
    from essentials.governanca_sql import sqls_views_gold

    comandos = sqls_views_gold(args.codigo, args.catalogo, args.schema_gold, args.schema_silver)
    for comando in comandos:
        spark.sql(comando)
    log.info("%d view(s) da gold criada(s).", len(comandos))


def aplicar_tags_pii(spark, args, fontes, log) -> None:
    from essentials.governanca_sql import TAG_PII, sqls_tags_pii

    catalogo = args.catalogo
    comandos = sqls_tags_pii(
        catalogo,
        args.schema_silver,
        args.schema_gold,
        fontes,
        objetos_do_schema(spark, catalogo, args.schema_gold),
        colunas_com_tag(spark, catalogo, args.schema_gold, TAG_PII),
    )
    for comando in comandos:
        spark.sql(comando)
    log.info("Tag pii aplicada em %d coluna(s).", len(comandos))


def criar_views_mon(spark, args, fontes, log) -> None:
    from essentials.monitoramento_sql import sql_atualizacao, sql_estrutura, sql_qualidade_diaria, sql_volume

    catalogo, monitoramento = args.catalogo, args.schema_monitoramento
    bronze = objetos_do_schema(spark, catalogo, args.schema_bronze, "bronze_")
    colunas_bronze = {tabela: colunas for tabela, (_, colunas) in bronze.items()}
    spark.sql(sql_qualidade_diaria(catalogo, monitoramento, fontes))
    spark.sql(sql_atualizacao(catalogo, monitoramento, args.schema_silver, fontes, args.limite_atraso_horas))
    spark.sql(sql_volume(catalogo, monitoramento, fontes, args.limite_queda_volume_pct))
    spark.sql(sql_estrutura(catalogo, monitoramento, args.schema_bronze, args.schema_silver, fontes, colunas_bronze))
    log.info("Views mon_qualidade_diaria, mon_atualizacao, mon_volume e mon_estrutura criadas.")


def criar_views_de_sistema(spark, args, log) -> None:
    """Custo e execuções dependem de acesso às tabelas de sistema: sem ele, só um aviso."""
    from pyspark.errors import PySparkException

    from essentials.monitoramento_sql import (
        booleano_da_variavel,
        cotacao_da_variavel,
        sql_custo_diario,
        sql_custo_mensal,
        sql_custo_por_carga,
        sql_execucoes,
    )

    catalogo, monitoramento = args.catalogo, args.schema_monitoramento
    # Valor inválido em warehouse_dedicado ou em cotacao_usd_brl é erro da etapa (ValueError),
    # não um false ou um 0 silencioso.
    atribuicao = (args.projeto, args.ambiente, booleano_da_variavel(args.warehouse_dedicado), args.warehouse_id)
    cotacao = cotacao_da_variavel(args.cotacao_usd_brl)
    for nome, comandos in (
        ("mon_custo_diario, mon_custo_mensal e mon_custo_por_carga", [
            sql_custo_diario(catalogo, monitoramento, *atribuicao, cotacao),
            sql_custo_mensal(catalogo, monitoramento, args.teto_custo_mensal, cotacao),
            sql_custo_por_carga(catalogo, monitoramento, *atribuicao, cotacao),
        ]),
        ("mon_execucoes", [sql_execucoes(catalogo, monitoramento, args.job_id)]),
    ):
        try:
            for comando in comandos:
                spark.sql(comando)
            log.info("Views %s criadas.", nome)
        except PySparkException as erro:
            log.warning("Views %s não criadas (acesso às tabelas de sistema?): %s.", nome, type(erro).__name__)


def aplicar_tags_camada_tipo(spark, args, log) -> None:
    """Copia camada e tipo (TBLPROPERTIES) para as tags de cada tabela e view publicada."""
    from essentials.governanca_sql import sql_tags_da_tabela

    catalogo = args.catalogo
    aplicadas = 0
    for schema in (args.schema_bronze, args.schema_silver, args.schema_gold, args.schema_monitoramento):
        for tabela, (tipo_objeto, _) in sorted(objetos_do_schema(spark, catalogo, schema).items()):
            if tabela.startswith("__"):
                continue
            comando = sql_tags_da_tabela(
                catalogo, schema, tabela, tipo_objeto, propriedades_da_tabela(spark, catalogo, schema, tabela)
            )
            if comando:
                spark.sql(comando)
                aplicadas += 1
    log.info("Tags camada e tipo aplicadas em %d objeto(s).", aplicadas)


# Falhas e log da carga ----------------------------------------------------------------------


def atualizacao_da_tarefa(spark, args, tarefa) -> str | None:
    from essentials.log_sql import sql_atualizacao_da_tarefa

    consulta = sql_atualizacao_da_tarefa(args.catalogo, args.schema_monitoramento, str(tarefa.run_id))
    linhas = spark.sql(consulta).collect()
    return linhas[0]["id_atualizacao"] if linhas else None


def motivos_do_pipeline(spark, args, tarefa, id_atualizacao, regras, privadas) -> tuple[str, list[tuple]]:
    """Motivo da tarefa do pipeline e o de cada tabela publicada cujo fluxo falhou.

    O texto do erro do event log só passa por motivo_seguro (lista de permissões).
    """
    from essentials.log_sql import sql_erros_dos_fluxos, sql_etapa_e_erros_da_atualizacao
    from essentials.monitoramento_sql import motivo_seguro

    mensagem = tarefa.state.state_message if tarefa.state else None
    if not id_atualizacao:
        # O pipeline nem chegou a criar a atualização: vale a mensagem da tarefa.
        return motivo_seguro(mensagem, None, regras), []
    catalogo, schema = args.catalogo, args.schema_monitoramento
    resumo = spark.sql(sql_etapa_e_erros_da_atualizacao(catalogo, schema, id_atualizacao)).collect()[0]
    etapa = resumo["ds_etapa"]
    motivo = motivo_seguro(resumo["ds_texto_erro"] or mensagem, etapa, regras)
    por_tabela = {}
    for fluxo in spark.sql(sql_erros_dos_fluxos(catalogo, schema, id_atualizacao)).collect():
        tabela = privadas.get(fluxo["nm_tabela"], fluxo["nm_tabela"])
        por_tabela[tabela] = motivo_seguro(fluxo["ds_texto_erro"], etapa, regras)
    return motivo, sorted(por_tabela.items())


def levantar_falhas(spark, w, args, fontes, estado: dict, log) -> None:
    """Lê a execução e monta o motivo seguro de cada tarefa que falhou."""
    from essentials.log_sql import TAREFA_PIPELINE, tabelas_privadas, tarefas_com_falha, ultimas_tentativas
    from essentials.monitoramento_sql import motivo_seguro, regras_monitoradas

    regras = {regra for _tabela, regra, _acao in regras_monitoradas(fontes)}
    privadas = dict(tabelas_privadas(fontes))
    execucao = w.jobs.get_run(int(args.run_id))
    estado["execucao"] = execucao
    pipeline = [t for t in ultimas_tentativas(execucao.tasks) if t.task_key == TAREFA_PIPELINE]
    estado["id_atualizacao"] = atualizacao_da_tarefa(spark, args, pipeline[0]) if pipeline else None
    for tarefa in tarefas_com_falha(execucao.tasks):
        if tarefa.task_key == TAREFA_PIPELINE:
            motivo, por_tabela = motivos_do_pipeline(spark, args, tarefa, estado["id_atualizacao"], regras, privadas)
            estado["motivos_tabelas"] = por_tabela
        else:
            mensagem = tarefa.state.state_message if tarefa.state else None
            if tarefa.condition_task is None:
                mensagem = w.jobs.get_run_output(tarefa.run_id).error or mensagem
            motivo = motivo_seguro(mensagem, None, regras)
        estado["motivos"][tarefa.task_key] = motivo
        log.error("Tarefa %s falhou: %s", tarefa.task_key, motivo)


def publicadas_da_atualizacao(spark, args, id_atualizacao: str) -> list[tuple[str, str, str | None]]:
    """(schema, tabela, tipo) das tabelas do catálogo que a atualização gravou (sem views)."""
    from essentials.log_sql import sql_saidas_da_atualizacao

    saidas = spark.sql(sql_saidas_da_atualizacao(args.catalogo, args.schema_monitoramento, id_atualizacao)).collect()
    no_catalogo = {}
    for schema in sorted({linha["nm_schema"] for linha in saidas if linha["nm_schema"]}):
        no_catalogo[schema] = objetos_do_schema(spark, args.catalogo, schema)
    publicadas = []
    for linha in saidas:
        objeto = no_catalogo.get(linha["nm_schema"], {}).get(linha["nm_tabela"])
        if objeto is None or objeto[0] == "VIEW" or linha["nm_tabela"].startswith("__"):
            continue
        tipo = propriedades_da_tabela(spark, args.catalogo, linha["nm_schema"], linha["nm_tabela"]).get("tipo")
        publicadas.append((linha["nm_schema"], linha["nm_tabela"], tipo))
    return sorted(publicadas)


def registrar_log(spark, w, args, fontes, estado: dict, etapas_com_erro: list[str], log) -> None:
    from essentials.governanca_sql import nome_completo
    from essentials.log_sql import linhas_de_execucao, sql_merge_execucao, sql_merge_tabelas, tabelas_privadas
    from essentials.monitoramento_sql import regras_monitoradas

    execucao = estado.get("execucao") or w.jobs.get_run(int(args.run_id))
    link = execucao.run_page_url or f"{w.config.host.rstrip('/')}/jobs/{execucao.job_id}/runs/{execucao.run_id}"
    id_atualizacao = estado.get("id_atualizacao")
    agora = int(time.time() * 1000)
    linhas = linhas_de_execucao(execucao, estado["motivos"], id_atualizacao, agora, etapas_com_erro)
    catalogo, monitoramento = args.catalogo, args.schema_monitoramento
    spark.sql(sql_merge_execucao(catalogo, monitoramento, args.run_id, execucao.run_name, link, linhas))
    if not id_atualizacao:
        log.warning("O pipeline não rodou nesta execução: o log não tem linhas de tabela.")
        return
    publicadas = publicadas_da_atualizacao(spark, args, id_atualizacao)
    # Uma contagem por tabela publicada que a atualização gravou, depois da carga.
    contagens = [
        (schema, tabela, spark.sql(f"SELECT count(*) AS qt FROM {nome_completo(catalogo, schema, tabela)}").first()[0])
        for schema, tabela, _tipo in publicadas
    ]
    spark.sql(
        sql_merge_tabelas(
            catalogo, monitoramento, args.run_id, execucao.run_name, link, id_atualizacao, publicadas,
            tabelas_privadas(fontes), regras_monitoradas(fontes), contagens, estado.get("motivos_tabelas"),
        )
    )
    log.info("Log da carga gravado em mon_log_execucao: job, %d tarefa(s) e %d tabela(s).", len(linhas) - 1,
             len(publicadas))


def imprimir_log(spark, args, log) -> None:
    from essentials.log_sql import sql_linhas_da_execucao
    from essentials.log_texto import mensagens_do_log

    linhas = [linha.asDict() for linha in spark.sql(
        sql_linhas_da_execucao(args.catalogo, args.schema_monitoramento, args.run_id)
    ).collect()]
    for nivel, mensagem in mensagens_do_log(linhas, args.fuso_horario):
        log.log(nivel, mensagem)


def main() -> None:
    args = argumentos()
    sys.path.append(args.codigo)
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.errors import DatabricksError
    from pyspark.errors import PySparkException
    from pyspark.sql import SparkSession

    from essentials.config_fontes import carregar_fontes
    from essentials.log_sql import decidir_encerramento
    from essentials.log_texto import configurar_log
    from essentials.monitoramento_sql import motivo_seguro, regras_monitoradas

    log = configurar_log(args.fuso_horario)
    fontes = carregar_fontes(args.config)
    # Só nomes de regra do fontes.yml podem sair do texto do erro (lista de permissões).
    regras = {regra for _tabela, regra, _acao in regras_monitoradas(fontes)}
    spark = SparkSession.builder.getOrCreate()
    w = WorkspaceClient()
    estado: dict = {"motivos": {}}
    etapas_com_erro: list[str] = []

    def etapa(nome: str, funcao) -> None:
        try:
            funcao()
        except (PySparkException, DatabricksError) as erro:
            # A mensagem do Spark pode citar um valor: só a parte que motivo_seguro deixa.
            log.error("Etapa %s com erro: %s", nome, motivo_seguro(str(erro), None, regras))
            etapas_com_erro.append(nome)
        except Exception as erro:  # noqa: BLE001 - qualquer outro erro: registra e segue para a próxima etapa
            motivo = motivo_seguro(f"{type(erro).__name__}: {erro}", None, regras)
            log.error("Etapa %s com erro inesperado: %s", nome, motivo)
            etapas_com_erro.append(nome)

    etapa("views da gold", lambda: criar_views_gold(spark, args, log))
    etapa("tags pii", lambda: aplicar_tags_pii(spark, args, fontes, log))
    etapa("views mon", lambda: criar_views_mon(spark, args, fontes, log))
    etapa("views de sistema", lambda: criar_views_de_sistema(spark, args, log))
    etapa("tags camada e tipo", lambda: aplicar_tags_camada_tipo(spark, args, log))
    etapa("falhas", lambda: levantar_falhas(spark, w, args, fontes, estado, log))
    etapa("log da carga", lambda: registrar_log(spark, w, args, fontes, estado, list(etapas_com_erro), log))
    etapa("log legível", lambda: imprimir_log(spark, args, log))

    falhas = sorted(estado["motivos"].items())
    encerramento = decidir_encerramento(falhas, etapas_com_erro)
    if encerramento:
        log.error(encerramento)
    # Só termina com erro se uma etapa desta tarefa falhou. A falha de outra tarefa é avisada
    # pela avisar_falha e deixa o job vermelho pela encerrar_com_falha: sair com erro aqui só
    # faria o serverless repetir a tarefa inteira (as novas tentativas automáticas não respeitam
    # max_retries: 0, que o bundle omite por ser zero).
    if etapas_com_erro:
        sys.exit(encerramento)
    if not encerramento:
        log.info("Monitoramento publicado; a carga terminou sem falhas.")


if __name__ == "__main__":
    main()
