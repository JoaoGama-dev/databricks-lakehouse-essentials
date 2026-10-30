"""Ingestão de bancos: grava na landing, em parquet, os dados de cada fonte do tipo
banco do config/fontes.yml.

O banco é lido pelo Lakehouse Federation: a conexão do Unity Catalog (campo
"conexao") tem um catálogo estrangeiro com o mesmo nome. Nos modos incremental e
cdc, só vêm as linhas com coluna_watermark maior que a da última carga; o último
valor fica em <landing>/_controle/<fonte>.json. No modo snapshot, vem a tabela
inteira a cada execução.

Roda como tarefa do job essentials_carga_diaria, antes do pipeline.
Testado só no Azure Databricks: o Free Edition restringe o acesso a bancos externos.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="caminho do config/fontes.yml")
    parser.add_argument("--landing", required=True, help="raiz da landing zone")
    parser.add_argument("--codigo", required=True, help="pasta src/ do bundle")
    return parser.parse_args()


def ler_watermark(spark, caminho: str) -> str | None:
    from pyspark.errors import AnalysisException

    try:
        return json.loads(spark.read.text(caminho, wholetext=True).first()["value"])["valor"]
    except AnalysisException:
        # Na primeira carga o arquivo de controle ainda não existe (PATH_NOT_FOUND).
        return None


def main() -> None:
    args = argumentos()
    sys.path.append(args.codigo)
    from databricks.sdk.runtime import dbutils
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    from essentials.config_fontes import carregar_fontes

    fontes = [fonte for fonte in carregar_fontes(args.config) if fonte["tipo"] == "banco"]
    if not fontes:
        print("Nenhuma fonte do tipo banco no config/fontes.yml; nada a fazer.")
        return

    spark = SparkSession.builder.getOrCreate()
    landing = args.landing.rstrip("/")
    momento = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")

    for fonte in fontes:
        banco = fonte["banco"]
        df = spark.read.table(f"{banco['conexao']}.{banco['tabela_origem']}")
        coluna = banco.get("coluna_watermark")
        incremental = fonte["modo_carga"] != "snapshot"
        controle = f"{landing}/_controle/{fonte['nome']}.json"

        if incremental:
            anterior = ler_watermark(spark, controle)
            if anterior is not None:
                df = df.where(F.col(coluna) > F.lit(anterior))
            novo = df.agg(F.max(coluna)).first()[0]
            if novo is None:
                print(f"{fonte['nome']}: nenhuma linha nova desde {anterior}.")
                continue
            # Fixa o limite superior para não perder linhas gravadas durante a leitura.
            df = df.where(F.col(coluna) <= F.lit(novo))

        destino = f"{landing}/{banco['pasta_landing']}/carga_{momento}"
        df.write.mode("errorifexists").parquet(destino)
        if incremental:
            dbutils.fs.put(controle, json.dumps({"valor": str(novo)}), overwrite=True)
        print(f"{fonte['nome']}: carga gravada em {destino}")


if __name__ == "__main__":
    main()
