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


def test_gold_declares_the_four_tables_of_the_spec() -> None:
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
