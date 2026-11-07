"""O núcleo nunca contém nome de fonte, coluna, regra ou tabela da gold do projeto.

Risco: um nome do cliente escrito no motor (num comentário, num teste, num padrão) faz o
núcleo funcionar só para ele, e leva o assunto de um cliente para o pacote de outro. Os
termos vêm sozinhos do config/fontes.yml, da gold (src/pipeline/gold_*.sql e
src/views/gold_vw_*.sql) e da lista de termos do negócio da camada do projeto
(tests/projeto/termos_do_negocio.py). A lista do núcleo está em
docs/padroes/nucleo-e-projeto.md.

A busca é por palavra inteira, sem diferenciar maiúsculas; o "_" separa palavras, para achar
o nome também dentro de um identificador (bronze_<fonte>, :titular_<coluna>). Ficam de fora
as colunas técnicas (começam com "_"), os tipos de máscara e os tipos de coluna, que são do
núcleo.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from essentials.config_fontes import TIPOS_SQL, carregar_fontes, tabelas_da_fonte
from fontes_ficticias import CADASTRO, EVENTOS

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = RAIZ / "config" / "fontes.yml"
ESTE_ARQUIVO = Path(__file__).resolve()

# Código do núcleo que é varrido. Os documentos (docs/, README, CHANGELOG, CLAUDE.md), os
# agentes e skills (.claude/) e as configurações do repositório (.gitignore, .gitattributes,
# .pre-commit-config.yaml) também são do núcleo, mas ainda explicam o exemplo e citam os
# arquivos fictícios dele: ficam fora desta varredura até serem revistos (ver o padrão).
# Os hooks (.claude/hooks/) e o teste deles liberam por nome os arquivos fictícios do
# exemplo (em data/) e por isso também ficam de fora.
PADROES_DO_NUCLEO = (
    "src/essentials/**/*.py",
    "src/pipeline/bronze.py",
    "src/pipeline/silver.py",
    "src/ingestao/**/*",
    "src/governanca/**/*",
    "src/dashboards/saude.lvdash.json",
    "scripts/*.py",
    "resources/*.yml",
    "databricks.yml",
    "config/fontes.schema.json",
    "setup/*",
    ".github/workflows/*.yml",
    "tests/conftest.py",
    "tests/nucleo/**/*.py",
)
# Camada do projeto dentro dessas pastas (docs/padroes/nucleo-e-projeto.md).
FORA_DA_VARREDURA = {
    "scripts/integracao.py",  # carrega o exemplo no target ci
    ".github/workflows/integracao.yml",  # roda o exemplo no target ci
    "tests/nucleo/test_hooks.py",  # testa a liberação dos arquivos fictícios do exemplo
}


def arquivos_do_nucleo() -> list[Path]:
    arquivos = set()
    for padrao in PADROES_DO_NUCLEO:
        for caminho in RAIZ.glob(padrao):
            relativo = caminho.relative_to(RAIZ).as_posix()
            if caminho.is_file() and "__pycache__" not in caminho.parts and relativo not in FORA_DA_VARREDURA:
                arquivos.add(caminho)
    return sorted(arquivos)


def termos_do_negocio() -> tuple[str, ...]:
    caminho = RAIZ / "tests" / "projeto" / "termos_do_negocio.py"
    especificacao = importlib.util.spec_from_file_location("termos_do_negocio", caminho)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo.TERMOS_DO_NEGOCIO


def tipos_de_mascara() -> set[str]:
    """Os valores aceitos em "mascarar" no fontes.schema.json (telefone, hash)."""
    encontrados = set()

    def procurar(no):
        if isinstance(no, dict):
            if isinstance(no.get("mascarar"), dict):
                encontrados.update(no["mascarar"].get("enum", []))
            for valor in no.values():
                procurar(valor)
        elif isinstance(no, list):
            for valor in no:
                procurar(valor)

    procurar(json.loads((RAIZ / "config" / "fontes.schema.json").read_text(encoding="utf-8")))
    return encontrados


def nomes_da_gold() -> set[str]:
    """Tabelas e views da gold do projeto e as colunas que elas declaram."""
    nomes = set()
    tabela = r"CREATE OR REFRESH (?:STREAMING TABLE|MATERIALIZED VIEW)\s+(?:\$\{\w+\}\.)*(\w+)"
    for arquivo in (RAIZ / "src" / "pipeline").glob("gold_*.sql"):
        sql = arquivo.read_text(encoding="utf-8")
        nomes.update(re.findall(tabela, sql))
        nomes.update(re.findall(r"^\s+(\w+) [A-Z]+(?:\([\d, ]+\))? COMMENT '", sql, re.MULTILINE))
    for arquivo in (RAIZ / "src" / "views").glob("gold_vw_*.sql"):
        sql = arquivo.read_text(encoding="utf-8")
        nomes.add(arquivo.stem)
        nomes.update(re.findall(r"^\s+(\w+) COMMENT '", sql, re.MULTILINE))
    return nomes


def termos_da_fonte(fonte: dict) -> set[str]:
    tabelas = tabelas_da_fonte(fonte)
    termos = {fonte["nome"], *fonte["colunas"], *tabelas["unicidade"]}
    termos.update(nome for chave, nome in tabelas.items() if chave != "unicidade" and nome)
    termos.update(regra["nome"] for regra in fonte.get("regras", []))
    return termos


def termos_ficticios() -> set[str]:
    """Nomes das fontes fictícias do próprio núcleo (tests/nucleo/fontes_ficticias.py)."""
    return {termo.lower() for fonte in (EVENTOS, CADASTRO) for termo in termos_da_fonte(fonte)}


def termos_do_projeto() -> set[str]:
    termos = set(termos_do_negocio()) | nomes_da_gold()
    for fonte in carregar_fontes(CONFIG):
        termos |= termos_da_fonte(fonte)
    # Um cliente com uma coluna ou fonte de nome igual ao de uma fonte fictícia do núcleo (ex.:
    # um "cadastro") não é vazamento: o nome já era do núcleo. Sem isto, o teste quebraria num
    # cliente novo sem que nada tivesse vazado.
    permitidos = tipos_de_mascara() | set(TIPOS_SQL) | termos_ficticios()
    return {termo.lower() for termo in termos if not termo.startswith("_") and termo.lower() not in permitidos}


def detector(termos: set[str]) -> re.Pattern:
    # [^\W_] é letra ou dígito: o "_" conta como separador, para achar o termo dentro de um
    # identificador; uma palavra que só começa igual ao termo não é o termo.
    alternativas = "|".join(re.escape(termo) for termo in sorted(termos, key=len, reverse=True))
    return re.compile(rf"(?<![^\W_])({alternativas})(?![^\W_])", re.IGNORECASE)


def vazamentos(texto: str, padrao: re.Pattern) -> list[tuple[int, str]]:
    """(linha, termo) de cada termo do projeto achado no texto."""
    return [
        (numero, achado.group(1))
        for numero, linha in enumerate(texto.splitlines(), start=1)
        for achado in padrao.finditer(linha)
    ]


TERMOS = termos_do_projeto()
PADRAO = detector(TERMOS)
ARQUIVOS = arquivos_do_nucleo()


def test_varredura_tem_arquivos_e_termos():
    # Sem isto, um padrão de caminho errado ou um fontes.yml vazio faria o teste passar sem
    # conferir nada.
    relativos = {arquivo.relative_to(RAIZ).as_posix() for arquivo in ARQUIVOS}
    assert {"src/essentials/config_fontes.py", "src/pipeline/silver.py", "databricks.yml",
            "resources/pipeline.yml", "tests/nucleo/fontes_ficticias.py"} <= relativos
    assert ESTE_ARQUIVO in ARQUIVOS
    conhecidos = TERMOS | termos_ficticios()
    for fonte in carregar_fontes(CONFIG):
        assert fonte["nome"].lower() in conhecidos
        assert {coluna.lower() for coluna in fonte["colunas"] if not coluna.startswith("_")} <= conhecidos
    assert {termo.lower() for termo in termos_do_negocio()} <= conhecidos

@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda a: a.relative_to(RAIZ).as_posix())
def test_arquivo_do_nucleo_nao_cita_o_projeto(arquivo):
    achados = vazamentos(arquivo.read_text(encoding="utf-8"), PADRAO)
    assert not achados, f"termos do projeto no núcleo (linha, termo): {achados}"


def test_detector_pega_vazamento_e_ignora_o_que_e_generico():
    # Mutação em memória: um arquivo real do núcleo com nomes do projeto acrescentados.
    # Só usa o que o projeto tem: gold, regra e termos do negócio podem não existir num cliente.
    fontes = [f for f in carregar_fontes(CONFIG) if f["nome"].lower() in TERMOS]
    if not fontes:
        pytest.skip("nenhuma fonte do projeto com nome fora das fontes fictícias do núcleo")
    fonte = fontes[0]
    coluna = next((c for c in fonte["colunas"] if c.lower() in TERMOS), None)
    regra = next((r["nome"] for r in fonte.get("regras", []) if r["nome"].lower() in TERMOS), None)
    gold = next(iter(sorted(nome for nome in nomes_da_gold() if nome.lower() in TERMOS)), None)
    termo = next((t for t in termos_do_negocio() if t.lower() in TERMOS), None)
    original = (RAIZ / "src" / "essentials" / "config_fontes.py").read_text(encoding="utf-8")
    assert not vazamentos(original, PADRAO)
    linhas = [f"# exemplo: {fonte['nome']}", f"TABELA = 'bronze_{fonte['nome']}'"]
    esperados = {fonte["nome"].lower(), f"bronze_{fonte['nome']}".lower()}
    if coluna:
        linhas.append(f"PARAMETRO = ':titular_{coluna}'")
        esperados.add(coluna.lower())
    if regra:
        linhas.append(f"REGRA = '{regra.upper()}'")
        esperados.add(regra.lower())
    if gold:
        linhas.append(f"-- lê {gold}")
        esperados.add(gold.lower())
    if termo:
        linhas.append(f"# {termo.capitalize()} do cliente")
        esperados.add(termo.lower())
    achados = {achado.lower() for _, achado in vazamentos(original + "\n".join(linhas), PADRAO)}
    assert esperados <= achados, esperados - achados
    # Palavra que só começa igual ao termo, coluna técnica, tipo de máscara e tipo de coluna passam.
    generico = "# _linha, _ingerido_em, mascarar: telefone ou hash, tipo texto, data, inteiro"
    if termo:
        generico += f", {termo}mento"
    assert not vazamentos(generico, PADRAO)
