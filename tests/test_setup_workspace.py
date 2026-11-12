"""Checks of `scripts/setup_workspace.py` (SPEC-002 §2, task P5.2). No workspace needed."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "setup_workspace", ROOT / "scripts" / "setup_workspace.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["setup_workspace"] = module
    spec.loader.exec_module(module)
    return module


setup = _load()


def test_statements_are_idempotent() -> None:
    statements = setup.build_statements("atlas_dev")
    assert statements[0] == "CREATE CATALOG IF NOT EXISTS atlas_dev"
    assert all("IF NOT EXISTS" in s for s in statements)


def test_creates_every_adr_0003_schema_and_the_landing_volume() -> None:
    statements = setup.build_statements("atlas")
    for schema in ("raw", "bronze", "silver", "gold", "semantic", "commission", "eval",
                   "observability"):  # fmt: skip
        assert f"CREATE SCHEMA IF NOT EXISTS atlas.{schema}" in statements
    assert any(s.startswith("CREATE VOLUME IF NOT EXISTS atlas.raw.landing") for s in statements)


@pytest.mark.parametrize("bad", ["", "Atlas", "atlas; DROP CATALOG x", "a-b", "1atlas", "a b"])
def test_rejects_unsafe_catalog_names(bad: str) -> None:
    with pytest.raises(ValueError):
        setup.build_statements(bad)


def test_groups_are_the_ones_the_specs_name() -> None:
    assert set(setup.GROUPS) == {
        "atlas_readers",
        "atlas_commission_analysts",
        "atlas_commission_directors",
    }


def test_targets_match_databricks_yml() -> None:
    text = (ROOT / "databricks.yml").read_text(encoding="utf-8")
    for target, catalog in setup.CATALOGS.items():
        block = re.search(rf"^  {target}:\n(?:    .*\n|\n)+", text, re.MULTILINE)
        assert block, target
        assert f"catalog: {catalog}" in block.group(0)


def test_dry_run_changes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert setup.main(["--target", "dev", "--profile", "x", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "CREATE CATALOG IF NOT EXISTS atlas_dev;" in out
    assert "atlas_readers" in out
