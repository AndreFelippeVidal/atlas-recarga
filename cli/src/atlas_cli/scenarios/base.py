"""Contexto e utilitários comuns dos cenários (SPEC-001 §5).

Cada cenário é um módulo com uma classe. Os cenários não importam `recharges`: recebem o
que precisam em `Context`, para que `recharges` possa chamar o injetor sem ciclo.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray


@dataclass(frozen=True)
class Context:
    seed: int
    rows: int
    days: tuple[date, ...]
    day_counts: tuple[int, ...]  # recargas-base por dia, na ordem de `days`
    pos_ids: NDArray[np.object_]
    pos_municipality: NDArray[np.object_]
    pos_opened: NDArray[np.datetime64]
    pos_closed: NDArray[np.datetime64]  # NaT já trocado por uma data muito no futuro


def distribute(total: int, weights: Sequence[int]) -> list[int]:
    """Divide `total` proporcional a `weights`, soma exata (maior resto; aritmética inteira)."""
    whole = sum(weights)
    if total <= 0 or whole <= 0:
        return [0] * len(weights)
    counts = [total * w // whole for w in weights]
    remainders = [total * w % whole for w in weights]
    missing = total - sum(counts)
    for i in sorted(range(len(weights)), key=lambda i: (-remainders[i], i))[:missing]:
        counts[i] += 1
    return counts


def share_of_rows(rows: int, basis_points: int) -> int:
    """`basis_points` (1/10.000) de `rows`, para cima, com mínimo 1 (o cenário sempre aparece)."""
    return max(1, -(-rows * basis_points // 10_000))


def plan_rng(seed: int, scenario_index: int) -> np.random.Generator:
    return np.random.default_rng([seed, 6, scenario_index])


def day_rng(seed: int, day: date, stream: int) -> np.random.Generator:
    return np.random.default_rng([seed, 5, day.toordinal(), stream])


def proportional_plan(ctx: Context, total: int) -> dict[date, int]:
    """Linhas por dia, proporcionais ao volume-base do dia."""
    counts = distribute(total, ctx.day_counts)
    return {d: c for d, c in zip(ctx.days, counts, strict=True) if c}


class Substitution:
    """Cenário que altera, no lugar, `planned[day]` linhas do dia (o total não muda)."""

    id = ""
    description = ""
    parameters: dict[str, str] = {}  # noqa: RUF012

    def __init__(self, ctx: Context, planned: dict[date, int]) -> None:
        self.ctx = ctx
        self.planned = planned
        self.rows = 0

    def planned_for(self, day: date) -> int:
        return self.planned.get(day, 0)

    def apply(self, table: pa.Table, idx: NDArray[np.int64], rng: np.random.Generator) -> pa.Table:
        raise NotImplementedError

    def stats(self) -> dict[str, int | str]:
        return {"rows": self.rows}
