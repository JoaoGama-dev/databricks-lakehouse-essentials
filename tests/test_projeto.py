"""Testes do projeto. Rodam sem Databricks: leem os arquivos e testam a lógica que
vem do config/fontes.yml (src/essentials/config_fontes.py)."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from essentials.config_fontes import (
    PREFIXOS_POR_TIPO,
    carregar_fontes,
    colunas_silver,
    expectations,
    expressao_data_referencia,
    expressao_limpeza,
    expressao_regra,
    expressoes_silver,
    nome_tabela_origem,
    pasta_landing,
    propriedades_tabela,
    regras_efetivas,
    schema_silver,
    tabelas_da_fonte,
    validar_config,
)

RAIZ = Path(__file__).resolve().parents[1]
CONFIG = RAIZ / "config" / "fontes.yml"
PASTA_PIPELINE = RAIZ / "src" / "pipeline"
SETUP = RAIZ / "setup" / "00_setup_free_edition.sql"
PADRAO_TABELA_SQL = re.compile(
    r"CREATE OR REFRESH (?:STREAMING TABLE|MATERIALIZED VIEW)\s+(?:\$\{\w+\}\.)?(\w+)", re.IGNORECASE
)

FONTES = carregar_fontes(CONFIG)


def carregar_yaml(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def config_bruta() -> dict:
    return carregar_yaml(CONFIG)


def fonte(nome: str) -> dict:
    return next(f for f in FONTES if f["nome"] == nome)


def arquivos_gold() -> list[Path]:
    return sorted(PASTA_PIPELINE.glob("gold_*.sql"))


def pipeline() -> dict:
    return carregar_yaml(RAIZ / "resources" / "pipeline.yml")["resources"]["pipelines"]["essentials_pipeline"]


# config/fontes.yml ----------------------------------------------------------------


def test_config_valida_contra_o_schema():
    validar_config(config_bruta())
    assert FONTES


def test_config_sem_campo_obrigatorio_e_rejeitada():
    config = config_bruta()
    del config["fontes"][0]["chave_primaria"]
    with pytest.raises(ValueError, match="chave_primaria"):
        validar_config(config)


def test_tipo_sem_seu_bloco_e_rejeitado():
    config = config_bruta()
    del config["fontes"][0]["arquivo"]
    with pytest.raises(ValueError):
        validar_config(config)


def test_regra_unico_so_aceita_alerta():
    config = config_bruta()
    regra = next(r for f in config["fontes"] for r in f.get("regras", []) if r["tipo"] == "unico")
    regra["acao"] = "drop"
    with pytest.raises(ValueError):
        validar_config(config)


def test_historico_nao_vale_no_modo_incremental():
    config = config_bruta()
    config["fontes"][0]["modo_carga"] = "incremental"
    config["fontes"][0]["historico"] = True
    with pytest.raises(ValueError):
        validar_config(config)


def test_nomes_de_fonte_repetidos_sao_rejeitados():
    config = config_bruta()
    config["fontes"].append(copy.deepcopy(config["fontes"][0]))
    with pytest.raises(ValueError, match="repetidos"):
        validar_config(config)


def test_banco_incremental_exige_watermark():
    config = config_bruta()
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
    config = config_bruta()
    config["fontes"][0]["regras"][0]["coluna"] = "nm_que_nao_existe"
    with pytest.raises(ValueError, match="nm_que_nao_existe"):
        validar_config(config)


def test_coluna_sem_prefixo_conhecido_e_rejeitada():
    config = config_bruta()
    colunas = config["fontes"][0]["colunas"]
    colunas["horario"] = colunas.pop("hr_entrevista")
    with pytest.raises(ValueError, match="horario"):
        validar_config(config)


def test_prefixo_precisa_combinar_com_o_tipo():
    config = config_bruta()
    config["fontes"][0]["colunas"]["dt_entrevista"]["tipo"] = "texto"
    with pytest.raises(ValueError, match="prefixo dt_"):
        validar_config(config)


def test_chave_sem_regra_ganha_nao_nulo_com_drop_sozinha():
    config = config_bruta()
    agenda = config["fontes"][0]
    agenda["regras"] = [r for r in agenda["regras"] if r["nome"] != "nome_preenchido"]
    validar_config(config)
    geradas = [r for r in regras_efetivas(agenda) if r not in agenda["regras"]]
    esperada = {"nome": "chave_nm_candidato_preenchida", "tipo": "nao_nulo", "coluna": "nm_candidato", "acao": "drop"}
    assert geradas == [esperada]
    descartar, _, _ = expectations(agenda)
    assert descartar["chave_nm_candidato_preenchida"] == "`nm_candidato` IS NOT NULL"


def test_chave_ja_conferida_no_yaml_nao_ganha_regra_repetida():
    for f in FONTES:
        assert regras_efetivas(f) == f.get("regras", []), f["nome"]


def test_chave_do_auto_cdc_nao_aceita_nao_nulo_so_com_alerta():
    config = config_bruta()
    regra = next(r for r in config["fontes"][0]["regras"] if r["nome"] == "nome_preenchido")
    regra["acao"] = "alerta"
    with pytest.raises(ValueError, match="regra nao_nulo da chave precisa de drop ou falhar: nm_candidato"):
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
    codigo = (PASTA_PIPELINE / "silver.py").read_text(encoding="utf-8")
    assert "dp.expect_all_or_fail(falhar)" in codigo


# Data de referência do snapshot ---------------------------------------------------


def config_com_data_referencia(referencia: dict, **campos) -> dict:
    config = config_bruta()
    agenda = next(f for f in config["fontes"] if f["nome"] == "agenda")
    agenda["data_referencia"] = referencia
    agenda.update(campos)
    return config


@pytest.mark.parametrize(
    "referencia",
    [
        {"tipo": "ingestao"},
        {"tipo": "conteudo", "expressao": "max(dt_entrevista)"},
        {"tipo": "nome_arquivo", "regex": "_([0-9]{8})[.]csv$", "formato": "yyyyMMdd"},
        {"tipo": "nome_arquivo", "regex": "(?:agenda)_([0-9]{8})", "formato": "yyyyMMdd"},
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
        ({"tipo": "conteudo", "expressao": "max(dt_entrevista)", "regex": "(x)"}, "data_referencia"),
        ({"tipo": "nome_arquivo", "regex": "([0-9]{8})"}, "data_referencia"),
        ({"tipo": "nome_arquivo", "formato": "yyyyMMdd"}, "data_referencia"),
        ({"tipo": "ingestao", "expressao": "max(dt_entrevista)"}, "data_referencia"),
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
    conteudo = {"tipo": "conteudo", "expressao": "max(dt_entrevista)"}
    with pytest.raises(ValueError, match="só vale no modo snapshot"):
        validar_config(config_com_data_referencia(conteudo, modo_carga="cdc", cdc={
            "coluna_operacao": "op", "valor_exclusao": "D"}))
    config = config_bruta()
    cargos = next(f for f in config["fontes"] if f["nome"] == "cargos")
    cargos["data_referencia"] = {"tipo": "conteudo", "expressao": "max(dh_atualizacao)"}
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


def test_agenda_escolhe_o_retrato_pela_maior_data_de_entrevista():
    assert expressao_data_referencia(fonte("agenda")) == "max(dt_entrevista)"
    assert expressao_data_referencia(fonte("cargos")) is None


def test_silver_ordena_pela_data_de_referencia_e_depois_pela_ingestao():
    codigo = (PASTA_PIPELINE / "silver.py").read_text(encoding="utf-8")
    funcao = codigo[codigo.index("def manter_ultimo_arquivo") : codigo.index("def manter_versao_mais_recente")]
    assert 'ordem = [F.desc("_ingerido_em"), F.desc("_arquivo_origem")]' in funcao
    assert 'ordem.insert(0, F.col("_data_referencia").desc_nulls_last())' in funcao
    assert 'groupBy("_arquivo_origem", "_ingerido_em").agg(F.expr(referencia)' in funcao
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


# Bronze ---------------------------------------------------------------------------


@pytest.mark.parametrize("f", FONTES, ids=lambda f: f["nome"])
def test_cada_fonte_gera_sua_bronze(f):
    assert tabelas_da_fonte(f)["bronze"] == f"bronze_{f['nome']}"
    if f["tipo"] != "tabela":
        assert pasta_landing(f)


@pytest.mark.parametrize("arquivo", sorted(PASTA_PIPELINE.glob("*.py")), ids=lambda a: a.name)
def test_pipeline_nao_usa_o_modulo_dlt_antigo(arquivo):
    # Regra 5 do CLAUDE.md: o módulo dlt é o legado; o pipeline usa pyspark.pipelines.
    assert not re.search(r"^\s*(import dlt|from dlt\b)", arquivo.read_text(encoding="utf-8"), re.MULTILINE)


def test_tabela_de_apoio_e_criada_no_setup():
    setup = SETUP.read_text(encoding="utf-8")
    for f in FONTES:
        if f["tipo"] == "tabela":
            assert nome_tabela_origem(f, "essentials", "portfolio") in setup


# Silver e regras ------------------------------------------------------------------


@pytest.mark.parametrize("f", FONTES, ids=lambda f: f["nome"])
def test_regras_viram_expectations(f):
    descartar, alertar, falhar = expectations(f)
    destinos = {"drop": descartar, "alerta": alertar, "falhar": falhar}
    for regra in regras_efetivas(f):
        if regra["tipo"] == "unico":
            assert all(regra["nome"] not in destino for destino in destinos.values())
            continue
        assert destinos[regra["acao"]][regra["nome"]] == expressao_regra(regra)


def test_expressoes_das_regras():
    assert expressao_regra({"tipo": "nao_nulo", "coluna": "nome"}) == "`nome` IS NOT NULL"
    aceitos = expressao_regra({"tipo": "valores_aceitos", "coluna": "x", "valores": ["d'água", 1]})
    assert aceitos == "`x` IN ('d\\'água', 1)"
    assert expressao_regra({"tipo": "unico", "colunas": ["x"]}) is None


def test_regra_unico_vira_checagem():
    assert tabelas_da_fonte(fonte("cargos"))["unicidade"] == ["silver_int_cargos_unico_ds_prefixo_vaga"]


def test_historico_cria_tabela_scd2():
    assert tabelas_da_fonte(fonte("agenda"))["historico"] == "silver_agenda_historico"
    assert tabelas_da_fonte(fonte("cargos"))["historico"] is None


@pytest.mark.parametrize(
    ("modo", "validada"),
    [("snapshot", "silver_int_x_retrato"), ("cdc", "silver_int_x_mudancas"), ("incremental", None)],
)
def test_auto_cdc_sempre_tem_tabela_intermediaria_com_as_regras(modo, validada):
    # As regras não podem ficar numa view: o AUTO CDC FROM SNAPSHOT não as aplica.
    assert tabelas_da_fonte({"nome": "x", "modo_carga": modo})["validada"] == validada


def test_silver_py_aplica_regras_em_tabela_e_nao_em_view():
    codigo = (PASTA_PIPELINE / "silver.py").read_text(encoding="utf-8")
    assert "dp.temporary_view" not in codigo
    assert 'source=tabelas["validada"]' in codigo


@pytest.mark.parametrize("f", FONTES, ids=lambda f: f["nome"])
def test_tabelas_seguem_camada_tipo_nome(f):
    tabelas = tabelas_da_fonte(f)
    nomes = [tabelas["bronze"], tabelas["silver"], tabelas["preparada"], tabelas["validada"], tabelas["historico"]]
    nomes += tabelas["unicidade"]
    padrao = re.compile(rf"^(bronze_{f['nome']}|silver_{f['nome']}(_historico)?|silver_int_{f['nome']}_\w+)$")
    assert all(padrao.match(nome) for nome in nomes if nome)


def colunas_da_fonte(nome_fonte: str) -> dict:
    return fonte(nome_fonte)["colunas"]


def test_data_aceita_os_dois_formatos():
    expressao = expressao_limpeza("data_entrevista", colunas_da_fonte("agenda")["dt_entrevista"])
    assert "'dd/MM/yyyy'" in expressao and "'yyyy-MM-dd'" in expressao
    assert "try_to_timestamp" in expressao


def test_status_tem_de_para_e_valor_padrao():
    expressao = expressao_limpeza("status", colunas_da_fonte("agenda")["st_entrevista"])
    assert "WHEN 'n/ atendeu' THEN 'Não atendeu'" in expressao
    assert "coalesce(" in expressao and "'Pendente'" in expressao


def test_telefone_e_mascarado():
    expressao = expressao_limpeza("telefone", colunas_da_fonte("agenda")["nr_telefone"])
    assert "****-" in expressao


def test_colunas_declaradas_recebem_o_nome_padronizado():
    expressoes = expressoes_silver(fonte("agenda"), [("data_entrevista", "string"), ("status", "string")])
    assert expressoes[0].endswith("AS `dt_entrevista`")
    assert expressoes[1].endswith("AS `st_entrevista`")


def test_silver_so_recebe_colunas_do_contrato():
    tipos = [
        ("status", "string"),
        ("coluna_nao_declarada", "string"),
        ("quantidade", "bigint"),
        ("_arquivo_origem", "string"),
        ("_rescued_data", "string"),
    ]
    expressoes = expressoes_silver(fonte("agenda"), tipos)
    assert len(expressoes) == 2
    assert expressoes[0].endswith("AS `st_entrevista`")
    assert expressoes[1] == "`_arquivo_origem`"


# Dicionário de dados ----------------------------------------------------------------


def test_coluna_sem_descricao_e_rejeitada():
    config = config_bruta()
    del config["fontes"][0]["colunas"]["dt_entrevista"]["descricao"]
    with pytest.raises(ValueError, match="descricao"):
        validar_config(config)


@pytest.mark.parametrize("f", FONTES, ids=lambda f: f["nome"])
def test_schema_da_silver_descreve_todas_as_colunas_na_ordem(f):
    schema = schema_silver(f)
    colunas = re.findall(r"`(\w+)` [A-Z(),0-9]+ COMMENT '", schema)
    assert colunas == colunas_silver(f)
    assert colunas[: len(f["colunas"])] == list(f["colunas"])
    assert schema.count(" COMMENT ") == len(colunas)


def test_schema_do_historico_inclui_a_vigencia():
    schema = schema_silver(fonte("agenda"), "TIMESTAMP")
    for coluna in ("__START_AT", "__END_AT"):
        assert f"`{coluna}` TIMESTAMP COMMENT '" in schema


def test_tipos_do_schema_seguem_o_yaml():
    schema = schema_silver(fonte("cargos"))
    trechos = (
        "`id_cargo` BIGINT",
        "`ds_prefixo_vaga` STRING",
        "`dh_atualizacao` TIMESTAMP",
        "`_ingerido_em` TIMESTAMP",
    )
    for trecho in trechos:
        assert trecho in schema
    assert "_arquivo_origem" not in schema  # fonte tabela não tem arquivo


@pytest.mark.parametrize("arquivo", arquivos_gold(), ids=lambda a: a.name)
def test_colunas_da_gold_tem_tipo_e_descricao(arquivo):
    sql = arquivo.read_text(encoding="utf-8")
    blocos = re.findall(r"MATERIALIZED VIEW (?:\$\{\w+\}\.)?\w+ \((.*?)\n\)\nCOMMENT", sql, re.DOTALL)
    assert len(blocos) == len(PADRAO_TABELA_SQL.findall(sql)), "toda view da gold declara as colunas"
    prefixos = "|".join(PREFIXOS_POR_TIPO)
    for bloco in blocos:
        for linha in [linha.strip() for linha in bloco.strip().splitlines()]:
            assert re.fullmatch(rf"({prefixos})_\w+ [A-Z]+ COMMENT '[^']{{10,}}'( MASK [\w${{}}.]+)?,?", linha), linha


def test_preparacao_sql_existe_quando_pedida():
    for f in FONTES:
        if f.get("preparacao_sql"):
            sql = (PASTA_PIPELINE / f"silver_{f['nome']}.sql").read_text(encoding="utf-8")
            assert f"CREATE TEMPORARY VIEW silver_int_{f['nome']}_preparada" in sql
            # A view mantém os nomes da origem; os nomes padronizados vêm do YAML.
            for configuracao in f["colunas"].values():
                if not configuracao["origem"].startswith("_"):
                    assert configuracao["origem"] in sql
            assert f"bronze_{f['nome']}" in sql


def test_preparacao_da_agenda_remove_o_bom():
    sql = (PASTA_PIPELINE / "silver_agenda.sql").read_text(encoding="utf-8")
    # Remove os bytes EF BB BF (U+FEFF) do início do texto antes de reconhecer "AGENDA DIA".
    assert "trim(LEADING decode(unhex('EFBBBF'), 'UTF-8') FROM value)" in sql
    assert chr(0xFEFF) not in sql, "o SQL não deve conter um BOM literal, que é invisível"


# Pipeline, job e targets ----------------------------------------------------------


def test_pipeline_lista_todos_os_arquivos():
    listados = {(RAIZ / "resources" / lib["file"]["path"]).resolve() for lib in pipeline()["libraries"]}
    esperados = {
        caminho.resolve()
        for padrao in ("bronze.py", "silver.py", "silver_*.sql", "gold_*.sql")
        for caminho in PASTA_PIPELINE.glob(padrao)
    }
    assert listados == esperados
    assert all(caminho.is_file() for caminho in listados)


def test_pipeline_serverless_com_configuracao():
    configuracao = pipeline()
    assert configuracao["serverless"] is True
    assert configuracao["continuous"] is False
    assert {"catalogo", "projeto", "schema_gold", "landing_path", "fontes_config", "diretorio_codigo"} <= set(
        configuracao["configuration"]
    )


def test_estrutura_do_pacote_essentials():
    """Catálogo do pacote, schemas e landing do projeto no bundle, bundle com o nome do projeto."""
    bundle = carregar_yaml(RAIZ / "databricks.yml")
    variaveis = bundle["variables"]
    projeto = variaveis["projeto"]["default"]
    assert bundle["bundle"]["name"] == f"essentials_{projeto}"
    assert variaveis["catalog"]["default"] == "essentials"
    assert "${var.projeto}" in pipeline()["name"]
    assert pipeline()["schema"] == "${resources.schemas.projeto.name}"
    assert pipeline()["configuration"]["schema_gold"] == "${resources.schemas.gold.name}"
    assert pipeline()["configuration"]["landing_path"].startswith("/Volumes/${resources.volumes.landing.")


def test_setup_cria_so_o_que_nao_pertence_ao_bundle():
    setup = SETUP.read_text(encoding="utf-8")
    projeto = carregar_yaml(RAIZ / "databricks.yml")["variables"]["projeto"]["default"]
    assert "CREATE CATALOG IF NOT EXISTS essentials\n" in setup
    assert f"CREATE SCHEMA IF NOT EXISTS essentials.{projeto}_origem\n" in setup
    assert f"CREATE SCHEMA IF NOT EXISTS essentials.{projeto}\n" not in setup
    assert "CREATE VOLUME" not in setup


def test_nome_da_tabela_de_origem_usa_catalogo_e_projeto():
    fonte_tabela = {"tabela": {"nome_completo": "{catalogo}.{projeto}_origem.cadastro"}}
    assert nome_tabela_origem(fonte_tabela, "prd", "clinica") == "prd.clinica_origem.cadastro"


def test_job_roda_ingestao_antes_do_pipeline():
    job = carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]["essentials_carga_diaria"]
    tarefas = {tarefa["task_key"]: tarefa for tarefa in job["tasks"]}
    assert job["schedule"]["timezone_id"] == "America/Sao_Paulo"
    pipeline_id = tarefas["atualizar_lakehouse"]["pipeline_task"]["pipeline_id"]
    assert pipeline_id == "${resources.pipelines.essentials_pipeline.id}"
    dependencias = {d["task_key"] for d in tarefas["atualizar_lakehouse"]["depends_on"]}
    assert dependencias == {"ingestao_api", "ingestao_banco", "governanca_antes"}
    for chave in ("ingestao_api", "ingestao_banco"):
        assert (RAIZ / "resources" / tarefas[chave]["spark_python_task"]["python_file"]).is_file()


def test_targets_dev_e_prod():
    targets = carregar_yaml(RAIZ / "databricks.yml")["targets"]
    assert targets["dev"]["mode"] == "development"
    assert targets["dev"]["default"] is True
    assert targets["prod"]["mode"] == "production"


def test_prod_tem_run_as():
    prod = carregar_yaml(RAIZ / "databricks.yml")["targets"]["prod"]
    assert prod["run_as"]["service_principal_name"]
    assert prod["variables"]["catalog"] == "prd"


# Gold -----------------------------------------------------------------------------


TIPOS_GOLD = {"dim": "dimensao", "fato": "fato", "agg": "agregada"}


@pytest.mark.parametrize("arquivo", arquivos_gold(), ids=lambda a: a.name)
def test_gold_segue_camada_tipo_nome_com_comment(arquivo):
    sql = arquivo.read_text(encoding="utf-8")
    for bloco in re.split(r"CREATE OR REFRESH", sql, flags=re.IGNORECASE)[1:]:
        tabela = PADRAO_TABELA_SQL.search("CREATE OR REFRESH" + bloco).group(1)
        tipo = re.match(r"gold_(dim|fato|agg)_[a-z0-9_]+$", tabela)
        assert tipo, f"{tabela} não segue gold_<dim|fato|agg>_<nome>"
        assert "COMMENT '" in bloco
        assert f"TBLPROPERTIES ('camada' = 'gold', 'tipo' = '{TIPOS_GOLD[tipo.group(1)]}')" in bloco


@pytest.mark.parametrize("arquivo", arquivos_gold(), ids=lambda a: a.name)
def test_colunas_da_gold_tem_prefixo_da_classe(arquivo):
    sql = arquivo.read_text(encoding="utf-8")
    prefixos = "|".join(PREFIXOS_POR_TIPO)
    # Apelidos de coluna em minúsculas com mais de uma letra (e, c, f, d são apelidos de tabela).
    apelidos = re.findall(r"\bAS ([a-z][a-z0-9_]+)\b", sql)
    assert apelidos
    assert all(re.match(rf"^({prefixos})_", apelido) for apelido in apelidos), apelidos


# Painel AI/BI -----------------------------------------------------------------------

PAINEL = RAIZ / "src" / "dashboards" / "entrevistas.lvdash.json"


def painel() -> dict:
    return json.loads(PAINEL.read_text(encoding="utf-8"))


def widgets_do_painel() -> list[tuple[str, dict]]:
    return [(pagina["name"], item) for pagina in painel()["pages"] for item in pagina["layout"]]


def test_painel_esta_no_bundle_sem_ambiente_fixo():
    recurso = carregar_yaml(RAIZ / "resources" / "dashboard.yml")["resources"]["dashboards"]["painel_entrevistas"]
    assert (RAIZ / "resources" / recurso["file_path"]).resolve() == PAINEL.resolve()
    assert recurso["warehouse_id"] == "${var.warehouse_id}"
    assert recurso["dataset_catalog"] == "${resources.schemas.gold.catalog_name}"
    assert recurso["dataset_schema"] == "${resources.schemas.gold.name}"
    assert recurso["embed_credentials"] is False


def test_datasets_do_painel_so_leem_a_gold_sem_catalogo_fixo():
    for dataset in painel()["datasets"]:
        sql = "".join(dataset["queryLines"])
        tabelas = re.findall(r"\b(?:FROM|JOIN)\s+([\w.]+)", sql, flags=re.IGNORECASE)
        tabelas = [t for t in tabelas if t != "entrevistas"]  # CTE interna
        assert tabelas, dataset["name"]
        assert all(re.fullmatch(r"gold_\w+", t) for t in tabelas), (dataset["name"], tabelas)
        assert "essentials" not in sql and "portfolio" not in sql


def test_widgets_usam_datasets_e_campos_que_existem():
    datasets = {d["name"] for d in painel()["datasets"]}
    for pagina, item in widgets_do_painel():
        widget = item["widget"]
        if "multilineTextboxSpec" in widget:
            continue
        consultas = {c["name"]: c["query"] for c in widget["queries"]}
        assert all(c["datasetName"] in datasets for c in consultas.values()), (pagina, widget["name"])
        campos = {f["name"] for c in consultas.values() for f in c["fields"]}
        codificacoes = widget["spec"]["encodings"]
        usados = []
        for valor in codificacoes.values():
            for item_codificacao in valor if isinstance(valor, list) else [valor]:
                usados.append(item_codificacao["fieldName"])
                if "queryName" in item_codificacao:
                    assert item_codificacao["queryName"] in consultas
        assert set(usados) <= campos, (pagina, widget["name"], set(usados) - campos)


# Gerador de dados fictícios -------------------------------------------------------

PADRAO_SEPARADOR = re.compile(r"^AGENDA DI[Aa] (\d{2}/\d{2}/\d{4});")


def importar_gerador():
    caminho = RAIZ / "data" / "gerar_dados_exemplo.py"
    spec = importlib.util.spec_from_file_location("gerar_dados_exemplo", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def ler_agenda(caminho: Path) -> list[dict]:
    """Espelha em Python a preparação de silver_agenda.sql: leva a data do separador."""
    entrevistas = []
    data_atual = None
    for linha in caminho.read_bytes().decode("utf-8-sig").split("\r\n"):
        separador = PADRAO_SEPARADOR.match(linha)
        if separador:
            data_atual = separador.group(1)
        elif linha.replace(";", "").strip():
            horario, nome, vaga, telefone, status = linha.split(";")[:5]
            entrevistas.append(
                {"data": data_atual, "horario": horario, "nome": nome, "vaga": vaga,
                 "telefone": telefone, "status": status}
            )
    return entrevistas


@pytest.fixture(scope="module")
def agendas(tmp_path_factory) -> list[Path]:
    return importar_gerador().gerar(tmp_path_factory.mktemp("agendas"))


def versao(agendas: list[Path], n: int) -> Path:
    return next(caminho for caminho in agendas if caminho.name == f"agenda_exemplo_v{n}.csv")


# Planilhas no formato da exportação do Excel (UTF-8 com BOM e ao menos uma entrevista);
# a v7 (só cabeçalho) e a v8 (cp1252) fogem dele de propósito.
VERSOES_NO_FORMATO_DA_PLANILHA = (1, 2, 3, 4, 5, 6)


def test_gerador_cria_as_oito_versoes(agendas):
    assert [caminho.name for caminho in agendas] == [f"agenda_exemplo_v{n}.csv" for n in range(1, 9)]


def test_gerador_nao_muda_as_versoes_ja_publicadas(agendas):
    # Os totais de tests/integracao/esperado.py dependem dos bytes da v1 a v4 versionados em data/.
    for n in range(1, 5):
        assert versao(agendas, n).read_bytes() == (RAIZ / "data" / f"agenda_exemplo_v{n}.csv").read_bytes(), n


def test_cenarios_de_falha_saem_da_v2(agendas):
    v2, v3, v4 = (ler_agenda(versao(agendas, n)) for n in (2, 3, 4))
    # v3: só o último mês, uma queda bem maior que o limite de 50% do alerta de volume.
    assert 0 < len(v3) < len(v2) / 2
    # v4: a v2 inteira mais uma entrevista antes de 2020, que viola a regra data_plausivel.
    assert len(v4) == len(v2) + 1
    assert any(e["data"].endswith("/2019") for e in v4)


def maior_data(entrevistas: list[dict]):
    return max(datetime.strptime(e["data"], "%d/%m/%Y").date() for e in entrevistas)


def test_reenvio_tem_os_mesmos_bytes_da_v2(agendas):
    assert versao(agendas, 5).read_bytes() == versao(agendas, 2).read_bytes()


def test_atrasado_tem_o_conteudo_da_v1_e_data_de_referencia_menor_que_a_da_v2(agendas):
    assert versao(agendas, 6).read_bytes() == versao(agendas, 1).read_bytes()
    # data_referencia da agenda: max(dt_entrevista). A v1 atrasada não pode vencer a v2.
    assert maior_data(ler_agenda(versao(agendas, 6))) < maior_data(ler_agenda(versao(agendas, 2)))


def test_v3_e_v4_tem_a_mesma_data_de_referencia_da_v2(agendas):
    # Empatam com a v2 e viram o retrato por serem as mais recentes, como antes da data_referencia.
    datas = {n: maior_data(ler_agenda(versao(agendas, n))) for n in (2, 3, 4)}
    assert datas[3] == datas[4] == datas[2]


def test_so_cabecalho_nao_tem_entrevista(agendas):
    conteudo = versao(agendas, 7).read_bytes()
    assert conteudo.startswith(b"\xef\xbb\xbf") and conteudo.endswith(b"\r\n")
    linhas = conteudo.decode("utf-8-sig").split("\r\n")
    assert linhas == [versao(agendas, 2).read_bytes().decode("utf-8-sig").split("\r\n")[0], ""]
    assert re.fullmatch(r"AGENDA DIA \d{2}/\d{2}/\d{4};NOME;VAGA;TELEFONE;STATUS\.;", linhas[0])
    assert ler_agenda(versao(agendas, 7)) == []


def test_cp1252_e_a_v2_em_outra_codificacao(agendas):
    conteudo = versao(agendas, 8).read_bytes()
    texto_v2 = versao(agendas, 2).read_bytes().decode("utf-8-sig")
    assert not conteudo.startswith(b"\xef\xbb\xbf"), "cp1252 não tem BOM"
    assert conteudo.decode("cp1252") == texto_v2
    # Lido como UTF-8 (o que o formato texto faz), o arquivo é inválido e os acentos viram U+FFFD.
    with pytest.raises(UnicodeDecodeError):
        conteudo.decode("utf-8")
    substituido = conteudo.decode("utf-8", errors="replace")
    assert "\N{REPLACEMENT CHARACTER}" in substituido and "\N{REPLACEMENT CHARACTER}" not in texto_v2


def test_agenda_tem_formato_da_planilha_real(agendas):
    for caminho in (versao(agendas, n) for n in VERSOES_NO_FORMATO_DA_PLANILHA):
        conteudo = caminho.read_bytes()
        assert conteudo.startswith(b"\xef\xbb\xbf"), "falta o BOM do UTF-8"
        assert conteudo.count(b"\n") == conteudo.count(b"\r\n"), "toda quebra de linha deve ser CRLF"
        linhas = conteudo.decode("utf-8-sig").split("\r\n")
        assert re.fullmatch(r"AGENDA DIA \d{2}/\d{2}/\d{4};NOME;VAGA;TELEFONE;STATUS\.;", linhas[0])
        assert sum(1 for linha in linhas if re.fullmatch(r"AGENDA DI[Aa] \d{2}/\d{2}/\d{4};;;;;", linha)) > 1
        assert linhas[-4:-1] == [";;;;;"] * 3, "faltam as linhas vazias do fim"
        entrevistas = [linha for linha in linhas[1:] if linha and not PADRAO_SEPARADOR.match(linha)]
        assert all(linha.endswith(";") for linha in entrevistas)


def test_agenda_tem_a_sujeira_da_planilha_real(agendas):
    entrevistas = ler_agenda(agendas[0])
    status = {e["status"] for e in entrevistas}
    assert {"Aprovado", "Aprovada", "N/ atendeu", ""} <= status
    assert any(e["nome"].endswith(".") for e in entrevistas)
    assert any(e["nome"] != e["nome"].strip() or "  " in e["nome"] for e in entrevistas)
    assert any(e["nome"] == "" for e in entrevistas)
    assert any(e["horario"] == "" for e in entrevistas)
    assert any(e["telefone"] in ("", "4,19E+10") for e in entrevistas)
    chaves = [(e["data"], e["nome"]) for e in entrevistas if e["nome"]]
    assert len(chaves) > len(set(chaves)), "falta uma entrevista reagendada no mesmo dia"


def test_v2_preenche_os_status_vazios(agendas):
    v1, v2 = (ler_agenda(caminho) for caminho in agendas[:2])
    status_v2 = {(e["data"], e["horario"], e["nome"]): e["status"] for e in v2}
    vazios = [e for e in v1 if e["status"] == "" and e["nome"]]
    assert vazios
    assert all(status_v2[(e["data"], e["horario"], e["nome"])] for e in vazios)
    assert len(v2) > len(v1)


def test_telefones_do_gerador_sao_ficticios(agendas):
    for e in ler_agenda(agendas[1]):
        digitos = re.sub(r"\D", "", e["telefone"])
        assert len(digitos) < 10 or "90000" in digitos
