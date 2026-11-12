"""Orquestra a geração e a escrita das entidades (SPEC-001 §3)."""

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from atlas_cli.entities import generate_distributors, generate_pos, month_window
from atlas_cli.generate_io import OutputFormat, write_table
from atlas_cli.manifest import build_manifest, write_manifest
from atlas_cli.recharges import write_recharges
from atlas_cli.reference import Municipalities, reference_path


@dataclass(frozen=True)
class GenerateResult:
    entity_files: list[Path]
    partitions: int
    rows: int
    manifest: Path


def _copy_reference(out: Path) -> Path:
    """Copia a referência IBGE para `municipalities/` (a SPEC-002 a lê do Volume)."""
    dest = out / "municipalities" / "municipalities.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(reference_path(), dest)
    return dest


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
    scenarios: tuple[str, ...] = (),
) -> GenerateResult:
    window = month_window(end_month, months)
    distributors = generate_distributors(seed, n_distributors, municipalities, window)
    pos = generate_pos(seed, n_pos, municipalities, distributors, window)
    written = [
        write_table(distributors.table, out / "distributors" / "distributors", fmt),
        write_table(pos, out / "pos" / "pos", fmt),
    ]
    written.append(_copy_reference(out))
    result = write_recharges(
        out=out,
        seed=seed,
        rows=rows,
        window=window,
        pos=pos,
        municipalities=municipalities,
        fmt=fmt,
        scenarios=scenarios,
    )
    manifest = build_manifest(
        out=out,
        files=[*written, *result.files],
        seed=seed,
        flags={
            "rows": rows,
            "months": months,
            "end_month": end_month.strftime("%Y-%m"),
            "pos": n_pos,
            "distributors": n_distributors,
            "scenarios": list(scenarios),
            "format": fmt.value,
        },
        counts={
            "distributors": distributors.table.num_rows,
            "municipalities": len(municipalities.code),
            "pos": pos.num_rows,
            "recharges": result.rows,
            "partitions": result.partitions,
        },
        scenarios=result.scenarios,
    )
    return GenerateResult(written, result.partitions, result.rows, write_manifest(out, manifest))
