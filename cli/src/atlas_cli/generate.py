"""Orquestra a geração e a escrita das entidades (SPEC-001 §3)."""

from datetime import date
from pathlib import Path

from atlas_cli.entities import generate_distributors, generate_pos, month_window
from atlas_cli.generate_io import OutputFormat, write_table
from atlas_cli.recharges import write_recharges
from atlas_cli.reference import Municipalities


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
    rows: int,
) -> tuple[list[Path], tuple[int, int]]:
    window = month_window(end_month, months)
    distributors = generate_distributors(seed, n_distributors, municipalities, window)
    pos = generate_pos(seed, n_pos, municipalities, distributors, window)
    written = [
        write_table(distributors.table, out / "distributors" / "distributors", fmt),
        write_table(pos, out / "pos" / "pos", fmt),
    ]
    recharges = write_recharges(
        out=out,
        seed=seed,
        rows=rows,
        window=window,
        pos=pos,
        municipalities=municipalities,
        fmt=fmt,
    )
    return written, recharges
