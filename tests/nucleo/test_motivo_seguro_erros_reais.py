"""motivo_seguro contra mensagens de erro realistas do Spark, do Delta e do Python.

Todos os valores são fictícios. Cada caso traz um valor do dado dentro da mensagem; o motivo
gravado em mon_log_* ou enviado por e-mail não pode conter nenhum deles. Com a lista de
permissões, o motivo é só texto montado por nós: a classe do erro, os nomes das regras e a
etapa. Os antigos limites conhecidos (valor minúsculo sem aspas, nome único no começo da
linha) agora são asserções normais.
"""

from __future__ import annotations

import re

import pytest

from essentials.monitoramento_sql import MOTIVO_SEM_CLASSE, classe_do_erro, motivo_seguro

VALORES = ("Maria Souza", "Fulano", "Tal", "12345678909", "fulano@exemplo.com", "31/02/2020", "98765")

COM_VALOR = [
    # Spark
    "[CAST_INVALID_INPUT] The value 'Maria Souza' of the type \"STRING\" cannot be cast to \"INT\" "
    "because it is malformed. Correct the value as per the syntax.",
    "The value Maria Souza of the type STRING cannot be cast to INT",
    "java.lang.NumberFormatException: For input string: \"Fulano\"",
    "org.apache.spark.SparkNumberFormatException: For input string: '12345678909'",
    "[DATETIME_PATTERN_RECOGNITION] Fail to parse '31/02/2020' in the new parser.",
    "Failed to parse date 31/02/2020 with pattern yyyy-MM-dd",
    "[INVALID_ARRAY_INDEX] The index 98765 is out of bounds.",
    "Cannot cast Maria Souza to DATE",
    # Delta
    "DeltaUnsupportedOperationException: Cannot perform Merge as multiple source rows matched "
    "and attempted to modify the same target row: id_pessoa=98765 nm_pessoa='Maria Souza'",
    "Duplicate key found: ('Fulano', 'fulano@exemplo.com')",
    "[DELTA_FAILED_TO_MERGE_FIELDS] Failed to merge fields 'nm_pessoa' and 'Maria Souza'",
    "Cannot write nullable values to non-null column 'nm_pessoa' (value: Maria Souza)",
    # Python / Databricks
    "ValueError: invalid literal for int() with base 10: 'Fulano'",
    "ValueError: time data '31/02/2020' does not match format '%Y-%m-%d'",
    "ValueError: could not convert string to float: 'Maria Souza'",
    "KeyError: 'fulano@exemplo.com'",
    "AssertionError: esperado 98765, veio Fulano",
    "Run failed with error message: Fulano falhou ao processar 12345678909",
    # Valor só na segunda linha: a primeira linha é a única que fica
    "Falha ao gravar a silver\nRow: Maria Souza, fulano@exemplo.com, 12345678909",
]


@pytest.mark.parametrize("mensagem", COM_VALOR)
def test_motivo_de_erro_real_nunca_carrega_o_valor_do_dado(mensagem):
    motivo = motivo_seguro(mensagem)
    assert motivo
    for valor in VALORES:
        assert valor not in motivo, (valor, motivo)
    assert "\n" not in motivo


def test_motivo_continua_dizendo_o_que_deu_errado():
    motivo = motivo_seguro("DeltaUnsupportedOperationException: " + COM_VALOR[8].split(": ", 1)[1])
    # O diagnóstico técnico que sobrevive é a classe do problema; o resto fica no link.
    assert motivo == (
        "Erro DeltaUnsupportedOperationException: veja a mensagem completa pelo link da execução."
    )
    assert "id_pessoa=98765" not in motivo


def test_regra_falhar_violada_mostra_so_o_nome_da_regra():
    mensagem = (
        "[EXPECTATION_VIOLATION.VERBOSE_ALL] Flow 'silver_x' failed.\n"
        "Violated expectations: 'data_recente'\n"
        "Input data: {nm_pessoa: Maria Souza, nr_cpf: 12345678909}"
    )
    motivo = motivo_seguro(mensagem)
    assert "data_recente" in motivo
    assert not any(valor in motivo for valor in VALORES)


def test_motivo_respeita_o_tamanho_maximo_mesmo_sem_dado():
    from essentials.monitoramento_sql import TAMANHO_MAXIMO_MOTIVO

    assert len(motivo_seguro("erro tecnico " * 100)) <= TAMANHO_MAXIMO_MOTIVO


# Antigos limites conhecidos: agora nada passa ---------------------------------------------


@pytest.mark.parametrize(
    "mensagem",
    [
        "Cannot parse value fulano for column nm_pessoa",
        "KeyError: fulano de tal",
    ],
)
def test_valor_minusculo_sem_aspas_nao_passa(mensagem):
    motivo = motivo_seguro(mensagem)
    assert "fulano" not in motivo.lower()
    assert "tal" not in re.findall(r"\w+", motivo.lower())


def test_nome_unico_no_comeco_da_linha_nao_passa():
    assert "Fulano" not in motivo_seguro("Fulano falhou na carga")
    assert motivo_seguro("Fulano falhou na carga") == MOTIVO_SEM_CLASSE


# Propriedade: só a classe, os nomes de regra e o texto fixo -------------------------------

TEXTO_FIXO = {
    palavra.lower()
    for frase in (
        MOTIVO_SEM_CLASSE,
        "Erro na etapa: veja a mensagem completa pelo link da execução.",
        "Regra de qualidade que para a carga foi violada: . Confira o arquivo enviado.",
    )
    for palavra in re.findall(r"\w+", frase)
}
# Um nome, um nome só em minúsculas, um e-mail, um CPF, um telefone e um endereço: cada forma
# de dado pessoal real-like passa por todos os moldes de erro.
VALORES_VARIADOS = (
    "Maria Souza", "fulano", "joana.silva@exemplo.com", "123.456.789-09", "(41) 99999-0000",
    "rua das flores 100",
)
MOLDES = (
    "[CAST_INVALID_INPUT] The value '{v}' of the type \"STRING\" cannot be cast to \"INT\"",
    "org.apache.spark.SparkNumberFormatException: For input string: {v}",
    "ValueError: invalid literal for int() with base 10: {v}",
    "KeyError: {v}",
    "{v} falhou na carga",
    "Erro ao processar {v} na linha 42",
    "Flow 'silver_x' failed. Violated expectations: 'data_recente'.\nInput record: {{nm: {v}}}",
    '{{"exceptions":[{{"class_name":"org.apache.spark.SparkException","message":"falhou {v}"}}]}}',
    "[DELTA_FAILED_TO_MERGE_FIELDS] Failed to merge fields 'nm_pessoa' and '{v}'",
)


@pytest.mark.parametrize("molde", MOLDES)
@pytest.mark.parametrize("valor", VALORES_VARIADOS)
@pytest.mark.parametrize("etapa", [None, "SETTING_UP_TABLES"])
def test_motivo_so_tem_palavras_permitidas(molde, valor, etapa):
    mensagem = molde.format(v=valor)
    motivo = motivo_seguro(mensagem, etapa, regras={"data_recente"})
    classe = classe_do_erro(mensagem) or ""
    permitidas = TEXTO_FIXO | {"data_recente", etapa.lower() if etapa else ""} | {
        parte.lower() for parte in re.findall(r"\w+", classe)
    }
    palavras = {palavra.lower() for palavra in re.findall(r"\w+", motivo)}
    assert palavras <= permitidas, (mensagem, motivo, palavras - permitidas)
    for parte in re.findall(r"\w+", valor):
        if parte.lower() not in permitidas:
            assert parte.lower() not in palavras, (valor, motivo)
