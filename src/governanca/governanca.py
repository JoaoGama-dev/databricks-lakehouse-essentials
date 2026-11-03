"""Governança de dados pessoais no Unity Catalog, como tarefa do job (docs/adr/0002).

  --etapa antes   cria a função de máscara usada pelas colunas sensíveis da gold
                  (precisa existir antes de o pipeline criar as tabelas gold)
  --etapa depois  aplica a tag "pii" nas colunas sensíveis da silver e da gold,
                  a partir da flag sensivel: true do config/fontes.yml

Os comandos SQL vêm de src/essentials/governanca_sql.py, testado pelo pytest.
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
    return parser.parse_args()


def main() -> None:
    args = argumentos()
    sys.path.append(args.codigo)
    from pyspark.sql import SparkSession

    from essentials.config_fontes import carregar_fontes, literal_sql
    from essentials.governanca_sql import sql_funcao_mascara, sqls_tags_pii

    spark = SparkSession.builder.getOrCreate()
    if args.etapa == "antes":
        spark.sql(sql_funcao_mascara(args.catalogo, args.schema, args.grupo_dados_pessoais))
        print(f"Função de máscara criada em {args.catalogo}.{args.schema}.")
        return

    linhas = spark.sql(
        f"SELECT table_name, column_name FROM `{args.catalogo}`.information_schema.columns "
        f"WHERE table_schema = {literal_sql(args.schema_gold)}"
    ).collect()
    colunas_gold: dict[str, list[str]] = {}
    for linha in linhas:
        colunas_gold.setdefault(linha["table_name"], []).append(linha["column_name"])

    comandos = sqls_tags_pii(
        args.catalogo, args.schema, args.schema_gold, carregar_fontes(args.config), colunas_gold
    )
    for comando in comandos:
        spark.sql(comando)
    print(f"Tag pii aplicada em {len(comandos)} colunas.")


if __name__ == "__main__":
    main()
