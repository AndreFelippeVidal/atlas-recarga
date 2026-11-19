"""Partes puras de `scripts/measure_web_p95.py` (a medição roda no workspace, com o mantenedor)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import measure_web_p95 as m


def test_percentile_nearest_rank() -> None:
    assert m.percentile([float(n) for n in range(1, 101)], 95) == 95.0
    assert m.percentile([5.0], 95) == 5.0
    with pytest.raises(ValueError):
        m.percentile([], 95)


def test_there_are_27_distinct_ufs() -> None:
    assert len(m.UFS) == 27 == len(set(m.UFS))


def test_measure_makes_one_cold_call_per_uf_and_measure_and_collects_failures() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def get(path: str, params: dict[str, str]) -> tuple[int, float]:
        calls.append((path, params))
        return (503, 0.0) if params["uf"] == "PA" else (200, 100.0)

    samples, failures = m.measure(
        get, "2026-10", ufs=("PA", "SP"), measures=("gross_revenue", "mom_change")
    )
    assert len(calls) == 4
    assert all(path == "/api/map/municipality" for path, _ in calls)
    assert samples == [100.0, 100.0]
    assert failures == ["gross_revenue/PA: HTTP 503", "mom_change/PA: HTTP 503"]


def test_summarize() -> None:
    stats = m.summarize([300.0, 100.0, 200.0])
    assert (stats["n"], stats["min"], stats["p50"], stats["max"]) == (3.0, 100.0, 200.0, 300.0)


def test_measures_match_the_api_measures() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "web"))
    from atlas_web.map_data import MAP_MEASURES

    assert set(m.MEASURES) == set(MAP_MEASURES)
