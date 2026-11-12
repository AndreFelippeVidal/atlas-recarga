"""Orquestra a geração e a escrita de `distributors` e `pos` (SPEC-001 §3)."""

from datetime import date
from enum import StrEnum
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq

from atlas_cli.entities import generate_distributors, generate_pos, month_window
from atlas_cli.reference import Municipalities


class OutputFormat(StrEnum):
    PARQUET = "parquet"
    CSV = "csv"


def write_table(table: pa.Table, path: Path, fmt: OutputFormat) -> Path:
    path = path.with_suffix(f".{fmt.value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt is OutputFormat.PARQUET:
        pq.write_table(table, path, compression="snappy")
    else:
        pa_csv.write_csv(table, path)
    return path


def generate_reference_entities(
    *,
    out: Path,
    seed: int,
    n_distributors: int,
    n_pos: int,
    months: int,
    end_month: date,
    fmt: OutputFormat,
    municipalities: Municipalities,
) -> list[Path]:
    window = month_window(end_month, months)
    distributors = generate_distributors(seed, n_distributors, municipalities, window)
    pos = generate_pos(seed, n_pos, municipalities, distributors, window)
    return [
        write_table(distributors.table, out / "distributors" / "distributors", fmt),
        write_table(pos, out / "pos" / "pos", fmt),
    ]
