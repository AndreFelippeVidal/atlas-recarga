"""Checks da metric view `mv_recharges` (SPEC-004 §3, task P7.1). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
SEMANTIC = ROOT / "semantic"

DIMENSIONS = {
    "recharge_date",
    "recharge_month",
    "recharge_hour_local",
    "region",
    "uf",
    "municipality_ibge_code",
    "municipality_name",
    "ddd",
    "pos_type",
    "distributor_name",
}
MEASURES = {
    "gross_revenue",
    "recharge_count",
    "avg_ticket",
    "active_pos",
    "revenue_per_active_pos",
    "reversal_rate",
    "distinct_subscribers",
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "apply_metric_views", SEMANTIC / "apply_metric_views.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["apply_metric_views"] = module
    spec.loader.exec_module(module)
    return module


amv = _load()


def _mv() -> dict[str, Any]:
    loaded = yaml.safe_load((SEMANTIC / "mv_recharges.yaml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_mv_recharges_has_the_spec_dimensions_and_measures() -> None:
    mv = _mv()
    assert mv["version"] == 1.1
    assert {d["name"] for d in mv["dimensions"]} == DIMENSIONS
    assert {m["name"] for m in mv["measures"]} == MEASURES


def test_every_field_has_comment_and_synonyms_for_genie_and_the_agent() -> None:
    mv = _mv()
    assert mv["comment"]
    for field in [*mv["dimensions"], *mv["measures"]]:
        assert field["comment"], field["name"]
        assert field["synonyms"], field["name"]


def test_only_approved_recharges_count_as_revenue_and_active_pos_is_defined_literally() -> None:
    measures = {m["name"]: m for m in _mv()["measures"]}
    for name in ("gross_revenue", "recharge_count", "active_pos", "distinct_subscribers"):
        assert "status = 'approved'" in measures[name]["expr"], name
    assert "pelo menos 1 recarga aprovada no período filtrado" in measures["active_pos"]["comment"]
    assert measures["avg_ticket"]["expr"] == "MEASURE(gross_revenue) / MEASURE(recharge_count)"


def test_join_aliases_are_not_a_prefix_of_a_fact_column() -> None:
    # `pos` seria prefixo de `pos_id` (INVALID_EXTRACT_BASE_FIELD_TYPE no workspace)
    fact_columns = {
        "recharge_id",
        "recharge_date",
        "recharge_month",
        "recharge_hour_local",
        "pos_id",
        "amount_brl",
        "status",
        "subscriber_id",
    }
    aliases: list[str] = []

    def walk(joins: list[dict[str, Any]]) -> None:
        for join in joins:
            aliases.append(join["name"])
            walk(join.get("joins", []))

    walk(_mv()["joins"])
    assert aliases == ["dim_pos", "dim_municipality", "dim_distributor"]
    assert not [a for a in aliases for c in fact_columns if c.startswith(a)]


def test_ddl_keeps_the_yaml_literal_and_resolves_the_catalog() -> None:
    text = (SEMANTIC / "mv_recharges.yaml").read_text(encoding="utf-8")
    ddl = amv.build_ddl("atlas_dev", "mv_recharges", text)
    assert ddl.startswith("CREATE OR REPLACE VIEW atlas_dev.semantic.mv_recharges\n")
    assert "WITH METRICS\nLANGUAGE YAML\nAS $$\n" in ddl and ddl.endswith("\n$$")
    assert "${" not in ddl
    body = ddl.split("AS $$\n", 1)[1].removesuffix("\n$$")
    assert body == text.replace("${catalog}", "atlas_dev")  # sem reindentar
    assert yaml.safe_load(body)["source"] == "atlas_dev.gold.fct_recharges"
    assert yaml.safe_load(amv.build_ddl("atlas", "mv_recharges", text).split("AS $$\n")[1][:-3])


def test_ddl_rejects_bad_catalog_name_placeholder_and_dollar_quotes() -> None:
    with pytest.raises(ValueError):
        amv.build_ddl("atlas; DROP", "mv_recharges", "version: 1.1")
    with pytest.raises(ValueError):
        amv.build_ddl("atlas", "mv; x", "version: 1.1")
    with pytest.raises(ValueError):
        amv.build_ddl("atlas", "mv_x", "source: ${schema}.t")
    with pytest.raises(ValueError):
        amv.build_ddl("atlas", "mv_x", "comment: $$ x")


def test_load_definitions_names_views_after_the_files(tmp_path: Path) -> None:
    (tmp_path / "mv_b.yaml").write_text("b", encoding="utf-8")
    (tmp_path / "mv_a.yaml").write_text("a", encoding="utf-8")
    assert amv.load_definitions(tmp_path) == [("mv_a", "a"), ("mv_b", "b")]
    with pytest.raises(FileNotFoundError):
        amv.load_definitions(tmp_path / "vazio")
    (tmp_path / "Bad-Name.yaml").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        amv.load_definitions(tmp_path)


def test_semantic_deploy_job_in_bundle_passes_catalog_and_synced_directory() -> None:
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
    job = bundle["resources"]["jobs"]["atlas_semantic_deploy"]
    assert "schedule" not in job  # sob demanda
    (task,) = job["tasks"]
    assert task["spark_python_task"]["python_file"] == "semantic/apply_metric_views.py"
    assert task["spark_python_task"]["parameters"] == [
        "${var.catalog}",
        "${workspace.file_path}/semantic",
    ]


def _load_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_mv_recharges", ROOT / "scripts" / "check_mv_recharges.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_mv_recharges"] = module
    spec.loader.exec_module(module)
    return module


def test_check_script_covers_every_measure_and_flags_empty_values() -> None:
    check = _load_check()
    assert set(check.MEASURES) == MEASURES
    query = check.build_totals_query("atlas_dev")
    assert all(f"MEASURE({m})" in query for m in MEASURES)
    assert "atlas_dev.semantic.mv_recharges" in query
    row = ["100.00"] * len(check.MEASURES)
    assert not [line for line in check.totals_lines(row) if line.startswith("FALHA")]
    assert check.totals_lines([None, *row[1:]])[0].startswith("FALHA")
    assert check.region_lines([])[0].startswith("FALHA")
    assert check.region_lines([["Sul", "10.50"]])[0].startswith("ok")
    assert check.region_lines([["Sul", None]])[0].startswith("FALHA")
    assert check.region_lines([["Sul", "abc"]])[0].startswith("FALHA")
