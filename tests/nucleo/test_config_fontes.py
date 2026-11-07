"""Testes do motor que lê o fontes.yml (src/essentials/config_fontes.py) e das partes
genéricas da bronze e da silver (src/pipeline/bronze.py e silver.py).

Rodam sem Databricks e só com as fontes fictícias de tests/nucleo/fontes_ficticias.py: valem
para qualquer cliente. O que depende do fontes.yml do projeto fica em
test_contrato_do_projeto.py; as regras de negócio do exemplo, em tests/projeto/.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from essentials.config_fontes import (
    ORDEM_DO_RETRATO,
    expectations,
    expressao_data_referencia,
    expressao_limpeza,
    expressao_regra,
    expressoes_silver,
    propriedades_tabela,
    regras_efetivas,
    schema_silver,
    tabelas_da_fonte,
    tipo_da_silver,
    validada_publicada,
    validar_config,
)
from fontes_ficticias import CADASTRO, EVENTOS, cadastro, config_ficticia, eventos

RAIZ = Path(__file__).resolve().parents[2]
PASTA_PIPELINE = RAIZ / "src" / "pipeline"


def silver_py() -> str:
    return (PASTA_PIPELINE / "silver.py").read_text(encoding="utf-8")


# Validação do fontes.yml ------------------------------------------------------------


def test_config_sem_campo_obrigatorio_e_rejeitada():
    config = config_ficticia()
    del config["fontes"][0]["chave_primaria"]
    with pytest.raises(ValueError, match="chave_primaria"):
        validar_config(config)


def test_tipo_sem_seu_bloco_e_rejeitado():
    config = config_ficticia()
    del config["fontes"][0]["arquivo"]
    with pytest.raises(ValueError):
        validar_config(config)


def test_regra_unico_so_aceita_alerta():
    config = config_ficticia()
    config["fontes"].append(cadastro())
    validar_config(config)
    next(r for r in config["fontes"][-1]["regras"] if r["tipo"] == "unico")["acao"] = "drop"
    with pytest.raises(ValueError):
        validar_config(config)


def test_historico_nao_vale_no_modo_incremental():
    config = config_ficticia()
    config["fontes"][0]["modo_carga"] = "incremental"
    config["fontes"][0]["historico"] = True
    with pytest.raises(ValueError):
        validar_config(config)


def test_nomes_de_fonte_repetidos_sao_rejeitados():
    config = config_ficticia()
    config["fontes"].append(copy.deepcopy(config["fontes"][0]))
    with pytest.raises(ValueError, match="repetidos"):
        validar_config(config)


def test_banco_incremental_exige_watermark():
    config = config_ficticia()
    config["fontes"].append(
        {
            "nome": "pedidos",
            "descricao": "Pedidos do ERP.",
            "tipo": "banco",
            "banco": {"conexao": "erp", "tabela_origem": "vendas.pedidos", "pasta_landing": "pedidos"},
            "modo_carga": "incremental",
            "chave_primaria": ["id_pedido"],
            "coluna_atualizacao": "_ingerido_em",
            "colunas": {"id_pedido": {"origem": "id", "tipo": "inteiro", "descricao": "Identificador do pedido."}},
        }
    )
    with pytest.raises(ValueError, match="coluna_watermark"):
        validar_config(config)


def test_coluna_da_regra_precisa_estar_declarada():
    config = config_ficticia()
    config["fontes"][0]["regras"][0]["coluna"] = "nm_que_nao_existe"
    with pytest.raises(ValueError, match="nm_que_nao_existe"):
        validar_config(config)


def test_coluna_sem_prefixo_conhecido_e_rejeitada():
    config = config_ficticia()
    colunas = config["fontes"][0]["colunas"]
    colunas["hora_evento"] = colunas.pop("hr_evento")
    with pytest.raises(ValueError, match="hora_evento"):
        validar_config(config)


def test_prefixo_precisa_combinar_com_o_tipo():
    config = config_ficticia()
    config["fontes"][0]["colunas"]["dt_evento"]["tipo"] = "texto"
    with pytest.raises(ValueError, match="prefixo dt_"):
        validar_config(config)


def test_coluna_sem_descricao_e_rejeitada():
    config = config_ficticia()
    del config["fontes"][0]["colunas"]["dt_evento"]["descricao"]
    with pytest.raises(ValueError, match="descricao"):
        validar_config(config)


# Chave e regras -----------------------------------------------------------------------


def test_chave_sem_regra_ganha_nao_nulo_com_drop_sozinha():
    config = config_ficticia()
    fonte = config["fontes"][0]
    fonte["regras"] = [r for r in fonte["regras"] if r["nome"] != "pessoa_preenchida"]
    validar_config(config)
    geradas = [r for r in regras_efetivas(fonte) if r not in fonte["regras"]]
    esperada = {"nome": "chave_nm_pessoa_preenchida", "tipo": "nao_nulo", "coluna": "nm_pessoa", "acao": "drop"}
    assert geradas == [esperada]
    descartar, _, _ = expectations(fonte)
    assert descartar["chave_nm_pessoa_preenchida"] == "`nm_pessoa` IS NOT NULL"


def test_chave_ja_conferida_no_yaml_nao_ganha_regra_repetida():
    assert regras_efetivas(EVENTOS) == EVENTOS["regras"]


def test_chave_do_auto_cdc_nao_aceita_nao_nulo_so_com_alerta():
    config = config_ficticia()
    regra = next(r for r in config["fontes"][0]["regras"] if r["nome"] == "pessoa_preenchida")
    regra["acao"] = "alerta"
    with pytest.raises(ValueError, match="regra nao_nulo da chave precisa de drop ou falhar: nm_pessoa"):
        validar_config(config)


def test_incremental_ganha_regra_de_chave_unica():
    fonte_incremental = {"nome": "vendas", "modo_carga": "incremental", "chave_primaria": ["id_venda"], "regras": []}
    regras = regras_efetivas(fonte_incremental)
    assert {"nome": "chave_unica", "tipo": "unico", "colunas": ["id_venda"], "acao": "alerta"} in regras
    assert tabelas_da_fonte(fonte_incremental)["unicidade"] == ["silver_int_vendas_unico_id_venda"]
    # Nos modos snapshot e cdc a chave já sai única: nenhuma checagem a mais.
    for modo in ("snapshot", "cdc"):
        assert not any(r["tipo"] == "unico" for r in regras_efetivas({**fonte_incremental, "modo_carga": modo}))


def test_regra_falhar_vira_expectation_que_para_a_carga():
    f = {"nome": "x", "modo_carga": "snapshot", "chave_primaria": ["id_x"], "regras": [
        {"nome": "id_x_preenchido", "tipo": "nao_nulo", "coluna": "id_x", "acao": "drop"},
        {"nome": "arquivo_certo", "tipo": "expressao", "expressao": "qt_linhas > 0", "acao": "falhar"},
    ]}
    descartar, alertar, falhar = expectations(f)
    assert falhar == {"arquivo_certo": "qt_linhas > 0"}
    assert "arquivo_certo" not in descartar and "arquivo_certo" not in alertar
    # A regra falhar precisa ser expect_all_or_fail: como drop ou alerta, um arquivo errado
    # viraria painel errado em vez de parar a carga.
    assert "funcao = dp.expect_all_or_fail(falhar)(funcao)" in silver_py()


def test_expressoes_das_regras():
    assert expressao_regra({"tipo": "nao_nulo", "coluna": "nome"}) == "`nome` IS NOT NULL"
    aceitos = expressao_regra({"tipo": "valores_aceitos", "coluna": "x", "valores": ["d'água", 1]})
    assert aceitos == "`x` IN ('d\\'água', 1)"
    assert expressao_regra({"tipo": "unico", "colunas": ["x"]}) is None


def test_regra_unico_vira_checagem():
    assert tabelas_da_fonte(CADASTRO)["unicidade"] == ["silver_int_cadastro_unico_ds_prefixo"]


# Data de referência do snapshot ---------------------------------------------------


def config_com_data_referencia(referencia: dict, **campos) -> dict:
    config = config_ficticia()
    config["fontes"][0]["data_referencia"] = referencia
    config["fontes"][0].update(campos)
    return config


@pytest.mark.parametrize(
    "referencia",
    [
        {"tipo": "ingestao"},
        {"tipo": "conteudo", "expressao": "max(dt_evento)"},
        {"tipo": "nome_arquivo", "regex": "_([0-9]{8})[.]csv$", "formato": "yyyyMMdd"},
        {"tipo": "nome_arquivo", "regex": "(?:eventos)_([0-9]{8})", "formato": "yyyyMMdd"},
    ],
    ids=["ingestao", "conteudo", "nome_arquivo", "grupo_sem_captura"],
)
def test_data_referencia_aceita_os_tres_tipos(referencia):
    validar_config(config_com_data_referencia(referencia))


@pytest.mark.parametrize(
    ("referencia", "trecho"),
    [
        ({"tipo": "versao"}, "data_referencia"),
        ({"tipo": "conteudo"}, "data_referencia"),
        ({"tipo": "conteudo", "expressao": ""}, "data_referencia"),
        ({"tipo": "conteudo", "expressao": "max(dt_evento)", "regex": "(x)"}, "data_referencia"),
        ({"tipo": "nome_arquivo", "regex": "([0-9]{8})"}, "data_referencia"),
        ({"tipo": "nome_arquivo", "formato": "yyyyMMdd"}, "data_referencia"),
        ({"tipo": "ingestao", "expressao": "max(dt_evento)"}, "data_referencia"),
        ({"tipo": "nome_arquivo", "regex": "[0-9]{8}", "formato": "yyyyMMdd"}, "exatamente um grupo"),
        ({"tipo": "nome_arquivo", "regex": "([0-9]{4})([0-9]{4})", "formato": "yyyyMMdd"}, "exatamente um grupo"),
        ({"tipo": "nome_arquivo", "regex": "([0-9]{8}", "formato": "yyyyMMdd"}, "regex de data_referencia inválida"),
    ],
    ids=["tipo_invalido", "conteudo_sem_expressao", "expressao_vazia", "conteudo_com_regex", "sem_formato",
         "sem_regex", "ingestao_com_expressao", "regex_sem_grupo", "regex_com_dois_grupos", "regex_quebrada"],
)
def test_data_referencia_invalida_e_rejeitada(referencia, trecho):
    with pytest.raises(ValueError, match=trecho):
        validar_config(config_com_data_referencia(referencia))


def test_data_referencia_so_vale_em_snapshot_de_arquivo():
    conteudo = {"tipo": "conteudo", "expressao": "max(dt_evento)"}
    with pytest.raises(ValueError, match="só vale no modo snapshot"):
        validar_config(config_com_data_referencia(conteudo, modo_carga="cdc", cdc={
            "coluna_operacao": "op", "valor_exclusao": "D"}))
    # Fonte tabela não tem arquivo para escolher: data_referencia não faz sentido.
    config = config_ficticia()
    config["fontes"].append(cadastro(data_referencia={"tipo": "conteudo", "expressao": "max(dh_atualizacao)"}))
    with pytest.raises(ValueError, match="só vale no modo snapshot"):
        validar_config(config)


def test_expressao_da_data_referencia_de_cada_tipo():
    assert expressao_data_referencia({"nome": "x"}) is None
    assert expressao_data_referencia({"data_referencia": {"tipo": "ingestao"}}) is None
    assert expressao_data_referencia(
        {"data_referencia": {"tipo": "conteudo", "expressao": "max(dt_x)"}}
    ) == "max(dt_x)"
    nome_arquivo = expressao_data_referencia(
        {"data_referencia": {"tipo": "nome_arquivo", "regex": "_(\\d{8})[.]csv$", "formato": "yyyyMMdd"}}
    )
    # Só o nome do arquivo (sem a pasta), grupo 1 da regex, com a barra escapada para o SQL.
    assert nome_arquivo == (
        "max(CAST(try_to_timestamp(nullif(regexp_extract(element_at(split(_arquivo_origem, '/'), -1), "
        "'_(\\\\d{8})[.]csv$', 1), ''), 'yyyyMMdd') AS DATE))"
    )


def test_silver_ordena_pela_data_de_referencia_e_desempata_sem_depender_da_ordem_de_chegada():
    # Dois arquivos no mesmo micro-batch têm o mesmo _ingerido_em: sem _modificado_em e o nome
    # do arquivo no desempate, o retrato poderia trocar de arquivo a cada atualização.
    # O nome do arquivo é único: fecha o desempate. Sem ele, empate total ficaria ao acaso.
    assert ORDEM_DO_RETRATO[-1] == "_arquivo_origem" and {"_ingerido_em", "_modificado_em"} <= set(ORDEM_DO_RETRATO)
    # Risco: com a ingestão primeiro, arquivos enviados juntos e lidos em micro-batches
    # diferentes escolheriam o retrato errado (não determinístico).
    assert ORDEM_DO_RETRATO.index("_modificado_em") < ORDEM_DO_RETRATO.index("_ingerido_em")
    assert len(set(ORDEM_DO_RETRATO)) == len(ORDEM_DO_RETRATO)
    codigo = silver_py()
    funcao = codigo[codigo.index("def manter_ultimo_arquivo") : codigo.index("def manter_versao_mais_recente")]
    # A escolha usa a lista compartilhada (a mesma que o agrupamento), e a data de referência vem antes.
    assert "ORDEM_DO_RETRATO" in funcao
    assert funcao.index("_data_referencia") < funcao.index("orderBy(")
    # A data de referência usa os nomes padronizados: a limpeza vem antes da escolha do arquivo.
    assert "manter_ultimo_arquivo(limpar(spark.read.table(origem), fonte), fonte)" in codigo


# Full refresh --------------------------------------------------------------------------


def test_bronze_da_landing_e_historico_nao_sao_esvaziados_por_full_refresh():
    bloqueado = {"pipelines.reset.allowed": "false"}
    for tipo in ("arquivo", "banco", "api"):
        assert bloqueado.items() <= propriedades_tabela("bronze", "bruta", {"nome": "x", "tipo": tipo}).items()
    assert bloqueado.items() <= propriedades_tabela("silver", "historico", {"nome": "x", "tipo": "arquivo"}).items()
    for camada, tipo, tipo_fonte in (("bronze", "bruta", "tabela"), ("silver", "atual", "arquivo"),
                                      ("silver", "intermediaria", "arquivo")):
        assert "pipelines.reset.allowed" not in propriedades_tabela(camada, tipo, {"nome": "x", "tipo": tipo_fonte})


# Bronze e silver genéricas ------------------------------------------------------------


@pytest.mark.parametrize("arquivo", sorted(PASTA_PIPELINE.glob("*.py")), ids=lambda a: a.name)
def test_pipeline_nao_usa_o_modulo_dlt_antigo(arquivo):
    # Regra 5 do CLAUDE.md: o módulo dlt é o legado; o pipeline usa pyspark.pipelines.
    assert not re.search(r"^\s*(import dlt|from dlt\b)", arquivo.read_text(encoding="utf-8"), re.MULTILINE)


def test_historico_faz_da_silver_uma_scd2_sem_tabela_separada():
    # Uma tabela só por fonte na silver: com historico, ela é a SCD tipo 2 e não aceita reset.
    assert "historico" not in tabelas_da_fonte(EVENTOS)
    assert tipo_da_silver(EVENTOS) == "historico"
    assert propriedades_tabela("silver", tipo_da_silver(EVENTOS), EVENTOS)["pipelines.reset.allowed"] == "false"
    assert tipo_da_silver(CADASTRO) == "atual"


def test_retrato_do_snapshot_e_privado_e_o_cdc_e_publicado():
    # O retrato não aparece no catálogo; as mudanças do cdc, sim (alvo de streaming do AUTO CDC).
    assert not validada_publicada(EVENTOS)
    assert validada_publicada({"modo_carga": "cdc"})
    assert not validada_publicada({"modo_carga": "incremental"})
    codigo = silver_py()
    trecho = codigo[codigo.index("def retrato_validado") : codigo.index("criar_alvo_auto_cdc(fonte)")]
    assert "private=not validada_publicada(fonte)," in trecho


@pytest.mark.parametrize(
    ("modo", "validada"),
    [("snapshot", "silver_int_x_retrato"), ("cdc", "silver_int_x_mudancas"), ("incremental", None)],
)
def test_auto_cdc_sempre_tem_tabela_intermediaria_com_as_regras(modo, validada):
    # As regras não podem ficar numa view: o AUTO CDC FROM SNAPSHOT não as aplica.
    assert tabelas_da_fonte({"nome": "x", "modo_carga": modo})["validada"] == validada


def test_silver_py_aplica_regras_em_tabela_e_nao_em_view():
    codigo = silver_py()
    assert "dp.temporary_view" not in codigo
    assert 'source=tabelas["validada"]' in codigo


def test_limpeza_padrao_aplica_formatos_de_para_valor_padrao_e_mascara():
    # Risco: um formato de data que some vira data nula (linha descartada pela chave), um de-para
    # que some deixa o status sujo, e uma máscara que some grava o telefone inteiro na silver.
    colunas = EVENTOS["colunas"]
    data = expressao_limpeza("data", colunas["dt_evento"])
    assert "'dd/MM/yyyy'" in data and "'yyyy-MM-dd'" in data and "try_to_timestamp" in data
    estado = expressao_limpeza("estado", colunas["st_evento"])
    assert "WHEN 'feito' THEN 'Feito'" in estado
    assert "coalesce(" in estado and "'Aberto'" in estado
    contato = expressao_limpeza("contato", colunas["nr_contato"])
    assert "concat('(', left(" in contato and "') ****-', right(" in contato
    assert expressao_limpeza("pessoa", {"tipo": "texto", "mascarar": "hash"}).startswith("sha2(")


def test_colunas_declaradas_recebem_o_nome_padronizado():
    expressoes = expressoes_silver(EVENTOS, [("data", "string"), ("estado", "string")])
    assert expressoes[0].endswith("AS `dt_evento`")
    assert expressoes[1].endswith("AS `st_evento`")


def test_silver_so_recebe_colunas_do_contrato():
    tipos = [
        ("estado", "string"),
        ("coluna_nao_declarada", "string"),
        ("quantidade", "bigint"),
        ("_arquivo_origem", "string"),
        ("_rescued_data", "string"),
    ]
    expressoes = expressoes_silver(EVENTOS, tipos)
    assert len(expressoes) == 2
    assert expressoes[0].endswith("AS `st_evento`")
    assert expressoes[1] == "`_arquivo_origem`"


# Dicionário de dados ----------------------------------------------------------------


def test_schema_do_historico_inclui_a_vigencia():
    schema = schema_silver(EVENTOS, "TIMESTAMP")
    for coluna in ("__START_AT", "__END_AT"):
        assert f"`{coluna}` TIMESTAMP COMMENT '" in schema


def test_tipos_do_schema_seguem_o_yaml():
    schema = schema_silver(CADASTRO)
    trechos = (
        "`id_item` BIGINT",
        "`ds_prefixo` STRING",
        "`dh_atualizacao` TIMESTAMP",
        "`_ingerido_em` TIMESTAMP",
    )
    for trecho in trechos:
        assert trecho in schema
    # Fonte tabela não tem arquivo: nem caminho nem data de modificação.
    assert "_arquivo_origem" not in schema and "_modificado_em" not in schema
    assert "`_modificado_em` TIMESTAMP" in schema_silver(eventos())
