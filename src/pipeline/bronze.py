"""Bronze genérica: cria uma tabela bronze_<nome> para cada fonte do config/fontes.yml.

A bronze guarda o dado exatamente como chegou (ELT): nenhuma limpeza, nenhum filtro.
Só acrescenta as colunas técnicas _fonte, _arquivo_origem (quando há arquivo) e
_ingerido_em.

  arquivo, banco, api -> streaming table com Auto Loader lendo a pasta da fonte na
                         landing (banco e api chegam lá pelos jobs de src/ingestao/)
  tabela              -> materialized view no modo snapshot; streaming table nos
                         modos incremental e cdc (cdc lê o change data feed)
"""

import sys

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

spark = SparkSession.getActiveSession()
sys.path.append(spark.conf.get("diretorio_codigo"))

# O pacote essentials só fica importável depois do sys.path.append acima, que aponta
# para a pasta src/ do bundle no workspace; por isso o import não está no topo.
from essentials.config_fontes import (  # noqa: E402
    carregar_fontes,
    formato_landing,
    nome_tabela_origem,
    pasta_landing,
    propriedades_tabela,
    tabelas_da_fonte,
)

CATALOGO = spark.conf.get("catalogo")
LANDING = spark.conf.get("landing_path").rstrip("/")
FONTES = carregar_fontes(spark.conf.get("fontes_config"))
FORMATOS_AUTO_LOADER = {"csv": "csv", "json": "json", "parquet": "parquet", "texto": "text"}


def com_colunas_tecnicas(df: DataFrame, fonte: dict) -> DataFrame:
    if fonte["tipo"] != "tabela":
        df = df.withColumn("_arquivo_origem", F.col("_metadata.file_path"))
    return df.withColumn("_fonte", F.lit(fonte["nome"])).withColumn("_ingerido_em", F.current_timestamp())


def ler_landing(fonte: dict) -> DataFrame:
    """Auto Loader: a cada execução lê só os arquivos novos da pasta da fonte."""
    formato = formato_landing(fonte)
    leitor = spark.readStream.format("cloudFiles").option("cloudFiles.format", FORMATOS_AUTO_LOADER[formato])
    if formato in ("csv", "json"):
        # Tudo como texto: tipar é papel da silver.
        leitor = leitor.option("cloudFiles.inferColumnTypes", "false")
    opcoes = fonte.get("arquivo", {}).get("opcoes", {})
    return leitor.options(**opcoes).load(f"{LANDING}/{pasta_landing(fonte)}")


def ler_tabela_em_streaming(fonte: dict) -> DataFrame:
    leitor = spark.readStream
    if fonte["modo_carga"] == "cdc":
        leitor = leitor.option("readChangeFeed", "true")
    else:
        # Incremental: ignora atualizações na origem e segue lendo só o que foi incluído.
        leitor = leitor.option("skipChangeCommits", "true")
    return leitor.table(nome_tabela_origem(fonte, CATALOGO))


def criar_bronze(fonte: dict) -> None:
    nome = tabelas_da_fonte(fonte)["bronze"]
    comentario = f"Bronze de {fonte['nome']}: {fonte['descricao']} Dado exatamente como chegou, sem transformação."
    propriedades = propriedades_tabela("bronze", fonte)

    if fonte["tipo"] == "tabela" and fonte["modo_carga"] == "snapshot":

        def copia_da_tabela() -> DataFrame:
            return com_colunas_tecnicas(spark.read.table(nome_tabela_origem(fonte, CATALOGO)), fonte)

        dp.materialized_view(name=nome, comment=comentario, table_properties=propriedades)(copia_da_tabela)
        return

    def leitura_incremental() -> DataFrame:
        df = ler_tabela_em_streaming(fonte) if fonte["tipo"] == "tabela" else ler_landing(fonte)
        return com_colunas_tecnicas(df, fonte)

    dp.table(name=nome, comment=comentario, table_properties=propriedades)(leitura_incremental)


for fonte in FONTES:
    criar_bronze(fonte)
