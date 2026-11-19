"""Gera tráfego no App `agent-atlas` para a P12.9 (revalidar o production monitoring do MLflow).

O experiment `atlas_agent_traces` só recebe traces das chamadas ao **App** (não do
`run_offline_eval.py`, que grava em `agent-eval`). Este script faz algumas dezenas de perguntas do
golden set ao App, com a sua identidade, e respeita o rate limit do gateway (ADR-0021: 30 req/min;
cada pergunta gasta várias chamadas ao LLM, então a pausa padrão é de 10 s):

    uv run --project apps/agent python scripts/generate_agent_traffic.py \\
        --profile andrevidal --count 40

Só pergunta; não altera nada no workspace. O texto das respostas não é impresso (só o status e o
tamanho). Depois conte as assessments (comando na P12.9, em
`docs/specs/007-react-geo-dashboard/tasks.md`).
Sai com 0 se ao menos 90% das perguntas receberam resposta HTTP 200.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SET = ROOT / "eval" / "golden_set.yaml"
APP_NAME = "agent-atlas"
DEFAULT_PAUSE_SECONDS = 10.0
TIMEOUT_SECONDS = 120
MIN_OK_RATE = 0.9


def pick_questions(cases: Sequence[dict[str, Any]], count: int) -> list[str]:
    """As `count` primeiras perguntas, em ciclo se o golden set for menor que `count`."""
    questions = [str(c["question"]) for c in cases if c.get("question")]
    if not questions or count <= 0:
        return []
    return [questions[i % len(questions)] for i in range(count)]


def build_body(question: str) -> dict[str, Any]:
    """Corpo da Responses API (o contrato de `/invocations` do template do App)."""
    return {"input": [{"role": "user", "content": question}]}


def ok_rate(statuses: Sequence[int]) -> float:
    return sum(1 for s in statuses if s == 200) / len(statuses) if statuses else 0.0


def ask(url: str, headers: dict[str, str], question: str) -> tuple[int, int]:
    """Faz uma pergunta; devolve (status HTTP, bytes da resposta). 0 em erro de rede."""
    request = urllib.request.Request(  # noqa: S310 (URL do App, https)
        f"{url.rstrip('/')}/invocations",
        data=json.dumps(build_body(question)).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.status, len(response.read())
    except urllib.error.HTTPError as error:
        return error.code, 0
    except (urllib.error.URLError, TimeoutError):
        return 0, 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--count", type=int, default=40, help="quantas perguntas (padrão 40)")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SECONDS)
    args = parser.parse_args(argv)

    from databricks.sdk import WorkspaceClient  # só existe no ambiente de apps/agent

    client = WorkspaceClient(profile=args.profile)
    app = client.apps.get(APP_NAME)
    if not app.url:
        print(f"O App {APP_NAME} não tem URL (está parado?).", file=sys.stderr)
        return 1

    cases = yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))
    questions = pick_questions(cases, args.count)
    statuses: list[int] = []
    for index, question in enumerate(questions, start=1):
        headers = client.config.authenticate()  # renova o token se preciso; não é impresso
        status, size = ask(app.url, headers, question)
        statuses.append(status)
        print(f"[{index}/{len(questions)}] HTTP {status} · {size} bytes")
        if index < len(questions):
            time.sleep(args.pause)

    rate = ok_rate(statuses)
    print(f"{sum(1 for s in statuses if s == 200)}/{len(statuses)} com HTTP 200 ({rate:.0%})")
    return 0 if rate >= MIN_OK_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
