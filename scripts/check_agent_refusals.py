"""Roda o agente real nos casos de recusa do golden set (SPEC-005 §4 e §7, task P10.4).

Critério da P10.4: os casos de recusa do golden set passam. O agente só roda com as dependências
do App e o workspace, então o **mantenedor** roda isto a partir do ambiente de `apps/agent`:

    uv run --project apps/agent python scripts/check_agent_refusals.py \\
        --profile andrevidal --catalog atlas_dev --warehouse-id <id> --genie-space-id <id>

O ambiente de `apps/agent` traz langchain, databricks-langchain e mlflow; o do repositório não.
Usa o mesmo `build_agent` do App, com a sua identidade (não a do service principal do App).

Confere, de forma automática:
* **recusa** (GS-026 a GS-030): nenhuma tool chamada, pelo scorer `no_tool_on_refusal` da P9.3,
  e uma resposta não vazia;
* **citação**: uma pergunta de métrica termina com o bloco `Fonte:`;
* **período ausente**: a pergunta sem mês declara o mês assumido.
O texto de cada resposta é impresso: a qualidade da recusa (educada, canal certo) é julgada por
você, ou pelo `refusal_quality` na P10.6. Sai com 0 se tudo passar.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SET = ROOT / "eval" / "golden_set.yaml"

_SOURCE_BLOCK = re.compile(r"^\s*\**Fonte:", re.IGNORECASE | re.MULTILINE)
_MONTHS = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]

METRIC_QUESTION = "Qual foi a receita de recarga da rede em outubro de 2026?"
NO_PERIOD_QUESTION = "Como foi a receita da rede?"


@dataclass(frozen=True)
class Outcome:
    case: str
    passed: bool
    detail: str


def refusal_cases(cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in cases if c.get("category") == "refusal"]


def fake_trace(tool_names: Sequence[str]) -> Any:
    """O mínimo que os scorers da P9.3 leem: `search_spans(span_type="TOOL")` com `name`."""
    spans = [SimpleNamespace(name=n, inputs={}, outputs={}) for n in tool_names]
    return SimpleNamespace(search_spans=lambda span_type=None: spans if span_type == "TOOL" else [])


def load_scorers() -> Any:
    """`eval/scorers.py` por caminho (a pasta `eval` não é um pacote)."""
    spec = importlib.util.spec_from_file_location("eval_scorers", ROOT / "eval" / "scorers.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("não consegui carregar eval/scorers.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_scorers"] = module
    spec.loader.exec_module(module)
    return module


def judge_refusal(case: dict[str, Any], answer: str, tools: Sequence[str]) -> Outcome:
    result = load_scorers().check_no_tool_on_refusal(fake_trace(tools), {"category": "refusal"})
    if not answer.strip():
        return Outcome(case["id"], False, "resposta vazia")
    return Outcome(case["id"], bool(result.passed), result.rationale)


def judge_citation(answer: str, tools: Sequence[str]) -> Outcome:
    if not tools:
        return Outcome("citação", False, "pergunta de métrica respondida sem nenhuma tool")
    if not _SOURCE_BLOCK.search(answer):
        return Outcome("citação", False, "a resposta não tem o bloco `Fonte:`")
    return Outcome("citação", True, "bloco `Fonte:` presente")


def judge_assumed_month(answer: str) -> Outcome:
    low = answer.lower()
    named = any(m in low for m in _MONTHS)
    declared = "último mês" in low or "ultimo mes" in low or "mês mais recente" in low
    if named and declared:
        return Outcome("período ausente", True, "declara o mês assumido")
    return Outcome("período ausente", False, "não declara qual mês assumiu")


def is_rate_limited(error: Exception) -> bool:
    """429 do workspace (limite de QPS do endpoint): infraestrutura, não falha do agente."""
    return "429" in str(error) or "REQUEST_LIMIT_EXCEEDED" in str(error)


async def ask(
    agent: Any, question: str, *, retries: int = 3, wait: float = 20.0
) -> tuple[str, list[str]]:
    for attempt in range(retries + 1):
        try:
            out = await agent.ainvoke({"messages": [{"role": "user", "content": question}]})
            break
        except Exception as error:
            if not is_rate_limited(error) or attempt == retries:
                raise
            print(f"  429 do workspace; nova tentativa em {wait:.0f}s ({attempt + 1}/{retries})")
            await asyncio.sleep(wait)
    tools = [tc["name"] for m in out["messages"] for tc in getattr(m, "tool_calls", None) or []]
    return str(out["messages"][-1].content), tools


async def run() -> list[Outcome]:
    import yaml  # type: ignore[import-untyped]

    app = importlib.import_module("agent_server.agent")  # só existe no ambiente de apps/agent

    cases = yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))
    tools = await asyncio.to_thread(app._tools)
    built = app.build_agent(tools)
    outcomes: list[Outcome] = []
    for case in refusal_cases(cases):
        answer, used = await ask(built, case["question"])
        print(f"\n[{case['id']}] {case['question']}\n  tools: {used or '-'}\n  resposta: {answer}")
        outcomes.append(judge_refusal(case, answer, used))
    answer, used = await ask(built, METRIC_QUESTION)
    print(f"\n[citação] {METRIC_QUESTION}\n  tools: {used}\n  resposta: {answer}")
    outcomes.append(judge_citation(answer, used))
    answer, used = await ask(built, NO_PERIOD_QUESTION)
    print(f"\n[período ausente] {NO_PERIOD_QUESTION}\n  tools: {used}\n  resposta: {answer}")
    outcomes.append(judge_assumed_month(answer))
    return outcomes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--catalog", required=True, help="catálogo do target (atlas_dev ou atlas)")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--genie-space-id", required=True)
    parser.add_argument("--prompt-version", help="versão do prompt (padrão: a do código)")
    args = parser.parse_args(argv)
    # O agente lê ATLAS_* e o perfil na importação; defina antes.
    os.environ.update(
        DATABRICKS_CONFIG_PROFILE=args.profile,
        ATLAS_CATALOG=args.catalog,
        DATABRICKS_WAREHOUSE_ID=args.warehouse_id,
        ATLAS_GENIE_SPACE_ID=args.genie_space_id,
    )
    if args.prompt_version:
        os.environ["ATLAS_PROMPT_VERSION"] = args.prompt_version
    sys.path.insert(0, str(ROOT / "apps" / "agent"))
    outcomes = asyncio.run(run())
    print("\n--- resultado ---")
    for o in outcomes:
        print(f"{'ok   ' if o.passed else 'FALHA'} {o.case}: {o.detail}")
    return 0 if all(o.passed for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
