"""Cenários de falha no target ci (Fase 7, docs/adr/0014 e 0015).

Rodam depois das cargas v1 e v2, quando o workflow é disparado com cenarios_de_falha:

    INTEGRACAO_CENARIO=v3 pytest -m integracao tests/integracao/test_cenarios.py
        agenda v3 (só o último mês) e coluna nova na origem cargos: a carga passa, e
        mon_volume e mon_estrutura avisam
    INTEGRACAO_CENARIO=v4 pytest -m integracao tests/integracao/test_cenarios.py
        agenda v4 (entrevista em 2019): a regra data_plausivel para a carga, e mon_falhas
        guarda o motivo sem nenhum dado do registro
"""

from __future__ import annotations

import os

import pytest

CENARIO = os.environ.get("INTEGRACAO_CENARIO", "")
MOTIVO_V4 = "Regra de qualidade que para a carga foi violada: data_plausivel. Confira o arquivo enviado."


@pytest.fixture(scope="module", autouse=True)
def cenario_definido():
    if CENARIO not in ("v3", "v4"):
        pytest.fail("defina INTEGRACAO_CENARIO=v3 ou v4")


@pytest.mark.skipif(CENARIO != "v3", reason="cenário v3")
def test_v3_queda_de_volume_avisa_sem_parar_a_carga(consultar, ultima_carga):
    assert ultima_carga["atualizar_lakehouse"] == "SUCCESS"
    ultima = consultar(
        "SELECT qt_linhas, qt_linhas_anterior, fl_alerta FROM {silver}.mon_volume "
        "WHERE nm_tabela = 'silver_int_agenda_retrato' ORDER BY dh_carga DESC LIMIT 1"
    )[0]
    assert ultima["fl_alerta"] == "true", ultima
    assert int(ultima["qt_linhas"]) < int(ultima["qt_linhas_anterior"]) / 2


@pytest.mark.skipif(CENARIO != "v3", reason="cenário v3")
def test_v3_coluna_nova_na_origem_aparece_em_mon_estrutura(consultar, integracao):
    avisos = consultar("SELECT nm_tabela, ds_tipo, nm_coluna FROM {silver}.mon_estrutura")
    esperado = {"nm_tabela": "bronze_cargos", "ds_tipo": "coluna_nova", "nm_coluna": integracao.COLUNA_NOVA_NA_ORIGEM}
    assert esperado in avisos, avisos


@pytest.mark.skipif(CENARIO != "v4", reason="cenário v4")
def test_v4_regra_falhar_para_a_carga_e_registra_o_motivo(consultar, ultima_carga):
    assert ultima_carga["atualizar_lakehouse"] == "FAILED"
    assert ultima_carga["registrar_falha"] == "FAILED", "registrar_falha termina com erro de propósito"
    falhas = consultar(
        "SELECT nm_tarefa, ds_motivo, ds_link FROM {silver}.mon_falhas ORDER BY dh_falha DESC LIMIT 5"
    )
    assert {"nm_tarefa": "atualizar_lakehouse", "ds_motivo": MOTIVO_V4} == {
        chave: falhas[0][chave] for chave in ("nm_tarefa", "ds_motivo")
    }, falhas
    assert falhas[0]["ds_link"].startswith("https://")


@pytest.mark.skipif(CENARIO != "v4", reason="cenário v4")
def test_v4_motivo_nao_tem_dado_pessoal(consultar):
    # Nenhum motivo pode trazer nome ou telefone: só o nome da regra e a orientação.
    motivos = [linha["ds_motivo"] for linha in consultar("SELECT ds_motivo FROM {silver}.mon_falhas")]
    assert motivos and all(motivo == MOTIVO_V4 for motivo in motivos), motivos


@pytest.mark.skipif(CENARIO != "v4", reason="cenário v4")
def test_v4_silver_continua_com_a_ultima_carga_boa(valor):
    # A carga com falha não grava nada: a silver segue com o retrato da v3.
    assert valor("SELECT count(*) FROM {silver}.silver_agenda") > 0
