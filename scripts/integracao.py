"""Apoio aos testes de integração (.github/workflows/integracao.yml, docs/adr/0005).

Roda contra o target "ci" do bundle, só com os dados fictícios do gerador. Os nomes reais
dos recursos vêm do resumo do bundle, gravado pelo workflow depois do deploy:

    databricks bundle summary -t ci -o json > recursos-ci.json

Comandos:
    python scripts/integracao.py preparar           esvazia a landing do CI
    python scripts/integracao.py enviar --versao 1  envia data/agenda_exemplo_v1.csv (1 a 8)
    python scripts/integracao.py limpar             apaga os schemas do CI que sobrarem

Por segurança, nada aqui toca num schema cujo nome não termine em _ci_bronze, _ci_silver,
_ci_gold ou _ci_monitoramento: o dev de quem roda fica intacto.
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
ARQUIVO_RECURSOS = Path(os.environ.get("INTEGRACAO_RECURSOS", RAIZ / "recursos-ci.json"))
# Um schema por camada (resources/governanca.yml), na ordem em que o limpar os apaga.
CAMADAS = ("bronze", "silver", "gold", "monitoramento")
SUFIXOS_CI = tuple(f"_ci_{camada}" for camada in CAMADAS)
PASTA_AGENDA = "agenda"
# Versões da agenda fictícia que podem ser enviadas (data/gerar_dados_exemplo.py):
#   1 e 2 cargas normais; 3 e 4 cenários de falha; 5 reenvio da v2; 6 a v1 chegando
#   atrasada; 7 só o cabeçalho; 8 a v2 em cp1252.
VERSOES_AGENDA = tuple(range(1, 9))


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
        "catalogo": schemas["silver"]["catalog_name"],
        **{f"schema_{camada}": verificar_schema_ci(schemas[camada]["name"]) for camada in CAMADAS},
        "projeto": variaveis["projeto"],
        "warehouse_id": variaveis["warehouse_id"],
        "job_id": resumo["resources"]["jobs"]["essentials_carga_diaria"].get("id"),
        "pipeline_id": resumo["resources"]["pipelines"]["essentials_pipeline"].get("id"),
    }
    # O volume landing fica no schema da bronze (resources/governanca.yml).
    recursos["landing"] = f"/Volumes/{recursos['catalogo']}/{recursos['schema_bronze']}/landing"
    return recursos


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
    partes = landing.split("/")
    if not landing.startswith("/Volumes/") or len(partes) < 5 or not partes[3].endswith("_ci_bronze"):
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
    print(f"Landing esvaziada: {esvaziar_landing(cliente(), recursos['landing'])} arquivo(s) apagado(s).")


def arquivo_da_versao(versao: int) -> Path:
    """Arquivo da agenda fictícia de uma versão; recusa o que não for da lista fechada."""
    if type(versao) is not int or versao not in VERSOES_AGENDA:  # True == 1 passaria no "in"
        raise ValueError(f"versão {versao!r} da agenda não existe (aceitas: {VERSOES_AGENDA})")
    return RAIZ / "data" / f"agenda_exemplo_v{versao}.csv"


def enviar(recursos: dict, versao: int) -> None:
    arquivo = arquivo_da_versao(versao)
    destino = f"{recursos['landing']}/{PASTA_AGENDA}/{arquivo.name}"
    cliente().files.upload(destino, io.BytesIO(arquivo.read_bytes()), overwrite=True)
    print(f"Enviado {arquivo.name} para {destino}.")


def limpar(recursos: dict) -> None:
    w = cliente()
    for camada in CAMADAS:
        schema = recursos[f"schema_{camada}"]
        nome = f"`{recursos['catalogo']}`.`{verificar_schema_ci(schema)}`"
        executar_sql(w, recursos["warehouse_id"], f"DROP SCHEMA IF EXISTS {nome} CASCADE")
        print(f"Schema {recursos['catalogo']}.{schema} apagado (se existia).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("comando", choices=["preparar", "enviar", "limpar"])
    parser.add_argument("--versao", type=int, choices=VERSOES_AGENDA, help="versão da agenda fictícia (enviar)")
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
    else:
        limpar(recursos)


if __name__ == "__main__":
    main()
