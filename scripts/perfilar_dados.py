"""Perfil de um arquivo de dados sem expor dados pessoais.

Para adaptar o projeto a um cliente, o modelo precisa entender a ESTRUTURA dos dados,
não o conteúdo. Este script imprime só metadados:

- codificação, BOM, separador, quebra de linha e contagem de linhas;
- linhas estruturais (separadores, totais, cabeçalhos repetidos), descritas pela forma;
- por coluna: tipo inferido, % de nulos, distintos, tamanhos e padrões de formato
  (letras viram A/a, dígitos viram 9: "41 90000-1234" vira "99 99999-9999");
- valores mais frequentes SÓ em colunas não sensíveis de baixa cardinalidade;
- detecção de dados pessoais (CPF, CNPJ, telefone, e-mail, nome próprio), com a
  sugestão de "mascarar" para o config/fontes.yml.

Nenhum valor de coluna sensível ou de alta cardinalidade é exibido.

Uso:
    python scripts/perfilar_dados.py data/privado/arquivo.csv
    python scripts/perfilar_dados.py arquivo.csv --separador ";" --json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

SEPARADORES_POSSIVEIS = [";", ",", "\t", "|"]
MAX_CATEGORIAS_PADRAO = 30
NOMES_SENSIVEIS = re.compile(
    r"nome|name|telefone|celular|fone|phone|whats|cpf|cnpj|rg\b|e-?mail|endere|logradouro|cep\b|nascimento",
    re.IGNORECASE,
)
PADROES_SENSIVEIS = {
    "cpf": re.compile(r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$"),
    "cnpj": re.compile(r"^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$"),
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "telefone": re.compile(r"^(\+?55\s?)?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}$|^\d,\d+E\+\d+$", re.IGNORECASE),
}
FORMATOS_DATA = {
    "dd/MM/yyyy": re.compile(r"^\d{2}/\d{2}/\d{4}$"),
    "yyyy-MM-dd": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "dd-MM-yyyy": re.compile(r"^\d{2}-\d{2}-\d{4}$"),
}


def forma(valor: str) -> str:
    """Padrão de formato: maiúscula vira A, minúscula vira a, dígito vira 9."""
    texto = []
    for caractere in valor:
        if caractere.isdigit():
            texto.append("9")
        elif caractere.isalpha():
            texto.append("A" if caractere.isupper() else "a")
        else:
            texto.append(caractere)
    # Sequências de letras viram "a+" ou "A+", para o padrão não revelar o tamanho de cada palavra.
    return re.sub(r"A{2,}", "A+", re.sub(r"a{2,}", "a+", "".join(texto)))


def forma_geral(valor: str) -> str:
    """Forma resumida (9+, A+, Aa+), para agrupar linhas da mesma estrutura."""
    if not valor.strip():
        return ""
    return re.sub(r"9+", "9+", re.sub(r"[Aa][Aa+]*", "A+", forma(valor)))


def ler_texto(caminho: Path) -> tuple[str, dict]:
    bruto = caminho.read_bytes()
    info = {"bom_utf8": bruto.startswith(b"\xef\xbb\xbf")}
    try:
        texto = bruto.decode("utf-8-sig")
        info["codificacao"] = "utf-8"
    except UnicodeDecodeError:
        texto = bruto.decode("cp1252")
        info["codificacao"] = "cp1252 (Windows-1252)"
    crlf = bruto.count(b"\r\n")
    info["quebra_de_linha"] = "CRLF" if crlf and crlf == bruto.count(b"\n") else ("misturada" if crlf else "LF")
    return texto, info


def detectar_separador(linhas: list[str]) -> str:
    amostra = [linha for linha in linhas[:200] if linha.strip()]
    contagens = {sep: Counter(linha.count(sep) for linha in amostra) for sep in SEPARADORES_POSSIVEIS}
    melhor, melhor_pontuacao = ",", 0
    for sep, contagem in contagens.items():
        quantidade, vezes = contagem.most_common(1)[0] if contagem else (0, 0)
        if quantidade and vezes > melhor_pontuacao:
            melhor, melhor_pontuacao = sep, vezes
    return melhor


def inferir_tipo(valores: list[str]) -> str:
    if not valores:
        return "vazia"
    if all(re.fullmatch(r"-?\d+", v) for v in valores):
        return "inteiro"
    if all(re.fullmatch(r"-?\d+\.\d+", v) for v in valores):
        return "decimal"
    if all(re.fullmatch(r"-?\d{1,3}(\.\d{3})*,\d+|-?\d+,\d+", v) for v in valores):
        return "decimal (formato brasileiro 1.234,56)"
    for nome, padrao in FORMATOS_DATA.items():
        if sum(bool(padrao.match(v)) for v in valores) >= 0.9 * len(valores):
            return f"data ({nome})"
    if sum(bool(re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", v)) for v in valores) >= 0.9 * len(valores):
        return "hora (HH:mm)"
    return "texto"


def detectar_sensivel(nome: str, valores: list[str]) -> str | None:
    if not valores:
        return "nome da coluna" if NOMES_SENSIVEIS.search(nome) else None
    tipos = [
        tipo
        for tipo, padrao in PADROES_SENSIVEIS.items()
        if sum(bool(padrao.match(v.strip())) for v in valores) >= 0.3 * len(valores)
    ]
    if tipos:
        # 11 dígitos servem para CPF e para celular: o nome da coluna desempata.
        if "telefone" in tipos and re.search(r"fone|cel|phone|whats", nome, re.IGNORECASE):
            return "telefone"
        if "cpf" in tipos and "telefone" in tipos and not re.search(r"cpf", nome, re.IGNORECASE):
            return "telefone ou cpf"
        return tipos[0]
    palavras = [v.split() for v in valores]
    parece_nome = sum(
        len(p) >= 2 and all(re.fullmatch(r"[^\W\d_]+\.?", t) for t in p) for p in palavras
    ) >= 0.6 * len(valores)
    if parece_nome and len(set(valores)) >= 0.5 * len(valores):
        return "nome próprio"
    if NOMES_SENSIVEIS.search(nome):
        return "nome da coluna"
    return None


def perfilar(caminho: Path, separador: str | None = None, max_categorias: int = MAX_CATEGORIAS_PADRAO) -> dict:
    texto, info = ler_texto(caminho)
    linhas = texto.splitlines()
    separador = separador or detectar_separador(linhas)
    registros = list(csv.reader(io.StringIO("\n".join(linhas)), delimiter=separador))
    cabecalho, corpo = (registros[0], registros[1:]) if registros else ([], [])

    vazias = [r for r in corpo if not any(c.strip() for c in r)]
    preenchidas = [r for r in corpo if any(c.strip() for c in r)]
    # A forma resumida da 1ª coluna mais comum define as linhas de dados; outras formas
    # (com a 1ª coluna preenchida) são linhas estruturais: separadores, totais etc.
    formas = Counter(forma_geral(r[0]) for r in preenchidas if r and r[0].strip())
    forma_dados = formas.most_common(1)[0][0] if formas else ""
    estruturais = [r for r in preenchidas if r and r[0].strip() and forma_geral(r[0]) != forma_dados]
    dados = [r for r in preenchidas if r not in estruturais]

    perfil = {
        "arquivo": caminho.name,
        **info,
        "separador": {"\t": "TAB"}.get(separador, separador),
        "linhas_total": len(linhas),
        "linhas_dados": len(dados),
        "linhas_vazias": len(vazias),
        "cabecalho": cabecalho,
        "linhas_estruturais": _descrever_estruturais(estruturais),
        "colunas": [],
    }
    for indice, nome in enumerate(cabecalho):
        valores = [r[indice].strip() for r in dados if indice < len(r) and r[indice].strip()]
        perfil["colunas"].append(_perfil_coluna(nome or f"coluna_{indice + 1}", valores, len(dados), max_categorias))
    largura = Counter(len(r) for r in dados)
    if len(largura) > 1:
        perfil["aviso_largura"] = f"linhas com quantidades diferentes de campos: {dict(largura)}"
    return perfil


def _descrever_estruturais(linhas: list[list[str]]) -> list[dict]:
    grupos: dict[str, list[list[str]]] = {}
    for linha in linhas:
        grupos.setdefault(forma_geral(linha[0]), []).append(linha)
    descricao = []
    for forma_grupo, membros in grupos.items():
        # Só palavras repetidas em muitas linhas aparecem por extenso: são rótulos, não pessoas.
        palavras = Counter(t for m in membros for t in set(re.findall(r"[^\W\d_]{3,}", m[0])))
        rotulos = [p for p, n in palavras.items() if n >= max(3, len(membros) // 2)]
        descricao.append(
            {
                "forma_primeira_coluna": forma(membros[0][0]) if rotulos else forma_grupo,
                "rotulos_repetidos": sorted(rotulos),
                "campos_preenchidos": sorted({sum(bool(c.strip()) for c in m) for m in membros}),
                "quantidade": len(membros),
            }
        )
    return descricao


def _perfil_coluna(nome: str, valores: list[str], total: int, max_categorias: int) -> dict:
    sensivel = detectar_sensivel(nome, valores)
    distintos = len(set(valores))
    coluna = {
        "nome": nome,
        "tipo_inferido": inferir_tipo(valores),
        "pc_nulos": round(100 * (total - len(valores)) / total, 1) if total else 0.0,
        "distintos": distintos,
        "tamanho_min": min((len(v) for v in valores), default=0),
        "tamanho_max": max((len(v) for v in valores), default=0),
        "padroes": [{"forma": f, "quantidade": n} for f, n in Counter(forma(v) for v in valores).most_common(5)],
        "sensivel": sensivel,
    }
    if sensivel:
        coluna["sugestao"] = "mascarar: telefone" if sensivel == "telefone" else "mascarar: hash"
    elif distintos <= max_categorias:
        coluna["valores_frequentes"] = [{"valor": v, "quantidade": n} for v, n in Counter(valores).most_common()]
    else:
        coluna["valores_frequentes"] = "ocultos (alta cardinalidade)"
    return coluna


def imprimir(perfil: dict) -> None:
    print(f"# Perfil de {perfil['arquivo']}\n")
    print(f"- Codificação: {perfil['codificacao']} | BOM UTF-8: {'sim' if perfil['bom_utf8'] else 'não'}")
    print(f"- Separador: `{perfil['separador']}` | Quebra de linha: {perfil['quebra_de_linha']}")
    print(
        f"- Linhas: {perfil['linhas_total']} no total, {perfil['linhas_dados']} de dados, "
        f"{perfil['linhas_vazias']} vazias"
    )
    print(f"- Cabeçalho: {perfil['cabecalho']}")
    if perfil.get("aviso_largura"):
        print(f"- Atenção: {perfil['aviso_largura']}")
    if perfil["linhas_estruturais"]:
        print("\n## Linhas estruturais (fora do padrão de dados)\n")
        for grupo in perfil["linhas_estruturais"]:
            print(
                f"- {grupo['quantidade']} linhas com a 1ª coluna na forma `{grupo['forma_primeira_coluna']}`, "
                f"rótulos {grupo['rotulos_repetidos']}, campos preenchidos {grupo['campos_preenchidos']}"
            )
    print("\n## Colunas\n")
    for coluna in perfil["colunas"]:
        print(f"### {coluna['nome']}")
        print(
            f"- Tipo: {coluna['tipo_inferido']} | Nulos: {coluna['pc_nulos']}% | Distintos: {coluna['distintos']}"
            f" | Tamanho: {coluna['tamanho_min']} a {coluna['tamanho_max']}"
        )
        print("- Padrões: " + ", ".join(f"`{p['forma']}` ({p['quantidade']})" for p in coluna["padroes"]))
        if coluna["sensivel"]:
            print(f"- **SENSÍVEL** ({coluna['sensivel']}): valores ocultos. Sugestão: `{coluna['sugestao']}`")
        elif isinstance(coluna["valores_frequentes"], list):
            valores = coluna["valores_frequentes"]
            texto = ", ".join(f"`{v['valor']}` ({v['quantidade']})" for v in valores)
            print(f"- Valores: {texto or 'nenhum'}")
        else:
            print(f"- Valores: {coluna['valores_frequentes']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Perfil de um arquivo de dados sem expor dados pessoais.")
    parser.add_argument("arquivo", type=Path)
    parser.add_argument("--separador", help="separador de campos; se omitido, é detectado")
    parser.add_argument("--max-categorias", type=int, default=MAX_CATEGORIAS_PADRAO)
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    args = parser.parse_args()
    if args.arquivo.suffix.lower() in (".xlsx", ".xls"):
        sys.exit("Excel ainda não é suportado: salve a planilha como CSV (UTF-8) e perfile o CSV.")
    sys.stdout.reconfigure(encoding="utf-8")
    perfil = perfilar(args.arquivo, args.separador, args.max_categorias)
    if args.json:
        print(json.dumps(perfil, ensure_ascii=False, indent=2))
    else:
        imprimir(perfil)


if __name__ == "__main__":
    main()
