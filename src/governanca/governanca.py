"""Preparação da governança antes do pipeline, como tarefa preparar_governanca do job.

  - cria a função de máscara usada pelas colunas sensíveis da gold, no schema da silver: ela
    precisa existir antes de o pipeline criar a gold (docs/adr/0002);
  - cria a tabela de log mon_log_execucao, no schema de monitoramento (CREATE TABLE IF NOT
    EXISTS: nunca apaga o que já está lá);
  - cria a view mon_falhas sobre o log, lida pelo alerta falha_carga mesmo antes da primeira
    falha (docs/adr/0015). Se mon_falhas ainda for a tabela antiga, ela é renomeada para
    mon_falhas_legado antes (nada é apagado).

O que roda depois do pipeline (views da gold, tags, views mon_* e o log) fica em
publicar_monitoramento.py. Os comandos SQL vêm de src/essentials/, testados pelo pytest.
"""

from __future__ import annotations

import argparse
import sys


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codigo", required=True, help="pasta src/ do bundle")
    parser.add_argument("--catalogo", required=True)
    parser.add_argument("--schema-silver", required=True, help="guarda a função de máscara")
    parser.add_argument("--schema-monitoramento", required=True, help="event log, log da carga e views mon_*")
    parser.add_argument("--grupo-dados-pessoais", required=True)
    parser.add_argument("--fuso-horario", required=True, help="fuso do log legível (variável fuso_horario)")
    return parser.parse_args()


def tipo_do_objeto(spark, catalogo: str, schema: str, nome: str) -> str | None:
    """table_type do objeto no information_schema (None se ele não existe)."""
    from essentials.config_fontes import literal_sql

    linhas = spark.sql(
        f"SELECT table_type FROM `{catalogo}`.information_schema.tables "
        f"WHERE table_schema = {literal_sql(schema)} AND table_name = {literal_sql(nome)}"
    ).collect()
    return linhas[0]["table_type"] if linhas else None


def main() -> None:
    args = argumentos()
    sys.path.append(args.codigo)
    from pyspark.sql import SparkSession

    from essentials.governanca_sql import sql_funcao_mascara
    from essentials.log_sql import (
        TABELA_FALHAS,
        TABELA_FALHAS_LEGADO,
        TABELA_LOG,
        precisa_renomear_falhas,
        sql_criar_tabela_log,
        sql_renomear_falhas_legado,
        sql_view_falhas,
    )
    from essentials.log_texto import configurar_log

    log = configurar_log(args.fuso_horario)
    spark = SparkSession.builder.getOrCreate()
    catalogo, monitoramento = args.catalogo, args.schema_monitoramento

    spark.sql(sql_funcao_mascara(catalogo, args.schema_silver, args.grupo_dados_pessoais))
    log.info("Função de máscara criada em %s.%s.", catalogo, args.schema_silver)

    spark.sql(sql_criar_tabela_log(catalogo, monitoramento))
    log.info("Tabela %s pronta em %s.%s.", TABELA_LOG, catalogo, monitoramento)

    if precisa_renomear_falhas(tipo_do_objeto(spark, catalogo, monitoramento, TABELA_FALHAS)):
        if tipo_do_objeto(spark, catalogo, monitoramento, TABELA_FALHAS_LEGADO) is not None:
            sys.exit(f"{TABELA_FALHAS} ainda é tabela e {TABELA_FALHAS_LEGADO} já existe: resolva à mão.")
        spark.sql(sql_renomear_falhas_legado(catalogo, monitoramento))
        log.warning("Tabela antiga %s renomeada para %s (nada foi apagado).", TABELA_FALHAS, TABELA_FALHAS_LEGADO)
    spark.sql(sql_view_falhas(catalogo, monitoramento))
    log.info("View %s criada sobre %s.", TABELA_FALHAS, TABELA_LOG)


if __name__ == "__main__":
    main()
