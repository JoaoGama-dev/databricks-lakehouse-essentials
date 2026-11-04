"""Conexão com o target ci para os testes de integração (docs/adr/0005).

Precisa do resumo do bundle (recursos-ci.json ou INTEGRACAO_RECURSOS) e de credenciais do
Databricks (perfil da CLI na máquina; DATABRICKS_HOST e DATABRICKS_TOKEN no workflow).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "integracao.py"


def carregar_script():
    especificacao = importlib.util.spec_from_file_location("integracao_ci", SCRIPT)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="session")
def integracao():
    return carregar_script()


@pytest.fixture(scope="session")
def recursos(integracao) -> dict:
    if not integracao.ARQUIVO_RECURSOS.is_file():
        pytest.fail(f"resumo do bundle não encontrado em {integracao.ARQUIVO_RECURSOS}")
    return integracao.carregar_recursos()


@pytest.fixture(scope="session")
def consultar(integracao, recursos):
    """consultar(sql) -> lista de dicionários. {bronze}, {silver}, {gold} e {monitoramento}
    viram os schemas do CI; {catalogo}, o catálogo; {nome_<camada>}, o nome do schema como
    texto SQL, para filtrar o information_schema (o catálogo é o mesmo do dev)."""
    w = integracao.cliente()
    prefixos = {
        camada: f"`{recursos['catalogo']}`.`{recursos[f'schema_{camada}']}`" for camada in integracao.CAMADAS
    }
    # Os nomes já passaram por verificar_schema_ci ([a-z0-9_]+): seguros dentro das aspas.
    prefixos |= {f"nome_{camada}": f"'{recursos[f'schema_{camada}']}'" for camada in integracao.CAMADAS}
    prefixos["catalogo"] = f"`{recursos['catalogo']}`"

    def executar(sql: str) -> list[dict]:
        return integracao.executar_sql(w, recursos["warehouse_id"], sql.format(**prefixos))

    return executar


@pytest.fixture(scope="session")
def valor(consultar):
    """valor(sql) -> o primeiro campo da primeira linha, como inteiro."""

    def executar(sql: str) -> int:
        linhas = consultar(sql)
        return int(next(iter(linhas[0].values())))

    return executar


@pytest.fixture(scope="session")
def ultima_carga(integracao, recursos):
    """Estado de cada tarefa na última execução do job do CI."""
    w = integracao.cliente()
    execucao = next(iter(w.jobs.list_runs(job_id=int(recursos["job_id"]), limit=1, expand_tasks=True)))
    return {tarefa.task_key: tarefa.state.result_state.value for tarefa in execucao.tasks}
