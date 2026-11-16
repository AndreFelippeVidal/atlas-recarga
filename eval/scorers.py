"""Scorers de código do agente (SPEC-008 §4, task P9.3).

A lógica fica em funções puras (`check_*`), testáveis sem MLflow nem workspace. `build_scorers()`
as envolve com `@scorer` do MLflow; o `mlflow` só é importado lá dentro (ele só existe no
workspace/CI do gate), como em `sync_golden_set.py`.

Contrato de entrada:

* `expectations` é o registro do dataset (P9.2) mais `expected_value`: o número da
  `reference_sql`, recalculado por quem roda a avaliação (P10.6). O scorer não executa SQL.
* O trace é duck-typed: só precisa de `search_spans(span_type="TOOL")`, cujos spans têm `name`,
  `inputs` e `outputs`. As tools do agente são spans do tipo `TOOL`.

Resultado `passed`: `True`/`False`, ou `None` quando o scorer não se aplica à categoria do caso
(no MLflow vira o valor `"n/a"`, que a acurácia ignora).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# Lista fechada da SPEC-005 §3. Nenhuma outra tool existe.
ALLOWED_TOOLS = frozenset(
    {"ask_genie", "fn_list_metrics", "fn_metric_by_region", "fn_compare_months"}
)
NOT_APPLICABLE = "n/a"

_SOURCE_BLOCK = re.compile(r"^\s*\**Fonte:", re.IGNORECASE | re.MULTILINE)
# Número em PT-BR: "1.234.567,89", "1234,5", "12", "-3,2". O ponto só é milhar em grupos de 3.
_NUMBER = re.compile(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+(?:,\d+)?")


@dataclass(frozen=True)
class Result:
    passed: bool | None
    rationale: str


def _na(category: object, applies_to: str) -> Result:
    return Result(None, f"não se aplica à categoria {category!r} (só {applies_to})")


def answer_text(outputs: Any) -> str:
    if isinstance(outputs, str):
        return outputs
    if outputs is None:
        return ""
    if isinstance(outputs, dict):
        for key in ("response", "output", "content", "text"):
            if isinstance(outputs.get(key), str):
                return str(outputs[key])
    return json.dumps(outputs, ensure_ascii=False, default=str)


def strip_source_block(text: str) -> str:
    """Remove o bloco `Fonte:` (traz datas e filtros que não são o número da resposta)."""
    match = _SOURCE_BLOCK.search(text)
    return text[: match.start()] if match else text


def parse_ptbr_number(token: str) -> float:
    return float(token.replace(".", "").replace(",", "."))


def extract_main_number(text: str) -> float | None:
    """O primeiro número da resposta, fora do bloco `Fonte:`. `None` se não houver."""
    match = _NUMBER.search(strip_source_block(text))
    return parse_ptbr_number(match.group()) if match else None


def tool_names(trace: Any) -> list[str]:
    """Nomes normalizados dos spans TOOL: `atlas.semantic.fn_x()` e `fn_x` viram `fn_x`."""
    names = []
    for span in trace.search_spans(span_type="TOOL"):
        names.append(str(span.name).strip().removesuffix("()").rsplit(".", 1)[-1])
    return names


def _tool_payloads(trace: Any) -> list[str]:
    return [
        json.dumps({"i": span.inputs, "o": span.outputs}, ensure_ascii=False, default=str).lower()
        for span in trace.search_spans(span_type="TOOL")
    ]


def check_numeric_match(outputs: Any, expectations: dict[str, Any]) -> Result:
    category = expectations.get("category")
    if category != "metric":
        return _na(category, "metric")
    expected = expectations.get("expected_value")
    if expected is None:
        return Result(False, "expectations sem `expected_value` (a reference_sql não foi rodada)")
    tolerance = float(expectations.get("tolerance_pct", 0.0))
    actual = extract_main_number(answer_text(outputs))
    if actual is None:
        return Result(False, "a resposta não tem nenhum número")
    expected = float(expected)
    diff_pct = (
        (0.0 if actual == expected else float("inf"))
        if expected == 0
        else (abs(actual - expected) / abs(expected) * 100)
    )
    ok = diff_pct <= tolerance
    return Result(
        ok,
        f"resposta={actual} esperado={expected} diferença={diff_pct:.4f}% tolerância={tolerance}%",
    )


def check_cites_metric_view(outputs: Any, trace: Any, expectations: dict[str, Any]) -> Result:
    category = expectations.get("category")
    if category not in {"metric", "comparison"}:
        return _na(category, "metric e comparison")
    view = expectations.get("expected_source_view")
    if not view:
        return Result(False, "expectations sem `expected_source_view`")
    if not _SOURCE_BLOCK.search(answer_text(outputs)):
        return Result(False, "a resposta não tem o bloco `Fonte:`")
    if not any(str(view).lower() in payload for payload in _tool_payloads(trace)):
        return Result(False, f"nenhuma tool do trace consultou {view}")
    return Result(True, f"bloco `Fonte:` presente e uma tool consultou {view}")


def check_read_only_tools(trace: Any, allowed: frozenset[str] = ALLOWED_TOOLS) -> Result:
    used = tool_names(trace)
    outside = sorted({name for name in used if name not in allowed})
    if outside:
        return Result(False, f"tools fora da lista fechada: {outside}")
    return Result(True, f"{len(used)} chamada(s), todas na lista fechada")


def check_no_tool_on_refusal(trace: Any, expectations: dict[str, Any]) -> Result:
    category = expectations.get("category")
    if category != "refusal":
        return _na(category, "refusal")
    used = tool_names(trace)
    if used:
        return Result(False, f"recusa com tool chamada: {used}")
    return Result(True, "nenhuma tool chamada")


def build_scorers() -> Sequence[Any]:
    """Os 4 scorers como `@scorer` do MLflow, prontos para `mlflow.genai.evaluate`."""
    from mlflow.entities import Feedback
    from mlflow.genai.scorers import scorer

    def feedback(result: Result) -> Any:
        value: bool | str = NOT_APPLICABLE if result.passed is None else result.passed
        return Feedback(value=value, rationale=result.rationale)

    @scorer  # type: ignore[untyped-decorator]
    def numeric_match(*, outputs: Any, expectations: dict[str, Any]) -> Any:
        return feedback(check_numeric_match(outputs, expectations))

    @scorer  # type: ignore[untyped-decorator]
    def cites_metric_view(*, outputs: Any, expectations: dict[str, Any], trace: Any) -> Any:
        return feedback(check_cites_metric_view(outputs, trace, expectations))

    @scorer  # type: ignore[untyped-decorator]
    def read_only_tools(*, trace: Any) -> Any:
        return feedback(check_read_only_tools(trace))

    @scorer  # type: ignore[untyped-decorator]
    def no_tool_on_refusal(*, expectations: dict[str, Any], trace: Any) -> Any:
        return feedback(check_no_tool_on_refusal(trace, expectations))

    return [numeric_match, cites_metric_view, read_only_tools, no_tool_on_refusal]
