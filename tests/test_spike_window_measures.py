"""Partes puras do spike P15.2 (a execução em si roda no workspace, com o mantenedor)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import spike_window_measures as spike


@pytest.mark.parametrize("version", ["1.1", "0.1"])
def test_yaml_is_valid_and_has_windows(version: str) -> None:
    doc = yaml.safe_load(spike.build_yaml("atlas_dev", version))
    assert str(doc["version"]) == version
    measures = {m["name"]: m for m in doc["measures"]}
    assert measures["revenue_ytd"]["window"][0]["order"] == "recharge_year"
    assert measures["revenue_trailing2"]["window"][0]["range"] == "trailing 2 month"
    assert ("synonyms" in measures["gross_revenue"]) == (version == "1.1")


def test_yaml_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="version"):
        spike.build_yaml("atlas_dev", "2.0")


def test_queries_filter_month_and_group() -> None:
    view = spike.build_view_query("c", "uf", "pos_type", "2026-10-01")
    assert "WHERE recharge_month = DATE'2026-10-01' AND pos_type = 'pharmacy'" in view
    gold = spike.build_gold_query("c", "uf", "pos_type", "2026-10-01")
    assert "PARTITION BY uf" in gold and "c.gold.fct_recharges" in gold


def test_compare_rows_equal_and_different() -> None:
    view = [["SP", "2026-10-01", "10.00", "x", "30.00", "40.00", "0.12341"]]
    same = [["SP", "2026-10-01", "10.00", "30.00", "40.00", "0.12344"]]
    assert spike.compare_rows(view, same, 2) == []  # mom igual em 4 casas
    other = [["SP", "2026-10-01", "10.00", "30.01", "40.00", None]]
    problems = spike.compare_rows(view, other, 2)
    assert any("t3" in p for p in problems) and any("mom" in p for p in problems)
    assert spike.compare_rows([], other, 2) == ["('SP', '2026-10-01'): linha só no gold"]
