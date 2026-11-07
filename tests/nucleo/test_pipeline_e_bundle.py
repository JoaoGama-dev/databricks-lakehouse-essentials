"""Testes do bundle (databricks.yml e resources/*.yml) e do código genérico do pipeline.

Valem para qualquer projeto: não leem o config/fontes.yml nem citam fonte, tabela ou coluna
do cliente.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from essentials.config_fontes import nome_tabela_origem

RAIZ = Path(__file__).resolve().parents[2]
PASTA_PIPELINE = RAIZ / "src" / "pipeline"
SETUP = RAIZ / "setup" / "00_setup_free_edition.sql"
# O que pode existir em src/pipeline/, que o pipeline lê inteira (glob): o motor genérico, a
# preparação de cada fonte e a gold. Qualquer outro arquivo viraria código do pipeline.
ARQUIVOS_DO_PIPELINE = ("bronze.py", "silver.py", "silver_*.sql", "gold_*.sql")


def carregar_yaml(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def pipeline() -> dict:
    return carregar_yaml(RAIZ / "resources" / "pipeline.yml")["resources"]["pipelines"]["essentials_pipeline"]


def paineis() -> dict[str, dict]:
    return carregar_yaml(RAIZ / "resources" / "dashboard.yml")["resources"]["dashboards"]


# Pipeline ---------------------------------------------------------------------------


def test_pipeline_le_a_pasta_inteira_e_ela_so_tem_codigo_do_pipeline():
    # O glob inclui tudo o que está na pasta: um arquivo de outro tipo (rascunho, notebook,
    # dado) entraria como código-fonte e quebraria o deploy ou a carga.
    assert pipeline()["libraries"] == [{"glob": {"include": "../src/pipeline/**"}}]
    pasta = (RAIZ / "resources" / "../src/pipeline").resolve()
    assert pasta == PASTA_PIPELINE.resolve()
    arquivos = {caminho for caminho in pasta.rglob("*") if caminho.is_file() and "__pycache__" not in caminho.parts}
    esperados = {caminho for padrao in ARQUIVOS_DO_PIPELINE for caminho in pasta.glob(padrao)}
    assert arquivos == esperados, sorted(str(c.relative_to(pasta)) for c in arquivos ^ esperados)
    assert {"bronze.py", "silver.py"} <= {caminho.name for caminho in arquivos}


def test_pipeline_serverless_com_configuracao():
    configuracao = pipeline()
    assert configuracao["serverless"] is True
    assert configuracao["continuous"] is False
    assert {
        "catalogo", "projeto", "schema_bronze", "schema_silver", "schema_gold", "schema_monitoramento",
        "landing_path", "fontes_config", "diretorio_codigo",
    } <= set(configuracao["configuration"])


def test_pipeline_limita_as_novas_tentativas_numa_falha():
    # Custo: sem o limite, a plataforma repete a atualização inteira 5 vezes (visto no dev em
    # 2026-11-05: uma regra que para a carga gerou 6 atualizações, ~14 min, ~6x o custo).
    configuracao = pipeline()["configuration"]
    assert int(configuracao["pipelines.numUpdateRetryAttempts"]) <= 1
    assert int(configuracao["pipelines.maxFlowRetryAttempts"]) <= 1


def test_bronze_e_silver_leem_e_publicam_com_nome_qualificado():
    bronze = (PASTA_PIPELINE / "bronze.py").read_text(encoding="utf-8")
    assert 'nome = f"{CATALOGO}.{SCHEMA_BRONZE}.{tabelas_da_fonte(fonte)[\'bronze\']}"' in bronze
    silver = (PASTA_PIPELINE / "silver.py").read_text(encoding="utf-8")
    assert 'f"{CATALOGO}.{SCHEMA_BRONZE}.{tabelas[\'bronze\']}"' in silver


# Bundle, job e targets ----------------------------------------------------------------


def test_estrutura_do_pacote_essentials():
    """Catálogo do pacote, schemas e landing do projeto no bundle, bundle com o nome do projeto."""
    bundle = carregar_yaml(RAIZ / "databricks.yml")
    variaveis = bundle["variables"]
    projeto = variaveis["projeto"]["default"]
    assert bundle["bundle"]["name"] == f"essentials_{projeto}"
    assert variaveis["catalog"]["default"] == "essentials"
    assert pipeline()["name"] == "${var.projeto}_pipeline_medalhao"
    job = carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]["essentials_carga_diaria"]
    assert job["name"] == "${var.projeto}_job_carga_diaria"
    # Silver é o schema padrão; bronze e gold vêm da configuration com o nome qualificado.
    assert pipeline()["schema"] == "${resources.schemas.silver.name}"
    for camada in ("bronze", "silver", "gold", "monitoramento"):
        assert pipeline()["configuration"][f"schema_{camada}"] == f"${{resources.schemas.{camada}.name}}"
    assert pipeline()["configuration"]["landing_path"].startswith("/Volumes/${resources.volumes.landing.")


def test_chaves_do_pipeline_e_do_job_nao_mudam():
    # Trocar a chave faria o bundle apagar o pipeline (e as tabelas dele) e o job.
    assert "essentials_pipeline" in carregar_yaml(RAIZ / "resources" / "pipeline.yml")["resources"]["pipelines"]
    assert "essentials_carga_diaria" in carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]


def test_setup_cria_so_o_que_nao_pertence_ao_bundle():
    # Os schemas e o volume são do bundle; o setup só cria o catálogo (sem origem simulada).
    setup = SETUP.read_text(encoding="utf-8")
    assert "CREATE CATALOG IF NOT EXISTS essentials\n" in setup
    assert "CREATE SCHEMA" not in setup and "CREATE VOLUME" not in setup and "CREATE TABLE" not in setup


def test_nome_da_tabela_de_origem_usa_catalogo_e_projeto():
    fonte_tabela = {"tabela": {"nome_completo": "{catalogo}.{projeto}_origem.cadastro"}}
    assert nome_tabela_origem(fonte_tabela, "prd", "clinica") == "prd.clinica_origem.cadastro"


def test_job_roda_ingestao_antes_do_pipeline():
    job = carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]["essentials_carga_diaria"]
    tarefas = {tarefa["task_key"]: tarefa for tarefa in job["tasks"]}
    assert job["schedule"]["timezone_id"] == "America/Sao_Paulo"
    pipeline_id = tarefas["processar_medalhao"]["pipeline_task"]["pipeline_id"]
    assert pipeline_id == "${resources.pipelines.essentials_pipeline.id}"
    dependencias = {d["task_key"] for d in tarefas["processar_medalhao"]["depends_on"]}
    assert dependencias == {"ingerir_fontes_externas", "preparar_governanca"}
    assert (RAIZ / "resources" / tarefas["ingerir_fontes_externas"]["spark_python_task"]["python_file"]).is_file()


def test_targets_dev_e_prod():
    targets = carregar_yaml(RAIZ / "databricks.yml")["targets"]
    assert targets["dev"]["mode"] == "development"
    assert targets["dev"]["default"] is True
    assert targets["prod"]["mode"] == "production"


def test_prod_tem_run_as():
    prod = carregar_yaml(RAIZ / "databricks.yml")["targets"]["prod"]
    assert prod["run_as"]["service_principal_name"]
    assert prod["variables"]["catalog"] == "prd"


# Painéis AI/BI ---------------------------------------------------------------------------


@pytest.mark.parametrize("chave", ["painel_negocio", "painel_saude"])
def test_painel_esta_no_bundle_sem_ambiente_fixo(chave):
    # Trocar a chave recria o painel (outro link para quem já usa); credencial embutida
    # mostraria o dado a quem não tem acesso à gold.
    recurso = paineis()[chave]
    assert (RAIZ / "resources" / recurso["file_path"]).resolve().is_file()
    assert recurso["warehouse_id"] == "${var.warehouse_id}"
    assert recurso["dataset_catalog"].startswith("${resources.schemas.")
    assert recurso["dataset_schema"].startswith("${resources.schemas.")
    assert recurso["embed_credentials"] is False
    assert recurso["display_name"].startswith("Essentials · ${var.projeto} · ")


def test_painel_do_negocio_le_a_gold_e_o_de_saude_o_monitoramento():
    # O negócio só tem acesso à gold; o monitoramento é só da engenharia (ADR 0018).
    assert paineis()["painel_negocio"]["dataset_schema"] == "${resources.schemas.gold.name}"
    assert paineis()["painel_negocio"]["file_path"] == "../src/dashboards/negocio.lvdash.json"
    assert paineis()["painel_saude"]["dataset_schema"] == "${resources.schemas.monitoramento.name}"
