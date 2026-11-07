"""Testes da configuração do Claude Code: permissões, subagentes, skills e evals.

Não chamam o modelo; garantem que nada perigoso fica liberado, que os agentes de revisão
não editam e que os dados dos evals são reconhecidos como sensíveis.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
CLAUDE = RAIZ / ".claude"
AGENTES = sorted((CLAUDE / "agents").glob("*.md"))
SKILLS = sorted(p.parent for p in (CLAUDE / "skills").glob("*/SKILL.md"))
EVALS = sorted(p for p in (RAIZ / "tests" / "evals").iterdir() if p.is_dir())
FERRAMENTAS = {"Read", "Glob", "Grep", "Edit", "Write", "Bash", "PowerShell", "Skill", "WebFetch", "WebSearch"}
MODELOS = {"sonnet", "opus", "haiku", "fable", "inherit"}


def frontmatter(caminho: Path) -> tuple[dict, str]:
    texto = caminho.read_text(encoding="utf-8")
    assert texto.startswith("---\n"), f"{caminho} precisa começar com o frontmatter"
    _, cabecalho, corpo = texto.split("---\n", 2)
    return yaml.safe_load(cabecalho), corpo


def configuracao() -> dict:
    return json.loads((CLAUDE / "settings.json").read_text(encoding="utf-8"))


# settings.json --------------------------------------------------------------------


def test_regras_de_permissao_tem_sintaxe_valida():
    permissoes = configuracao()["permissions"]
    for tipo in ("allow", "ask", "deny"):
        for regra in permissoes[tipo]:
            assert re.fullmatch(r"(Bash|PowerShell|Read|Edit)\(.+\)", regra), regra


def test_negacoes_essenciais_existem():
    deny = configuracao()["permissions"]["deny"]
    for regra in (
        "Bash(databricks bundle deploy -t prod*)",
        "PowerShell(databricks bundle deploy -t prod*)",
        "Bash(git push --force*)",
        "Read(./.env)",
        "Read(./data/privado/**)",
    ):
        assert regra in deny
    assert "Edit(./.github/workflows/deploy.yml)" in configuracao()["permissions"]["ask"]


def test_nada_perigoso_esta_liberado():
    for regra in configuracao()["permissions"]["allow"]:
        assert not re.search(r"deploy|destroy|push|commit|fs cp|bundle run", regra), regra


# Subagentes -----------------------------------------------------------------------


@pytest.mark.parametrize("caminho", AGENTES, ids=lambda p: p.stem)
def test_subagente_tem_frontmatter_valido(caminho):
    # Frontmatter inválido faz o Claude Code ignorar o agente ou dar ferramentas erradas.
    meta, _ = frontmatter(caminho)
    assert meta["name"] == caminho.stem
    assert meta["description"]
    assert meta["model"] in MODELOS
    ferramentas = {f.strip() for f in meta["tools"].split(",")}
    assert ferramentas <= FERRAMENTAS, ferramentas - FERRAMENTAS
    nomes_skills = {p.name for p in SKILLS}
    assert set(meta.get("skills", [])) <= nomes_skills


@pytest.mark.parametrize("caminho", AGENTES, ids=lambda p: p.stem)
def test_hooks_dos_subagentes_apontam_para_scripts_existentes(caminho):
    meta, _ = frontmatter(caminho)
    for grupos in meta.get("hooks", {}).values():
        for grupo in grupos:
            for hook in grupo["hooks"]:
                script = hook["args"][0].replace("${CLAUDE_PROJECT_DIR}/", "")
                assert (RAIZ / script).is_file(), script


def test_agentes_de_revisao_nao_editam():
    for nome in ("arquiteto-dados", "revisor-seguranca", "devops-dados"):
        meta, _ = frontmatter(CLAUDE / "agents" / f"{nome}.md")
        assert not {"Edit", "Write"} & {f.strip() for f in meta["tools"].split(",")}, nome


# Skills ---------------------------------------------------------------------------


def test_skill_com_efeito_colateral_nao_e_invocada_sozinha():
    meta, _ = frontmatter(CLAUDE / "skills" / "implantar-dev" / "SKILL.md")
    assert meta["disable-model-invocation"] is True


# Evals ----------------------------------------------------------------------------


def perfilar_dados():
    spec = importlib.util.spec_from_file_location("perfilar_dados", RAIZ / "scripts" / "perfilar_dados.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.mark.parametrize(
    ("arquivo", "sensiveis"),
    [
        ("novo-cliente/dados/agendamentos.csv", {"paciente": "nome próprio", "cpf": "cpf", "telefone": "telefone"}),
        ("nova-fonte/dados/admissoes.csv", {"nome_colaborador": "nome próprio", "cpf": "cpf"}),
    ],
)
def test_perfil_dos_evals_detecta_os_dados_sensiveis(arquivo, sensiveis):
    perfil = perfilar_dados().perfilar(RAIZ / "tests" / "evals" / arquivo)
    detectados = {c["nome"]: c["sensivel"] for c in perfil["colunas"] if c["sensivel"]}
    assert detectados == sensiveis
