"""Relatório `commission_review` (task P8.8): consultas, dashboard e notebook (sem workspace)."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from commission import review_report as rr

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "semantic" / "dashboards" / "commission_review.lvdash.json"

# Colunas que cada dataset devolve (o contrato com os widgets).
COLUMNS: dict[str, set[str]] = {
    "totals": {
        "batch_id", "status", "reference_month", "demo_mode", "total_pos_brl",
        "total_distributor_brl", "pos_lines", "distributor_lines", "flagged_lines",
        "reconciliation_status", "lines_compared", "max_line_diff_brl", "total_diff_brl",
        "pos_control_diff_brl", "distributor_control_diff_brl",
    },
    "top20": {
        "batch_id", "rnk", "beneficiary_type", "beneficiary_id", "tier", "base_amount_brl",
        "rate", "commission_brl", "flags",
    },
    "flagged": {
        "batch_id", "beneficiary_type", "beneficiary_id", "tier", "base_amount_brl",
        "commission_brl", "flags",
    },
    "flag_counts": {"batch_id", "flag", "lines"},
    "previous_totals": {
        "batch_id", "previous_batch_id", "total_pos_brl", "previous_total_pos_brl",
        "total_distributor_brl", "previous_total_distributor_brl",
    },
    "previous_pos": {
        "batch_id", "previous_batch_id", "beneficiary_id", "tier", "previous_tier",
        "commission_brl", "previous_commission_brl", "change_brl", "flags",
    },
}  # fmt: skip

STEMS = [stem for _, _, stem in rr.DATASETS]


def _widgets(dash: dict[str, Any]) -> list[dict[str, Any]]:
    return [item["widget"] for p in dash["pages"] for item in p["layout"]]


@pytest.fixture(scope="module")
def dash() -> dict[str, Any]:
    return json.loads(DASH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_every_dataset_has_a_sql_file_and_a_contract() -> None:
    assert set(STEMS) == set(COLUMNS)
    assert {p.stem for p in rr.SQL_DIR.glob("*.sql")} == set(STEMS)


@pytest.mark.parametrize("stem", STEMS)
def test_sql_reads_only_commission_tables_and_never_writes(stem: str) -> None:
    sql = rr.load_sql(stem)
    tables = set(re.findall(r"(?i)\b(?:FROM|JOIN)\s+([a-z_.]+)", sql))
    tables -= {"previous", "compared"}  # CTEs
    assert tables <= {"batches", "batch_lines", "reconciliation"}, tables
    assert not re.search(r"(?i)\b(insert|update|delete|merge|create|drop|alter|truncate)\b", sql)
    for layer in ("gold", "silver", "bronze", "semantic"):
        assert layer not in sql.lower().replace("semantic.", "x")
    assert "batch_id" in sql and ":" not in re.sub(r"'[^']*'", "", sql)  # sem parâmetro no corpo


@pytest.mark.parametrize("stem", STEMS)
def test_sql_has_no_global_limit_so_the_batch_filter_is_safe(stem: str) -> None:
    assert not re.search(r"(?i)\blimit\b", rr.load_sql(stem))


def test_batch_query_binds_batch_id() -> None:
    q = rr.batch_query("top20")
    assert q.endswith(") WHERE batch_id = :batch_id") and "'COM-" not in q


@pytest.mark.parametrize("bad", ["", "COM-2026-10", "x'; DROP TABLE t; --", "COM-2026-10-v1 "])
def test_batch_id_is_validated(bad: str) -> None:
    with pytest.raises(ValueError, match="batch_id inválido"):
        rr.check_batch_id(bad)


@pytest.mark.parametrize("ok", ["COM-2026-10-v1", "COM-2026-09-v12", "COM-2026-10-ADJ-1"])
def test_batch_id_accepts_the_spec_formats(ok: str) -> None:
    assert rr.check_batch_id(ok) == ok


def test_previous_batch_rule_is_the_same_in_both_comparisons() -> None:
    def cte(stem: str) -> str:
        sql = rr.load_sql(stem)
        end = "DESC) = 1"
        return sql[sql.index("WITH previous AS") : sql.index(end) + len(end)]

    assert cte("previous_totals") == cte("previous_pos")
    assert "status = 'locked'" in cte("previous_pos")
    assert "NOT LIKE '%-ADJ-%'" in cte("previous_pos")


def test_run_uses_the_catalog_and_one_bound_query_per_dataset() -> None:
    calls: list[tuple[str, dict[str, str] | None]] = []

    class FakeSpark:
        def sql(self, text: str, args: dict[str, str] | None = None) -> str:
            calls.append((text, args))
            return "df"

    out = rr.run(FakeSpark(), "atlas_dev", "COM-2026-10-v1")
    assert set(out) == {name for name, _, _ in rr.DATASETS}
    assert calls[0][0] == "USE CATALOG atlas_dev" and calls[1][0] == "USE SCHEMA commission"
    assert all(a == {"batch_id": "COM-2026-10-v1"} for _, a in calls[2:])
    with pytest.raises(ValueError, match="batch_id inválido"):
        rr.run(FakeSpark(), "atlas_dev", "bad")


def test_versioned_dashboard_is_in_sync_with_the_generator() -> None:
    spec = importlib.util.spec_from_file_location(
        "build_commission_review_dashboard",
        ROOT / "scripts" / "build_commission_review_dashboard.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert DASH.read_text(encoding="utf-8") == module.render(), (
        "rode: uv run python scripts/build_commission_review_dashboard.py"
    )


def test_dashboard_datasets_match_the_sql_files(dash: dict[str, Any]) -> None:
    by_name = {d["name"]: d for d in dash["datasets"]}
    for name, _, stem in rr.DATASETS:
        assert "".join(by_name[name]["queryLines"]).strip() == rr.load_sql(stem)
        assert "".join(by_name[name]["queryLines"]).startswith(("SELECT", "--", "WITH"))


def test_dashboard_fields_exist_and_encodings_match(dash: dict[str, Any]) -> None:
    columns = {name: COLUMNS[stem] for name, _, stem in rr.DATASETS}
    for w in _widgets(dash):
        for q in w.get("queries", []):
            ds = q["query"]["datasetName"]
            for f in q["query"]["fields"]:
                inner = re.sub(r"^\w+\(`(\w+)`\)$", r"\1", f["expression"]).strip("`")
                assert inner in columns[ds], (w["name"], f)
        if "spec" in w and not w["spec"]["widgetType"].startswith("filter"):
            names = {f["name"] for q in w["queries"] for f in q["query"]["fields"]}
            used = set(re.findall(r'"fieldName": "([^"]+)"', json.dumps(w["spec"]["encodings"])))
            assert used <= names, (w["name"], used - names)


def test_every_dataset_is_filterable_by_batch(dash: dict[str, Any]) -> None:
    (page,) = [p for p in dash["pages"] if p["pageType"] == "PAGE_TYPE_GLOBAL_FILTERS"]
    fields = {
        f["fieldName"]
        for item in page["layout"]
        for f in item["widget"]["spec"]["encodings"]["fields"]
    }
    assert fields == {"batch_id"}
    assert all("batch_id" in COLUMNS[stem] for stem in STEMS)


def test_dashboard_shows_what_the_task_requires(dash: dict[str, Any]) -> None:
    used = {q["query"]["datasetName"] for w in _widgets(dash) for q in w.get("queries", [])}
    # totais, top 20, flags e comparação com o mês anterior
    assert {"ds_totals", "ds_top20", "ds_flagged", "ds_previous_totals", "ds_previous_pos"} <= used


def test_layout_rows_have_no_overlap_and_fit_the_grid(dash: dict[str, Any]) -> None:
    (page,) = [p for p in dash["pages"] if p["pageType"] == "PAGE_TYPE_CANVAS"]
    boxes = [i["position"] for i in page["layout"]]
    assert all(b["x"] >= 0 and b["x"] + b["width"] <= 12 for b in boxes)
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            apart = (
                a["x"] + a["width"] <= b["x"]
                or b["x"] + b["width"] <= a["x"]
                or a["y"] + a["height"] <= b["y"]
                or b["y"] + b["height"] <= a["y"]
            )
            assert apart, (a, b)


def test_bundle_declares_the_dashboard_over_the_commission_schema() -> None:
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
    d = bundle["resources"]["dashboards"]["commission_review"]
    assert d["file_path"] == "semantic/dashboards/commission_review.lvdash.json"
    assert d["dataset_catalog"] == "${var.catalog}"
    assert d["dataset_schema"] == "commission"
    assert (ROOT / d["file_path"]).is_file()


def test_notebook_only_goes_through_the_report_module() -> None:
    text = (ROOT / "commission" / "commission_review.py").read_text(encoding="utf-8")
    assert text.startswith("# Databricks notebook source")
    assert "spark.sql" not in text.replace("review_report.run(spark", "")
    assert not re.search(r"(?i)\b(insert into|update \w+ set|delete from|merge into)\b", text)


@pytest.mark.parametrize("bad", ["", "atlas_prod", "atlas_dev; DROP CATALOG atlas", "ATLAS"])
def test_catalog_is_a_closed_list(bad: str) -> None:
    class Spark:
        def sql(self, *_: object, **__: object) -> None:
            raise AssertionError("não deve executar SQL com catálogo inválido")

    with pytest.raises(ValueError, match="catalog inválido"):
        rr.run(Spark(), bad, "COM-2026-10-v1")


def test_catalogs_match_the_bundle_targets() -> None:
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
    targets = {t["variables"]["catalog"] for t in bundle["targets"].values()}
    assert targets == set(rr.CATALOGS)
