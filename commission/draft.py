"""Cálculo do rascunho (`draft`) do lote de comissão (SPEC-003 §2 a §4, task P8.3).

Roda como `spark_python_task` serverless no job `atlas_commission_draft`. Lê só
`gold.agg_pos_month` (e `gold.dim_pos` para o distribuidor) e grava `commission.batch_lines`,
`commission.batches` (`status = 'draft'`) e o primeiro evento em `commission.batch_events`.
Determinístico, sem IA (ADR-0010). Não reconcilia (P8.4), não marca flags (P8.5) e não aprova.

* Mês de referência: o mês civil anterior ao de hoje em America/Sao_Paulo, ou o informado
  (`YYYY-MM`, nunca o mês corrente nem um futuro).
* Só nasce a versão `v1`. Se `COM-YYYY-MM-v1` já existe, recusa: nada é sobrescrito.
  Versão `vN+1` nasce de uma rejeição (P8.6).
* PDV fechado no mês: o gold só tem recarga até `closed_date` (SPEC-001: PDV só recebe recarga
  enquanto ativo), então o volume de `agg_pos_month` já está cortado.
* Dinheiro é `DECIMAL`; `bround` do Spark é HALF_EVEN, o mesmo critério de `rules.round_brl`.
  Faixas e taxas vêm de `rules.TIERS`; não há segunda tabela de faixas.
* As três escritas não são uma transação. Ordem: linhas, cabeçalho, evento. Uma falha antes do
  cabeçalho deixa linhas órfãs, que a próxima execução apaga (o lote ainda não existe).
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# No workspace o script roda de dentro de `commission/`; o pacote precisa do diretório raiz.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from commission import rules  # noqa: E402

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
FIRST_VERSION = 1
MONEY = "decimal(14,2)"


def check_identifier(value: str, what: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


def first_of_month(day: date) -> date:
    return day.replace(day=1)


def default_reference_month(now: datetime) -> date:
    """Primeiro dia do mês civil anterior a `now`, em America/Sao_Paulo."""
    local = now.astimezone(SAO_PAULO) if now.tzinfo else now.replace(tzinfo=SAO_PAULO)
    current = first_of_month(local.date())
    if current.month == 1:
        return date(current.year - 1, 12, 1)
    return current.replace(month=current.month - 1)


def resolve_reference_month(text: str, now: datetime) -> date:
    """Vazio = mês anterior; `YYYY-MM` = esse mês, desde que já esteja fechado."""
    text = text.strip()
    if not text:
        return default_reference_month(now)
    if not _MONTH.fullmatch(text):
        raise ValueError(f"reference_month deve ser YYYY-MM, recebi {text!r}")
    year, month = (int(part) for part in text.split("-"))
    month_start = date(year, month, 1)
    local = now.astimezone(SAO_PAULO) if now.tzinfo else now.replace(tzinfo=SAO_PAULO)
    if month_start >= first_of_month(local.date()):
        raise ValueError(f"o mês {text} ainda não fechou; use um mês anterior ao corrente")
    return month_start


def batch_id_for(month: date, version: int = FIRST_VERSION) -> str:
    return f"COM-{month:%Y-%m}-v{version}"


def tier_case(column: Any, field: str) -> Any:
    """`CASE` Spark que escolhe `name` ou `rate` da faixa a partir de `rules.TIERS`."""
    from pyspark.sql import functions as F

    ordered = sorted(rules.TIERS, key=lambda t: t.floor, reverse=True)

    def value(tier: rules.Tier) -> Any:
        return F.lit(tier.name if field == "name" else tier.rate)

    expr = None
    for tier in ordered[:-1]:
        cond = column >= F.lit(tier.floor)
        expr = F.when(cond, value(tier)) if expr is None else expr.when(cond, value(tier))
    if expr is None:
        raise RuntimeError("rules.TIERS precisa ter mais de uma faixa")
    return expr.otherwise(value(ordered[-1]))


def build_lines(volumes: Any, pos: Any, batch_id: str) -> Any:
    """Linhas do rascunho: uma por PDV com volume > 0 e uma por distribuidor.

    `volumes`: `pos_id`, `approved_amount_brl` do mês. `pos`: `pos_id`, `distributor_id`.
    """
    from pyspark.sql import functions as F

    base = F.col("approved_amount_brl").cast(MONEY)
    pos_lines = (
        volumes.where(F.col("approved_amount_brl") > 0)
        .select(F.col("pos_id").alias("beneficiary_id"), base.alias("base_amount_brl"))
        .withColumn("beneficiary_type", F.lit("pos"))
        .withColumn("tier", tier_case(F.col("base_amount_brl"), "name"))
        .withColumn("rate", tier_case(F.col("base_amount_brl"), "rate").cast("decimal(5,4)"))
    )
    distributor_lines = (
        pos_lines.join(
            pos.select(F.col("pos_id").alias("beneficiary_id"), "distributor_id"),
            "beneficiary_id",
            "left",
        )
        .groupBy("distributor_id")
        .agg(F.sum("base_amount_brl").cast(MONEY).alias("base_amount_brl"))
        .select(
            F.col("distributor_id").alias("beneficiary_id"),
            "base_amount_brl",
            F.lit("distributor").alias("beneficiary_type"),
            F.lit(None).cast("string").alias("tier"),
            F.lit(rules.DISTRIBUTOR_RATE).cast("decimal(5,4)").alias("rate"),
        )
    )
    both = pos_lines.select(*distributor_lines.columns).unionByName(distributor_lines)
    return both.select(
        F.lit(batch_id).alias("batch_id"),
        "beneficiary_type",
        "beneficiary_id",
        "base_amount_brl",
        "tier",
        "rate",
        F.bround(F.col("base_amount_brl") * F.col("rate"), 2).cast(MONEY).alias("commission_brl"),
        F.array().cast("array<string>").alias("flags"),
    )


def sum_commission(lines: Any, beneficiary_type: str) -> Decimal:
    """Soma das linhas já gravadas e arredondadas (nunca o total recalculado)."""
    from pyspark.sql import functions as F

    row = (
        lines.where(F.col("beneficiary_type") == beneficiary_type)
        .agg(F.sum("commission_brl").alias("total"))
        .first()
    )
    total = row["total"] if row is not None else None
    return Decimal("0.00") if total is None else Decimal(total)


def create_draft(spark: Any, catalog: str, reference_month: str = "") -> str:
    """Cria o lote `COM-YYYY-MM-v1` em `draft` e devolve o `batch_id`."""
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
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

    check_identifier(catalog, "catalog name")
    month = resolve_reference_month(reference_month, datetime.now(SAO_PAULO))
    batch_id = batch_id_for(month)
    batches_t = f"{catalog}.commission.batches"
    lines_t = f"{catalog}.commission.batch_lines"
    events_t = f"{catalog}.commission.batch_events"

    if spark.table(batches_t).where(F.col("batch_id") == batch_id).limit(1).count() > 0:
        raise RuntimeError(
            f"{batch_id} já existe; nada foi alterado (nova versão só após rejeição)"
        )

    agg_t = f"{catalog}.gold.agg_pos_month"
    snapshot_version = int(spark.sql(f"DESCRIBE HISTORY {agg_t} LIMIT 1").first()["version"])
    volumes = spark.table(agg_t).where(F.col("recharge_month") == F.lit(month))
    pos = spark.table(f"{catalog}.gold.dim_pos")

    # Todo PDV com volume precisa de distribuidor: senão a soma do distribuidor perderia base.
    orphans = (
        volumes.where(F.col("approved_amount_brl") > 0)
        .join(pos.select("pos_id", "distributor_id"), "pos_id", "left")
        .where(F.col("distributor_id").isNull())
        .count()
    )
    if orphans:
        raise RuntimeError(f"{orphans} PDV(s) com volume sem distribuidor em dim_pos")

    # Sem cache (não existe em serverless): grava as linhas e soma o que foi gravado, para o
    # total ser a soma exata das linhas persistidas mesmo se o gold mudar no meio.
    lines = build_lines(volumes, pos, batch_id)
    delete_sql = f"DELETE FROM {lines_t} WHERE batch_id = :batch_id"  # noqa: S608
    spark.sql(delete_sql, args={"batch_id": batch_id})  # órfãs de uma execução que caiu antes
    lines.select(*spark.table(lines_t).columns).writeTo(lines_t).append()
    written = spark.table(lines_t).where(F.col("batch_id") == batch_id)
    if written.limit(1).count() == 0:
        raise RuntimeError(f"sem volume aprovado em {month:%Y-%m}; nenhum lote criado")
    total_pos = sum_commission(written, "pos")
    total_distributor = sum_commission(written, "distributor")

    header_schema = StructType(
        [
            StructField("batch_id", StringType(), False),
            StructField("reference_month", DateType(), False),
            StructField("version", IntegerType(), False),
            StructField("status", StringType(), False),
            StructField("total_pos_brl", DecimalType(14, 2), True),
            StructField("total_distributor_brl", DecimalType(14, 2), True),
            StructField("source_snapshot_version", LongType(), True),
            StructField("remittance_sha256", StringType(), True),
            StructField("demo_mode", BooleanType(), False),
            StructField("created_at_utc", TimestampType(), False),
        ]
    )
    header = spark.createDataFrame(
        [
            (
                batch_id,
                month,
                FIRST_VERSION,
                "draft",
                total_pos,
                total_distributor,
                snapshot_version,
                None,
                False,
                datetime.now(ZoneInfo("UTC")),
            )
        ],
        header_schema,
    )
    header.writeTo(batches_t).append()
    spark.sql(
        f"INSERT INTO {events_t} "
        "(event_id, batch_id, from_status, to_status, actor, role, justification, event_ts_utc) "
        "SELECT uuid(), :batch_id, CAST(NULL AS STRING), 'draft', current_user(), 'system', "
        "CAST(NULL AS STRING), current_timestamp()",
        args={"batch_id": batch_id},
    )
    return batch_id


def main(catalog: str, reference_month: str = "") -> None:
    from pyspark.sql import SparkSession  # só existe no workspace

    spark: Any = SparkSession.builder.getOrCreate()
    batch_id = create_draft(spark, catalog, reference_month)
    print(f"rascunho criado: {batch_id}")


if __name__ == "__main__":
    # sem sys.exit: no serverless, `SystemExit` (até com 0) marca a task como falha
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
