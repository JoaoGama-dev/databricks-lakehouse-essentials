"""Contrato do projeto: testes gerados a partir do config/fontes.yml e da gold do projeto.

Valem para qualquer cliente sem escrever nada: cada teste é parametrizado por fonte, coluna
ou arquivo, e nenhum nome de fonte, coluna ou tabela aparece aqui. É o único arquivo do
núcleo, com test_nucleo_sem_projeto.py, que lê o fontes.yml e a gold do projeto.

Protegem contra: chave nula no AUTO CDC (linha que some ou carga que quebra), dado pessoal sem
máscara na gold, coluna sem descrição no dicionário, tabela fora do padrão de nomes e gold
fora do schema que o negócio lê.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from essentials.config_fontes import (
    PREFIXOS_POR_TIPO,
    carregar_fontes,
    colunas_sensiveis,
    colunas_silver,
    descricao_coluna,
    expectations,
    expressao_regra,
    pasta_landing,
    regras_efetivas,
    schema_silver,
    tabelas_da_fonte,
    validar_config,
)
from essentials.governanca_sql import FUNCAO_MASCARA

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = RAIZ / "config" / "fontes.yml"
PASTA_PIPELINE = RAIZ / "src" / "pipeline"
PASTA_VIEWS = RAIZ / "src" / "views"
PADRAO_TABELA_SQL = re.compile(
    r"CREATE OR REFRESH (?:STREAMING TABLE|MATERIALIZED VIEW)\s+(?:\$\{\w+\}\.)*(\w+)", re.IGNORECASE
)
MASCARA = f"${{catalogo}}.${{schema_silver}}.{FUNCAO_MASCARA}"
PREFIXOS = "|".join(PREFIXOS_POR_TIPO)
TIPOS_GOLD = {"dim": "dimensao", "fato": "fato", "agg": "agregada"}
# Funções que mudam de valor sem o dado mudar: fora do WHERE, impedem o refresh incremental.
NAO_DETERMINISTICAS = r"\b(current_date|current_timestamp|now|curdate|rand|randn|uuid|unix_timestamp)\s*\("

FONTES = carregar_fontes(CONFIG)
ARQUIVOS_GOLD = sorted(PASTA_PIPELINE.glob("gold_*.sql"))
ARQUIVOS_VIEWS = sorted(PASTA_VIEWS.glob("gold_vw_*.sql"))
COLUNAS = [(fonte, coluna) for fonte in FONTES for coluna in fonte["colunas"]]
CHAVES = [(fonte, coluna) for fonte in FONTES for coluna in fonte["chave_primaria"]]
SENSIVEIS = [(fonte, coluna) for fonte in FONTES for coluna in colunas_sensiveis(fonte)]


def id_fonte(fonte: dict) -> str:
    return fonte["nome"]


def id_par(par: tuple[dict, str]) -> str:
    return f"{par[0]['nome']}-{par[1]}"


def id_arquivo(arquivo: Path) -> str:
    return arquivo.name


def ler(arquivo: Path) -> str:
    return arquivo.read_text(encoding="utf-8")


def sem_comentarios(sql: str) -> str:
    return "\n".join(linha.split("--")[0] for linha in sql.splitlines())


def colunas_declaradas_da_gold(sql: str) -> list[tuple[str, str]]:
    """(coluna, linha da declaração) de todas as tabelas de um gold_*.sql.

    Lista, não dicionário: a mesma coluna pode estar em duas tabelas (dimensão e fato), e a
    segunda não pode esconder a primeira.
    """
    blocos = re.findall(r"MATERIALIZED VIEW (?:\$\{\w+\}\.)*\w+ \((.*?)\n\)\nCOMMENT", sql, re.DOTALL)
    linhas = [linha.strip() for bloco in blocos for linha in bloco.strip().splitlines()]
    return [(linha.split()[0], linha.rstrip(",")) for linha in linhas if linha]


def violacoes_de_mascara_na_gold(sql: str, coluna: str) -> list[str]:
    """Declarações da gold que expõem a coluna sensível (ou um apelido dela) sem o MASK."""
    declaradas = colunas_declaradas_da_gold(sql)
    # Renomeada no SELECT ("e.coluna AS outro_nome"): o nome novo também é sensível.
    apelidos = re.findall(rf"\b\w+\.{coluna}\b[^,\n]*?\bAS\s+(\w+)", sem_comentarios(sql))
    sensiveis = {coluna, *apelidos}
    erros = [linha for nome, linha in declaradas if nome in sensiveis and not linha.endswith(f"MASK {MASCARA}")]
    erros += [f"apelido {nome} não declarado" for nome in apelidos if nome not in {n for n, _ in declaradas}]
    return erros


def colunas_da_view(sql: str) -> list[str]:
    lista = sql[sql.index("(\n") + 2 : sql.index("\n)\nCOMMENT")]
    return [re.match(r"\s*(\w+) COMMENT '[^']{10,}',?$", linha).group(1) for linha in lista.splitlines()]


def corpo_da_view(sql: str) -> str:
    return sem_comentarios(sql)[sem_comentarios(sql).index("AS SELECT") :]


# fontes.yml ------------------------------------------------------------------------


def test_config_do_projeto_valida_contra_o_schema():
    validar_config(yaml.safe_load(ler(CONFIG)))
    assert FONTES


def test_contrato_declara_o_que_nao_conseguiu_verificar():
    # Sem gold, sem view ou sem coluna sensível, os testes parametrizados deste arquivo nascem
    # vazios e o pytest os pula sem dizer por quê. Aqui o motivo fica escrito.
    ausentes = [
        texto
        for texto, falta in (
            ("gold (src/pipeline/gold_*.sql): contratos da gold não verificados", not ARQUIVOS_GOLD),
            ("views (src/views/gold_vw_*.sql): contrato das views não verificado", not ARQUIVOS_VIEWS),
            ("coluna sensível no fontes.yml: contrato de máscara não verificado", not SENSIVEIS),
            ("chave_primaria no fontes.yml: contrato da chave não verificado", not CHAVES),
        )
        if falta
    ]
    if ausentes:
        pytest.skip("projeto sem " + "; sem ".join(ausentes))


GOLD_COM_MASCARA = f"""CREATE OR REFRESH MATERIALIZED VIEW ${{catalogo}}.${{schema_gold}}.gold_fato_x (
  nm_a STRING COMMENT 'Nome da pessoa, mascarado.' MASK {MASCARA},
  nm_b STRING COMMENT 'Nome repetido em outra tabela.' MASK {MASCARA}
)
COMMENT 'x'
AS SELECT e.nm_a, e.nm_a AS nm_b FROM t e;
"""


def test_deteccao_de_mascara_pega_coluna_sem_mask_renomeada_ou_repetida():
    # O teste de máscara só vale se a detecção falha quando deve: o contrato rodando contra uma
    # gold fictícia estragada de três jeitos.
    assert not violacoes_de_mascara_na_gold(GOLD_COM_MASCARA, "nm_a")
    sem_mask = GOLD_COM_MASCARA.replace(f" MASK {MASCARA},", ",", 1)
    assert violacoes_de_mascara_na_gold(sem_mask, "nm_a")
    # Apelido: nm_b vem de e.nm_a e também precisa do MASK.
    apelido_sem_mask = GOLD_COM_MASCARA.replace(f"tabela.' MASK {MASCARA}", "tabela.'")
    assert violacoes_de_mascara_na_gold(apelido_sem_mask, "nm_a")
    # Mesma coluna em duas tabelas, só a segunda com MASK: a segunda não esconde a primeira.
    duas = GOLD_COM_MASCARA.replace(f" MASK {MASCARA},", ",", 1) + GOLD_COM_MASCARA.replace("gold_fato_x", "gold_dim_x")
    assert violacoes_de_mascara_na_gold(duas, "nm_a")
    # Apelido sem declaração na gold: o dado sai sem dicionário nem máscara.
    assert violacoes_de_mascara_na_gold(GOLD_COM_MASCARA + "SELECT e.nm_a AS nm_c FROM t e;", "nm_a")


@pytest.mark.parametrize(("fonte", "coluna"), CHAVES, ids=list(map(id_par, CHAVES)))
def test_coluna_da_chave_tem_nao_nulo_que_barra_a_linha(fonte, coluna):
    # Chave nula: o AUTO CDC não aceita (a carga quebra ou a linha some sem aviso) e o
    # incremental grava registro que não dá para identificar. A regra precisa barrar a linha.
    regras = [r for r in regras_efetivas(fonte) if r["tipo"] == "nao_nulo" and r.get("coluna") == coluna]
    assert regras, f"{coluna} sem regra nao_nulo"
    assert all(regra["acao"] in ("drop", "falhar") for regra in regras), regras
    barrar, _, falhar = expectations(fonte)
    assert any(f"`{coluna}` IS NOT NULL" in condicao for condicao in (*barrar.values(), *falhar.values()))


@pytest.mark.parametrize(("fonte", "coluna"), COLUNAS, ids=list(map(id_par, COLUNAS)))
def test_coluna_tem_descricao_que_vira_comment_na_silver(fonte, coluna):
    # Dicionário obrigatório (regra 7): a descrição é o que o negócio lê no Catalog Explorer.
    descricao = descricao_coluna(fonte, coluna)
    assert len(descricao.strip()) >= 10, descricao
    assert re.search(rf"`{coluna}` [A-Z(),0-9]+ COMMENT '", schema_silver(fonte))


@pytest.mark.parametrize(("fonte", "coluna"), SENSIVEIS, ids=list(map(id_par, SENSIVEIS)))
def test_coluna_sensivel_que_chega_a_gold_tem_mascara(fonte, coluna):
    # LGPD. Na silver (schema só da engenharia), a coluna sensível sem "mascarar" fica com o
    # valor e a tag pii: é ela que identifica o titular na exclusão. Ao chegar à gold, que o
    # negócio lê, toda tabela que a declara precisa do MASK e toda view que a mostra precisa
    # passar pela função de máscara (o painel lê a view; ADR 0002 e 0020). Vale também para a
    # coluna já mascarada na silver (ex.: telefone parcial), que ainda é dado pessoal.
    for arquivo in ARQUIVOS_GOLD:
        assert not violacoes_de_mascara_na_gold(ler(arquivo), coluna), arquivo.name
    for arquivo in ARQUIVOS_VIEWS:
        sql = ler(arquivo)
        if coluna in colunas_da_view(sql):
            mascara = rf"^\s*{re.escape(MASCARA)}\(\w+\.{coluna}\) AS {coluna},?$"
            assert re.search(mascara, corpo_da_view(sql), re.MULTILINE), (arquivo.name, coluna)


# Tabelas de cada fonte ------------------------------------------------------------


@pytest.mark.parametrize("f", FONTES, ids=id_fonte)
def test_cada_fonte_gera_sua_bronze(f):
    # Toda fonte gera bronze e silver; a que vem por arquivo, banco ou API tem a sua pasta na landing.
    tabelas = tabelas_da_fonte(f)
    assert tabelas["bronze"] == f"bronze_{f['nome']}"
    assert tabelas["silver"] == f"silver_{f['nome']}"
    if f["tipo"] != "tabela":
        assert pasta_landing(f)


@pytest.mark.parametrize("f", FONTES, ids=id_fonte)
def test_tabelas_seguem_camada_tipo_nome(f):
    tabelas = tabelas_da_fonte(f)
    nomes = [tabelas["bronze"], tabelas["silver"], tabelas["preparada"], tabelas["validada"]]
    nomes += tabelas["unicidade"]
    padrao = re.compile(rf"^(bronze_{f['nome']}|silver_{f['nome']}|silver_int_{f['nome']}_\w+)$")
    assert all(padrao.match(nome) for nome in nomes if nome)


@pytest.mark.parametrize("f", FONTES, ids=id_fonte)
def test_regras_viram_expectations(f):
    descartar, alertar, falhar = expectations(f)
    destinos = {"drop": descartar, "alerta": alertar, "falhar": falhar}
    for regra in regras_efetivas(f):
        if regra["tipo"] == "unico":
            assert all(regra["nome"] not in destino for destino in destinos.values())
            continue
        assert destinos[regra["acao"]][regra["nome"]] == expressao_regra(regra)


@pytest.mark.parametrize("f", FONTES, ids=id_fonte)
def test_schema_da_silver_descreve_todas_as_colunas_na_ordem(f):
    schema = schema_silver(f)
    colunas = re.findall(r"`(\w+)` [A-Z(),0-9]+ COMMENT '", schema)
    assert colunas == colunas_silver(f)
    assert colunas[: len(f["colunas"])] == list(f["colunas"])
    assert schema.count(" COMMENT ") == len(colunas)


def test_preparacao_sql_existe_quando_pedida():
    for f in FONTES:
        if f.get("preparacao_sql"):
            sql = ler(PASTA_PIPELINE / f"silver_{f['nome']}.sql")
            assert f"CREATE TEMPORARY VIEW silver_int_{f['nome']}_preparada" in sql
            # A view mantém os nomes da origem; os nomes padronizados vêm do YAML.
            for configuracao in f["colunas"].values():
                if not configuracao["origem"].startswith("_"):
                    assert configuracao["origem"] in sql
            # A bronze fica no schema dela: sem o nome qualificado, a preparação leria a silver.
            assert f"FROM ${{catalogo}}.${{schema_bronze}}.bronze_{f['nome']}" in sql


def test_variavel_de_ingestao_reflete_o_fontes_yml():
    # Fonte banco ou api sem a variável em "true": a ingestão é pulada e a carga fica sem dado novo.
    import ingestao.ingerir_fontes_externas as modulo

    bundle = yaml.safe_load(ler(RAIZ / "databricks.yml"))
    esperado = "true" if modulo.tem_fonte_externa(FONTES) else "false"
    assert bundle["variables"]["ingerir_fontes_externas"]["default"] == esperado


# Gold ------------------------------------------------------------------------------


@pytest.mark.parametrize("arquivo", ARQUIVOS_GOLD, ids=id_arquivo)
def test_gold_e_publicada_no_schema_gold(arquivo):
    # Fora do schema gold, o negócio não lê a tabela (ou lê na silver, sem as permissões certas).
    criadas = re.findall(r"CREATE OR REFRESH MATERIALIZED VIEW (\S+)", ler(arquivo))
    assert criadas and all(nome.startswith("${catalogo}.${schema_gold}.gold_") for nome in criadas), criadas


@pytest.mark.parametrize("arquivo", ARQUIVOS_GOLD, ids=id_arquivo)
def test_gold_segue_camada_tipo_nome_com_comment(arquivo):
    sql = ler(arquivo)
    for bloco in re.split(r"CREATE OR REFRESH", sql, flags=re.IGNORECASE)[1:]:
        tabela = PADRAO_TABELA_SQL.search("CREATE OR REFRESH" + bloco).group(1)
        tipo = re.match(r"gold_(dim|fato|agg)_[a-z0-9_]+$", tabela)
        assert tipo, f"{tabela} não segue gold_<dim|fato|agg>_<nome>"
        assert "COMMENT '" in bloco
        assert f"TBLPROPERTIES ('camada' = 'gold', 'tipo' = '{TIPOS_GOLD[tipo.group(1)]}')" in bloco


@pytest.mark.parametrize("arquivo", ARQUIVOS_GOLD, ids=id_arquivo)
def test_colunas_da_gold_tem_tipo_e_descricao(arquivo):
    sql = ler(arquivo)
    blocos = re.findall(r"MATERIALIZED VIEW (?:\$\{\w+\}\.)*\w+ \((.*?)\n\)\nCOMMENT", sql, re.DOTALL)
    assert len(blocos) == len(PADRAO_TABELA_SQL.findall(sql)), "toda view da gold declara as colunas"
    for bloco in blocos:
        for linha in [linha.strip() for linha in bloco.strip().splitlines()]:
            # Tipo com precisão (DECIMAL(18,2)) também vale.
            padrao = rf"({PREFIXOS})_\w+ [A-Z]+(?:\(\d+(?:, ?\d+)?\))? COMMENT '[^']{{10,}}'( MASK [\w${{}}.]+)?,?"
            assert re.fullmatch(padrao, linha), linha


@pytest.mark.parametrize("arquivo", ARQUIVOS_GOLD, ids=id_arquivo)
def test_colunas_da_gold_tem_prefixo_da_classe(arquivo):
    sql = ler(arquivo)
    # Apelidos de coluna em minúsculas com mais de uma letra (e, c, f, d são apelidos de tabela).
    apelidos = re.findall(r"\bAS ([a-z][a-z0-9_]+)\b", sql)
    assert apelidos
    assert all(re.match(rf"^({PREFIXOS})_", apelido) for apelido in apelidos), apelidos


@pytest.mark.parametrize("arquivo", ARQUIVOS_GOLD, ids=id_arquivo)
def test_gold_sem_funcao_nao_deterministica(arquivo):
    # Com current_date() e afins, a materialized view perde o refresh incremental (custo).
    assert not re.search(NAO_DETERMINISTICAS, sem_comentarios(ler(arquivo)), re.IGNORECASE)


# Views da gold (src/views/), criadas pela publicar_monitoramento -----------------------


@pytest.mark.parametrize("arquivo", ARQUIVOS_VIEWS, ids=id_arquivo)
def test_view_da_gold_tem_dicionario_e_propriedades(arquivo):
    sql = ler(arquivo)
    nome = re.search(r"CREATE OR REPLACE VIEW \$\{catalogo\}\.\$\{schema_gold\}\.(\w+) \(", sql).group(1)
    assert nome == arquivo.stem and re.fullmatch(r"gold_vw_[a-z0-9_]+", nome)
    colunas = colunas_da_view(sql)
    assert all(re.match(rf"^({PREFIXOS})_", coluna) for coluna in colunas), colunas
    # Na ordem do SELECT: o COMMENT de cada coluna cai na coluna certa.
    selecao = corpo_da_view(sql)
    selecionadas = [linha.strip().rstrip(",").split(" AS ")[-1].split(".")[-1]
                    for linha in selecao.splitlines()[1:] if linha.strip() and not linha.lstrip().startswith("FROM")]
    assert selecionadas == colunas
    assert "\nCOMMENT '" in sql
    assert "TBLPROPERTIES ('camada' = 'gold', 'tipo' = 'view')" in sql
    # A view só lê a gold: um FROM ou JOIN na silver traria o dado pessoal sem a máscara da fato.
    lidas = re.findall(r"\b(?:FROM|JOIN)\s+(\S+)", sem_comentarios(sql), re.IGNORECASE)
    assert lidas and all(t.startswith("${catalogo}.${schema_gold}.gold_") for t in lidas), lidas
