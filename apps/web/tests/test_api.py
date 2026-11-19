from __future__ import annotations

import re
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


# --- P12.3: /api/map/* -------------------------------------------------------------------------

M, P = date(2026, 10, 1), date(2026, 9, 1)
REGION_ROWS = {  # (mês, região) -> (receita, recargas, ticket, pdvs)
    (M, "SE"): ("3000.00", 60, "50.00", 30),
    (M, "N"): ("1000.00", 40, "25.00", 10),
    (P, "SE"): ("2000.00", 50, "40.00", 28),
    (P, "N"): ("0.00", 0, "0.00", 0),
}
UF_ROWS = {
    (M, "SP", "SE"): "2000.00",
    (M, "RJ", "SE"): "1000.00",
    (M, "PA", "N"): "1000.00",
    (P, "SP", "SE"): "1000.00",
    (P, "RJ", "SE"): "1000.00",
}


def shape(sql: str, rows: list[list[Any]]) -> list[list[Any]]:
    """Só o SQL do `mom_change` seleciona `recharge_month` (1ª coluna)."""
    return rows if "SELECT `recharge_month`" in sql else [r[1:] for r in rows]


class MapWarehouse:
    """Responde conforme a medida e o nível do SQL (a metric view real faz o GROUP BY)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def __call__(self, sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        self.calls.append((sql, params))
        if "WHERE" not in sql:  # list_months
            return ["m", "v"], [[M, Decimal("1.00")], [P, Decimal("1.00")]]
        months = {params[k] for k in ("month", "previous") if k in params}
        measure = re.search(r"MEASURE\(`(\w+)`\)", sql).group(1)  # type: ignore[union-attr]
        idx = {"gross_revenue": 0, "recharge_count": 1, "avg_ticket": 2, "active_pos": 3}[measure]
        if "`municipality_ibge_code`" in sql:
            assert params["uf"] == "PA"
            rows = [[M, "1500001", "Belém", Decimal("700.00")], [M, "1500002", "Ananindeua", None]]
            return ["m", "c", "n", "value"], shape(sql, [r for r in rows if r[0] in months])
        if "`uf`" in sql.split("FROM")[0]:
            ufs = [
                [m, uf, Decimal(v)]
                for (m, uf, reg), v in UF_ROWS.items()
                if m in months and params.get("region", reg) == reg
            ]
            return ["m", "uf", "value"], shape(sql, ufs)
        regions = [[m, r, Decimal(str(v[idx]))] for (m, r), v in REGION_ROWS.items() if m in months]
        return ["m", "region", "value"], shape(sql, regions)


def map_client() -> tuple[TestClient, MapWarehouse]:
    wh = MapWarehouse()
    return TestClient(create_app(executor=wh, cache=TTLCache())), wh


def test_map_region_values_come_from_measure_by_region_sorted_desc() -> None:
    c, wh = map_client()
    r = c.get("/api/map/region", params={"month": "2026-10", "measure": "gross_revenue"})
    assert r.json() == [{"region": "SE", "value": "3000.00"}, {"region": "N", "value": "1000.00"}]
    sql = wh.calls[0][0]
    assert "MEASURE(`gross_revenue`)" in sql and "atlas_test.semantic.mv_recharges" in sql
    assert wh.calls[0][1] == {"month": M}


def test_region_and_uf_sums_equal_kpi_for_additive_measures() -> None:
    c, _ = map_client()
    regions = c.get("/api/map/region", params={"month": "2026-10", "measure": "gross_revenue"})
    ufs = c.get("/api/map/uf", params={"month": "2026-10", "measure": "gross_revenue"})
    total = Decimal("4000.00")
    assert sum(Decimal(i["value"]) for i in regions.json()) == total
    assert sum(Decimal(i["value"]) for i in ufs.json()) == total
    kpi = TestClient(
        create_app(
            executor=FakeWarehouse([[M, total, 100, Decimal("40.00"), 40]]), cache=TTLCache()
        )
    )
    assert (
        Decimal(kpi.get("/api/kpis", params={"month": "2026-10"}).json()["gross_revenue"]["value"])
        == total
    )
    counts = c.get("/api/map/region", params={"month": "2026-10", "measure": "recharge_count"})
    assert sum(Decimal(i["value"]) for i in counts.json()) == 100


def test_map_uf_filters_by_region_with_bound_parameter() -> None:
    c, wh = map_client()
    r = c.get("/api/map/uf", params={"month": "2026-10", "measure": "gross_revenue", "region": "N"})
    assert r.json() == [{"uf": "PA", "value": "1000.00"}]
    assert wh.calls[0][1]["region"] == "N"
    assert "N'" not in wh.calls[0][0]


def test_mom_change_is_computed_in_backend_and_null_without_base() -> None:
    c, wh = map_client()
    r = c.get("/api/map/region", params={"month": "2026-10", "measure": "mom_change"})
    assert r.json() == [{"region": "SE", "value": "50.00"}, {"region": "N", "value": None}]
    assert "MEASURE(`gross_revenue`)" in wh.calls[0][0]
    assert wh.calls[0][1] == {"month": M, "previous": P}
    ufs = c.get("/api/map/uf", params={"month": "2026-10", "measure": "mom_change"}).json()
    assert ufs == [
        {"uf": "SP", "value": "100.00"},
        {"uf": "RJ", "value": "0.00"},
        {"uf": "PA", "value": None},
    ]


def test_map_municipality_returns_code_name_value_and_skips_null_measure() -> None:
    c, wh = map_client()
    r = c.get(
        "/api/map/municipality", params={"month": "2026-10", "measure": "gross_revenue", "uf": "PA"}
    )
    assert r.json() == [
        {"municipality_ibge_code": "1500001", "municipality_name": "Belém", "value": "700.00"}
    ]
    assert wh.calls[0][1]["uf"] == "PA"


def test_invalid_arguments_are_400_and_never_reach_sql() -> None:
    c, wh = map_client()
    base = {"month": "2026-10", "measure": "gross_revenue"}
    cases = [
        ("/api/map/region", {**base, "measure": "foo"}),
        ("/api/map/region", {**base, "measure": "gross_revenue; DROP"}),
        ("/api/map/region", {**base, "month": "2026-13"}),
        ("/api/map/uf", {**base, "measure": "foo"}),
        ("/api/map/uf", {**base, "region": "XX"}),
        ("/api/map/uf", {**base, "region": "n"}),
        ("/api/map/municipality", {**base, "measure": "foo", "uf": "PA"}),
        ("/api/map/municipality", {**base, "uf": "XX"}),
        ("/api/map/municipality", {**base, "uf": "pa"}),
        ("/api/map/municipality", base),
    ]
    for path, params in cases:
        r = c.get(path, params=params)
        assert r.status_code == 400, (path, params)
        assert r.json()["detail"]["code"] == "INVALID_ARGUMENT"
    assert wh.calls == []


def test_month_without_data_is_404_at_every_level() -> None:
    c, _ = map_client()
    for path in ("/api/map/region", "/api/map/uf"):
        r = c.get(path, params={"month": "2020-01", "measure": "gross_revenue"})
        assert r.status_code == 404
    r = c.get(
        "/api/map/municipality", params={"month": "2020-01", "measure": "gross_revenue", "uf": "PA"}
    )
    assert r.status_code == 404


def test_map_responses_are_cached_and_failures_are_503() -> None:
    c, wh = map_client()
    params = {"month": "2026-10", "measure": "gross_revenue"}
    c.get("/api/map/region", params=params)
    c.get("/api/map/region", params=params)
    assert len(wh.calls) == 1

    def boom(sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        raise RuntimeError("connector secret detail")

    r = TestClient(create_app(executor=boom, cache=TTLCache())).get("/api/map/uf", params=params)
    assert r.status_code == 503 and "secret" not in r.text


def test_filter_without_rows_in_an_existing_month_is_empty_list_not_404() -> None:
    c, _ = map_client()
    r = c.get(
        "/api/map/uf", params={"month": "2026-10", "measure": "gross_revenue", "region": "CO"}
    )
    assert r.status_code == 200 and r.json() == []


def test_null_municipality_names_do_not_break_the_ordering() -> None:
    from atlas_web.map_data import _sorted

    items = [
        {"municipality_ibge_code": "2", "municipality_name": None, "value": Decimal("1")},
        {"municipality_ibge_code": "1", "municipality_name": None, "value": Decimal("1")},
    ]
    keys = ("municipality_ibge_code", "municipality_name")
    assert [i["municipality_ibge_code"] for i in _sorted(items, keys)] == ["1", "2"]


def test_cache_refresh_overwrites_and_keeps_old_value_on_failure() -> None:
    cache = TTLCache()
    cache.get_or_set(("k",), lambda: 1)
    assert cache.refresh(("k",), lambda: 2) == 2
    assert cache.get_or_set(("k",), lambda: 99) == 2

    def boom() -> int:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        cache.refresh(("k",), boom)
    assert cache.get_or_set(("k",), lambda: 99) == 2


def test_warm_cache_fills_the_latest_month_screen_then_requests_hit_the_cache() -> None:
    from atlas_web.app import warm_cache

    wh = MapWarehouse()
    cache = TTLCache()
    warm_cache(cache, "atlas_test", wh)
    calls = len(wh.calls)
    assert calls > 1
    c = TestClient(create_app(executor=wh, cache=cache, warm=False))
    month = M.strftime("%Y-%m")
    assert c.get("/api/months").is_success
    for measure in ("gross_revenue", "mom_change"):
        assert c.get("/api/map/region", params={"month": month, "measure": measure}).is_success
        assert c.get("/api/map/uf", params={"month": month, "measure": measure}).is_success
    assert len(wh.calls) == calls  # tudo veio do cache aquecido


def test_warm_cache_never_raises_when_the_warehouse_fails() -> None:
    from atlas_web.app import warm_cache

    def down(sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        raise RuntimeError("warehouse fora")

    warm_cache(TTLCache(), "atlas_test", down)


def test_lifespan_warms_in_background_and_refreshes_periodically() -> None:
    import threading

    wh = FakeWarehouse(ROWS)
    cache = TTLCache()
    done = threading.Event()
    refreshes: list[int] = []
    original = cache.refresh

    def spy(key: tuple[Any, ...], compute: Any) -> Any:
        if key == ("months",):
            refreshes.append(1)
            if len(refreshes) >= 2:
                done.set()
        return original(key, compute)

    cache.refresh = spy  # type: ignore[method-assign]
    with TestClient(create_app(executor=wh, cache=cache, refresh_interval_s=0.01)):
        assert done.wait(5)


def test_warm_cache_releases_each_worker_connection() -> None:
    from atlas_web.app import warm_cache

    released: list[int] = []
    warm_cache(TTLCache(), "atlas_test", MapWarehouse(), lambda: released.append(1))
    assert len(released) >= 2  # meses + uma por tarefa do pool


def _frontend(tmp_path: Any) -> tuple[Any, Any]:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<div id='root'></div>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    geo = tmp_path / "geo"
    (geo / "mun").mkdir(parents=True)
    (geo / "br-uf.json").write_text("{}")
    (geo / "mun" / "PA.json").write_text('{"x":1}')
    return static, geo


def test_serves_the_react_build_geo_and_keeps_api_routes(tmp_path: Any) -> None:
    static, geo = _frontend(tmp_path)
    c = TestClient(
        create_app(executor=FakeWarehouse(ROWS), cache=TTLCache(), static_dir=static, geo_dir=geo)
    )
    root = c.get("/")
    assert root.status_code == 200 and "root" in root.text
    assert c.get("/assets/app.js").status_code == 200
    assert c.get("/geo/br-uf.json").status_code == 200
    assert c.get("/geo/mun/PA.json").json() == {"x": 1}
    assert c.get("/api/health").json()["status"] == "healthy"
    assert c.get("/api/months").json() == {"months": ["2026-10", "2026-09"]}


def test_api_only_when_there_is_no_build(tmp_path: Any) -> None:
    c = TestClient(
        create_app(
            executor=FakeWarehouse(ROWS),
            cache=TTLCache(),
            static_dir=tmp_path / "nada",
            geo_dir=tmp_path / "nada",
        )
    )
    assert c.get("/").status_code == 404
    assert c.get("/api/health").status_code == 200


def test_committed_build_exists_and_references_only_committed_assets() -> None:
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "static"
    html = (static / "index.html").read_text()
    refs = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    assert refs, "index.html sem /assets/..."
    for ref in refs:
        assert (static / ref.lstrip("/")).is_file(), ref
