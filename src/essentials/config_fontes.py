"""Leitura e validação do config/fontes.yml e geração das expressões SQL da silver.

Não depende do Spark: é usado pelo pipeline (bronze.py e silver.py), pelos jobs de
ingestão e pelos testes. Toda a lógica que vem da configuração fica aqui, para que
os testes cubram exatamente o que roda no Databricks.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

CAMINHO_SCHEMA = Path(__file__).resolve().parents[2] / "config" / "fontes.schema.json"
FORMATOS_DATA_PADRAO = ["yyyy-MM-dd", "dd/MM/yyyy"]
FORMATOS_TIMESTAMP_PADRAO = ["yyyy-MM-dd HH:mm:ss", "dd/MM/yyyy HH:mm:ss", "dd/MM/yyyy HH:mm"]
FUNCOES_CAIXA = {"titulo": "initcap", "maiuscula": "upper", "minuscula": "lower"}
# Colunas que o Auto Loader cria e que não seguem para a silver.
COLUNAS_SO_DA_BRONZE = {"_rescued_data"}


def resolver_caminho(caminho: str | Path) -> Path:
    """No workspace, o bundle pode informar o caminho sem o prefixo /Workspace."""
    caminho = Path(caminho)
    com_prefixo = Path("/Workspace") / str(caminho).lstrip("/")
    if not caminho.exists() and str(caminho).startswith("/") and com_prefixo.exists():
        return com_prefixo
    return caminho


def carregar_fontes(caminho: str | Path) -> list[dict]:
    config = yaml.safe_load(resolver_caminho(caminho).read_text(encoding="utf-8"))
    validar_config(config)
    return config["fontes"]


def validar_config(config: dict) -> None:
    """Valida contra o JSON Schema e checa as regras que o schema não expressa."""
    schema = json.loads(CAMINHO_SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(config, schema)
    except jsonschema.ValidationError as erro:
        local = "/".join(str(parte) for parte in erro.absolute_path) or "raiz"
        raise ValueError(f"config/fontes.yml inválido em '{local}': {erro.message}") from erro

    erros = []
    nomes = [fonte["nome"] for fonte in config["fontes"]]
    repetidos = sorted({nome for nome in nomes if nomes.count(nome) > 1})
    if repetidos:
        erros.append(f"nomes de fonte repetidos: {', '.join(repetidos)}")

    for fonte in config["fontes"]:
        nome = fonte["nome"]
        banco = fonte.get("banco", {})
        if fonte["tipo"] == "banco" and fonte["modo_carga"] != "snapshot" and not banco.get("coluna_watermark"):
            erros.append(f"{nome}: banco em modo {fonte['modo_carga']} precisa de coluna_watermark")

        declaradas = set(fonte.get("colunas", {}))
        if not declaradas:
            continue
        usadas = set(fonte["chave_primaria"])
        for regra in fonte.get("regras", []):
            usadas.update(regra.get("colunas", []))
            if "coluna" in regra:
                usadas.add(regra["coluna"])
        faltando = sorted(coluna for coluna in usadas if coluna not in declaradas and not coluna.startswith("_"))
        if faltando:
            erros.append(f"{nome}: colunas usadas na chave ou nas regras, mas não declaradas: {', '.join(faltando)}")

    if erros:
        raise ValueError("config/fontes.yml inválido:\n- " + "\n- ".join(erros))


# Nomes e caminhos -----------------------------------------------------------------


def regras_unico(fonte: dict) -> list[dict]:
    return [regra for regra in fonte.get("regras", []) if regra["tipo"] == "unico"]


def tabelas_da_fonte(fonte: dict) -> dict:
    """Nomes de tudo o que o pipeline cria para uma fonte."""
    nome = fonte["nome"]
    return {
        "bronze": f"bronze_{nome}",
        "silver": f"silver_{nome}",
        "historico": f"silver_{nome}_historico" if fonte.get("historico") else None,
        "preparada": f"preparada_{nome}" if fonte.get("preparacao_sql") else None,
        "limpa": f"limpa_{nome}",
        "unicidade": [f"silver_{nome}_unico_{'_'.join(regra['colunas'])}" for regra in regras_unico(fonte)],
    }


def colunas_tecnicas(fonte: dict) -> list[str]:
    """Colunas técnicas que seguem da bronze até a silver."""
    colunas = ["_fonte", "_ingerido_em"]
    if fonte["tipo"] != "tabela":
        colunas.append("_arquivo_origem")
    return colunas


def pasta_landing(fonte: dict) -> str | None:
    if fonte["tipo"] == "arquivo":
        return fonte["arquivo"]["caminho"]
    if fonte["tipo"] in ("banco", "api"):
        return fonte[fonte["tipo"]]["pasta_landing"]
    return None


def formato_landing(fonte: dict) -> str | None:
    """Formato dos arquivos na landing: o do config, ou o que os jobs de ingestão gravam."""
    return {"arquivo": fonte.get("arquivo", {}).get("formato"), "banco": "parquet", "api": "json"}.get(fonte["tipo"])


def nome_tabela_origem(fonte: dict, catalogo: str) -> str:
    return fonte["tabela"]["nome_completo"].replace("{catalogo}", catalogo)


def propriedades_tabela(camada: str, fonte: dict) -> dict:
    return {"camada": camada, "fonte": fonte["nome"]}


# Regras de qualidade --------------------------------------------------------------


def literal_sql(valor) -> str:
    if isinstance(valor, int | float) and not isinstance(valor, bool):
        return str(valor)
    texto = str(valor).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{texto}'"


def expressao_regra(regra: dict) -> str | None:
    """Condição SQL que um registro válido satisfaz. A regra "unico" é checada à parte."""
    tipo = regra["tipo"]
    if tipo == "nao_nulo":
        return f"`{regra['coluna']}` IS NOT NULL"
    if tipo == "valores_aceitos":
        valores = ", ".join(literal_sql(valor) for valor in regra["valores"])
        return f"`{regra['coluna']}` IN ({valores})"
    if tipo == "expressao":
        return regra["expressao"]
    return None


def expectations(fonte: dict) -> tuple[dict, dict]:
    """Separa as regras em (descartar, alertar), no formato {nome: condição}."""
    descartar, alertar = {}, {}
    for regra in fonte.get("regras", []):
        condicao = expressao_regra(regra)
        if condicao is None:
            continue
        destino = descartar if regra["acao"] == "drop" else alertar
        destino[regra["nome"]] = condicao
    return descartar, alertar


# Limpeza padrão -------------------------------------------------------------------


def texto_limpo(expressao: str) -> str:
    """TRIM, um espaço só entre palavras e texto vazio vira nulo."""
    return f"nullif(trim(regexp_replace({expressao}, ' +', ' ')), '')"


def expressao_limpeza(coluna: str, configuracao: dict | None = None) -> str:
    """Expressão SQL que limpa e tipa uma coluna conforme o bloco "colunas" do config."""
    configuracao = configuracao or {}
    expressao = texto_limpo(f"CAST(`{coluna}` AS STRING)")

    if configuracao.get("remover_ponto_final"):
        expressao = texto_limpo(f"regexp_replace({expressao}, '[.]+$', '')")

    funcao_caixa = FUNCOES_CAIXA.get(configuracao.get("caixa"))
    if funcao_caixa:
        expressao = f"{funcao_caixa}({expressao})"

    mapa = configuracao.get("mapa_valores")
    if mapa:
        casos = " ".join(f"WHEN {literal_sql(de.lower())} THEN {literal_sql(para)}" for de, para in mapa.items())
        expressao = f"CASE lower({expressao}) {casos} ELSE {expressao} END"

    if "valor_se_vazio" in configuracao:
        expressao = f"coalesce({expressao}, {literal_sql(configuracao['valor_se_vazio'])})"

    mascara = configuracao.get("mascarar")
    if mascara == "telefone":
        digitos = f"regexp_replace({expressao}, '[^0-9]', '')"
        expressao = (
            f"CASE WHEN length({digitos}) IN (10, 11) "
            f"THEN concat('(', left({digitos}, 2), ') ****-', right({digitos}, 4)) END"
        )
    elif mascara == "hash":
        expressao = f"sha2({expressao}, 256)"

    tipo = configuracao.get("tipo", "texto")
    if tipo == "inteiro":
        return f"try_cast({expressao} AS BIGINT)"
    if tipo == "decimal":
        return f"try_cast({expressao} AS DECIMAL(18, 4))"
    if tipo == "data":
        formatos = configuracao.get("formatos", FORMATOS_DATA_PADRAO)
        tentativas = [f"CAST(try_to_timestamp({expressao}, {literal_sql(f)}) AS DATE)" for f in formatos]
        return f"coalesce({', '.join(tentativas)}, try_cast({expressao} AS DATE))"
    if tipo == "timestamp":
        formatos = configuracao.get("formatos", FORMATOS_TIMESTAMP_PADRAO)
        tentativas = [f"try_to_timestamp({expressao}, {literal_sql(f)})" for f in formatos]
        return f"coalesce({', '.join(tentativas)}, try_cast({expressao} AS TIMESTAMP))"
    if tipo == "booleano":
        return (
            f"CASE WHEN lower({expressao}) IN ('true', 'sim', 's', '1') THEN true "
            f"WHEN lower({expressao}) IN ('false', 'não', 'nao', 'n', '0') THEN false END"
        )
    return expressao


def expressoes_silver(fonte: dict, tipos_das_colunas: list[tuple[str, str]]) -> list[str]:
    """Lista de expressões para selectExpr, a partir de df.dtypes da origem.

    Colunas declaradas recebem a limpeza do config; as outras de texto recebem só
    TRIM; colunas técnicas (começam com _) e não textuais passam como estão.
    """
    declaradas = fonte.get("colunas", {})
    expressoes = []
    for coluna, tipo in tipos_das_colunas:
        if coluna in COLUNAS_SO_DA_BRONZE:
            continue
        if coluna in declaradas:
            expressoes.append(f"{expressao_limpeza(coluna, declaradas[coluna])} AS `{coluna}`")
        elif coluna.startswith("_") or tipo != "string":
            expressoes.append(f"`{coluna}`")
        else:
            expressoes.append(f"{texto_limpo(f'`{coluna}`')} AS `{coluna}`")
    return expressoes
