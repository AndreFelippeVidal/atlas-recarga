"""Lista fechada de views, medidas e dimensões (SPEC-006 §3), lida do `catalog.json`.

O JSON é gerado de `semantic/*.yaml` por `scripts/build_mcp_catalog.py`; nada aqui define métrica.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("catalog.json")


@cache
def load_catalog() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return data


def list_metrics() -> dict[str, Any]:
    """Medidas e dimensões das duas views com a descrição oficial (tool `list_metrics`)."""
    return {
        "views": {
            name: {
                "description": view["description"],
                "period_dimension": view["period_dimension"],
                "measures": view["measures"],
                "dimensions": view["dimensions"],
            }
            for name, view in load_catalog()["views"].items()
        }
    }
