"""Governança e monitoramento no Unity Catalog, como tarefa do job (docs/adr/0002 e 0003).

  --etapa antes   cria a função de máscara usada pelas colunas sensíveis da gold
                  (precisa existir antes de o pipeline criar as tabelas gold)
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
    return parser.parse_args()


def main() -> None:
    args = argumentos()
    sys.path.append(args.codigo)
    from pyspark.sql import SparkSession

    from essentials.config_fontes import carregar_fontes, literal_sql
    from essentials.governanca_sql import sql_funcao_mascara, sqls_tags_pii
    from essentials.monitoramento_sql import sql_atualizacao, sql_custo_diario, sql_qualidade_diaria

    spark = SparkSession.builder.getOrCreate()
    if args.etapa == "antes":
        spark.sql(sql_funcao_mascara(args.catalogo, args.schema, args.grupo_dados_pessoais))
        print(f"Função de máscara criada em {args.catalogo}.{args.schema}.")
        return

    fontes = carregar_fontes(args.config)
    linhas = spark.sql(
        f"SELECT table_name, column_name FROM `{args.catalogo}`.information_schema.columns "
        f"WHERE table_schema = {literal_sql(args.schema_gold)}"
    ).collect()
    colunas_gold: dict[str, list[str]] = {}
    for linha in linhas:
        colunas_gold.setdefault(linha["table_name"], []).append(linha["column_name"])

    comandos = sqls_tags_pii(args.catalogo, args.schema, args.schema_gold, fontes, colunas_gold)
    for comando in comandos:
        spark.sql(comando)
    print(f"Tag pii aplicada em {len(comandos)} colunas.")

    spark.sql(sql_qualidade_diaria(args.catalogo, args.schema, fontes))
    spark.sql(sql_atualizacao(args.catalogo, args.schema, fontes, args.limite_atraso_horas))
    print("Views mon_qualidade_diaria e mon_atualizacao criadas.")

    # As tabelas de sistema de faturamento dependem de permissão do administrador da conta:
    # sem ela, a view de custo fica de fora, mas a carga não falha.
    if args.job_id and args.pipeline_id:
        try:
            spark.sql(sql_custo_diario(args.catalogo, args.schema, args.job_id, args.pipeline_id))
            print("View mon_custo_diario criada.")
        except Exception as erro:  # noqa: BLE001 - qualquer falha aqui só vira aviso
            print(f"AVISO: view mon_custo_diario não criada (acesso a system.billing?): {erro}")


if __name__ == "__main__":
    main()
