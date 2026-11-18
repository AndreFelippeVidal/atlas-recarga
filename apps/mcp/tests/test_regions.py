"""P11.3: `top_regions` e `compare_months` (SPEC-006 §3, §4 e §7 critério 3)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import pytest
from atlas_mcp.errors import InvalidArgument, ResultTooLarge
from atlas_mcp.regions import compare_months, top_regions


class Recorder:
    def __init__(self, *results: list[list[Any]]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, sql: str, params: Any) -> tuple[list[str], list[list[Any]]]:
        self.calls.append((sql, dict(params)))
        return [], self.results[len(self.calls) - 1]


def test_top_regions_builds_closed_list_query_with_bound_values() -> None:
    rec = Recorder([["SP", Decimal("9.50")], ["RJ", Decimal("1.00")]])
    out = top_regions("atlas_dev", rec, "gross_revenue", "uf", "2026-10", n=5, uf="SP")
    sql, params = rec.calls[0]
    assert "FROM atlas_dev.semantic.mv_recharges" in sql
    assert "MEASURE(`gross_revenue`) AS `gross_revenue`" in sql
    assert "GROUP BY `uf`" in sql and "ORDER BY `gross_revenue` DESC LIMIT 5" in sql
    assert params["f0"] == "SP" and "SP" not in sql
    assert out["rows"] == [["SP", "9.50"], ["RJ", "1.00"]]
    assert out["source"]["level"] == "uf" and out["source"]["month"] == "2026-10"
    assert re.fullmatch(r"[0-9a-f]{40}", out["sql_fingerprint"])


def test_top_regions_municipality_uses_code_and_name() -> None:
    rec = Recorder([])
    top_regions("atlas", rec, "recharge_count", "municipality", "2026-10")
    assert "GROUP BY `municipality_ibge_code`, `municipality_name`" in rec.calls[0][0]


@pytest.mark.parametrize(
    "bad",
    [
        {"measure": "DROP TABLE x"},
        {"measure": "commission_total"},  # medida da outra view
        {"measure": 7},
        {"level": "pais"},
        {"level": ["uf"]},
        {"month": "2026-13"},
        {"month": "outubro"},
        {"n": 0},
        {"n": 51},
        {"n": True},
        {"uf": ""},
        {"uf": ["SP"]},
    ],
)
def test_top_regions_invalid_argument_never_runs_a_query(bad: dict[str, Any]) -> None:
    rec = Recorder()
    args: dict[str, Any] = {"measure": "gross_revenue", "level": "uf", "month": "2026-10", **bad}
    with pytest.raises(InvalidArgument):
        top_regions("atlas", rec, **args)
    assert rec.calls == []


def test_top_regions_injection_in_uf_is_bound() -> None:
    rec = Recorder([])
    top_regions("atlas", rec, "gross_revenue", "uf", "2026-10", uf="SP'; DROP TABLE x; --")
    sql, params = rec.calls[0]
    assert "DROP" not in sql and "SP'; DROP TABLE x; --" in params.values()


def test_compare_months_computes_deltas_in_decimal() -> None:
    rec = Recorder(
        [["SP", Decimal("100.00")], ["RJ", Decimal("0.00")], ["MG", Decimal("10.10")]],
        [["SP", Decimal("112.35")], ["RJ", Decimal("5.00")], ["BA", Decimal("3.00")]],
    )
    out = compare_months("atlas", rec, "gross_revenue", "2026-09", "2026-10", "uf")
    assert [c[1]["month_from"] for c in rec.calls] == ["2026-09-01", "2026-10-01"]
    assert rec.calls[0][0] == rec.calls[1][0]  # mesmo SQL, só os binds mudam
    assert out["columns"] == ["uf", "value_a", "value_b", "delta_abs", "delta_pct"]
    rows = {r[0]: r[1:] for r in out["rows"]}
    assert rows["SP"] == ["100.00", "112.35", "12.35", "12.35"]
    assert rows["RJ"] == ["0.00", "5.00", "5.00", None]  # base 0: sem Δ%
    assert rows["MG"] == ["10.10", None, None, None]  # só em um mês
    assert rows["BA"] == [None, "3.00", None, None]
    assert out["rows"][0][0] == "SP"  # maior variação absoluta primeiro
    assert out["source"]["month_a"] == "2026-09" and out["source"]["month_b"] == "2026-10"


def test_compare_months_pct_rounds_half_even() -> None:
    rec = Recorder([["SP", Decimal("8")]], [["SP", Decimal("8.01")]])
    out = compare_months("atlas", rec, "gross_revenue", "2026-09", "2026-10", "uf")
    assert out["rows"][0][4] == "0.12"  # 0.125 -> 0.12 (half-even)


def test_compare_months_too_many_rows_is_result_too_large() -> None:
    big = [[str(i), Decimal(1)] for i in range(501)]
    with pytest.raises(ResultTooLarge, match="uf"):
        compare_months("atlas", Recorder(big, []), "gross_revenue", "2026-09", "2026-10", "uf")


def test_compare_months_union_above_limit_is_result_too_large() -> None:
    a = [[str(i), Decimal(1)] for i in range(300)]
    b = [[str(i + 300), Decimal(1)] for i in range(300)]
    with pytest.raises(ResultTooLarge):
        compare_months("atlas", Recorder(a, b), "gross_revenue", "2026-09", "2026-10", "uf")


def test_compare_months_exactly_500_rows_is_accepted() -> None:
    rows = [[str(i), Decimal(1)] for i in range(500)]
    out = compare_months("atlas", Recorder(rows, rows), "gross_revenue", "2026-09", "2026-10", "uf")
    assert len(out["rows"]) == 500


def test_compare_months_invalid_argument_never_runs_a_query() -> None:
    rec = Recorder()
    for bad in ({"month_a": "09/2026"}, {"level": "x"}, {"measure": "x; DROP"}):
        args: dict[str, Any] = {
            "measure": "gross_revenue",
            "month_a": "2026-09",
            "month_b": "2026-10",
            "level": "uf",
            **bad,
        }
        with pytest.raises(InvalidArgument):
            compare_months("atlas", rec, **args)
    assert rec.calls == []
