"""Lógica pura de `eval/run_offline_eval.py` (P10.6). Sem MLflow, agente nem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "run_offline_eval", ROOT / "eval" / "run_offline_eval.py"
)
assert _spec
assert _spec.loader
run = importlib.util.module_from_spec(_spec)
sys.modules["run_offline_eval"] = run
_spec.loader.exec_module(run)

OK = {"numeric_match": True, "cites_metric_view": True, "read_only_tools": True}


def case(case_id: str, category: str, **scores: Any) -> Any:
    return run.CaseScore(case_id, category, {**OK, **scores})


def test_case_passes_only_if_every_applicable_scorer_passes() -> None:
    assert run.case_passed(OK) is True
    assert run.case_passed({**OK, "numeric_match": False}) is False
    # `n/a` (scorer de outra categoria) não conta, nem a favor nem contra
    assert run.case_passed({**OK, "no_tool_on_refusal": "n/a"}) is True
    assert run.case_passed({"numeric_match": "n/a"}) is None


@pytest.mark.parametrize("value", [True, "yes", "pass", "True"])
def test_pass_values(value: Any) -> None:
    assert run.is_pass(value) is True


@pytest.mark.parametrize("value", [False, "no", "fail", 0, None])
def test_non_pass_values(value: Any) -> None:
    assert run.is_pass(value) is False


def test_summary_by_category_and_failures() -> None:
    cases = [
        case("GS-001", "metric"),
        case("GS-002", "metric", numeric_match=False),
        case("GS-026", "refusal", no_tool_on_refusal=True),
        case("GS-031", "no_period", declares_assumed_month=True),
    ]
    summary = run.summarize(cases)
    assert summary.total == 4
    assert summary.accuracy == 0.75
    assert summary.by_category == {"metric": 0.5, "no_period": 1.0, "refusal": 1.0}
    assert [f.case_id for f in summary.failures] == ["GS-002"]
    assert summary.failures[0].failed_scorers() == ["numeric_match"]
    assert summary.meets_target is False


def test_meets_target_needs_90_percent_and_no_refusal_failure() -> None:
    passing = [case(f"GS-{i:03d}", "metric") for i in range(1, 10)]
    one_failure = [case("GS-010", "metric", numeric_match=False)]
    assert run.summarize(passing + one_failure).meets_target is True  # 90%
    refusal = case("GS-026", "refusal", no_tool_on_refusal=False)
    summary = run.summarize([*passing * 3, refusal])  # 96%, mas uma recusa falhou
    assert summary.accuracy >= run.TARGET_ACCURACY
    assert summary.meets_target is False


def test_summary_without_cases_is_an_error() -> None:
    with pytest.raises(ValueError, match="nenhum caso"):
        run.summarize([])


def test_scores_from_result_df_rows() -> None:
    rows = [
        {
            "expectations": {"id": "GS-031", "category": "no_period"},
            "declares_assumed_month/value": False,
            "declares_assumed_month/rationale": "o começo da resposta cita nenhum",
            "numeric_match/value": "n/a",
            "read_only_tools/value": True,
            "outputs": "ignorado",
        }
    ]
    (scored,) = run.scores_from_result_df(rows)
    assert (scored.case_id, scored.category) == ("GS-031", "no_period")
    assert scored.scores["numeric_match"] == "n/a"
    assert scored.passed is False
    assert scored.failed_scorers() == ["declares_assumed_month"]
    assert "cita nenhum" in scored.rationales["declares_assumed_month"]
    text = run.format_summary(run.summarize([scored]), "run-1")
    assert "acurácia 0.0%" in text
    assert "FALHA GS-031 (no_period) declares_assumed_month: o começo" in text


def test_expected_values_are_recomputed_from_the_sql() -> None:
    records = [
        {"inputs": {"question": "a"}, "expectations": {"id": "A", "reference_sql": "SQL-1"}},
        {
            "inputs": {"question": "b"},
            "expectations": {
                "id": "B",
                "reference_sql": "SQL-2",
                "reference_month_sql": "SQL-M",
            },
        },
        {"inputs": {"question": "c"}, "expectations": {"id": "C", "category": "refusal"}},
    ]
    answers = {"SQL-1": "10.50", "SQL-2": "1000", "SQL-M": "2026-10-01"}
    out = run.with_expected_values(records, answers.__getitem__)
    assert out[0]["expectations"]["expected_value"] == 10.5
    assert out[1]["expectations"]["expected_value"] == 1000.0
    assert out[1]["expectations"]["expected_month"] == "2026-10-01"
    assert "expected_value" not in out[2]["expectations"]
    assert "expected_value" not in records[0]["expectations"]  # não altera a entrada


@pytest.mark.parametrize("raw", [None, "abc", ""])
def test_expected_value_must_be_numeric(raw: str | None) -> None:
    with pytest.raises(ValueError, match="número"):
        run.parse_value(raw)


def test_expected_month_must_be_a_date() -> None:
    records = [{"inputs": {}, "expectations": {"id": "B", "reference_month_sql": "SQL-M"}}]
    with pytest.raises(ValueError, match="data"):
        run.with_expected_values(records, lambda _sql: "outubro")


def test_first_cell() -> None:
    response = SimpleNamespace(result=SimpleNamespace(data_array=[["7"]]))
    assert run.first_cell(response) == "7"
    assert run.first_cell(SimpleNamespace(result=None)) is None
    assert run.first_cell(SimpleNamespace(result=SimpleNamespace(data_array=[]))) is None


def test_rate_limit_detection_and_run_url() -> None:
    assert run.is_rate_limited(RuntimeError("Error code: 429"))
    assert run.is_rate_limited(RuntimeError("REQUEST_LIMIT_EXCEEDED"))
    assert not run.is_rate_limited(RuntimeError("boom"))
    assert run.run_url("https://x.cloud.databricks.com/", "12", "abc") == (
        "https://x.cloud.databricks.com/ml/experiments/12/runs/abc"
    )


def test_ask_retries_on_429_then_returns_the_answer() -> None:
    import asyncio

    calls = {"n": 0}

    class Agent:
        async def ainvoke(self, _payload: dict[str, Any]) -> dict[str, Any]:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("429 Too Many Requests")
            return {"messages": [SimpleNamespace(content="ok")]}

    assert asyncio.run(run.ask(Agent(), "oi", wait=0)) == "ok"
    assert calls["n"] == 2


def test_ask_does_not_hide_other_errors() -> None:
    import asyncio

    class Agent:
        async def ainvoke(self, _payload: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run.ask(Agent(), "oi", wait=0))
