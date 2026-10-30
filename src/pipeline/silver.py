"""Silver genérica: limpeza padrão e regras de qualidade de cada fonte do config/fontes.yml.

Para cada fonte:
  1. lê a bronze, ou a view silver_int_<nome>_preparada quando há src/pipeline/silver_<nome>.sql;
  2. aplica a limpeza padrão (TRIM, tipos, datas em mais de um formato, de-para, máscara)
     e dá às colunas os nomes padronizados do YAML (dt_, nm_, st_...);
  3. aplica as regras do YAML como expectations (drop descarta, alerta só conta);
  4. grava conforme o modo de carga:
       incremental -> streaming table silver_<nome>, com as regras, só acrescenta
       snapshot    -> materialized view silver_int_<nome>_retrato, com as regras, e
                      AUTO CDC FROM SNAPSHOT para silver_<nome> (estado atual) e, se
                      historico: true, silver_<nome>_historico (SCD tipo 2)
       cdc         -> streaming table silver_int_<nome>_mudancas, com as regras, e
                      AUTO CDC para os mesmos dois alvos
  5. regras "unico" viram a materialized view silver_int_<nome>_unico_<colunas>.

As regras ficam numa tabela intermediária, e não numa view, porque o AUTO CDC FROM
SNAPSHOT lê a origem como um retrato e não aplica nem registra expectations de views.
"""

import operator
import sys
from functools import reduce

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

spark = SparkSession.getActiveSession()
sys.path.append(spark.conf.get("diretorio_codigo"))

# O pacote essentials só fica importável depois do sys.path.append acima, que aponta
# para a pasta src/ do bundle no workspace; por isso o import não está no topo.
from essentials.config_fontes import (  # noqa: E402
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
    """O AUTO CDC FROM SNAPSHOT exige chave única dentro do retrato.

    Registros com chave incompleta não são deduplicados: seguem para as regras
    nao_nulo da chave, que os descartam e os contam na aba Data quality.
    """
    chave = fonte["chave_primaria"]
    janela = Window.partitionBy(*chave).orderBy(F.col(fonte["coluna_atualizacao"]).desc_nulls_last())
    chave_incompleta = reduce(operator.or_, [F.col(coluna).isNull() for coluna in chave])
    return (
        df.withColumn("_ordem", F.row_number().over(janela))
        .where((F.col("_ordem") == 1) | chave_incompleta)
        .drop("_ordem")
    )


def sem_colunas_auxiliares(df: DataFrame, fonte: dict) -> DataFrame:
    """Tira colunas auxiliares da preparação (como _linha), mantendo as técnicas."""
    tecnicas = set(colunas_tecnicas(fonte))
    return df.drop(*[coluna for coluna in df.columns if coluna.startswith("_") and coluna not in tecnicas])


def criar_alvos_auto_cdc(fonte: dict) -> None:
    tabelas = tabelas_da_fonte(fonte)
    alvos = [(tabelas["silver"], 1, "atual", "estado atual de cada registro")]
    if tabelas["historico"]:
        alvos.append(
            (tabelas["historico"], 2, "historico", "histórico de versões (SCD tipo 2, colunas __START_AT e __END_AT)")
        )

    for nome, tipo_scd, tipo_tabela, descricao in alvos:
        dp.create_streaming_table(
            name=nome,
            comment=f"Silver de {fonte['nome']}, {descricao}: {fonte['descricao']}",
            table_properties=propriedades_tabela("silver", tipo_tabela, fonte),
        )
        # As colunas técnicas mudam a cada carga e não devem gerar nova versão no histórico.
        ignorar_no_historico = colunas_tecnicas(fonte) if tipo_scd == 2 else None
        if fonte["modo_carga"] == "snapshot":
            dp.create_auto_cdc_from_snapshot_flow(
                target=nome,
                source=tabelas["validada"],
                keys=fonte["chave_primaria"],
                stored_as_scd_type=tipo_scd,
                track_history_except_column_list=ignorar_no_historico,
            )
        else:
            cdc = fonte["cdc"]
            dp.create_auto_cdc_flow(
                target=nome,
                source=tabelas["validada"],
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
        return spark.read.table(silver).groupBy(*regra["colunas"]).agg(F.count("*").alias("qt_registros"))

    dp.materialized_view(
        name=nome,
        comment=f"Checagem da regra {regra['nome']}: quantos registros de {silver} existem para cada valor de "
        f"{', '.join(regra['colunas'])}. Cada linha com qt_registros maior que 1 conta como alerta.",
        table_properties=propriedades_tabela("silver", "intermediaria", fonte),
    )(dp.expect_all({regra["nome"]: "qt_registros = 1"})(contagem_por_chave))


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
            table_properties=propriedades_tabela("silver", "atual", fonte),
        )(com_expectations(silver_incremental, fonte))

    elif modo == "snapshot":

        def retrato_validado() -> DataFrame:
            df = limpar(manter_ultimo_arquivo(spark.read.table(origem)), fonte)
            return sem_colunas_auxiliares(manter_versao_mais_recente(df, fonte), fonte)

        dp.materialized_view(
            name=tabelas["validada"],
            comment=f"Último retrato de {fonte['nome']}, limpo e com as regras de qualidade aplicadas; "
            f"alimenta o AUTO CDC de {tabelas['silver']}.",
            table_properties=propriedades_tabela("silver", "intermediaria", fonte),
        )(com_expectations(retrato_validado, fonte))
        criar_alvos_auto_cdc(fonte)

    else:

        def mudancas_validadas() -> DataFrame:
            df = spark.readStream.table(origem)
            if fonte["tipo"] == "tabela":
                # No change data feed, a imagem anterior de um UPDATE não é uma mudança nova.
                df = df.where("_change_type != 'update_preimage'")
            return limpar(df, fonte)

        dp.table(
            name=tabelas["validada"],
            comment=f"Mudanças de {fonte['nome']}, limpas e com as regras de qualidade aplicadas; "
            f"alimentam o AUTO CDC de {tabelas['silver']}.",
            table_properties=propriedades_tabela("silver", "intermediaria", fonte),
        )(com_expectations(mudancas_validadas, fonte))
        criar_alvos_auto_cdc(fonte)

    for regra, nome in zip(regras_unico(fonte), tabelas["unicidade"], strict=True):
        criar_checagem_unicidade(fonte, regra, nome)


for fonte in FONTES:
    criar_silver(fonte)
