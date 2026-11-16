"""Lógica pura de `scripts/check_agent_functions.py` (P10.1). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_agent_functions", ROOT / "scripts" / "check_agent_functions.py"
)
assert _spec and _spec.loader
chk = importlib.util.module_from_spec(_spec)
sys.modules["check_agent_functions"] = chk
_spec.loader.exec_module(chk)


def test_queries_use_the_catalog_and_the_closed_lists() -> None:
    q = chk.direct_query("atlas_dev", "gross_revenue", "municipality", "2026-10-01")
    assert "MEASURE(gross_revenue)" in q and "municipality_ibge_code" in q
    f = chk.function_query("atlas_dev", "gross_revenue", "uf", "2026-10-01")
    assert "atlas_dev.semantic.fn_metric_by_region('gross_revenue', 'uf'" in f


def test_compare_rows_matches_within_the_function_rounding() -> None:
    assert chk.compare_rows([["N", "10.00"]], [["N", "10.000000"]]) is None
    assert chk.compare_rows([["N", "10.00"]], [["N", "10.01"]])
    assert chk.compare_rows([["N", "1"]], [["S", "1"]])
    assert chk.compare_rows([], [])


def test_compare_change_checks_values_and_difference() -> None:
    a, b = [["N", "100"], ["S", "50"]], [["N", "110"], ["S", "40"]]
    ok = [["N", "100", "110", "10"], ["S", "50", "40", "-10"]]
    assert chk.compare_change(a, b, ok) is None
    assert chk.compare_change(a, b, [["N", "100", "110", "11"], ["S", "50", "40", "-10"]])
    assert chk.compare_change(a, b, ok[:1])


def test_rejects_bad_month(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        chk.main(
            ["--target", "dev", "--profile", "x", "--warehouse-id", "w",
             "--month", "2026-10-15; DROP", "--previous-month", "2026-09-01"]
        )  # fmt: skip
