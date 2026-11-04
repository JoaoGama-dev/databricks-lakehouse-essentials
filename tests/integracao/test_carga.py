"""Confere os dados no target ci depois de uma carga (docs/adr/0005).

O workflow roda este arquivo duas vezes, depois da carga de cada versão da agenda:

    INTEGRACAO_VERSAO=1 pytest -m integracao tests/integracao
    INTEGRACAO_VERSAO=2 pytest -m integracao tests/integracao
"""

from __future__ import annotations

import os

import pytest
from esperado import ESPERADO

VERSAO = int(os.environ.get("INTEGRACAO_VERSAO", "0"))
VIGENTE = "__END_AT IS NULL"


@pytest.fixture(scope="module")
def esperado() -> dict:
    if VERSAO not in ESPERADO:
        pytest.fail("defina INTEGRACAO_VERSAO=1 ou 2 (a versão da agenda carregada por último)")
    return ESPERADO[VERSAO]


@pytest.fixture(scope="module")
def qualidade(consultar) -> dict[str, dict]:
    """Última atualização registrada em mon_qualidade_diaria, por regra da agenda.

    O retrato é privado do pipeline, mas as expectations dele chegam ao event log com o nome
    da tabela.
    """
    linhas = consultar(
        "SELECT nm_regra, qt_aprovadas, qt_descartadas, qt_alertas FROM {monitoramento}.mon_qualidade_diaria "
        "WHERE nm_tabela = 'silver_int_agenda_retrato' "
        "AND dt_execucao = (SELECT max(dt_execucao) FROM {monitoramento}.mon_qualidade_diaria)"
    )
    return {linha["nm_regra"]: {chave: int(v) for chave, v in linha.items() if chave != "nm_regra"} for linha in linhas}


def test_carga_rodou_com_as_ingestoes_puladas(ultima_carga):
    assert ultima_carga["ingestao_api"] == "EXCLUDED"
    assert ultima_carga["ingestao_banco"] == "EXCLUDED"
    for tarefa in ("governanca_antes", "atualizar_lakehouse", "governanca_depois"):
        assert ultima_carga[tarefa] == "SUCCESS", tarefa


def test_retrato_e_privado_e_nao_aparece_no_catalogo(valor):
    publicadas = valor(
        "SELECT count(*) FROM {catalogo}.information_schema.tables "
        "WHERE table_schema IN ({nome_bronze}, {nome_silver}, {nome_gold}, {nome_monitoramento}) "
        "AND table_name LIKE 'silver_int_agenda%'"
    )
    assert publicadas == 0


def test_versoes_na_silver(valor, esperado):
    assert valor("SELECT count(*) FROM {silver}.silver_agenda") == esperado["versoes"]
    assert valor(f"SELECT count(*) FROM {{silver}}.silver_agenda WHERE {VIGENTE}") == esperado["vigentes"]
    fechadas = valor("SELECT count(*) FROM {silver}.silver_agenda WHERE __END_AT IS NOT NULL")
    assert fechadas == esperado["fechadas"]


def test_nenhuma_chave_nula(valor):
    assert valor("SELECT count(*) FROM {silver}.silver_agenda WHERE dt_entrevista IS NULL OR nm_candidato IS NULL") == 0


def test_uma_versao_vigente_por_entrevista(valor):
    duplicadas = valor(
        f"SELECT count(*) FROM (SELECT dt_entrevista, nm_candidato FROM {{silver}}.silver_agenda WHERE {VIGENTE} "
        "GROUP BY ALL HAVING count(*) > 1)"
    )
    assert duplicadas == 0


def test_descartes_por_regra(qualidade, esperado):
    descartes = {regra: qualidade[regra]["qt_descartadas"] for regra in esperado["descartes"]}
    assert descartes == esperado["descartes"]
    retrato = qualidade["nome_preenchido"]["qt_aprovadas"] + qualidade["nome_preenchido"]["qt_descartadas"]
    assert retrato == esperado["linhas_retrato"]


def test_alertas_por_regra(qualidade, esperado):
    alertas = {regra: qualidade[regra]["qt_alertas"] for regra in esperado["alertas"]}
    assert alertas == esperado["alertas"]


def test_fato_tem_uma_linha_por_entrevista_vigente(valor, esperado):
    assert valor("SELECT count(*) FROM {gold}.gold_fato_entrevista") == esperado["vigentes"]
    # Toda entrevista tem área: o de-para cai em Não classificada quando nenhum prefixo combina.
    assert valor("SELECT count(*) FROM {gold}.gold_fato_entrevista WHERE nm_area IS NULL") == 0


def test_view_do_painel_bate_com_a_fato(valor):
    # A view é criada pela governanca_depois: sem ela, o painel fica vazio.
    assert valor("SELECT count(*) FROM {gold}.gold_vw_entrevistas") == valor(
        "SELECT count(*) FROM {gold}.gold_fato_entrevista"
    )


def test_tags_de_camada_e_tipo_vem_das_propriedades(consultar):
    linhas = consultar(
        "SELECT schema_name, table_name, tag_name, tag_value FROM {catalogo}.information_schema.table_tags "
        "WHERE schema_name IN ({nome_bronze}, {nome_silver}, {nome_gold}, {nome_monitoramento}) "
        "AND tag_name IN ('camada', 'tipo') AND table_name IN "
        "('bronze_agenda', 'silver_agenda', 'gold_fato_entrevista', 'gold_vw_entrevistas', 'mon_qualidade_diaria')"
    )
    tags = {(linha["table_name"], linha["tag_name"]): linha["tag_value"] for linha in linhas}
    assert tags == {
        ("bronze_agenda", "camada"): "bronze",
        ("bronze_agenda", "tipo"): "bruta",
        ("silver_agenda", "camada"): "silver",
        ("silver_agenda", "tipo"): "historico",
        ("gold_fato_entrevista", "camada"): "gold",
        ("gold_fato_entrevista", "tipo"): "fato",
        ("gold_vw_entrevistas", "camada"): "gold",
        ("gold_vw_entrevistas", "tipo"): "view",
        ("mon_qualidade_diaria", "camada"): "monitoramento",
        ("mon_qualidade_diaria", "tipo"): "qualidade",
    }, tags
