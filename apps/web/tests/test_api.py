from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from atlas_web.app import UNREACHABLE, create_app
from atlas_web.cache import TTLCache
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_CATALOG", "atlas_test")
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh1")


COLS = ["recharge_month", "gross_revenue", "recharge_count", "avg_ticket", "active_pos"]


def _day(value: date) -> date:
    return value.date() if isinstance(value, datetime) else value


class FakeWarehouse:
    def __init__(self, rows: list[list[Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def __call__(self, sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        self.calls.append((sql, params))
        if "WHERE" not in sql:
            return ["recharge_month", "gross_revenue"], [
                [date(2026, 10, 1), Decimal("10.00")],
                [date(2026, 9, 1), Decimal("5.00")],
                [date(2026, 8, 1), None],
            ]
        wanted = {params["month"], params["previous"]}
        return COLS, [r for r in self.rows if _day(r[0]) in wanted]


ROWS = [
    [date(2026, 10, 1), Decimal("4122460.00"), 100, Decimal("41.22"), 4800],
    [date(2026, 9, 1), Decimal("3000000.00"), 90, Decimal("33.33"), 4700],
]


def client(rows: list[list[Any]] = ROWS) -> tuple[TestClient, FakeWarehouse]:
    wh = FakeWarehouse(rows)
    return TestClient(create_app(executor=wh, cache=TTLCache())), wh


def test_months_lists_months_with_revenue_desc_and_uses_view() -> None:
    c, wh = client()
    assert c.get("/api/months").json() == {"months": ["2026-10", "2026-09"]}
    assert "atlas_test.semantic.mv_recharges" in wh.calls[0][0]
    assert "MEASURE(`gross_revenue`)" in wh.calls[0][0]


def test_kpis_with_previous_and_delta() -> None:
    c, wh = client()
    body = c.get("/api/kpis", params={"month": "2026-10"}).json()
    assert body["previous_month"] == "2026-09"
    revenue = body["gross_revenue"]
    assert revenue["value"] == "4122460.00"
    assert revenue["previous"] == "3000000.00"
    assert revenue["delta_pct"] == "37.42"
    assert body["active_pos"]["value"] == "4800"
    assert wh.calls[0][1] == {"month": date(2026, 10, 1), "previous": date(2026, 9, 1)}


def test_kpis_accept_timestamp_months_from_date_trunc() -> None:
    rows = [[datetime(2026, 10, 1, tzinfo=UTC), *ROWS[0][1:]], [datetime(2026, 9, 1), *ROWS[1][1:]]]
    c, _ = client(rows)
    assert c.get("/api/kpis", params={"month": "2026-10"}).json()["gross_revenue"]["previous"] == (
        "3000000.00"
    )


def test_first_month_has_null_previous() -> None:
    c, _ = client([ROWS[1]])
    body = c.get("/api/kpis", params={"month": "2026-09"}).json()
    assert body["gross_revenue"]["previous"] is None
    assert body["gross_revenue"]["delta_pct"] is None


def test_january_looks_at_december_of_previous_year() -> None:
    c, wh = client()
    c.get("/api/kpis", params={"month": "2026-01"})
    assert wh.calls[0][1]["previous"] == date(2025, 12, 1)


def test_invalid_month_is_400_and_never_reaches_sql() -> None:
    c, wh = client()
    for bad in ("foo", "2026-13", "2026-1", "2026-10-01", "'; DROP"):
        r = c.get("/api/kpis", params={"month": bad})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_ARGUMENT"
    assert wh.calls == []
    assert c.get("/api/kpis").status_code == 422


def test_month_without_data_is_404() -> None:
    c, _ = client()
    assert c.get("/api/kpis", params={"month": "2020-01"}).status_code == 404


def test_cache_hits_skip_the_warehouse_and_failures_are_not_cached() -> None:
    c, wh = client()
    c.get("/api/kpis", params={"month": "2026-10"})
    c.get("/api/kpis", params={"month": "2026-10"})
    assert len(wh.calls) == 1

    def boom(sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        raise RuntimeError("connector secret detail")

    failing = TestClient(create_app(executor=boom, cache=TTLCache()))
    r = failing.get("/api/months")
    assert r.status_code == 503
    assert "secret" not in r.text


def test_cache_expires_after_ttl() -> None:
    now = [0.0]
    cache = TTLCache(ttl_s=600, clock=lambda: now[0])
    wh = FakeWarehouse(ROWS)
    c = TestClient(create_app(executor=wh, cache=cache))
    c.get("/api/months")
    now[0] = 599
    c.get("/api/months")
    assert len(wh.calls) == 1
    now[0] = 601
    c.get("/api/months")
    assert len(wh.calls) == 2


def test_health_reports_warehouse_without_querying_it() -> None:
    wh = FakeWarehouse(ROWS)

    class S:
        state = "RUNNING"

    c = TestClient(create_app(executor=wh, warehouse_fetch=lambda _id: S()))
    assert c.get("/api/health").json() == {"status": "healthy", "warehouse": "RUNNING"}
    assert wh.calls == []


def test_health_survives_warehouse_lookup_failure() -> None:
    def fail(_id: str) -> Any:
        raise RuntimeError("x")

    c = TestClient(create_app(executor=FakeWarehouse(ROWS), warehouse_fetch=fail))
    assert c.get("/api/health").json() == {"status": "healthy", "warehouse": UNREACHABLE}
