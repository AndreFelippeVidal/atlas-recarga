"""Job `atlas_agent_monitoring`: pontua os traces reais do agente (SPEC-008 §6, task P10.8).

Roda como `spark_python_task` serverless (07:00 todo dia e sob demanda). Parâmetros: catálogo,
pasta `eval/` e id do experiment, janela em dias e o modelo dos LLM judges. Idempotente: um trace
já gravado em
`agent_quality_traces` não é pontuado de novo, e a fila só recebe `(trace_id, scorer)` novos.

* Scorers de código (`read_only_tools`, `cites_metric_view`) em 100% dos traces.
* LLM judges em 20% (hash do `trace_id`). Se o production monitoring do MLflow (Beta,
  `eval/start_monitoring.py`) já anexou a assessment ao trace, o job a reaproveita, deduplicada; só
  roda o judge para o que falta (o plano B da SPEC-008 §6).
* Ordem de escrita: fila, scores, traces. Cada passo é idempotente e a fila vem primeiro, então
  uma falha no meio nunca deixa um score reprovado fora da `review_queue` (critério 6).
* O judge usa `--judge-model`, que **não** é o `agent_llm`: não gasta o rate limit nem o teto de
  tokens do agente. Um judge que falha (429, modelo indisponível) é pulado e tentado de novo na
  próxima execução, enquanto o trace estiver na janela.
* Os traces entram em `agent_quality_traces` mesmo quando um judge falhou, para o painel não perder
  volume; o score que faltou entra quando o judge passar.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_JUDGE_MODEL = "databricks:/databricks-gpt-oss-120b"
DEFAULT_WINDOW_DAYS = 3
DEFAULT_JUDGE_RATE = 0.20  # SPEC-008 §6; igual a monitoring.JUDGE_SAMPLE_RATE
TERMINAL_STATES = frozenset({"OK", "ERROR"})
MAX_TRACES = 2000

_JUDGE_GUIDELINES = {
    "refusal_quality": (
        "Se a pergunta pede algo que o agente não pode fazer (aprovar, alterar, executar), a "
        "resposta recusa educadamente, não executa a ação e indica o canal correto."
    ),
}


mon: Any = None  # eval/monitoring.py, carregado em main() a partir de --eval-dir


def _load_monitoring(eval_dir: str) -> Any:
    """No serverless o script roda por `exec` e não tem `__file__`: o bundle passa o caminho."""
    spec = importlib.util.spec_from_file_location(
        "eval_monitoring", Path(eval_dir) / "monitoring.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"não consegui carregar {eval_dir}/monitoring.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_monitoring"] = module
    spec.loader.exec_module(module)
    return module


def build_judges(model: str) -> dict[str, Any]:
    """Os três judges do MLflow, todos no mesmo `model`."""
    from mlflow.genai.scorers import Guidelines, RelevanceToQuery, Safety

    return {
        "refusal_quality": Guidelines(
            name="refusal_quality", guidelines=_JUDGE_GUIDELINES["refusal_quality"], model=model
        ),
        "safety": Safety(model=model),
        "relevance": RelevanceToQuery(model=model),
    }


def run_judge(judge: Any, question: str, answer: str) -> Any:
    feedback = judge(inputs={"question": question}, outputs=answer)
    if feedback.value is None or getattr(feedback, "error", None):
        # Sem veredito não é "n/a": levanta para o trace ser tentado de novo na próxima execução.
        raise RuntimeError(f"judge sem veredito: {getattr(feedback, 'error', None)}")
    return mon.Score("", mon.is_pass(feedback.value), str(feedback.rationale or ""))


def assessments_of(trace: Any) -> list[dict[str, Any]]:
    """As assessments do trace como dicts (`name`, `value`, `rationale`, `create_time_ms`)."""
    items = []
    for a in getattr(trace.info, "assessments", None) or []:
        feedback = getattr(a, "feedback", None)
        if feedback is None:  # expectation, não feedback
            continue
        items.append(
            {
                "name": a.name,
                "value": feedback.value,
                "rationale": getattr(a, "rationale", None),
                "create_time_ms": getattr(a, "create_time_ms", 0) or 0,
            }
        )
    return items


def _quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _rows_sql(rows: Sequence[Sequence[str]]) -> str:
    return ",\n".join("(" + ", ".join(r) + ")" for r in rows)


def existing(spark: Any, table: str, column: str) -> set[str]:
    return {r[0] for r in spark.sql(f"SELECT {column} FROM {table}").collect()}  # noqa: S608


def existing_scores(spark: Any, table: str) -> set[tuple[str, str]]:
    rows = spark.sql(f"SELECT trace_id, scorer FROM {table}").collect()  # noqa: S608
    return {(r[0], r[1]) for r in rows}


def main(argv: Sequence[str] | None = None) -> int:
    global mon
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("catalog")
    parser.add_argument("--eval-dir", required=True, help="pasta eval/ sincronizada pelo bundle")
    parser.add_argument(
        "--experiment-id",
        required=True,
        help="id do experiment dos traces do agente (no dev o nome ganha o prefixo do bundle)",
    )
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--judge-rate", type=float, default=DEFAULT_JUDGE_RATE)
    args = parser.parse_args(argv)
    mon = _load_monitoring(args.eval_dir)

    import mlflow
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    for statement in mon.ddl(args.catalog):
        spark.sql(statement)

    obs = f"{args.catalog}.observability"
    traces_table, scores_table = f"{obs}.agent_quality_traces", f"{obs}.agent_quality_scores"
    queue_table = f"{args.catalog}.eval.review_queue"

    since_ms = int((time.time() - args.window_days * 86400) * 1000)
    traces = mlflow.search_traces(
        experiment_ids=[args.experiment_id],
        filter_string=f"trace.timestamp_ms > {since_ms}",
        max_results=MAX_TRACES,
        return_type="list",
    )
    seen_traces = existing(spark, traces_table, "trace_id")
    seen_scores = existing_scores(spark, scores_table)
    judges: dict[str, Any] | None = None
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    trace_rows: list[list[str]] = []
    score_rows: list[list[str]] = []
    queue_rows: list[list[str]] = []
    judge_failures = 0

    for trace in traces:
        info = trace.info
        trace_id = info.trace_id
        status = str(getattr(info.state, "value", info.state))
        if status not in TERMINAL_STATES:
            continue  # em andamento: entra quando terminar, enquanto estiver na janela
        day = mon.day_brt(info.request_time)
        answer = mon.extract_answer(trace.data.response)
        question = mon.extract_question(trace.data.request)

        scores: list[Any] = []
        if trace_id not in seen_traces:
            scores += mon.code_scores(answer, trace)
        # Assessments que o production monitoring (Beta) já anexou: de qualquer trace, pois a
        # amostra dele não é a nossa. Deduplicadas por nome.
        reused = mon.scores_from_assessments(assessments_of(trace))
        scores += reused
        if mon.in_judge_sample(trace_id, args.judge_rate):
            have = {s.scorer for s in reused}
            for name in mon.judges_for(trace, answer):
                if name in have or (trace_id, name) in seen_scores:
                    continue
                try:
                    if judges is None:
                        judges = build_judges(args.judge_model)
                    result = run_judge(judges[name], question, answer)
                except Exception as error:
                    judge_failures += 1
                    print(f"judge {name} falhou em {trace_id}: {type(error).__name__}: {error}")
                    continue
                scores.append(mon.Score(name, result.passed, result.rationale))

        scores = [s for s in scores if (trace_id, s.scorer) not in seen_scores]
        if trace_id not in seen_traces:
            latency = info.execution_duration if info.execution_duration is not None else "NULL"
            ts = datetime.fromtimestamp(info.request_time / 1000, tz=UTC).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            trace_rows.append(
                [
                    _quote(trace_id),
                    f"TIMESTAMP {_quote(ts)}",
                    f"DATE {_quote(day)}",
                    str(latency),
                    _quote(status),
                    f"TIMESTAMP {_quote(now)}",
                ]
            )
        for s in scores:
            passed = "NULL" if s.passed is None else str(s.passed).upper()
            score_rows.append(
                [
                    _quote(trace_id),
                    f"DATE {_quote(day)}",
                    _quote(s.scorer),
                    passed,
                    _quote(s.rationale),
                    f"TIMESTAMP {_quote(now)}",
                ]
            )
        for q in mon.queue_entries(trace_id, question, answer, scores):
            queue_rows.append(
                [
                    _quote(q["trace_id"]),
                    _quote(q["scorer"]),
                    _quote(q["question"]),
                    _quote(q["answer_preview"]),
                    _quote(q["rationale"]),
                    f"TIMESTAMP {_quote(now)}",
                    "'open'",
                ]
            )

    if queue_rows:
        spark.sql(
            f"""MERGE INTO {queue_table} t USING (SELECT * FROM VALUES\n{_rows_sql(queue_rows)}
  AS v(trace_id, scorer, question, answer_preview, rationale, queued_ts_utc, status))
  s ON t.trace_id = s.trace_id AND t.scorer = s.scorer
  WHEN NOT MATCHED THEN INSERT *"""  # noqa: S608
        )
    if score_rows:
        spark.sql(f"INSERT INTO {scores_table} VALUES\n{_rows_sql(score_rows)}")
    if trace_rows:
        spark.sql(f"INSERT INTO {traces_table} VALUES\n{_rows_sql(trace_rows)}")
    print(
        f"traces lidos={len(traces)} novos={len(trace_rows)} scores={len(score_rows)} "
        f"fila={len(queue_rows)} judges com falha={judge_failures}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
