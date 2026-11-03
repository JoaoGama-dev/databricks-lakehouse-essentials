"""Testes da governança no Unity Catalog como código (Fase 3).

Conferem o modelo de acesso declarado no bundle (resources/governanca.yml): quem chega a
cada schema e ao volume, e que nada do projeto pode ser apagado por um destroy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from essentials.config_fontes import carregar_fontes, colunas_sensiveis, validar_config
from essentials.governanca_sql import FUNCAO_MASCARA, sql_funcao_mascara, sqls_tags_pii

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


# 3.3 e 3.4 Dados pessoais: máscara e tags -----------------------------------------

FONTES = carregar_fontes(RAIZ / "config" / "fontes.yml")
SENSIVEIS = {coluna for fonte in FONTES for coluna in colunas_sensiveis(fonte)}


def test_colunas_sensiveis_estao_marcadas():
    assert SENSIVEIS == {"nm_candidato", "nr_telefone"}


def test_coluna_mascarada_precisa_ser_sensivel():
    config = yaml.safe_load((RAIZ / "config" / "fontes.yml").read_text(encoding="utf-8"))
    del config["fontes"][0]["colunas"]["nr_telefone"]["sensivel"]
    with pytest.raises(ValueError, match="sensivel: true: nr_telefone"):
        validar_config(config)


def test_toda_coluna_sensivel_da_gold_tem_mascara():
    sql = (RAIZ / "src" / "pipeline" / "gold_entrevistas.sql").read_text(encoding="utf-8")
    for linha in sql.splitlines():
        coluna = re.match(r"\s+(\w+) [A-Z]+ COMMENT", linha)
        if coluna and coluna.group(1) in SENSIVEIS:
            assert linha.rstrip(",").endswith(f"MASK ${{catalogo}}.${{schema_projeto}}.{FUNCAO_MASCARA}"), linha


def test_funcao_de_mascara_libera_so_o_grupo_de_dados_pessoais():
    sql = sql_funcao_mascara("essentials", "portfolio", "essentials_dados_pessoais")
    assert sql.startswith("CREATE OR REPLACE FUNCTION `essentials`.`portfolio`.`mascarar_dado_pessoal`")
    assert "is_account_group_member('essentials_dados_pessoais')" in sql
    assert "ELSE '****'" in sql


def test_tags_pii_cobrem_silver_e_gold():
    colunas_gold = {
        "gold_fato_entrevista": ["dt_entrevista", "nm_candidato", "nr_telefone"],
        "gold_dim_cargo": ["id_cargo", "nm_area"],
        "__materialization_mat_abc_gold_fato_entrevista_1": ["nm_candidato"],
    }
    comandos = sqls_tags_pii("essentials", "portfolio", "portfolio_gold", FONTES, colunas_gold)
    alvos = {re.search(r"ALTER TABLE (\S+) ALTER COLUMN `(\w+)`", c).groups() for c in comandos}
    assert ("`essentials`.`portfolio`.`silver_agenda`", "nm_candidato") in alvos
    assert ("`essentials`.`portfolio`.`silver_agenda_historico`", "nr_telefone") in alvos
    assert ("`essentials`.`portfolio`.`silver_int_agenda_retrato`", "nm_candidato") in alvos
    assert ("`essentials`.`portfolio_gold`.`gold_fato_entrevista`", "nm_candidato") in alvos
    assert not any(tabela.endswith("`gold_dim_cargo`") for tabela, _ in alvos)
    assert not any("__materialization" in tabela for tabela, _ in alvos), "tabela interna não recebe tag"
    assert all("SET TAGS ('pii' = 'true')" in c for c in comandos)


def test_job_cria_a_mascara_antes_e_aplica_as_tags_depois_do_pipeline():
    job = carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]["essentials_carga_diaria"]
    tarefas = {tarefa["task_key"]: tarefa for tarefa in job["tasks"]}
    dependencias = {d["task_key"] for d in tarefas["atualizar_lakehouse"]["depends_on"]}
    assert "governanca_antes" in dependencias
    assert [d["task_key"] for d in tarefas["governanca_depois"]["depends_on"]] == ["atualizar_lakehouse"]
    for chave, etapa in (("governanca_antes", "antes"), ("governanca_depois", "depois")):
        parametros = tarefas[chave]["spark_python_task"]["parameters"]
        assert parametros[parametros.index("--etapa") + 1] == etapa
