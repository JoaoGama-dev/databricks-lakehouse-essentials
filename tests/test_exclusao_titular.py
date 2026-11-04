"""Testes do scripts/gerar_exclusao_titular.py (LGPD, exclusão dos dados de um titular).

O script só gera SQL para revisão humana: não executa nada, não usa rede e não recebe o dado
da pessoa (o SQL usa marcadores de parâmetro :titular_<coluna>).
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import re
from pathlib import Path

import pytest

from essentials.config_fontes import carregar_fontes, colunas_sensiveis, tabelas_da_fonte
from fontes_ficticias import CADASTRO

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "scripts" / "gerar_exclusao_titular.py"
FONTES = {fonte["nome"]: fonte for fonte in carregar_fontes(RAIZ / "config" / "fontes.yml")}


def carregar_script():
    especificacao = importlib.util.spec_from_file_location("gerar_exclusao_titular", SCRIPT)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


EXCLUSAO = carregar_script()

# Fonte fictícia em CSV incremental: a bronze tem as colunas da origem.
CLIENTES = {
    "nome": "clientes",
    "descricao": "Clientes cadastrados no ERP.",
    "tipo": "arquivo",
    "arquivo": {"formato": "csv", "caminho": "clientes"},
    "modo_carga": "incremental",
    "chave_primaria": ["id_cliente"],
    "coluna_atualizacao": "_ingerido_em",
    "colunas": {
        "id_cliente": {"origem": "codigo", "tipo": "inteiro", "descricao": "Código do cliente no ERP."},
        "nm_cliente": {"origem": "nome", "tipo": "texto", "sensivel": True, "caixa": "titulo",
                       "descricao": "Nome do cliente."},
        "nr_documento": {"origem": "cpf", "tipo": "texto", "sensivel": True, "descricao": "CPF do cliente."},
        "nr_telefone": {"origem": "fone", "tipo": "texto", "sensivel": True, "mascarar": "telefone",
                        "descricao": "Telefone mascarado."},
    },
}


SCHEMAS = ("portfolio_bronze", "portfolio_silver", "portfolio_gold")
BRONZE = "`essentials`.`portfolio_bronze`"
SILVER = "`essentials`.`portfolio_silver`"


def sql_agenda() -> str:
    return EXCLUSAO.gerar_sql(FONTES["agenda"], "essentials", *SCHEMAS)


def sql_clientes() -> str:
    return EXCLUSAO.gerar_sql(CLIENTES, "essentials", *SCHEMAS)


def comandos(sql: str) -> list[str]:
    """Só o que seria executado: tira os comentários e junta cada comando numa linha."""
    sem_comentario = "\n".join(linha for linha in sql.splitlines() if not linha.startswith("--"))
    return [" ".join(comando.split()) for comando in sem_comentario.split(";") if comando.strip()]


# O titular nunca entra no script ----------------------------------------------------


def importar_gerador():
    especificacao = importlib.util.spec_from_file_location("gerador", RAIZ / "data" / "gerar_dados_exemplo.py")
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


@pytest.mark.parametrize("gerar", [sql_agenda, sql_clientes], ids=["agenda", "ficticia"])
def test_saida_nao_tem_nenhum_valor_de_pessoa(gerar):
    sql = gerar()
    gerador = importar_gerador()
    nomes = set(gerador.PRIMEIROS_NOMES) | set(gerador.SOBRENOMES)
    palavras = set(re.findall(r"\w+", sql))
    assert not nomes & palavras, nomes & palavras
    # Nem telefone ou documento: nenhuma sequência longa de dígitos.
    assert not re.search(r"\d{6,}", sql)
    # Os únicos textos literais nos comandos são os da limpeza padrão, nunca um valor.
    literais = {texto for comando in comandos(sql) for texto in re.findall(r"'([^']*)'", comando)}
    assert literais <= {" +", " ", "", "[.]+$", "\\n", "[\\u003B,\\t|]", "(", ") ****-", "[^0-9]"}, literais


def test_cada_coluna_que_identifica_a_pessoa_vira_um_parametro():
    assert ":titular_nm_candidato" in sql_agenda()
    sql = sql_clientes()
    assert ":titular_nm_cliente" in sql and ":titular_nr_documento" in sql
    # A coluna mascarada não guarda o valor completo: não serve para achar a pessoa.
    assert ":titular_nr_telefone" not in sql
    delete = next(c for c in comandos(sql) if c.startswith(f"DELETE FROM {SILVER}.`silver_clientes`"))
    assert "`nm_cliente` = initcap(" in delete and " AND `nr_documento` = " in delete


def test_parametro_recebe_a_mesma_limpeza_da_silver():
    silver = f"DELETE FROM {SILVER}.`silver_agenda` "
    delete = next(c for c in comandos(sql_agenda()) if c.startswith(silver))
    # caixa titulo e remover_ponto_final do fontes.yml, aplicados ao valor digitado.
    assert "`nm_candidato` = initcap(" in delete and "'[.]+$'" in delete
    assert "CAST(:titular_nm_candidato AS STRING)" in delete


def test_fonte_sem_coluna_que_identifica_a_pessoa_e_recusada():
    with pytest.raises(ValueError, match="sensivel: true sem mascarar"):
        EXCLUSAO.gerar_sql(CADASTRO, "essentials", *SCHEMAS)


@pytest.mark.parametrize(
    ("catalogo", "bronze", "silver", "gold"),
    [
        ("essentials; DROP CATALOG x", "portfolio_bronze", "portfolio_silver", "portfolio_gold"),
        ("essentials", "Portfolio_bronze", "portfolio_silver", "portfolio_gold"),
        ("essentials", "portfolio_bronze", "portfolio`.`x", "portfolio_gold"),
        ("essentials", "portfolio_bronze", "portfolio_silver", "portfolio-gold"),
        ("essentials", "", "portfolio_silver", "portfolio_gold"),
    ],
)
def test_identificador_invalido_e_recusado(catalogo, bronze, silver, gold):
    with pytest.raises(EXCLUSAO.IdentificadorInvalido):
        EXCLUSAO.gerar_sql(FONTES["agenda"], catalogo, bronze, silver, gold)


SCHEMAS_CLI = ["--schema-bronze", "b", "--schema-silver", "s", "--schema-gold", "g"]


def test_fonte_com_nome_invalido_e_recusada():
    with pytest.raises(EXCLUSAO.IdentificadorInvalido):
        EXCLUSAO.main(["--fonte", "agenda;x", "--catalogo", "c", *SCHEMAS_CLI])
    with pytest.raises(SystemExit, match="não está no config/fontes.yml"):
        EXCLUSAO.main(["--fonte", "nao_existe", "--catalogo", "c", *SCHEMAS_CLI])


# Tabelas e ordem dos passos -----------------------------------------------------------------


def test_agenda_cobre_todas_as_tabelas_com_dado_pessoal():
    sql = sql_agenda()
    tabelas = tabelas_da_fonte(FONTES["agenda"])
    assert colunas_sensiveis(FONTES["agenda"]) == ["nm_candidato", "nr_telefone"]
    executados = comandos(sql)
    # Bronze: texto inteiro em value; o UPDATE tira só as linhas do titular.
    bronze = f"{BRONZE}.`bronze_agenda`"
    assert any(c.startswith(f"UPDATE {bronze} SET value = array_join(filter(split(value, '\\n')") for c in executados)
    assert not any(c.startswith(f"DELETE FROM {bronze}") for c in executados), "apagaria o arquivo inteiro"
    # A silver SCD2 guarda todas as versões do titular: o DELETE nela apaga todas.
    assert f"DELETE FROM {SILVER}.`{tabelas['silver']}` WHERE" in "\n".join(executados)
    # O retrato (privado) e a gold são materialized views: recalculadas pelo pipeline, nunca com DELETE.
    for mv in (tabelas["validada"], "gold_fato_entrevista"):
        assert mv in sql, mv
        assert not any(mv in c and c.startswith(("DELETE", "UPDATE")) for c in executados), mv


@pytest.mark.parametrize("gerar", [sql_agenda, sql_clientes], ids=["agenda", "ficticia"])
def test_parametro_vazio_nao_apaga_nada(gerar):
    # Parâmetro esquecido ou em branco casaria com todo campo vazio: todo DELETE e UPDATE, e o
    # filtro que tira as linhas do texto, exigem o parâmetro preenchido.
    for comando in comandos(gerar()):
        if comando.startswith(("DELETE", "UPDATE", "SELECT")):
            for parametro in set(re.findall(r":titular_\w+", comando)):
                assert f"length(trim({parametro})) > 0" in comando, comando[:80]
    update = next(c for c in comandos(sql_agenda()) if c.startswith("UPDATE"))
    assert update.count("length(trim(:titular_nm_candidato)) > 0") == 2, "no filter e no WHERE"


def test_bronze_de_texto_compara_o_campo_inteiro_e_nao_pedaco_do_nome():
    # "Ana" não pode casar com "Mariana": cada campo da linha é comparado inteiro.
    update = next(c for c in comandos(sql_agenda()) if c.startswith("UPDATE"))
    assert "instr(" not in update and " LIKE " not in update.upper()
    assert "exists(split(linha, '[\\u003B,\\t|]'), campo -> initcap(" in update
    assert "= initcap(" in update


def test_fonte_csv_apaga_na_bronze_pelas_colunas_da_origem():
    executados = comandos(sql_clientes())
    delete = next(c for c in executados if c.startswith(f"DELETE FROM {BRONZE}.`bronze_clientes`"))
    assert "CAST(`nome` AS STRING)" in delete and "CAST(`cpf` AS STRING)" in delete


def test_reorg_e_vacuum_em_cada_tabela_alterada():
    for sql, alteradas in (
        (sql_agenda(), [f"{BRONZE}.`bronze_agenda`", f"{SILVER}.`silver_agenda`"]),
        (sql_clientes(), [f"{BRONZE}.`bronze_clientes`", f"{SILVER}.`silver_clientes`"]),
    ):
        executados = comandos(sql)
        reorg = [c for c in executados if c.startswith("REORG TABLE")]
        vacuum = [c for c in executados if c.startswith("VACUUM") and not c.endswith("DRY RUN")]
        # Cada tabela no schema da sua camada: no schema errado o REORG não acharia a tabela.
        assert reorg == [f"REORG TABLE {t} APPLY (PURGE)" for t in alteradas]
        assert vacuum == [f"VACUUM {t}" for t in alteradas]


def test_passos_na_ordem():
    sql = sql_agenda()
    posicoes = [sql.index(f"-- PASSO {n}.") for n in range(1, 8)]
    assert posicoes == sorted(posicoes)
    assert sql.index("-- PASSO 2.") < sql.index("UPDATE ") < sql.index("-- PASSO 3.")
    assert sql.index("-- PASSO 3.") < sql.index("DELETE FROM") < sql.index("-- PASSO 4.")
    assert sql.index("-- PASSO 6.") < sql.index("REORG TABLE") < sql.index("-- PASSO 7.") < sql.index("VACUUM")


def test_landing_nunca_apaga_a_pasta_inteira():
    landing = sql_agenda().split("-- PASSO 2.")[0]
    assert "/Volumes/essentials/portfolio_bronze/landing/agenda/" in landing
    assert "Nunca apague a pasta inteira" in landing
    passo_1 = landing[landing.index("-- PASSO 1.") :]
    assert not comandos(passo_1), "o passo 1 é só orientação"


def test_aviso_de_streaming_e_pendencia_do_skip_change_commits():
    agenda = sql_agenda()
    assert "ATENÇÃO" not in agenda  # snapshot: o AUTO CDC lê em lote, nada quebra
    # No incremental, a silver lê a bronze em streaming: o roteiro avisa que a carga quebraria.
    clientes = sql_clientes()
    assert "ATENÇÃO: src/pipeline/silver.py lê bronze_clientes em streaming" in clientes
    cdc = copy.deepcopy(CLIENTES)
    cdc.update(modo_carga="cdc", cdc={"coluna_operacao": "op", "valor_exclusao": "D"})
    sql_cdc = EXCLUSAO.gerar_sql(cdc, "essentials", *SCHEMAS)
    assert "O AUTO CDC também lê silver_int_clientes_mudancas em streaming" in sql_cdc
    assert f"DELETE FROM {SILVER}.`silver_int_clientes_mudancas`" in sql_cdc


def test_vacuum_explica_o_prazo_e_nao_reduz_a_retencao():
    vacuum = sql_agenda().split("-- PASSO 7.")[1]
    assert "time travel" in vacuum and "DEPOIS desse prazo" in vacuum
    assert "RETAIN" not in vacuum and "retentionDurationCheck" not in vacuum


# Nada é executado ----------------------------------------------------------------------------


def test_script_nao_importa_databricks_nem_rede():
    arvore = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    importados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            importados |= {alias.name.split(".")[0] for alias in no.names}
        elif isinstance(no, ast.ImportFrom):
            importados.add((no.module or "").split(".")[0])
    proibidos = {"databricks", "pyspark", "requests", "urllib", "http", "socket", "subprocess"}
    assert not importados & proibidos, importados & proibidos
    assert importados <= {"__future__", "argparse", "re", "sys", "pathlib", "essentials"}, importados


def test_saida_em_arquivo_ou_na_tela(tmp_path, capsys):
    destino = tmp_path / "exclusao.sql"
    argumentos = ["--fonte", "agenda", "--catalogo", "essentials", "--schema-bronze", "portfolio_bronze",
                  "--schema-silver", "portfolio_silver", "--schema-gold", "portfolio_gold"]
    EXCLUSAO.main([*argumentos, "--saida", str(destino)])
    assert destino.read_text(encoding="utf-8") == sql_agenda()
    assert "Nada foi executado" in capsys.readouterr().out
    EXCLUSAO.main(argumentos)
    assert capsys.readouterr().out == sql_agenda()
