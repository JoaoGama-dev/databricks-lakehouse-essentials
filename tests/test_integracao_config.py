"""Testes de unidade da configuração dos testes de integração (Fase 5, docs/adr/0005).

Rodam sem Databricks: conferem o target ci, o workflow e as travas de segurança do
scripts/integracao.py, que nunca pode mexer num schema fora do CI.
"""

from __future__ import annotations

import importlib.util
import json
import re
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
    # Só manual e agendado: nada de pull_request, pull_request_target nem push.
    assert set(gatilhos()) == {"workflow_dispatch", "schedule"}


def test_workflow_com_permissoes_minimas_e_sem_sobreposicao():
    assert workflow()["permissions"] == {}
    job = workflow()["jobs"]["integracao"]
    assert job["permissions"] == {"contents": "read"}
    assert workflow()["concurrency"]["cancel-in-progress"] is False


def passos() -> list[dict]:
    return workflow()["jobs"]["integracao"]["steps"]


# Cenários depois da v2: primeiro os de risco, que partem do estado da v2; a v3 e a v4 por último.
CENARIOS_DE_TESTE = ("reenvio", "atrasado", "so_cabecalho", "full_refresh", "cp1252", "v3", "v4")
CENARIOS_EM_ORDEM = (
    "integracao.py enviar --versao 5",
    "INTEGRACAO_CENARIO=reenvio",
    "integracao.py enviar --versao 6",
    "INTEGRACAO_CENARIO=atrasado",
    "integracao.py enviar --versao 7",
    "INTEGRACAO_CENARIO=so_cabecalho",
    "--full-refresh-all",
    "INTEGRACAO_CENARIO=full_refresh",
    "integracao.py enviar --versao 8",
    "INTEGRACAO_CENARIO=cp1252",
    "integracao.py enviar --versao 3",
    "INTEGRACAO_CENARIO=v3",
    "integracao.py enviar --versao 4",
    "INTEGRACAO_CENARIO=v4",
)


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
        *CENARIOS_EM_ORDEM,
        "bundle destroy -t ci",
        "integracao.py limpar",
    ]
    posicoes = [next(i for i, comando in enumerate(comandos) if trecho in comando) for trecho in ordem]
    assert posicoes == sorted(posicoes), ordem
    # Depois do deploy, destroy e limpeza rodam mesmo quando um passo anterior falha.
    for passo in passos()[deploy:]:
        if "bundle destroy" in passo.get("run", "") or "integracao.py limpar" in passo.get("run", ""):
            assert passo["if"] == "always()", passo["name"]


def test_cenarios_so_rodam_quando_pedidos_e_cada_um_tem_conferencia():
    comandos = [passo.get("run", "") for passo in passos()]
    v2 = next(i for i, comando in enumerate(comandos) if "INTEGRACAO_VERSAO=2" in comando)
    destroy = next(i for i, comando in enumerate(comandos) if "bundle destroy -t ci" in comando and i > v2)
    cenarios = passos()[v2 + 1 : destroy]
    assert cenarios and all(passo["if"] == "inputs.cenarios_de_falha" for passo in cenarios)
    # Um passo de carga e um de conferência por cenário, alternados.
    conferencias = [passo["run"] for passo in cenarios[1::2]]
    assert all(run.startswith("INTEGRACAO_CENARIO=") and "tests/integracao/test_cenarios.py" in run
               for run in conferencias), conferencias
    assert len(cenarios) == 2 * len(CENARIOS_DE_TESTE)


def test_todo_cenario_do_workflow_existe_em_test_cenarios():
    texto = WORKFLOW.read_text(encoding="utf-8")
    nomes = re.findall(r"INTEGRACAO_CENARIO=(\w+)", texto)
    assert tuple(nomes) == CENARIOS_DE_TESTE
    codigo = (RAIZ / "tests" / "integracao" / "test_cenarios.py").read_text(encoding="utf-8")
    declarados = re.search(r"^CENARIOS = \((.*)\)$", codigo, re.MULTILINE).group(1)
    assert tuple(re.findall(r'"(\w+)"', declarados)) == CENARIOS_DE_TESTE


def test_full_refresh_recalcula_o_pipeline_e_recria_as_views():
    passo = next(p for p in passos() if "--full-refresh-all" in p.get("run", ""))
    linhas = passo["run"].strip().splitlines()
    assert linhas == [
        "databricks bundle run essentials_pipeline -t ci --full-refresh-all",
        "databricks bundle run essentials_carga_diaria -t ci --only governanca_depois",
    ]


def test_timeout_do_workflow_cabe_as_cargas_dos_cenarios():
    # Nove cargas de até 6 minutos, mais deploy, conferências e destroy.
    assert workflow()["jobs"]["integracao"]["timeout-minutes"] >= 9 * 6 + 20


def test_workflow_envia_so_versoes_da_lista_fechada():
    texto = WORKFLOW.read_text(encoding="utf-8")
    enviadas = [int(n) for n in re.findall(r"integracao\.py enviar --versao (\d+)", texto)]
    assert enviadas == [1, 2, 5, 6, 7, 8, 3, 4]
    assert set(enviadas) <= set(INTEGRACAO.VERSOES_AGENDA)


def test_enviar_aceita_so_as_versoes_do_gerador():
    gerador = importlib.util.spec_from_file_location("gerador", RAIZ / "data" / "gerar_dados_exemplo.py")
    modulo = importlib.util.module_from_spec(gerador)
    gerador.loader.exec_module(modulo)
    nomes = [
        modulo.ARQUIVO_V1, modulo.ARQUIVO_V2, modulo.ARQUIVO_V3, modulo.ARQUIVO_V4,
        modulo.ARQUIVO_REENVIO, modulo.ARQUIVO_ATRASADO, modulo.ARQUIVO_SO_CABECALHO, modulo.ARQUIVO_CP1252,
    ]
    assert [INTEGRACAO.arquivo_da_versao(n).name for n in INTEGRACAO.VERSOES_AGENDA] == nomes
    assert all(INTEGRACAO.arquivo_da_versao(n).is_file() for n in INTEGRACAO.VERSOES_AGENDA)


@pytest.mark.parametrize("versao", [0, 9, -1, "1", "../privado/x"])
def test_enviar_recusa_versao_fora_da_lista(versao):
    with pytest.raises(ValueError, match="não existe"):
        INTEGRACAO.arquivo_da_versao(versao)


def test_workflow_nunca_toca_em_prod():
    comandos = [passo.get("run", "") for passo in passos()]
    assert all("-t prod" not in comando and "--target prod" not in comando for comando in comandos)
    assert all("-t ci" in comando for comando in comandos if "databricks bundle" in comando)
