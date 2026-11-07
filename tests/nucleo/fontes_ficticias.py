"""Fontes fictícias e genéricas para os testes do núcleo, fora do config/fontes.yml do projeto.

O núcleo não pode depender do cliente: os testes do motor usam só estas fontes. Juntas, elas
cobrem os caminhos do código:
  EVENTOS   arquivo de texto, snapshot com histórico (SCD tipo 2), preparação em SQL, data de
            referência pelo conteúdo, colunas sensíveis (uma mascarada) e regras de todo tipo;
  CADASTRO  fonte do tipo tabela (sem arquivo), snapshot sem histórico (SCD tipo 1) e regra
            "unico".
Nenhum dado aqui é real, e nenhum nome vem do projeto (tests/nucleo/test_nucleo_sem_projeto.py).
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

EVENTOS = {
    "nome": "eventos",
    "descricao": "Eventos fictícios de um arquivo de texto, só para os testes do núcleo.",
    "tipo": "arquivo",
    "arquivo": {"formato": "texto", "caminho": "eventos", "opcoes": {"wholeText": "true"}},
    "modo_carga": "snapshot",
    "historico": True,
    "preparacao_sql": True,
    "chave_primaria": ["dt_evento", "nm_pessoa"],
    "coluna_atualizacao": "_linha",
    "data_referencia": {"tipo": "conteudo", "expressao": "max(dt_evento)"},
    "colunas": {
        "dt_evento": {
            "origem": "data",
            "descricao": "Data do evento, tirada do arquivo.",
            "tipo": "data",
            "formatos": ["dd/MM/yyyy", "yyyy-MM-dd"],
        },
        "hr_evento": {"origem": "hora", "descricao": "Hora do evento no formato HH:mm.", "tipo": "texto"},
        "nm_pessoa": {
            "origem": "pessoa",
            "descricao": "Nome da pessoa do evento, com as iniciais maiúsculas.",
            "sensivel": True,
            "tipo": "texto",
            "caixa": "titulo",
            "remover_ponto_final": True,
        },
        "nr_contato": {
            "origem": "contato",
            "descricao": "Telefone de contato mascarado (DDD e 4 últimos dígitos).",
            "sensivel": True,
            "tipo": "texto",
            "mascarar": "telefone",
        },
        "st_evento": {
            "origem": "estado",
            "descricao": "Estado do evento padronizado (Feito, Desfeito ou Aberto).",
            "tipo": "texto",
            "remover_ponto_final": True,
            "valor_se_vazio": "Aberto",
            "mapa_valores": {"feito": "Feito", "feita": "Feito", "desfeito": "Desfeito"},
        },
    },
    "regras": [
        {"nome": "pessoa_preenchida", "tipo": "nao_nulo", "coluna": "nm_pessoa", "acao": "drop"},
        {"nome": "data_do_evento_preenchida", "tipo": "nao_nulo", "coluna": "dt_evento", "acao": "drop"},
        {
            "nome": "estado_conhecido",
            "tipo": "valores_aceitos",
            "coluna": "st_evento",
            "valores": ["Feito", "Desfeito", "Aberto"],
            "acao": "alerta",
        },
        {"nome": "contato_preenchido", "tipo": "nao_nulo", "coluna": "nr_contato", "acao": "alerta"},
        {
            "nome": "hora_no_formato",
            "tipo": "expressao",
            "expressao": "hr_evento RLIKE '^[0-9]{1,2}:[0-9]{2}$'",
            "acao": "alerta",
        },
        {
            "nome": "data_recente",
            "tipo": "expressao",
            "expressao": "dt_evento IS NULL OR dt_evento >= DATE'2000-01-01'",
            "acao": "falhar",
        },
    ],
}

CADASTRO = {
    "nome": "cadastro",
    "descricao": "Cadastro fictício que liga um prefixo a um grupo, só para os testes.",
    "tipo": "tabela",
    "tabela": {"nome_completo": "{catalogo}.{projeto}_origem.cadastro"},
    "modo_carga": "snapshot",
    "historico": False,
    "chave_primaria": ["id_item"],
    "coluna_atualizacao": "dh_atualizacao",
    "colunas": {
        "id_item": {"origem": "id_item", "descricao": "Identificador do item no cadastro.", "tipo": "inteiro"},
        "ds_prefixo": {
            "origem": "prefixo",
            "descricao": "Começo do nome, em minúsculas.",
            "tipo": "texto",
            "caixa": "minuscula",
        },
        "nm_grupo": {"origem": "grupo", "descricao": "Grupo ao qual o item pertence.", "tipo": "texto"},
        "dh_atualizacao": {
            "origem": "atualizado_em",
            "descricao": "Data e hora da última alteração na origem.",
            "tipo": "timestamp",
        },
    },
    "regras": [
        {"nome": "prefixo_unico", "tipo": "unico", "colunas": ["ds_prefixo"], "acao": "alerta"},
    ],
}


def eventos(**campos) -> dict:
    """Cópia de EVENTOS, com os campos trocados."""
    fonte = copy.deepcopy(EVENTOS)
    fonte.update(campos)
    return fonte


def cadastro(**campos) -> dict:
    """Cópia do CADASTRO, com os campos trocados."""
    fonte = copy.deepcopy(CADASTRO)
    fonte.update(campos)
    return fonte


def config_ficticia() -> dict:
    """Um fontes.yml fictício (como dicionário), com a fonte EVENTOS."""
    return {"fontes": [eventos()]}


def gravar_config(pasta: Path, *fontes: dict) -> Path:
    """Grava um fontes.yml fictício em pasta e devolve o caminho (EVENTOS, se nada for passado)."""
    caminho = pasta / "fontes.yml"
    conteudo = {"fontes": [copy.deepcopy(fonte) for fonte in fontes] or [eventos()]}
    caminho.write_text(yaml.safe_dump(conteudo, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return caminho
