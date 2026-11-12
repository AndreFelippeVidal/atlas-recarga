"""`fractioning`: 3 PDVs fazem rajadas de recargas de R$ 10 ao mesmo assinante em < 2 min."""

from datetime import date

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from atlas_cli.arrow_utils import set_rows
from atlas_cli.scenarios.base import Context, Substitution, plan_rng

BURSTS = 3
BURST_SIZE = 30
BURST_SPAN_SECONDS = 110  # a rajada inteira cabe em menos de 2 minutos
AMOUNT_CENTS = 1_000
SP_OFFSET_HOURS = 3  # hora de São Paulo -> UTC
_EPOCH = date(1970, 1, 1).toordinal()


class Fractioning(Substitution):
    id = "fractioning"
    description = "3 PDVs com rajadas de 30 recargas de R$ 10 ao mesmo assinante em < 2 min"
    parameters = {"pos": str(BURSTS), "burst_size": str(BURST_SIZE), "span": "<2min"}  # noqa: RUF012

    def __init__(self, ctx: Context) -> None:
        rng = plan_rng(ctx.seed, 1)
        picks = rng.choice(len(ctx.days), size=BURSTS, replace=len(ctx.days) < BURSTS)
        self.bursts: dict[date, list[tuple[str, str, int]]] = {}
        taken: set[str] = set()
        for i in picks:
            day = ctx.days[int(i)]
            d64 = np.datetime64(day, "D")
            active = (ctx.pos_opened <= d64) & (ctx.pos_closed >= d64)
            candidates = [p for p in ctx.pos_ids[active] if p not in taken]
            if not candidates:
                continue
            pos_id = str(candidates[int(rng.integers(len(candidates)))])
            taken.add(pos_id)
            subscriber = f"SUB-{int(rng.integers(0, 2**40)):010x}"
            start = int(rng.integers(8, 20)) * 3_600 + int(rng.integers(0, 3_000))
            self.bursts.setdefault(day, []).append((pos_id, subscriber, start))
        self._day = date.min
        super().__init__(ctx, {d: BURST_SIZE * len(b) for d, b in self.bursts.items()})
        self.pos_with_burst: set[str] = set()

    def start_day(self, day: date) -> None:
        self._day = day

    def apply(self, table: pa.Table, idx: NDArray[np.int64], rng: np.random.Generator) -> pa.Table:
        bursts = self.bursts[self._day]
        n = len(idx)
        which = np.arange(n) // BURST_SIZE
        pos = [bursts[k][0] for k in which]
        sub = [bursts[k][1] for k in which]
        base = (self._day.toordinal() - _EPOCH) * 86_400 + SP_OFFSET_HOURS * 3_600
        ts = np.array(
            [
                (base + bursts[k][2] + (j % BURST_SIZE) * BURST_SPAN_SECONDS // (BURST_SIZE - 1))
                * 1_000_000
                for j, k in enumerate(which)
            ],
            dtype=np.int64,
        )
        self.rows += n
        self.pos_with_burst.update(pos)
        table = set_rows(table, "pos_id", idx, pa.array(pos, pa.string()))
        table = set_rows(table, "subscriber_id", idx, pa.array(sub, pa.string()))
        table = set_rows(
            table,
            "recharge_ts_utc",
            idx,
            pa.array(ts, pa.int64()).cast(pa.timestamp("us", tz="UTC")),
        )
        cents = np.full(n, AMOUNT_CENTS, dtype=np.int64)
        words = np.empty((n, 2), dtype=np.int64)
        words[:, 0], words[:, 1] = cents, 0
        amount = pa.Array.from_buffers(
            pa.decimal128(10, 2), n, [None, pa.py_buffer(words.tobytes())]
        )
        table = set_rows(table, "amount_brl", idx, amount)
        return set_rows(table, "status", idx, pa.array(["approved"] * n, pa.string()))

    def stats(self) -> dict[str, int | str]:
        return {
            "rows": self.rows,
            "pos": len(self.pos_with_burst),
            "bursts": sum(map(len, self.bursts.values())),
        }
