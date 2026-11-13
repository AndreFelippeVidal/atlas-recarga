"""Checks do gold: dimensões e fato com COMMENT em tudo (SPEC-002 §3, P6.5). Sem workspace."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "pipeline" / "gold.py"

TABLES = {
    "DIM_MUNICIPALITY": "gold.dim_municipality",
    "DIM_DISTRIBUTOR": "gold.dim_distributor",
    "DIM_POS": "gold.dim_pos",
    "FCT_RECHARGES": "gold.fct_recharges",
    "AGG_POS_MONTH": "gold.agg_pos_month",
}


def _columns() -> dict[str, list[tuple[str, str, str]]]:
    tree = ast.parse(GOLD.read_text(encoding="utf-8"))
    found: dict[str, list[tuple[str, str, str]]] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in TABLES
            and node.value is not None
        ):
            found[node.target.id] = ast.literal_eval(node.value)
    return found


def _views() -> dict[str, dict[str, Any]]:
    tree = ast.parse(GOLD.read_text(encoding="utf-8"))
    views: dict[str, dict[str, Any]] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call) and getattr(deco.func, "attr", "") == "materialized_view":
                kwargs = {k.arg: k.value for k in deco.keywords if k.arg}
                name = ast.literal_eval(kwargs["name"])
                views[name] = {"comment": kwargs.get("comment"), "schema": kwargs.get("schema")}
    return views


def test_gold_declares_the_five_tables_of_the_spec() -> None:
    assert set(_views()) == set(TABLES.values())


def test_every_gold_table_has_a_comment_and_a_declared_schema() -> None:
    for name, view in _views().items():
        assert view["comment"] is not None, name
        assert view["schema"] is not None, name


def test_every_gold_column_has_a_description() -> None:
    columns = _columns()
    assert set(columns) == set(TABLES)
    for table, cols in columns.items():
        assert cols, table
        for name, sql_type, comment in cols:
            assert comment.strip(), f"{table}.{name} sem descrição"
            assert sql_type, f"{table}.{name} sem tipo"


def test_gold_columns_follow_the_spec() -> None:
    names = {t: [c[0] for c in cols] for t, cols in _columns().items()}
    assert names["DIM_MUNICIPALITY"] == [
        "municipality_ibge_code",
        "municipality_name",
        "uf",
        "region",
        "ddd",
        "population",
    ]
    assert names["DIM_POS"] == [
        "pos_id",
        "pos_type",
        "distributor_id",
        "municipality_ibge_code",
        "opened_date",
        "closed_date",
    ]
    assert names["DIM_DISTRIBUTOR"] == ["distributor_id", "distributor_name", "hq_uf"]
    assert names["FCT_RECHARGES"] == [
        "recharge_id",
        "recharge_date",
        "recharge_month",
        "recharge_hour_local",
        "pos_id",
        "amount_brl",
        "status",
        "subscriber_id",
    ]
    assert names["AGG_POS_MONTH"] == [
        "pos_id",
        "recharge_month",
        "approved_amount_brl",
        "approved_count",
        "reversed_count",
        "distinct_subscribers",
    ]


def test_agg_pos_month_types_follow_the_spec() -> None:
    types = {name: sql_type for name, sql_type, _ in _columns()["AGG_POS_MONTH"]}
    assert types["approved_amount_brl"] == "DECIMAL(14,2)"
    assert {types[c] for c in ("approved_count", "reversed_count", "distinct_subscribers")} == {
        "BIGINT"
    }


def test_agg_pos_month_reads_only_gold_facts_and_pos() -> None:
    tree = ast.parse(GOLD.read_text(encoding="utf-8"))
    func = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "agg_pos_month"
    )
    reads = sorted(
        ast.literal_eval(c.args[0])
        for c in ast.walk(func)
        if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "read"
    )
    assert reads == ["gold.dim_pos", "gold.fct_recharges"]


def test_gold_has_no_technical_columns_and_money_is_decimal() -> None:
    for table, cols in _columns().items():
        assert not [c for c, _, _ in cols if c.startswith("_")], table
    types = {name: sql_type for name, sql_type, _ in _columns()["FCT_RECHARGES"]}
    assert types["amount_brl"] == "DECIMAL(14,2)"
    assert types["recharge_month"] == "DATE"


def test_fct_recharges_reads_only_silver_recharges() -> None:
    tree = ast.parse(GOLD.read_text(encoding="utf-8"))
    func = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fct_recharges"
    )
    reads = [
        ast.literal_eval(c.args[0])
        for c in ast.walk(func)
        if isinstance(c, ast.Call)
        and getattr(c.func, "attr", "") in {"read", "read_stream", "table"}
    ]
    assert reads == ["silver.recharges"]


def test_bundle_registers_gold_in_the_pipeline() -> None:
    assert "pipeline/gold.py" in (ROOT / "databricks.yml").read_text(encoding="utf-8")


def _check_script() -> Any:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "check_gold_agg_pos_month", ROOT / "scripts" / "check_gold_agg_pos_month.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_gold_agg_pos_month"] = module
    spec.loader.exec_module(module)
    return module


def test_check_script_flags_a_month_that_does_not_match() -> None:
    script = _check_script()
    rows = [
        ["2026-01-01", "100.00", "100.00", "10", "10", "1", "1"],
        ["2026-02-01", "100.00", "90.00", "10", "9", "1", "1"],
        ["2026-03-01", "50.00", None, "5", None, "0", None],
    ]
    lines = script.month_lines(rows)
    assert [line.split()[0] for line in lines] == ["ok", "FALHA", "FALHA"]


def test_check_queries_use_the_closed_catalog_list() -> None:
    script = _check_script()
    assert set(script.CATALOGS) == {"dev", "demo"}
    assert "atlas_dev.gold.agg_pos_month" in script.build_compare_query("atlas_dev")
    assert "atlas_dev.gold.agg_pos_month" in script.build_duplicates_query("atlas_dev")


def test_check_script_fails_when_there_are_no_months() -> None:
    assert _check_script().month_lines([])[0].startswith("FALHA")
