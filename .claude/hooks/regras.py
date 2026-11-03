"""Regras compartilhadas pelos hooks do Claude Code deste projeto.

Só biblioteca padrão: os hooks rodam com o Python do sistema, fora da .venv.
Os caminhos chegam com barra invertida no Windows; tudo é normalizado para "/".
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

# Agendas fictícias do gerador: as únicas planilhas de data/ que podem ser lidas.
DADO_FICTICIO = re.compile(r"(^|/)data/agenda_exemplo_v\d+\.csv$", re.IGNORECASE)
DADO_REAL = (
    re.compile(r"(^|/)data/privado(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)data/[^/]+\.(csv|json|parquet|xlsx?|xls|txt)$", re.IGNORECASE),
)
SEGREDO = re.compile(r"(^|/)\.env(\.[^/]*)?$", re.IGNORECASE)

# Referências a dados dentro de um comando de shell.
CAMINHO_EM_COMANDO = re.compile(
    r"data[/\\](?:privado(?:[/\\][^\s\"';|&]*)?|[^\s\"';|&/\\]+\.(?:csv|json|parquet|xlsx?|xls|txt))",
    re.IGNORECASE,
)
SEPARADORES = re.compile(r"&&|\|\||[;|&\n]")
ALVO_PROD = re.compile(r"(?:-t|--target)(?:\s+|=)['\"]?prod\b", re.IGNORECASE)
REMOCAO_LIBERADA = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".databricks"}


def normalizar(caminho: str) -> str:
    return caminho.replace("\\", "/")


def e_dado_real(caminho: str) -> bool:
    caminho = normalizar(caminho)
    if DADO_FICTICIO.search(caminho):
        return False
    return any(padrao.search(caminho) for padrao in DADO_REAL)


def e_segredo(caminho: str) -> bool:
    return bool(SEGREDO.search(normalizar(caminho)))


def ler_entrada() -> dict:
    return json.loads(sys.stdin.read() or "{}")


def avisar(mensagem: str) -> None:
    """Escreve no stderr em UTF-8: no Windows, o padrão seria a página de código do sistema."""
    sys.stderr.reconfigure(encoding="utf-8")
    print(mensagem, file=sys.stderr)


def bloquear(motivo: str) -> None:
    """Saída 2: o Claude Code cancela a ação e mostra o motivo ao Claude."""
    avisar(f"Bloqueado pelo hook do projeto: {motivo}")
    sys.exit(2)


def segmentos(comando: str) -> list[str]:
    return [parte.strip() for parte in SEPARADORES.split(comando) if parte.strip()]


def branch_atual(cwd: str | None) -> str:
    try:
        saida = subprocess.run(
            ["git", "branch", "--show-current"], cwd=cwd, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return saida.stdout.strip() if saida.returncode == 0 else ""


def motivo_para_bloquear_comando(comando: str, cwd: str | None = None) -> str | None:
    """Devolve o motivo do bloqueio, ou None se o comando pode rodar."""
    for referencia in CAMINHO_EM_COMANDO.findall(comando):
        if e_dado_real(referencia):
            return (
                f"o comando cita '{referencia}', que é dado real de cliente. Use scripts/perfilar_dados.py, "
                "que mostra só a estrutura, ou os dados fictícios do gerador."
            )
    if re.search(r"(^|[\\/\s\"'])\.env(\.[\w.-]*)?(\s|$|[\"'])", comando):
        return "o comando cita um arquivo .env, que guarda segredos."

    for parte in segmentos(comando):
        texto = parte.lower()
        if re.search(r"\bbundle\s+destroy\b", texto):
            return "databricks bundle destroy apaga os recursos implantados e nunca roda por aqui."
        if re.search(r"\bbundle\s+(deploy|run)\b", texto) and ALVO_PROD.search(parte):
            return "produção só muda pelo workflow de deploy do GitHub, nunca por comando local."
        if re.search(r"\bgit\s+push\b", texto):
            if re.search(r"\s(--force(-with-lease)?|-f)(\s|$|=)", parte) or re.search(r"\s\+\S", parte):
                return "git push forçado reescreve o histórico remoto e está proibido."
            if re.search(r"(\s|:)main(\s|$)", parte) or (
                not re.search(r"\bgit\s+push\s+\S+\s+\S", parte) and branch_atual(cwd) == "main"
            ):
                return "push direto na main é proibido: abra uma branch e um pull request."
        if re.search(r"\b(databricks|gh)\s+auth\s+(token|env)\b", texto):
            return "o comando imprime um token de acesso."
        if re.search(r"\$(env:)?\{?\w*(token|secret|password|senha)\w*", texto) or re.search(
            r"\bprintenv\b|\b(get-childitem|gci|dir|ls)\s+env:", texto
        ):
            return "o comando lê variáveis de ambiente que podem conter segredos."
        motivo = _motivo_remocao(parte)
        if motivo:
            return motivo
    return None


def _motivo_remocao(parte: str) -> str | None:
    tokens = parte.replace('"', " ").replace("'", " ").split()
    if not tokens:
        return None
    comando = tokens[0].lower()
    if comando == "rm":
        opcoes = "".join(t.lstrip("-").lower() for t in tokens[1:] if t.startswith("-"))
        recursivo = "r" in opcoes or "recursive" in opcoes
    elif comando in ("remove-item", "ri", "del", "erase", "rd", "rmdir"):
        recursivo = any(t.lower().startswith("-r") for t in tokens[1:])
    else:
        return None
    if not recursivo:
        return None
    alvos = [t for t in tokens[1:] if not t.startswith("-") and t.lower() not in ("-force", "-fo")]
    nomes = [normalizar(alvo).rstrip("/").split("/")[-1] for alvo in alvos]
    if alvos and all(nome in REMOCAO_LIBERADA for nome in nomes):
        return None
    return (
        "remoção recursiva só é liberada para .venv, caches e .databricks/. "
        "Peça ao usuário para apagar outras pastas."
    )
