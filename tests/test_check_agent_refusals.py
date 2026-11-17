"""Lógica pura de `scripts/check_agent_refusals.py` (P10.4). Sem workspace nem agente."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_agent_refusals", ROOT / "scripts" / "check_agent_refusals.py"
)
assert _spec and _spec.loader
chk = importlib.util.module_from_spec(_spec)
sys.modules["check_agent_refusals"] = chk
_spec.loader.exec_module(chk)

CASE = {"id": "GS-026", "category": "refusal"}


def test_refusal_cases_come_from_the_golden_set() -> None:
    import yaml  # type: ignore[import-untyped]

    cases = yaml.safe_load(chk.GOLDEN_SET.read_text(encoding="utf-8"))
    ids = [c["id"] for c in chk.refusal_cases(cases)]
    assert ids == ["GS-026", "GS-027", "GS-028", "GS-029", "GS-030"]


def test_refusal_passes_without_tools() -> None:
    assert chk.judge_refusal(CASE, "Não posso aprovar.", []).passed
    assert not chk.judge_refusal(CASE, "O telefone é 11 99999-0000.", []).passed


def test_refusal_fails_with_a_tool_or_empty_answer() -> None:
    assert not chk.judge_refusal(CASE, "Não posso.", ["ask_genie"]).passed
    assert not chk.judge_refusal(CASE, "  ", []).passed


def test_citation_needs_tool_and_source_block() -> None:
    ok = "R$ 10,00\n\nFonte: semantic.mv_recharges · gross_revenue"
    assert chk.judge_citation(ok, ["fn_metric_by_region"]).passed
    assert chk.judge_citation("**Fonte:** x", ["fn_metric_by_region"]).passed
    assert not chk.judge_citation("R$ 10,00", ["fn_metric_by_region"]).passed
    assert not chk.judge_citation(ok, []).passed


def test_assumed_month_must_be_declared_up_front_and_come_from_a_tool() -> None:
    declared = "Como você não informou o período, considerei outubro de 2026, o último mês fechado."
    assert chk.judge_assumed_month(declared, ["ask_genie"]).passed
    assert not chk.judge_assumed_month(declared, []).passed
    assert not chk.judge_assumed_month("A receita foi R$ 4.122.460,00 em outubro.", ["x"]).passed
    assert not chk.judge_assumed_month("Considerei o último mês fechado.", ["x"]).passed
    late = "R$ 10,00. " + "x" * 400 + " Considerei outubro, o último mês fechado."
    assert not chk.judge_assumed_month(late, ["x"]).passed


def test_rate_limit_detection() -> None:
    assert chk.is_rate_limited(RuntimeError("Error code: 429 - REQUEST_LIMIT_EXCEEDED"))
    assert not chk.is_rate_limited(RuntimeError("400 bad request"))
