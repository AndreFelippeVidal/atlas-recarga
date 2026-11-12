"""`null_pos`: 0,05% das recargas com `pos_id` nulo (drop no silver)."""

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from atlas_cli.arrow_utils import set_rows
from atlas_cli.scenarios.base import Context, Substitution, proportional_plan, share_of_rows


class NullPos(Substitution):
    id = "null_pos"
    description = "0,05% das recargas com pos_id nulo"
    parameters = {"share": "0,05%"}  # noqa: RUF012

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, proportional_plan(ctx, share_of_rows(ctx.rows, 5)))

    def apply(self, table: pa.Table, idx: NDArray[np.int64], rng: np.random.Generator) -> pa.Table:
        self.rows += len(idx)
        return set_rows(table, "pos_id", idx, pa.nulls(len(idx), pa.string()))
