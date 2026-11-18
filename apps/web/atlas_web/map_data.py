"""Consultas de `/api/map/*` sobre `atlas.semantic.mv_recharges` (SPEC-007 §3).

O valor de cada nível vem de `MEASURE()` agrupado pela dimensão do nível: nada é somado aqui
(`avg_ticket` e `active_pos` não são aditivos). A única conta é o `mom_change` (Δ% de
`gross_revenue` contra o mês anterior), em Decimal. Listas fechadas e parâmetros vinculados.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from atlas_web.kpis import (
    KPI_MEASURES,
    MonthNotFound,
    _as_date,
    _delta_pct,
    _table,
    list_months,
    parse_month,
    previous_month,
)
from atlas_web.sql_client import Executor

MOM = "mom_change"
MAP_MEASURES = (*KPI_MEASURES, MOM)
REGIONS = ("N", "NE", "CO", "SE", "S")
UFS = (
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB",
    "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
)  # fmt: skip


class InvalidArgument(ValueError):
    """`measure`, `region` ou `uf` fora da lista fechada."""


def check_measure(measure: str) -> None:
    if measure not in MAP_MEASURES:
        raise InvalidArgument(f"measure deve ser um de {', '.join(MAP_MEASURES)}")


def check_region(region: str) -> None:
    if region not in REGIONS:
        raise InvalidArgument(f"region deve ser um de {', '.join(REGIONS)}")


def check_uf(uf: str) -> None:
    if uf not in UFS:  # vazio (uf ausente) também cai aqui
        raise InvalidArgument("uf deve ser uma das 27 siglas de UF")


def _values(
    catalog: str,
    execute: Executor,
    month: str,
    measure: str,
    keys: tuple[str, ...],
    where: tuple[str, str, str] | None,
) -> list[dict[str, Any]]:
    """Linhas `{<keys>, value}` do mês; `where` = (dimensão, nome do parâmetro, valor)."""
    first = parse_month(month)
    params: dict[str, Any] = {"month": first}
    extra = ""
    if where is not None:
        dim, name, value = where
        extra = f" AND `{dim}` = :{name}"
        params[name] = value
    key_list = ", ".join(f"`{k}`" for k in keys)
    if measure != MOM:
        sql = (
            f"SELECT {key_list}, MEASURE(`{measure}`) AS `value` FROM {_table(catalog)} "  # noqa: S608
            f"WHERE `recharge_month` = :month{extra} GROUP BY ALL"
        )
        _, rows = execute(sql, params)
        return [
            {**dict(zip(keys, r[:-1], strict=True)), "value": Decimal(str(r[-1]))}
            for r in rows
            if r[-1] is not None
        ]
    prev = previous_month(first)
    params["previous"] = prev
    sql = (
        f"SELECT `recharge_month`, {key_list}, MEASURE(`gross_revenue`) AS `value` "  # noqa: S608
        f"FROM {_table(catalog)} WHERE `recharge_month` IN (:month, :previous){extra} GROUP BY ALL"
    )
    _, rows = execute(sql, params)
    current: dict[tuple[Any, ...], Decimal] = {}
    before: dict[tuple[Any, ...], Decimal] = {}
    for r in rows:
        if r[-1] is None:
            continue
        target = current if _as_date(r[0]) == first else before
        target[tuple(r[1:-1])] = Decimal(str(r[-1]))
    return [
        {**dict(zip(keys, k, strict=True)), "value": _delta_pct(v, before.get(k))}
        for k, v in current.items()
    ]


def _sorted(items: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Maior valor primeiro, sem valor por último, desempate pela chave (ordem estável)."""
    return sorted(
        items,
        key=lambda i: (i["value"] is None, -(i["value"] or Decimal(0)), tuple(i[k] for k in keys)),
    )


def map_region(catalog: str, execute: Executor, month: str, measure: str) -> list[dict[str, Any]]:
    keys = ("region",)
    items = _values(catalog, execute, month, measure, keys, None)
    if not items:
        raise MonthNotFound(month)
    return _sorted(items, keys)


def map_uf(
    catalog: str, execute: Executor, month: str, measure: str, region: str | None
) -> list[dict[str, Any]]:
    keys = ("uf",)
    where = None if region is None else ("region", "region", region)
    items = _values(catalog, execute, month, measure, keys, where)
    if not items:
        raise MonthNotFound(month)
    return _sorted(items, keys)


def map_municipality(
    catalog: str, execute: Executor, month: str, measure: str, uf: str
) -> list[dict[str, Any]]:
    keys = ("municipality_ibge_code", "municipality_name")
    items = _values(catalog, execute, month, measure, keys, ("uf", "uf", uf))
    if not items and month not in list_months(catalog, execute):
        raise MonthNotFound(month)  # UF sem recarga no mês é lista vazia; mês sem dados é 404
    return _sorted(items, keys)
