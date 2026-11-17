"""Lógica pura de `scripts/check_agent_guardrails.py` (P10.5). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_agent_guardrails", ROOT / "scripts" / "check_agent_guardrails.py"
)
assert _spec and _spec.loader
chk = importlib.util.module_from_spec(_spec)
sys.modules["check_agent_guardrails"] = chk
_spec.loader.exec_module(chk)

GOOD: dict[str, Any] = {
    "config": {
        "routing": {
            "destinations": [{"pay_per_token_config": {"model": "models/system.ai.gpt-oss-120b"}}]
        },
        "rate_limits": [
            {
                "key": "RATE_LIMIT_KEY_USER_DEFAULT",
                "renewal_period": "RATE_LIMIT_RENEWAL_PERIOD_MINUTE",
                "requests": "30",
            },
            {
                "key": "RATE_LIMIT_KEY_SERVICE",
                "renewal_period": "RATE_LIMIT_RENEWAL_PERIOD_HOUR",
                "tokens": 500000,
            },
        ],
        "inference_table": {"parent": "schemas/atlas_dev.observability"},
    }
}


def test_service_ok() -> None:
    assert chk.evaluate_service(GOOD) == []


def test_service_reports_each_missing_piece() -> None:
    assert len(chk.evaluate_service({})) == 4
    no_limits = {"config": {**GOOD["config"], "rate_limits": []}}
    assert len(chk.evaluate_service(no_limits)) == 2


def test_service_wrong_numbers_fail() -> None:
    limits = [dict(r) for r in GOOD["config"]["rate_limits"]]
    limits[0]["requests"] = 60
    assert chk.evaluate_service({"config": {**GOOD["config"], "rate_limits": limits}})


def test_burst_needs_a_429_and_no_other_error() -> None:
    assert chk.evaluate_burst(["ok"] * 30 + ["429"] * 5) == []
    assert chk.evaluate_burst(["ok"] * 40)
    assert chk.evaluate_burst(["ok", "429", "erro: boom"])


def test_classify() -> None:
    assert chk.classify(0, "") == "ok"
    assert chk.classify(1, "Error: 429 Too Many Requests") == "429"
    assert chk.classify(1, "REQUEST_LIMIT_EXCEEDED") == "429"
    assert chk.classify(1, "boom").startswith("erro:")


def test_payload_rows() -> None:
    assert chk.evaluate_payload_rows([["3"]]) == []
    assert chk.evaluate_payload_rows([["0"]])
    assert chk.evaluate_payload_rows([])


def test_burst_body_uses_three_part_name_and_one_token() -> None:
    body = chk.burst_body("atlas_dev.observability.agent_llm")
    assert body["model"].count(".") == 2 and body["max_tokens"] == 1
