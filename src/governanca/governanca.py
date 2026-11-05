"""Governança e monitoramento no Unity Catalog, como tarefa do job (docs/adr/0002 e 0003).

  --etapa antes   cria a função de máscara usada pelas colunas sensíveis da gold (no
                  schema da silver; precisa existir antes de o pipeline criar a gold) e a
                  tabela mon_falhas (no schema de monitoramento), lida pelo alerta de falha
                  mesmo antes da primeira falha
  --etapa depois  cria as views da gold (src/views/gold_vw_*.sql), aplica a tag "pii" nas
                  colunas sensíveis da silver e da gold (sensivel: true do fontes.yml), cria
                  as views mon_* sobre o event log (que só existe depois do pipeline) e copia
                  as TBLPROPERTIES camada e tipo de cada tabela e view publicada para as tags
                  do Unity Catalog

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
    parser.add_argument("--schema-bronze", required=True)
    parser.add_argument("--schema-silver", required=True, help="também guarda a função de máscara")
    parser.add_argument("--schema-gold", required=True)
    parser.add_argument("--schema-monitoramento", required=True, help="event log, views mon_* e mon_falhas")
    parser.add_argument("--grupo-dados-pessoais", required=True)
    parser.add_argument("--job-id", help="ID do job, para a view de custo (etapa depois)")
    parser.add_argument("--pipeline-id", help="ID do pipeline, para a view de custo (etapa depois)")
    parser.add_argument("--limite-atraso-horas", type=int, default=26, help="limite da view mon_atualizacao")
    parser.add_argument("--limite-queda-volume-pct", type=int, default=50, help="limite da view mon_volume")
    parser.add_argument("--teto-custo-mensal", type=float, default=0, help="teto da view mon_custo_mensal")
    return parser.parse_args()


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


def aplicar_tags_das_tabelas(spark, catalogo: str, schemas: list[str]) -> int:
    """Copia camada e tipo (TBLPROPERTIES) para as tags de cada tabela e view publicada."""
    from essentials.governanca_sql import sql_tags_da_tabela

    aplicadas = 0
    for schema in schemas:
        for tabela, (tipo_objeto, _) in sorted(objetos_do_schema(spark, catalogo, schema).items()):
            if tabela.startswith("__"):
                continue
            comando = sql_tags_da_tabela(
                catalogo, schema, tabela, tipo_objeto, propriedades_da_tabela(spark, catalogo, schema, tabela)
            )
            if comando:
                spark.sql(comando)
                aplicadas += 1
    return aplicadas


def main() -> None:
    args = argumentos()
    sys.path.append(args.codigo)
    from pyspark.sql import SparkSession

    from essentials.config_fontes import carregar_fontes
    from essentials.governanca_sql import TAG_PII, sql_funcao_mascara, sqls_tags_pii, sqls_views_gold
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
    catalogo, monitoramento = args.catalogo, args.schema_monitoramento
    if args.etapa == "antes":
        spark.sql(sql_funcao_mascara(catalogo, args.schema_silver, args.grupo_dados_pessoais))
        spark.sql(sql_tabela_falhas(catalogo, monitoramento))
        print(f"Função de máscara em {catalogo}.{args.schema_silver} e mon_falhas em {catalogo}.{monitoramento}.")
        return

    fontes = carregar_fontes(args.config)
    views_gold = sqls_views_gold(args.codigo, catalogo, args.schema_gold, args.schema_silver)
    for comando in views_gold:
        spark.sql(comando)
    print(f"{len(views_gold)} view(s) da gold criada(s).")

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
    print(f"Tag pii aplicada em {len(comandos)} colunas.")

    bronze = objetos_do_schema(spark, catalogo, args.schema_bronze, "bronze_")
    colunas_bronze = {tabela: colunas for tabela, (_, colunas) in bronze.items()}
    spark.sql(sql_qualidade_diaria(catalogo, monitoramento, fontes))
    spark.sql(sql_atualizacao(catalogo, monitoramento, args.schema_silver, fontes, args.limite_atraso_horas))
    spark.sql(sql_volume(catalogo, monitoramento, fontes, args.limite_queda_volume_pct))
    spark.sql(sql_estrutura(catalogo, monitoramento, args.schema_bronze, args.schema_silver, fontes, colunas_bronze))
    print("Views mon_qualidade_diaria, mon_atualizacao, mon_volume e mon_estrutura criadas.")

    # As tabelas de sistema (faturamento e jobs) dependem de permissão do administrador da
    # conta: sem ela, as views de custo e de execuções ficam de fora, mas a carga não falha.
    if args.job_id and args.pipeline_id:
        for nome, comandos_sistema in (
            ("mon_custo_diario e mon_custo_mensal", [
                sql_custo_diario(catalogo, monitoramento, args.job_id, args.pipeline_id),
                sql_custo_mensal(catalogo, monitoramento, args.teto_custo_mensal),
            ]),
            ("mon_execucoes", [sql_execucoes(catalogo, monitoramento, args.job_id)]),
        ):
            try:
                for comando in comandos_sistema:
                    spark.sql(comando)
                print(f"Views {nome} criadas.")
            except Exception as erro:  # noqa: BLE001 - qualquer falha aqui só vira aviso
                print(f"AVISO: views {nome} não criadas (acesso às tabelas de sistema?): {erro}")

    # Por último, para alcançar também as views criadas acima.
    schemas = [args.schema_bronze, args.schema_silver, args.schema_gold, monitoramento]
    print(f"Tags camada e tipo aplicadas em {aplicar_tags_das_tabelas(spark, catalogo, schemas)} objetos.")


if __name__ == "__main__":
    main()
