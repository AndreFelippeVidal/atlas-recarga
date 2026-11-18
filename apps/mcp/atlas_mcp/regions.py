"""`top_regions` e `compare_months` (SPEC-006 §3): ranking e comparação por nível geográfico.

Só `mv_recharges` (a única view com `ddd`). Reaproveitam `build_query`, então valem as mesmas
regras: identificadores da lista fechada, valores em parâmetros vinculados, validação antes de
qualquer acesso ao warehouse. Δ e Δ% são aritmética sobre o resultado de duas consultas da
mesma medida da metric view; não redefinem a métrica (princípio: definição única na semantic).
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from atlas_mcp.errors import InvalidArgument, too_large
from atlas_mcp.query import MAX_LIMIT, Executor, build_query, jsonable

VIEW = "mv_recharges"
MAX_TOP_N = 50
DEFAULT_TOP_N = 10
LEVELS: dict[str, list[str]] = {
    "region": ["region"],
    "uf": ["uf"],
    "municipality": ["municipality_ibge_code", "municipality_name"],
    "ddd": ["ddd"],
}
PCT = Decimal("0.01")


def _check_level(level: str) -> list[str]:
    if not isinstance(level, str) or level not in LEVELS:
        raise InvalidArgument(f"level deve ser um de {sorted(LEVELS)}")
    return LEVELS[level]


def _check_measure(measure: str) -> str:
    if not isinstance(measure, str):
        raise InvalidArgument("measure deve ser texto: use list_metrics")
    return measure


def _uf_filter(uf: str | None) -> dict[str, Any]:
    if uf is None:
        return {}
    if not isinstance(uf, str) or not uf.strip():
        raise InvalidArgument("uf deve ser um texto não vazio")
    return {"uf": uf}


def top_regions(
    catalog: str,
    executor: Executor,
    measure: str,
    level: str,
    month: str,
    n: int = DEFAULT_TOP_N,
    uf: str | None = None,
) -> dict[str, Any]:
    dims = _check_level(level)
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_TOP_N:
        raise InvalidArgument(f"n deve estar entre 1 e {MAX_TOP_N}")
    built = build_query(
        catalog,
        VIEW,
        [_check_measure(measure)],
        dims,
        _uf_filter(uf),
        month,
        month,
        order_by=f"{measure} desc",
        limit=n,
    )
    columns, rows = executor(built.sql, built.params)
    return {
        "columns": columns,
        "rows": [[jsonable(v) for v in row] for row in rows],
        "source": {
            "view": VIEW,
            "measures": [measure],
            "dimensions": dims,
            "filters": built.source["filters"],
            "month": month,
            "level": level,
            "n": n,
        },
        "sql_fingerprint": built.fingerprint,
    }


def _number(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _delta(a: Decimal | None, b: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    if a is None or b is None:
        return None, None
    pct = None if a == 0 else ((b - a) / a * 100).quantize(PCT, rounding=ROUND_HALF_EVEN)
    return b - a, pct


def compare_months(
    catalog: str,
    executor: Executor,
    measure: str,
    month_a: str,
    month_b: str,
    level: str,
    uf: str | None = None,
) -> dict[str, Any]:
    dims = _check_level(level)
    filters = _uf_filter(uf)
    request_id = str(uuid.uuid4())
    # Pede 1 linha além do teto: se vier, o resultado não cabe e o cliente deve filtrar.
    built = [
        build_query(
            catalog,
            VIEW,
            [_check_measure(measure)],
            dims,
            filters,
            month,
            month,
            order_by=f"{measure} desc",
            limit=MAX_LIMIT + 1,
            request_id=request_id,
            max_limit=MAX_LIMIT + 1,
        )
        for month in (month_a, month_b)
    ]
    values: dict[tuple[Any, ...], list[Decimal | None]] = {}
    for slot, query in enumerate(built):
        _, rows = executor(query.sql, query.params)
        if len(rows) > MAX_LIMIT:
            raise too_large(MAX_LIMIT)
        for row in rows:
            key = tuple(jsonable(v) for v in row[: len(dims)])
            values.setdefault(key, [None, None])[slot] = _number(row[len(dims)])
    if len(values) > MAX_LIMIT:
        raise too_large(MAX_LIMIT)

    table = []
    for key, (a, b) in values.items():
        delta_abs, delta_pct = _delta(a, b)
        table.append((key, a, b, delta_abs, delta_pct))
    # Maior variação absoluta primeiro; sem comparação possível (None) por último.
    table.sort(
        key=lambda r: (r[3] is None, -abs(r[3]) if r[3] is not None else 0, [str(x) for x in r[0]])
    )
    return {
        "columns": [*dims, "value_a", "value_b", "delta_abs", "delta_pct"],
        "rows": [
            [*key, *(None if v is None else str(v) for v in (a, b, d_abs, d_pct))]
            for key, a, b, d_abs, d_pct in table
        ],
        "source": {
            "view": VIEW,
            "measures": [measure],
            "dimensions": dims,
            "filters": built[0].source["filters"],
            "month_a": month_a,
            "month_b": month_b,
            "level": level,
        },
        "sql_fingerprint": built[0].fingerprint,
    }
