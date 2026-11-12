"""`_manifest.json` (SPEC-001 §3): seed, flags, contagens e sha256 por arquivo.

Sem timestamps nem caminhos absolutos: a mesma seed e as mesmas flags geram o mesmo manifest.
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from atlas_cli import __version__

MANIFEST_NAME = "_manifest.json"
MANIFEST_VERSION = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    *,
    out: Path,
    files: Iterable[Path],
    seed: int,
    flags: dict[str, Any],
    counts: dict[str, int],
    scenarios: dict[str, dict[str, int | str]],
) -> dict[str, Any]:
    entries = {path.relative_to(out).as_posix(): {"sha256": sha256_file(path)} for path in files}
    return {
        "manifest_version": MANIFEST_VERSION,
        "atlas_cli_version": __version__,
        "seed": seed,
        "flags": flags,
        "counts": counts,
        "scenarios": scenarios,
        "files": dict(sorted(entries.items())),
    }


def write_manifest(out: Path, manifest: dict[str, Any]) -> Path:
    path = out / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
