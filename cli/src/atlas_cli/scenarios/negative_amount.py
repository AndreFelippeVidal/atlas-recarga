"""`negative_amount`: 10 recargas com valor negativo (drop no silver)."""

from datetime import date

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from numpy.typing import NDArray

from atlas_cli.arrow_utils import set_rows
from atlas_cli.scenarios.base import (
    Context,
    Substitution,
    plan_rng,
)

NEGATIVE_ROWS = 10


class NegativeAmount(Substitution):
    id = "negative_amount"
    description = "10 recargas com valor negativo"
    parameters = {"rows": str(NEGATIVE_ROWS)}  # noqa: RUF012

    def __init__(self, ctx: Context) -> None:
        rng = plan_rng(ctx.seed, 4)
        picks = rng.choice(len(ctx.days), size=NEGATIVE_ROWS, replace=len(ctx.days) < NEGATIVE_ROWS)
        planned: dict[date, int] = {}
        for i in picks:
            day = ctx.days[int(i)]
            planned[day] = planned.get(day, 0) + 1
        super().__init__(ctx, planned)

    def apply(self, table: pa.Table, idx: NDArray[np.int64], rng: np.random.Generator) -> pa.Table:
        self.rows += len(idx)
        return set_rows(table, "amount_brl", idx, pc.negate(table["amount_brl"].take(idx)))
