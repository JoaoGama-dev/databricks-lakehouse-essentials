"""Testes do projeto. Rodam sem Databricks: leem os arquivos e testam a lógica que
vem do config/fontes.yml (src/essentials/config_fontes.py)."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

from essentials.config_fontes import (
    PREFIXOS_POR_TIPO,
    carregar_fontes,
    expectations,
    expressao_limpeza,
    expressao_regra,
    expressoes_silver,
    nome_tabela_origem,
    pasta_landing,
    tabelas_da_fonte,
    validar_config,
)

RAIZ = Path(__file__).resolve().parents[1]
CONFIG = RAIZ / "config" / "fontes.yml"
PASTA_PIPELINE = RAIZ / "src" / "pipeline"
SETUP = RAIZ / "setup" / "00_setup_free_edition.sql"
PADRAO_TABELA_SQL = re.compile(r"CREATE OR REFRESH (?:STREAMING TABLE|MATERIALIZED VIEW)\s+(\w+)", re.IGNORECASE)

FONTES = carregar_fontes(CONFIG)


def carregar_yaml(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def config_bruta() -> dict:
    return carregar_yaml(CONFIG)


def fonte(nome: str) -> dict:
    return next(f for f in FONTES if f["nome"] == nome)


def pipeline() -> dict:
    return carregar_yaml(RAIZ / "resources" / "pipeline.yml")["resources"]["pipelines"]["essentials_pipeline"]


# config/fontes.yml ----------------------------------------------------------------


def test_config_valida_contra_o_schema():
    validar_config(config_bruta())
    assert FONTES


def test_exemplo_tem_arquivo_e_tabela():
    assert {f["tipo"] for f in FONTES} >= {"arquivo", "tabela"}


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
            "coluna_atualizacao": "atualizado_em",
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


def test_chave_do_auto_cdc_precisa_de_regra_nao_nulo_com_drop():
    config = config_bruta()
    agenda = config["fontes"][0]
    agenda["regras"] = [r for r in agenda["regras"] if r["nome"] != "nome_preenchido"]
    with pytest.raises(ValueError, match="chave sem regra nao_nulo com drop: nm_candidato"):
        validar_config(config)


# Bronze ---------------------------------------------------------------------------


@pytest.mark.parametrize("f", FONTES, ids=lambda f: f["nome"])
def test_cada_fonte_gera_sua_bronze(f):
    assert tabelas_da_fonte(f)["bronze"] == f"bronze_{f['nome']}"
    if f["tipo"] != "tabela":
        assert pasta_landing(f)


def test_bronze_py_cria_uma_tabela_por_fonte():
    codigo = (PASTA_PIPELINE / "bronze.py").read_text(encoding="utf-8")
    assert "from pyspark import pipelines as dp" in codigo
    assert "import dlt" not in codigo
    assert "for fonte in FONTES:\n    criar_bronze(fonte)" in codigo


def test_tabela_de_apoio_e_criada_no_setup():
    setup = SETUP.read_text(encoding="utf-8")
    for f in FONTES:
        if f["tipo"] == "tabela":
            assert nome_tabela_origem(f, "essentials", "portfolio") in setup


# Silver e regras ------------------------------------------------------------------


@pytest.mark.parametrize("f", FONTES, ids=lambda f: f["nome"])
def test_regras_viram_expectations(f):
    descartar, alertar = expectations(f)
    for regra in f.get("regras", []):
        if regra["tipo"] == "unico":
            assert regra["nome"] not in descartar and regra["nome"] not in alertar
            continue
        destino = descartar if regra["acao"] == "drop" else alertar
        assert destino[regra["nome"]] == expressao_regra(regra)


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


def test_limpeza_padrao_nas_colunas_nao_declaradas():
    tipos = [
        ("observacao", "string"),
        ("quantidade", "bigint"),
        ("_arquivo_origem", "string"),
        ("_rescued_data", "string"),
    ]
    expressoes = expressoes_silver({"colunas": {}}, tipos)
    assert expressoes[0].startswith("nullif(trim(") and expressoes[0].endswith("AS `observacao`")
    assert expressoes[1:] == ["`quantidade`", "`_arquivo_origem`"]


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
    assert {"catalogo", "projeto", "landing_path", "fontes_config", "diretorio_codigo"} <= set(
        configuracao["configuration"]
    )


def test_estrutura_do_pacote_essentials():
    """Catálogo do pacote, schema e landing por projeto, bundle com o nome do projeto."""
    bundle = carregar_yaml(RAIZ / "databricks.yml")
    variaveis = bundle["variables"]
    projeto = variaveis["projeto"]["default"]
    assert bundle["bundle"]["name"] == f"essentials_{projeto}"
    assert variaveis["catalog"]["default"] == "essentials"
    assert variaveis["schema"]["default"] == "${var.projeto}"
    assert variaveis["landing_path"]["default"] == "/Volumes/${var.catalog}/${var.projeto}/landing"
    assert "${var.projeto}" in pipeline()["name"]
    setup = SETUP.read_text(encoding="utf-8")
    for comando in (
        "CREATE CATALOG IF NOT EXISTS essentials\n",
        f"CREATE SCHEMA IF NOT EXISTS essentials.{projeto}\n",
        f"CREATE VOLUME IF NOT EXISTS essentials.{projeto}.landing\n",
        f"CREATE SCHEMA IF NOT EXISTS essentials.{projeto}_origem\n",
    ):
        assert comando in setup


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
    assert dependencias == {"ingestao_api", "ingestao_banco"}
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


def arquivos_gold() -> list[Path]:
    return sorted(PASTA_PIPELINE.glob("gold_*.sql"))


def test_existe_gold():
    assert arquivos_gold()


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


def test_gold_classifica_a_situacao_da_entrevista():
    sql = (PASTA_PIPELINE / "gold_entrevistas.sql").read_text(encoding="utf-8")
    for situacao in ("'Concluído'", "'Em andamento'", "'Pendente'", "'Não identificado'"):
        assert situacao in sql
    assert "AS st_situacao" in sql


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
    assert recurso["dataset_catalog"] == "${var.catalog}"
    assert recurso["dataset_schema"] == "${var.schema}"
    assert recurso["embed_credentials"] is False


def test_painel_tem_as_tres_paginas():
    assert [p["displayName"] for p in painel()["pages"]] == ["Visão geral", "Áreas e vagas", "Pendências"]


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


def test_widgets_nao_se_sobrepoem():
    ocupadas: dict[tuple[str, int, int], str] = {}
    for pagina, item in widgets_do_painel():
        pos = item["position"]
        assert pos["x"] + pos["width"] <= 6, item["widget"]["name"]
        for x in range(pos["x"], pos["x"] + pos["width"]):
            for y in range(pos["y"], pos["y"] + pos["height"]):
                chave = (pagina, x, y)
                assert chave not in ocupadas, (item["widget"]["name"], ocupadas.get(chave))
                ocupadas[chave] = item["widget"]["name"]


def test_gold_junta_as_duas_silvers():
    sql = (PASTA_PIPELINE / "gold_entrevistas.sql").read_text(encoding="utf-8")
    assert "silver_agenda" in sql and "silver_cargos" in sql and "JOIN" in sql


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


def test_gerador_cria_as_duas_versoes(agendas):
    assert [caminho.name for caminho in agendas] == ["agenda_exemplo_v1.csv", "agenda_exemplo_v2.csv"]


def test_agenda_tem_formato_da_planilha_real(agendas):
    for caminho in agendas:
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
    v1, v2 = (ler_agenda(caminho) for caminho in agendas)
    status_v2 = {(e["data"], e["horario"], e["nome"]): e["status"] for e in v2}
    vazios = [e for e in v1 if e["status"] == "" and e["nome"]]
    assert vazios
    assert all(status_v2[(e["data"], e["horario"], e["nome"])] for e in vazios)
    assert len(v2) > len(v1)


def test_telefones_do_gerador_sao_ficticios(agendas):
    for e in ler_agenda(agendas[1]):
        digitos = re.sub(r"\D", "", e["telefone"])
        assert len(digitos) < 10 or "90000" in digitos
