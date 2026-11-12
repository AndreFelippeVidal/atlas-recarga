"""Geração determinística de `distributors` e `pos` (SPEC-001 §4).

Cada stream de aleatoriedade deriva de `[seed, stream_id]`, então mudar uma entidade
não desloca os números sorteados das outras.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pyarrow as pa
from faker import Faker
from numpy.typing import NDArray

from atlas_cli.geo import UF_NEIGHBORS
from atlas_cli.reference import Municipalities

POS_TYPES = ("newsstand", "pharmacy", "grocery", "lottery", "partner_app")
POS_TYPE_WEIGHTS = (0.25, 0.20, 0.30, 0.15, 0.10)
CLOSED_SHARE = 0.03
MAX_SERVED_UFS = 4

_STREAM_DISTRIBUTORS = 1
_STREAM_POS = 2

DISTRIBUTORS_SCHEMA = pa.schema(
    [
        ("distributor_id", pa.string()),
        ("distributor_name", pa.string()),
        ("hq_uf", pa.string()),
        ("created_date", pa.date32()),
    ]
)
POS_SCHEMA = pa.schema(
    [
        ("pos_id", pa.string()),
        ("distributor_id", pa.string()),
        ("pos_name", pa.string()),
        ("pos_type", pa.string()),
        ("municipality_ibge_code", pa.string()),
        ("opened_date", pa.date32()),
        ("closed_date", pa.date32()),
    ]
)


@dataclass(frozen=True)
class Window:
    """Janela de meses gerados: [start, end] inclusive."""

    start: date
    end: date


def month_window(end_month: date, months: int) -> Window:
    """O último mês gerado é `end_month - 1` (mês fechado)."""
    index = end_month.year * 12 + end_month.month - 1
    first = index - months
    last = index - 1
    start = date(first // 12, first % 12 + 1, 1)
    last_year, last_month = last // 12, last % 12 + 1
    end = date(last_year, last_month, calendar.monthrange(last_year, last_month)[1])
    return Window(start=start, end=end)


@dataclass(frozen=True)
class Distributors:
    table: pa.Table
    served_ufs: dict[str, tuple[str, ...]]  # distributor_id -> UFs atendidas


def _faker(seed: int, stream: int) -> Faker:
    fake = Faker("pt_BR")
    fake.seed_instance(seed * 1000 + stream)
    return fake


def _rng(seed: int, stream: int) -> np.random.Generator:
    return np.random.default_rng([seed, stream])


def _days_before(anchor: date, days: int) -> date:
    return anchor - timedelta(days=days)


def _served_ufs(rng: np.random.Generator, hq_uf: str) -> tuple[str, ...]:
    """Cresce a partir da sede por vizinhança até 1 a 4 UFs contíguas."""
    target = int(rng.integers(1, MAX_SERVED_UFS + 1))
    served = [hq_uf]
    while len(served) < target:
        frontier = sorted({n for uf in served for n in UF_NEIGHBORS[uf]} - set(served))
        if not frontier:
            break
        served.append(frontier[int(rng.integers(len(frontier)))])
    return tuple(sorted(served))


def generate_distributors(
    seed: int, count: int, municipalities: Municipalities, window: Window
) -> Distributors:
    rng = _rng(seed, _STREAM_DISTRIBUTORS)
    fake = _faker(seed, _STREAM_DISTRIBUTORS)
    ufs = sorted(set(municipalities.uf))
    # Primeiro uma sede por UF (cobertura), depois o resto ponderado por população.
    shuffled = [ufs[i] for i in rng.permutation(len(ufs))]
    pop_by_uf = np.array(
        [municipalities.population[np.array(municipalities.uf) == uf].sum() for uf in ufs],
        dtype=np.float64,
    )
    hqs = shuffled[:count]
    extra = count - len(hqs)
    if extra > 0:
        hqs += [ufs[i] for i in rng.choice(len(ufs), size=extra, p=pop_by_uf / pop_by_uf.sum())]
    ids = [f"DST-{i:04d}" for i in range(1, count + 1)]
    created = [
        _days_before(window.start, int(d)) for d in rng.integers(3 * 365, 8 * 365 + 1, size=count)
    ]
    served = {dist_id: _served_ufs(rng, hq) for dist_id, hq in zip(ids, hqs, strict=True)}
    table = pa.table(
        {
            "distributor_id": ids,
            "distributor_name": [fake.company() for _ in ids],
            "hq_uf": hqs,
            "created_date": created,
        },
        schema=DISTRIBUTORS_SCHEMA,
    )
    return Distributors(table=table, served_ufs=served)


def _sample_municipalities(
    rng: np.random.Generator, municipalities: Municipalities, count: int, covered: set[str]
) -> NDArray[np.int64]:
    """Índices de municípios: 1 por UF coberta (até `count`), o resto ∝ população x peso."""
    uf = np.array(municipalities.uf)
    weight = municipalities.population * municipalities.prepaid_weight
    weight = np.where(np.isin(uf, sorted(covered)), weight, 0.0)
    chosen: list[int] = []
    for target_uf in [sorted(covered)[i] for i in rng.permutation(len(covered))][:count]:
        mask = uf == target_uf
        w = np.where(mask, weight, 0.0)
        chosen.append(int(rng.choice(len(w), p=w / w.sum())))
    rest = count - len(chosen)
    if rest > 0:
        chosen.extend(int(i) for i in rng.choice(len(weight), size=rest, p=weight / weight.sum()))
    order = rng.permutation(len(chosen))
    return np.array(chosen, dtype=np.int64)[order]


def generate_pos(
    seed: int,
    count: int,
    municipalities: Municipalities,
    distributors: Distributors,
    window: Window,
) -> pa.Table:
    rng = _rng(seed, _STREAM_POS)
    fake = _faker(seed, _STREAM_POS)
    dist_created = dict(
        zip(
            distributors.table["distributor_id"].to_pylist(),
            distributors.table["created_date"].to_pylist(),
            strict=True,
        )
    )
    by_uf: dict[str, list[str]] = {}
    for dist_id, ufs in distributors.served_ufs.items():
        for uf in ufs:
            by_uf.setdefault(uf, []).append(dist_id)

    idx = _sample_municipalities(rng, municipalities, count, set(by_uf))
    pos_dist: list[str] = []
    for i in idx:
        options = by_uf[municipalities.uf[int(i)]]
        pos_dist.append(options[int(rng.integers(len(options)))])

    types = rng.choice(len(POS_TYPES), size=count, p=POS_TYPE_WEIGHTS)
    opened: list[date] = []
    for dist_id in pos_dist:
        earliest = max(dist_created[dist_id], _days_before(window.start, 5 * 365))
        latest = _days_before(window.start, 365)
        opened.append(earliest + timedelta(days=int(rng.integers((latest - earliest).days + 1))))

    closed: list[date | None] = [None] * count
    window_days = (window.end - window.start).days + 1
    for i in rng.choice(count, size=round(CLOSED_SHARE * count), replace=False):
        closed[int(i)] = window.start + timedelta(days=int(rng.integers(window_days)))

    return pa.table(
        {
            "pos_id": [f"POS-{i:06d}" for i in range(1, count + 1)],
            "distributor_id": pos_dist,
            "pos_name": [fake.company() for _ in range(count)],
            "pos_type": [POS_TYPES[int(t)] for t in types],
            "municipality_ibge_code": [municipalities.code[int(i)] for i in idx],
            "opened_date": opened,
            "closed_date": closed,
        },
        schema=POS_SCHEMA,
    )
