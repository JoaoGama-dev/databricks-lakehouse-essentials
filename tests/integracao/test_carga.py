"""Confere os dados no target ci depois de uma carga (docs/adr/0005).

O workflow roda este arquivo duas vezes, depois da carga de cada versão da agenda:

    INTEGRACAO_VERSAO=1 pytest -m integracao tests/integracao
    INTEGRACAO_VERSAO=2 pytest -m integracao tests/integracao
"""

from __future__ import annotations

import os

import pytest
from esperado import CARGOS, ESPERADO

VERSAO = int(os.environ.get("INTEGRACAO_VERSAO", "0"))


@pytest.fixture(scope="module")
def esperado() -> dict:
    if VERSAO not in ESPERADO:
        pytest.fail("defina INTEGRACAO_VERSAO=1 ou 2 (a versão da agenda carregada por último)")
    return ESPERADO[VERSAO]


@pytest.fixture(scope="module")
def qualidade(consultar) -> dict[str, dict]:
    """Última atualização registrada em mon_qualidade_diaria, por regra da agenda."""
    linhas = consultar(
        "SELECT nm_regra, qt_aprovadas, qt_descartadas, qt_alertas FROM {silver}.mon_qualidade_diaria "
        "WHERE nm_tabela = 'silver_int_agenda_retrato' "
        "AND dt_execucao = (SELECT max(dt_execucao) FROM {silver}.mon_qualidade_diaria)"
    )
    return {linha["nm_regra"]: {chave: int(v) for chave, v in linha.items() if chave != "nm_regra"} for linha in linhas}


def test_carga_rodou_com_as_ingestoes_puladas(ultima_carga):
    assert ultima_carga["ingestao_api"] == "EXCLUDED"
    assert ultima_carga["ingestao_banco"] == "EXCLUDED"
    for tarefa in ("governanca_antes", "atualizar_lakehouse", "governanca_depois"):
        assert ultima_carga[tarefa] == "SUCCESS", tarefa


def test_linhas_na_silver(valor, esperado):
    assert valor("SELECT count(*) FROM {silver}.silver_agenda") == esperado["silver_agenda"]
    assert valor("SELECT count(*) FROM {silver}.silver_cargos") == CARGOS


def test_nenhuma_chave_nula(valor):
    assert valor("SELECT count(*) FROM {silver}.silver_agenda WHERE dt_entrevista IS NULL OR nm_candidato IS NULL") == 0
    assert valor("SELECT count(*) FROM {silver}.silver_cargos WHERE id_cargo IS NULL") == 0


def test_nenhuma_chave_duplicada(valor):
    duplicadas = valor(
        "SELECT count(*) FROM (SELECT dt_entrevista, nm_candidato FROM {silver}.silver_agenda "
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


def test_versoes_no_historico(valor, esperado):
    assert valor("SELECT count(*) FROM {silver}.silver_agenda_historico") == esperado["historico"]
    fechadas = valor("SELECT count(*) FROM {silver}.silver_agenda_historico WHERE __END_AT IS NOT NULL")
    assert fechadas == esperado["historico_fechadas"]
    # Cada entrevista da silver tem exatamente uma versão aberta no histórico.
    abertas = valor("SELECT count(*) FROM {silver}.silver_agenda_historico WHERE __END_AT IS NULL")
    assert abertas == esperado["silver_agenda"]


def test_fato_tem_todas_as_entrevistas(valor, esperado):
    assert valor("SELECT count(*) FROM {gold}.gold_fato_entrevista") == esperado["silver_agenda"]


def test_agregada_bate_com_a_fato(valor):
    total_agregada = valor("SELECT sum(qt_entrevistas) FROM {gold}.gold_agg_entrevista_mensal")
    assert total_agregada == valor("SELECT count(*) FROM {gold}.gold_fato_entrevista")
