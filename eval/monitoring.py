"""Monitoramento do agente em produção (SPEC-008 §4 e §6, task P10.8). Lógica pura, só a stdlib.

O job `atlas_agent_monitoring` (`eval/run_agent_monitoring.py`) lê os traces reais do experiment
do agente e usa estas funções para decidir o que pontuar, como pontuar e o que gravar. Aqui não há
MLflow nem Spark, então tudo é testável sem workspace.

* **Scorers de código** (100% dos traces): `read_only_tools` e `cites_metric_view`. Em produção não
  há `expectations`, então `cites_metric_view` é `n/a` quando o trace não chamou uma tool de dados
  e, quando chamou, vale se a resposta tem o bloco `Fonte:` e uma tool consultou `mv_recharges` ou
  `mv_commission` (SPEC-008 §4). A lógica é a de `eval/scorers.py`, não uma cópia.
* **LLM judges** (20%): a amostra é decidida pelo hash do `trace_id`, então a mesma execução
  escolhe os mesmos traces e um trace já avaliado não é avaliado de novo.
* **Fila de revisão**: todo scorer que reprova vira uma linha em `eval.review_queue`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

EVAL_DIR = Path(__file__).resolve().parent
NOT_APPLICABLE = "n/a"

CODE_SCORERS = ("read_only_tools", "cites_metric_view")
JUDGE_SCORERS = ("refusal_quality", "safety", "relevance")
ALL_SCORERS = CODE_SCORERS + JUDGE_SCORERS
# Os scorers que o alerta da SPEC-008 §6 vigia (média de 7 dias abaixo de 90%).
ALERT_SCORERS = ("cites_metric_view", "read_only_tools")
ALERT_THRESHOLD = 0.90

DATA_TOOLS = frozenset({"ask_genie", "fn_metric_by_region", "fn_compare_months"})
PRODUCTION_VIEWS = ("mv_recharges", "mv_commission")
JUDGE_SAMPLE_RATE = 0.20
_PASS_VALUES = {True, "yes", "pass", "true"}
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
ANSWER_PREVIEW_CHARS = 500
_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


def _load_scorers() -> Any:
    """`eval/scorers.py` por caminho (a pasta `eval` não é um pacote)."""
    name = "eval_scorers"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, EVAL_DIR / "scorers.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("não consegui carregar eval/scorers.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Score:
    scorer: str
    passed: bool | None  # None = não se aplica ao trace
    rationale: str


# ---------------------------------------------------------------------------------------------
# Resposta do agente
# ---------------------------------------------------------------------------------------------


def extract_answer(response: Any) -> str:
    """O texto da resposta de um trace do agente.

    O agente (ResponsesAgent) devolve `{"output": [{"type": "message", "content": [{"type":
    "output_text", "text": ...}]}]}`. Junta os textos das mensagens do assistente; qualquer outro
    formato cai no `answer_text` dos scorers. Aceita o JSON como `str`, como vem do trace.
    """
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            return str(response)
    texts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            if node.get("type") == "output_text" and isinstance(node.get("text"), str):
                texts.append(node["text"])
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(response)
    return "\n".join(texts) if texts else str(_load_scorers().answer_text(response))


def extract_question(request: Any) -> str:
    """O texto da última mensagem do usuário na requisição do trace (`""` se não achar)."""
    if isinstance(request, str):
        try:
            request = json.loads(request)
        except ValueError:
            return str(request)
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            if node.get("role") == "user":
                content = node.get("content")
                if isinstance(content, str):
                    found.append(content)
                elif isinstance(content, list):
                    found.extend(
                        str(part["text"])
                        for part in content
                        if isinstance(part, Mapping) and isinstance(part.get("text"), str)
                    )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(request)
    return found[-1] if found else ""


# ---------------------------------------------------------------------------------------------
# Scorers de código em produção
# ---------------------------------------------------------------------------------------------


def uses_data_tool(trace: Any) -> bool:
    return any(name in DATA_TOOLS for name in _load_scorers().tool_names(trace))


def production_cites_metric_view(answer: str, trace: Any) -> Score:
    """`cites_metric_view` sem `expectations` (SPEC-008 §4, "Em produção")."""
    scorers = _load_scorers()
    if not uses_data_tool(trace):
        return Score("cites_metric_view", None, "nenhuma tool de dados chamada")
    failures: list[str] = []
    for view in PRODUCTION_VIEWS:
        result = scorers.check_cites_metric_view(
            answer, trace, {"category": "metric", "expected_source_view": view}
        )
        if result.passed:
            return Score("cites_metric_view", True, result.rationale)
        failures.append(result.rationale)
    # As duas views falharam; se a falha for a falta do bloco `Fonte:`, a justificativa é a mesma.
    return Score("cites_metric_view", False, failures[0])


def code_scores(answer: str, trace: Any) -> list[Score]:
    scorers = _load_scorers()
    read_only = scorers.check_read_only_tools(trace)
    return [
        Score("read_only_tools", bool(read_only.passed), read_only.rationale),
        production_cites_metric_view(answer, trace),
    ]


# ---------------------------------------------------------------------------------------------
# LLM judges: amostra e assessments
# ---------------------------------------------------------------------------------------------


def in_judge_sample(trace_id: str, rate: float = JUDGE_SAMPLE_RATE) -> bool:
    """Decisão estável pelo hash do `trace_id`: o mesmo trace dá sempre a mesma resposta."""
    if not 0.0 <= rate <= 1.0:
        raise ValueError(f"rate fora de [0, 1]: {rate!r}")
    bucket = int.from_bytes(hashlib.sha256(trace_id.encode()).digest()[:8], "big") % 10_000
    return bucket < round(rate * 10_000)


def is_pass(value: Any) -> bool:
    return (value.lower() if isinstance(value, str) else value) in _PASS_VALUES


def dedupe_assessments(assessments: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Uma assessment por nome: a mais recente (`create_time_ms`).

    O monitoring e o `evaluate` podem gravar a mesma assessment duas vezes no mesmo trace (S0.3).
    """
    latest: dict[str, Mapping[str, Any]] = {}
    for item in assessments:
        name = str(item["name"])
        if name not in latest or item.get("create_time_ms", 0) >= latest[name].get(
            "create_time_ms", 0
        ):
            latest[name] = item
    return latest


def scores_from_assessments(assessments: Iterable[Mapping[str, Any]]) -> list[Score]:
    """Os judges que o production monitoring já anexou ao trace (deduplicados)."""
    found = dedupe_assessments(a for a in assessments if a["name"] in JUDGE_SCORERS)
    scores = []
    for name, item in sorted(found.items()):
        value = item.get("value")
        passed = None if value == NOT_APPLICABLE or value is None else is_pass(value)
        scores.append(Score(name, passed, str(item.get("rationale") or "")))
    return scores


def judges_for(trace: Any, answer: str) -> tuple[str, ...]:
    """Quais judges valem para o trace. `refusal_quality` só para quem não chamou tool de dados."""
    if uses_data_tool(trace):
        return ("safety", "relevance")
    return ("refusal_quality", "safety", "relevance") if answer else ()


# ---------------------------------------------------------------------------------------------
# Agregados e fila
# ---------------------------------------------------------------------------------------------


def day_brt(timestamp_ms: int) -> str:
    """O dia de negócio (America/Sao_Paulo) de um timestamp em ms UTC, como `AAAA-MM-DD`."""
    return (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).astimezone(SAO_PAULO).date().isoformat()
    )


def p95(values: Sequence[float]) -> float | None:
    """Percentil 95 pelo método do posto mais próximo; `None` sem valores."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def preview(text: str, limit: int = ANSWER_PREVIEW_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def queue_entries(
    trace_id: str, question: str, answer: str, scores: Iterable[Score]
) -> list[dict[str, str]]:
    """Uma linha de `review_queue` por scorer que reprovou (`passed is False`)."""
    return [
        {
            "trace_id": trace_id,
            "scorer": s.scorer,
            "question": preview(question),
            "answer_preview": preview(answer),
            "rationale": preview(s.rationale),
        }
        for s in scores
        if s.passed is False
    ]


# ---------------------------------------------------------------------------------------------
# DDL (idempotente) das tabelas e views
# ---------------------------------------------------------------------------------------------


def ddl(catalog: str) -> list[str]:
    """CREATE ... IF NOT EXISTS de `observability.agent_quality_*`, `agent_traffic_daily` e
    `eval.review_queue`. Os nomes são fixos; só o catálogo varia (validado)."""
    if not _IDENT.fullmatch(catalog):
        raise ValueError(f"catálogo inválido: {catalog!r}")
    obs = f"{catalog}.observability"
    return [
        f"""CREATE TABLE IF NOT EXISTS {obs}.agent_quality_traces (
  trace_id STRING NOT NULL COMMENT 'id do trace MLflow do agente',
  trace_ts_utc TIMESTAMP COMMENT 'início do trace, em UTC',
  day DATE COMMENT 'dia de negócio (America/Sao_Paulo)',
  latency_ms BIGINT COMMENT 'duração do trace em ms',
  status STRING COMMENT 'estado do trace (OK ou ERROR)',
  scored_ts_utc TIMESTAMP COMMENT 'quando o job pontuou o trace')
COMMENT 'Um trace do agente por linha (SPEC-008 §6). Escrita só pelo job de monitoramento.'""",
        f"""CREATE TABLE IF NOT EXISTS {obs}.agent_quality_scores (
  trace_id STRING NOT NULL COMMENT 'id do trace MLflow do agente',
  day DATE COMMENT 'dia de negócio do trace (America/Sao_Paulo)',
  scorer STRING NOT NULL COMMENT 'cites_metric_view, read_only_tools, refusal_quality, safety...',
  passed BOOLEAN COMMENT 'true, false, ou nulo quando o scorer não se aplica ao trace',
  rationale STRING COMMENT 'justificativa do scorer',
  scored_ts_utc TIMESTAMP COMMENT 'quando o scorer rodou')
COMMENT 'Um trace e um scorer por linha (SPEC-008 §6). Escrita só pelo job de monitoramento.'""",
        f"""CREATE OR REPLACE VIEW {obs}.agent_quality_daily (
  day COMMENT 'dia de negócio (America/Sao_Paulo)',
  scorer COMMENT 'nome do scorer',
  evaluated COMMENT 'traces avaliados (exclui os que não se aplicam)',
  passed COMMENT 'traces que passaram',
  pass_rate COMMENT 'passed / evaluated, de 0 a 1',
  pass_rate_7d COMMENT 'média de 7 dias do pass_rate (ponderada pelos traces avaliados)')
COMMENT 'Pass por scorer por dia e média de 7 dias (SPEC-008 §6).' AS
WITH daily AS (
  SELECT day, scorer, COUNT(*) AS evaluated, SUM(CASE WHEN passed THEN 1 ELSE 0 END) AS passed
  FROM {obs}.agent_quality_scores
  WHERE passed IS NOT NULL
  GROUP BY day, scorer
)
SELECT day, scorer, evaluated, passed, passed / evaluated AS pass_rate,
  SUM(passed) OVER w / SUM(evaluated) OVER w AS pass_rate_7d
FROM daily
WINDOW w AS (PARTITION BY scorer ORDER BY CAST(day AS TIMESTAMP)
  RANGE BETWEEN INTERVAL 6 DAYS PRECEDING AND CURRENT ROW)""",
        f"""CREATE OR REPLACE VIEW {obs}.agent_traffic_daily (
  day COMMENT 'dia de negócio (America/Sao_Paulo)',
  traces COMMENT 'traces do dia',
  errors COMMENT 'traces com status diferente de OK',
  latency_p95_ms COMMENT 'latência p95 em ms')
COMMENT 'Volume e latência p95 do agente por dia (SPEC-008 §6).' AS
SELECT day, COUNT(*) AS traces, SUM(CASE WHEN status <> 'OK' THEN 1 ELSE 0 END) AS errors,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS latency_p95_ms
FROM {obs}.agent_quality_traces
GROUP BY day""",
        f"""CREATE OR REPLACE VIEW {obs}.agent_quality_alert (
  scorer COMMENT 'cites_metric_view ou read_only_tools',
  pass_rate_7d COMMENT 'média dos últimos 7 dias, de 0 a 1')
COMMENT 'Alvo do SQL alert (SPEC-008 §6): um scorer vigiado por linha, só com dados na janela.' AS
SELECT scorer, SUM(passed) / SUM(evaluated) AS pass_rate_7d
FROM {obs}.agent_quality_daily
WHERE scorer IN ('cites_metric_view', 'read_only_tools')
  AND day >= date_sub(CAST(from_utc_timestamp(current_timestamp(), 'America/Sao_Paulo') AS DATE), 6)
GROUP BY scorer""",
        f"""CREATE TABLE IF NOT EXISTS {catalog}.eval.review_queue (
  trace_id STRING NOT NULL COMMENT 'id do trace MLflow que falhou',
  scorer STRING NOT NULL COMMENT 'scorer que reprovou',
  question STRING COMMENT 'pergunta do usuário (trecho)',
  answer_preview STRING COMMENT 'resposta do agente (trecho)',
  rationale STRING COMMENT 'justificativa do scorer',
  queued_ts_utc TIMESTAMP COMMENT 'quando entrou na fila',
  status STRING COMMENT 'open, golden_set_added ou dismissed; quem revisa muda este campo')
COMMENT 'Fila de revisão: traces que falharam um scorer (SPEC-008 §6). O job só insere.'""",
    ]
