"""SQL da governança de dados pessoais no Unity Catalog (docs/adr/0002).

Funções puras, sem Spark, para serem testadas pelo pytest. Quem executa é
src/governanca/governanca.py, como tarefa do job:
  - antes do pipeline: cria a função de máscara usada pelas colunas sensíveis da gold;
  - depois do pipeline: aplica a tag "pii" nas colunas sensíveis da silver e da gold.
"""

from __future__ import annotations

from essentials.config_fontes import colunas_sensiveis, literal_sql, tabelas_da_fonte

FUNCAO_MASCARA = "mascarar_dado_pessoal"
TAG_PII = "pii"


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
    """Tabelas da silver que guardam as colunas da fonte com o nome padronizado."""
    tabelas = tabelas_da_fonte(fonte)
    return [nome for nome in (tabelas["validada"], tabelas["silver"], tabelas["historico"]) if nome]


def sql_tag_pii(catalogo: str, schema: str, tabela: str, coluna: str) -> str:
    return (
        f"ALTER TABLE {nome_completo(catalogo, schema, tabela)} "
        f"ALTER COLUMN `{coluna}` SET TAGS ('{TAG_PII}' = 'true')"
    )


def sqls_tags_pii(
    catalogo: str,
    schema: str,
    schema_gold: str,
    fontes: list[dict],
    colunas_gold: dict[str, list[str]],
) -> list[str]:
    """Tags pii nas colunas sensíveis da silver e nas colunas de mesmo nome da gold.

    colunas_gold: {tabela: [colunas]} do schema gold, lido do information_schema na hora.
    Tabelas internas do Databricks (que começam com "__", como as de materialização das
    materialized views) ficam de fora.
    """
    sensiveis = {coluna for fonte in fontes for coluna in colunas_sensiveis(fonte)}
    comandos = [
        sql_tag_pii(catalogo, schema, tabela, coluna)
        for fonte in fontes
        for tabela in tabelas_silver_da_fonte(fonte)
        for coluna in colunas_sensiveis(fonte)
    ]
    comandos += [
        sql_tag_pii(catalogo, schema_gold, tabela, coluna)
        for tabela, colunas in sorted(colunas_gold.items())
        if not tabela.startswith("__")
        for coluna in colunas
        if coluna in sensiveis
    ]
    return comandos
