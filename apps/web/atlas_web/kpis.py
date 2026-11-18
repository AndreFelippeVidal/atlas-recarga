"""Consultas de `/api/months` e `/api/kpis` sobre `atlas.semantic.mv_recharges` (SPEC-007 §3).

Toda métrica vem de `MEASURE()`; o Δ% é a única conta feita aqui (mês contra mês anterior) e usa
Decimal, nunca float (tech-stack: dinheiro em DECIMAL).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from atlas_web.sql_client import Executor

VIEW = "mv_recharges"
SEMANTIC_SCHEMA = "semantic"
KPI_MEASURES = ("gross_revenue", "recharge_count", "avg_ticket", "active_pos")
MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
CATALOG_RE = re.compile(r"[a-z][a-z0-9_]*")
PCT_PLACES = Decimal("0.01")


class InvalidMonth(ValueError):
    """`month` fora do formato YYYY-MM."""


class MonthNotFound(LookupError):
    """Mês sem nenhuma recarga aprovada na metric view."""


def parse_month(month: str) -> date:
    if not MONTH_RE.fullmatch(month):
        raise InvalidMonth("month deve ter o formato YYYY-MM")
    return date(int(month[:4]), int(month[5:]), 1)


def previous_month(first_day: date) -> date:
    return (
        date(first_day.year - 1, 12, 1)
        if first_day.month == 1
        else date(first_day.year, first_day.month - 1, 1)
    )


def _as_date(value: date | datetime) -> date:
    """`DATE_TRUNC('MONTH', ...)` chega como TIMESTAMP (datetime) do conector; a chave é a data."""
    return value.date() if isinstance(value, datetime) else value


def _table(catalog: str) -> str:
    if not CATALOG_RE.fullmatch(catalog):
        raise ValueError("catálogo inválido")
    return f"{catalog}.{SEMANTIC_SCHEMA}.{VIEW}"


def list_months(catalog: str, execute: Executor) -> list[str]:
    """Meses com receita, do mais recente para o mais antigo (`YYYY-MM`)."""
    sql = (
        f"SELECT `recharge_month`, MEASURE(`gross_revenue`) AS `gross_revenue` "  # noqa: S608
        f"FROM {_table(catalog)} GROUP BY ALL ORDER BY `recharge_month` DESC"
    )
    _, rows = execute(sql, {})
    return [_as_date(r[0]).strftime("%Y-%m") for r in rows if r[1] is not None]


def _delta_pct(current: Decimal, previous: Decimal | None) -> Decimal | None:
    if previous is None or previous == 0:
        return None
    return ((current - previous) / previous * 100).quantize(PCT_PLACES, ROUND_HALF_EVEN)


def kpis(catalog: str, execute: Executor, month: str) -> dict[str, Any]:
    first = parse_month(month)
    prev = previous_month(first)
    measures = ", ".join(f"MEASURE(`{m}`) AS `{m}`" for m in KPI_MEASURES)
    sql = (
        f"SELECT `recharge_month`, {measures} FROM {_table(catalog)} "  # noqa: S608
        "WHERE `recharge_month` IN (:month, :previous) GROUP BY ALL"
    )
    columns, rows = execute(sql, {"month": first, "previous": prev})
    by_month = {_as_date(r[0]): dict(zip(columns[1:], r[1:], strict=True)) for r in rows}
    current = by_month.get(first)
    if current is None or current["gross_revenue"] is None:
        raise MonthNotFound(month)
    before = by_month.get(prev)
    result: dict[str, Any] = {"month": month, "previous_month": prev.strftime("%Y-%m")}
    for m in KPI_MEASURES:
        value = Decimal(str(current[m]))
        previous = None if before is None or before[m] is None else Decimal(str(before[m]))
        result[m] = {"value": value, "previous": previous, "delta_pct": _delta_pct(value, previous)}
    return result
