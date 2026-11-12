"""`late_arrival`: 0,5% das recargas de um dia aparecem no arquivo do dia seguinte."""

from datetime import date

import pyarrow as pa
import pyarrow.compute as pc

from atlas_cli.scenarios.base import Context

ID = "late_arrival"
DESCRIPTION = "0,5% das recargas de cada dia chegam em recharges/dt=D+1/part-0001"
PARAMETERS = {"share": "0,5%", "file": "part-0001 do dia seguinte"}

SHARE_PER_MILLE = 5
ONE_DAY_US = 86_400 * 1_000_000


class LateArrival:
    def __init__(self, ctx: Context) -> None:
        last = ctx.days[-1]
        self.planned = {
            d: (c * SHARE_PER_MILLE + 500) // 1000  # arredonda para o inteiro mais próximo
            for d, c in zip(ctx.days, ctx.day_counts, strict=True)
            if d != last
        }
        self.rows = 0

    def planned_for(self, day: date) -> int:
        return self.planned.get(day, 0)

    def delay(self, late: pa.Table) -> pa.Table:
        """As linhas entram na partição D+1: ganham o `ingested_at_utc` dela, 1 dia depois."""
        self.rows += late.num_rows
        index = late.schema.get_field_index("ingested_at_utc")
        shifted = pc.add(late["ingested_at_utc"], pa.scalar(ONE_DAY_US, pa.duration("us")))
        return late.set_column(index, late.schema.field(index), shifted)

    def stats(self) -> dict[str, int | str]:
        return {"rows": self.rows}
