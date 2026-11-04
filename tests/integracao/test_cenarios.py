"""Cenários de risco e de falha no target ci (docs/adr/0014 e 0015).

Rodam depois das cargas v1 e v2, quando o workflow é disparado com cenarios_de_falha, nesta
ordem (cada um parte do estado deixado pelo anterior):

    INTEGRACAO_CENARIO=reenvio       agenda v5 (os bytes da v2 com outro nome): retrato e
                                     silver (SCD tipo 2) iguais aos da v2, sem versão nova
    INTEGRACAO_CENARIO=atrasado      agenda v6 (a v1 chegando depois): a data de referência
                                     mantém o retrato da v2, e mon_estrutura avisa
                                     arquivo_ignorado
    INTEGRACAO_CENARIO=so_cabecalho  agenda v7 (só o cabeçalho): o retrato da v2 fica, e
                                     mon_estrutura avisa arquivo_ignorado
    INTEGRACAO_CENARIO=full_refresh  full refresh do pipeline: bronze e silver SCD2 preservadas
                                     (pipelines.reset.allowed = false), silver e gold iguais
    INTEGRACAO_CENARIO=cp1252        agenda v8 (a v2 em cp1252): a carga passa, e
                                     mon_estrutura avisa codificacao_invalida
    INTEGRACAO_CENARIO=v3            agenda v3 (só o último mês): a carga passa, e mon_volume
                                     avisa a queda (a coluna nova na origem é conferida no teste
                                     de unidade de colunas_novas_na_origem)
    INTEGRACAO_CENARIO=v4            agenda v4 (entrevista em 2019): a regra data_plausivel
                                     para a carga, e mon_falhas guarda o motivo sem nenhum
                                     dado do registro
"""

from __future__ import annotations

import os

import pytest
from esperado import ESPERADO

CENARIO = os.environ.get("INTEGRACAO_CENARIO", "")
CENARIOS = ("reenvio", "atrasado", "so_cabecalho", "full_refresh", "cp1252", "v3", "v4")
MOTIVO_V4 = "Regra de qualidade que para a carga foi violada: data_plausivel. Confira o arquivo enviado."
# Arquivo de cada versão enviada (scripts/integracao.py enviar --versao).
REENVIO, ATRASADO, SO_CABECALHO, CP1252, V3 = (f"agenda_exemplo_v{n}.csv" for n in (5, 6, 7, 8, 3))
# Arquivos que chegaram à bronze até o full refresh, cada um numa carga: v1, v2, v5, v6, v7.
ARQUIVOS_ANTES_DO_FULL_REFRESH = 5
# Os cenários reenvio, atrasado, só cabeçalho e full refresh não podem mudar o que a v2 gravou.
CENARIOS_COM_A_SILVER_DA_V2 = ("reenvio", "atrasado", "so_cabecalho", "full_refresh")
NOME_DO_ARQUIVO = "element_at(split(_arquivo_origem, '/'), -1)"
VIGENTE = "__END_AT IS NULL"


@pytest.fixture(scope="module", autouse=True)
def cenario_definido():
    if CENARIO not in CENARIOS:
        pytest.fail(f"defina INTEGRACAO_CENARIO com um destes: {', '.join(CENARIOS)}")


def so_no(*cenarios: str):
    return pytest.mark.skipif(CENARIO not in cenarios, reason=f"cenário {', '.join(cenarios)}")


def arquivos_do_retrato(consultar) -> set[str]:
    """O retrato é privado do pipeline: o arquivo dele é o das versões vigentes da silver."""
    linhas = consultar(
        f"SELECT DISTINCT {NOME_DO_ARQUIVO} AS nm_arquivo FROM {{silver}}.silver_agenda WHERE {VIGENTE}"
    )
    return {linha["nm_arquivo"] for linha in linhas}


def vigentes(valor) -> int:
    return valor(f"SELECT count(*) FROM {{silver}}.silver_agenda WHERE {VIGENTE}")


def avisos_da_agenda(consultar) -> list[dict]:
    return consultar(
        "SELECT nm_tabela, ds_tipo, nm_coluna FROM {monitoramento}.mon_estrutura WHERE nm_tabela = 'bronze_agenda'"
    )


def aviso(tipo: str, arquivo: str) -> dict:
    return {"nm_tabela": "bronze_agenda", "ds_tipo": tipo, "nm_coluna": arquivo}


# Cenários de risco: reenvio, atrasado, só cabeçalho, full refresh e cp1252 -----------------


@so_no("reenvio", "atrasado", "so_cabecalho", "cp1252")
def test_carga_do_cenario_passa(ultima_carga):
    assert ultima_carga["atualizar_lakehouse"] == "SUCCESS"
    assert ultima_carga["governanca_depois"] == "SUCCESS"


@so_no(*CENARIOS_COM_A_SILVER_DA_V2)
def test_silver_continua_a_da_v2(valor):
    esperado = ESPERADO[2]
    assert vigentes(valor) == esperado["vigentes"]
    # Nenhuma versão nova: o mesmo total e as mesmas versões fechadas da v2 (as colunas
    # técnicas, como o arquivo de origem, são atualizadas na versão vigente sem versão nova).
    assert valor("SELECT count(*) FROM {silver}.silver_agenda") == esperado["versoes"]
    fechadas = valor("SELECT count(*) FROM {silver}.silver_agenda WHERE __END_AT IS NOT NULL")
    assert fechadas == esperado["fechadas"]


@so_no("reenvio")
def test_reenvio_vira_o_retrato_sem_aviso(consultar):
    # Mesmo conteúdo e mesma data de referência da v2: desempata pela ingestão mais recente.
    assert arquivos_do_retrato(consultar) == {REENVIO}
    tipos = {linha["ds_tipo"] for linha in avisos_da_agenda(consultar)}
    assert not tipos & {"arquivo_ignorado", "codificacao_invalida"}, tipos


@so_no("atrasado")
def test_arquivo_atrasado_nao_vira_o_retrato_e_avisa(consultar):
    assert arquivos_do_retrato(consultar) == {REENVIO}
    assert aviso("arquivo_ignorado", ATRASADO) in avisos_da_agenda(consultar)


@so_no("so_cabecalho")
def test_arquivo_so_com_cabecalho_nao_vira_o_retrato_e_avisa(consultar):
    assert arquivos_do_retrato(consultar) == {REENVIO}
    assert aviso("arquivo_ignorado", SO_CABECALHO) in avisos_da_agenda(consultar)


@so_no("full_refresh")
def test_full_refresh_preserva_a_bronze(valor):
    # Cada arquivo continua com a ingestão da sua carga: a bronze não foi esvaziada e relida.
    arquivos = valor("SELECT count(DISTINCT _arquivo_origem) FROM {bronze}.bronze_agenda")
    ingestoes = valor("SELECT count(DISTINCT _ingerido_em) FROM {bronze}.bronze_agenda")
    assert arquivos == ingestoes == ARQUIVOS_ANTES_DO_FULL_REFRESH


@so_no("full_refresh")
def test_full_refresh_recusado_nao_apaga_a_silver_nem_a_gold(consultar, valor):
    assert arquivos_do_retrato(consultar) == {REENVIO}
    fato = valor("SELECT count(*) FROM {gold}.gold_fato_entrevista")
    assert fato == vigentes(valor) > 0


@so_no("cp1252")
def test_arquivo_fora_do_utf8_avisa_sem_parar_a_carga(consultar):
    assert arquivos_do_retrato(consultar) == {CP1252}
    assert aviso("codificacao_invalida", CP1252) in avisos_da_agenda(consultar)


# Cenários de falha: v3 e v4 ------------------------------------------------------------------


@so_no("v3")
def test_v3_queda_de_volume_avisa_sem_parar_a_carga(consultar, ultima_carga):
    assert ultima_carga["atualizar_lakehouse"] == "SUCCESS"
    ultima = consultar(
        "SELECT qt_linhas, qt_linhas_anterior, fl_alerta FROM {monitoramento}.mon_volume "
        "WHERE nm_tabela = 'silver_int_agenda_retrato' ORDER BY dh_carga DESC LIMIT 1"
    )[0]
    assert ultima["fl_alerta"] == "true", ultima
    assert int(ultima["qt_linhas"]) < int(ultima["qt_linhas_anterior"]) / 2


@so_no("v4")
def test_v4_regra_falhar_para_a_carga_e_registra_o_motivo(consultar, ultima_carga):
    assert ultima_carga["atualizar_lakehouse"] == "FAILED"
    assert ultima_carga["registrar_falha"] == "FAILED", "registrar_falha termina com erro de propósito"
    falhas = consultar(
        "SELECT nm_tarefa, ds_motivo, ds_link FROM {monitoramento}.mon_falhas ORDER BY dh_falha DESC LIMIT 5"
    )
    assert {"nm_tarefa": "atualizar_lakehouse", "ds_motivo": MOTIVO_V4} == {
        chave: falhas[0][chave] for chave in ("nm_tarefa", "ds_motivo")
    }, falhas
    assert falhas[0]["ds_link"].startswith("https://")


@so_no("v4")
def test_v4_motivo_nao_tem_dado_pessoal(consultar):
    # Nenhum motivo pode trazer nome ou telefone: só o nome da regra e a orientação.
    motivos = [linha["ds_motivo"] for linha in consultar("SELECT ds_motivo FROM {monitoramento}.mon_falhas")]
    assert motivos and all(motivo == MOTIVO_V4 for motivo in motivos), motivos


@so_no("v4")
def test_v4_silver_continua_com_a_ultima_carga_boa(consultar, valor):
    # A carga com falha não grava nada: as versões vigentes seguem as da v3, e a fato bate com elas.
    assert arquivos_do_retrato(consultar) == {V3}
    assert vigentes(valor) > 0
    assert vigentes(valor) == valor("SELECT count(*) FROM {gold}.gold_fato_entrevista")
