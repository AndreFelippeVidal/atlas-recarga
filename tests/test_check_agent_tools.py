"""Lógica pura de `scripts/check_agent_tools.py` (P10.3). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_agent_tools", ROOT / "scripts" / "check_agent_tools.py"
)
assert _spec and _spec.loader
chk = importlib.util.module_from_spec(_spec)
sys.modules["check_agent_tools"] = chk
_spec.loader.exec_module(chk)


def test_app_running() -> None:
    app = {
        "name": "agent-atlas",
        "app_status": {"state": "RUNNING"},
        "service_principal_client_id": "abcd-1234",
    }
    assert chk.evaluate_app(app) == []
    assert chk.evaluate_app({**app, "app_status": {"state": "UNAVAILABLE"}})


def test_expected_query_uses_catalog_and_rejects_injection() -> None:
    assert "atlas_dev.semantic.mv_recharges" in chk.expected_revenue_query("atlas_dev")
    with pytest.raises(ValueError):
        chk.expected_revenue_query("atlas; DROP")


def test_request_tags_query_validates() -> None:
    assert "abcd-1234" in chk.request_tags_query("abcd-1234", 3)
    with pytest.raises(ValueError):
        chk.request_tags_query("x'; --", 3)
    with pytest.raises(ValueError):
        chk.request_tags_query("abcd-1234", 0)


def test_evaluate_expected() -> None:
    assert chk.evaluate_expected([["48880720.00"]]) == []
    assert chk.evaluate_expected([])
    assert chk.evaluate_expected([[None]])


def test_evaluate_request_tags() -> None:
    ok = [["t", "MODEL_SERVICE", "system.ai.gpt-oss-120b", '{"app":"agent-atlas"}']]
    assert chk.evaluate_request_tags(ok) == []
    assert chk.evaluate_request_tags([])
    empty = [["t", "MODEL_SERVICE", "system.ai.gpt-oss-120b", None]]
    assert "request_tags" in chk.evaluate_request_tags(empty)[0]
