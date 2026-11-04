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
PROJETO = spark.conf.get("projeto")
LANDING = spark.conf.get("landing_path").rstrip("/")
FONTES = carregar_fontes(spark.conf.get("fontes_config"))
FORMATOS_AUTO_LOADER = {"csv": "csv", "json": "json", "parquet": "parquet", "texto": "text", "excel": "excel"}


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
    if formato in ("csv", "json", "parquet"):
        # Coluna nova na origem não derruba a carga: vai para _rescued_data, e a view
        # mon_estrutura avisa no mesmo dia (docs/adr/0014).
        leitor = leitor.option("cloudFiles.schemaEvolutionMode", "rescue")
    if formato == "excel":
        # Planilha .xlsx/.xls: o Auto Loader de Excel não evolui schema (exige "none"); a
        # primeira linha é o cabeçalho, salvo headerRows ou dataAddress nas opções da fonte.
        leitor = leitor.option("cloudFiles.schemaEvolutionMode", "none").option("headerRows", "1")
    opcoes = fonte.get("arquivo", {}).get("opcoes", {})
    return leitor.options(**opcoes).load(f"{LANDING}/{pasta_landing(fonte)}")


def ler_tabela_em_streaming(fonte: dict) -> DataFrame:
    leitor = spark.readStream
    if fonte["modo_carga"] == "cdc":
        leitor = leitor.option("readChangeFeed", "true")
    else:
        # Incremental: ignora atualizações na origem e segue lendo só o que foi incluído.
        leitor = leitor.option("skipChangeCommits", "true")
    return leitor.table(nome_tabela_origem(fonte, CATALOGO, PROJETO))


def criar_bronze(fonte: dict) -> None:
    nome = tabelas_da_fonte(fonte)["bronze"]
    comentario = f"Bronze de {fonte['nome']}: {fonte['descricao']} Dado exatamente como chegou, sem transformação."
    propriedades = propriedades_tabela("bronze", "bruta", fonte)

    if fonte["tipo"] == "tabela" and fonte["modo_carga"] == "snapshot":

        def copia_da_tabela() -> DataFrame:
            return com_colunas_tecnicas(spark.read.table(nome_tabela_origem(fonte, CATALOGO, PROJETO)), fonte)

        dp.materialized_view(name=nome, comment=comentario, table_properties=propriedades)(copia_da_tabela)
        return

    def leitura_incremental() -> DataFrame:
        df = ler_tabela_em_streaming(fonte) if fonte["tipo"] == "tabela" else ler_landing(fonte)
        return com_colunas_tecnicas(df, fonte)

    # Na bronze de arquivo, banco e api, propriedades_tabela já bloqueia o reset do full refresh.
    dp.table(name=nome, comment=comentario, table_properties=propriedades)(leitura_incremental)


for fonte in FONTES:
    criar_bronze(fonte)
