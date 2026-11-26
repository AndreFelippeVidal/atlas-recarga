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
    "recharge_year",
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
    "aux_revenue_cur",
    "aux_revenue_prev",
    "aux_revenue_trailing2",
    "gross_revenue_t3m",
    "gross_revenue_ytd",
    "revenue_mom_change",
}
# As 7 medidas do MVP: `check_mv_recharges.py` as confere; as janelas são do `check_mv_windows.py`.
BASE_MEASURES = {
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
        "recharge_ts_utc",
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
    task = job["tasks"][0]  # a segunda task (P10.1) aplica as UC functions
    assert task["task_key"] == "apply_metric_views"
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
    assert set(check.MEASURES) == BASE_MEASURES
    query = check.build_totals_query("atlas_dev")
    assert all(f"MEASURE({m})" in query for m in BASE_MEASURES)
    assert "atlas_dev.semantic.mv_recharges" in query
    row = ["100.00"] * len(check.MEASURES)
    assert not [line for line in check.totals_lines(row) if line.startswith("FALHA")]
    assert check.totals_lines([None, *row[1:]])[0].startswith("FALHA")
    assert check.region_lines([])[0].startswith("FALHA")
    assert check.region_lines([["Sul", "10.50"]])[0].startswith("ok")
    assert check.region_lines([["Sul", None]])[0].startswith("FALHA")
    assert check.region_lines([["Sul", "abc"]])[0].startswith("FALHA")


def _load_consistency_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_mv_consistency", ROOT / "scripts" / "check_mv_consistency.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_mv_consistency"] = module
    spec.loader.exec_module(module)
    return module


def test_consistency_query_compares_measure_with_direct_gold_sql() -> None:
    check = _load_consistency_check()
    query = check.build_compare_query("atlas_dev")
    assert "MEASURE(gross_revenue)" in query
    assert "atlas_dev.semantic.mv_recharges" in query
    assert "atlas_dev.gold.fct_recharges" in query
    assert "status = 'approved'" in query
    assert "FULL OUTER JOIN" in query
    assert "'TOTAL'" in query
    assert "(SELECT MEASURE" not in query  # MEASURE só em CTE/nível superior (validado na P7.1)
    assert query.count("WHERE status = 'approved'") == 2  # por mês e total no gold


def test_consistency_lines_are_exact_to_the_cent() -> None:
    check = _load_consistency_check()
    same = [["2026-10-01", "100.00", "100.0"], ["TOTAL", "100.00", "100.00"]]
    assert all(line.startswith("ok") for line in check.compare_lines(same))
    off_by_cent = [["2026-10-01", "100.01", "100.00"], ["TOTAL", "100.00", "100.00"]]
    lines = check.compare_lines(off_by_cent)
    assert lines[0].startswith("FALHA") and lines[1].startswith("ok")


def test_consistency_flags_missing_side_empty_and_no_total() -> None:
    check = _load_consistency_check()
    total = ["TOTAL", "1.00", "1.00"]
    assert check.compare_lines([["2026-10-01", None, "1.00"], total])[0].startswith("FALHA")
    assert check.compare_lines([["2026-10-01", "x", "1.00"], total])[0].startswith("FALHA")
    assert check.compare_lines([total])[0].startswith("FALHA")  # sem meses
    assert check.compare_lines([["2026-10-01", "1.00", "1.00"]])[0].startswith("FALHA")


def test_consistency_main_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    check = _load_consistency_check()
    argv = ["--target", "dev", "--profile", "p", "--warehouse-id", "w"]
    monkeypatch.setattr(
        check, "_run", lambda *_: [["2026-10-01", "1.00", "1.00"], ["TOTAL", "1.00", "1.00"]]
    )
    assert check.main(argv) == 0
    monkeypatch.setattr(
        check, "_run", lambda *_: [["2026-10-01", "1.01", "1.00"], ["TOTAL", "1.00", "1.00"]]
    )
    assert check.main(argv) == 1


def test_mv_commission_has_the_spec_dimensions_and_measures_and_reads_only_locked() -> None:
    mv = yaml.safe_load((SEMANTIC / "mv_commission.yaml").read_text(encoding="utf-8"))
    assert {d["name"] for d in mv["dimensions"]} == {
        "reference_month",
        "beneficiary_type",
        "tier",
        "uf",
        "region",
        "municipality_name",
        "distributor_name",
        "batch_id",
    }
    assert {m["name"] for m in mv["measures"]} == {
        "commission_total",
        "commission_base",
        "effective_rate",
        "paid_beneficiaries",
    }
    for field in [*mv["dimensions"], *mv["measures"]]:
        assert field["comment"] and field["synonyms"], field["name"]
    source = mv["source"]
    assert "commission.locked_lines" in source and "commission.batches" in source
    assert "b.status = 'locked'" in source  # critério 2: rascunho nunca aparece
    assert "JOIN ${catalog}.commission.batches b ON b.batch_id = l.batch_id AND" in source
    measures = {m["name"]: m["expr"] for m in mv["measures"]}
    assert "FILTER (WHERE beneficiary_type = 'pos')" in measures["commission_base"]
    assert "FILTER (WHERE beneficiary_type = 'pos')" in measures["effective_rate"]
    assert "NULLIF(MEASURE(commission_base), 0)" in measures["effective_rate"]
    ddl = amv.build_ddl("atlas_dev", "mv_commission", (SEMANTIC / "mv_commission.yaml").read_text())
    assert "${" not in ddl and "atlas_dev.commission.locked_lines" in ddl


def test_check_mv_commission_queries_and_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "check_mv_commission", ROOT / "scripts" / "check_mv_commission.py"
    )
    assert spec and spec.loader
    check = importlib.util.module_from_spec(spec)
    sys.modules["check_mv_commission"] = check
    spec.loader.exec_module(check)
    leak = check.build_leak_query("atlas_dev")
    assert "atlas_dev.semantic.mv_commission" in leak and "<> 'locked'" in leak
    compare = check.build_compare_query("atlas_dev")
    assert "MEASURE(commission_total)" in compare and "b.status = 'locked'" in compare
    assert check.leak_lines([])[0].startswith("ok")
    assert check.leak_lines([["COM-2026-11-v1", "draft"]])[0].startswith("FALHA")
    assert check.compare_lines([["2026-10-01", "10.00", "10.0"]])[0].startswith("ok")
    assert check.compare_lines([["2026-10-01", "10.01", "10.00"]])[0].startswith("FALHA")
    assert check.compare_lines([])[0].startswith("FALHA")
    argv = ["--target", "dev", "--profile", "p", "--warehouse-id", "w"]
    monkeypatch.setattr(check, "_run", lambda *_: [])
    assert check.main(argv) == 1  # view vazia não passa
    answers = iter([[], [["2026-10-01", "1.00", "1.00"]]])
    monkeypatch.setattr(check, "_run", lambda *_: next(answers))
    assert check.main(argv) == 0


def test_window_measures_keep_the_structure_validated_in_the_spike() -> None:
    measures = {m["name"]: m for m in _mv()["measures"]}
    windows = {
        name: [(w["order"], w["range"]) for w in measures[name]["window"]]
        for name in ("aux_revenue_cur", "aux_revenue_prev", "aux_revenue_trailing2")
    }
    assert windows["aux_revenue_cur"] == [("recharge_month", "current")]
    assert windows["aux_revenue_prev"] == [("recharge_month", "trailing 1 month")]
    assert windows["aux_revenue_trailing2"] == [("recharge_month", "trailing 2 month")]
    ytd = measures["gross_revenue_ytd"]
    assert [(w["order"], w["range"]) for w in ytd["window"]] == [
        ("recharge_year", "current"),
        ("recharge_month", "cumulative"),
    ]
    t3m = measures["gross_revenue_t3m"]["expr"]
    assert t3m.count("COALESCE(") == 2 and "aux_revenue_trailing2" in t3m
    assert "NULLIF(MEASURE(aux_revenue_prev), 0)" in measures["revenue_mom_change"]["expr"]
    for name in ("gross_revenue_t3m", "gross_revenue_ytd", "revenue_mom_change"):
        assert measures[name]["format"] and measures[name]["synonyms"], name


def test_mcp_catalog_and_functions_exclude_the_same_measures() -> None:
    spec = importlib.util.spec_from_file_location(
        "build_mcp_catalog", ROOT / "scripts" / "build_mcp_catalog.py"
    )
    assert spec and spec.loader
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    funcs = importlib.util.spec_from_file_location(
        "apply_functions", SEMANTIC / "apply_functions.py"
    )
    assert funcs and funcs.loader
    fn = importlib.util.module_from_spec(funcs)
    funcs.loader.exec_module(fn)
    assert catalog.AUX_PREFIX == fn.AUX_PREFIX
    assert catalog.WINDOW_MEASURES_PENDING_P15_6 == fn.WINDOW_MEASURES_PENDING_P15_6
