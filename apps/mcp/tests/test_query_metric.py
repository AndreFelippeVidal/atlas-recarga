"""P11.2: critérios 3 e 4 da SPEC-006 §7 (lista fechada, binds) e `list_metrics`."""

from __future__ import annotations

import asyncio
import re
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from atlas_mcp import server
from atlas_mcp.catalog import list_metrics, load_catalog
from atlas_mcp.errors import InvalidArgument
from atlas_mcp.query import MAX_LIMIT, build_query, query_metric
from fastmcp import Client
from fastmcp.exceptions import ToolError

BASE: dict[str, Any] = {
    "view": "mv_recharges",
    "measures": ["gross_revenue"],
    "dimensions": ["uf"],
    "filters": None,
    "month_from": "2026-10",
    "month_to": "2026-10",
}


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, sql: str, params: Any) -> tuple[list[str], list[list[Any]]]:
        self.calls.append((sql, dict(params)))
        return ["uf", "gross_revenue"], [["SP", Decimal("123.40")], ["RJ", Decimal("5.00")]]


def _run(executor: Recorder, **over: Any) -> dict[str, Any]:
    args = {**BASE, **over}
    return query_metric("atlas_dev", executor, **args)


def test_happy_path_builds_semantic_query_and_serializes_decimals() -> None:
    rec = Recorder()
    out = _run(rec)
    sql, params = rec.calls[0]
    assert "FROM atlas_dev.semantic.mv_recharges" in sql
    assert "MEASURE(`gross_revenue`) AS `gross_revenue`" in sql
    assert "GROUP BY `uf`" in sql and sql.endswith("LIMIT 50")
    assert params == {"month_from": "2026-10-01", "month_to": "2026-10-01"}
    assert out["rows"] == [["SP", "123.40"], ["RJ", "5.00"]]
    assert out["source"]["view"] == "mv_recharges"
    assert re.fullmatch(r"[0-9a-f]{40}", out["sql_fingerprint"])


def test_sql_carries_request_id_comment_and_fingerprint_ignores_it() -> None:
    a = build_query("atlas", **BASE, request_id="aaaa")
    b = build_query("atlas", **BASE, request_id="bbbb")
    assert a.sql.startswith("/* atlas-mcp request_id=aaaa */ ")
    assert a.fingerprint == b.fingerprint


@pytest.mark.parametrize(
    "over",
    [
        {"measures": ["DROP TABLE x"]},
        {"measures": ["gross_revenue; DROP TABLE x"]},
        {"measures": []},
        {"measures": ["gross_revenue", "gross_revenue"]},
        {"measures": ["commission_total"]},  # medida da outra view
        {"dimensions": ["nao_existe"]},
        {"dimensions": ["uf`; DROP"]},
        {"view": "gold.fct_recharges"},
        {"view": "mv_recharges; DROP"},
        {"filters": {"nao_existe": "x"}},
        {"filters": {"uf = 'x' OR 1": "SP"}},
        {"filters": {"uf": {"a": 1}}},
        {"filters": {"uf": []}},
        {"filters": {"uf": [None]}},
        {"filters": {"uf": True}},
        {"month_from": "2026-13"},
        {"month_from": "\u0662\u0660\u0662\u0666-\u0661\u0660"},
        {"measures": "gross_revenue"},
        {"filters": {"uf": float("nan")}},
        {"filters": {"uf": 2**70}},
        {"month_from": "2026-10-01"},
        {"month_to": "2026-1'; DROP"},
        {"month_from": "2026-11", "month_to": "2026-10"},
        {"limit": 0},
        {"limit": MAX_LIMIT + 1},
        {"limit": "50; DROP"},
        {"order_by": "uf; DROP"},
        {"order_by": "gross_revenue sideways"},
        {"order_by": "tier"},
    ],
)
def test_invalid_arguments_never_reach_the_warehouse(over: dict[str, Any]) -> None:
    rec = Recorder()
    with pytest.raises(InvalidArgument):
        _run(rec, **over)
    assert rec.calls == []


@pytest.mark.parametrize("evil", ["O'Brien", "SP'; DROP TABLE x; --", 'a"b', "x;y", "`"])
def test_filter_values_are_bound_never_concatenated(evil: str) -> None:
    rec = Recorder()
    _run(rec, filters={"uf": evil})
    sql, params = rec.calls[0]
    assert params["f0"] == evil
    assert "`uf` = :f0" in sql
    for fragment in ("DROP", "O'Brien", "x;y", '"'):
        assert fragment not in sql


def test_list_filter_uses_in_with_one_bind_per_value() -> None:
    rec = Recorder()
    _run(rec, filters={"uf": ["SP", "x'); DROP--"], "pos_type": "pharmacy"})
    sql, params = rec.calls[0]
    assert "`uf` IN (:f0_0, :f0_1)" in sql and "`pos_type` = :f1" in sql
    assert params["f0_1"] == "x'); DROP--"
    assert "DROP" not in sql


def test_period_uses_each_views_month_dimension() -> None:
    rec = Recorder()
    _run(rec, view="mv_commission", measures=["commission_total"], dimensions=[])
    sql, _ = rec.calls[0]
    assert "`reference_month` >= CAST(:month_from AS DATE)" in sql
    assert "GROUP BY" not in sql


def test_no_order_by_defaults_to_first_measure_desc() -> None:
    rec = Recorder()
    _run(rec, measures=["recharge_count", "gross_revenue"])
    assert " ORDER BY `recharge_count` DESC LIMIT 50" in rec.calls[0][0]


def test_order_by_defaults_and_explicit_direction() -> None:
    rec = Recorder()
    _run(rec, order_by="gross_revenue")
    _run(rec, order_by="uf desc", limit=5)
    assert " ORDER BY `gross_revenue` DESC LIMIT 50" in rec.calls[0][0]
    assert " ORDER BY `uf` DESC LIMIT 5" in rec.calls[1][0]


def test_date_values_are_json_safe() -> None:
    out = query_metric("atlas", lambda *_: (["m"], [[date(2026, 10, 1)]]), **BASE)
    assert out["rows"] == [["2026-10-01"]]


def test_list_metrics_exposes_both_views_with_descriptions() -> None:
    views = list_metrics()["views"]
    assert set(views) == {"mv_recharges", "mv_commission"}
    for view in views.values():
        for entry in [*view["measures"], *view["dimensions"]]:
            assert entry["name"] and entry["description"]
    assert "gross_revenue" in {m["name"] for m in views["mv_recharges"]["measures"]}


def test_catalog_period_dimensions_exist() -> None:
    for view in load_catalog()["views"].values():
        assert view["period_dimension"] in {d["name"] for d in view["dimensions"]}


def test_mcp_tools_list_and_injection_is_rejected_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_headers: Any) -> Any:
        raise AssertionError("não deve abrir conexão")

    monkeypatch.setattr(server, "make_executor", boom)

    async def run() -> tuple[set[str], Any]:
        async with Client(server.mcp) as client:
            names = {t.name for t in await client.list_tools()}
            with pytest.raises(ToolError, match="INVALID_ARGUMENT"):
                await client.call_tool(
                    "query_metric",
                    {**BASE, "measures": ["DROP TABLE x"]},
                )
            listed = await client.call_tool("list_metrics", {})
            return names, listed

    names, listed = asyncio.run(run())
    assert names == {
        "health",
        "list_metrics",
        "query_metric",
        "top_regions",
        "compare_months",
    }
    assert "mv_recharges" in listed.data["views"]


def test_query_failure_does_not_leak_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(_headers: Any) -> Any:
        def run(_sql: str, _params: Any) -> Any:
            raise RuntimeError("token=segredo no stack trace")

        return run

    monkeypatch.setattr(server, "make_executor", failing)

    async def run() -> str:
        async with Client(server.mcp) as client:
            try:
                await client.call_tool("query_metric", BASE)
            except ToolError as exc:
                return str(exc)
        return ""

    message = asyncio.run(run())
    assert message and "segredo" not in message
