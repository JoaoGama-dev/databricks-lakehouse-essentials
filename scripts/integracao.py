"""Apoio aos testes de integração (.github/workflows/integracao.yml, docs/adr/0005).

Roda contra o target "ci" do bundle, só com os dados fictícios do gerador. Os nomes reais
dos recursos vêm do resumo do bundle, gravado pelo workflow depois do deploy:

    databricks bundle summary -t ci -o json > recursos-ci.json

Comandos:
    python scripts/integracao.py preparar           cria <projeto>_origem e esvazia a landing
    python scripts/integracao.py enviar --versao 1  envia data/agenda_exemplo_v1.csv (1 a 4)
    python scripts/integracao.py alterar-origem     cenário: a origem cargos ganha uma coluna
    python scripts/integracao.py limpar             apaga os schemas do CI que sobrarem

Por segurança, nada aqui toca num schema cujo nome não termine em _ci, _ci_gold ou
_ci_origem: o dev de quem roda fica intacto.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SETUP = RAIZ / "setup" / "00_setup_free_edition.sql"
ARQUIVO_RECURSOS = Path(os.environ.get("INTEGRACAO_RECURSOS", RAIZ / "recursos-ci.json"))
SUFIXOS_CI = ("_ci", "_ci_gold", "_ci_origem")
PASTA_AGENDA = "agenda"


class SchemaForaDoCI(ValueError):
    """Tentativa de mexer num schema que não é do CI."""


def verificar_schema_ci(schema: str) -> str:
    """Devolve o schema se ele for do CI; senão recusa."""
    if not re.fullmatch(r"[a-z0-9_]+", schema) or not schema.endswith(SUFIXOS_CI):
        raise SchemaForaDoCI(f"schema {schema!r} não é do CI (precisa terminar em {', '.join(SUFIXOS_CI)})")
    return schema


# Recursos do target ci ------------------------------------------------------------


def carregar_recursos(caminho: Path = ARQUIVO_RECURSOS) -> dict:
    """Nomes e IDs do target ci, a partir do resumo do bundle."""
    resumo = json.loads(caminho.read_text(encoding="utf-8-sig"))
    variaveis = {nome: valor.get("value") for nome, valor in resumo.get("variables", {}).items()}
    schemas = resumo["resources"]["schemas"]
    recursos = {
        "catalogo": schemas["projeto"]["catalog_name"],
        "schema": verificar_schema_ci(schemas["projeto"]["name"]),
        "schema_gold": verificar_schema_ci(schemas["gold"]["name"]),
        "projeto": variaveis["projeto"],
        "warehouse_id": variaveis["warehouse_id"],
        "job_id": resumo["resources"]["jobs"]["essentials_carga_diaria"].get("id"),
        "pipeline_id": resumo["resources"]["pipelines"]["essentials_pipeline"].get("id"),
    }
    recursos["schema_origem"] = verificar_schema_ci(f"{recursos['projeto']}_origem")
    recursos["landing"] = f"/Volumes/{recursos['catalogo']}/{recursos['schema']}/landing"
    return recursos


def projeto_do_bundle() -> str:
    """Valor padrão da variável projeto no databricks.yml (o projeto de dev)."""
    import yaml

    bundle = yaml.safe_load((RAIZ / "databricks.yml").read_text(encoding="utf-8"))
    return bundle["variables"]["projeto"]["default"]


def comandos_origem(catalogo: str, projeto_ci: str) -> list[str]:
    """Comandos do setup que criam a origem simulada, apontados para <projeto_ci>_origem.

    Usa o próprio setup/00_setup_free_edition.sql, para o CI e o dev lerem a mesma origem.
    """
    verificar_schema_ci(f"{projeto_ci}_origem")
    projeto = projeto_do_bundle()
    sql = SETUP.read_text(encoding="utf-8")
    sql = "\n".join(linha for linha in sql.splitlines() if not linha.lstrip().startswith("--"))
    origem_dev = f"essentials.{projeto}_origem"
    # Cada comando termina com ";" no fim da linha (há ";" dentro de textos de COMMENT).
    comandos = [comando.strip() for comando in re.split(r";[ \t]*(?:\n|$)", sql) if origem_dev in comando]
    return [comando.replace(origem_dev, f"`{catalogo}`.`{projeto_ci}_origem`") for comando in comandos]


# Databricks ------------------------------------------------------------------------


def cliente():
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


def executar_sql(w, warehouse_id: str, comando: str) -> list[dict]:
    """Executa um comando no SQL warehouse e devolve as linhas como dicionários."""
    from databricks.sdk.service.sql import StatementState

    resposta = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id, statement=comando, wait_timeout="50s"
    )
    while resposta.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(3)
        resposta = w.statement_execution.get_statement(resposta.statement_id)
    if resposta.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL falhou ({resposta.status.state}): {resposta.status.error}\n{comando}")
    if not resposta.manifest or not resposta.manifest.schema or not resposta.manifest.schema.columns:
        return []
    colunas = [coluna.name for coluna in resposta.manifest.schema.columns]
    linhas = (resposta.result.data_array if resposta.result else None) or []
    return [dict(zip(colunas, linha, strict=True)) for linha in linhas]


def esvaziar_landing(w, landing: str) -> int:
    """Apaga todos os arquivos da landing do CI (pastas inclusive)."""
    if not landing.startswith("/Volumes/") or not landing.split("/")[3].endswith("_ci"):
        raise SchemaForaDoCI(f"landing {landing!r} não é do CI")
    from databricks.sdk.errors import NotFound

    apagados = 0
    pastas = []
    pendentes = [landing]
    while pendentes:
        pasta = pendentes.pop()
        try:
            itens = list(w.files.list_directory_contents(pasta))
        except NotFound:  # pasta que ainda não existe: nada a apagar
            continue
        for item in itens:
            if item.is_directory:
                pendentes.append(item.path)
                pastas.append(item.path)
            else:
                w.files.delete(item.path)
                apagados += 1
    for pasta in sorted(pastas, key=len, reverse=True):
        w.files.delete_directory(pasta)
    return apagados


# Comandos --------------------------------------------------------------------------


def preparar(recursos: dict) -> None:
    w = cliente()
    for comando in comandos_origem(recursos["catalogo"], recursos["projeto"]):
        executar_sql(w, recursos["warehouse_id"], comando)
    print(f"Origem simulada criada em {recursos['catalogo']}.{recursos['schema_origem']}.")
    print(f"Landing esvaziada: {esvaziar_landing(w, recursos['landing'])} arquivo(s) apagado(s).")


def enviar(recursos: dict, versao: int) -> None:
    arquivo = RAIZ / "data" / f"agenda_exemplo_v{versao}.csv"
    destino = f"{recursos['landing']}/{PASTA_AGENDA}/{arquivo.name}"
    cliente().files.upload(destino, io.BytesIO(arquivo.read_bytes()), overwrite=True)
    print(f"Enviado {arquivo.name} para {destino}.")


COLUNA_NOVA_NA_ORIGEM = "cd_centro_custo"


def alterar_origem(recursos: dict) -> None:
    """Cenário de mudança na origem: a tabela de cargos do CI ganha uma coluna nova."""
    origem = f"`{recursos['catalogo']}`.`{verificar_schema_ci(recursos['schema_origem'])}`.cadastro_cargos"
    executar_sql(cliente(), recursos["warehouse_id"], f"ALTER TABLE {origem} ADD COLUMN {COLUNA_NOVA_NA_ORIGEM} STRING")
    print(f"Coluna {COLUNA_NOVA_NA_ORIGEM} acrescentada em {origem}.")


def limpar(recursos: dict) -> None:
    w = cliente()
    for schema in (recursos["schema"], recursos["schema_gold"], recursos["schema_origem"]):
        nome = f"`{recursos['catalogo']}`.`{verificar_schema_ci(schema)}`"
        executar_sql(w, recursos["warehouse_id"], f"DROP SCHEMA IF EXISTS {nome} CASCADE")
        print(f"Schema {recursos['catalogo']}.{schema} apagado (se existia).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("comando", choices=["preparar", "enviar", "alterar-origem", "limpar"])
    parser.add_argument("--versao", type=int, choices=[1, 2, 3, 4], help="versão da agenda fictícia (enviar)")
    args = parser.parse_args()
    if not ARQUIVO_RECURSOS.is_file():
        sys.exit(f"Resumo do bundle não encontrado em {ARQUIVO_RECURSOS}: rode o deploy -t ci antes.")
    recursos = carregar_recursos()
    if args.comando == "preparar":
        preparar(recursos)
    elif args.comando == "enviar":
        if not args.versao:
            parser.error("enviar precisa de --versao")
        enviar(recursos, args.versao)
    elif args.comando == "alterar-origem":
        alterar_origem(recursos)
    else:
        limpar(recursos)


if __name__ == "__main__":
    main()
