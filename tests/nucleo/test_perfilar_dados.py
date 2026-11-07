"""Testes do scripts/perfilar_dados.py: o perfil descreve a estrutura sem expor dados pessoais."""

from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "perfilar_dados.py"


def importar(nome: str, caminho: Path):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


perfilar_dados = importar("perfilar_dados", SCRIPT)


# Nomes fictícios para montar um arquivo com dado pessoal sem depender do exemplo do projeto.
PRIMEIROS = ("Alana", "Bruno", "Carla", "Diego", "Elisa", "Fabio", "Gisele", "Heitor", "Iara", "Jonas",
             "Karina", "Lucas", "Marta", "Nilo", "Olivia", "Paulo")
SOBRENOMES = ("Araujo", "Barros", "Campos", "Dantas", "Esteves", "Freitas", "Gomes", "Holanda", "Ilha",
              "Jardim", "Lopes", "Moraes", "Nunes", "Pires", "Queiroz", "Rocha")


@pytest.fixture(scope="module")
def arquivo_pessoal(tmp_path_factory) -> Path:
    """CSV fictício no formato do Excel em português: ";" e UTF-8 com BOM, linhas separadoras
    de resumo no meio e as colunas NOME e TELEFONE com dado pessoal."""
    linhas = ["HORA;NOME;SITUACAO;TELEFONE"]
    for i, (primeiro, sobrenome) in enumerate((p, s) for p in PRIMEIROS for s in SOBRENOMES):
        if i % 50 == 0:
            linhas.append(f"RESUMO DIA {1 + i // 50:02d}/08/2025;;;")
        situacao = ("Feito", "Aberto", "Desfeito")[i % 3]
        linhas.append(f"{8 + i % 10:02d}:{i % 60:02d};{primeiro} {sobrenome};{situacao};(41) 90000-{i:04d}")
    caminho = tmp_path_factory.mktemp("perfil") / "arquivo_ficticio.csv"
    caminho.write_bytes(("\r\n".join(linhas) + "\r\n").encode("utf-8-sig"))
    return caminho


def rodar(*args: str) -> str:
    resultado = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    assert resultado.returncode == 0, resultado.stderr
    return resultado.stdout


def valores_pessoais(caminho: Path) -> set[str]:
    """Nomes e telefones do arquivo fictício, que nunca podem aparecer no perfil."""
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.reader(arquivo, delimiter=";"))[1:]
    pessoais = set()
    for linha in linhas:
        if not linha[0].startswith("RESUMO"):
            pessoais.update(v.strip() for v in (linha[1], linha[3]) if len(v.strip()) >= 5)
    return pessoais


def coluna(perfil: dict, nome: str) -> dict:
    return next(c for c in perfil["colunas"] if c["nome"] == nome)


def test_perfil_nao_expoe_nomes_nem_telefones(arquivo_pessoal):
    pessoais = valores_pessoais(arquivo_pessoal)
    assert len(pessoais) > 200
    for saida in (rodar(str(arquivo_pessoal)), rodar(str(arquivo_pessoal), "--json")):
        vazados = [valor for valor in pessoais if valor in saida]
        assert not vazados, f"o perfil expôs {len(vazados)} valores pessoais"


def test_detecta_colunas_sensiveis_e_sugere_mascara(arquivo_pessoal):
    perfil = perfilar_dados.perfilar(arquivo_pessoal)
    nome, telefone = coluna(perfil, "NOME"), coluna(perfil, "TELEFONE")
    assert nome["sensivel"] == "nome próprio" and nome["sugestao"] == "mascarar: hash"
    assert telefone["sensivel"] == "telefone" and telefone["sugestao"] == "mascarar: telefone"
    assert "valores_frequentes" not in nome and "valores_frequentes" not in telefone


def test_detecta_cpf_email_e_esconde_alta_cardinalidade(tmp_path):
    arquivo = tmp_path / "clientes.csv"
    linhas = ["documento,contato,segmento,codigo"]
    for i in range(40):
        segmento = "Varejo" if i % 2 else "Atacado"
        linhas.append(f"{i:03d}.456.789-{i % 100:02d},pessoa{i}@exemplo.com,{segmento},C{i:04d}")
    arquivo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    perfil = perfilar_dados.perfilar(arquivo)
    assert coluna(perfil, "documento")["sensivel"] == "cpf"
    assert coluna(perfil, "contato")["sensivel"] == "email"
    assert {v["valor"] for v in coluna(perfil, "segmento")["valores_frequentes"]} == {"Varejo", "Atacado"}
    assert coluna(perfil, "codigo")["valores_frequentes"] == "ocultos (alta cardinalidade)"
    saida = rodar(str(arquivo), "--json")
    assert "pessoa1@exemplo.com" not in saida and "001.456.789-01" not in saida
    assert json.loads(saida)["separador"] == ","


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("41 90000-1234", "99 99999-9999"), ("Maria Silva", "Aa+ Aa+"), ("MARIA SILVA", "A+ A+"), ("09:30", "99:99")],
)
def test_forma_esconde_o_conteudo(valor, esperado):
    assert perfilar_dados.forma(valor) == esperado


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("TOTAL", "A+"), ("RESUMO DIA 04/08/2025", "A+ A+ 9+/9+/9+"), ("Maria Silva", "A+ A+"), ("", "")],
)
def test_forma_geral_agrupa_linhas_da_mesma_estrutura(valor, esperado):
    assert perfilar_dados.forma_geral(valor) == esperado
