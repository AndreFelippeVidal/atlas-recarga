"""Monitoramento do agente em produção (`eval/monitoring.py`, P10.8). Sem MLflow nem workspace."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "eval" / f"{name}.py")
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mon = _load("monitoring")


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


def genie(view: str = "mv_recharges") -> FakeTrace:
    return FakeTrace([FakeSpan("ask_genie", {"q": "x"}, {"sql": f"FROM atlas.semantic.{view}"})])


ANSWER = "A receita foi R$ 10,00.\n\nFonte: mv_recharges"


# --- extração do texto -----------------------------------------------------------------------


def test_extract_answer_from_responses_output() -> None:
    response = {
        "output": [
            {"type": "function_call", "name": "ask_genie"},
            {"type": "message", "content": [{"type": "output_text", "text": ANSWER}]},
        ]
    }
    assert mon.extract_answer(response) == ANSWER
    assert mon.extract_answer(json.dumps(response)) == ANSWER


def test_extract_answer_and_question_handle_a_double_encoded_trace() -> None:
    # No workspace, `trace.data.response` chega como JSON dentro de uma string JSON.
    response = {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": ANSWER}]}]
    }
    assert mon.extract_answer(json.dumps(json.dumps(response))) == ANSWER
    request = {"input": [{"role": "user", "content": [{"type": "input_text", "text": "oi?"}]}]}
    assert mon.extract_question(json.dumps(json.dumps(request))) == "oi?"


def test_extract_answer_keeps_real_newlines_so_the_source_block_is_found() -> None:
    # Se o JSON inteiro fosse serializado, o `\n` viraria `\\n` e o `Fonte:` não seria achado.
    text = mon.extract_answer({"output": [{"type": "output_text", "text": ANSWER}]})
    assert "\nFonte:" in text


def test_extract_answer_falls_back_for_plain_text() -> None:
    assert mon.extract_answer("oi") == "oi"


def test_extract_question_takes_the_last_user_message() -> None:
    request = {
        "input": [
            {"role": "user", "content": "primeira"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": [{"type": "input_text", "text": "segunda"}]},
        ]
    }
    assert mon.extract_question(request) == "segunda"
    assert mon.extract_question(json.dumps(request)) == "segunda"
    assert mon.extract_question({}) == ""


# --- scorers de código em produção -----------------------------------------------------------


def test_cites_is_not_applicable_without_a_data_tool() -> None:
    score = mon.production_cites_metric_view("Não posso aprovar comissão.", FakeTrace())
    assert score.passed is None


def test_cites_passes_with_source_block_and_mv_recharges() -> None:
    assert mon.production_cites_metric_view(ANSWER, genie()).passed is True


def test_cites_passes_for_commission_questions_on_mv_commission() -> None:
    answer = "A comissão foi R$ 5,00.\n\nFonte: mv_commission"
    assert mon.production_cites_metric_view(answer, genie("mv_commission")).passed is True


def test_cites_fails_without_the_source_block() -> None:
    score = mon.production_cites_metric_view("A receita foi R$ 10,00.", genie())
    assert score.passed is False
    assert "Fonte" in score.rationale


def test_cites_fails_when_no_tool_consulted_a_known_view() -> None:
    score = mon.production_cites_metric_view(ANSWER, genie("outra_tabela"))
    assert score.passed is False


def test_uc_functions_count_as_a_data_tool() -> None:
    trace = FakeTrace([FakeSpan("atlas.semantic.fn_metric_by_region()", {}, {"rows": []})])
    assert mon.uses_data_tool(trace)
    assert mon.production_cites_metric_view(ANSWER, trace).passed is True


def test_list_metrics_alone_is_not_a_data_tool() -> None:
    assert not mon.uses_data_tool(FakeTrace([FakeSpan("fn_list_metrics")]))


def test_read_only_tools_flags_a_tool_outside_the_list() -> None:
    scores = {s.scorer: s for s in mon.code_scores(ANSWER, FakeTrace([FakeSpan("run_sql")]))}
    assert scores["read_only_tools"].passed is False
    assert "run_sql" in scores["read_only_tools"].rationale


def test_code_scores_cover_exactly_the_code_scorers() -> None:
    assert tuple(s.scorer for s in mon.code_scores(ANSWER, genie())) == mon.CODE_SCORERS


# --- amostra e assessments dos judges --------------------------------------------------------


def test_judge_sample_is_stable_and_near_the_rate() -> None:
    ids = [f"tr-{i:05d}" for i in range(5000)]
    picked = [i for i in ids if mon.in_judge_sample(i)]
    assert picked == [i for i in ids if mon.in_judge_sample(i)]
    assert 0.17 <= len(picked) / len(ids) <= 0.23


def test_judge_sample_edges() -> None:
    assert not mon.in_judge_sample("tr-1", 0.0)
    assert mon.in_judge_sample("tr-1", 1.0)
    with pytest.raises(ValueError, match="rate"):
        mon.in_judge_sample("tr-1", 1.5)


def test_dedupe_assessments_keeps_the_latest_per_name() -> None:
    items = [
        {"name": "safety", "value": "no", "create_time_ms": 1},
        {"name": "safety", "value": "yes", "create_time_ms": 2},
        {"name": "relevance", "value": "yes", "create_time_ms": 1},
    ]
    latest = mon.dedupe_assessments(items)
    assert latest["safety"]["value"] == "yes"
    assert set(latest) == {"safety", "relevance"}


def test_scores_from_assessments_ignore_other_names_and_handle_values() -> None:
    items = [
        {"name": "safety", "value": "yes", "rationale": "ok", "create_time_ms": 1},
        {"name": "relevance", "value": False, "create_time_ms": 1},
        {"name": "refusal_quality", "value": "n/a", "create_time_ms": 1},
        {"name": "has_source", "value": True, "create_time_ms": 1},
    ]
    by_name = {s.scorer: s.passed for s in mon.scores_from_assessments(items)}
    assert by_name == {"safety": True, "relevance": False, "refusal_quality": None}


def test_refusal_quality_only_without_a_data_tool() -> None:
    assert mon.judges_for(genie(), ANSWER) == ("safety", "relevance")
    assert mon.judges_for(FakeTrace(), "Não posso.") == ("refusal_quality", "safety", "relevance")
    assert mon.judges_for(FakeTrace(), "") == ()


# --- agregados e fila ------------------------------------------------------------------------


def test_day_brt_uses_sao_paulo_not_utc() -> None:
    def ms(iso: str) -> int:
        return int(datetime.fromisoformat(iso).timestamp() * 1000)

    # 02:00 UTC de 17/11 ainda é 16/11 em São Paulo (UTC-3); 03:00 UTC já é 17/11.
    assert mon.day_brt(ms("2026-11-17T02:00:00+00:00")) == "2026-11-16"
    assert mon.day_brt(ms("2026-11-17T03:00:00+00:00")) == "2026-11-17"


def test_p95() -> None:
    assert mon.p95([]) is None
    assert mon.p95([5]) == 5
    assert mon.p95(list(range(1, 101))) == 95


def test_queue_entries_only_for_failed_scorers() -> None:
    scores = [
        mon.Score("read_only_tools", True, "ok"),
        mon.Score("cites_metric_view", False, "sem Fonte"),
        mon.Score("safety", None, "n/a"),
    ]
    (entry,) = mon.queue_entries("tr-1", "pergunta", "x" * 600, scores)
    assert entry["scorer"] == "cites_metric_view"
    assert entry["trace_id"] == "tr-1"
    assert len(entry["answer_preview"]) == mon.ANSWER_PREVIEW_CHARS


# --- DDL -------------------------------------------------------------------------------------


def test_ddl_creates_the_objects_in_the_right_schemas() -> None:
    text = "\n".join(mon.ddl("atlas_dev"))
    for name in (
        "atlas_dev.observability.agent_quality_traces",
        "atlas_dev.observability.agent_quality_scores",
        "atlas_dev.observability.agent_quality_daily",
        "atlas_dev.observability.agent_traffic_daily",
        "atlas_dev.observability.agent_quality_alert",
        "atlas_dev.eval.review_queue",
    ):
        assert name in text


def test_ddl_is_idempotent_and_never_destructive() -> None:
    for statement in mon.ddl("atlas"):
        head = statement.lstrip().upper()
        assert head.startswith(("CREATE TABLE IF NOT EXISTS", "CREATE OR REPLACE VIEW"))
        assert "DROP " not in head
        assert "DELETE" not in head
        assert "UPDATE " not in head


def test_ddl_rejects_a_bad_catalog() -> None:
    with pytest.raises(ValueError, match="catálogo"):
        mon.ddl("atlas; DROP CATALOG x")


def test_alert_view_only_watches_the_alert_scorers() -> None:
    text = "\n".join(mon.ddl("atlas"))
    for scorer in mon.ALERT_SCORERS:
        assert f"'{scorer}'" in text
