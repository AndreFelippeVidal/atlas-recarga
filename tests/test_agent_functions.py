"""UC functions do agente (SPEC-005 §3, task P10.1). Sem workspace: confere o DDL gerado."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
SEMANTIC = ROOT / "semantic"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "apply_functions", SEMANTIC / "apply_functions.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["apply_functions"] = module
    spec.loader.exec_module(module)
    return module


af = _load()


def _mv() -> dict[str, Any]:
    loaded = yaml.safe_load((SEMANTIC / "mv_recharges.yaml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _ddl() -> dict[str, str]:
    return dict(af.build_all("atlas_dev", _mv()))


def test_three_functions_in_creation_order() -> None:
    names = [n for n, _ in af.build_all("atlas_dev", _mv())]
    assert names == ["fn_list_metrics", "fn_metric_by_region", "fn_compare_months"]
    for name, ddl in _ddl().items():
        assert ddl.startswith(f"CREATE OR REPLACE FUNCTION atlas_dev.semantic.{name}(")


def test_signatures_follow_the_spec() -> None:
    ddl = _ddl()
    by_region = ddl["fn_metric_by_region"].split("RETURNS")[0]
    for param in ("measure STRING", "level STRING", "month DATE", "uf STRING DEFAULT NULL"):
        assert param in by_region
    compare = ddl["fn_compare_months"].split("RETURNS")[0]
    positions = [compare.index(p) for p in ("measure ", "month_a ", "month_b ", "level ", "uf ")]
    assert positions == sorted(positions)


def test_every_measure_is_validated_and_selected_from_the_yaml() -> None:
    measures = [m["name"] for m in _mv()["measures"]]
    ddl = _ddl()["fn_metric_by_region"]
    for m in measures:
        assert f"MEASURE({m}) AS {m}" in ddl
        assert f"WHEN '{m}' THEN CAST({m} AS DECIMAL(24, 6))" in ddl  # nada passa por DOUBLE
    assert "INVALID_MEASURE" in ddl and "INVALID_LEVEL" in ddl
    assert ddl.count("MEASURE(") == len(measures) * len(af.LEVELS)


def test_levels_use_dimensions_that_exist() -> None:
    dims = {d["name"] for d in _mv()["dimensions"]}
    for key, label in af.LEVELS.values():
        assert {key, label} <= dims


def test_params_are_qualified_by_the_function_name() -> None:
    # coluna `uf`/`level` vence o parâmetro de mesmo nome: sem qualificar, `uf = uf` é sempre true
    ddl = _ddl()["fn_metric_by_region"].split("RETURN\n", 1)[1]
    assert "uf = fn_metric_by_region.uf" in ddl
    assert "a.level = fn_metric_by_region.level" in ddl
    assert not re.search(r"(?<![.\w])month\)", ddl)


def test_no_dynamic_sql_no_double_and_only_the_metric_view() -> None:
    for ddl in _ddl().values():
        upper = ddl.upper()
        assert "EXECUTE IMMEDIATE" not in upper
        assert "DOUBLE" not in upper and "FLOAT" not in upper
        for layer in ("gold", "silver", "bronze", "commission"):
            assert f".{layer}." not in ddl
    assert "atlas_dev.semantic.mv_recharges" in _ddl()["fn_metric_by_region"]


def test_compare_months_reuses_by_region_and_guards_division_by_zero() -> None:
    ddl = _ddl()["fn_compare_months"]
    assert ddl.count("atlas_dev.semantic.fn_metric_by_region(") == 2
    assert "a.value = 0 THEN NULL" in ddl
    assert "FULL OUTER JOIN" in ddl


def test_compare_months_joins_null_keys_and_rounds_the_percentage() -> None:
    ddl = _ddl()["fn_compare_months"]
    assert "ON a.key <=> b.key" in ddl
    assert "ROUND((b.value - a.value) / a.value * 100, 2)" in ddl


def test_list_metrics_carries_every_field_with_its_official_comment() -> None:
    mv = _mv()
    ddl = _ddl()["fn_list_metrics"]
    for kind, key in (("measure", "measures"), ("dimension", "dimensions")):
        for field in mv[key]:
            assert f"('{kind}', '{field['name']}'," in ddl
    assert ddl.count("('measure',") == len(mv["measures"])
    assert ddl.count("('dimension',") == len(mv["dimensions"])


def test_list_metrics_escapes_quotes() -> None:
    definition = {
        "measures": [{"name": "m", "comment": "d'água \\ x", "synonyms": ["a'b"]}],
        "dimensions": [],
    }
    ddl = af.build_list_metrics("atlas", definition)
    assert "d\\'água \\\\ x" in ddl and "a\\'b" in ddl


def test_rejects_unsafe_names() -> None:
    with pytest.raises(ValueError):
        af.build_all("atlas; DROP", _mv())
    with pytest.raises(ValueError):
        af.build_compare_months("a b")
    bad = {"measures": [{"name": "x; DROP", "comment": "c"}], "dimensions": []}
    with pytest.raises(ValueError):
        af.build_list_metrics("atlas", bad)


def test_missing_dimension_for_a_level_is_an_error() -> None:
    definition = _mv()
    definition["dimensions"] = [d for d in definition["dimensions"] if d["name"] != "ddd"]
    with pytest.raises(ValueError, match="ddd"):
        af.build_metric_by_region("atlas", definition)


def test_bundle_runs_the_functions_after_the_metric_views() -> None:
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
    tasks = {
        t["task_key"]: t for t in bundle["resources"]["jobs"]["atlas_semantic_deploy"]["tasks"]
    }
    assert tasks["apply_agent_functions"]["depends_on"] == [{"task_key": "apply_metric_views"}]
    assert tasks["apply_agent_functions"]["spark_python_task"]["python_file"] == (
        "semantic/apply_functions.py"
    )
