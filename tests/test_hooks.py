"""Testes dos hooks do Claude Code (.claude/hooks/).

Cada hook roda como processo separado, recebendo pela entrada padrão o mesmo JSON que o
Claude Code envia. Saída 0 libera a ação; saída 2 bloqueia (ou, no PostToolUse, avisa).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
HOOKS = RAIZ / ".claude" / "hooks"
PROJETO_WIN = "C:\\Users\\dev\\projeto"


def rodar(script: str, entrada: dict, *args: str, ambiente: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOKS / script), *args],
        input=json.dumps(entrada),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=ambiente,
    )


def comando(texto: str, cwd: Path) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "PowerShell",
        "cwd": str(cwd),
        "tool_input": {"command": texto},
    }


def arquivo(ferramenta: str, caminho: str) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": ferramenta, "tool_input": {"file_path": caminho}}


# proteger_comandos.py ------------------------------------------------------------

COMANDOS_PERMITIDOS = [
    "ruff check .",
    ".venv\\Scripts\\pytest.exe -q",
    "databricks bundle validate -t dev",
    "databricks bundle deploy -t dev",
    "databricks bundle run essentials_carga_diaria -t dev",
    "databricks fs cp data/agenda_exemplo_v1.csv dbfs:/Volumes/essentials/portfolio/landing/agenda/",
    "python data/gerar_dados_exemplo.py",
    "git push -u origin fase-1",
    "git status --short",
    "Remove-Item -Recurse -Force .pytest_cache",
    "rm -rf .venv",
    "$env:BUNDLE_VAR_alert_email = 'voce@exemplo.com'",
]

COMANDOS_BLOQUEADOS = [
    "databricks bundle deploy -t prod",
    "databricks bundle deploy --target=prod",
    "databricks bundle run essentials_pipeline -t prod",
    "databricks bundle destroy -t dev",
    "git push --force origin fase-1",
    "git push -f",
    "git push origin +fase-1",
    "git push -u origin main",
    "git push origin HEAD:main",
    "Get-Content data\\tabela_agenda_2025.csv -TotalCount 5",
    "cat data/privado/clientes.csv",
    "python -c \"open('data/vendas_cliente.xlsx')\"",
    "type .env",
    "databricks auth token",
    "gh auth token",
    "echo $env:DATABRICKS_TOKEN",
    "printenv",
    "Get-ChildItem env:",
    "rm -rf src",
    "Remove-Item -Recurse -Force docs",
    "ruff check . && databricks bundle deploy -t prod",
]


@pytest.mark.parametrize("texto", COMANDOS_PERMITIDOS)
def test_comandos_permitidos_passam(texto, tmp_path):
    resultado = rodar("proteger_comandos.py", comando(texto, tmp_path))
    assert resultado.returncode == 0, resultado.stderr


@pytest.mark.parametrize("texto", COMANDOS_BLOQUEADOS)
def test_comandos_perigosos_sao_bloqueados(texto, tmp_path):
    resultado = rodar("proteger_comandos.py", comando(texto, tmp_path))
    assert resultado.returncode == 2
    assert resultado.stderr.startswith("Bloqueado pelo hook do projeto:")


def test_push_sem_destino_estando_na_main_e_bloqueado(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    assert rodar("proteger_comandos.py", comando("git push", tmp_path)).returncode == 2


def test_push_sem_destino_em_outra_branch_passa(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "fase-1", str(tmp_path)], check=True)
    assert rodar("proteger_comandos.py", comando("git push", tmp_path)).returncode == 0


# proteger_arquivos.py ------------------------------------------------------------


@pytest.mark.parametrize(
    "caminho",
    [
        f"{PROJETO_WIN}\\README.md",
        f"{PROJETO_WIN}\\data\\agenda_exemplo_v1.csv",
        f"{PROJETO_WIN}\\data\\gerar_dados_exemplo.py",
        "/home/dev/projeto/src/pipeline/silver.py",
        "/home/dev/projeto/.venv/lib/site.py",
    ],
)
def test_arquivos_do_projeto_e_dados_ficticios_passam(caminho):
    for ferramenta in ("Read", "Edit", "Write"):
        resultado = rodar("proteger_arquivos.py", arquivo(ferramenta, caminho))
        assert resultado.returncode == 0, resultado.stderr


@pytest.mark.parametrize(
    "caminho",
    [
        f"{PROJETO_WIN}\\data\\tabela_agenda_2025.csv",
        f"{PROJETO_WIN}\\data\\privado\\clientes.xlsx",
        "/home/dev/projeto/data/vendas.parquet",
        f"{PROJETO_WIN}\\.env",
        "/home/dev/projeto/.env.prod",
    ],
)
def test_dados_reais_e_segredos_sao_bloqueados(caminho):
    for ferramenta in ("Read", "Edit", "Write"):
        assert rodar("proteger_arquivos.py", arquivo(ferramenta, caminho)).returncode == 2


def test_pesquisa_na_pasta_data_inteira_e_bloqueada():
    entrada = {"tool_name": "Grep", "tool_input": {"pattern": "Silva", "path": f"{PROJETO_WIN}\\data"}}
    assert rodar("proteger_arquivos.py", entrada).returncode == 2


# restringir_edicao.py ------------------------------------------------------------


@pytest.mark.parametrize(
    ("caminho", "esperado"),
    [
        (f"{PROJETO_WIN}\\tests\\test_projeto.py", 0),
        (f"{PROJETO_WIN}\\src\\pipeline\\silver.py", 2),
        (f"{PROJETO_WIN}\\config\\fontes.yml", 2),
    ],
)
def test_agente_de_qa_so_edita_testes(caminho, esperado):
    ambiente = dict(os.environ, CLAUDE_PROJECT_DIR=PROJETO_WIN)
    resultado = rodar("restringir_edicao.py", arquivo("Edit", caminho), "tests/**", ambiente=ambiente)
    assert resultado.returncode == esperado


@pytest.mark.parametrize(
    ("caminho", "esperado"),
    [
        (f"{PROJETO_WIN}\\README.md", 0),
        (f"{PROJETO_WIN}\\docs\\adr\\0001-sem-dbt.md", 0),
        (f"{PROJETO_WIN}\\CLAUDE.md", 0),
        (f"{PROJETO_WIN}\\src\\essentials\\config_fontes.py", 2),
    ],
)
def test_documentador_so_edita_documentacao(caminho, esperado):
    ambiente = dict(os.environ, CLAUDE_PROJECT_DIR=PROJETO_WIN)
    resultado = rodar("restringir_edicao.py", arquivo("Write", caminho), "docs/**", "*.md", ambiente=ambiente)
    assert resultado.returncode == esperado


# lint_apos_edicao.py -------------------------------------------------------------


def test_lint_avisa_problema_no_arquivo_editado(tmp_path):
    ruim = tmp_path / "ruim.py"
    ruim.write_text("import os\n", encoding="utf-8")
    entrada = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Write",
        "cwd": str(RAIZ),
        "tool_input": {"file_path": str(ruim)},
    }
    resultado = rodar("lint_apos_edicao.py", entrada)
    assert resultado.returncode == 2
    assert "F401" in resultado.stderr


def test_lint_aceita_arquivo_limpo_e_ignora_nao_python(tmp_path):
    limpo = tmp_path / "limpo.py"
    limpo.write_text("VALOR = 1\n", encoding="utf-8")
    texto = tmp_path / "nota.md"
    texto.write_text("import os\n", encoding="utf-8")
    for caminho in (limpo, texto):
        entrada = {"tool_name": "Edit", "cwd": str(RAIZ), "tool_input": {"file_path": str(caminho)}}
        assert rodar("lint_apos_edicao.py", entrada).returncode == 0


# Registro no settings.json -------------------------------------------------------


def test_hooks_estao_registrados_e_existem():
    configuracao = json.loads((RAIZ / ".claude" / "settings.json").read_text(encoding="utf-8"))
    registrados = {}
    for evento, grupos in configuracao["hooks"].items():
        for grupo in grupos:
            for hook in grupo["hooks"]:
                script = Path(hook["args"][0].replace("${CLAUDE_PROJECT_DIR}/", "")).name
                registrados[script] = (evento, grupo["matcher"])
                assert (HOOKS / script).is_file(), script
    assert registrados["proteger_comandos.py"] == ("PreToolUse", "Bash|PowerShell")
    assert registrados["proteger_arquivos.py"] == ("PreToolUse", "Read|Edit|Write|Grep")
    assert registrados["lint_apos_edicao.py"] == ("PostToolUse", "Edit|Write")
