"""Formato de saída e escrita de tabelas (SPEC-001 §2 e §3)."""

from enum import StrEnum
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq


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
