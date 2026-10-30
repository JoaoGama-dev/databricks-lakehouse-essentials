"""Deixa o pacote src/essentials importável nos testes, como no pipeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
