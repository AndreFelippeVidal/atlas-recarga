"""Geração determinística de `recharges` (SPEC-001 §3 e §4).

Cada partição `dt=` (dia em America/Sao_Paulo) deriva de `[seed, stream, dia]`, então
um dia não depende dos outros nem do total (base do `--incremental-day`).
A curva intradiária é sorteada na hora local do município do PDV e convertida para UTC.
"""

import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from atlas_cli.entities import Window
from atlas_cli.generate_io import OutputFormat, write_table
from atlas_cli.geo import UF_UTC_OFFSET_HOURS
from atlas_cli.reference import Municipalities
from atlas_cli.scenarios.base import Context
from atlas_cli.scenarios.inject import Injector

FACE_VALUES = (10, 15, 20, 25, 30, 40, 50, 100)
FACE_WEIGHTS = (0.22, 0.18, 0.20, 0.10, 0.12, 0.06, 0.09, 0.03)
REVERSED_SHARE = 0.015
SUBSCRIBER_POOL = 400_000
POS_WEIGHT_SIGMA = 0.8  # cauda longa: lognormal por PDV
SP_OFFSET_HOURS = -3
INGESTION_DELAY_HOURS = 9  # 06:00 em São Paulo do dia seguinte = 09:00 UTC

# Peso por hora local (0 a 23): picos entre 11h e 13h e entre 18h e 21h.
_HOUR_WEIGHTS = np.array(
    [
        0.2,
        0.1,
        0.1,
        0.1,
        0.15,
        0.3,
        0.6,
        1.0,
        1.5,
        2.0,
        2.6,
        3.4,
        3.6,
        3.0,
        2.4,
        2.4,
        2.6,
        3.0,
        3.8,
        4.0,
        3.6,
        2.4,
        1.2,
        0.5,
    ]
)
HOUR_CDF = np.cumsum(_HOUR_WEIGHTS / _HOUR_WEIGHTS.sum())
FACE_CDF = np.cumsum(np.array(FACE_WEIGHTS) / np.sum(FACE_WEIGHTS))


class NoActivePosError(ValueError):
    """Nenhum PDV ativo num dia da janela (poucos PDVs ou todos fechados)."""


_STREAM_POS_WEIGHT = 3
_STREAM_RECHARGES = 4
_NAMESPACE = uuid.UUID("6f0c1f7e-3b1d-5c52-9a2e-a71a5a2c0001")
_FAR_FUTURE = np.datetime64("2262-01-01", "D")

RECHARGES_SCHEMA = pa.schema(
    [
        ("recharge_id", pa.string()),
        ("recharge_ts_utc", pa.timestamp("us", tz="UTC")),
        ("pos_id", pa.string()),
        ("subscriber_id", pa.string()),
        ("amount_brl", pa.decimal128(10, 2)),
        ("status", pa.string()),
        ("ingested_at_utc", pa.timestamp("us", tz="UTC")),
    ]
)


def _mix64(x: NDArray[np.uint64]) -> NDArray[np.uint64]:
    """SplitMix64: espalha índices em 64 bits de forma determinística."""
    s30, s27, s31 = np.uint64(30), np.uint64(27), np.uint64(31)
    x = x + np.uint64(0x9E3779B97F4A7C15)
    x = (x ^ (x >> s30)) * np.uint64(0xBF58476D1CE4E5B9)
    x = (x ^ (x >> s27)) * np.uint64(0x94D049BB133111EB)
    return x ^ (x >> s31)


def subscriber_pool(seed: int) -> NDArray[np.object_]:
    """`SUB-` + 10 hex. Nunca um telefone com formato real."""
    base = _mix64(np.array([seed], dtype=np.uint64))  # a seed entra no hash, sem sobreposição
    idx = np.arange(SUBSCRIBER_POOL, dtype=np.uint64) + base
    low40 = np.unique(_mix64(idx) & np.uint64(0xFFFFFFFFFF))  # sem colisões no pool
    return np.array([f"SUB-{int(v):010x}" for v in low40], dtype=object)


SALARY_DAYS = range(5, 11)  # dia 5 a 10 (calendário de São Paulo)
# Fatores em centésimos (inteiros): a divisão dos dias não depende de ponto flutuante.
SALARY_FACTOR_PCT = 118
DECEMBER_FACTOR_PCT = 125
FEBRUARY_FACTOR_PCT = 92
SUNDAY_FACTOR_PCT = 70
_PCT_SCALE = 100**3  # no máximo 3 fatores por dia (salário, mês, domingo)


def _seasonality_int(day: date) -> int:
    """Peso inteiro do dia, na escala `_PCT_SCALE`; os fatores se multiplicam."""
    weight, factors = 1, 0
    for applies, pct in (
        (day.day in SALARY_DAYS, SALARY_FACTOR_PCT),
        (day.month == 12, DECEMBER_FACTOR_PCT),
        (day.month == 2, FEBRUARY_FACTOR_PCT),
        (day.weekday() == 6, SUNDAY_FACTOR_PCT),
    ):
        if applies:
            weight *= pct
            factors += 1
    return weight * int(100 ** (3 - factors))


def seasonality_weight(day: date) -> float:
    """Fator de sazonalidade do dia (SPEC-001 §4), relativo a um dia comum."""
    return _seasonality_int(day) / _PCT_SCALE


def daily_counts(total: int, days: Sequence[date]) -> list[int]:
    """Divide `total` entre os dias, proporcional à sazonalidade; a soma é exata.

    Aritmética inteira (maior resto, desempate pelo dia mais cedo): o resultado é idêntico
    em qualquer plataforma, requisito do invariante 1.
    """
    if not days:
        raise ValueError("a janela precisa ter ao menos um dia")
    weights = [_seasonality_int(d) for d in days]
    whole = sum(weights)
    counts = [total * w // whole for w in weights]
    remainders = [total * w % whole for w in weights]
    missing = total - sum(counts)
    for i in sorted(range(len(days)), key=lambda i: (-remainders[i], i))[:missing]:
        counts[i] += 1
    return counts


def _decimal_cents(cents: NDArray[np.int64]) -> pa.Array:
    """DECIMAL(10,2) a partir de centavos, sem criar objetos Decimal."""
    words = np.empty((len(cents), 2), dtype=np.int64)
    words[:, 0] = cents
    words[:, 1] = cents >> 63  # extensão de sinal para 128 bits
    return pa.Array.from_buffers(
        pa.decimal128(10, 2), len(cents), [None, pa.py_buffer(words.tobytes())]
    )


@dataclass(frozen=True)
class PosBook:
    """PDVs em arrays para amostragem vetorizada."""

    pos_id: NDArray[np.object_]
    weight: NDArray[np.float64]
    opened: NDArray[np.datetime64]
    closed: NDArray[np.datetime64]  # NaT virou "muito no futuro"
    offset_hours: NDArray[np.int64]


def build_pos_book(seed: int, pos: pa.Table, municipalities: Municipalities) -> PosBook:
    """Peso do PDV = lognormal seedado x sqrt(população do município) (cauda longa)."""
    count = pos.num_rows
    index_by_code = {code: i for i, code in enumerate(municipalities.code)}
    muni = np.array([index_by_code[c] for c in pos["municipality_ibge_code"].to_pylist()])
    rng = np.random.default_rng([seed, _STREAM_POS_WEIGHT])
    weight = rng.lognormal(0.0, POS_WEIGHT_SIGMA, size=count) * np.sqrt(
        municipalities.population[muni].astype(np.float64)
    )
    closed = np.array(pos["closed_date"].to_pylist(), dtype="datetime64[D]")
    return PosBook(
        pos_id=np.array(pos["pos_id"].to_pylist(), dtype=object),
        weight=weight,
        opened=np.array(pos["opened_date"].to_pylist(), dtype="datetime64[D]"),
        closed=np.where(np.isnat(closed), _FAR_FUTURE, closed),
        offset_hours=np.array(
            [UF_UTC_OFFSET_HOURS[municipalities.uf[int(i)]] for i in muni], dtype=np.int64
        ),
    )


def generate_recharge_day(
    seed: int, day: date, count: int, book: PosBook, subscribers: NDArray[np.object_]
) -> pa.Table:
    """Recargas da partição `dt=day` (dia em America/Sao_Paulo)."""
    rng = np.random.default_rng([seed, _STREAM_RECHARGES, day.toordinal()])
    day64 = np.datetime64(day, "D")
    active = (book.opened <= day64) & (book.closed >= day64)
    cdf = np.cumsum(np.where(active, book.weight, 0.0))
    if cdf[-1] <= 0:
        raise NoActivePosError(f"nenhum PDV ativo em {day}; aumente --pos")
    pos_idx = np.minimum(
        np.searchsorted(cdf, rng.random(count) * cdf[-1], side="right"), len(cdf) - 1
    )

    hour = np.minimum(np.searchsorted(HOUR_CDF, rng.random(count), side="right"), 23)
    second = rng.integers(0, 3600, size=count)
    offset = book.offset_hours[pos_idx]
    # Hora local + deslocamento até São Paulo; passou de 24h => o dia local é o anterior.
    spills = hour + (SP_OFFSET_HOURS - offset) >= 24
    local_day = day.toordinal() - date(1970, 1, 1).toordinal() - spills.astype(np.int64)
    utc_seconds = local_day * 86_400 + hour * 3_600 + second - offset * 3_600
    order = np.argsort(utc_seconds, kind="stable")
    utc_seconds, pos_idx = utc_seconds[order], pos_idx[order]

    cents = (
        np.array(FACE_VALUES, dtype=np.int64)[
            np.minimum(
                np.searchsorted(FACE_CDF, rng.random(count), side="right"), len(FACE_VALUES) - 1
            )
        ]
        * 100
    )
    status = np.where(rng.random(count) < REVERSED_SHARE, "reversed", "approved")
    subscriber = subscribers[rng.integers(0, len(subscribers), size=count)]

    ingested_s = (day + timedelta(days=1) - date(1970, 1, 1)).days * 86_400 + (
        INGESTION_DELAY_HOURS * 3_600
    )
    iso = day.isoformat()
    return pa.table(
        {
            "recharge_id": [str(uuid.uuid5(_NAMESPACE, f"{seed}:{iso}:{i}")) for i in range(count)],
            "recharge_ts_utc": pa.array(utc_seconds * 1_000_000, pa.int64()).cast(
                pa.timestamp("us", tz="UTC")
            ),
            "pos_id": pa.array(book.pos_id[pos_idx], pa.string()),
            "subscriber_id": pa.array(subscriber, pa.string()),
            "amount_brl": _decimal_cents(cents),
            "status": pa.array(status, pa.string()),
            "ingested_at_utc": pa.array(
                np.full(count, ingested_s * 1_000_000, dtype=np.int64), pa.int64()
            ).cast(pa.timestamp("us", tz="UTC")),
        },
        schema=RECHARGES_SCHEMA,
    )


def iter_days(window: Window) -> Iterator[date]:
    day = window.start
    while day <= window.end:
        yield day
        day += timedelta(days=1)


@dataclass(frozen=True)
class RechargesResult:
    partitions: int
    rows: int
    files: list[Path]
    scenarios: dict[str, dict[str, int | str]]


def write_recharges(
    *,
    out: Path,
    seed: int,
    rows: int,
    window: Window,
    pos: pa.Table,
    municipalities: Municipalities,
    fmt: OutputFormat,
    scenarios: tuple[str, ...] = (),
) -> RechargesResult:
    """Escreve `recharges/dt=YYYY-MM-DD/part-0000.<fmt>` (e `part-0001` com `late_arrival`)."""
    days = list(iter_days(window))
    counts = daily_counts(rows, days)
    book = build_pos_book(seed, pos, municipalities)
    subscribers = subscriber_pool(seed)
    injector = Injector(
        Context(
            seed=seed,
            rows=rows,
            days=tuple(days),
            day_counts=tuple(counts),
            pos_ids=book.pos_id,
            pos_municipality=np.array(pos["municipality_ibge_code"].to_pylist(), dtype=object),
            pos_opened=book.opened,
            pos_closed=book.closed,
        ),
        scenarios,
    )
    files: list[Path] = []
    total = 0
    carry: pa.Table | None = None  # `late_arrival` do dia anterior
    for day, count in zip(days, counts, strict=True):
        base = generate_recharge_day(seed, day, count, book, subscribers)
        result = injector.process(day, base)
        folder = out / "recharges" / f"dt={day.isoformat()}"
        files.append(write_table(result.main, folder / "part-0000", fmt))
        total += result.main.num_rows
        if carry is not None:
            files.append(write_table(carry, folder / "part-0001", fmt))
            total += carry.num_rows
        carry = result.late
    return RechargesResult(len(days), total, files, injector.stats())
