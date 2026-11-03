"""Hook PreToolUse (Read, Edit, Write e Grep): protege dados reais e segredos.

Bloqueia ler, editar ou pesquisar dados reais de clientes (data/privado/ e planilhas de
data/ que não sejam as agendas fictícias do gerador) e arquivos .env. Uma pesquisa
(Grep) na pasta data/ inteira também é bloqueada, porque leria as planilhas reais.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from regras import bloquear, e_dado_real, e_segredo, ler_entrada, normalizar


def main() -> None:
    entrada = ler_entrada()
    argumentos = entrada.get("tool_input", {})
    caminho = argumentos.get("file_path") or argumentos.get("path") or ""
    if not caminho:
        return
    if e_dado_real(caminho):
        bloquear(
            f"'{caminho}' é dado real de cliente. Use scripts/perfilar_dados.py, que mostra só a estrutura."
        )
    if e_segredo(caminho):
        bloquear(f"'{caminho}' guarda segredos e não pode ser lido nem alterado pelo Claude.")
    if entrada.get("tool_name") == "Grep" and normalizar(caminho).rstrip("/").endswith("/data"):
        bloquear("pesquisar a pasta data/ inteira leria planilhas reais. Pesquise um arquivo fictício específico.")


if __name__ == "__main__":
    main()
