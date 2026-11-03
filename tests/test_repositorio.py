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


# 2.4 Varredura de segredos --------------------------------------------------------


def test_ci_tem_os_tres_jobs():
    assert set(carregar_yaml(RAIZ / ".github" / "workflows" / "ci.yml")["jobs"]) == {
        "testes",
        "validar_bundle",
        "segredos",
    }


def test_gitleaks_do_ci_e_conferido_pelo_sha256_e_varre_o_historico():
    job = carregar_yaml(RAIZ / ".github" / "workflows" / "ci.yml")["jobs"]["segredos"]
    assert job["steps"][0]["with"]["fetch-depth"] == 0
    instalar = next(passo for passo in job["steps"] if "GITLEAKS_SHA256" in passo.get("env", {}))
    assert re.fullmatch(r"[0-9a-f]{64}", instalar["env"]["GITLEAKS_SHA256"])
    assert "sha256sum --check --strict" in instalar["run"]
    assert any("gitleaks git --redact" in passo.get("run", "") for passo in job["steps"])


# 2.5 pre-commit -------------------------------------------------------------------


def test_pre_commit_fixado_por_sha_e_com_os_hooks_do_plano():
    texto = (RAIZ / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    configuracao = yaml.safe_load(texto)
    for repo in configuracao["repos"]:
        assert re.fullmatch(r"[0-9a-f]{40}", repo["rev"]), repo["repo"]
    assert len(re.findall(r"rev: [0-9a-f]{40} # frozen: v\d+\.\d+\.\d+", texto)) == len(configuracao["repos"])
    hooks = {hook["id"] for repo in configuracao["repos"] for hook in repo["hooks"]}
    assert hooks == {
        "ruff-check",
        "check-yaml",
        "check-json",
        "end-of-file-fixer",
        "trailing-whitespace",
        "detect-private-key",
        "gitleaks",
    }


def test_gitleaks_tem_a_mesma_versao_no_ci_e_no_pre_commit():
    pre_commit = (RAIZ / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    versao_pre_commit = re.search(r"gitleaks/gitleaks\n\s+rev: \w+ # frozen: v([\d.]+)", pre_commit).group(1)
    job = carregar_yaml(RAIZ / ".github" / "workflows" / "ci.yml")["jobs"]["segredos"]
    versao_ci = next(p["env"]["GITLEAKS_VERSAO"] for p in job["steps"] if "GITLEAKS_VERSAO" in p.get("env", {}))
    assert str(versao_ci) == versao_pre_commit


# 2.6 Arquivos do repositório ------------------------------------------------------


@pytest.mark.parametrize(
    "arquivo",
    [
        "LICENSE",
        "SECURITY.md",
        ".github/CODEOWNERS",
        ".github/pull_request_template.md",
        ".github/ISSUE_TEMPLATE/bug.md",
        ".github/ISSUE_TEMPLATE/nova-fonte.md",
        ".github/ISSUE_TEMPLATE/novo-indicador.md",
        ".github/ISSUE_TEMPLATE/config.yml",
    ],
)
def test_arquivos_do_repositorio_existem(arquivo):
    assert (RAIZ / arquivo).is_file()


def test_licenca_e_a_mesma_do_readme():
    licenca = (RAIZ / "LICENSE").read_text(encoding="utf-8")
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    assert "Todos os direitos reservados" in licenca and "Todos os direitos reservados" in readme
    assert "não pode copiá-lo, modificá-lo, distribuí-lo nem usá-lo comercialmente" in licenca


def test_templates_de_issue_tem_frontmatter():
    for modelo in (RAIZ / ".github" / "ISSUE_TEMPLATE").glob("*.md"):
        texto = modelo.read_text(encoding="utf-8")
        meta = yaml.safe_load(texto.split("---\n")[1])
        assert meta["name"] and meta["about"] and meta["labels"], modelo.name


# 2.7 Permissões mínimas -----------------------------------------------------------


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_nao_concede_nada_por_padrao_e_cada_job_declara_o_que_usa(workflow):
    configuracao = carregar_yaml(workflow)
    assert configuracao["permissions"] == {}
    for nome, job in configuracao["jobs"].items():
        assert "permissions" in job, f"{workflow.name}: job {nome} sem permissions"
        escritas = {escopo for escopo, nivel in job["permissions"].items() if nivel == "write"}
        permitido = {"id-token"} if nome == "deploy_prod" else set()
        assert escritas <= permitido, f"{workflow.name}: job {nome} pode escrever em {escritas - permitido}"
