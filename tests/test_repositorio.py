"""Testes da segurança e da cadeia de suprimentos do repositório (Fase 2).

Garantem por código o que a revisão humana esqueceria: actions fixadas por SHA,
dependências com versão, permissões mínimas nos workflows e os arquivos do repositório.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((RAIZ / ".github" / "workflows").glob("*.yml"))


def carregar_yaml(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


# 2.1 Actions fixadas por SHA ------------------------------------------------------


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_actions_fixadas_por_sha_com_versao_no_comentario(workflow):
    usos = re.findall(r"uses:\s*(\S+)(.*)", workflow.read_text(encoding="utf-8"))
    assert usos, f"{workflow.name} não usa nenhuma action"
    for acao, resto in usos:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", acao), f"{acao} não está fixada por SHA"
        assert re.fullmatch(r"\s*# v\d+\.\d+\.\d+", resto), f"{acao} sem a versão em comentário"


# 2.2 Dependabot -------------------------------------------------------------------


def test_dependabot_cobre_actions_e_python_com_cooldown():
    configuracao = carregar_yaml(RAIZ / ".github" / "dependabot.yml")
    assert configuracao["version"] == 2
    atualizacoes = {u["package-ecosystem"]: u for u in configuracao["updates"]}
    assert set(atualizacoes) == {"github-actions", "pip"}
    for atualizacao in atualizacoes.values():
        assert atualizacao["schedule"]["interval"] == "weekly"
        assert atualizacao["cooldown"]["default-days"] >= 14
        assert any(g["update-types"] == ["minor", "patch"] for g in atualizacao["groups"].values())


# 2.3 Versões fixas num único lugar ------------------------------------------------

RUNTIME = "-r ${workspace.file_path}/requirements-runtime.txt"


@pytest.mark.parametrize("arquivo", sorted(RAIZ.glob("requirements-*.txt")), ids=lambda p: p.name)
def test_toda_dependencia_tem_versao_fixa(arquivo):
    linhas = [
        linha.strip()
        for linha in arquivo.read_text(encoding="utf-8").splitlines()
        if linha.strip() and not linha.lstrip().startswith(("#", "-r "))
    ]
    assert linhas
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+==\d+(\.\d+)+", linha) for linha in linhas), linhas


def test_dev_inclui_as_versoes_do_runtime():
    assert "-r requirements-runtime.txt" in (RAIZ / "requirements-dev.txt").read_text(encoding="utf-8")


def test_pipeline_e_job_instalam_o_requirements_runtime():
    pipeline = carregar_yaml(RAIZ / "resources" / "pipeline.yml")["resources"]["pipelines"]["essentials_pipeline"]
    assert pipeline["environment"]["dependencies"] == [RUNTIME]
    job = carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]["essentials_carga_diaria"]
    assert [ambiente["spec"]["dependencies"] for ambiente in job["environments"]] == [[RUNTIME]]
