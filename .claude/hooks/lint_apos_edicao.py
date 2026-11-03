"""Hook PostToolUse (Edit e Write): roda o ruff no arquivo Python que acabou de ser editado.

Procura o ruff na .venv do projeto e, se não achar, no PATH; sem ruff, termina sem erro.
Com problemas, sai com 2: o Claude Code mostra a saída do ruff ao Claude, que corrige.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from regras import avisar, ler_entrada


def localizar_ruff(projeto: Path) -> str | None:
    for candidato in (projeto / ".venv" / "Scripts" / "ruff.exe", projeto / ".venv" / "bin" / "ruff"):
        if candidato.is_file():
            return str(candidato)
    return shutil.which("ruff")


def main() -> None:
    entrada = ler_entrada()
    arquivo = entrada.get("tool_input", {}).get("file_path", "")
    if not arquivo.endswith(".py") or not Path(arquivo).is_file():
        return
    projeto = Path(os.environ.get("CLAUDE_PROJECT_DIR") or entrada.get("cwd") or Path.cwd())
    ruff = localizar_ruff(projeto)
    if not ruff:
        return
    resultado = subprocess.run(
        [ruff, "check", "--no-cache", arquivo], cwd=projeto, capture_output=True, text=True, timeout=60
    )
    if resultado.returncode != 0:
        avisar(f"ruff encontrou problemas em {arquivo}:\n{resultado.stdout}{resultado.stderr}")
        sys.exit(2)


if __name__ == "__main__":
    main()
