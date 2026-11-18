"""O snapshot `apps/mcp/atlas_mcp/catalog.json` tem que refletir `semantic/*.yaml` (SPEC-006 §3)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_mcp_catalog.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_mcp_catalog", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_json_matches_semantic_yaml() -> None:
    mod = _load()
    assert mod.CATALOG_PATH.read_text(encoding="utf-8") == mod.render(mod.build_catalog()), (
        "rode: uv run python scripts/build_mcp_catalog.py"
    )
