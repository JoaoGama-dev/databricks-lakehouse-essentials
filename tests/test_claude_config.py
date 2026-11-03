"""Testes da configuração do Claude Code: settings, subagentes, skills, CLAUDE.md e evals.

Não chamam o modelo; garantem que a estrutura está completa e coerente.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
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


def test_existem_os_seis_subagentes():
    assert [p.stem for p in AGENTES] == [
        "arquiteto-dados",
        "devops-dados",
        "documentador",
        "engenheiro-dados",
        "qa-dados",
        "revisor-seguranca",
    ]


@pytest.mark.parametrize("caminho", AGENTES, ids=lambda p: p.stem)
def test_subagente_tem_frontmatter_valido(caminho):
    meta, corpo = frontmatter(caminho)
    assert meta["name"] == caminho.stem
    assert len(meta["description"]) >= 40
    assert meta["model"] in MODELOS
    ferramentas = {f.strip() for f in meta["tools"].split(",")}
    assert ferramentas <= FERRAMENTAS, ferramentas - FERRAMENTAS
    nomes_skills = {p.name for p in SKILLS}
    assert set(meta.get("skills", [])) <= nomes_skills
    assert "português" in corpo


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


def test_existem_as_oito_skills():
    assert [p.name for p in SKILLS] == [
        "adr",
        "entrega",
        "implantar-dev",
        "nova-fonte",
        "novo-cliente",
        "novo-indicador",
        "revisao-qualidade",
        "revisar-pr",
    ]


@pytest.mark.parametrize("pasta", SKILLS, ids=lambda p: p.name)
def test_skill_tem_descricao_passos_e_criterio_de_pronto(pasta):
    meta, corpo = frontmatter(pasta / "SKILL.md")
    assert meta["name"] == pasta.name
    assert meta["description"].startswith("Use ")
    assert re.search(r"^1\. ", corpo, re.MULTILINE), "passos numerados"
    assert "**Pronto quando:**" in corpo
    assert len(corpo.splitlines()) < 500


def test_skill_com_efeito_colateral_nao_e_invocada_sozinha():
    meta, _ = frontmatter(CLAUDE / "skills" / "implantar-dev" / "SKILL.md")
    assert meta["disable-model-invocation"] is True


# CLAUDE.md ------------------------------------------------------------------------


def test_claude_md_e_enxuto_e_aponta_para_os_padroes():
    texto = (RAIZ / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(texto.splitlines()) <= 100
    for arquivo in ("nomes.md", "camadas.md", "lgpd.md", "fluxo-de-trabalho.md"):
        assert f"docs/padroes/{arquivo}" in texto
        assert (RAIZ / "docs" / "padroes" / arquivo).is_file()


# Evals ----------------------------------------------------------------------------


def perfilar_dados():
    spec = importlib.util.spec_from_file_location("perfilar_dados", RAIZ / "scripts" / "perfilar_dados.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_existem_evals_das_skills_criticas():
    assert [p.name for p in EVALS] == ["nova-fonte", "novo-cliente"]


@pytest.mark.parametrize("caso", EVALS, ids=lambda p: p.name)
def test_eval_esta_completo(caso):
    assert (caso / "pedido.md").is_file()
    verificacoes = (caso / "verificacoes.md").read_text(encoding="utf-8")
    assert "## Obrigatórios" in verificacoes
    assert verificacoes.count("- [ ]") >= 8
    assert list((caso / "dados").glob("*.csv"))


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
