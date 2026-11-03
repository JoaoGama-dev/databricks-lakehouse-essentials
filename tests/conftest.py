"""Deixa o pacote src/essentials importável nos testes, como no pipeline, e marca cada
teste como "integracao" (os de tests/integracao/) ou "unidade" (todos os outros)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    # tryfirst: a marca precisa existir antes de o "-m" do pytest.ini filtrar os testes.
    for item in items:
        marca = "integracao" if "integracao" in item.path.parent.parts else "unidade"
        item.add_marker(getattr(pytest.mark, marca))
