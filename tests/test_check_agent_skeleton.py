"""Lógica pura de `scripts/check_agent_skeleton.py` (P10.2). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_agent_skeleton", ROOT / "scripts" / "check_agent_skeleton.py"
)
assert _spec and _spec.loader
chk = importlib.util.module_from_spec(_spec)
sys.modules["check_agent_skeleton"] = chk
_spec.loader.exec_module(chk)

GOOD_APP = {
    "name": "agent-atlas",
    "app_status": {"state": "RUNNING"},
    "service_principal_client_id": "abcd-1234",
}


def test_app_running_is_ok() -> None:
    assert chk.evaluate_app(GOOD_APP) == []


def test_app_stopped_or_renamed_fails() -> None:
    assert chk.evaluate_app({**GOOD_APP, "app_status": {"state": "UNAVAILABLE"}})
    assert chk.evaluate_app({**GOOD_APP, "name": "atlas-agent"})
    assert chk.evaluate_app({**GOOD_APP, "service_principal_client_id": ""})


def test_usage_query_filters_by_requester_and_window() -> None:
    q = chk.usage_query("abcd-1234", 3)
    assert "requester = 'abcd-1234'" in q and "INTERVAL 3 HOURS" in q


@pytest.mark.parametrize(
    ("requester", "hours"), [("x'; DROP", 3), ("abcd-1234", 0), ("abcd-1234", 99)]
)
def test_usage_query_rejects_bad_input(requester: str, hours: int) -> None:
    with pytest.raises(ValueError):
        chk.usage_query(requester, hours)


def test_usage_needs_a_200_on_the_expected_model_service() -> None:
    good = [["2026-11-16", "MODEL_SERVICE", "system.ai.gpt-oss-120b", "200", "10", "5"]]
    assert chk.evaluate_usage(good) == []
    assert chk.evaluate_usage([])
    bad = [["2026-11-16", "MODEL_SERVICE", "system.ai.gpt-oss-120b", "429", "0", "0"]]
    assert chk.evaluate_usage(bad)
