"""Fontes fictícias para os testes de unidade, fora do config/fontes.yml do exemplo.

O exemplo só tem a agenda (arquivo, snapshot, SCD tipo 2). Estas fontes mantêm coberto o
código dos outros caminhos: fonte do tipo tabela (sem arquivo), snapshot sem histórico
(SCD tipo 1) e regra "unico". Nenhum dado aqui é real.
"""

from __future__ import annotations

import copy

CADASTRO = {
    "nome": "cadastro",
    "descricao": "Cadastro fictício que liga um prefixo a uma área, só para os testes.",
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
        "nm_area": {"origem": "area", "descricao": "Área à qual o item pertence.", "tipo": "texto"},
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


def cadastro(**campos) -> dict:
    """Cópia do CADASTRO, com os campos trocados."""
    fonte = copy.deepcopy(CADASTRO)
    fonte.update(campos)
    return fonte
