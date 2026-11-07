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


def termos_do_projeto() -> set[str]:
    termos = set(termos_do_negocio()) | nomes_da_gold()
    for fonte in carregar_fontes(CONFIG):
        tabelas = tabelas_da_fonte(fonte)
        termos.add(fonte["nome"])
        termos.update(nome for chave, nome in tabelas.items() if chave != "unicidade" and nome)
        termos.update(tabelas["unicidade"])
        termos.update(fonte["colunas"])
        termos.update(regra["nome"] for regra in fonte.get("regras", []))
    permitidos = tipos_de_mascara() | set(TIPOS_SQL)
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
    for fonte in carregar_fontes(CONFIG):
        assert fonte["nome"].lower() in TERMOS
        assert {coluna.lower() for coluna in fonte["colunas"] if not coluna.startswith("_")} <= TERMOS
    assert set(termos_do_negocio()) <= TERMOS
    assert not TERMOS & (tipos_de_mascara() | set(TIPOS_SQL))


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda a: a.relative_to(RAIZ).as_posix())
def test_arquivo_do_nucleo_nao_cita_o_projeto(arquivo):
    achados = vazamentos(arquivo.read_text(encoding="utf-8"), PADRAO)
    assert not achados, f"termos do projeto no núcleo (linha, termo): {achados}"


def test_detector_pega_vazamento_e_ignora_o_que_e_generico():
    # Mutação em memória: um arquivo real do núcleo com nomes do projeto acrescentados.
    fonte = carregar_fontes(CONFIG)[0]
    coluna = next(c for c in fonte["colunas"] if not c.startswith("_"))
    regra = fonte["regras"][0]["nome"]
    gold = sorted(nomes_da_gold())[0]
    termo = termos_do_negocio()[0]
    original = (RAIZ / "src" / "essentials" / "config_fontes.py").read_text(encoding="utf-8")
    assert not vazamentos(original, PADRAO)
    mutado = original + "\n".join([
        f"# exemplo: {fonte['nome']}",
        f"TABELA = 'bronze_{fonte['nome']}'",
        f"PARAMETRO = ':titular_{coluna}'",
        f"REGRA = '{regra.upper()}'",
        f"-- lê {gold}",
        f"# {termo.capitalize()} do cliente",
    ])
    achados = {achado.lower() for _, achado in vazamentos(mutado, PADRAO)}
    assert {fonte["nome"].lower(), f"bronze_{fonte['nome']}".lower(), coluna.lower(), regra.lower(),
            gold.lower(), termo.lower()} <= achados
    # Palavra que só começa igual ao termo, coluna técnica, tipo de máscara e tipo de coluna passam.
    generico = f"# {termo}mento, _linha, _ingerido_em, mascarar: telefone ou hash, tipo texto, data, inteiro"
    assert not vazamentos(generico, PADRAO)
