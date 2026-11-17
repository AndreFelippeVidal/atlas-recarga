"""Scorers de código do agente (SPEC-008 §4, task P9.3).

A lógica fica em funções puras (`check_*`), testáveis sem MLflow nem workspace. `build_scorers()`
as envolve com `@scorer` do MLflow; o `mlflow` só é importado lá dentro (ele só existe no
workspace/CI do gate), como em `sync_golden_set.py`.

Contrato de entrada:

* `expectations` é o registro do dataset (P9.2) mais `expected_value`: o número da
  `reference_sql` e, nos casos `no_period`, `expected_month`: o mês da `reference_month_sql`
  (`AAAA-MM-DD`). Os dois são recalculados por quem roda a avaliação (P10.6). O scorer não
  executa SQL.
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
# As UC functions de dados leem só `mv_recharges` (SPEC-005 §3), mas o retorno delas (CSV de
# `level,key,label,value`) não traz o nome da view: a consulta vale pelo contrato da função.
_TOOL_VIEWS = {
    "fn_metric_by_region": frozenset({"mv_recharges"}),
    "fn_compare_months": frozenset({"mv_recharges"}),
}


def _consulted_view(trace: Any, view: str) -> bool:
    """Alguma tool de dados citou `view` como identificador inteiro (não `mv_x_daily`)."""
    pattern = re.compile(rf"(?<![a-z0-9_]){re.escape(view.lower())}(?![a-z0-9_])")
    for span in trace.search_spans(span_type="TOOL"):
        name = normalize_tool_name(span.name)
        if name in _CATALOG_ONLY_TOOLS:
            continue
        if view.lower() in _TOOL_VIEWS.get(name, frozenset()):
            return True
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


_MONTHS = (
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
)
# Quantos caracteres do começo da resposta valem como "o começo" (a frase do prompt tem ~120).
OPENING_CHARS = 250
_LATEST_MONTH = re.compile(r"último mês|ultimo mes|mês mais recente|mes mais recente")
_ISO_MONTH = re.compile(r"^(\d{4})-(\d{2})")


def _month_parts(value: object) -> tuple[int, int] | None:
    """`2026-10-01` ou `2026-10` vira `(2026, 10)`; qualquer outra coisa, `None`."""
    match = _ISO_MONTH.match(str(value).strip())
    if not match or not 1 <= int(match.group(2)) <= 12:
        return None
    return int(match.group(1)), int(match.group(2))


def _months_named(text: str) -> set[int]:
    lowered = text.lower()
    return {i + 1 for i, name in enumerate(_MONTHS) if name in lowered}


def _tool_returned_month(trace: Any, year: int, month: int) -> bool:
    """O mês aparece no retorno de alguma tool (`2026-10` ou o nome por extenso)."""
    iso = f"{year:04d}-{month:02d}"
    name = _MONTHS[month - 1]
    for span in trace.search_spans(span_type="TOOL"):
        out = json.dumps(span.outputs, ensure_ascii=False, default=str).lower()
        if iso in out or name in out:
            return True
    return False


def check_declares_assumed_month(outputs: Any, trace: Any, expectations: dict[str, Any]) -> Result:
    """Período ausente (SPEC-005 §4, regra 4): declara o mês assumido, que veio de tool.

    Passa só se, no começo da resposta, aparece o mês esperado (e nenhum outro) junto da ideia de
    "último mês"; o mês aparece no retorno de uma tool; e o número bate com a `reference_sql`.
    """
    category = expectations.get("category")
    if category != "no_period":
        return _na(category, "no_period")
    expected_month = _month_parts(expectations.get("expected_month"))
    if expected_month is None:
        return Result(False, "expectations sem `expected_month` (a reference_month_sql não rodou)")
    year, month = expected_month
    text = answer_text(outputs)
    opening = text.strip()[:OPENING_CHARS]
    named = _months_named(opening)
    if named != {month}:
        shown = sorted(_MONTHS[m - 1] for m in named) or "nenhum"
        return Result(
            False,
            f"o começo da resposta cita {shown}, esperava só {_MONTHS[month - 1]} (último mês)",
        )
    if not _LATEST_MONTH.search(opening.lower()):
        return Result(False, "o começo da resposta não diz que assumiu o último mês")
    if not _tool_returned_month(trace, year, month):
        return Result(False, f"nenhuma tool devolveu o mês {year:04d}-{month:02d}")
    value = check_numeric_match(text, {**expectations, "category": "metric"})
    if not value.passed:
        return Result(False, f"número: {value.rationale}")
    return Result(
        True, f"declara {_MONTHS[month - 1]} como último mês, vindo de tool; {value.rationale}"
    )


def check_cites_metric_view(outputs: Any, trace: Any, expectations: dict[str, Any]) -> Result:
    category = expectations.get("category")
    if category not in {"metric", "comparison", "no_period"}:
        return _na(category, "metric, comparison e no_period")
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
    """Os 5 scorers como `@scorer` do MLflow, prontos para `mlflow.genai.evaluate`."""
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

    @scorer  # type: ignore[untyped-decorator]
    def declares_assumed_month(*, outputs: Any, expectations: dict[str, Any], trace: Any) -> Any:
        return feedback(check_declares_assumed_month(outputs, trace, expectations))

    return [
        numeric_match,
        cites_metric_view,
        read_only_tools,
        no_tool_on_refusal,
        declares_assumed_month,
    ]
