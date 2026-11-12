"""Checks da camada bronze (SPEC-002 §3, task P6.1). Não precisam de workspace nem de pyspark."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRONZE = ROOT / "pipeline" / "bronze.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_bronze_counts", ROOT / "scripts" / "check_bronze_counts.py"
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_bronze_counts"] = module
    spec.loader.exec_module(module)
    return module


def _declared() -> dict[str, tuple[str, str]]:
    """nome da tabela -> (decorator, comment), lidos do AST de `bronze.py`."""
    found: dict[str, tuple[str, str]] = {}
    for node in ast.walk(ast.parse(BRONZE.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute):
                kwargs = {k.arg: ast.literal_eval(k.value) for k in deco.keywords}
                found[kwargs["name"]] = (deco.func.attr, kwargs.get("comment", ""))
    return found


def test_bronze_declares_the_four_datasets_with_the_right_kind() -> None:
    assert {name: kind for name, (kind, _) in _declared().items()} == {
        "bronze.recharges": "table",
        "bronze.pos": "materialized_view",
        "bronze.distributors": "materialized_view",
        "bronze.municipalities": "materialized_view",
    }


def test_every_bronze_dataset_has_a_comment() -> None:
    assert all(comment for _, comment in _declared().values())


def test_bronze_never_drops_rows() -> None:
    # SPEC-002 §3: sem expectations que descartem linhas no bronze
    decorators = {
        deco.func.attr
        for node in ast.walk(ast.parse(BRONZE.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef)
        for deco in node.decorator_list
        if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
    }
    assert not {d for d in decorators if d.startswith("expect")}


def test_bronze_adds_only_the_two_lineage_columns() -> None:
    text = BRONZE.read_text(encoding="utf-8")
    assert '"_source_file"' in text
    assert '"_ingested_at_utc"' in text


def test_expected_counts_come_from_the_manifest() -> None:
    script = _load_script()
    manifest = {"counts": {"recharges": 10, "pos": 3, "distributors": 2, "municipalities": 5570}}
    assert script.expected_counts(manifest) == {
        "recharges": 10,
        "pos": 3,
        "distributors": 2,
        "municipalities": 5570,
    }


def test_expected_counts_requires_every_count() -> None:
    script = _load_script()
    with pytest.raises(KeyError, match="municipalities"):
        script.expected_counts({"counts": {"recharges": 1, "pos": 1, "distributors": 1}})


def test_compare_flags_a_mismatch() -> None:
    script = _load_script()
    lines = script.compare({"pos": 5, "recharges": 9}, {"pos": 5, "recharges": 8})
    assert lines[0].startswith("ok")
    assert lines[1].startswith("FALHA")


def test_query_reads_only_the_closed_list_of_bronze_tables() -> None:
    script = _load_script()
    query = script.build_query("atlas_dev")
    assert query.count("SELECT") == 4
    assert "atlas_dev.bronze.recharges" in query
    assert "atlas_dev.bronze.municipalities" in query


def test_bundle_declares_the_single_pipeline_with_the_landing_path() -> None:
    text = (ROOT / "databricks.yml").read_text(encoding="utf-8")
    assert "atlas_medallion:" in text
    assert "serverless: true" in text
    assert "atlas.landing_path: /Volumes/${var.catalog}/raw/landing" in text
    assert "pipeline/bronze.py" in text
