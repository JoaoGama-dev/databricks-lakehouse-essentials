"""Testes de unidade do script e do workflow que carregam o exemplo no target ci (Fase 5,
docs/adr/0005). Camada do projeto: scripts/integracao.py e .github/workflows/integracao.yml.

Rodam sem Databricks: conferem o workflow e as travas de segurança do scripts/integracao.py,
que nunca pode mexer num schema fora do CI.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
WORKFLOW = RAIZ / ".github" / "workflows" / "integracao.yml"
# A fonte do exemplo que o workflow carrega.
FONTE_DO_EXEMPLO = "agenda"


def carregar_script():
    especificacao = importlib.util.spec_from_file_location("integracao_ci", RAIZ / "scripts" / "integracao.py")
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


INTEGRACAO = carregar_script()


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


# Travas do scripts/integracao.py ----------------------------------------------------


@pytest.mark.parametrize(
    "schema",
    [
        "dev_joao_portfolio_ci_bronze",
        "dev_joao_portfolio_ci_silver",
        "dev_joao_portfolio_ci_gold",
        "dev_joao_portfolio_ci_monitoramento",
    ],
)
def test_aceita_schemas_do_ci(schema):
    assert INTEGRACAO.verificar_schema_ci(schema) == schema


def test_sufixos_aceitos_sao_os_quatro_schemas_do_ci():
    governanca = yaml.safe_load((RAIZ / "resources" / "governanca.yml").read_text(encoding="utf-8"))["resources"]
    assert {f"_ci_{camada}" for camada in governanca["schemas"]} == set(INTEGRACAO.SUFIXOS_CI)


@pytest.mark.parametrize(
    "schema",
    [
        "dev_joao_portfolio_bronze",
        "dev_joao_portfolio_silver",
        "dev_joao_portfolio_gold",
        "dev_joao_portfolio_monitoramento",
        # Sufixos antigos: o schema do projeto inteiro e a origem simulada não existem mais.
        "dev_joao_portfolio_ci",
        "portfolio_ci_origem",
        "portfolio",
        "ci_portfolio_bronze",
        "dev_joao_portfolio_ci_bronze; DROP CATALOG essentials",
        "dev_joao_portfolio_ci_bronze`.`x",
    ],
)
def test_recusa_qualquer_schema_fora_do_ci(schema):
    with pytest.raises(INTEGRACAO.SchemaForaDoCI):
        INTEGRACAO.verificar_schema_ci(schema)


@pytest.mark.parametrize(
    "landing",
    [
        "/Volumes/essentials/dev_joao_portfolio_bronze/landing",
        "/Volumes/essentials/dev_joao_portfolio_ci/landing",
        "/Volumes/essentials/dev_joao_portfolio_ci_gold/landing",
        "/Volumes/essentials",
    ],
)
def test_recusa_landing_fora_do_ci(landing):
    with pytest.raises(INTEGRACAO.SchemaForaDoCI):
        INTEGRACAO.esvaziar_landing(None, landing)


CAMADAS = ("bronze", "silver", "gold", "monitoramento")


def resumo(prefixo: str, projeto: str = "portfolio_ci", trocar: dict | None = None) -> dict:
    schemas = {camada: {"catalog_name": "essentials", "name": f"{prefixo}_{camada}"} for camada in CAMADAS}
    for camada, nome in (trocar or {}).items():
        schemas[camada]["name"] = nome
    return {
        "variables": {"projeto": {"value": projeto}, "warehouse_id": {"value": "abc"}},
        "resources": {
            "schemas": schemas,
            "jobs": {"essentials_carga_diaria": {"id": "1"}},
            "pipelines": {"essentials_pipeline": {"id": "p"}},
        },
    }


def test_recursos_do_resumo_do_bundle(tmp_path):
    arquivo = tmp_path / "recursos.json"
    arquivo.write_text(json.dumps(resumo("dev_joao_portfolio_ci")), encoding="utf-8")
    recursos = INTEGRACAO.carregar_recursos(arquivo)
    assert {recursos[f"schema_{camada}"] for camada in CAMADAS} == {f"dev_joao_portfolio_ci_{c}" for c in CAMADAS}
    # A landing fica no schema da bronze.
    assert recursos["landing"] == "/Volumes/essentials/dev_joao_portfolio_ci_bronze/landing"


@pytest.mark.parametrize(
    "outro_target",
    [
        resumo("dev_joao_portfolio", "portfolio"),
        # Um schema só fora do CI já basta para recusar o resumo inteiro.
        resumo("dev_joao_portfolio_ci", trocar={"gold": "dev_joao_portfolio_gold"}),
    ],
    ids=["dev", "um_schema_do_dev"],
)
def test_resumo_de_outro_target_e_recusado(tmp_path, outro_target):
    arquivo = tmp_path / "recursos.json"
    arquivo.write_text(json.dumps(outro_target), encoding="utf-8")
    with pytest.raises(INTEGRACAO.SchemaForaDoCI):
        INTEGRACAO.carregar_recursos(arquivo)


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


def comandos() -> list[str]:
    return [passo.get("run", "") for passo in passos()]


def test_workflow_comeca_limpo():
    deploy = next(i for i, comando in enumerate(comandos()) if "bundle deploy -t ci" in comando)
    limpeza = next(i for i, comando in enumerate(comandos()) if "bundle destroy -t ci" in comando)
    assert limpeza < deploy
    assert "integracao.py limpar" in comandos()[limpeza]


# Ordem das duas rodadas. A rodada 2 manda quatro arquivos numa carga só, nesta ordem: a v5
# (mesmo conteúdo da v2) por último, para ganhar o desempate do retrato.
ORDEM = [
    "bundle deploy -t ci",
    "bundle summary -t ci",
    "integracao.py preparar",
    "--only preparar_governanca",
    "--validate-only",
    f"integracao.py enviar --fonte {FONTE_DO_EXEMPLO} --versao 1\n",
    "bundle run essentials_carga_diaria -t ci\n",
    "INTEGRACAO_RODADA=1 pytest -m integracao tests/projeto/integracao/test_carga.py",
    f"integracao.py enviar --fonte {FONTE_DO_EXEMPLO} --versao 2 6 7 5\n",
    "bundle run essentials_carga_diaria -t ci\n",
    "INTEGRACAO_RODADA=2 pytest -m integracao tests/projeto/integracao/test_carga.py",
    "bundle destroy -t ci",
    "integracao.py limpar",
]


def test_workflow_segue_a_ordem_das_rodadas_e_sempre_limpa():
    deploy = next(i for i, comando in enumerate(comandos()) if "bundle deploy -t ci" in comando)
    depois = [comando + "\n" for comando in comandos()[deploy:]]
    posicoes = []
    inicio = 0
    for trecho in ORDEM:
        inicio = next(i for i in range(inicio, len(depois)) if trecho in depois[i])
        posicoes.append(inicio)
    assert posicoes == sorted(posicoes), ORDEM
    # Depois do deploy, destroy e limpeza rodam mesmo quando um passo anterior falha.
    for passo in passos()[deploy:]:
        if "bundle destroy" in passo.get("run", "") or "integracao.py limpar" in passo.get("run", ""):
            assert passo["if"] == "always()", passo["name"]


def test_workflow_sem_cenarios_opcionais_e_com_duas_cargas():
    # Cada carga custa tempo do Free Edition; um cenário que só roda quando lembram não protege nada.
    assert gatilhos()["workflow_dispatch"] is None
    cargas = [c for c in comandos() if "bundle run essentials_carga_diaria -t ci" in c and "--only" not in c]
    assert len(cargas) == 2
    assert all(passo.get("if", "always()") == "always()" for passo in passos())


def test_timeout_do_workflow_cabe_duas_cargas_sem_esconder_travamento():
    # Duas cargas de até 6 minutos, mais deploy, conferências e destroy (cerca de 15 minutos).
    assert workflow()["jobs"]["integracao"]["timeout-minutes"] == 30


def test_workflow_envia_so_versoes_da_lista_fechada():
    texto = WORKFLOW.read_text(encoding="utf-8")
    listas = re.findall(r"integracao\.py enviar --fonte (\w+) --versao ([\d ]+)", texto)
    assert {fonte for fonte, _ in listas} == {FONTE_DO_EXEMPLO}
    enviadas = [[int(n) for n in lista.split()] for _, lista in listas]
    assert enviadas == [[1], [2, 6, 7, 5]]
    assert all(set(lista) <= set(INTEGRACAO.VERSOES_EXEMPLO) for lista in enviadas)


def test_enviar_aceita_so_as_versoes_do_gerador():
    gerador = importlib.util.spec_from_file_location("gerador", RAIZ / "data" / "gerar_dados_exemplo.py")
    modulo = importlib.util.module_from_spec(gerador)
    gerador.loader.exec_module(modulo)
    nomes = [
        modulo.ARQUIVO_V1, modulo.ARQUIVO_V2, modulo.ARQUIVO_V3, modulo.ARQUIVO_V4,
        modulo.ARQUIVO_REENVIO, modulo.ARQUIVO_ATRASADO, modulo.ARQUIVO_SO_CABECALHO, modulo.ARQUIVO_CP1252,
    ]
    assert [INTEGRACAO.arquivo_da_versao(n).name for n in INTEGRACAO.VERSOES_EXEMPLO] == nomes
    assert all(INTEGRACAO.arquivo_da_versao(n).is_file() for n in INTEGRACAO.VERSOES_EXEMPLO)


@pytest.mark.parametrize("versao", [0, 9, -1, "1", "../privado/x"])
def test_enviar_recusa_versao_fora_da_lista(versao):
    with pytest.raises(ValueError, match="não existe"):
        INTEGRACAO.arquivo_da_versao(versao)


def test_enviar_varias_versoes_mantem_a_ordem_e_confere_todas_antes():
    # A ordem decide o desempate do retrato (a última enviada é a mais recente).
    assert [a.name for a in INTEGRACAO.arquivos_das_versoes([2, 6, 7, 5])] == [
        "agenda_exemplo_v2.csv", "agenda_exemplo_v6.csv", "agenda_exemplo_v7.csv", "agenda_exemplo_v5.csv",
    ]
    # Uma versão fora da lista recusa o envio inteiro, antes de mandar qualquer arquivo.
    with pytest.raises(ValueError, match="não existe"):
        INTEGRACAO.arquivos_das_versoes([2, 9])
    for invalida in ([], [2, 5, 2]):
        with pytest.raises(ValueError):
            INTEGRACAO.arquivos_das_versoes(invalida)


def test_enviar_usa_a_pasta_da_fonte_no_fontes_yml():
    # Risco: arquivo numa pasta que o Auto Loader não lê (a carga passa sem dado novo e a
    # conferência falha por outro motivo) ou, com outra fonte, na pasta errada.
    from essentials.config_fontes import carregar_fontes, pasta_landing

    fonte = next(f for f in carregar_fontes(INTEGRACAO.CONFIG) if f["nome"] == FONTE_DO_EXEMPLO)
    recursos = {"landing": "/Volumes/essentials/dev_joao_portfolio_ci_bronze/landing"}
    envios = INTEGRACAO.destinos(recursos, FONTE_DO_EXEMPLO, [2, 1])
    assert [destino for _, destino in envios] == [
        f"{recursos['landing']}/{pasta_landing(fonte)}/agenda_exemplo_v2.csv",
        f"{recursos['landing']}/{pasta_landing(fonte)}/agenda_exemplo_v1.csv",
    ]


@pytest.mark.parametrize("pasta", ["../privado", "/agenda", "agenda/../x", "agenda/", ""])
def test_enviar_recusa_fonte_que_nao_existe_ou_pasta_fora_da_landing(tmp_path, monkeypatch, pasta):
    with pytest.raises(ValueError, match="não está"):
        INTEGRACAO.pasta_da_fonte("nao_existe")
    import essentials.config_fontes

    fonte = {"nome": "x", "tipo": "arquivo", "arquivo": {"caminho": pasta}}
    monkeypatch.setattr(INTEGRACAO, "carregar_fontes", lambda caminho: [fonte])
    assert essentials.config_fontes.pasta_landing(fonte) == pasta
    with pytest.raises(ValueError, match="sem pasta válida"):
        INTEGRACAO.pasta_da_fonte("x")


def test_workflow_nunca_toca_em_prod():
    comandos = [passo.get("run", "") for passo in passos()]
    assert all("-t prod" not in comando and "--target prod" not in comando for comando in comandos)
    assert all("-t ci" in comando for comando in comandos if "databricks bundle" in comando)
