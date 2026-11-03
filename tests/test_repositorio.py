"""Testes da segurança e da cadeia de suprimentos do repositório (Fase 2).

Garantem por código o que a revisão humana esqueceria: actions fixadas por SHA,
dependências com versão, permissões mínimas nos workflows e os arquivos do repositório.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((RAIZ / ".github" / "workflows").glob("*.yml"))


def carregar_yaml(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


# 2.1 Actions fixadas por SHA ------------------------------------------------------


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_actions_fixadas_por_sha_com_versao_no_comentario(workflow):
    usos = re.findall(r"uses:\s*(\S+)(.*)", workflow.read_text(encoding="utf-8"))
    assert usos, f"{workflow.name} não usa nenhuma action"
    for acao, resto in usos:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", acao), f"{acao} não está fixada por SHA"
        assert re.fullmatch(r"\s*# v\d+\.\d+\.\d+", resto), f"{acao} sem a versão em comentário"
