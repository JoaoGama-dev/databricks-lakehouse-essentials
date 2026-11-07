"""Testes da camada do projeto: as regras de negócio do exemplo (agenda de entrevistas).

Rodam sem Databricks. Conferem o que é próprio deste cliente: a limpeza das colunas da
agenda, a preparação de silver_agenda.sql, a gold e a view de entrevistas, o painel do
negócio e o gerador de dados fictícios. O que vale para qualquer cliente (motor, contrato
gerado do fontes.yml, bundle) fica em tests/nucleo/ (docs/padroes/nucleo-e-projeto.md).
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from essentials.config_fontes import (
    PREFIXOS_POR_TIPO,
    carregar_fontes,
    colunas_sensiveis,
    expectations,
    expressao_data_referencia,
    expressao_limpeza,
)

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = RAIZ / "config" / "fontes.yml"
PASTA_PIPELINE = RAIZ / "src" / "pipeline"
PASTA_VIEWS = RAIZ / "src" / "views"

FONTES = carregar_fontes(CONFIG)


def fonte(nome: str) -> dict:
    return next(f for f in FONTES if f["nome"] == nome)


def colunas_da_fonte(nome_fonte: str) -> dict:
    return fonte(nome_fonte)["colunas"]


def sem_comentarios(sql: str) -> str:
    return "\n".join(linha.split("--")[0] for linha in sql.splitlines())


def colunas_da_view(sql: str) -> list[str]:
    lista = sql[sql.index("(\n") + 2 : sql.index("\n)\nCOMMENT")]
    return [re.match(r"\s*(\w+) COMMENT '[^']{10,}',?$", linha).group(1) for linha in lista.splitlines()]


# Fonte agenda: config/fontes.yml e silver_agenda.sql ---------------------------------


def test_agenda_escolhe_o_retrato_pela_maior_data_de_entrevista():
    assert expressao_data_referencia(fonte("agenda")) == "max(dt_entrevista)"


def test_colunas_sensiveis_estao_marcadas():
    # Nome e telefone do candidato são dado pessoal: sem sensivel, saem da tag pii e da máscara.
    assert {coluna for f in FONTES for coluna in colunas_sensiveis(f)} == {"nm_candidato", "nr_telefone"}


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


def test_regra_data_plausivel_para_a_carga_inteira():
    # Substitui o cenário v4 da integração: uma planilha com data antes de 2020 não pode virar
    # painel; a regra precisa ser falhar (expect_all_or_fail), não drop nem alerta.
    _descartar, _alertar, falhar = expectations(fonte("agenda"))
    assert falhar == {"data_plausivel": "dt_entrevista IS NULL OR dt_entrevista >= DATE'2020-01-01'"}


def test_preparacao_da_agenda_remove_o_bom():
    sql = (PASTA_PIPELINE / "silver_agenda.sql").read_text(encoding="utf-8")
    # Remove os bytes EF BB BF (U+FEFF) do início do texto antes de reconhecer "AGENDA DIA".
    assert "trim(LEADING decode(unhex('EFBBBF'), 'UTF-8') FROM value)" in sql
    assert chr(0xFEFF) not in sql, "o SQL não deve conter um BOM literal, que é invisível"


def test_exclusao_de_titular_da_agenda_nao_tem_nome_do_gerador():
    # O SQL de exclusão da agenda real não pode levar nome de pessoa (o titular é parâmetro).
    especificacao = importlib.util.spec_from_file_location("exclusao", RAIZ / "scripts" / "gerar_exclusao_titular.py")
    exclusao = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(exclusao)
    sql = exclusao.gerar_sql(fonte("agenda"), "essentials", "portfolio_bronze", "portfolio_silver", "portfolio_gold")
    gerador = importar_gerador()
    nomes = set(gerador.PRIMEIROS_NOMES) | set(gerador.SOBRENOMES)
    assert not nomes & set(re.findall(r"\w+", sql)), nomes & set(re.findall(r"\w+", sql))
    assert ":titular_nm_candidato" in sql and ":titular_nr_telefone" not in sql


# Gold de entrevistas ----------------------------------------------------------------


GOLD_FATO = PASTA_PIPELINE / "gold_entrevistas.sql"


def test_fato_le_so_a_versao_vigente_e_e_incremental():
    sql = sem_comentarios(GOLD_FATO.read_text(encoding="utf-8"))
    # A silver é SCD tipo 2: sem o filtro, cada entrevista apareceria uma vez por versão.
    # (Sem função não determinística: test_contrato_do_projeto.py, para toda a gold.)
    assert "FROM silver_agenda AS e" in sql and "WHERE e.__END_AT IS NULL" in sql
    assert "\nCLUSTER BY AUTO\n" in sql


def de_para_da_fato() -> list[tuple[str, str]]:
    sql = GOLD_FATO.read_text(encoding="utf-8")
    bloco = sql[sql.index("de_para_area (ds_prefixo_vaga, nm_area) AS (") : sql.index("\n)\nSELECT")]
    return re.findall(r"\('([^']+)', '([^']+)'\)", bloco)


def test_de_para_de_area_compara_em_minusculas_sem_prefixo_repetido():
    # A junção é lower(nm_vaga) LIKE prefixo || '%': um prefixo com maiúscula nunca combinaria,
    # e um prefixo repetido com duas áreas deixaria a área ao acaso.
    de_para = de_para_da_fato()
    assert de_para, "o de-para não foi lido do SQL"
    prefixos = [prefixo for prefixo, _ in de_para]
    assert all(prefixo == prefixo.lower() for prefixo in prefixos), prefixos
    assert len(prefixos) == len(set(prefixos))
    # No LIKE, "%" e "_" são curingas e espaço na ponta nunca combinaria com o começo da vaga.
    assert all(prefixo == prefixo.strip() and not re.search(r"[%_]", prefixo) for prefixo in prefixos), prefixos
    assert all(area.strip() and area != "Não classificada" for _, area in de_para)
    sql = GOLD_FATO.read_text(encoding="utf-8")
    assert "ON lower(e.nm_vaga) LIKE a.ds_prefixo_vaga || '%'" in sql
    assert "ORDER BY length(a.ds_prefixo_vaga) DESC NULLS LAST, a.ds_prefixo_vaga" in sql
    assert "coalesce(a.nm_area, 'Não classificada') AS nm_area" in sql


# View da gold de entrevistas --------------------------------------------------------


VIEW = PASTA_VIEWS / "gold_vw_entrevistas.sql"


def test_existe_view_da_gold_para_o_painel():
    # Sem a view, os testes parametrizados do contrato passariam vazios e o painel ficaria sem fonte.
    assert VIEW.is_file()


def test_view_tem_as_colunas_da_fato_e_o_que_depende_de_hoje():
    fato = GOLD_FATO.read_text(encoding="utf-8")
    bloco = re.search(r"gold_fato_entrevista \((.*?)\n\)\nCOMMENT", fato, re.DOTALL).group(1)
    colunas_fato = re.findall(r"^\s*(\w+) [A-Z]+ COMMENT", bloco, re.MULTILINE)
    sql = VIEW.read_text(encoding="utf-8")
    assert colunas_da_view(sql) == [*colunas_fato, "fl_sem_retorno"]
    # Só a fato: nenhum JOIN, nem com outra gold (o painel conta uma linha por entrevista).
    corpo = sem_comentarios(sql)[sem_comentarios(sql).index("AS SELECT") :]
    assert re.findall(r"\bFROM\s+(\S+)", corpo) == ["${catalogo}.${schema_gold}.gold_fato_entrevista"]
    assert "JOIN" not in corpo.upper()


# Painel do negócio ------------------------------------------------------------------

PAINEL = RAIZ / "src" / "dashboards" / "negocio.lvdash.json"


def painel() -> dict:
    return json.loads(PAINEL.read_text(encoding="utf-8"))


def widgets_do_painel() -> list[tuple[str, dict]]:
    return [(pagina["name"], item) for pagina in painel()["pages"] for item in pagina["layout"]]


def test_datasets_do_painel_so_leem_a_view_da_gold_sem_catalogo_fixo():
    # A fato não tem o que depende de hoje (fl_sem_retorno): o painel lê só a view.
    for dataset in painel()["datasets"]:
        sql = "".join(dataset["queryLines"])
        tabelas = re.findall(r"\b(?:FROM|JOIN)\s+([\w.]+)", sql, flags=re.IGNORECASE)
        tabelas = [t for t in tabelas if t != "entrevistas"]  # CTE interna
        assert tabelas, dataset["name"]
        assert all(re.fullmatch(r"gold_vw_\w+", t) for t in tabelas), (dataset["name"], tabelas)
        assert "essentials" not in sql and "portfolio" not in sql


def test_datasets_do_painel_so_usam_colunas_da_view():
    colunas = set(colunas_da_view(VIEW.read_text(encoding="utf-8")))
    prefixos = "|".join(PREFIXOS_POR_TIPO)
    for dataset in painel()["datasets"]:
        sql = "".join(dataset["queryLines"])
        apelidos = set(re.findall(r"\bAS ([a-z]\w*)", sql))
        usadas = set(re.findall(rf"\b(?:{prefixos})_\w+", sql)) - apelidos
        assert usadas <= colunas, (dataset["name"], usadas - colunas)


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
    # Os totais de tests/projeto/integracao/esperado.py dependem dos bytes da v1 a v4 versionados em data/.
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
