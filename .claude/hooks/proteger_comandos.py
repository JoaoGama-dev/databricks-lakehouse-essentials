"""Hook PreToolUse (Bash e PowerShell): bloqueia comandos perigosos antes de rodarem.

Bloqueia: produção (deploy, run ou destroy), push forçado ou direto na main, leitura de
dados reais e de .env, comandos que imprimem tokens e remoção recursiva fora de
.venv, caches e .databricks/. Saída 2 cancela o comando e mostra o motivo ao Claude.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from regras import bloquear, ler_entrada, motivo_para_bloquear_comando


def main() -> None:
    entrada = ler_entrada()
    comando = entrada.get("tool_input", {}).get("command", "")
    motivo = motivo_para_bloquear_comando(comando, entrada.get("cwd"))
    if motivo:
        bloquear(motivo)


if __name__ == "__main__":
    main()
