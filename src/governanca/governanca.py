"""Governança e monitoramento no Unity Catalog, como tarefa do job (docs/adr/0002 e 0003).

  --etapa antes   cria a função de máscara usada pelas colunas sensíveis da gold
                  (precisa existir antes de o pipeline criar as tabelas gold) e a tabela
                  mon_falhas, lida pelo alerta de falha mesmo antes da primeira falha
  --etapa depois  aplica a tag "pii" nas colunas sensíveis da silver e da gold, a partir
                  da flag sensivel: true do config/fontes.yml, e cria as views mon_* de
                  monitoramento sobre o event log (que só existe depois do pipeline)

Os comandos SQL vêm de src/essentials/governanca_sql.py e monitoramento_sql.py, testados
pelo pytest.
"""

from __future__ import annotations

import argparse
import sys


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--etapa", choices=["antes", "depois"], required=True)
    parser.add_argument("--config", required=True, help="caminho do config/fontes.yml")
    parser.add_argument("--codigo", required=True, help="pasta src/ do bundle")
    parser.add_argument("--catalogo", required=True)
    parser.add_argument("--schema", required=True, help="schema de bronze e silver")
    parser.add_argument("--schema-gold", required=True)
    parser.add_argument("--grupo-dados-pessoais", required=True)
    parser.add_argument("--job-id", help="ID do job, para a view de custo (etapa depois)")
    parser.add_argument("--pipeline-id", help="ID do pipeline, para a view de custo (etapa depois)")
    parser.add_argument("--limite-atraso-horas", type=int, default=26, help="limite da view mon_atualizacao")
    parser.add_argument("--limite-queda-volume-pct", type=int, default=50, help="limite da view mon_volume")
    parser.add_argument("--teto-custo-mensal", type=float, default=0, help="teto da view mon_custo_mensal")
    return parser.parse_args()


def colunas_por_tabela(spark, catalogo: str, schema: str, prefixo: str) -> dict[str, list[str]]:
    from essentials.config_fontes import literal_sql

    linhas = spark.sql(
        f"SELECT table_name, column_name FROM `{catalogo}`.information_schema.columns "
        f"WHERE table_schema = {literal_sql(schema)} AND table_name LIKE {literal_sql(prefixo + '%')}"
    ).collect()
    colunas: dict[str, list[str]] = {}
    for linha in linhas:
        colunas.setdefault(linha["table_name"], []).append(linha["column_name"])
    return colunas


def main() -> None:
    args = argumentos()
    sys.path.append(args.codigo)
    from pyspark.sql import SparkSession

    from essentials.config_fontes import carregar_fontes
    from essentials.governanca_sql import sql_funcao_mascara, sqls_tags_pii
    from essentials.monitoramento_sql import (
        sql_atualizacao,
        sql_custo_diario,
        sql_custo_mensal,
        sql_estrutura,
        sql_execucoes,
        sql_qualidade_diaria,
        sql_tabela_falhas,
        sql_volume,
    )

    spark = SparkSession.builder.getOrCreate()
    if args.etapa == "antes":
        spark.sql(sql_funcao_mascara(args.catalogo, args.schema, args.grupo_dados_pessoais))
        spark.sql(sql_tabela_falhas(args.catalogo, args.schema))
        print(f"Função de máscara e tabela mon_falhas prontas em {args.catalogo}.{args.schema}.")
        return

    fontes = carregar_fontes(args.config)
    colunas_gold = colunas_por_tabela(spark, args.catalogo, args.schema_gold, "")
    comandos = sqls_tags_pii(args.catalogo, args.schema, args.schema_gold, fontes, colunas_gold)
    for comando in comandos:
        spark.sql(comando)
    print(f"Tag pii aplicada em {len(comandos)} colunas.")

    colunas_bronze = colunas_por_tabela(spark, args.catalogo, args.schema, "bronze_")
    spark.sql(sql_qualidade_diaria(args.catalogo, args.schema, fontes))
    spark.sql(sql_atualizacao(args.catalogo, args.schema, fontes, args.limite_atraso_horas))
    spark.sql(sql_volume(args.catalogo, args.schema, fontes, args.limite_queda_volume_pct))
    spark.sql(sql_estrutura(args.catalogo, args.schema, fontes, colunas_bronze))
    print("Views mon_qualidade_diaria, mon_atualizacao, mon_volume e mon_estrutura criadas.")

    # As tabelas de sistema (faturamento e jobs) dependem de permissão do administrador da
    # conta: sem ela, as views de custo e de execuções ficam de fora, mas a carga não falha.
    if args.job_id and args.pipeline_id:
        for nome, comandos_sistema in (
            ("mon_custo_diario e mon_custo_mensal", [
                sql_custo_diario(args.catalogo, args.schema, args.job_id, args.pipeline_id),
                sql_custo_mensal(args.catalogo, args.schema, args.teto_custo_mensal),
            ]),
            ("mon_execucoes", [sql_execucoes(args.catalogo, args.schema, args.job_id)]),
        ):
            try:
                for comando in comandos_sistema:
                    spark.sql(comando)
                print(f"Views {nome} criadas.")
            except Exception as erro:  # noqa: BLE001 - qualquer falha aqui só vira aviso
                print(f"AVISO: views {nome} não criadas (acesso às tabelas de sistema?): {erro}")


if __name__ == "__main__":
    main()
