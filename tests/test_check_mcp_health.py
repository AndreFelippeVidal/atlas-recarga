"""Lógica pura de `scripts/check_mcp_health.py` (P11.1). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_mcp_health", ROOT / "scripts" / "check_mcp_health.py"
)
assert _spec and _spec.loader
chk = importlib.util.module_from_spec(_spec)
sys.modules["check_mcp_health"] = chk
_spec.loader.exec_module(chk)


def test_healthy_payload_has_no_problems() -> None:
    payload = {"status": "healthy", "warehouse": "RUNNING", "version": "0.1.0"}
    assert chk.evaluate_health(payload) == []


def test_bad_payload_lists_problems() -> None:
    assert len(chk.evaluate_health({"status": "down"})) == 3


def test_bearer_token_extracts_and_rejects() -> None:
    assert chk.bearer_token({"Authorization": "Bearer abc"}) == "abc"
    with pytest.raises(ValueError, match="Bearer"):
        chk.bearer_token({})
