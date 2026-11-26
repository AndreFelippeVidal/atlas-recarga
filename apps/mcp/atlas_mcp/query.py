"""`query_metric` (SPEC-006 §3): valida por lista fechada e monta SQL com parâmetros vinculados.

Regras (princípio "sem SQL livre"):
* Todo identificador no SQL (view, medida, dimensão) vem da lista fechada do catálogo.
* Todo valor (filtros, mês) vai em `params`, nunca no texto do SQL. O `LIMIT` é um inteiro já
  validado (1..500).
* Validar vem antes de qualquer acesso ao warehouse: argumento inválido nunca executa query.
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from atlas_mcp.catalog import load_catalog
from atlas_mcp.errors import InvalidArgument

MAX_LIMIT = 500
DEFAULT_LIMIT = 50
MAX_FILTER_VALUES = 100
MAX_INT = 2**63 - 1
MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")
SEMANTIC_SCHEMA = "semantic"

Executor = Callable[[str, Mapping[str, Any]], tuple[list[str], list[list[Any]]]]


@dataclass(frozen=True)
class BuiltQuery:
    sql: str
    params: dict[str, Any]
    fingerprint: str
    source: dict[str, Any]


def _names(entries: Sequence[Mapping[str, str]]) -> list[str]:
    return [e["name"] for e in entries]


def _check_month(value: str, field: str) -> str:
    if not isinstance(value, str) or not MONTH.fullmatch(value):
        raise InvalidArgument(f"{field} deve ter o formato YYYY-MM")
    return f"{value}-01"


def _check_subset(values: Sequence[str], allowed: Sequence[str], field: str) -> list[str]:
    if isinstance(values, str):
        raise InvalidArgument(f"{field} deve ser uma lista")
    for value in values:
        if not isinstance(value, str) or value not in allowed:
            raise InvalidArgument(f"{field} fora da lista permitida: use list_metrics")
    if len(set(values)) != len(values):
        raise InvalidArgument(f"{field} com itens repetidos")
    return list(values)


def _check_filters(filters: Mapping[str, Any], dimensions: Sequence[str]) -> dict[str, Any]:
    checked: dict[str, Any] = {}
    for key, value in filters.items():
        if key not in dimensions:
            raise InvalidArgument("filters com chave que não é dimensão da view: use list_metrics")
        values = value if isinstance(value, list) else [value]
        if not values or len(values) > MAX_FILTER_VALUES:
            raise InvalidArgument(f"filters[{key}] deve ter de 1 a {MAX_FILTER_VALUES} valores")
        for item in values:
            if isinstance(item, bool) or not isinstance(item, str | int | float):
                raise InvalidArgument(f"filters[{key}] aceita só valores escalares")
            if isinstance(item, float) and not math.isfinite(item):
                raise InvalidArgument(f"filters[{key}] não aceita nan nem infinito")
            if isinstance(item, int) and abs(item) > MAX_INT:
                raise InvalidArgument(f"filters[{key}] com inteiro fora do intervalo")
        checked[key] = value
    return checked


def _check_windows(
    spec: Mapping[str, Any],
    measures: Sequence[str],
    dimensions: Sequence[str],
    start: str,
    end: str,
) -> None:
    """Medida com janela (SPEC-004 §5): um único mês e sem `recharge_year` (SPEC-006 §3).

    Com mais de um mês no filtro, ou agrupando por ano, a janela deixa de ser a validada no spike
    P15.2 e o valor sairia sem aviso. Falhar aqui evita o resultado enganoso.
    """
    windowed = {m["name"] for m in spec["measures"] if m.get("window")}
    used = [m for m in measures if m in windowed]
    if not used:
        return
    if start != end:
        raise InvalidArgument(
            f"{', '.join(used)} (medida com janela) exige month_from igual a month_to: um mês só"
        )
    if "recharge_year" in dimensions:
        raise InvalidArgument(
            f"{', '.join(used)} (medida com janela) não combina com recharge_year"
        )


def _order_clause(order_by: str | None, measures: Sequence[str], dimensions: Sequence[str]) -> str:
    """`order_by`: coluna do resultado + `asc`/`desc` (padrão: medida desc, dimensão asc)."""
    if order_by is None:
        # Sem order_by o LIMIT cortaria linhas arbitrárias: padrão = primeira medida, desc.
        return f"ORDER BY `{measures[0]}` DESC"
    column, _, direction = order_by.strip().partition(" ")
    direction = direction.strip().lower()
    if column not in [*measures, *dimensions] or direction not in {"", "asc", "desc"}:
        raise InvalidArgument("order_by deve ser uma coluna do resultado, com asc ou desc")
    default = "DESC" if column in measures else "ASC"
    return f"ORDER BY `{column}` {direction.upper() or default}"


def build_query(
    catalog: str,
    view: str,
    measures: Sequence[str],
    dimensions: Sequence[str],
    filters: Mapping[str, Any] | None,
    month_from: str,
    month_to: str,
    order_by: str | None = None,
    limit: int = DEFAULT_LIMIT,
    request_id: str | None = None,
    max_limit: int = MAX_LIMIT,
) -> BuiltQuery:
    views = load_catalog()["views"]
    if not isinstance(view, str) or view not in views:
        raise InvalidArgument(f"view deve ser uma de {sorted(views)}")
    spec = views[view]
    if not re.fullmatch(r"[a-z][a-z0-9_]*", catalog):
        raise InvalidArgument("catálogo inválido na configuração do App")
    if not measures:
        raise InvalidArgument("informe ao menos uma medida")
    ms = _check_subset(measures, _names(spec["measures"]), "measures")
    ds = _check_subset(dimensions, _names(spec["dimensions"]), "dimensions")
    fs = _check_filters(filters or {}, _names(spec["dimensions"]))
    start, end = _check_month(month_from, "month_from"), _check_month(month_to, "month_to")
    if start > end:
        raise InvalidArgument("month_from deve ser anterior ou igual a month_to")
    _check_windows(spec, ms, ds, start, end)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= max_limit:
        raise InvalidArgument(f"limit deve estar entre 1 e {max_limit}")

    params: dict[str, Any] = {"month_from": start, "month_to": end}
    where = [
        f"`{spec['period_dimension']}` >= CAST(:month_from AS DATE)",
        f"`{spec['period_dimension']}` <= CAST(:month_to AS DATE)",
    ]
    for i, (key, value) in enumerate(fs.items()):
        if isinstance(value, list):
            names = []
            for j, item in enumerate(value):
                params[f"f{i}_{j}"] = item
                names.append(f":f{i}_{j}")
            where.append(f"`{key}` IN ({', '.join(names)})")
        else:
            params[f"f{i}"] = value
            where.append(f"`{key}` = :f{i}")

    select = [f"`{d}`" for d in ds] + [f"MEASURE(`{m}`) AS `{m}`" for m in ms]
    # Só identificadores da lista fechada entram no texto; os valores ficam em `params`.
    table = f"{catalog}.{SEMANTIC_SCHEMA}.{view}"
    parts = ["SELECT", ", ".join(select), "FROM", table, "WHERE", " AND ".join(where)]
    if ds:
        parts += ["GROUP BY", ", ".join(f"`{d}`" for d in ds)]
    order = _order_clause(order_by, ms, ds)
    if order:
        parts.append(order)
    parts += ["LIMIT", str(limit)]
    sql = " ".join(parts)
    rid = request_id or str(uuid.uuid4())
    return BuiltQuery(
        sql=f"/* atlas-mcp request_id={rid} */ {sql}",
        params=params,
        # O fingerprint cobre o SQL parametrizado, sem o comentário do request_id nem os valores.
        fingerprint=hashlib.sha1(sql.encode(), usedforsecurity=False).hexdigest(),
        source={
            "view": view,
            "measures": ms,
            "dimensions": ds,
            "filters": fs,
            "month_from": month_from,
            "month_to": month_to,
        },
    )


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)  # string preserva os centavos
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def query_metric(
    catalog: str,
    executor: Executor,
    view: str,
    measures: Sequence[str],
    dimensions: Sequence[str] | None = None,
    filters: Mapping[str, Any] | None = None,
    month_from: str = "",
    month_to: str = "",
    order_by: str | None = None,
    limit: int = DEFAULT_LIMIT,
    request_id: str | None = None,
) -> dict[str, Any]:
    built = build_query(
        catalog,
        view,
        measures,
        dimensions or [],
        filters,
        month_from,
        month_to,
        order_by,
        limit,
        request_id=request_id,
    )
    columns, rows = executor(built.sql, built.params)
    return {
        "columns": columns,
        "rows": [[jsonable(v) for v in row] for row in rows],
        "source": built.source,
        "sql_fingerprint": built.fingerprint,
    }
