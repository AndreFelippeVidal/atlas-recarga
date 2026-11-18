"""Fluxo de `eval/run_agent_monitoring.py` (P10.8) com mlflow e Spark falsos.

O job só roda no workspace; este teste existe porque dois erros de execução (`__file__` e o
`global`) só apareceram lá. Cobre o caminho principal: carrega o monitoring por `--eval-dir`, lê um
trace, pontua e grava na ordem fila, scores, traces.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"


class FakeSpan:
    def __init__(self, name: str, outputs: Any) -> None:
        self.name = name
        self.inputs: dict[str, Any] = {}
        self.outputs = outputs


class FakeTrace:
    def __init__(self, response: Any, spans: list[FakeSpan], state: str = "OK") -> None:
        self.info = types.SimpleNamespace(
            trace_id="tr-1",
            request_time=1_794_960_000_000,
            execution_duration=1200,
            state=state,
            assessments=[],
        )
        self.data = types.SimpleNamespace(
            request=json.dumps({"input": [{"role": "user", "content": "receita?"}]}),
            response=json.dumps(response),
        )
        self._spans = spans

    def search_spans(self, span_type: str) -> list[FakeSpan]:
        assert span_type == "TOOL"
        return self._spans


class FakeSpark:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def sql(self, statement: str) -> Any:
        self.statements.append(statement)
        return types.SimpleNamespace(collect=lambda: [])


def run(monkeypatch: pytest.MonkeyPatch, traces: list[FakeTrace]) -> FakeSpark:
    spark = FakeSpark()
    mlflow = types.ModuleType("mlflow")
    mlflow.search_traces = lambda **_: traces  # type: ignore[attr-defined]
    pyspark = types.ModuleType("pyspark")
    sql = types.ModuleType("pyspark.sql")
    builder = types.SimpleNamespace(getOrCreate=lambda: spark)
    sql.SparkSession = types.SimpleNamespace(builder=builder)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlflow", mlflow)
    monkeypatch.setitem(sys.modules, "pyspark", pyspark)
    monkeypatch.setitem(sys.modules, "pyspark.sql", sql)
    spec = importlib.util.spec_from_file_location(
        "run_agent_monitoring", EVAL / "run_agent_monitoring.py"
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = module.main(
        [
            "atlas_dev",
            "--warehouse-id",
            "wh1",
            "--eval-dir",
            str(EVAL),
            "--experiment-id",
            "1",
            "--judge-rate",
            "0",
        ]
    )
    assert code == 0
    assert os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] == "wh1"
    return spark


def test_scores_a_failing_trace_and_queues_it_before_writing_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = {"output": [{"type": "output_text", "text": "A receita foi R$ 10,00."}]}  # sem Fonte:
    trace = FakeTrace(answer, [FakeSpan("ask_genie", {"sql": "FROM atlas.semantic.mv_recharges"})])
    statements = run(monkeypatch, [trace]).statements
    writes = [s for s in statements if s.lstrip().startswith(("MERGE", "INSERT"))]
    assert [w.split()[0] + " " + w.split()[2] for w in writes] == [
        "MERGE atlas_dev.eval.review_queue",
        "INSERT atlas_dev.observability.agent_quality_scores",
        "INSERT atlas_dev.observability.agent_quality_traces",
    ]
    assert "cites_metric_view" in writes[0]
    assert any(s.startswith("CREATE TABLE IF NOT EXISTS") for s in statements)


def test_trace_in_progress_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    trace = FakeTrace({"output": []}, [], state="IN_PROGRESS")
    statements = run(monkeypatch, [trace]).statements
    assert not [s for s in statements if s.lstrip().startswith(("MERGE", "INSERT"))]
