"""Hook PreToolUse (Edit e Write) dos subagentes: limita a edição a certas pastas.

Uso no frontmatter do agente: args com os padrões permitidos, relativos à raiz do
projeto, por exemplo "tests/**" ou "docs/**" e "*.md". O formato de subagente não tem
restrição de ferramenta por pasta; este hook é o mecanismo documentado para isso.
"""

import os
import sys
from fnmatch import fnmatch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from regras import bloquear, ler_entrada, normalizar


def caminho_relativo(arquivo: str, projeto: str) -> str:
    arquivo, projeto = normalizar(arquivo), normalizar(projeto).rstrip("/")
    if arquivo.lower().startswith(projeto.lower() + "/"):
        return arquivo[len(projeto) + 1 :]
    return arquivo


def main() -> None:
    permitidos = sys.argv[1:]
    entrada = ler_entrada()
    arquivo = entrada.get("tool_input", {}).get("file_path", "")
    if not arquivo or not permitidos:
        return
    projeto = os.environ.get("CLAUDE_PROJECT_DIR") or entrada.get("cwd") or str(Path.cwd())
    relativo = caminho_relativo(arquivo, projeto)
    if not any(fnmatch(relativo, padrao) for padrao in permitidos):
        bloquear(f"este agente só pode editar {', '.join(permitidos)}; '{relativo}' está fora disso.")


if __name__ == "__main__":
    main()
