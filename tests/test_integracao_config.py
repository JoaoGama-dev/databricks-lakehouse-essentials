"""Testes de unidade da configuração dos testes de integração (Fase 5, docs/adr/0005).

Rodam sem Databricks: conferem o target ci, o workflow e as travas de segurança do
scripts/integracao.py, que nunca pode mexer num schema fora do CI.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
WORKFLOW = RAIZ / ".github" / "workflows" / "integracao.yml"


def carregar_script():
    especificacao = importlib.util.spec_from_file_location("integracao_ci", RAIZ / "scripts" / "integracao.py")
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


INTEGRACAO = carregar_script()


def bundle() -> dict:
    return yaml.safe_load((RAIZ / "databricks.yml").read_text(encoding="utf-8"))


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


# Target ci ---------------------------------------------------------------------------


def test_target_ci_usa_o_projeto_com_sufixo_ci():
    projeto = bundle()["variables"]["projeto"]["default"]
    ci = bundle()["targets"]["ci"]
    assert ci["mode"] == "development"
    assert ci["variables"]["projeto"] == f"{projeto}_ci"


def test_target_ci_pode_ser_destruido_e_nao_roda_sozinho():
    # Sem prevent_destroy na base nem no ci: a CLI antes da v1.22 ignora um override para
    # false, e o destroy do workflow seria recusado (docs/adr/0005).
    governanca = yaml.safe_load((RAIZ / "resources" / "governanca.yml").read_text(encoding="utf-8"))["resources"]
    recursos = bundle()["targets"]["ci"]["resources"]
    for tipo in ("schemas", "volumes"):
        assert tipo not in recursos, tipo
        assert all("lifecycle" not in recurso for recurso in governanca[tipo].values()), tipo
    assert recursos["jobs"]["essentials_carga_diaria"]["schedule"]["pause_status"] == "PAUSED"
    assert recursos["alerts"]["atraso_carga"]["schedule"]["pause_status"] == "PAUSED"


def test_dev_nao_tem_agendamento_ativo():
    dev = bundle()["targets"]["dev"]["resources"]
    assert dev["jobs"]["essentials_carga_diaria"]["schedule"]["pause_status"] == "PAUSED"


# Travas do scripts/integracao.py ----------------------------------------------------


@pytest.mark.parametrize("schema", ["dev_joao_portfolio_ci", "dev_joao_portfolio_ci_gold", "portfolio_ci_origem"])
def test_aceita_schemas_do_ci(schema):
    assert INTEGRACAO.verificar_schema_ci(schema) == schema


@pytest.mark.parametrize(
    "schema",
    [
        "dev_joao_portfolio",
        "dev_joao_portfolio_gold",
        "portfolio_origem",
        "portfolio",
        "ci_portfolio",
        "dev_joao_portfolio_ci; DROP CATALOG essentials",
        "dev_joao_portfolio_ci`.`x",
    ],
)
def test_recusa_qualquer_schema_fora_do_ci(schema):
    with pytest.raises(INTEGRACAO.SchemaForaDoCI):
        INTEGRACAO.verificar_schema_ci(schema)


def test_recusa_landing_fora_do_ci():
    with pytest.raises(INTEGRACAO.SchemaForaDoCI):
        INTEGRACAO.esvaziar_landing(None, "/Volumes/essentials/dev_joao_portfolio/landing")


def resumo(schema: str, gold: str, projeto: str = "portfolio_ci") -> dict:
    return {
        "variables": {"projeto": {"value": projeto}, "warehouse_id": {"value": "abc"}},
        "resources": {
            "schemas": {
                "projeto": {"catalog_name": "essentials", "name": schema},
                "gold": {"catalog_name": "essentials", "name": gold},
            },
            "jobs": {"essentials_carga_diaria": {"id": "1"}},
            "pipelines": {"essentials_pipeline": {"id": "p"}},
        },
    }


def test_recursos_do_resumo_do_bundle(tmp_path):
    arquivo = tmp_path / "recursos.json"
    arquivo.write_text(json.dumps(resumo("dev_joao_portfolio_ci", "dev_joao_portfolio_ci_gold")), encoding="utf-8")
    recursos = INTEGRACAO.carregar_recursos(arquivo)
    assert recursos["schema_origem"] == "portfolio_ci_origem"
    assert recursos["landing"] == "/Volumes/essentials/dev_joao_portfolio_ci/landing"


def test_resumo_de_outro_target_e_recusado(tmp_path):
    arquivo = tmp_path / "recursos.json"
    outro_target = resumo("dev_joao_portfolio", "dev_joao_portfolio_gold", "portfolio")
    arquivo.write_text(json.dumps(outro_target), encoding="utf-8")
    with pytest.raises(INTEGRACAO.SchemaForaDoCI):
        INTEGRACAO.carregar_recursos(arquivo)


def test_origem_do_ci_vem_do_setup():
    comandos = INTEGRACAO.comandos_origem("essentials", "portfolio_ci")
    assert len(comandos) == 3
    assert all("`essentials`.`portfolio_ci_origem`" in comando for comando in comandos)
    assert not any("essentials.portfolio_origem" in comando for comando in comandos)
    assert comandos[2].count("current_timestamp()") == 38


# Workflow ----------------------------------------------------------------------------


def gatilhos() -> dict:
    # O YAML lê a chave "on" como True.
    return workflow().get("on", workflow().get(True))


def test_workflow_nunca_roda_em_pull_request():
    assert "pull_request" not in gatilhos()
    assert "pull_request_target" not in gatilhos()
    assert {"workflow_dispatch", "schedule"} <= set(gatilhos())


def test_workflow_com_permissoes_minimas_e_sem_sobreposicao():
    assert workflow()["permissions"] == {}
    job = workflow()["jobs"]["integracao"]
    assert job["permissions"] == {"contents": "read"}
    assert workflow()["concurrency"]["cancel-in-progress"] is False


def passos() -> list[dict]:
    return workflow()["jobs"]["integracao"]["steps"]


def test_workflow_comeca_limpo():
    comandos = [passo.get("run", "") for passo in passos()]
    deploy = next(i for i, comando in enumerate(comandos) if "bundle deploy -t ci" in comando)
    limpeza = next(i for i, comando in enumerate(comandos) if "bundle destroy -t ci" in comando)
    assert limpeza < deploy
    assert "integracao.py limpar" in comandos[limpeza]


def test_workflow_segue_a_ordem_e_sempre_limpa():
    comandos = [passo.get("run", "") for passo in passos()]
    deploy = next(i for i, comando in enumerate(comandos) if "bundle deploy -t ci" in comando)
    comandos = comandos[deploy:]
    ordem = [
        "bundle deploy -t ci",
        "bundle summary -t ci",
        "integracao.py preparar",
        "--only governanca_antes",
        "--validate-only",
        "integracao.py enviar --versao 1",
        "INTEGRACAO_VERSAO=1",
        "integracao.py enviar --versao 2",
        "INTEGRACAO_VERSAO=2",
        "bundle destroy -t ci",
        "integracao.py limpar",
    ]
    posicoes = [next(i for i, comando in enumerate(comandos) if trecho in comando) for trecho in ordem]
    assert posicoes == sorted(posicoes), ordem
    # Depois do deploy, destroy e limpeza rodam mesmo quando um passo anterior falha.
    for passo in passos()[deploy:]:
        if "bundle destroy" in passo.get("run", "") or "integracao.py limpar" in passo.get("run", ""):
            assert passo["if"] == "always()", passo["name"]


def test_workflow_nunca_toca_em_prod():
    comandos = [passo.get("run", "") for passo in passos()]
    assert all("-t prod" not in comando and "--target prod" not in comando for comando in comandos)
    assert all("-t ci" in comando for comando in comandos if "databricks bundle" in comando)
