"""Testes de unidade do target ci do bundle, usado pelos testes de integração (Fase 5,
docs/adr/0005).

Rodam sem Databricks. O script e o workflow que carregam o exemplo no ci são da camada do
projeto: tests/projeto/test_integracao_do_exemplo.py.
"""

from __future__ import annotations

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]


def bundle() -> dict:
    return yaml.safe_load((RAIZ / "databricks.yml").read_text(encoding="utf-8"))


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
