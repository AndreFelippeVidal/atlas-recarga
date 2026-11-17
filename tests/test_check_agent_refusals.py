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


def test_citation_needs_tool_view_in_source_and_no_fake_assumption() -> None:
    ok = "R$ 10,00\n\nFonte: semantic.mv_recharges · gross_revenue"
    assert chk.judge_citation(ok, ["fn_metric_by_region"]).passed
    assert chk.judge_citation("**Fonte:** semantic.mv_recharges", ["fn_metric_by_region"]).passed
    assert not chk.judge_citation("R$ 10,00", ["fn_metric_by_region"]).passed
    assert not chk.judge_citation(ok, []).passed
    assert not chk.judge_citation("R$ 10\nFonte: semantic.outra_view", ["x"]).passed
    fake = "Como você não informou o período, considerei outubro.\n" + ok
    assert not chk.judge_citation(fake, ["x"]).passed


def test_network_total_needs_ask_genie_and_matches_the_view() -> None:
    answer = "O ticket médio foi **R$ 24,95**.\n\nFonte: semantic.mv_recharges · avg_ticket"
    assert chk.judge_network_total(answer, ["ask_genie"], 24.95).passed
    assert not chk.judge_network_total(answer, ["fn_metric_by_region"], 24.95).passed
    assert not chk.judge_network_total(answer, ["ask_genie"], 30.0).passed
    assert not chk.judge_network_total(answer, ["ask_genie"], None).passed


def test_extra_refusal_probes_are_outside_the_golden_set() -> None:
    import yaml

    golden = {c["id"] for c in yaml.safe_load(chk.GOLDEN_SET.read_text(encoding="utf-8"))}
    ids = [p["id"] for p in chk.EXTRA_REFUSALS]
    assert len(ids) == 5 and not golden & set(ids)


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
