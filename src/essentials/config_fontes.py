"""Leitura e validação do config/fontes.yml e geração das expressões SQL da silver.

Não depende do Spark: é usado pelo pipeline (bronze.py e silver.py), pelos jobs de
ingestão e pelos testes. Toda a lógica que vem da configuração fica aqui, para que
os testes cubram exatamente o que roda no Databricks.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import yaml

CAMINHO_SCHEMA = Path(__file__).resolve().parents[2] / "config" / "fontes.schema.json"
FORMATOS_DATA_PADRAO = ["yyyy-MM-dd", "dd/MM/yyyy"]
FORMATOS_TIMESTAMP_PADRAO = ["yyyy-MM-dd HH:mm:ss", "dd/MM/yyyy HH:mm:ss", "dd/MM/yyyy HH:mm"]
FUNCOES_CAIXA = {"titulo": "initcap", "maiuscula": "upper", "minuscula": "lower"}
# Colunas que o Auto Loader cria e que não seguem para a silver.
COLUNAS_SO_DA_BRONZE = {"_rescued_data"}

# Padrão de nomes de colunas da silver e da gold: o prefixo diz a classe da informação
# e só aceita os tipos compatíveis. Ex.: dt_evento (data), st_pedido (status).
PREFIXOS_POR_TIPO = {
    "id": {"inteiro", "texto"},  # identificador / chave
    "cd": {"texto", "inteiro"},  # código
    "nm": {"texto"},  # nome
    "ds": {"texto"},  # descrição / texto livre
    "sg": {"texto"},  # sigla
    "st": {"texto"},  # status / situação
    "nr": {"texto", "inteiro"},  # número (telefone, documento)
    "qt": {"inteiro", "decimal"},  # quantidade / contagem
    "vl": {"decimal", "inteiro"},  # valor
    "pc": {"decimal"},  # percentual
    "dt": {"data"},  # data
    "dh": {"timestamp"},  # data e hora
    "hr": {"texto"},  # hora (hh:mm)
    "fl": {"booleano"},  # flag
}

# Tipo de cada tabela, gravado em TBLPROPERTIES ('tipo' = ...) e copiado para a tag "tipo"
# do Unity Catalog pela tarefa publicar_monitoramento. A silver com historico: true é do tipo
# historico (SCD tipo 2); sem historico, atual (SCD tipo 1).
TIPOS_DE_TABELA = {
    "bruta",
    "intermediaria",
    "atual",
    "historico",
    "dimensao",
    "fato",
    "agregada",
    "view",
    "observabilidade",
}

# Tabelas que um full refresh do pipeline não pode esvaziar: a bronze que lê a landing
# (o arquivo pode já ter saído de lá) e a silver SCD tipo 2 (não dá para refazer).
TIPOS_DE_FONTE_SEM_RESET_NA_BRONZE = {"arquivo", "banco", "api"}

# O retrato do snapshot (silver_int_<nome>_retrato) é uma materialized view privada do
# pipeline: não é publicada no catálogo, só alimenta o AUTO CDC. Plano B, se o AUTO CDC FROM
# SNAPSHOT não aceitar a origem privada: False, e o retrato volta a ser publicado na silver.
RETRATO_PRIVADO = True

# Dicionário de dados: tipo SQL de cada tipo do fontes.yml e descrição das colunas que o
# pipeline cria. Viram o schema (com COMMENT por coluna) das tabelas da silver.
TIPOS_SQL = {
    "texto": "STRING",
    "inteiro": "BIGINT",
    "decimal": "DECIMAL(18,4)",
    "data": "DATE",
    "timestamp": "TIMESTAMP",
    "booleano": "BOOLEAN",
}
COLUNAS_TECNICAS = {
    "_fonte": ("STRING", "Nome da fonte no config/fontes.yml que originou o registro."),
    "_arquivo_origem": ("STRING", "Caminho do arquivo na landing zone de onde o registro veio."),
    "_modificado_em": ("TIMESTAMP", "Data e hora da última modificação do arquivo na landing zone."),
    "_ingerido_em": ("TIMESTAMP", "Momento em que o registro foi carregado na bronze."),
}
# Colunas técnicas que só existem quando o dado chega por arquivo (não na fonte tabela).
COLUNAS_TECNICAS_DE_ARQUIVO = {"_arquivo_origem", "_modificado_em"}
# Colunas do change data feed do Delta (fonte tabela em modo cdc); não entram na silver.
COLUNAS_CDF = {"_change_type": "STRING", "_commit_version": "BIGINT", "_commit_timestamp": "TIMESTAMP"}
COLUNAS_SCD2 = {
    "__START_AT": "Início da vigência desta versão do registro.",
    "__END_AT": "Fim da vigência desta versão do registro; vazio na versão atual.",
}


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

        colunas = fonte.get("colunas", {})
        for coluna, configuracao in colunas.items():
            prefixo = coluna.split("_", 1)[0]
            aceitos = PREFIXOS_POR_TIPO.get(prefixo)
            if aceitos is None:
                erros.append(f"{nome}: coluna {coluna} sem prefixo conhecido ({', '.join(PREFIXOS_POR_TIPO)})")
            elif configuracao["tipo"] not in aceitos:
                erros.append(
                    f"{nome}: coluna {coluna} é do tipo {configuracao['tipo']}, "
                    f"mas o prefixo {prefixo}_ aceita só {', '.join(sorted(aceitos))}"
                )
        origens = [configuracao["origem"] for configuracao in colunas.values()]
        origens_repetidas = sorted({origem for origem in origens if origens.count(origem) > 1})
        if origens_repetidas:
            erros.append(f"{nome}: mais de uma coluna com a mesma origem: {', '.join(origens_repetidas)}")
        mascaradas_sem_flag = sorted(
            coluna
            for coluna, configuracao in colunas.items()
            if configuracao.get("mascarar") and not configuracao.get("sensivel")
        )
        if mascaradas_sem_flag:
            erros.append(f"{nome}: coluna com mascarar precisa de sensivel: true: {', '.join(mascaradas_sem_flag)}")

        if fonte["modo_carga"] in ("snapshot", "cdc"):
            # O AUTO CDC não aceita chave nula: a regra nao_nulo da chave (declarada ou gerada
            # por regras_efetivas) precisa barrar a linha, não só alertar.
            so_alerta = sorted(
                regra["coluna"]
                for regra in fonte.get("regras", [])
                if regra["tipo"] == "nao_nulo"
                and regra["coluna"] in fonte["chave_primaria"]
                and regra["acao"] == "alerta"
            )
            if so_alerta:
                erros.append(f"{nome}: regra nao_nulo da chave precisa de drop ou falhar: {', '.join(so_alerta)}")

        erros += erros_data_referencia(fonte)

        declaradas = set(colunas)
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


def regras_efetivas(fonte: dict) -> list[dict]:
    """Regras declaradas no YAML mais as regras padrão da chave, geradas quando faltam.

    - nao_nulo com drop em cada coluna da chave_primaria que não tem regra nao_nulo;
    - unico (alerta) na chave inteira, só no modo incremental: nos modos snapshot e cdc a
      chave já sai única (o retrato guarda a versão mais recente e o AUTO CDC garante).
    """
    declaradas = list(fonte.get("regras", []))
    chave = fonte.get("chave_primaria", [])
    com_nao_nulo = {regra["coluna"] for regra in declaradas if regra["tipo"] == "nao_nulo"}
    geradas = [
        {"nome": f"chave_{coluna}_preenchida", "tipo": "nao_nulo", "coluna": coluna, "acao": "drop"}
        for coluna in chave
        if coluna not in com_nao_nulo
    ]
    tem_unico_da_chave = any(
        regra["tipo"] == "unico" and set(regra["colunas"]) == set(chave) for regra in declaradas
    )
    if chave and fonte["modo_carga"] == "incremental" and not tem_unico_da_chave:
        geradas.append({"nome": "chave_unica", "tipo": "unico", "colunas": list(chave), "acao": "alerta"})
    return declaradas + geradas


def regras_unico(fonte: dict) -> list[dict]:
    return [regra for regra in regras_efetivas(fonte) if regra["tipo"] == "unico"]


def tabelas_da_fonte(fonte: dict) -> dict:
    """Nomes de tudo o que o pipeline cria para uma fonte, no padrão camada_tipo_nome.

    validada: tabela intermediária onde as regras de qualidade são aplicadas antes do
    AUTO CDC (retrato no modo snapshot, mudanças no modo cdc). No modo incremental as
    regras ficam na própria silver_<nome>.
    silver: com historico: true, a silver_<nome> é a SCD tipo 2 (__START_AT e __END_AT);
    sem historico, SCD tipo 1 (estado atual).
    """
    nome = fonte["nome"]
    validada = {"snapshot": f"silver_int_{nome}_retrato", "cdc": f"silver_int_{nome}_mudancas"}
    return {
        "bronze": f"bronze_{nome}",
        "preparada": f"silver_int_{nome}_preparada" if fonte.get("preparacao_sql") else None,
        "validada": validada.get(fonte["modo_carga"]),
        "silver": f"silver_{nome}",
        "unicidade": [f"silver_int_{nome}_unico_{'_'.join(regra['colunas'])}" for regra in regras_unico(fonte)],
    }


def validada_publicada(fonte: dict) -> bool:
    """A tabela intermediária das regras aparece no catálogo? O retrato do snapshot, não."""
    return fonte["modo_carga"] == "cdc" or (fonte["modo_carga"] == "snapshot" and not RETRATO_PRIVADO)


def tem_historico(fonte: dict) -> bool:
    """historico: true faz da silver_<nome> uma SCD tipo 2 (só nos modos snapshot e cdc)."""
    return bool(fonte.get("historico")) and fonte["modo_carga"] in ("snapshot", "cdc")


def tipo_da_silver(fonte: dict) -> str:
    """Tipo da silver_<nome> em TBLPROPERTIES: historico (SCD tipo 2) ou atual."""
    return "historico" if tem_historico(fonte) else "atual"


def filtro_versao_atual(fonte: dict) -> str | None:
    """Condição que deixa só a versão vigente de cada registro na silver SCD tipo 2."""
    return "__END_AT IS NULL" if tem_historico(fonte) else None


def colunas_tecnicas(fonte: dict) -> list[str]:
    """Colunas técnicas que seguem da bronze até a silver (fonte tabela não tem arquivo)."""
    return [
        coluna for coluna in COLUNAS_TECNICAS if coluna not in COLUNAS_TECNICAS_DE_ARQUIVO or fonte["tipo"] != "tabela"
    ]


def colunas_silver(fonte: dict) -> list[str]:
    """Contrato da silver, na ordem: colunas declaradas no YAML e depois as técnicas."""
    return [*fonte["colunas"], *colunas_tecnicas(fonte)]


def colunas_sensiveis(fonte: dict) -> list[str]:
    """Colunas com dado pessoal (sensivel: true): recebem a tag pii e, na gold, a máscara."""
    return [coluna for coluna, configuracao in fonte["colunas"].items() if configuracao.get("sensivel")]


def tipo_sql(fonte: dict, coluna: str) -> str:
    if coluna in fonte["colunas"]:
        return TIPOS_SQL[fonte["colunas"][coluna]["tipo"]]
    if coluna in COLUNAS_TECNICAS:
        return COLUNAS_TECNICAS[coluna][0]
    if coluna in COLUNAS_CDF:
        return COLUNAS_CDF[coluna]
    raise ValueError(f"{fonte['nome']}: coluna {coluna} não está no contrato da silver")


def colunas_extras_cdc(fonte: dict) -> list[str]:
    """Colunas que o AUTO CDC usa (operação, sequência, change data feed), mas não grava."""
    extras = [fonte["cdc"]["coluna_operacao"]]
    if fonte["tipo"] == "tabela":
        extras += ["_commit_version", "_commit_timestamp"]
    if fonte["coluna_atualizacao"] not in colunas_silver(fonte):
        extras.append(fonte["coluna_atualizacao"])
    return list(dict.fromkeys(coluna for coluna in extras if coluna not in colunas_silver(fonte)))


def descricao_coluna(fonte: dict, coluna: str) -> str:
    if coluna in fonte["colunas"]:
        return fonte["colunas"][coluna]["descricao"]
    return COLUNAS_TECNICAS[coluna][1]


def schema_silver(fonte: dict, inicio_scd2: str | None = None) -> str:
    """Schema DDL da silver com COMMENT em cada coluna: o dicionário de dados no Unity Catalog.

    inicio_scd2: tipo SQL de __START_AT/__END_AT, para a silver SCD tipo 2 (historico: true).
    """
    partes = [
        f"`{coluna}` {tipo_sql(fonte, coluna)} COMMENT {literal_sql(descricao_coluna(fonte, coluna))}"
        for coluna in colunas_silver(fonte)
    ]
    if inicio_scd2:
        partes += [f"`{coluna}` {inicio_scd2} COMMENT {literal_sql(texto)}" for coluna, texto in COLUNAS_SCD2.items()]
    return ", ".join(partes)


def pasta_landing(fonte: dict) -> str | None:
    if fonte["tipo"] == "arquivo":
        return fonte["arquivo"]["caminho"]
    if fonte["tipo"] in ("banco", "api"):
        return fonte[fonte["tipo"]]["pasta_landing"]
    return None


def formato_landing(fonte: dict) -> str | None:
    """Formato dos arquivos na landing: o do config, ou o que os jobs de ingestão gravam."""
    return {"arquivo": fonte.get("arquivo", {}).get("formato"), "banco": "parquet", "api": "json"}.get(fonte["tipo"])


def nome_tabela_origem(fonte: dict, catalogo: str, projeto: str) -> str:
    """Troca os marcadores {catalogo} e {projeto} pelos valores do target."""
    return fonte["tabela"]["nome_completo"].replace("{catalogo}", catalogo).replace("{projeto}", projeto)


def bloqueia_reset(camada: str, tipo: str, fonte: dict) -> bool:
    """Bronze de arquivo, banco ou api e silver SCD 2: um full refresh não as esvazia."""
    bronze_da_landing = camada == "bronze" and fonte["tipo"] in TIPOS_DE_FONTE_SEM_RESET_NA_BRONZE
    return bronze_da_landing or tipo == "historico"


def propriedades_tabela(camada: str, tipo: str, fonte: dict) -> dict:
    if tipo not in TIPOS_DE_TABELA:
        raise ValueError(f"tipo de tabela desconhecido: {tipo}")
    propriedades = {"camada": camada, "tipo": tipo, "fonte": fonte["nome"]}
    if bloqueia_reset(camada, tipo, fonte):
        propriedades["pipelines.reset.allowed"] = "false"
    return propriedades


# Data de referência do snapshot ----------------------------------------------------


# Desempate do retrato depois da data de referência, do mais recente para o mais antigo:
# determinístico mesmo quando vários arquivos chegam no mesmo micro-batch (mesmo _ingerido_em).
# A modificação do arquivo (quando chegou à landing) vem antes da ingestão: arquivos enviados
# juntos podem cair em micro-batches diferentes, e aí o _ingerido_em não segue a ordem de envio.
ORDEM_DO_RETRATO = ("_modificado_em", "_ingerido_em", "_arquivo_origem")


def expressao_data_referencia(fonte: dict) -> str | None:
    """Expressão SQL agregada que dá a data de referência de cada arquivo de um snapshot.

    É calculada por arquivo (agrupando por _arquivo_origem), sobre as colunas já com os
    nomes padronizados. O retrato é o arquivo com a maior data; empate ou data nula
    (nulos por último) desempata pelo momento da ingestão, pela modificação do arquivo e
    pelo nome do arquivo (ORDEM_DO_RETRATO).
      ingestao (padrão) -> None: vale o último arquivo ingerido, como antes
      conteudo          -> a expressão do YAML, ex.: max(dt_evento)
      nome_arquivo      -> a data extraída do nome do arquivo (grupo 1 da regex) no formato
    """
    referencia = fonte.get("data_referencia") or {"tipo": "ingestao"}
    if referencia["tipo"] == "conteudo":
        return referencia["expressao"]
    if referencia["tipo"] == "nome_arquivo":
        nome = "element_at(split(_arquivo_origem, '/'), -1)"
        trecho = f"regexp_extract({nome}, {literal_sql(referencia['regex'])}, 1)"
        return f"max(CAST(try_to_timestamp(nullif({trecho}, ''), {literal_sql(referencia['formato'])}) AS DATE))"
    return None


def erros_data_referencia(fonte: dict) -> list[str]:
    """O que o JSON Schema não confere no campo data_referencia."""
    referencia = fonte.get("data_referencia")
    if not referencia or referencia["tipo"] == "ingestao":
        return []
    nome = fonte["nome"]
    erros = []
    if fonte["modo_carga"] != "snapshot" or fonte["tipo"] == "tabela":
        erros.append(f"{nome}: data_referencia só vale no modo snapshot com arquivos (tipo arquivo, banco ou api)")
    if referencia["tipo"] == "nome_arquivo":
        try:
            grupos = re.compile(referencia["regex"]).groups
        except re.error as erro:
            erros.append(f"{nome}: regex de data_referencia inválida: {erro}")
        else:
            if grupos != 1:
                erros.append(f"{nome}: regex de data_referencia precisa de exatamente um grupo (a data); tem {grupos}")
    return erros


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


def expectations(fonte: dict) -> tuple[dict, dict, dict]:
    """Separa as regras efetivas em (descartar, alertar, falhar), no formato {nome: condição}.

    falhar para a atualização inteira: a carga do dia não acontece e o aviso de falha
    dispara (a mensagem do motor traz o registro, por isso nunca é repassada como está).
    """
    destinos = {"drop": {}, "alerta": {}, "falhar": {}}
    for regra in regras_efetivas(fonte):
        condicao = expressao_regra(regra)
        if condicao is not None:
            destinos[regra["acao"]][regra["nome"]] = condicao
    return destinos["drop"], destinos["alerta"], destinos["falhar"]


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

    A silver tem contrato explícito: só entram as colunas declaradas no bloco "colunas"
    (com limpeza, tipo, nome padronizado e descrição) e as técnicas (começam com _).
    Colunas da origem que não foram declaradas ficam só na bronze.
    """
    por_origem = {configuracao["origem"]: (nome, configuracao) for nome, configuracao in fonte["colunas"].items()}
    expressoes = []
    for coluna, _tipo in tipos_das_colunas:
        if coluna in COLUNAS_SO_DA_BRONZE:
            continue
        if coluna in por_origem:
            nome, configuracao = por_origem[coluna]
            expressoes.append(f"{expressao_limpeza(coluna, configuracao)} AS `{nome}`")
        elif coluna.startswith("_"):
            expressoes.append(f"`{coluna}`")
    return expressoes
