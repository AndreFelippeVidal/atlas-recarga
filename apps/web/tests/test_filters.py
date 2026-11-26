"""Filtros `pos_type` e `distributor` e `/api/filters` (SPEC-007 §3 e §6, P15.3)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from atlas_web.app import create_app, warm_tasks
from atlas_web.cache import TTLCache
from fastapi.testclient import TestClient

M, P = date(2026, 10, 1), date(2026, 9, 1)

# (mês, região, UF, tipo de PDV, distribuidor, receita, recargas)
FACTS: list[tuple[date, str, str, str, str, str, int]] = [
    (M, "N", "PA", "pharmacy", "Alfa", "100.00", 10),
    (M, "N", "AM", "grocery", "Alfa", "50.00", 5),
    (M, "SE", "SP", "pharmacy", "Beta", "300.00", 20),
    (M, "SE", "SP", "newsstand", "Beta", "70.00", 7),
    (P, "N", "PA", "pharmacy", "Alfa", "80.00", 8),
    (P, "SE", "SP", "lottery", "Beta", "200.00", 10),
]
DIMS = {"region": 1, "uf": 2, "pos_type": 3, "distributor_name": 4}


class FilterWarehouse:
    """Aplica `pos_type`/`distributor` e agrupa como a metric view faria."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def __call__(self, sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        self.calls.append((sql, params))
        if "DISTINCT" in sql:
            return ["pos_type", "distributor_name"], [[f[3], f[4]] for f in FACTS]
        months = {params[k] for k in ("month", "previous") if k in params}
        rows = [
            f
            for f in FACTS
            if (not months or f[0] in months)
            and f[3] == params.get("pos_type", f[3])
            and f[4] == params.get("distributor", f[4])
            and f[1] == params.get("region", f[1])
            and f[2] == params.get("uf", f[2])
        ]
        if "WHERE" not in sql:  # list_months
            return ["m", "v"], [[m, Decimal("1.00")] for m in sorted({f[0] for f in FACTS})[::-1]]
        select = sql.split("FROM")[0]
        is_kpis = select.count("MEASURE(") == len(KPI_COLUMNS)
        keys = [d for d in ("region", "uf") if f"`{d}`" in select]
        measure = "" if is_kpis else re.search(r"MEASURE\(`(\w+)`\)", select).group(1)  # type: ignore[union-attr]
        groups: dict[tuple[Any, ...], list[Any]] = {}
        for f in rows:
            groups.setdefault((f[0], *(f[DIMS[d]] for d in keys)), []).append(f)
        out: list[list[Any]] = []
        for key, fs in groups.items():
            revenue, count = sum(Decimal(f[5]) for f in fs), sum(f[6] for f in fs)
            values = dict(zip(KPI_COLUMNS, [revenue, count, revenue / count, len(fs)], strict=True))
            lead = list(key) if "`recharge_month`" in select else list(key[1:])
            out.append([*lead, *values.values()] if is_kpis else [*lead, values[measure]])
        if is_kpis:
            return ["recharge_month", *KPI_COLUMNS], out
        return ["m", *keys, "value"], out


KPI_COLUMNS = ["gross_revenue", "recharge_count", "avg_ticket", "active_pos"]


def make() -> tuple[TestClient, FilterWarehouse]:
    wh = FilterWarehouse()
    return TestClient(create_app(executor=wh, cache=TTLCache(), warm=False)), wh


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_CATALOG", "atlas_test")


def total(items: list[dict[str, Any]]) -> Decimal:
    return sum((Decimal(i["value"]) for i in items), Decimal(0))


def test_filters_lists_distinct_values_sorted_and_is_cached() -> None:
    c, wh = make()
    assert c.get("/api/filters").json() == {
        "pos_types": ["grocery", "lottery", "newsstand", "pharmacy"],
        "distributors": ["Alfa", "Beta"],
    }
    c.get("/api/filters")
    assert len(wh.calls) == 1
    assert "MEASURE" not in wh.calls[0][0]


@pytest.mark.parametrize(
    "flt",
    [
        {"pos_type": "pharmacy"},
        {"distributor": "Beta"},
        {"pos_type": "pharmacy", "distributor": "Beta"},
    ],
)
def test_filtered_regions_and_ufs_sum_to_the_filtered_kpi(flt: dict[str, str]) -> None:
    c, _ = make()
    kpi = c.get("/api/kpis", params={"month": "2026-10", **flt}).json()
    for measure in ("gross_revenue", "recharge_count"):
        want = Decimal(kpi[measure]["value"])
        for level in ("region", "uf"):
            items = c.get(
                f"/api/map/{level}", params={"month": "2026-10", "measure": measure, **flt}
            ).json()
            assert total(items) == want
    expected = sum(
        Decimal(f[5])
        for f in FACTS
        if f[0] == M and f[3] == flt.get("pos_type", f[3]) and f[4] == flt.get("distributor", f[4])
    )
    assert Decimal(kpi["gross_revenue"]["value"]) == expected


def test_filters_are_bound_parameters_never_concatenated() -> None:
    c, wh = make()
    c.get("/api/kpis", params={"month": "2026-10", "pos_type": "pharmacy", "distributor": "Alfa"})
    sql, params = wh.calls[-1]
    assert "pharmacy" not in sql and "Alfa" not in sql
    assert "`pos_type` = :pos_type" in sql and "`distributor_name` = :distributor" in sql
    assert params["pos_type"] == "pharmacy" and params["distributor"] == "Alfa"


@pytest.mark.parametrize("path", ["/api/kpis", "/api/map/region", "/api/map/uf"])
def test_invalid_pos_type_is_400_before_sql(path: str) -> None:
    c, wh = make()
    r = c.get(path, params={"month": "2026-10", "measure": "gross_revenue", "pos_type": "foo"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_ARGUMENT"
    assert wh.calls == []


def test_invalid_pos_type_on_municipality_is_400() -> None:
    c, _ = make()
    params = {"month": "2026-10", "measure": "gross_revenue", "uf": "PA", "pos_type": "'; --"}
    assert c.get("/api/map/municipality", params=params).status_code == 400


def test_unknown_distributor_rereads_filters_once_then_400() -> None:
    c, wh = make()
    r = c.get("/api/kpis", params={"month": "2026-10", "distributor": "Zeta"})
    assert r.status_code == 400
    assert sum("DISTINCT" in sql for sql, _ in wh.calls) == 2  # cache frio + 1 releitura
    assert not any("MEASURE" in sql for sql, _ in wh.calls)


def test_distributor_added_after_cache_is_accepted_by_the_reread() -> None:
    c, _ = make()
    c.get("/api/filters")
    FACTS.append((M, "S", "RS", "grocery", "Gama", "10.00", 1))
    try:
        r = c.get("/api/kpis", params={"month": "2026-10", "distributor": "Gama"})
        assert r.status_code == 200
        assert r.json()["gross_revenue"]["value"] == "10.00"
    finally:
        FACTS.pop()


def test_cache_key_includes_the_filters() -> None:
    c, wh = make()
    base = {"month": "2026-10"}
    all_ = c.get("/api/kpis", params=base).json()["gross_revenue"]["value"]
    ph = c.get("/api/kpis", params={**base, "pos_type": "pharmacy"}).json()["gross_revenue"][
        "value"
    ]
    assert (all_, ph) == ("520.00", "400.00")
    n = len(wh.calls)
    c.get("/api/kpis", params={**base, "pos_type": "pharmacy"})
    assert len(wh.calls) == n


def test_month_without_recharge_in_the_cut_is_200_with_empty_state() -> None:
    c, _ = make()
    # Alfa não vende `newsstand` em lugar nenhum: o mês existe no total, o recorte é vazio
    params = {"month": "2026-10", "pos_type": "lottery", "distributor": "Beta"}
    kpi = c.get("/api/kpis", params=params)
    assert kpi.status_code == 200
    body = kpi.json()
    assert body["gross_revenue"] == {"value": "0.00", "previous": "200.00", "delta_pct": "-100.00"}
    assert body["recharge_count"]["value"] == "0"
    assert body["avg_ticket"]["value"] is None
    for level in ("region", "uf"):
        r = c.get(f"/api/map/{level}", params={**params, "measure": "gross_revenue"})
        assert (r.status_code, r.json()) == (200, [])
    mun = c.get("/api/map/municipality", params={**params, "measure": "gross_revenue", "uf": "PA"})
    assert (mun.status_code, mun.json()) == (200, [])


def test_empty_cut_with_empty_previous_month_has_zero_previous_and_null_delta() -> None:
    c, _ = make()
    params = {"month": "2026-10", "pos_type": "lottery", "distributor": "Alfa"}
    body = c.get("/api/kpis", params=params).json()
    assert body["gross_revenue"] == {"value": "0.00", "previous": "0.00", "delta_pct": None}
    assert body["avg_ticket"] == {"value": None, "previous": None, "delta_pct": None}


def test_first_month_of_series_keeps_null_previous_in_an_empty_cut() -> None:
    c, _ = make()
    params = {"month": "2026-09", "pos_type": "newsstand"}
    body = c.get("/api/kpis", params=params).json()
    assert body["gross_revenue"] == {"value": "0.00", "previous": None, "delta_pct": None}


def test_month_without_any_recharge_is_still_404_with_a_filter() -> None:
    c, _ = make()
    params = {"month": "2020-01", "pos_type": "pharmacy"}
    assert c.get("/api/kpis", params=params).status_code == 404
    r = c.get("/api/map/uf", params={**params, "measure": "gross_revenue"})
    assert r.status_code == 404


def test_warm_cache_keys_match_the_unfiltered_endpoint_keys() -> None:
    wh = FilterWarehouse()
    store = TTLCache()
    app = create_app(executor=wh, cache=store, warm=False)
    for key, compute in warm_tasks("atlas_test", wh, "2026-10"):
        store.refresh(key, compute)
    n = len(wh.calls)
    client = TestClient(app)
    client.get("/api/kpis", params={"month": "2026-10"})
    client.get("/api/map/region", params={"month": "2026-10", "measure": "gross_revenue"})
    client.get("/api/map/uf", params={"month": "2026-10", "measure": "gross_revenue"})
    assert len(wh.calls) == n
