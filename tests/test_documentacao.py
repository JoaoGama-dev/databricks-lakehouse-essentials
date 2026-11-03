"""Testes da documentação de engenharia (Fase 6).

Conferem os ADRs (sequência, formato e índice), o CHANGELOG (Keep a Changelog, versões em
ordem e com link), os diagramas do README e que nenhum link relativo do README e de
docs/ aponta para um arquivo que não existe.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PASTA_ADR = RAIZ / "docs" / "adr"
CHANGELOG = RAIZ / "CHANGELOG.md"
README = RAIZ / "README.md"
REPOSITORIO = "https://github.com/JoaoGama-dev/databricks-lakehouse-essentials"


def ler(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8")


def adrs() -> list[Path]:
    return sorted(PASTA_ADR.glob("[0-9][0-9][0-9][0-9]-*.md"))


# ADRs --------------------------------------------------------------------------------


def test_adrs_numerados_em_sequencia_sem_buracos():
    numeros = [int(adr.name[:4]) for adr in adrs()]
    assert numeros == list(range(1, len(numeros) + 1)), numeros
    assert len(numeros) >= 13


@pytest.mark.parametrize("adr", adrs(), ids=lambda a: a.name)
def test_adr_segue_o_formato_da_skill(adr):
    texto = ler(adr)
    assert re.match(rf"# {adr.name[:4]}\. \S", texto), "título com o número do arquivo"
    assert re.search(r"^- \*\*Status:\*\* (proposta|aceita|substituída por \d{4})$", texto, re.MULTILINE)
    assert re.search(r"^- \*\*Data:\*\* \d{4}-\d{2}-\d{2}", texto, re.MULTILINE)
    secoes = re.findall(r"^## (.+)$", texto, re.MULTILINE)
    assert secoes == ["Contexto", "Decisão", "Alternativas consideradas", "Consequências"], secoes
    assert adr.name == adr.name.lower() and " " not in adr.name


def test_indice_lista_todos_os_adrs_com_o_status():
    indice = ler(PASTA_ADR / "README.md")
    for adr in adrs():
        status = re.search(r"\*\*Status:\*\* (.+)$", ler(adr), re.MULTILINE).group(1)
        linha = next((linha for linha in indice.splitlines() if f"]({adr.name})" in linha), None)
        assert linha, f"{adr.name} fora do índice"
        assert linha.rstrip(" |").endswith(status), (adr.name, status)


# CHANGELOG -----------------------------------------------------------------------------


def versoes_do_changelog() -> list[str]:
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", ler(CHANGELOG), re.MULTILINE)


def chave(versao: str) -> tuple[int, ...]:
    return tuple(int(parte) for parte in versao.split("."))


def test_changelog_segue_o_keep_a_changelog():
    texto = ler(CHANGELOG)
    assert "keepachangelog.com" in texto and "semver.org" in texto
    assert re.search(r"^## \[Unreleased\]$", texto, re.MULTILINE)
    titulos = re.findall(r"^## (.+)$", texto, re.MULTILINE)
    assert titulos[0] == "[Unreleased]"
    tipos = set(re.findall(r"^### (.+)$", texto, re.MULTILINE))
    assert tipos <= {"Adicionado", "Alterado", "Obsoleto", "Removido", "Corrigido", "Segurança"}, tipos


def test_changelog_tem_uma_versao_menor_por_fase_em_ordem_decrescente():
    versoes = versoes_do_changelog()
    assert versoes == sorted(versoes, key=chave, reverse=True)
    assert versoes[-1] == "0.1.0"
    assert [chave(v)[1] for v in reversed(versoes)] == list(range(1, len(versoes) + 1))


def test_cada_versao_do_changelog_tem_link():
    texto = ler(CHANGELOG)
    versoes = versoes_do_changelog()
    assert f"[Unreleased]: {REPOSITORIO}/compare/v{versoes[0]}...HEAD" in texto
    for atual, anterior in itertools.pairwise(versoes):
        assert f"[{atual}]: {REPOSITORIO}/compare/v{anterior}...v{atual}" in texto, atual
    assert f"[{versoes[-1]}]: {REPOSITORIO}/releases/tag/v{versoes[-1]}" in texto


# README -------------------------------------------------------------------------------


def test_readme_comeca_pela_visao_geral_e_tem_os_diagramas():
    texto = ler(README)
    secoes = re.findall(r"^## (.+)$", texto, re.MULTILINE)
    assert secoes[:2] == ["Em 1 minuto", "Como rodar (Free Edition)"], secoes
    assert texto.count("```mermaid") >= 2
    assert len(texto.splitlines()) <= 200, "detalhes vão para docs/"


def test_diagramas_mermaid_usam_so_flowchart():
    # Sintaxe simples, renderizada pelo GitHub: um diagrama por bloco, sempre flowchart.
    for arquivo in [README, *RAIZ.joinpath("docs").rglob("*.md")]:
        for bloco in re.findall(r"```mermaid\n(.*?)```", ler(arquivo), re.DOTALL):
            assert re.match(r"flowchart (LR|TD)\n", bloco), arquivo.name
            # Rótulos com < e > quebram o HTML do diagrama: use #60; e #62;.
            rotulos = re.findall(r'"([^"]*)"', bloco)
            assert not any(re.search(r"<(?!br/>)|(?<!<br/)>", rotulo) for rotulo in rotulos), arquivo.name


# Links relativos -------------------------------------------------------------------------


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
