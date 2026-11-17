"""Avaliação offline do agente contra o golden set (SPEC-008 §2 e §4, task P10.6).

Roda o agente real em cada caso de `eval/golden_set.yaml` com `mlflow.genai.evaluate` e os
scorers de código de `eval/scorers.py`, e imprime a acurácia por categoria, os casos que falharam
e o link do run do MLflow (o que vai no PR). O agente só roda com as dependências do App e o
workspace, então o **mantenedor** (ou quem tem o perfil) roda a partir do ambiente de `apps/agent`:

    uv run --project apps/agent python eval/run_offline_eval.py \\
        --profile andrevidal --catalog atlas_dev --warehouse-id <id> --genie-space-id <id>

* Os casos vêm do YAML (`to_records` do sync, a mesma fonte do dataset `agent_golden_set`).
* O valor esperado é **recalculado a cada rodada**: a `reference_sql` (e, nos casos `no_period`,
  a `reference_month_sql`) roda no warehouse e entra em `expectations` como `expected_value` e
  `expected_month`. Nenhum número fica no repositório.
* A resposta de um LLM varia: `--repeats` (padrão 3) roda a avaliação várias vezes, cada uma é
  um run do MLflow. Sai com 0 só se **todas** as rodadas ficarem em ≥ 90% **e** sem falha em
  `refusal` (SPEC-008 §5).
* **Acurácia** = % de casos em que **todos** os scorers aplicáveis à categoria deram pass. Aqui
  são só os de código; os LLM judges (`refusal_quality`, `correctness`) ficam fora e a qualidade
  do texto da recusa é lida por uma pessoa (o texto de cada resposta vai no run).
* Usa a sua identidade (não a do service principal do App) e o gateway do `dev`: respeita o rate
  limit de 30 req/min (ADR-0021), por isso poucas threads e nova tentativa no 429.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import os
import re
import sys
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval"
GOLDEN_SET = EVAL_DIR / "golden_set.yaml"
EXPERIMENT = "/Shared/atlas/agent-eval"  # separado do `agent-traces` (traces de uso do App)
TARGET_ACCURACY = 0.90
NOT_APPLICABLE = "n/a"
_PASS_VALUES = {True, "yes", "pass", "true"}


def _load(name: str) -> Any:
    """`eval/<name>.py` por caminho (a pasta `eval` não é um pacote)."""
    spec = importlib.util.spec_from_file_location(f"eval_{name}", EVAL_DIR / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"não consegui carregar eval/{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"eval_{name}"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------------------------
# Acurácia (lógica pura, testada sem MLflow nem workspace)
# ---------------------------------------------------------------------------------------------


def is_pass(value: Any) -> bool:
    return (value.lower() if isinstance(value, str) else value) in _PASS_VALUES


def case_passed(scores: Mapping[str, Any]) -> bool | None:
    """Todos os scorers aplicáveis passaram? `None` se nenhum se aplica ao caso."""
    applicable = [v for v in scores.values() if v != NOT_APPLICABLE and v is not None]
    return all(is_pass(v) for v in applicable) if applicable else None


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    category: str
    scores: Mapping[str, Any]
    rationales: Mapping[str, str] = field(default_factory=dict)
    answer: str = ""

    @property
    def passed(self) -> bool:
        return bool(case_passed(self.scores))

    def failed_scorers(self) -> list[str]:
        return sorted(
            name
            for name, value in self.scores.items()
            if value != NOT_APPLICABLE and value is not None and not is_pass(value)
        )


@dataclass(frozen=True)
class Summary:
    accuracy: float
    by_category: dict[str, float]
    failures: list[CaseScore]
    total: int

    @property
    def refusal_failures(self) -> list[CaseScore]:
        return [f for f in self.failures if f.category == "refusal"]

    @property
    def meets_target(self) -> bool:
        return self.accuracy >= TARGET_ACCURACY and not self.refusal_failures


def summarize(cases: Sequence[CaseScore]) -> Summary:
    if not cases:
        raise ValueError("nenhum caso avaliado")
    by_category: dict[str, list[bool]] = defaultdict(list)
    for case in cases:
        by_category[case.category].append(case.passed)
    return Summary(
        accuracy=sum(c.passed for c in cases) / len(cases),
        by_category={k: sum(v) / len(v) for k, v in sorted(by_category.items())},
        failures=[c for c in cases if not c.passed],
        total=len(cases),
    )


def scores_from_result_df(
    rows: Iterable[Mapping[str, Any]], scorer_names: Collection[str]
) -> list[CaseScore]:
    """Linhas de `EvaluationResult.result_df`: colunas `<scorer>/value` e `<scorer>/rationale`.

    O `result_df` também traz as expectations como colunas `<campo>/value`: só os nomes de
    `scorer_names` contam como scorer. O id e a categoria vêm de `expectations` (ou dessas colunas).
    """
    cases: list[CaseScore] = []
    for row in rows:
        expectations = row.get("expectations") or {}
        scores = {n: row[f"{n}/value"] for n in scorer_names if f"{n}/value" in row}
        rationales = {
            n: str(row[f"{n}/rationale"])
            for n in scorer_names
            if row.get(f"{n}/rationale") is not None
        }
        cases.append(
            CaseScore(
                case_id=str(expectations.get("id") or row.get("id/value") or "?"),
                category=str(expectations.get("category") or row.get("category/value") or "?"),
                scores=scores,
                rationales=rationales,
                answer=str(row.get("outputs") or ""),
            )
        )
    return cases


def with_missing_as_failures(
    cases: list[CaseScore], records: Sequence[Mapping[str, Any]]
) -> list[CaseScore]:
    """Caso que foi para a avaliação e não voltou no resultado conta como falha, não some."""
    seen = {c.case_id for c in cases}
    missing = [
        CaseScore(
            str(r["expectations"]["id"]),
            str(r["expectations"]["category"]),
            {"avaliado": False},
            {"avaliado": "o caso não voltou no resultado do MLflow"},
        )
        for r in records
        if r["expectations"]["id"] not in seen
    ]
    return [*cases, *missing]


def format_summary(summary: Summary, label: str) -> str:
    lines = [
        f"{label}: acurácia {summary.accuracy:.1%} ({summary.total - len(summary.failures)}"
        f"/{summary.total})"
    ]
    lines += [f"  {cat}: {value:.0%}" for cat, value in summary.by_category.items()]
    for case in summary.failures:
        why = "; ".join(f"{s}: {case.rationales.get(s, '-')}" for s in case.failed_scorers())
        lines.append(f"  FALHA {case.case_id} ({case.category}) {why}")
        if case.answer:
            lines.append(f"    resposta: {case.answer[:300]!r}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Valores esperados (recalculados a cada rodada)
# ---------------------------------------------------------------------------------------------


def parse_value(raw: str | None) -> float:
    try:
        return float(Decimal(str(raw)))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"a reference_sql não devolveu um número: {raw!r}") from error


def first_cell(response: Any) -> str | None:
    rows = response.result.data_array if response.result else None
    return rows[0][0] if rows and rows[0] else None


def with_expected_values(records: Sequence[dict[str, Any]], run_sql: Any) -> list[dict[str, Any]]:
    """Copia os registros e injeta `expected_value` (e `expected_month`) rodando as SQLs."""
    out: list[dict[str, Any]] = []
    for record in records:
        expectations = dict(record["expectations"])
        if "reference_sql" in expectations:
            expectations["expected_value"] = parse_value(run_sql(expectations["reference_sql"]))
        if "reference_month_sql" in expectations:
            month = run_sql(expectations["reference_month_sql"])
            if not month or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(month)):
                raise ValueError(f"a reference_month_sql não devolveu uma data: {month!r}")
            expectations["expected_month"] = str(month)
        out.append({"inputs": record["inputs"], "expectations": expectations})
    return out


def warehouse_runner(warehouse_id: str) -> Any:
    from databricks.sdk import WorkspaceClient  # só existe no ambiente de apps/agent

    client = WorkspaceClient()

    def run(statement: str) -> str | None:
        response = client.statement_execution.execute_statement(
            warehouse_id=warehouse_id, statement=statement, wait_timeout="50s"
        )
        if response.status and response.status.state and response.status.state.value != "SUCCEEDED":
            raise RuntimeError(f"a consulta falhou: {response.status}")
        return first_cell(response)

    return run


# ---------------------------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------------------------


def is_rate_limited(error: Exception) -> bool:
    """429 do gateway ou do workspace: infraestrutura, não falha do agente."""
    return "429" in str(error) or "REQUEST_LIMIT_EXCEEDED" in str(error)


CASE_TIMEOUT_S = 240.0  # um caso pendurado (rede, Genie) não pode travar a rodada inteira


async def ask(
    agent: Any,
    question: str,
    *,
    retries: int = 4,
    wait: float = 20.0,
    timeout: float = CASE_TIMEOUT_S,
) -> str:
    for attempt in range(retries + 1):
        try:
            out = await asyncio.wait_for(
                agent.ainvoke({"messages": [{"role": "user", "content": question}]}), timeout
            )
            return str(out["messages"][-1].content)
        except TimeoutError:
            return f"[timeout: o agente não respondeu em {timeout:.0f}s]"
        except Exception as error:
            if not is_rate_limited(error) or attempt == retries:
                raise
            print(f"  429; nova tentativa em {wait:.0f}s ({attempt + 1}/{retries})")
            await asyncio.sleep(wait)
    raise AssertionError("inalcançável")


def build_predict_fn() -> Any:
    app = importlib.import_module("agent_server.agent")  # só existe no ambiente de apps/agent
    agent = app.build_agent(app._tools())

    def predict(question: str) -> str:
        return asyncio.run(ask(agent, question))

    return predict


# ---------------------------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------------------------


def run_once(
    records: Sequence[dict[str, Any]],
    predict_fn: Any,
    scorers: Sequence[Any],
    label: str,
    tags: dict,
) -> tuple[Summary, str]:
    import mlflow

    with mlflow.start_run(run_name=label) as run:
        mlflow.set_tags(tags)
        result = mlflow.genai.evaluate(data=list(records), predict_fn=predict_fn, scorers=scorers)
        names = [s.name for s in scorers]
        scored = scores_from_result_df(result.result_df.to_dict("records"), names)
        summary = summarize(with_missing_as_failures(scored, records))
        mlflow.log_metric("accuracy", summary.accuracy)
        for category, value in summary.by_category.items():
            mlflow.log_metric(f"accuracy_{category}", value)
        mlflow.log_metric("refusal_failures", len(summary.refusal_failures))
        return summary, run.info.run_id


def run_url(host: str, experiment_id: str, run_id: str) -> str:
    return f"{host.rstrip('/')}/ml/experiments/{experiment_id}/runs/{run_id}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--catalog", required=True, help="catálogo do target (atlas_dev ou atlas)")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--genie-space-id", required=True)
    parser.add_argument("--prompt-version", help="versão do prompt (padrão: a do código)")
    parser.add_argument("--repeats", type=int, default=3, help="rodadas (o LLM varia); padrão 3")
    parser.add_argument("--experiment", default=EXPERIMENT)
    parser.add_argument("--only", help="ids separados por vírgula (ex.: GS-031), para depurar")
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats deve ser ≥ 1")

    # O agente lê ATLAS_* e o perfil na importação; defina antes.
    os.environ.update(
        DATABRICKS_CONFIG_PROFILE=args.profile,
        ATLAS_CATALOG=args.catalog,
        DATABRICKS_WAREHOUSE_ID=args.warehouse_id,
        ATLAS_GENIE_SPACE_ID=args.genie_space_id,
        MLFLOW_TRACKING_URI="databricks",
        # poucas threads: o gateway aceita 30 req/min e cada caso faz várias chamadas ao LLM
        MLFLOW_GENAI_EVAL_MAX_WORKERS="2",
        MLFLOW_DISABLE_AGENT_HINT="1",
    )
    if args.prompt_version:
        os.environ["ATLAS_PROMPT_VERSION"] = args.prompt_version
    sys.path.insert(0, str(ROOT / "apps" / "agent"))

    sync = _load("sync_golden_set")
    scorers_module = _load("scorers")
    records = sync.to_records(sync.load_cases(GOLDEN_SET), args.catalog)
    if args.only:
        wanted = {i.strip() for i in args.only.split(",")}
        records = [r for r in records if r["expectations"]["id"] in wanted]
        if not records:
            parser.error(f"nenhum caso com id em {sorted(wanted)}")
    records = with_expected_values(records, warehouse_runner(args.warehouse_id))
    print(f"{len(records)} casos; valores esperados recalculados em {args.catalog}")

    import mlflow
    from databricks.sdk import WorkspaceClient

    mlflow.set_experiment(args.experiment)
    experiment_id = mlflow.get_experiment_by_name(args.experiment).experiment_id
    host = WorkspaceClient().config.host
    predict_fn = build_predict_fn()
    app = importlib.import_module("agent_server.agent")
    tags = {"prompt_version": app.CONFIG.prompt_version, "catalog": args.catalog}
    scorers = scorers_module.build_scorers()

    summaries: list[Summary] = []
    for i in range(1, args.repeats + 1):
        label = f"offline-{tags['prompt_version']}-{i}of{args.repeats}"
        print(f"\n--- rodada {i}/{args.repeats} ---")
        summary, run_id = run_once(records, predict_fn, scorers, label, {**tags, "repeat": str(i)})
        summaries.append(summary)
        print(format_summary(summary, label))
        print(f"  run: {run_url(host, experiment_id, run_id)}")

    accuracies = [s.accuracy for s in summaries]
    print(
        f"\n--- resultado: {len(summaries)} rodada(s), acurácia "
        f"mín {min(accuracies):.1%} · média {sum(accuracies) / len(accuracies):.1%} "
        f"· máx {max(accuracies):.1%} (meta ≥ {TARGET_ACCURACY:.0%}, sem falha em refusal)"
    )
    # Os traces são enviados em segundo plano; espere antes de sair.
    mlflow.flush_trace_async_logging()
    return 0 if all(s.meets_target for s in summaries) else 1


if __name__ == "__main__":
    sys.exit(main())
