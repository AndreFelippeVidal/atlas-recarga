"""Filtros `pos_type` e `distributor` e `/api/filters` (SPEC-007 §3, v1.1).

Os dois filtros recortam o `WHERE` da metric view antes da conta, sempre como parâmetros
vinculados (nunca concatenados). `pos_type` valida contra uma lista fechada; `distributor`
contra o resultado de `list_filters`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from atlas_web.kpis import _table
from atlas_web.sql_client import Executor

POS_TYPES = ("newsstand", "pharmacy", "grocery", "lottery", "partner_app")


class InvalidFilter(ValueError):
    """`pos_type` ou `distributor` fora dos valores válidos."""


@dataclass(frozen=True)
class Filters:
    pos_type: str | None = None
    distributor: str | None = None

    @property
    def active(self) -> bool:
        return self.pos_type is not None or self.distributor is not None

    @property
    def key(self) -> tuple[str | None, str | None]:
        """Parte da chave de cache de cada endpoint."""
        return (self.pos_type, self.distributor)

    def sql(self) -> tuple[str, dict[str, Any]]:
        """Condições ` AND ...` (com parâmetros vinculados) para o `WHERE` da metric view."""
        clause, params = "", {}
        if self.pos_type is not None:
            clause += " AND `pos_type` = :pos_type"
            params["pos_type"] = self.pos_type
        if self.distributor is not None:
            clause += " AND `distributor_name` = :distributor"
            params["distributor"] = self.distributor
        return clause, params


NO_FILTERS = Filters()


def check_pos_type(pos_type: str) -> None:
    if pos_type not in POS_TYPES:
        raise InvalidFilter(f"pos_type deve ser um de {', '.join(POS_TYPES)}")


def list_filters(catalog: str, execute: Executor) -> dict[str, list[str]]:
    """Valores distintos das dimensões da metric view (sem `MEASURE()`)."""
    sql = (
        "SELECT DISTINCT `pos_type`, `distributor_name` "  # noqa: S608
        f"FROM {_table(catalog)}"
    )
    _, rows = execute(sql, {})
    pos_types = sorted({str(r[0]) for r in rows if r[0] is not None})
    distributors = sorted({str(r[1]) for r in rows if r[1] is not None})
    return {"pos_types": pos_types, "distributors": distributors}
