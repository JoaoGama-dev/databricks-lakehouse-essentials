"""Ingestão de APIs: grava na landing, em JSON (um registro por linha), a resposta de
cada fonte do tipo api do config/fontes.yml.

Roda como tarefa do job essentials_carga_diaria, antes do pipeline. A bronze lê os
arquivos gerados com Auto Loader, como qualquer outro arquivo. O token fica num
secret scope do Databricks, nunca no repositório.

Testado só no Azure Databricks: o Free Edition restringe o acesso à internet.
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


def cabecalhos(autenticacao: dict, segredo: str) -> dict:
    if autenticacao["tipo"] == "bearer":
        return {"Authorization": f"Bearer {segredo}"}
    if autenticacao["tipo"] == "api_key":
        return {autenticacao.get("cabecalho", "X-API-Key"): segredo}
    return {}


def extrair_registros(resposta, campo: str | None) -> list:
    """Navega até a lista de registros, por exemplo campo "dados.itens"."""
    dados = resposta
    for parte in campo.split(".") if campo else []:
        dados = dados.get(parte, []) if isinstance(dados, dict) else []
    return dados if isinstance(dados, list) else [dados]


def buscar(api: dict, cabecalhos_http: dict) -> list:
    import requests

    parametros = dict(api.get("parametros", {}))
    paginacao = api.get("paginacao")
    paginas = range(1, paginacao.get("max_paginas", 100) + 1) if paginacao else [None]
    registros = []
    for pagina in paginas:
        if pagina is not None:
            parametros[paginacao["parametro"]] = pagina
        resposta = requests.get(api["url"], headers=cabecalhos_http, params=parametros, timeout=60)
        resposta.raise_for_status()
        lote = extrair_registros(resposta.json(), api.get("campo_registros"))
        if not lote:
            break
        registros.extend(lote)
    return registros


def main() -> None:
    args = argumentos()
    sys.path.append(args.codigo)
    from databricks.sdk.runtime import dbutils

    from essentials.config_fontes import carregar_fontes

    fontes = [fonte for fonte in carregar_fontes(args.config) if fonte["tipo"] == "api"]
    if not fontes:
        print("Nenhuma fonte do tipo api no config/fontes.yml; nada a fazer.")
        return

    momento = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    for fonte in fontes:
        api = fonte["api"]
        autenticacao = api["autenticacao"]
        segredo = ""
        if autenticacao["tipo"] != "nenhuma":
            segredo = dbutils.secrets.get(scope=autenticacao["escopo"], key=autenticacao["chave"])

        registros = buscar(api, cabecalhos(autenticacao, segredo))
        if not registros:
            print(f"{fonte['nome']}: a API não devolveu registros.")
            continue

        destino = f"{args.landing.rstrip('/')}/{api['pasta_landing']}/{fonte['nome']}_{momento}.json"
        conteudo = "\n".join(json.dumps(registro, ensure_ascii=False) for registro in registros)
        dbutils.fs.put(destino, conteudo, overwrite=False)
        print(f"{fonte['nome']}: {len(registros)} registros gravados em {destino}")


if __name__ == "__main__":
    main()
