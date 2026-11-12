"""`regional_drop`: -14% de volume no Baixo Amazonas (oeste do PA) no penúltimo mês."""

from datetime import date

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from atlas_cli.scenarios.base import Context

ID = "regional_drop"
DESCRIPTION = "-14% de volume nos municipios do Baixo Amazonas (oeste do PA) no penultimo mes"
PARAMETERS = {"drop": "14%", "municipalities": "13 (Baixo Amazonas)", "month": "penultimo"}

DROP_SHARE = 0.14
# Mesorregião do Baixo Amazonas (IBGE). A referência não tem mesorregião, então a lista é fixa.
BAIXO_AMAZONAS = frozenset(
    {
        "1500404",  # Alenquer
        "1500503",  # Almeirim
        "1501451",  # Belterra
        "1502855",  # Curuá
        "1503002",  # Faro
        "1503903",  # Juruti
        "1504752",  # Mojuí dos Campos
        "1504802",  # Monte Alegre
        "1505106",  # Óbidos
        "1505304",  # Oriximiná
        "1506005",  # Prainha
        "1506807",  # Santarém
        "1507979",  # Terra Santa
    }
)


def target_month(days: tuple[date, ...]) -> tuple[int, int] | None:
    """(ano, mês) do penúltimo mês da janela; None se a janela tem menos de 2 meses."""
    last = days[-1]
    index = last.year * 12 + last.month - 2
    year, month = index // 12, index % 12 + 1
    return (year, month) if days[0] <= date(year, month, 1) else None


class RegionalDrop:
    def __init__(self, ctx: Context) -> None:
        self.month = target_month(ctx.days)
        in_region = np.isin(ctx.pos_municipality, list(BAIXO_AMAZONAS))
        self._affected = pa.array(ctx.pos_ids[in_region].tolist(), pa.string())
        self.candidate_rows = 0
        self.removed_rows = 0

    def applies(self, day: date) -> bool:
        return self.month == (day.year, day.month)

    def apply(self, table: pa.Table, day: date, rng: np.random.Generator) -> pa.Table:
        if not self.applies(day):
            return table
        in_region = pc.is_in(table["pos_id"], value_set=self._affected).to_numpy(
            zero_copy_only=False
        )
        drop = in_region & (rng.random(table.num_rows) < DROP_SHARE)
        self.candidate_rows += int(in_region.sum())
        self.removed_rows += int(drop.sum())
        return table.filter(pa.array(~drop))

    def stats(self) -> dict[str, int | str]:
        month = f"{self.month[0]}-{self.month[1]:02d}" if self.month else ""
        return {
            "rows": self.removed_rows,
            "candidate_rows": self.candidate_rows,
            "municipalities": len(BAIXO_AMAZONAS),
            "month": month,
        }
