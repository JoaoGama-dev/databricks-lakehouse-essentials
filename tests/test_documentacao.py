"""Testes da documentação.

Conferem só o que quebra para quem lê: nenhum link relativo do README, do CHANGELOG, do
CLAUDE.md e de docs/ aponta para um arquivo que não existe. Forma e ordem dos ADRs e do
CHANGELOG ficam a cargo da revisão do PR, não de teste.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CHANGELOG = RAIZ / "CHANGELOG.md"
README = RAIZ / "README.md"


def ler(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8")


def documentos() -> list[Path]:
    return [README, CHANGELOG, RAIZ / "CLAUDE.md", *sorted(RAIZ.joinpath("docs").rglob("*.md"))]


@pytest.mark.parametrize("documento", documentos(), ids=lambda d: str(d.relative_to(RAIZ)))
def test_links_relativos_apontam_para_arquivos_que_existem(documento):
    texto = re.sub(r"```.*?```", "", ler(documento), flags=re.DOTALL)
    quebrados = []
    for alvo in re.findall(r"\]\(([^)\s]+)\)", texto):
        if re.match(r"^(https?:|mailto:|#)", alvo):
            continue
        caminho = (documento.parent / unquote(alvo.split("#")[0])).resolve()
        if not caminho.exists():
            quebrados.append(alvo)
    assert not quebrados, quebrados
