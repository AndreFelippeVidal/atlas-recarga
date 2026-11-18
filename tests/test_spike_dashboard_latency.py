"""Partes puras do spike P12.10 (as medições em si rodam no workspace, com o mantenedor)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import spike_dashboard_latency as spike


def test_percentile_nearest_rank() -> None:
    samples = [float(n) for n in range(1, 101)]
    assert spike.percentile(samples, 50) == 50.0
    assert spike.percentile(samples, 95) == 95.0
    assert spike.percentile([7.0], 95) == 7.0


def test_percentile_rejects_empty() -> None:
    with pytest.raises(ValueError, match="sem amostras"):
        spike.percentile([], 95)


def test_plan_covers_the_three_map_levels() -> None:
    paths = {path for _, path, _ in spike.endpoint_plan("2026-10", "SP")}
    assert paths == {
        "/api/months",
        "/api/kpis",
        "/api/map/region",
        "/api/map/uf",
        "/api/map/municipality",
    }


def test_aggregate_is_derived_from_the_metric_view_only() -> None:
    sql = spike._agg_sql("atlas_dev")
    assert sql.count("MEASURE(") == 3 * len(spike.MEASURES)
    assert sql.count("atlas_dev.semantic.mv_recharges") == 3
    for forbidden in ("gold.", "silver.", "bronze.", "commission."):
        assert forbidden not in sql
    assert "atlas_dev.semantic.spike_map_agg" in sql


def test_geometry_rows_use_real_files() -> None:
    rows = spike.geometry_rows("SP")
    assert len(rows) == 2
    assert "geo/br-uf.json" in rows[0]
