"""Gera, para revisão humana, o SQL de exclusão dos dados de um titular (LGPD, art. 18).

NÃO EXECUTA NADA: não conecta ao Databricks, não usa rede e não recebe o dado da pessoa.
O SQL gerado usa marcadores de parâmetro nomeados (:titular_<coluna>, um por coluna que
identifica a pessoa), preenchidos por quem roda no SQL editor do Databricks. Assim a saída
pode ser revisada, versionada e anexada ao chamado sem conter dado pessoal.

As tabelas e colunas vêm do config/fontes.yml: a pessoa é identificada pelas colunas com
sensivel: true e sem mascarar (as mascaradas não guardam o valor completo para comparar).
O valor informado passa pela mesma limpeza da silver (TRIM, caixa, ponto final), então
pode ser digitado como veio na origem.

Passos gerados, na ordem: 1 landing, 2 bronze, 3 silver, 4 aviso sobre leituras em
streaming, 5 atualização do pipeline (gold e retrato), 6 REORG ... APPLY (PURGE),
7 VACUUM. Referência: https://docs.databricks.com/aws/en/ldp/gdpr

Uso:
    python scripts/gerar_exclusao_titular.py --fonte agenda --catalogo essentials \\
        --schema-bronze portfolio_bronze --schema-silver portfolio_silver \\
        --schema-gold portfolio_gold [--saida exclusao.sql]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from essentials.config_fontes import (  # noqa: E402
    carregar_fontes,
    expressao_limpeza,
    formato_landing,
    nome_tabela_origem,
    pasta_landing,
    tabelas_da_fonte,
    validada_publicada,
)

CONFIG = RAIZ / "config" / "fontes.yml"
PASTA_PIPELINE = RAIZ / "src" / "pipeline"
# Volume da landing em resources/governanca.yml (no schema da bronze).
VOLUME_LANDING = "landing"
IDENTIFICADOR = re.compile(r"[a-z0-9_]+")
PADRAO_GOLD = re.compile(
    r"CREATE OR REFRESH MATERIALIZED VIEW\s+(?:\$\{catalogo\}\.)?\$\{schema_gold\}\.(\w+)", re.IGNORECASE
)
# Formatos em que a bronze tem as colunas da origem (o DELETE compara coluna a coluna).
FORMATOS_COM_COLUNAS = {"csv", "json", "parquet", "excel"}
# Separadores de campo aceitos numa linha de arquivo texto (a agenda usa ";"). O ";" vai como
# o escape unicode 003B, que o Spark SQL converte no literal: um ";" cru cortaria o comando
# em ferramentas que separam os comandos pelo ";". chr(92) é a barra invertida.
SEPARADORES_TEXTO = "[" + chr(92) + "u003B," + chr(92) + "t|]"


class IdentificadorInvalido(ValueError):
    """Catálogo, schema ou fonte fora do padrão [a-z0-9_]+."""


def validar_identificador(valor: str, nome: str) -> str:
    if not isinstance(valor, str) or not IDENTIFICADOR.fullmatch(valor):
        raise IdentificadorInvalido(f"{nome} {valor!r} inválido: use só letras minúsculas, dígitos e _")
    return valor


def colunas_do_titular(fonte: dict) -> dict[str, dict]:
    """Colunas que identificam a pessoa: sensíveis e sem máscara, na ordem do YAML."""
    colunas = {
        coluna: configuracao
        for coluna, configuracao in fonte["colunas"].items()
        if configuracao.get("sensivel") and not configuracao.get("mascarar")
    }
    if not colunas:
        raise ValueError(
            f"a fonte {fonte['nome']} não tem coluna com sensivel: true sem mascarar para identificar o titular; "
            "escreva a exclusão à mão a partir do roteiro de docs/padroes/lgpd.md"
        )
    return colunas


def parametro(coluna: str) -> str:
    return f":titular_{coluna}"


def valor_limpo(coluna: str, configuracao: dict) -> str:
    """O parâmetro com a mesma limpeza que a coluna recebe na silver (expressao_limpeza)."""
    origem = f"`{configuracao['origem']}`"
    expressao = expressao_limpeza(configuracao["origem"], configuracao)
    return expressao.replace(origem, parametro(coluna))


def guarda_parametro_vazio(fonte: dict) -> str:
    """Parâmetro esquecido ou em branco não casa com nada (sem isso, campo vazio = valor vazio)."""
    return " AND ".join(f"length(trim({parametro(coluna)})) > 0" for coluna in colunas_do_titular(fonte))


def condicao_silver(fonte: dict) -> str:
    comparacoes = (
        f"`{coluna}` = {valor_limpo(coluna, configuracao)}"
        for coluna, configuracao in colunas_do_titular(fonte).items()
    )
    return " AND ".join([guarda_parametro_vazio(fonte), *comparacoes])


def condicao_bronze_por_coluna(fonte: dict) -> str:
    """Na bronze com as colunas da origem: a mesma limpeza dos dois lados da comparação."""
    comparacoes = (
        f"{expressao_limpeza(configuracao['origem'], configuracao)} = {valor_limpo(coluna, configuracao)}"
        for coluna, configuracao in colunas_do_titular(fonte).items()
    )
    return " AND ".join([guarda_parametro_vazio(fonte), *comparacoes])


def condicao_linha_de_texto(fonte: dict) -> str:
    """A linha do arquivo tem um CAMPO igual ao titular, com a limpeza da silver dos dois lados.

    Igualdade do campo inteiro, nunca pedaço do texto: "Ana" não casa com "Mariana"."""
    comparacoes = []
    for coluna, configuracao in colunas_do_titular(fonte).items():
        campo = expressao_limpeza(configuracao["origem"], configuracao).replace(f"`{configuracao['origem']}`", "campo")
        comparacoes.append(
            f"exists(split(linha, '{SEPARADORES_TEXTO}'), campo -> {campo} = {valor_limpo(coluna, configuracao)})"
        )
    return " AND ".join([guarda_parametro_vazio(fonte), *comparacoes])


def nome_completo(catalogo: str, schema: str, tabela: str) -> str:
    return f"`{catalogo}`.`{schema}`.`{tabela}`"


def tabelas_gold() -> list[str]:
    return sorted({nome for arquivo in PASTA_PIPELINE.glob("gold_*.sql") for nome in PADRAO_GOLD.findall(
        arquivo.read_text(encoding="utf-8"))})


# Passos ----------------------------------------------------------------------------


def passo_landing(fonte: dict, catalogo: str, schema_bronze: str) -> list[str]:
    linhas = ["-- PASSO 1. Landing: os arquivos originais que contêm o titular."]
    if fonte["tipo"] == "tabela":
        origem = nome_tabela_origem(fonte, catalogo, "<projeto>")
        return [
            *linhas,
            f"-- A fonte é a tabela {origem} (sistema de origem): a exclusão nela é do dono do sistema.",
            "-- Sem isso, a próxima carga traz o titular de volta.",
        ]
    pasta = f"/Volumes/{catalogo}/{schema_bronze}/{VOLUME_LANDING}/{pasta_landing(fonte)}/"
    return [
        *linhas,
        f"-- Liste os arquivos da pasta {pasta} (no Catalog Explorer ou com LIST '{pasta}')",
        "-- e, em cada arquivo que cita o titular, reescreva o arquivo sem as linhas dele ou apague",
        "-- só esse arquivo. Nunca apague a pasta inteira: os outros arquivos são o histórico da fonte.",
        "-- O Auto Loader não relê um arquivo reescrito com o mesmo nome (cloudFiles.allowOverwrites",
        "-- desligado por padrão): a bronze é corrigida no passo 2, não pela releitura.",
    ]


def passo_bronze(fonte: dict, catalogo: str, schema_bronze: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Linhas do passo 2 e as tabelas alteradas por DML, como (schema, tabela)."""
    bronze = tabelas_da_fonte(fonte)["bronze"]
    tabela = nome_completo(catalogo, schema_bronze, bronze)
    linhas = ["-- PASSO 2. Bronze."]
    formato = formato_landing(fonte)
    if fonte["tipo"] == "tabela" and fonte["modo_carga"] == "snapshot":
        return [
            *linhas,
            f"-- {bronze} é uma materialized view da tabela de origem: não aceita DELETE. Depois da",
            "-- exclusão na origem (passo 1), ela é recalculada na atualização do pipeline (passo 5).",
        ], []
    if formato == "texto":
        condicao = condicao_linha_de_texto(fonte)
        return [
            *linhas,
            f"-- Em {bronze}, cada linha é um ARQUIVO inteiro (coluna value). Apagar a linha apagaria",
            "-- todas as pessoas do arquivo, e no snapshot o retrato voltaria para um arquivo mais",
            "-- antigo, que também cita o titular. Por isso o UPDATE tira do texto só as linhas que",
            "-- citam o titular e mantém o resto do arquivo como chegou (quebras de linha e BOM).",
            "-- Confira antes quais arquivos e quantas linhas serão alterados. Se qt_linhas_do_titular",
            "-- passar do número de registros que o titular tem na silver (passo 3), PARE: o valor",
            "-- informado está casando com outra pessoa.",
            f"SELECT _arquivo_origem, size(filter(split(value, '\\n'), linha -> {condicao})) AS qt_linhas_do_titular",
            f"FROM {tabela}",
            f"WHERE exists(split(value, '\\n'), linha -> {condicao});",
            "",
            f"UPDATE {tabela}",
            f"SET value = array_join(filter(split(value, '\\n'), linha -> NOT ({condicao})), '\\n')",
            f"WHERE exists(split(value, '\\n'), linha -> {condicao});",
        ], [(schema_bronze, bronze)]
    if fonte.get("preparacao_sql") or formato not in FORMATOS_COM_COLUNAS | {None}:
        return [
            *linhas,
            f"-- {bronze} passa por src/pipeline/silver_{fonte['nome']}.sql antes da limpeza: as colunas",
            "-- da origem não são as do fontes.yml. Escreva a condição do DELETE à mão, revisada.",
        ], []
    condicao = condicao_bronze_por_coluna(fonte)
    return [
        *linhas,
        f"-- {bronze} tem as colunas da origem: a mesma limpeza da silver dos dois lados.",
        f"SELECT count(*) AS qt_linhas FROM {tabela} WHERE {condicao};",
        f"DELETE FROM {tabela} WHERE {condicao};",
    ], [(schema_bronze, bronze)]


def passo_silver(fonte: dict, catalogo: str, schema_silver: str) -> tuple[list[str], list[tuple[str, str]]]:
    tabelas = tabelas_da_fonte(fonte)
    condicao = condicao_silver(fonte)
    linhas = ["-- PASSO 3. Silver (com historico: true, a silver guarda todas as versões do titular)."]
    alvos = [tabelas["silver"]]
    if fonte["modo_carga"] == "snapshot":
        privada = "" if validada_publicada(fonte) else " privada do pipeline (não está no catálogo)"
        linhas += [
            f"-- {tabelas['validada']} é uma materialized view{privada}, o retrato: não aceita DELETE e é",
            "-- recalculada da bronze corrigida no passo 5.",
        ]
    elif tabelas["validada"]:
        alvos.insert(0, tabelas["validada"])
    for tabela in alvos:
        completo = nome_completo(catalogo, schema_silver, tabela)
        linhas += [
            f"-- {tabela}",
            f"SELECT count(*) AS qt_linhas FROM {completo} WHERE {condicao};",
            f"DELETE FROM {completo} WHERE {condicao};",
        ]
    if tabelas["unicidade"]:
        linhas.append(f"-- {', '.join(tabelas['unicidade'])}: materialized views, recalculadas no passo 5.")
    return linhas, [(schema_silver, tabela) for tabela in alvos]


def passo_streaming(fonte: dict, alteradas: list[tuple[str, str]]) -> list[str]:
    tabelas = tabelas_da_fonte(fonte)
    linhas = [
        "-- PASSO 4. Aviso: leituras em streaming de tabelas alteradas por DML.",
        "-- Quem lê em streaming uma streaming table que recebeu UPDATE ou DELETE falha na próxima",
        "-- leitura, a menos que leia com a opção skipChangeCommits (docs.databricks.com/aws/en/ldp/gdpr).",
    ]
    if fonte["modo_carga"] == "snapshot":
        linhas += [
            f"-- Neste pipeline: {tabelas['bronze']} é lida em lote pelo retrato (materialized view), e",
            f"-- {tabelas['silver']} é alvo do AUTO CDC e lida em lote pela gold: nenhuma leitura em",
            "-- streaming do próprio pipeline quebra.",
        ]
    else:
        origem = tabelas["preparada"] or tabelas["bronze"]
        leitor = tabelas["validada"] or tabelas["silver"]
        linhas += [
            f"-- ATENÇÃO: src/pipeline/silver.py lê {origem} em streaming (readStream) para {leitor}, sem",
            "-- skipChangeCommits: a próxima atualização falha depois do DML na bronze. Não rode este",
            "-- roteiro até a opção entrar no código (pendência registrada).",
        ]
        if fonte["modo_carga"] == "cdc":
            linhas.append(f"-- O AUTO CDC também lê {tabelas['validada']} em streaming: vale o mesmo aviso.")
    return [
        *linhas,
        "-- Fora do pipeline: confira se algum job ou notebook lê estas tabelas em streaming:",
        f"-- {', '.join(tabela for _, tabela in alteradas)}.",
    ]


def passo_pipeline(fonte: dict) -> list[str]:
    tabelas = tabelas_da_fonte(fonte)
    recalculadas = [t for t in [tabelas["validada"] if fonte["modo_carga"] == "snapshot" else None,
                                *tabelas["unicidade"]] if t]
    return [
        "-- PASSO 5. Gold e materialized views: rode uma atualização normal do pipeline",
        "-- <projeto>_pipeline_medalhao (a carga diária ou o botão Start; não use full refresh). As",
        "-- materialized views tratam as exclusões sozinhas, mas só no próximo recálculo:",
        f"-- {', '.join([*recalculadas, *tabelas_gold()])}.",
        "-- Depois, confira na gold que o titular sumiu (com o mesmo parâmetro, como no passo 3).",
    ]


def passo_reorg(alteradas: list[tuple[str, str]], catalogo: str) -> list[str]:
    return [
        "-- PASSO 6. Tirar o dado dos arquivos de dados: com deletion vectors, o DELETE e o UPDATE só",
        "-- marcam as linhas como apagadas; o REORG reescreve os arquivos sem elas.",
        *(f"REORG TABLE {nome_completo(catalogo, schema, tabela)} APPLY (PURGE);" for schema, tabela in alteradas),
    ]


def passo_vacuum(alteradas: list[tuple[str, str]], catalogo: str) -> list[str]:
    return [
        "-- PASSO 7. Apagar de vez os arquivos antigos. Até aqui, o dado apagado ainda pode ser lido",
        "-- pelo time travel (versões anteriores da tabela). O VACUUM só remove arquivos fora do prazo",
        "-- de retenção (delta.deletedFileRetentionDuration, 7 dias por padrão; o histórico da tabela",
        "-- fica 30 dias por padrão): rode este passo DEPOIS desse prazo, contado do passo 6. Confira o",
        "-- prazo com SHOW TBLPROPERTIES (delta.deletedFileRetentionDuration e delta.logRetentionDuration)",
        "-- e não reduza a retenção sem uma decisão registrada. Anote no chamado a data do passo 6: a",
        "-- exclusão só termina depois deste passo. Rode antes o DRY RUN para ver o que será apagado.",
        "-- As materialized views (passo 5) dependem da manutenção do próprio pipeline (otimização",
        "-- preditiva) para limpar os arquivos antigos.",
        *(f"VACUUM {nome_completo(catalogo, schema, tabela)} DRY RUN;" for schema, tabela in alteradas),
        *(f"VACUUM {nome_completo(catalogo, schema, tabela)};" for schema, tabela in alteradas),
    ]


def gerar_sql(fonte: dict, catalogo: str, schema_bronze: str, schema_silver: str, schema_gold: str) -> str:
    for valor, nome in (
        (catalogo, "catálogo"),
        (schema_bronze, "schema da bronze"),
        (schema_silver, "schema da silver"),
        (schema_gold, "schema da gold"),
    ):
        validar_identificador(valor, nome)
    colunas = colunas_do_titular(fonte)
    bronze, alteradas_bronze = passo_bronze(fonte, catalogo, schema_bronze)
    silver, alteradas_silver = passo_silver(fonte, catalogo, schema_silver)
    alteradas = alteradas_bronze + alteradas_silver
    cabecalho = [
        f"-- Exclusão dos dados de um titular na fonte {fonte['nome']}",
        f"-- ({catalogo}.{schema_bronze}, {catalogo}.{schema_silver} e {catalogo}.{schema_gold}).",
        "-- Gerado por scripts/gerar_exclusao_titular.py para REVISÃO HUMANA: nada foi executado.",
        "-- Rode passo a passo no SQL editor, conferindo cada SELECT antes do DELETE ou UPDATE.",
        "-- Parâmetros (o editor abre um campo para cada um; o valor como veio na origem):",
        *(f"--   {parametro(coluna)}  {configuracao['descricao']}" for coluna, configuracao in colunas.items()),
        "-- Não grave o valor do parâmetro neste arquivo nem no chamado.",
    ]
    blocos = [
        cabecalho,
        passo_landing(fonte, catalogo, schema_bronze),
        bronze,
        silver,
        passo_streaming(fonte, alteradas),
        passo_pipeline(fonte),
        passo_reorg(alteradas, catalogo),
        passo_vacuum(alteradas, catalogo),
    ]
    return "\n\n".join("\n".join(bloco) for bloco in blocos) + "\n"


def argumentos(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fonte", required=True, help="nome da fonte no config/fontes.yml")
    parser.add_argument("--catalogo", required=True)
    parser.add_argument("--schema-bronze", required=True, help="schema da bronze (e da landing) do projeto")
    parser.add_argument("--schema-silver", required=True, help="schema da silver do projeto")
    parser.add_argument("--schema-gold", required=True)
    parser.add_argument("--config", default=str(CONFIG), help="caminho do config/fontes.yml")
    parser.add_argument("--saida", help="grava o SQL neste arquivo em vez de mostrar na tela")
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    opcoes = argumentos(args)
    validar_identificador(opcoes.fonte, "fonte")
    fontes = {fonte["nome"]: fonte for fonte in carregar_fontes(opcoes.config)}
    if opcoes.fonte not in fontes:
        raise SystemExit(f"fonte {opcoes.fonte!r} não está no config/fontes.yml ({', '.join(fontes)})")
    sql = gerar_sql(
        fontes[opcoes.fonte], opcoes.catalogo, opcoes.schema_bronze, opcoes.schema_silver, opcoes.schema_gold
    )
    if opcoes.saida:
        Path(opcoes.saida).write_text(sql, encoding="utf-8")
        print(f"SQL de exclusão gravado em {opcoes.saida}, para revisão. Nada foi executado.")
        print("Anexe ao chamado; não versione o arquivo no repositório.")
    else:
        # No Windows, o console usaria a página de código do sistema e trocaria os acentos.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(sql)


if __name__ == "__main__":
    try:
        main()
    except (IdentificadorInvalido, ValueError) as erro:
        sys.exit(f"Erro: {erro}")
