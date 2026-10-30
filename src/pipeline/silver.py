"""Silver genérica: limpeza padrão e regras de qualidade de cada fonte do config/fontes.yml.

Para cada fonte:
  1. lê a bronze, ou a view preparada_<nome> quando há src/pipeline/silver_<nome>.sql;
  2. aplica a limpeza padrão (TRIM, tipos, datas em mais de um formato, de-para, máscara);
  3. aplica as regras do YAML como expectations (drop descarta, alerta só conta);
  4. grava conforme o modo de carga:
       incremental -> streaming table silver_<nome>, só acrescenta
       snapshot    -> AUTO CDC FROM SNAPSHOT: silver_<nome> com o estado atual e,
                      se historico: true, silver_<nome>_historico (SCD tipo 2)
       cdc         -> AUTO CDC com as mudanças, com os mesmos dois alvos
  5. regras "unico" viram a materialized view silver_<nome>_unico_<colunas>.

Nos modos snapshot e cdc as regras ficam na view limpa_<nome>, que alimenta o AUTO CDC.
"""

import sys

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

spark = SparkSession.getActiveSession()
sys.path.append(spark.conf.get("diretorio_codigo"))

from essentials.config_fontes import (
    carregar_fontes,
    colunas_tecnicas,
    expectations,
    expressoes_silver,
    literal_sql,
    propriedades_tabela,
    regras_unico,
    tabelas_da_fonte,
)

FONTES = carregar_fontes(spark.conf.get("fontes_config"))


def limpar(df: DataFrame, fonte: dict) -> DataFrame:
    return df.selectExpr(*expressoes_silver(fonte, df.dtypes))


def com_expectations(funcao, fonte: dict):
    descartar, alertar = expectations(fonte)
    if descartar:
        funcao = dp.expect_all_or_drop(descartar)(funcao)
    if alertar:
        funcao = dp.expect_all(alertar)(funcao)
    return funcao


def manter_ultimo_arquivo(df: DataFrame) -> DataFrame:
    """No modo snapshot, cada arquivo é um retrato completo: vale só o mais recente."""
    if "_arquivo_origem" not in df.columns:
        return df
    ultimo = (
        df.select("_arquivo_origem", "_ingerido_em")
        .distinct()
        .orderBy(F.desc("_ingerido_em"), F.desc("_arquivo_origem"))
        .limit(1)
    )
    return df.join(ultimo.select("_arquivo_origem"), "_arquivo_origem", "left_semi")


def manter_versao_mais_recente(df: DataFrame, fonte: dict) -> DataFrame:
    """O AUTO CDC FROM SNAPSHOT exige chave única dentro do retrato."""
    janela = Window.partitionBy(*fonte["chave_primaria"]).orderBy(F.col(fonte["coluna_atualizacao"]).desc_nulls_last())
    return df.withColumn("_ordem", F.row_number().over(janela)).where("_ordem = 1").drop("_ordem")


def sem_colunas_auxiliares(df: DataFrame, fonte: dict) -> DataFrame:
    """Tira colunas auxiliares da preparação (como _linha), mantendo as técnicas."""
    tecnicas = set(colunas_tecnicas(fonte))
    return df.drop(*[coluna for coluna in df.columns if coluna.startswith("_") and coluna not in tecnicas])


def criar_alvos_auto_cdc(fonte: dict) -> None:
    tabelas = tabelas_da_fonte(fonte)
    alvos = [(tabelas["silver"], 1, "estado atual de cada registro")]
    if tabelas["historico"]:
        alvos.append((tabelas["historico"], 2, "histórico de versões (SCD tipo 2, colunas __START_AT e __END_AT)"))

    for nome, tipo_scd, descricao in alvos:
        dp.create_streaming_table(
            name=nome,
            comment=f"Silver de {fonte['nome']}, {descricao}: {fonte['descricao']}",
            table_properties=propriedades_tabela("silver", fonte),
        )
        # As colunas técnicas mudam a cada carga e não devem gerar nova versão no histórico.
        ignorar_no_historico = colunas_tecnicas(fonte) if tipo_scd == 2 else None
        if fonte["modo_carga"] == "snapshot":
            dp.create_auto_cdc_from_snapshot_flow(
                target=nome,
                source=tabelas["limpa"],
                keys=fonte["chave_primaria"],
                stored_as_scd_type=tipo_scd,
                track_history_except_column_list=ignorar_no_historico,
            )
        else:
            cdc = fonte["cdc"]
            dp.create_auto_cdc_flow(
                target=nome,
                source=tabelas["limpa"],
                keys=fonte["chave_primaria"],
                sequence_by=F.col(fonte["coluna_atualizacao"]),
                apply_as_deletes=F.expr(f"`{cdc['coluna_operacao']}` = {literal_sql(cdc['valor_exclusao'])}"),
                except_column_list=[cdc["coluna_operacao"]],
                stored_as_scd_type=tipo_scd,
                track_history_except_column_list=ignorar_no_historico,
            )


def criar_checagem_unicidade(fonte: dict, regra: dict, nome: str) -> None:
    silver = tabelas_da_fonte(fonte)["silver"]

    def contagem_por_chave() -> DataFrame:
        return spark.read.table(silver).groupBy(*regra["colunas"]).agg(F.count("*").alias("quantidade"))

    dp.materialized_view(
        name=nome,
        comment=f"Checagem da regra {regra['nome']}: quantos registros de {silver} existem para cada valor de "
        f"{', '.join(regra['colunas'])}. Cada linha com quantidade maior que 1 conta como alerta.",
        table_properties=propriedades_tabela("silver", fonte),
    )(dp.expect_all({regra["nome"]: "quantidade = 1"})(contagem_por_chave))


def criar_silver(fonte: dict) -> None:
    tabelas = tabelas_da_fonte(fonte)
    origem = tabelas["preparada"] or tabelas["bronze"]
    modo = fonte["modo_carga"]

    if modo == "incremental":

        def silver_incremental() -> DataFrame:
            return limpar(spark.readStream.table(origem), fonte)

        dp.table(
            name=tabelas["silver"],
            comment=f"Silver de {fonte['nome']}, limpa e padronizada: {fonte['descricao']}",
            table_properties=propriedades_tabela("silver", fonte),
        )(com_expectations(silver_incremental, fonte))

    elif modo == "snapshot":

        def retrato_limpo() -> DataFrame:
            df = limpar(manter_ultimo_arquivo(spark.read.table(origem)), fonte)
            return sem_colunas_auxiliares(manter_versao_mais_recente(df, fonte), fonte)

        dp.temporary_view(name=tabelas["limpa"])(com_expectations(retrato_limpo, fonte))
        criar_alvos_auto_cdc(fonte)

    else:

        def mudancas_limpas() -> DataFrame:
            df = spark.readStream.table(origem)
            if fonte["tipo"] == "tabela":
                # No change data feed, a imagem anterior de um UPDATE não é uma mudança nova.
                df = df.where("_change_type != 'update_preimage'")
            return limpar(df, fonte)

        dp.temporary_view(name=tabelas["limpa"])(com_expectations(mudancas_limpas, fonte))
        criar_alvos_auto_cdc(fonte)

    for regra, nome in zip(regras_unico(fonte), tabelas["unicidade"], strict=True):
        criar_checagem_unicidade(fonte, regra, nome)


for fonte in FONTES:
    criar_silver(fonte)
