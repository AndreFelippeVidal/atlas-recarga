"""Checks of `scripts/check_readers_permissions.py` (P7.3). No workspace needed."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "check_readers_permissions", ROOT / "scripts" / "check_readers_permissions.py"
)
assert spec and spec.loader
check = importlib.util.module_from_spec(spec)
sys.modules["check_readers_permissions"] = check
spec.loader.exec_module(check)

DENIED = {"state": "FAILED", "error": {"message": "PERMISSION_DENIED: User does not have SELECT"}}
MISSING = {"state": "FAILED", "error": {"message": "TABLE_OR_VIEW_NOT_FOUND"}}
OK = {"state": "SUCCEEDED"}


def test_only_a_permission_failure_counts_as_denied() -> None:
    assert check.is_permission_denied(DENIED)
    assert not check.is_permission_denied(MISSING)
    assert not check.is_permission_denied(OK)
    assert not check.is_permission_denied({"state": "FAILED"})


def test_evaluate_passes_when_semantic_works_and_the_rest_is_denied() -> None:
    lines = check.evaluate({"semantic.mv_recharges": OK}, {"gold.fct_recharges": DENIED})
    assert all(line.startswith("ok") for line in lines)


def test_evaluate_flags_a_leak_and_a_broken_allow() -> None:
    lines = check.evaluate({"semantic.mv_recharges": DENIED}, {"gold.fct_recharges": OK})
    assert all(line.startswith("FALHA") for line in lines)


def test_denied_probe_on_a_missing_table_is_not_proof() -> None:
    assert check.evaluate({}, {"gold.x": MISSING})[0].startswith("FALHA")


def test_reads_only_the_closed_lists() -> None:
    assert check.ALLOWED == (("semantic", "mv_recharges"),)
    assert {s for s, _ in check.DENIED} == {"gold", "silver", "bronze", "commission"}
    assert "MEASURE(gross_revenue)" in check.build_select("atlas_dev", "semantic", "mv_recharges")
    assert check.build_select("atlas_dev", "gold", "fct_recharges").endswith("LIMIT 1")


def test_main_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    argv = ["--target", "dev", "--profile", "r", "--warehouse-id", "w"]
    monkeypatch.setattr(check, "_status", lambda _p, _w, sql: OK if "MEASURE" in sql else DENIED)
    assert check.main(argv) == 0
    monkeypatch.setattr(check, "_status", lambda *_a: OK)
    assert check.main(argv) == 1
