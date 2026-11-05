"""Ingestão das fontes externas (banco e api) para a landing, como tarefa do job.

Roda só quando a variável ingerir_fontes_externas é "true" (tarefa de condição
tem_fonte_externa, docs/adr/0004): um teste confere que ela reflete o fontes.yml. Para cada
tipo de fonte externa que o fontes.yml tem, chama o script do tipo:

  banco  banco_para_landing.ingerir  (parquet na landing, pelo Lakehouse Federation)
  api    api_para_landing.ingerir    (JSON na landing)

Um tipo com erro não impede o outro; no fim, a tarefa falha com a classe do erro de cada
tipo (nunca a mensagem, que pode ter um valor de registro) e o pipeline não roda
(processar_medalhao com run_if NONE_FAILED).
"""

from __future__ import annotations

import argparse
import sys

# Tipo de fonte externa -> módulo de src/ingestao/ que o traz para a landing, na ordem em que rodam.
MODULOS_POR_TIPO = {"banco": "banco_para_landing", "api": "api_para_landing"}


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="caminho do config/fontes.yml")
    parser.add_argument("--landing", required=True, help="raiz da landing zone")
    parser.add_argument("--codigo", required=True, help="pasta src/ do bundle")
    parser.add_argument("--fuso-horario", required=True, help="fuso do log legível (variável fuso_horario)")
    return parser.parse_args()


def tipos_externos(fontes: list[dict]) -> list[str]:
    """Tipos de fonte externa presentes no fontes.yml, na ordem de MODULOS_POR_TIPO."""
    presentes = {fonte["tipo"] for fonte in fontes}
    return [tipo for tipo in MODULOS_POR_TIPO if tipo in presentes]


def tem_fonte_externa(fontes: list[dict]) -> bool:
    """O que a variável ingerir_fontes_externas do databricks.yml precisa dizer ("true"/"false")."""
    return bool(tipos_externos(fontes))


def main() -> None:
    args = argumentos()
    sys.path.append(args.codigo)
    import importlib

    from essentials.config_fontes import carregar_fontes
    from essentials.log_texto import configurar_log

    log = configurar_log(args.fuso_horario)
    fontes = carregar_fontes(args.config)
    tipos = tipos_externos(fontes)
    if not tipos:
        log.warning("Nenhuma fonte banco ou api no fontes.yml: confira a variável ingerir_fontes_externas.")
        return

    com_erro = []
    for tipo in tipos:
        modulo = importlib.import_module(f"ingestao.{MODULOS_POR_TIPO[tipo]}")
        log.info("Ingestão das fontes do tipo %s.", tipo)
        try:
            modulo.ingerir(fontes, args.landing)
        except Exception as erro:  # noqa: BLE001 - um tipo com erro não impede o outro
            log.error("Ingestão das fontes do tipo %s falhou: %s.", tipo, type(erro).__name__)
            com_erro.append(f"{tipo} ({type(erro).__name__})")
    if com_erro:
        sys.exit(f"Ingestão com erro: {', '.join(com_erro)}. Veja o log da tarefa.")
    log.info("Ingestão das fontes externas concluída.")


if __name__ == "__main__":
    main()
