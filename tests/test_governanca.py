"""Testes da governança no Unity Catalog como código (Fase 3).

Conferem o modelo de acesso declarado no bundle (resources/governanca.yml): quem chega a
cada schema e ao volume, e que nada do projeto pode ser apagado por um destroy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from essentials.config_fontes import carregar_fontes, colunas_sensiveis, validar_config
from essentials.governanca_sql import (
    FUNCAO_MASCARA,
    sql_funcao_mascara,
    sql_tags_da_tabela,
    sqls_tags_pii,
    sqls_views_gold,
)

RAIZ = Path(__file__).resolve().parents[1]


def carregar_yaml(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def recursos() -> dict:
    return carregar_yaml(RAIZ / "resources" / "governanca.yml")["resources"]


def grants(recurso: dict) -> dict[str, set[str]]:
    return {g["principal"]: set(g["privileges"]) for g in recurso["grants"]}


CAMADAS = ("bronze", "silver", "gold", "monitoramento")


def test_um_schema_por_camada_no_mesmo_catalogo():
    assert set(recursos()["schemas"]) == set(CAMADAS)
    for camada in CAMADAS:
        schema = recursos()["schemas"][camada]
        assert schema["name"] == f"${{var.projeto}}_{camada}"
        assert schema["catalog_name"] == "${var.catalog}"
    assert set(recursos()["volumes"]) == {"landing"}
    # A landing guarda o dado como chegou: fica com a bronze.
    assert recursos()["volumes"]["landing"]["schema_name"] == "${resources.schemas.bronze.name}"


def test_nada_do_projeto_pode_ser_apagado_por_destroy_em_dev_e_prod():
    # A proteção fica nos targets (o ci precisa ser destruído): docs/adr/0005.
    targets = carregar_yaml(RAIZ / "databricks.yml")["targets"]
    for alvo in ("dev", "prod"):
        for tipo in ("schemas", "volumes"):
            for nome in recursos()[tipo]:
                recurso = targets[alvo]["resources"][tipo][nome]
                assert recurso["lifecycle"]["prevent_destroy"] is True, f"{alvo}: {tipo}.{nome}"


def test_leitura_so_chega_a_gold():
    schemas = recursos()["schemas"]
    for camada in ("bronze", "silver", "monitoramento"):
        assert set(grants(schemas[camada])) == {"${var.grupo_engenharia}"}, camada
    assert "${var.grupo_leitura_gold}" not in grants(recursos()["volumes"]["landing"])
    assert grants(schemas["gold"])["${var.grupo_leitura_gold}"] == {"USE_SCHEMA", "SELECT"}


def test_engenharia_administra_os_schemas_e_a_landing():
    for recurso in recursos()["schemas"].values():
        assert grants(recurso)["${var.grupo_engenharia}"] == {"ALL_PRIVILEGES"}
    assert grants(recursos()["volumes"]["landing"])["${var.grupo_engenharia}"] == {"READ_VOLUME", "WRITE_VOLUME"}


def test_ninguem_alem_da_engenharia_tem_privilegio_amplo():
    for tipo in ("schemas", "volumes"):
        for recurso in recursos()[tipo].values():
            for principal, privilegios in grants(recurso).items():
                if principal != "${var.grupo_engenharia}":
                    assert not privilegios & {"ALL_PRIVILEGES", "MODIFY", "MANAGE", "WRITE_VOLUME"}, principal


def test_grupos_sao_variaveis_trocadas_em_producao():
    bundle = carregar_yaml(RAIZ / "databricks.yml")
    for grupo in ("grupo_engenharia", "grupo_leitura_gold", "grupo_dados_pessoais"):
        assert grupo in bundle["variables"]
        assert grupo in bundle["targets"]["prod"]["variables"]


def test_landing_de_producao_e_volume_externo():
    prod = carregar_yaml(RAIZ / "databricks.yml")["targets"]["prod"]
    landing = prod["resources"]["volumes"]["landing"]
    assert landing["volume_type"] == "EXTERNAL"
    # Nada de nuvem fixo no recurso: o endereço vem da variável (Azure é o padrão).
    assert landing["storage_location"] == "${var.landing_url}"
    assert prod["variables"]["landing_url"].startswith("abfss://")


def test_gold_e_publicada_no_schema_gold():
    sql = (RAIZ / "src" / "pipeline" / "gold_entrevistas.sql").read_text(encoding="utf-8")
    criadas = re.findall(r"CREATE OR REFRESH MATERIALIZED VIEW (\S+)", sql)
    assert criadas and all(nome.startswith("${catalogo}.${schema_gold}.gold_") for nome in criadas), criadas


# 3.3 e 3.4 Dados pessoais: máscara e tags -----------------------------------------

FONTES = carregar_fontes(RAIZ / "config" / "fontes.yml")
SENSIVEIS = {coluna for fonte in FONTES for coluna in colunas_sensiveis(fonte)}


def test_colunas_sensiveis_estao_marcadas():
    assert SENSIVEIS == {"nm_candidato", "nr_telefone"}


def test_coluna_mascarada_precisa_ser_sensivel():
    config = yaml.safe_load((RAIZ / "config" / "fontes.yml").read_text(encoding="utf-8"))
    del config["fontes"][0]["colunas"]["nr_telefone"]["sensivel"]
    with pytest.raises(ValueError, match="sensivel: true: nr_telefone"):
        validar_config(config)


def test_toda_coluna_sensivel_da_gold_tem_mascara():
    sql = (RAIZ / "src" / "pipeline" / "gold_entrevistas.sql").read_text(encoding="utf-8")
    vistas = set()
    for linha in sql.splitlines():
        coluna = re.match(r"\s+(\w+) [A-Z]+ COMMENT", linha)
        if coluna and coluna.group(1) in SENSIVEIS:
            vistas.add(coluna.group(1))
            assert linha.rstrip(",").endswith(f"MASK ${{catalogo}}.${{schema_silver}}.{FUNCAO_MASCARA}"), linha
    # Sem isto, uma mudança no formato da declaração faria o teste passar sem conferir nada.
    assert vistas == SENSIVEIS, SENSIVEIS - vistas


def test_funcao_de_mascara_libera_so_o_grupo_de_dados_pessoais():
    sql = sql_funcao_mascara("essentials", "portfolio", "essentials_dados_pessoais")
    assert sql.startswith("CREATE OR REPLACE FUNCTION `essentials`.`portfolio`.`mascarar_dado_pessoal`")
    assert "is_account_group_member('essentials_dados_pessoais')" in sql
    assert "ELSE '****'" in sql


OBJETOS_GOLD = {
    "gold_fato_entrevista": ("MATERIALIZED_VIEW", ["dt_entrevista", "nm_candidato", "nr_telefone"]),
    "gold_vw_entrevistas": ("VIEW", ["dt_entrevista", "nm_candidato", "nr_telefone", "fl_sem_retorno"]),
    "gold_fato_outra": ("MATERIALIZED_VIEW", ["dt_entrevista", "nm_area"]),
    "__materialization_mat_abc_gold_fato_entrevista_1": ("MANAGED", ["nm_candidato"]),
}


def test_tags_pii_cobrem_silver_e_gold_e_nunca_o_retrato_privado():
    comandos = sqls_tags_pii("essentials", "portfolio_silver", "portfolio_gold", FONTES, OBJETOS_GOLD)
    alvos = {re.search(r"ALTER TABLE (\S+) ALTER COLUMN `(\w+)`", c).groups() for c in comandos if "ALTER TABLE" in c}
    assert ("`essentials`.`portfolio_silver`.`silver_agenda`", "nm_candidato") in alvos
    assert ("`essentials`.`portfolio_silver`.`silver_agenda`", "nr_telefone") in alvos
    assert ("`essentials`.`portfolio_gold`.`gold_fato_entrevista`", "nm_candidato") in alvos
    # O retrato é privado: não está no catálogo, e um ALTER nele derrubaria a governanca_depois.
    assert not any("retrato" in c for c in comandos)
    assert not any(tabela.endswith("`gold_fato_outra`") for tabela, _ in alvos)
    assert not any("__materialization" in c for c in comandos), "tabela interna não recebe tag"


def test_tag_pii_em_view_usa_set_tag_e_so_onde_falta():
    # ALTER VIEW não altera coluna, e SET TAG ON COLUMN falha se a tag já existir.
    comandos = sqls_tags_pii("essentials", "portfolio_silver", "portfolio_gold", FONTES, OBJETOS_GOLD)
    na_view = [c for c in comandos if "gold_vw_entrevistas" in c]
    assert na_view == [
        "SET TAG ON COLUMN `essentials`.`portfolio_gold`.`gold_vw_entrevistas`.`nm_candidato` `pii` = `true`",
        "SET TAG ON COLUMN `essentials`.`portfolio_gold`.`gold_vw_entrevistas`.`nr_telefone` `pii` = `true`",
    ]
    ja_marcada = {("gold_vw_entrevistas", "nm_candidato")}
    comandos = sqls_tags_pii("essentials", "portfolio_silver", "portfolio_gold", FONTES, OBJETOS_GOLD, ja_marcada)
    assert [c for c in comandos if "gold_vw_entrevistas" in c] == [na_view[1]]


@pytest.mark.parametrize(
    ("tipo_objeto", "comando"),
    [
        ("STREAMING_TABLE", "ALTER STREAMING TABLE"),
        ("MATERIALIZED_VIEW", "ALTER MATERIALIZED VIEW"),
        ("VIEW", "ALTER VIEW"),
        ("MANAGED", "ALTER TABLE"),
    ],
)
def test_tags_camada_e_tipo_vem_das_propriedades_com_o_alter_de_cada_objeto(tipo_objeto, comando):
    propriedades = {"camada": "silver", "tipo": "historico", "fonte": "agenda", "pipelines.reset.allowed": "false"}
    sql = sql_tags_da_tabela("essentials", "portfolio_silver", "silver_agenda", tipo_objeto, propriedades)
    assert sql == (
        f"{comando} `essentials`.`portfolio_silver`.`silver_agenda` "
        "SET TAGS ('camada' = 'silver', 'tipo' = 'historico')"
    )


def test_sem_camada_e_tipo_ou_tabela_interna_nao_recebe_tag():
    # O event log não tem as propriedades; a tabela interna da materialized view não é do projeto.
    assert sql_tags_da_tabela("c", "s", "mon_log_eventos", "MANAGED", {"delta.minReaderVersion": "3"}) is None
    assert sql_tags_da_tabela("c", "s", "x", "VIEW", {"camada": "gold"}) is None
    assert sql_tags_da_tabela("c", "s", "__materialization_x", "MANAGED", {"camada": "g", "tipo": "f"}) is None
    assert sql_tags_da_tabela("c", "s", "x", "FOREIGN", {"camada": "g", "tipo": "f"}) is None


def test_governanca_aplica_as_tags_depois_das_views_nos_quatro_schemas():
    codigo = (RAIZ / "src" / "governanca" / "governanca.py").read_text(encoding="utf-8")
    depois = codigo[codigo.index("fontes = carregar_fontes(args.config)") :]
    assert depois.index("sqls_views_gold(") < depois.index("sqls_tags_pii(") < depois.index("aplicar_tags_das_tabelas(")
    assert "schemas = [args.schema_bronze, args.schema_silver, args.schema_gold, monitoramento]" in depois


def test_views_da_gold_saem_do_arquivo_com_o_schema_do_target():
    comandos = sqls_views_gold(RAIZ / "src", "essentials", "dev_x_portfolio_gold", "dev_x_portfolio_silver")
    assert comandos
    view = next(c for c in comandos if "gold_vw_entrevistas" in c)
    assert view.startswith("CREATE OR REPLACE VIEW `essentials`.`dev_x_portfolio_gold`.gold_vw_entrevistas (")
    assert "FROM `essentials`.`dev_x_portfolio_gold`.gold_fato_entrevista AS f" in view
    # A função de máscara fica no schema silver do target: outro schema quebraria a view.
    assert "`essentials`.`dev_x_portfolio_silver`.mascarar_dado_pessoal(f.nm_candidato)" in view
    # Sobrou marcador, comentário ou ";" no fim: o spark.sql recusaria ou leria o schema errado.
    assert all("${" not in c and "--" not in c and not c.endswith(";") for c in comandos)


def test_job_cria_a_mascara_antes_e_aplica_as_tags_depois_do_pipeline():
    job = carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]["essentials_carga_diaria"]
    tarefas = {tarefa["task_key"]: tarefa for tarefa in job["tasks"]}
    dependencias = {d["task_key"] for d in tarefas["atualizar_lakehouse"]["depends_on"]}
    assert "governanca_antes" in dependencias
    assert [d["task_key"] for d in tarefas["governanca_depois"]["depends_on"]] == ["atualizar_lakehouse"]
    for chave, etapa in (("governanca_antes", "antes"), ("governanca_depois", "depois")):
        parametros = tarefas[chave]["spark_python_task"]["parameters"]
        assert parametros[parametros.index("--etapa") + 1] == etapa
