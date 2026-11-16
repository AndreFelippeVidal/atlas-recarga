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
_NUM = r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+(?:,\d+)?"
_NUMBER = re.compile(_NUM)
# Número "principal": o primeiro com `R$` ou `%` (é o valor); senão o primeiro que não seja ano
# (1900-2099) nem ordinal ("1º", "2ª").
_MARKED_NUMBER = re.compile(rf"R\$\s*({_NUM})|({_NUM})\s*%")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_ORDINAL = re.compile(r"[ºª°]")


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
    """O número principal da resposta, fora do bloco `Fonte:`; `None` se não houver.

    Prioridade: o primeiro valor com `R$` ou `%`; senão o primeiro número que não seja ano nem
    ordinal. Escalas por extenso ("1,2 milhão") não são interpretadas.
    """
    body = strip_source_block(text)
    marked = _MARKED_NUMBER.search(body)
    if marked:
        return parse_ptbr_number(marked.group(1) or marked.group(2))
    for match in _NUMBER.finditer(body):
        token = match.group()
        if _YEAR.fullmatch(token) or _ORDINAL.match(body[match.end() : match.end() + 1]):
            continue
        return parse_ptbr_number(token)
    return None


_QUALIFIED_FN = re.compile(r"atlas(?:_[a-z0-9_]+)?\.semantic\.(fn_[a-z_]+)")


def normalize_tool_name(raw: object) -> str:
    """`fn_x`, `atlas.semantic.fn_x()` e `atlas_dev.semantic.fn_x` viram `fn_x`.

    Qualificado só vale em `atlas*.semantic`; qualquer outro prefixo (`evil.fn_x`) fica intacto
    e portanto fora da lista fechada.
    """
    name = str(raw).strip().removesuffix("()")
    match = _QUALIFIED_FN.fullmatch(name)
    return match.group(1) if match else name


def tool_names(trace: Any) -> list[str]:
    """Nomes normalizados dos spans TOOL do trace."""
    return [normalize_tool_name(span.name) for span in trace.search_spans(span_type="TOOL")]


# Tools que só descrevem o catálogo: citar a view no retorno delas não é consultar a view.
_CATALOG_ONLY_TOOLS = frozenset({"fn_list_metrics"})


def _consulted_view(trace: Any, view: str) -> bool:
    """Alguma tool de dados citou `view` como identificador inteiro (não `mv_x_daily`)."""
    pattern = re.compile(rf"(?<![a-z0-9_]){re.escape(view.lower())}(?![a-z0-9_])")
    for span in trace.search_spans(span_type="TOOL"):
        if normalize_tool_name(span.name) in _CATALOG_ONLY_TOOLS:
            continue
        payload = json.dumps(
            {"i": span.inputs, "o": span.outputs}, ensure_ascii=False, default=str
        ).lower()
        if pattern.search(payload):
            return True
    return False


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
    if not _consulted_view(trace, str(view)):
        return Result(False, f"nenhuma tool do trace consultou {view}")
    return Result(True, f"bloco `Fonte:` presente e uma tool consultou {view}")


def check_read_only_tools(trace: Any, allowed: frozenset[str] = ALLOWED_TOOLS) -> Result:
    used = tool_names(trace)
    outside = sorted({name for name in used if name not in allowed})
    if outside:
        return Result(False, f"tools fora da lista fechada: {outside}")
    note = "" if used else " (trace sem spans TOOL: confira a instrumentação)"
    return Result(True, f"{len(used)} chamada(s), todas na lista fechada{note}")


def check_no_tool_on_refusal(trace: Any, expectations: dict[str, Any]) -> Result:
    category = expectations.get("category")
    if category != "refusal":
        return _na(category, "refusal")
    used = tool_names(trace)
    if used:
        return Result(False, f"recusa com tool chamada: {used}")
    return Result(True, "nenhuma tool chamada (trace sem spans TOOL)")


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
