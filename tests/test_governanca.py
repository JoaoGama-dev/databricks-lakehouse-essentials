"""Testes da governança no Unity Catalog como código (Fase 3).

Conferem o modelo de acesso declarado no bundle (resources/governanca.yml): quem chega a
cada schema e ao volume, e que nada do projeto pode ser apagado por um destroy.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]


def carregar_yaml(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def recursos() -> dict:
    return carregar_yaml(RAIZ / "resources" / "governanca.yml")["resources"]


def grants(recurso: dict) -> dict[str, set[str]]:
    return {g["principal"]: set(g["privileges"]) for g in recurso["grants"]}


def test_schemas_e_volume_do_projeto_estao_no_bundle():
    assert set(recursos()["schemas"]) == {"projeto", "gold"}
    assert set(recursos()["volumes"]) == {"landing"}
    assert recursos()["schemas"]["projeto"]["name"] == "${var.projeto}"
    assert recursos()["schemas"]["gold"]["name"] == "${var.projeto}_gold"


def test_nada_do_projeto_pode_ser_apagado_por_destroy():
    for tipo in ("schemas", "volumes"):
        for nome, recurso in recursos()[tipo].items():
            assert recurso["lifecycle"]["prevent_destroy"] is True, f"{tipo}.{nome}"


def test_leitura_so_chega_a_gold():
    projeto, gold = recursos()["schemas"]["projeto"], recursos()["schemas"]["gold"]
    landing = recursos()["volumes"]["landing"]
    assert "${var.grupo_leitura_gold}" not in grants(projeto)
    assert "${var.grupo_leitura_gold}" not in grants(landing)
    assert grants(gold)["${var.grupo_leitura_gold}"] == {"USE_SCHEMA", "SELECT"}


def test_engenharia_administra_os_schemas_e_a_landing():
    for recurso in (recursos()["schemas"]["projeto"], recursos()["schemas"]["gold"]):
        assert grants(recurso)["${var.grupo_engenharia}"] == {"ALL_PRIVILEGES"}
    assert grants(recursos()["volumes"]["landing"])["${var.grupo_engenharia}"] == {"READ_VOLUME", "WRITE_VOLUME"}


def test_ninguem_alem_da_engenharia_tem_privilegio_amplo():
    for tipo in ("schemas", "volumes"):
        for recurso in recursos()[tipo].values():
            for principal, privilegios in grants(recurso).items():
                if principal != "${var.grupo_engenharia}":
                    assert not privilegios & {"ALL_PRIVILEGES", "MODIFY", "MANAGE", "WRITE_VOLUME"}, principal


def test_grupos_sao_variaveis_trocadas_em_producao():
    bundle = carregar_yaml(RAIZ / "databricks.yml")
    for grupo in ("grupo_engenharia", "grupo_leitura_gold", "grupo_dados_pessoais"):
        assert grupo in bundle["variables"]
        assert grupo in bundle["targets"]["prod"]["variables"]


def test_landing_de_producao_e_volume_externo():
    prod = carregar_yaml(RAIZ / "databricks.yml")["targets"]["prod"]
    landing = prod["resources"]["volumes"]["landing"]
    assert landing["volume_type"] == "EXTERNAL"
    assert landing["storage_location"].startswith("abfss://")


def test_gold_e_publicada_no_schema_gold():
    sql = (RAIZ / "src" / "pipeline" / "gold_entrevistas.sql").read_text(encoding="utf-8")
    criadas = re.findall(r"CREATE OR REFRESH MATERIALIZED VIEW (\S+)", sql)
    assert criadas and all(nome.startswith("${schema_gold}.gold_") for nome in criadas), criadas
