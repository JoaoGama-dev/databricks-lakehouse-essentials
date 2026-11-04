"""SQL da governança no Unity Catalog (docs/adr/0002).

Funções puras, sem Spark, para serem testadas pelo pytest. Quem executa é
src/governanca/governanca.py, como tarefa do job:
  - antes do pipeline: cria a função de máscara usada pelas colunas sensíveis da gold;
  - depois do pipeline: cria as views da gold (src/views/gold_vw_*.sql), aplica a tag
    "pii" nas colunas sensíveis da silver e da gold e copia as TBLPROPERTIES camada e
    tipo de cada tabela e view publicada para as tags do Unity Catalog.
"""

from __future__ import annotations

import re
from pathlib import Path

from essentials.config_fontes import colunas_sensiveis, literal_sql, tabelas_da_fonte, validada_publicada

FUNCAO_MASCARA = "mascarar_dado_pessoal"
TAG_PII = "pii"
# TBLPROPERTIES que viram tag do Unity Catalog: a fonte da verdade é o código (pipeline e
# views); a tag é só a cópia que o catálogo mostra e filtra.
TAGS_DA_TABELA = ("camada", "tipo")
# Comando ALTER de cada tipo de objeto (information_schema.tables.table_type).
ALTER_POR_TIPO_DE_OBJETO = {
    "STREAMING_TABLE": "ALTER STREAMING TABLE",
    "MATERIALIZED_VIEW": "ALTER MATERIALIZED VIEW",
    "VIEW": "ALTER VIEW",
    "MANAGED": "ALTER TABLE",
    "EXTERNAL": "ALTER TABLE",
}
PASTA_VIEWS = "views"
PADRAO_VIEW_GOLD = "gold_vw_*.sql"


def nome_completo(*partes: str) -> str:
    return ".".join(f"`{parte}`" for parte in partes)


def sql_funcao_mascara(catalogo: str, schema: str, grupo_dados_pessoais: str) -> str:
    """Função de máscara: o grupo de dados pessoais vê o valor; os demais veem ****.

    O grupo pode ser um grupo da conta (no cliente) ou um usuário (no Free Edition).
    """
    grupo = literal_sql(grupo_dados_pessoais)
    return (
        f"CREATE OR REPLACE FUNCTION {nome_completo(catalogo, schema, FUNCAO_MASCARA)}(valor STRING)\n"
        "RETURNS STRING\n"
        "COMMENT 'Máscara de dado pessoal (LGPD): só o grupo de dados pessoais vê o valor.'\n"
        f"RETURN CASE WHEN is_account_group_member({grupo}) OR current_user() = {grupo} "
        "THEN valor ELSE '****' END"
    )


def tabelas_silver_da_fonte(fonte: dict) -> list[str]:
    """Tabelas publicadas da silver que guardam as colunas da fonte com o nome padronizado.

    O retrato do snapshot é privado do pipeline: não está no catálogo, não recebe tag.
    """
    tabelas = tabelas_da_fonte(fonte)
    validada = tabelas["validada"] if validada_publicada(fonte) else None
    return [nome for nome in (validada, tabelas["silver"]) if nome]


def sql_tag_pii(catalogo: str, schema: str, tabela: str, coluna: str) -> str:
    return (
        f"ALTER TABLE {nome_completo(catalogo, schema, tabela)} "
        f"ALTER COLUMN `{coluna}` SET TAGS ('{TAG_PII}' = 'true')"
    )


def sql_tag_pii_em_view(catalogo: str, schema: str, view: str, coluna: str) -> str:
    """ALTER VIEW não altera coluna: SET TAG ON COLUMN, que falha se a tag já existir."""
    return f"SET TAG ON COLUMN {nome_completo(catalogo, schema, view, coluna)} `{TAG_PII}` = `true`"


def sqls_tags_pii(
    catalogo: str,
    schema_silver: str,
    schema_gold: str,
    fontes: list[dict],
    objetos_gold: dict[str, tuple[str, list[str]]],
    ja_marcadas: set[tuple[str, str]] | frozenset = frozenset(),
) -> list[str]:
    """Tags pii nas colunas sensíveis da silver e nas colunas de mesmo nome da gold.

    objetos_gold: {nome: (table_type, [colunas])} do schema gold, lido do information_schema
    na hora. Tabelas internas do Databricks (que começam com "__", como as de materialização
    das materialized views) ficam de fora. Nas views, a tag só é aplicada onde ainda não
    existe (ja_marcadas: {(view, coluna)} de information_schema.column_tags), porque o
    SET TAG ON COLUMN recusa uma tag repetida.
    """
    sensiveis = {coluna for fonte in fontes for coluna in colunas_sensiveis(fonte)}
    comandos = [
        sql_tag_pii(catalogo, schema_silver, tabela, coluna)
        for fonte in fontes
        for tabela in tabelas_silver_da_fonte(fonte)
        for coluna in colunas_sensiveis(fonte)
    ]
    for nome, (tipo_objeto, colunas) in sorted(objetos_gold.items()):
        if nome.startswith("__"):
            continue
        for coluna in colunas:
            if coluna not in sensiveis:
                continue
            if tipo_objeto == "VIEW":
                if (nome, coluna) not in ja_marcadas:
                    comandos.append(sql_tag_pii_em_view(catalogo, schema_gold, nome, coluna))
            else:
                comandos.append(sql_tag_pii(catalogo, schema_gold, nome, coluna))
    return comandos


def sql_tags_da_tabela(
    catalogo: str, schema: str, tabela: str, tipo_objeto: str, propriedades: dict[str, str]
) -> str | None:
    """ALTER <tipo> ... SET TAGS com camada e tipo, lidos das TBLPROPERTIES do objeto.

    Sem as duas propriedades (o event log, por exemplo), ou tabela interna (começa com
    "__"), não há o que copiar: devolve None.
    """
    comando = ALTER_POR_TIPO_DE_OBJETO.get(tipo_objeto)
    if tabela.startswith("__") or comando is None or not all(propriedades.get(tag) for tag in TAGS_DA_TABELA):
        return None
    tags = ", ".join(f"{literal_sql(tag)} = {literal_sql(propriedades[tag])}" for tag in TAGS_DA_TABELA)
    return f"{comando} {nome_completo(catalogo, schema, tabela)} SET TAGS ({tags})"


def arquivos_views_gold(codigo: str | Path) -> list[Path]:
    """Views da gold criadas depois do pipeline: src/views/gold_vw_*.sql, em ordem."""
    return sorted((Path(codigo) / PASTA_VIEWS).glob(PADRAO_VIEW_GOLD))


def sqls_views_gold(codigo: str | Path, catalogo: str, schema_gold: str) -> list[str]:
    """Comandos das views da gold, com o catálogo e o schema gold do target.

    Tira as linhas de comentário e separa os comandos pelo ";" no fim da linha (pode haver
    ";" dentro de um COMMENT).
    """
    comandos = []
    for arquivo in arquivos_views_gold(codigo):
        texto = "\n".join(
            linha for linha in arquivo.read_text(encoding="utf-8").splitlines() if not linha.lstrip().startswith("--")
        )
        texto = texto.replace("${catalogo}", f"`{catalogo}`").replace("${schema_gold}", f"`{schema_gold}`")
        comandos += [comando.strip() for comando in re.split(r";[ \t]*(?:\n|$)", texto) if comando.strip()]
    return comandos
