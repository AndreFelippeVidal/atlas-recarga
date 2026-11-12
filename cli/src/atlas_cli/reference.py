"""Leitura e validação da referência IBGE (SPEC-001 §4)."""

import csv
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from atlas_cli.geo import REGION_PREPAID_WEIGHT, UF_NEIGHBORS

REFERENCE_ENV = "ATLAS_REFERENCE_PATH"
DEFAULT_REFERENCE = Path("data/reference/municipalities_ibge.csv")
COLUMNS = ("municipality_ibge_code", "municipality_name", "uf", "region", "population", "ddd")


class ReferenceError(Exception):
    """Referência IBGE ausente ou inválida (exit code 3)."""


@dataclass(frozen=True)
class Municipalities:
    code: tuple[str, ...]
    uf: tuple[str, ...]
    population: NDArray[np.int64]
    prepaid_weight: NDArray[np.float64]


def reference_path() -> Path:
    return Path(os.environ.get(REFERENCE_ENV, str(DEFAULT_REFERENCE)))


def load_municipalities(path: Path | None = None) -> Municipalities:
    path = path or reference_path()
    if not path.is_file():
        raise ReferenceError(f"Referência IBGE ausente. Caminho esperado: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ReferenceError(f"Referência IBGE inválida ({path}): colunas esperadas {COLUMNS}")
        rows = list(reader)
    if not rows:
        raise ReferenceError(f"Referência IBGE inválida ({path}): arquivo vazio")
    codes: list[str] = []
    ufs: list[str] = []
    population: list[int] = []
    weight: list[float] = []
    try:
        for row in rows:
            code = row["municipality_ibge_code"]
            if len(code) != 7 or not code.isdigit():
                raise ValueError(f"código IBGE inválido: {code!r}")
            if row["uf"] not in UF_NEIGHBORS:
                raise ValueError(f"UF inválida: {row['uf']!r}")
            codes.append(code)
            ufs.append(row["uf"])
            population.append(int(row["population"]))
            weight.append(REGION_PREPAID_WEIGHT[row["region"]])
    except (ValueError, KeyError) as exc:
        raise ReferenceError(f"Referência IBGE inválida ({path}): {exc}") from exc
    if len(set(codes)) != len(codes):
        raise ReferenceError(f"Referência IBGE inválida ({path}): códigos duplicados")
    return Municipalities(
        code=tuple(codes),
        uf=tuple(ufs),
        population=np.array(population, dtype=np.int64),
        prepaid_weight=np.array(weight, dtype=np.float64),
    )
