"""Lógica pura de `scripts/check_agent_monitoring.py` (P10.8). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_agent_monitoring", ROOT / "scripts" / "check_agent_monitoring.py"
)
assert _spec
assert _spec.loader
chk = importlib.util.module_from_spec(_spec)
sys.modules["check_agent_monitoring"] = chk
_spec.loader.exec_module(chk)


def row(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "traces": 100,
        "traces_missing_code_scorers": 0,
        "traces_with_judge": 20,
        "failures_not_queued": 0,
        "queued_too_late": 0,
        "open_in_queue": 3,
    }
    return base | over


def failed(r: dict[str, Any]) -> list[str]:
    return [name for name, ok, _ in chk.evaluate(r) if not ok]


def test_all_good() -> None:
    assert failed(row()) == []


def test_no_traces_fails() -> None:
    assert failed(row(traces=0, traces_with_judge=0)) == ["há traces pontuados"]


def test_missing_code_scorers_fails() -> None:
    assert failed(row(traces_missing_code_scorers=2)) == ["scorers de código em 100% dos traces"]


@pytest.mark.parametrize(("judged", "ok"), [(15, True), (25, True), (14, False), (26, False)])
def test_judge_sample_needs_20_percent_within_5_points(judged: int, ok: bool) -> None:
    assert (failed(row(traces_with_judge=judged)) == []) is ok


def test_judge_sample_is_informative_below_100_traces() -> None:
    assert failed(row(traces=40, traces_with_judge=0)) == []


def test_failures_must_be_queued_and_on_time() -> None:
    assert failed(row(failures_not_queued=1)) == ["toda falha está na review_queue"]
    assert failed(row(queued_too_late=1)) == ["a fila recebeu em até 24 h"]


def test_sql_rejects_a_bad_catalog_and_is_read_only() -> None:
    with pytest.raises(ValueError, match="catálogo"):
        chk.summary_sql("x; DROP TABLE y")
    sql = chk.summary_sql("atlas_dev").upper()
    assert sql.lstrip().startswith("SELECT")
    for word in ("INSERT", "UPDATE", "DELETE", "DROP", "MERGE"):
        assert word not in sql
