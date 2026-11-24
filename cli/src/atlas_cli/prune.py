"""Poda das partições de recargas fora de um intervalo de dias (SPEC-001 §2, SPEC-012).

Não é um comando: o `scripts/load_data.py` a chama depois de gerar os meses que cobrem o intervalo.
Só `recharges/dt=<dia>/` sai; `pos`, `distributors` e `municipalities` ficam como estão. O
`_manifest.json` é atualizado (arquivos, contagens, `incremental` e a chave `pruned`), então
`validate` e `upload` continuam valendo. Os números de `scenarios` descrevem a geração original.
"""

import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.csv as pa_csv
import pyarrow.parquet as pq

from atlas_cli.manifest import write_manifest
from atlas_cli.validate import ValidateError, load_manifest

_PARTITION = re.compile(r"dt=(\d{4}-\d{2}-\d{2})")


class PruneError(ValueError):
    """Pré-condição da poda violada (exit code 2)."""


@dataclass(frozen=True)
class PruneResult:
    removed_partitions: int
    removed_rows: int
    kept_partitions: int
    kept_rows: int
    manifest: Path


def _count_rows(path: Path) -> int:
    if path.suffix == ".csv":
        return int(pa_csv.read_csv(path).num_rows)
    rows: int = pq.read_metadata(path).num_rows
    return rows


def prune_recharges(out: Path, first: date, last: date) -> PruneResult:
    """Remove as partições de `recharges/` fora de `[first, last]` (inclusivo)."""
    if first > last:
        raise PruneError(f"--from {first} é depois de --to {last}")
    try:
        manifest: dict[str, Any] = load_manifest(out)
    except ValidateError as exc:
        raise PruneError(str(exc)) from exc

    removed_rows = 0
    removed: list[date] = []
    for folder in sorted((out / "recharges").glob("dt=*")):
        match = _PARTITION.fullmatch(folder.name)
        if not folder.is_dir() or match is None:
            continue
        day = date.fromisoformat(match.group(1))
        if first <= day <= last:
            continue
        removed_rows += sum(_count_rows(p) for p in folder.glob("part-*") if p.is_file())
        shutil.rmtree(folder)
        removed.append(day)

    prefixes = tuple(f"recharges/dt={day.isoformat()}/" for day in removed)
    files = {k: v for k, v in manifest["files"].items() if not k.startswith(prefixes)}
    manifest["files"] = dict(sorted(files.items()))
    counts: dict[str, int] = manifest["counts"]
    counts["recharges"] -= removed_rows
    counts["partitions"] -= len(removed)
    if "incremental" in manifest:
        gone = {day.isoformat() for day in removed}
        kept = {k: v for k, v in manifest["incremental"].items() if k not in gone}
        if kept:
            manifest["incremental"] = kept
        else:
            del manifest["incremental"]
    manifest["pruned"] = {"from": first.isoformat(), "to": last.isoformat()}
    path = write_manifest(out, manifest)
    return PruneResult(len(removed), removed_rows, counts["partitions"], counts["recharges"], path)
