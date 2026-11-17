"""Confere o monitoramento do agente em produção (SPEC-008 §6 e §7, task P10.8).

Critérios 5 e 6 da SPEC-008 §7. As tabelas só têm dados no workspace, então o **mantenedor** roda
isto depois do deploy e de pelo menos uma execução do job `atlas_agent_monitoring`:

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run atlas_agent_monitoring -t dev --profile andrevidal
    uv run python scripts/check_agent_monitoring.py --profile andrevidal \\
        --warehouse-id <id> --catalog atlas_dev

Checagens (uma consulta só, sobre `observability.agent_quality_*` e `eval.review_queue`):
1. Há traces pontuados.
2. Todo trace tem os 2 scorers de código (100%).
3. Os LLM judges cobrem ~20% dos traces (±5 pontos). Só vale com 100 traces ou mais; com menos, é
   só informativo, porque a amostra é pequena demais.
4. Todo scorer que reprovou está em `review_queue`.
5. Nenhuma linha da fila entrou mais de 24 h depois do trace.

Sai com 0 se tudo passa.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Mapping, Sequence
from typing import Any

_IDENT = re.compile(r"^[A-Za-z0-9_]+$")
MIN_TRACES_FOR_SAMPLE = 100
SAMPLE_TARGET, SAMPLE_TOLERANCE = 0.20, 0.05
QUEUE_LAG_HOURS = 24


def summary_sql(catalog: str) -> str:
    if not _IDENT.fullmatch(catalog):
        raise ValueError(f"catálogo inválido: {catalog!r}")
    obs, ev = f"{catalog}.observability", f"{catalog}.eval"
    return f"""
SELECT
  (SELECT COUNT(*) FROM {obs}.agent_quality_traces) AS traces,
  (SELECT COUNT(*) FROM {obs}.agent_quality_traces t WHERE
     (SELECT COUNT(DISTINCT scorer) FROM {obs}.agent_quality_scores s
      WHERE s.trace_id = t.trace_id AND s.scorer IN ('read_only_tools', 'cites_metric_view')) < 2
  ) AS traces_missing_code_scorers,
  (SELECT COUNT(DISTINCT trace_id) FROM {obs}.agent_quality_scores
   WHERE scorer IN ('refusal_quality', 'safety', 'relevance')) AS traces_with_judge,
  (SELECT COUNT(*) FROM {obs}.agent_quality_scores s WHERE s.passed = false AND NOT EXISTS (
     SELECT 1 FROM {ev}.review_queue q
     WHERE q.trace_id = s.trace_id AND q.scorer = s.scorer)) AS failures_not_queued,
  (SELECT COUNT(*) FROM {ev}.review_queue q JOIN {obs}.agent_quality_traces t
     ON t.trace_id = q.trace_id
   WHERE q.queued_ts_utc > t.trace_ts_utc + INTERVAL {QUEUE_LAG_HOURS} HOURS) AS queued_too_late,
  (SELECT COUNT(*) FROM {ev}.review_queue WHERE status = 'open') AS open_in_queue
"""


def evaluate(row: Mapping[str, Any]) -> list[tuple[str, bool, str]]:
    """`(nome, passou, detalhe)` por checagem, a partir da linha do resumo."""
    traces = int(row["traces"])
    judged = int(row["traces_with_judge"])
    checks = [
        ("há traces pontuados", traces > 0, f"{traces} traces"),
        (
            "scorers de código em 100% dos traces",
            int(row["traces_missing_code_scorers"]) == 0,
            f"{row['traces_missing_code_scorers']} trace(s) sem os 2 scorers",
        ),
    ]
    ratio = judged / traces if traces else 0.0
    in_range = round(abs(ratio - SAMPLE_TARGET), 9) <= SAMPLE_TOLERANCE
    if traces >= MIN_TRACES_FOR_SAMPLE:
        checks.append(("judges em ~20% dos traces", in_range, f"{ratio:.1%} ({judged}/{traces})"))
    else:
        checks.append(
            (
                "judges em ~20% dos traces (informativo)",
                True,
                f"{ratio:.1%} ({judged}/{traces}); só vale com {MIN_TRACES_FOR_SAMPLE}+ traces",
            )
        )
    checks.append(
        (
            "toda falha está na review_queue",
            int(row["failures_not_queued"]) == 0,
            f"{row['failures_not_queued']} falha(s) fora da fila",
        )
    )
    checks.append(
        (
            f"a fila recebeu em até {QUEUE_LAG_HOURS} h",
            int(row["queued_too_late"]) == 0,
            f"{row['queued_too_late']} linha(s) atrasada(s); {row['open_in_queue']} aberta(s)",
        )
    )
    return checks


def _query(profile: str, warehouse_id: str, statement: str) -> dict[str, Any]:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    command = ["databricks", "--profile", profile, "api", "post", "/api/2.0/sql/statements"]
    command += ["--json", json.dumps(body), "-o", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    response: dict[str, Any] = json.loads(result.stdout)
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(str(status.get("error", status)))
    columns = [c["name"] for c in response["manifest"]["schema"]["columns"]]
    values = response["result"]["data_array"][0]
    return dict(zip(columns, values, strict=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--catalog", required=True)
    args = parser.parse_args(argv)
    row = _query(args.profile, args.warehouse_id, summary_sql(args.catalog))
    ok = True
    for name, passed, detail in evaluate(row):
        print(f"[{'ok' if passed else 'FALHOU'}] {name}: {detail}")
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
