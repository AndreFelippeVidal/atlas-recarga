"""Injetor de cenários: aplica as anomalias da SPEC-001 §5 dia a dia, de forma determinística.

Cada dia sorteia uma permutação das suas linhas e entrega fatias disjuntas a cada cenário,
então uma linha nunca é alterada por dois cenários. As linhas injetadas substituem linhas
normais (o total não muda); só `regional_drop` remove linhas.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from atlas_cli.scenarios import SCENARIO_IDS
from atlas_cli.scenarios.base import Context, day_rng
from atlas_cli.scenarios.duplicates import Duplicates
from atlas_cli.scenarios.fractioning import Fractioning
from atlas_cli.scenarios.late_arrival import LateArrival
from atlas_cli.scenarios.negative_amount import NegativeAmount
from atlas_cli.scenarios.null_pos import NullPos
from atlas_cli.scenarios.regional_drop import RegionalDrop
from atlas_cli.scenarios.unknown_pos import UnknownPos


class HasStats(Protocol):
    def stats(self) -> dict[str, int | str]: ...


@dataclass(frozen=True)
class DayOutput:
    main: pa.Table  # `recharges/dt=D/part-0000`
    late: pa.Table | None  # linhas de D que vão para `recharges/dt=D+1/part-0001`


class Injector:
    def __init__(self, ctx: Context, enabled: tuple[str, ...]) -> None:
        on = set(enabled)
        self.ctx = ctx
        self.enabled = [i for i in SCENARIO_IDS if i in on]
        self.drop = RegionalDrop(ctx) if "regional_drop" in on else None
        self.duplicates = Duplicates(ctx) if "duplicates" in on else None
        self.fractioning = Fractioning(ctx) if "fractioning" in on else None
        self.late = LateArrival(ctx) if "late_arrival" in on else None
        self.substitutions = [
            cls(ctx)
            for cls, key in (
                (NullPos, "null_pos"),
                (UnknownPos, "unknown_pos"),
                (NegativeAmount, "negative_amount"),
            )
            if key in on
        ]
        self._prev_clean: pa.Table | None = None

    def process(self, day: date, table: pa.Table) -> DayOutput:
        seed = self.ctx.seed
        if self.drop:
            table = self.drop.apply(table, day, day_rng(seed, day, 1))
        n = table.num_rows
        perm = day_rng(seed, day, 0).permutation(n)
        touched = np.zeros(n, dtype=bool)
        cursor = 0

        def take(wanted: int) -> NDArray[np.int64]:
            nonlocal cursor
            k = max(0, min(wanted, n - cursor))
            idx = np.sort(perm[cursor : cursor + k]).astype(np.int64)
            cursor += k
            touched[idx] = True
            return idx

        if self.duplicates:
            idx = take(self.duplicates.planned_for(day))
            table, _ = self.duplicates.apply(table, idx, self._prev_clean, day_rng(seed, day, 2))
        if self.fractioning and (wanted := self.fractioning.planned_for(day)):
            self.fractioning.start_day(day)
            idx = take(wanted)
            table = self.fractioning.apply(table, idx, day_rng(seed, day, 3))
        for stream, sub in enumerate(self.substitutions, start=4):
            if wanted := sub.planned_for(day):
                table = sub.apply(table, take(wanted), day_rng(seed, day, stream))
        late: pa.Table | None = None
        main = table
        if self.late and (wanted := self.late.planned_for(day)):
            idx = take(wanted)
            late = self.late.delay(table.take(pa.array(idx)))
            keep = np.ones(n, dtype=bool)
            keep[idx] = False
            main = table.filter(pa.array(keep))
        self._prev_clean = table.filter(pa.array(~touched))
        return DayOutput(main=main, late=late)

    def stats(self) -> dict[str, dict[str, int | str]]:
        parts: dict[str, dict[str, int | str]] = {}
        objects: dict[str, HasStats | None] = {
            "regional_drop": self.drop,
            "duplicates": self.duplicates,
            "fractioning": self.fractioning,
            "late_arrival": self.late,
        }
        for sub in self.substitutions:
            objects[sub.id] = sub
        for scenario_id in self.enabled:
            scenario = objects[scenario_id]
            if scenario is not None:
                parts[scenario_id] = scenario.stats()
        return parts
