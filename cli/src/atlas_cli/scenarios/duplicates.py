"""`duplicates`: 0,2% de `recharge_id` repetidos em arquivos diferentes (dedup no silver)."""

from datetime import date

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from atlas_cli.arrow_utils import set_rows
from atlas_cli.scenarios.base import Context, distribute, share_of_rows

ID = "duplicates"
DESCRIPTION = "0,2% de recharge_id repetidos, a copia chega na particao do dia seguinte"
PARAMETERS = {"share": "0,2%", "where": "particao D+1"}


class Duplicates:
    def __init__(self, ctx: Context) -> None:
        total = share_of_rows(ctx.rows, 20)
        counts = [0, *distribute(total, ctx.day_counts[1:])] if len(ctx.days) > 1 else [0]
        self.planned = {d: c for d, c in zip(ctx.days, counts, strict=True) if c}
        self.rows = 0

    def planned_for(self, day: date) -> int:
        return self.planned.get(day, 0)

    def apply(
        self,
        table: pa.Table,
        idx: NDArray[np.int64],
        source: pa.Table | None,
        rng: np.random.Generator,
    ) -> tuple[pa.Table, NDArray[np.int64]]:
        """Troca as linhas `idx` por cópias de `source` (dia anterior); devolve as linhas usadas."""
        if source is None or source.num_rows == 0 or len(idx) == 0:
            return table, idx[:0]
        k = min(len(idx), source.num_rows)
        used = np.sort(idx[:k])
        picked = source.take(pa.array(np.sort(rng.choice(source.num_rows, size=k, replace=False))))
        for name in table.schema.names:
            if name != "ingested_at_utc":  # a cópia chega na ingestão da partição D+1
                table = set_rows(table, name, used, picked[name].combine_chunks())
        self.rows += k
        return table, used

    def stats(self) -> dict[str, int | str]:
        return {"rows": self.rows}
