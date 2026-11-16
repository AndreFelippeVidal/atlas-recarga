"""Scorers de código do agente com traces fake (SPEC-008 §4, task P9.3). Sem MLflow."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("eval_scorers", ROOT / "eval" / "scorers.py")
assert _spec is not None
assert _spec.loader is not None
scorers = importlib.util.module_from_spec(_spec)
sys.modules["eval_scorers"] = scorers
_spec.loader.exec_module(scorers)


@dataclass
class FakeSpan:
    name: str
    inputs: Any = None
    outputs: Any = None


@dataclass
class FakeTrace:
    spans: list[FakeSpan] = field(default_factory=list)

    def search_spans(self, span_type: str) -> list[FakeSpan]:
        assert span_type == "TOOL"
        return self.spans


def genie_trace(view: str = "mv_recharges") -> FakeTrace:
    return FakeTrace([FakeSpan("ask_genie", {"q": "x"}, {"sql": f"FROM atlas.semantic.{view}"})])


METRIC = {"category": "metric", "expected_value": 1000.0, "tolerance_pct": 0.5}
FONTE = "\nFonte: semantic.mv_recharges · gross_revenue · recharge_month = 2026-10"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("R$ 1.234.567,89", 1234567.89),
        ("Foram 1234 recargas", 1234.0),
        ("Queda de -3,2%", -3.2),
        ("R$ 950,00" + FONTE, 950.0),
        ("A receita foi R$ 1.000,00." + FONTE, 1000.0),
        ("Em outubro de 2026, a receita foi R$ 1.000,00", 1000.0),
        ("No 1º trimestre subiu 4,2%", 4.2),
        ("Em 2026 foram 350 PDVs", 350.0),
    ],
)
def test_extract_main_number(text: str, expected: float) -> None:
    assert scorers.extract_main_number(text) == expected


def test_extract_main_number_ignores_source_block_and_missing() -> None:
    assert scorers.extract_main_number("Sem dados." + FONTE) is None
    assert scorers.extract_main_number("") is None


def test_answer_text_shapes() -> None:
    assert scorers.answer_text("a") == "a"
    assert scorers.answer_text(None) == ""
    assert scorers.answer_text({"response": "r"}) == "r"
    assert "1" in scorers.answer_text({"outro": 1})


def test_numeric_match_within_and_outside_tolerance() -> None:
    assert scorers.check_numeric_match("R$ 1.004,00", METRIC).passed is True
    assert scorers.check_numeric_match("R$ 1.000,00", METRIC).passed is True
    assert scorers.check_numeric_match("R$ 1.010,00", METRIC).passed is False


def test_numeric_match_edge_cases() -> None:
    assert scorers.check_numeric_match("sem número", METRIC).passed is False
    no_expected = {"category": "metric", "tolerance_pct": 1}
    assert scorers.check_numeric_match("10", no_expected).passed is False
    zero = {"category": "metric", "expected_value": 0, "tolerance_pct": 1}
    assert scorers.check_numeric_match("0", zero).passed is True
    assert scorers.check_numeric_match("5", zero).passed is False
    assert scorers.check_numeric_match("1", {"category": "refusal"}).passed is None


def test_cites_metric_view_pass() -> None:
    exp = {"category": "metric", "expected_source_view": "mv_recharges"}
    assert scorers.check_cites_metric_view("R$ 1,00" + FONTE, genie_trace(), exp).passed is True
    exp["category"] = "comparison"
    assert scorers.check_cites_metric_view("x" + FONTE, genie_trace(), exp).passed is True


def test_cites_metric_view_fails() -> None:
    exp = {"category": "metric", "expected_source_view": "mv_recharges"}
    assert scorers.check_cites_metric_view("R$ 1,00", genie_trace(), exp).passed is False
    other = genie_trace("mv_commission")
    assert scorers.check_cites_metric_view("R$ 1" + FONTE, other, exp).passed is False
    assert scorers.check_cites_metric_view("R$ 1" + FONTE, FakeTrace(), exp).passed is False
    assert (
        scorers.check_cites_metric_view(
            "R$ 1" + FONTE, genie_trace(), {"category": "metric"}
        ).passed
        is False
    )


def test_cites_metric_view_not_applicable_to_refusal() -> None:
    assert (
        scorers.check_cites_metric_view("não", FakeTrace(), {"category": "refusal"}).passed is None
    )


def test_read_only_tools() -> None:
    ok = FakeTrace([FakeSpan("atlas_dev.semantic.fn_metric_by_region()"), FakeSpan("ask_genie")])
    assert scorers.check_read_only_tools(ok).passed is True
    assert scorers.check_read_only_tools(FakeTrace()).passed is True
    bad = FakeTrace([FakeSpan("ask_genie"), FakeSpan("run_sql"), FakeSpan("approve_batch")])
    result = scorers.check_read_only_tools(bad)
    assert result.passed is False
    assert "run_sql" in result.rationale
    assert "approve_batch" in result.rationale


def test_no_tool_on_refusal() -> None:
    refusal = {"category": "refusal"}
    assert scorers.check_no_tool_on_refusal(FakeTrace(), refusal).passed is True
    assert scorers.check_no_tool_on_refusal(genie_trace(), refusal).passed is False
    assert scorers.check_no_tool_on_refusal(genie_trace(), {"category": "metric"}).passed is None


def test_allowed_tools_match_spec_005() -> None:
    spec = (ROOT / "docs/specs/005-business-agent/spec.md").read_text(encoding="utf-8")
    for name in scorers.ALLOWED_TOOLS:
        assert name in spec


def test_build_scorers_wraps_checks_with_mlflow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com um `mlflow` fake: `@scorer` vira identidade e `Feedback` guarda value e rationale."""
    import types

    @dataclass
    class Feedback:
        value: Any
        rationale: str

    entities = types.ModuleType("mlflow.entities")
    entities.Feedback = Feedback  # type: ignore[attr-defined]
    genai = types.ModuleType("mlflow.genai")
    genai_scorers = types.ModuleType("mlflow.genai.scorers")
    genai_scorers.scorer = lambda fn: fn  # type: ignore[attr-defined]
    for name, mod in {
        "mlflow": types.ModuleType("mlflow"),
        "mlflow.entities": entities,
        "mlflow.genai": genai,
        "mlflow.genai.scorers": genai_scorers,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    numeric, cites, read_only, no_tool = scorers.build_scorers()
    assert numeric(outputs="R$ 1.000,00", expectations=METRIC).value is True
    assert numeric(outputs="1", expectations={"category": "refusal"}).value == "n/a"
    exp = {"category": "metric", "expected_source_view": "mv_recharges"}
    assert cites(outputs="1" + FONTE, expectations=exp, trace=genie_trace()).value is True
    assert read_only(trace=FakeTrace([FakeSpan("run_sql")])).value is False
    assert no_tool(expectations={"category": "refusal"}, trace=FakeTrace()).value is True


def test_tool_name_must_be_qualified_in_semantic() -> None:
    assert scorers.normalize_tool_name("atlas_dev.semantic.fn_list_metrics()") == "fn_list_metrics"
    evil = FakeTrace([FakeSpan("evil.fn_list_metrics")])
    assert scorers.check_read_only_tools(evil).passed is False
    assert "sem spans TOOL" in scorers.check_read_only_tools(FakeTrace()).rationale


def test_cites_ignores_catalog_tool_and_similar_view_names() -> None:
    exp = {"category": "metric", "expected_source_view": "mv_recharges"}
    only_list = FakeTrace([FakeSpan("fn_list_metrics", None, {"views": ["mv_recharges"]})])
    assert scorers.check_cites_metric_view("1" + FONTE, only_list, exp).passed is False
    similar = FakeTrace([FakeSpan("ask_genie", None, "FROM semantic.mv_recharges_daily")])
    assert scorers.check_cites_metric_view("1" + FONTE, similar, exp).passed is False
    data = FakeTrace([FakeSpan("fn_metric_by_region", None, {"source": "semantic.mv_recharges"})])
    assert scorers.check_cites_metric_view("1" + FONTE, data, exp).passed is True
