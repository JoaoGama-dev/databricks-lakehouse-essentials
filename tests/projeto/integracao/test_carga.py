"""Confere os dados no target ci depois de cada rodada da carga (docs/adr/0005).

O workflow roda este arquivo duas vezes, depois da carga de cada rodada:

    INTEGRACAO_RODADA=1 pytest -m integracao tests/projeto/integracao/test_carga.py   agenda v1
    INTEGRACAO_RODADA=2 pytest -m integracao tests/projeto/integracao/test_carga.py   v2, v6, v7 e v5
"""

from __future__ import annotations

import os
import re

import pytest
from esperado import ESPERADO

RODADA = int(os.environ.get("INTEGRACAO_RODADA", "0"))
VIGENTE = "__END_AT IS NULL"
NOME_DO_ARQUIVO = "element_at(split(_arquivo_origem, '/'), -1)"
# A última execução do job registrada no log da carga.
ULTIMA = "(SELECT max_by(id_execucao_job, dh_inicio) FROM {monitoramento}.mon_log_execucao WHERE cd_nivel = 'job')"


def so_na_rodada(rodada: int):
    return pytest.mark.skipif(RODADA != rodada, reason=f"só na rodada {rodada}")


@pytest.fixture(scope="module")
def esperado() -> dict:
    if RODADA not in ESPERADO:
        pytest.fail("defina INTEGRACAO_RODADA=1 ou 2 (a rodada carregada por último)")
    return ESPERADO[RODADA]


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


@pytest.fixture(scope="module")
def log_da_carga(consultar) -> list[dict]:
    """Linhas do log mon_log_execucao da última execução do job."""
    return consultar(f"SELECT * FROM {{monitoramento}}.mon_log_execucao WHERE id_execucao_job = {ULTIMA}")


def da_tabela(log: list[dict], tabela: str) -> dict:
    return next(linha for linha in log if linha["cd_nivel"] == "tabela" and linha["nm_tabela"] == tabela)


def arquivos_do_retrato(consultar) -> set[str]:
    """O retrato é privado do pipeline: o arquivo dele é o das versões vigentes da silver."""
    linhas = consultar(
        f"SELECT DISTINCT {NOME_DO_ARQUIVO} AS nm_arquivo FROM {{silver}}.silver_agenda WHERE {VIGENTE}"
    )
    return {linha["nm_arquivo"] for linha in linhas}


# Tarefas do job ------------------------------------------------------------------------------


def test_carga_rodou_com_a_ingestao_pulada_e_sem_aviso_de_falha(ultima_carga):
    assert ultima_carga["ingerir_fontes_externas"] == "EXCLUDED"
    for tarefa in ("tem_fonte_externa", "preparar_governanca", "processar_medalhao", "publicar_monitoramento"):
        assert ultima_carga[tarefa] == "SUCCESS", tarefa
    # Sem falha, o aviso e o encerramento com erro não rodam.
    for tarefa in ("avisar_falha", "encerrar_com_falha"):
        assert ultima_carga.get(tarefa, "EXCLUDED") == "EXCLUDED", tarefa


# Silver, gold e qualidade --------------------------------------------------------------------


def test_retrato_e_privado_e_nao_aparece_no_catalogo(valor):
    publicadas = valor(
        "SELECT count(*) FROM {catalogo}.information_schema.tables "
        "WHERE table_schema IN ({nome_bronze}, {nome_silver}, {nome_gold}, {nome_monitoramento}) "
        "AND table_name LIKE 'silver_int_agenda%'"
    )
    assert publicadas == 0


def test_bronze_guarda_todo_arquivo_recebido(valor, esperado):
    assert valor("SELECT count(DISTINCT _arquivo_origem) FROM {bronze}.bronze_agenda") == esperado["arquivos_bronze"]


def test_retrato_e_o_arquivo_esperado(consultar, esperado):
    # Rodada 2: a v5 empata com a v2 na data de referência e ganha no desempate; a v6 (mais
    # antiga) e a v7 (sem linhas) nunca viram o retrato.
    assert arquivos_do_retrato(consultar) == esperado["retrato"]


def test_versoes_na_silver(valor, esperado):
    assert valor("SELECT count(*) FROM {silver}.silver_agenda") == esperado["versoes"]
    assert valor(f"SELECT count(*) FROM {{silver}}.silver_agenda WHERE {VIGENTE}") == esperado["vigentes"]
    fechadas = valor("SELECT count(*) FROM {silver}.silver_agenda WHERE __END_AT IS NOT NULL")
    assert fechadas == esperado["fechadas"]


def test_chave_sem_nula_e_sem_duplicada_nas_versoes_vigentes(valor):
    assert valor("SELECT count(*) FROM {silver}.silver_agenda WHERE dt_entrevista IS NULL OR nm_candidato IS NULL") == 0
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


def test_fato_e_view_tem_uma_linha_por_entrevista_vigente(valor, esperado):
    assert valor("SELECT count(*) FROM {gold}.gold_fato_entrevista") == esperado["vigentes"]
    # A view é criada pela publicar_monitoramento: sem ela, o painel fica vazio.
    assert valor("SELECT count(*) FROM {gold}.gold_vw_entrevistas") == esperado["vigentes"]
    # Toda entrevista tem área: o de-para cai em Não classificada quando nenhum prefixo combina.
    assert valor("SELECT count(*) FROM {gold}.gold_fato_entrevista WHERE nm_area IS NULL") == 0


# Governança e LGPD ---------------------------------------------------------------------------


def test_tags_de_camada_e_tipo_vem_das_propriedades(consultar):
    linhas = consultar(
        "SELECT schema_name, table_name, tag_name, tag_value FROM {catalogo}.information_schema.table_tags "
        "WHERE schema_name IN ({nome_bronze}, {nome_silver}, {nome_gold}, {nome_monitoramento}) "
        "AND tag_name IN ('camada', 'tipo') AND table_name IN "
        "('bronze_agenda', 'silver_agenda', 'gold_fato_entrevista', 'gold_vw_entrevistas', 'mon_qualidade_diaria', "
        "'mon_log_execucao')"
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
        ("mon_log_execucao", "camada"): "monitoramento",
        ("mon_log_execucao", "tipo"): "observabilidade",
    }, tags


def test_colunas_sensiveis_da_fato_tem_a_mascara(consultar, recursos):
    linhas = consultar(
        # Colunas conferidas no Free Edition: o schema é table_schema e mask_name vem com o nome
        # completo da função (catálogo.schema.função).
        "SELECT column_name, mask_name FROM {catalogo}.information_schema.column_masks "
        "WHERE table_schema = {nome_gold} AND table_name = 'gold_fato_entrevista'"
    )
    mascaras = {linha["column_name"]: linha["mask_name"] for linha in linhas}
    funcao = f"{recursos['catalogo']}.{recursos['schema_silver']}.mascarar_dado_pessoal"
    assert mascaras == {"nm_candidato": funcao, "nr_telefone": funcao}, mascaras


def test_telefone_da_silver_so_no_formato_mascarado(valor):
    # O telefone completo nunca chega à silver: só DDD e os 4 últimos dígitos (ou vazio).
    fora_do_formato = valor(
        r"SELECT count(*) FROM {silver}.silver_agenda "
        r"WHERE nr_telefone IS NOT NULL AND NOT nr_telefone RLIKE '^\\([0-9]{{2}}\\) [*]{{4}}-[0-9]{{4}}$'"
    )
    assert fora_do_formato == 0
    assert valor("SELECT count(*) FROM {silver}.silver_agenda WHERE nr_telefone IS NOT NULL") > 0


# Monitoramento -------------------------------------------------------------------------------


def test_avisos_de_estrutura_da_agenda(consultar, esperado):
    avisos = consultar(
        "SELECT ds_tipo, nm_coluna FROM {monitoramento}.mon_estrutura WHERE nm_tabela = 'bronze_agenda'"
    )
    # Vários arquivos na mesma carga: todos os que não viraram o retrato, exatamente.
    assert {linha["nm_coluna"] for linha in avisos if linha["ds_tipo"] == "arquivo_ignorado"} == esperado["ignorados"]
    assert {linha["ds_tipo"] for linha in avisos} <= {"arquivo_ignorado"}, avisos


def test_log_da_carga_tem_job_tarefas_e_tabelas_com_duracao_legivel(log_da_carga):
    niveis = {linha["cd_nivel"] for linha in log_da_carga}
    assert niveis == {"job", "tarefa", "tabela"}
    tabelas = {linha["nm_tabela"] for linha in log_da_carga if linha["cd_nivel"] == "tabela"}
    # O retrato privado não aparece: os números dele estão na silver_agenda.
    assert tabelas == {"bronze_agenda", "silver_agenda", "gold_fato_entrevista"}, tabelas
    assert all(linha["nm_tarefa"] == "processar_medalhao" for linha in log_da_carga if linha["cd_nivel"] == "tabela")
    duracoes = [linha["ds_duracao"] for linha in log_da_carga if linha["ds_duracao"] is not None]
    assert duracoes and all(re.fullmatch(r"\d{2,}:[0-5]\d:[0-5]\d", duracao) for duracao in duracoes), duracoes
    assert all(linha["ds_motivo_falha"] is None for linha in log_da_carga)


def test_log_da_silver_soma_os_descartes_e_alertas_do_retrato(log_da_carga, esperado):
    silver = da_tabela(log_da_carga, "silver_agenda")
    assert silver["ds_metodo_carga"] == "AUTO CDC FROM SNAPSHOT SCD2"
    assert int(silver["qt_linhas_descartadas"]) == sum(esperado["descartes"].values())
    assert int(silver["qt_linhas_alerta"]) == sum(esperado["alertas"].values())
    assert int(silver["qt_linhas_tabela"]) == esperado["versoes"]


@so_na_rodada(1)
def test_primeira_carga_nao_tem_atualizacao_anterior(log_da_carga):
    assert all(linha["dh_ultima_atualizacao_anterior"] is None for linha in log_da_carga)


@so_na_rodada(2)
def test_atualizacao_anterior_e_o_fim_da_rodada_1(consultar, log_da_carga):
    silver = da_tabela(log_da_carga, "silver_agenda")
    anterior = consultar(
        "SELECT dh_fim FROM {monitoramento}.mon_log_execucao "
        f"WHERE cd_nivel = 'tabela' AND nm_tabela = 'silver_agenda' AND id_execucao_job <> {ULTIMA} "
        "ORDER BY dh_fim DESC LIMIT 1"
    )
    assert silver["dh_ultima_atualizacao_anterior"] == anterior[0]["dh_fim"]
