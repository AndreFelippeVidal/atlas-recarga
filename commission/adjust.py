"""Lote de ajuste `COM-YYYY-MM-ADJ-n` depois do lock (SPEC-003 §7, task P8.10).

Chamado por `draft.py` quando o job `atlas_commission_draft` recebe `adjust_batch_id`. Recalcula
o mês com `rules.py` sobre o gold atual e grava **só a diferença** contra a soma das
`locked_lines` de todos os lotes `locked` do mês (original e ajustes anteriores). As linhas
podem ser negativas. Nenhum valor é informado à mão e nada em `locked_lines` é tocado.

A parte de regra (`net_locked`, `recompute`, `diff_lines`) é pura e testada sem Spark; a parte
Spark só lê o gold e as tabelas de `commission.*` e escreve `batch_lines`, `batches` (`draft`) e
o primeiro evento, como o rascunho. O ajuste segue o fluxo de `review.py` sem mudança.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

ZERO = Decimal("0.00")
_ADJ_ID = re.compile(r"^COM-(\d{4})-(0[1-9]|1[0-2])-ADJ-(\d+)$")
_REGULAR_ID = re.compile(r"^COM-(\d{4})-(0[1-9]|1[0-2])-v\d+$")
FINISHED = ("locked", "rejected")

Key = tuple[str, str]  # (beneficiary_type, beneficiary_id)


@dataclass(frozen=True)
class Line:
    beneficiary_type: str
    beneficiary_id: str
    base_amount_brl: Decimal
    tier: str | None
    rate: Decimal
    commission_brl: Decimal


def _rules() -> Any:
    return importlib.import_module("commission.rules")


def adjustment_id(month: date, n: int) -> str:
    return f"COM-{month:%Y-%m}-ADJ-{n}"


def is_adjustment(batch_id: str) -> bool:
    return _ADJ_ID.fullmatch(batch_id) is not None


def month_of(batch_id: str) -> date:
    """Mês de referência embutido no `batch_id` (regular ou ajuste)."""
    match = _ADJ_ID.fullmatch(batch_id) or _REGULAR_ID.fullmatch(batch_id)
    if match is None:
        raise ValueError(f"batch_id inválido: {batch_id!r}")
    return date(int(match.group(1)), int(match.group(2)), 1)


def next_adjustment_number(existing_ids: Iterable[str]) -> int:
    """Maior `n` já usado no mês mais 1 (rejeitado conta: o `batch_id` nunca se repete)."""
    used = [int(m.group(3)) for i in existing_ids if (m := _ADJ_ID.fullmatch(i))]
    return max(used, default=0) + 1


def net_locked(lines: Iterable[Line]) -> dict[Key, Line]:
    """Soma, por beneficiário, as linhas travadas do mês. `tier` e `rate` vêm da última vista."""
    net: dict[Key, Line] = {}
    for line in lines:
        key = (line.beneficiary_type, line.beneficiary_id)
        prev = net.get(key)
        if prev is None:
            net[key] = line
        else:
            net[key] = Line(
                key[0],
                key[1],
                prev.base_amount_brl + line.base_amount_brl,
                line.tier,
                line.rate,
                prev.commission_brl + line.commission_brl,
            )
    return net


def recompute(volumes: dict[str, Decimal], distributor_of: dict[str, str]) -> dict[Key, Line]:
    """Linhas do mês pelas regras de §2: uma por PDV com volume > 0 e uma por distribuidor."""
    rules = _rules()
    out: dict[Key, Line] = {}
    per_distributor: dict[str, Decimal] = {}
    for pos_id, volume in volumes.items():
        if not rules.has_line(volume):
            continue
        distributor = distributor_of.get(pos_id)
        if distributor is None:
            raise RuntimeError(f"PDV {pos_id} com volume sem distribuidor em dim_pos")
        tier, commission = rules.pos_commission(volume)
        out[("pos", pos_id)] = Line("pos", pos_id, volume, tier.name, tier.rate, commission)
        per_distributor[distributor] = per_distributor.get(distributor, ZERO) + volume
    for distributor, total in per_distributor.items():
        out[("distributor", distributor)] = Line(
            "distributor",
            distributor,
            total,
            None,
            rules.DISTRIBUTOR_RATE,
            rules.distributor_commission(total),
        )
    return out


def diff_lines(locked: dict[Key, Line], fresh: dict[Key, Line]) -> list[Line]:
    """Linhas de diferença (`fresh` menos `locked`), só onde base ou comissão mudou."""
    out: list[Line] = []
    for key in sorted(locked.keys() | fresh.keys()):
        old, new = locked.get(key), fresh.get(key)
        base = (new.base_amount_brl if new else ZERO) - (old.base_amount_brl if old else ZERO)
        commission = (new.commission_brl if new else ZERO) - (old.commission_brl if old else ZERO)
        if base == ZERO and commission == ZERO:
            continue
        source = new if new is not None else old
        if source is None:  # a chave vem de um dos dois; defensivo
            continue
        out.append(Line(key[0], key[1], base, source.tier, source.rate, commission))
    return out


def totals(lines: Iterable[Line]) -> tuple[Decimal, Decimal]:
    """(total PDV, total distribuidor) das linhas de diferença, já em centavos."""
    pos = ZERO
    dist = ZERO
    for line in lines:
        if line.beneficiary_type == "pos":
            pos += line.commission_brl
        else:
            dist += line.commission_brl
    return pos, dist


def _draft() -> Any:
    return importlib.import_module("commission.draft")


def latest_adjustment_id(spark: Any, catalog: str, month: date) -> str:
    """O ajuste mais novo do mês (para as tasks de reconciliação e de flags)."""
    rows = spark.sql(
        f"SELECT batch_id FROM {catalog}.commission.batches WHERE reference_month = :m",  # noqa: S608
        args={"m": month},
    ).collect()
    ids = [r["batch_id"] for r in rows if is_adjustment(r["batch_id"])]
    if not ids:
        raise RuntimeError(f"não há lote de ajuste em {month:%Y-%m}")
    return adjustment_id(month, next_adjustment_number(ids) - 1)


def create_adjustment(spark: Any, catalog: str, adjust_batch_id: str) -> str:
    """Cria o `COM-YYYY-MM-ADJ-n` em `draft` e devolve o `batch_id`."""
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        ArrayType,
        BooleanType,
        DateType,
        DecimalType,
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )

    draft = _draft()
    draft.check_identifier(catalog, "catalog name")
    month = month_of(adjust_batch_id)
    c = f"{catalog}.commission"

    header = spark.sql(
        f"SELECT status, reference_month FROM {c}.batches WHERE batch_id = :b",  # noqa: S608
        args={"b": adjust_batch_id},
    ).first()
    if header is None:
        raise RuntimeError(f"{adjust_batch_id} não existe")
    if header["status"] != "locked":
        raise RuntimeError(f"{adjust_batch_id} está em {header['status']}; só se ajusta um locked")

    if header["reference_month"] != month:
        raise RuntimeError(f"{adjust_batch_id}: o mês do cabeçalho não bate com o do batch_id")

    month_batches = spark.sql(
        f"SELECT batch_id, status FROM {c}.batches WHERE reference_month = :m",  # noqa: S608
        args={"m": month},
    ).collect()
    pending = [
        r["batch_id"]
        for r in month_batches
        if is_adjustment(r["batch_id"]) and r["status"] not in FINISHED
    ]
    if pending:
        raise RuntimeError(f"já há ajuste em andamento em {month:%Y-%m}: {', '.join(pending)}")
    number = next_adjustment_number(r["batch_id"] for r in month_batches)
    batch_id = adjustment_id(month, number)

    locked_rows = spark.sql(
        "SELECT l.beneficiary_type, l.beneficiary_id, l.base_amount_brl, l.tier, l.rate, "  # noqa: S608
        f"l.commission_brl FROM {c}.locked_lines l JOIN {c}.batches b USING (batch_id) "
        "WHERE b.reference_month = :m AND b.status = 'locked' "
        "ORDER BY b.created_at_utc, b.batch_id",
        args={"m": month},
    ).collect()
    locked = net_locked(
        Line(
            r["beneficiary_type"],
            r["beneficiary_id"],
            Decimal(r["base_amount_brl"]),
            r["tier"],
            Decimal(r["rate"]),
            Decimal(r["commission_brl"]),
        )
        for r in locked_rows
    )

    volume_rows = (
        spark.table(f"{catalog}.gold.agg_pos_month")
        .where(F.col("recharge_month") == F.lit(month))
        .select("pos_id", "approved_amount_brl")
        .collect()
    )
    volumes = {r["pos_id"]: Decimal(r["approved_amount_brl"]) for r in volume_rows}
    distributor_of = {
        r["pos_id"]: r["distributor_id"]
        for r in spark.table(f"{catalog}.gold.dim_pos").select("pos_id", "distributor_id").collect()
    }
    lines = diff_lines(locked, recompute(volumes, distributor_of))
    if not lines:
        raise RuntimeError(f"nada a ajustar em {month:%Y-%m}: o gold bate com as linhas travadas")
    total_pos, total_distributor = totals(lines)

    money = DecimalType(14, 2)
    line_schema = StructType(
        [
            StructField("batch_id", StringType(), False),
            StructField("beneficiary_type", StringType(), False),
            StructField("beneficiary_id", StringType(), False),
            StructField("base_amount_brl", money, False),
            StructField("tier", StringType(), True),
            StructField("rate", DecimalType(5, 4), False),
            StructField("commission_brl", money, False),
            StructField("flags", ArrayType(StringType()), True),
        ]
    )
    data: list[tuple[Any, ...]] = [
        (
            batch_id,
            x.beneficiary_type,
            x.beneficiary_id,
            x.base_amount_brl,
            x.tier,
            x.rate,
            x.commission_brl,
            [],
        )
        for x in lines
    ]
    lines_t = f"{c}.batch_lines"
    spark.sql(f"DELETE FROM {lines_t} WHERE batch_id = :b", args={"b": batch_id})  # noqa: S608
    spark.createDataFrame(data, line_schema).writeTo(lines_t).append()

    header_schema = StructType(
        [
            StructField("batch_id", StringType(), False),
            StructField("reference_month", DateType(), False),
            StructField("version", IntegerType(), False),
            StructField("status", StringType(), False),
            StructField("total_pos_brl", money, True),
            StructField("total_distributor_brl", money, True),
            StructField("source_snapshot_version", LongType(), True),
            StructField("remittance_sha256", StringType(), True),
            StructField("demo_mode", BooleanType(), False),
            StructField("created_at_utc", TimestampType(), False),
        ]
    )
    spark.createDataFrame(
        [
            (
                batch_id,
                month,
                number,
                "draft",
                total_pos,
                total_distributor,
                None,
                None,
                False,
                datetime.now(ZoneInfo("UTC")),
            )
        ],
        header_schema,
    ).writeTo(f"{c}.batches").append()
    spark.sql(
        f"INSERT INTO {c}.batch_events "
        "(event_id, batch_id, from_status, to_status, actor, role, justification, event_ts_utc) "
        "SELECT uuid(), :b, CAST(NULL AS STRING), 'draft', current_user(), 'system', "
        "CAST(NULL AS STRING), current_timestamp()",
        args={"b": batch_id},
    )
    return batch_id
