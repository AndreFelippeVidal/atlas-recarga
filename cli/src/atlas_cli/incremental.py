"""`generate --incremental-day` (SPEC-001 §2 e §7): só a partição `recharges/dt=<dia>/`.

Os PDVs vêm do `pos/pos` já gerado em `--out` (as FKs são reais) e o dia usa os mesmos
streams de `generate_recharge_day`. O `_manifest.json` existente é atualizado, não recriado.
Só os cenários proporcionais ao volume (`null_pos`, `unknown_pos`) se aplicam ao dia; os que
dependem de vários dias (`regional_drop`, `duplicates`, `late_arrival`) ou sorteiam um dia da
janela (`fractioning`, `negative_amount`) ficam de fora, então só há `part-0000`.
"""

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq

from atlas_cli.entities import POS_SCHEMA, month_window
from atlas_cli.generate_io import OutputFormat, write_table
from atlas_cli.manifest import sha256_file, write_manifest
from atlas_cli.recharges import (
    build_pos_book,
    generate_recharge_day,
    iter_days,
    seasonality_int,
    subscriber_pool,
)
from atlas_cli.reference import Municipalities
from atlas_cli.scenarios.base import Context
from atlas_cli.scenarios.inject import Injector
from atlas_cli.validate import ValidateError, load_manifest

INCREMENTAL_SCENARIOS = ("null_pos", "unknown_pos")


class IncrementalError(ValueError):
    """Pré-condição do incremental violada (exit code 2)."""


@dataclass(frozen=True)
class IncrementalResult:
    day: date
    rows: int
    files: list[Path]
    manifest: Path
    replaced: bool


def day_volume(rows: int, day: date, window_days: list[date]) -> int:
    """Volume esperado de `day`: `rows` repartido pela sazonalidade da janela histórica."""
    whole = sum(seasonality_int(d) for d in window_days)
    return max(1, rows * seasonality_int(day) // whole)


def _count_rows(path: Path) -> int:
    if path.suffix == ".csv":
        return int(pa_csv.read_csv(path).num_rows)
    rows: int = pq.read_metadata(path).num_rows
    return rows


def _read_pos(path: Path) -> pa.Table:
    if path.suffix == ".csv":
        options = pa_csv.ConvertOptions(column_types=POS_SCHEMA)
        return pa_csv.read_csv(path, convert_options=options).cast(POS_SCHEMA)
    return pq.read_table(path)


def generate_incremental_day(
    *,
    out: Path,
    day: date,
    seed: int,
    rows: int,
    fmt: OutputFormat,
    municipalities: Municipalities,
    scenarios: tuple[str, ...],
) -> IncrementalResult:
    try:
        manifest: dict[str, Any] = load_manifest(out)
    except ValidateError as exc:
        raise IncrementalError(f"{exc} O incremental precisa do lote histórico em {out}.") from exc
    flags: dict[str, Any] = manifest["flags"]
    if manifest["seed"] != seed:
        raise IncrementalError(
            f"--seed {seed} difere do lote em {out} (seed {manifest['seed']}): "
            "os PDVs não seriam coerentes."
        )
    if flags.get("format") != fmt.value:
        raise IncrementalError(
            f"--format {fmt.value} difere do lote em {out} (format {flags.get('format')})."
        )
    pos_path = out / "pos" / f"pos.{fmt.value}"
    if not pos_path.is_file():
        raise IncrementalError(f"{pos_path} não existe: rode `generate` completo antes.")

    scenarios = tuple(s for s in scenarios if s in INCREMENTAL_SCENARIOS)
    pos = _read_pos(pos_path)
    window_days = list(iter_days(month_window(_end_month(flags), int(flags["months"]))))
    count = day_volume(rows, day, window_days)
    book = build_pos_book(seed, pos, municipalities)
    injector = Injector(
        Context(
            seed=seed,
            rows=count,
            days=(day,),
            day_counts=(count,),
            pos_ids=book.pos_id,
            pos_municipality=np.array(pos["municipality_ibge_code"].to_pylist(), dtype=object),
            pos_opened=book.opened,
            pos_closed=book.closed,
        ),
        scenarios,
    )
    base = generate_recharge_day(seed, day, count, book, subscriber_pool(seed))
    result = injector.process(day, base)

    folder = out / "recharges" / f"dt={day.isoformat()}"
    prefix = folder.relative_to(out).as_posix() + "/"
    old_files = [p for p in folder.glob("part-*") if p.is_file()] if folder.is_dir() else []
    old_rows = sum(_count_rows(p) for p in old_files)
    if folder.is_dir():
        shutil.rmtree(folder)  # a partição do dia é substituída inteira
    written = write_table(result.main, folder / "part-0000", fmt)

    files: dict[str, Any] = {k: v for k, v in manifest["files"].items() if not k.startswith(prefix)}
    files[written.relative_to(out).as_posix()] = {"sha256": sha256_file(written)}
    manifest["files"] = dict(sorted(files.items()))
    counts: dict[str, int] = manifest["counts"]
    counts["recharges"] = counts["recharges"] - old_rows + result.main.num_rows
    counts["partitions"] = counts["partitions"] + (0 if old_files else 1)
    incremental: dict[str, Any] = manifest.setdefault("incremental", {})
    incremental[day.isoformat()] = {
        "rows": result.main.num_rows,
        "scenarios": injector.stats(),
        "scenarios_enabled": list(scenarios),
    }
    manifest["incremental"] = dict(sorted(incremental.items()))
    return IncrementalResult(
        day, result.main.num_rows, [written], write_manifest(out, manifest), bool(old_files)
    )


def _end_month(flags: dict[str, Any]) -> date:
    year, month = str(flags["end_month"]).split("-")
    return date(int(year), int(month), 1)
