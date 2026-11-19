"""Lógica pura de `scripts/generate_agent_traffic.py` (P12.9). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "generate_agent_traffic", ROOT / "scripts" / "generate_agent_traffic.py"
)
assert _spec and _spec.loader
gen = importlib.util.module_from_spec(_spec)
sys.modules["generate_agent_traffic"] = gen
_spec.loader.exec_module(gen)

CASES = [{"question": "A?"}, {"question": "B?"}, {"id": "sem-pergunta"}]


def test_pick_questions_cycles_and_skips_cases_without_question() -> None:
    assert gen.pick_questions(CASES, 5) == ["A?", "B?", "A?", "B?", "A?"]


def test_pick_questions_empty_cases_or_zero_count() -> None:
    assert gen.pick_questions([], 3) == []
    assert gen.pick_questions(CASES, 0) == []


def test_build_body_is_a_responses_input() -> None:
    assert gen.build_body("oi") == {"input": [{"role": "user", "content": "oi"}]}


def test_ok_rate() -> None:
    assert gen.ok_rate([200, 200, 429, 0]) == 0.5
    assert gen.ok_rate([]) == 0.0


def test_golden_set_has_enough_questions() -> None:
    import yaml  # type: ignore[import-untyped]

    cases = yaml.safe_load((ROOT / "eval" / "golden_set.yaml").read_text(encoding="utf-8"))
    assert len(gen.pick_questions(cases, 40)) == 40
