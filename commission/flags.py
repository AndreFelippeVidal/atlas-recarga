"""Flags de revisão do rascunho de comissão (SPEC-003 §5, item 3, task P8.5).

Roda como terceira task do job `atlas_commission_draft` (`flag_draft`), depois de
`reconcile_draft`. Calcula em SQL, só leitura em `gold`, os quatro flags e grava em
`commission.batch_lines.flags` (linhas de PDV; a linha do distribuidor fica sem flag):

* `spike_3x`: comissão do PDV > 3 vezes a média da comissão dos até 3 meses anteriores em que o PDV
  teve linha. Sem nenhum mês anterior, não sinaliza.
* `fractioning_suspect`: mais de 20 recargas `approved` de R$ 10 do mesmo `subscriber_id` no
  mesmo PDV em menos de 10 min (janela a partir de cada recarga, em `recharge_ts_utc`).
* `tier_jump`: a faixa subiu 2 ou mais degraus contra o mês anterior. Sem linha no mês
  anterior, não sinaliza.
* `closed_pos`: `closed_date` do PDV cai dentro do mês de referência.

Flags **não bloqueiam**: só destacam linhas para a analista. O histórico vem de
`gold.fct_recharges` com as mesmas faixas de `rules.TIERS` (um mês anterior ainda não tem lote).
Reexecutar substitui os flags do lote (idempotente); só atua em lote `draft`. Sem IA (ADR-0010).
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

SPIKE_FACTOR = 3
SPIKE_HISTORY_MONTHS = 3
TIER_JUMP_STEPS = 2
FRACTION_AMOUNT = 10
FRACTION_MIN_COUNT = 21  # "mais de 20"
FRACTION_WINDOW_MICROS = 10 * 60 * 1_000_000 - 1  # < 10 min a partir de cada recarga

FLAG_ORDER = ("spike_3x", "fractioning_suspect", "tier_jump", "closed_pos")

FLAGS_SQL = """
WITH batch AS (
  SELECT reference_month AS ref FROM {catalog}.commission.batches WHERE batch_id = :batch_id
),
volume AS (
  SELECT f.pos_id, f.recharge_month AS month, SUM(f.amount_brl) AS base
  FROM {catalog}.gold.fct_recharges f
  JOIN batch b ON f.recharge_month BETWEEN add_months(b.ref, -{history}) AND b.ref
  WHERE f.status = 'approved'
  GROUP BY f.pos_id, f.recharge_month
  HAVING SUM(f.amount_brl) > 0
),
tiered AS (
  SELECT pos_id, month, {tier_index} AS tier_idx,
         BROUND(base * {tier_rate}, 2) AS commission
  FROM volume
),
history AS (
  SELECT t.pos_id, AVG(t.commission) AS avg_commission
  FROM tiered t JOIN batch b ON t.month < b.ref
  GROUP BY t.pos_id
),
prev AS (
  SELECT t.pos_id, t.tier_idx FROM tiered t JOIN batch b ON t.month = add_months(b.ref, -1)
),
cur AS (
  SELECT t.pos_id, t.tier_idx, t.commission FROM tiered t JOIN batch b ON t.month = b.ref
),
burst AS (
  SELECT DISTINCT pos_id FROM (
    SELECT f.pos_id,
           COUNT(*) OVER (
             PARTITION BY f.pos_id, f.subscriber_id
             ORDER BY unix_micros(f.recharge_ts_utc)
             RANGE BETWEEN CURRENT ROW AND {window} FOLLOWING
           ) AS n
    FROM {catalog}.gold.fct_recharges f
    JOIN batch b ON f.recharge_month = b.ref
    WHERE f.status = 'approved' AND f.amount_brl = {amount} AND f.recharge_ts_utc IS NOT NULL
  ) WHERE n >= {min_count}
),
closed AS (
  SELECT p.pos_id FROM {catalog}.gold.dim_pos p JOIN batch b
    ON p.closed_date >= b.ref AND p.closed_date <= last_day(b.ref)
),
computed AS (
  SELECT l.beneficiary_id,
    filter(array(
      CASE WHEN h.avg_commission IS NOT NULL
                AND c.commission > {spike} * h.avg_commission THEN 'spike_3x' END,
      CASE WHEN bu.pos_id IS NOT NULL THEN 'fractioning_suspect' END,
      CASE WHEN pr.tier_idx IS NOT NULL
                AND c.tier_idx - pr.tier_idx >= {jump} THEN 'tier_jump' END,
      CASE WHEN cl.pos_id IS NOT NULL THEN 'closed_pos' END
    ), x -> x IS NOT NULL) AS flags
  FROM {catalog}.commission.batch_lines l
  LEFT JOIN cur c ON c.pos_id = l.beneficiary_id
  LEFT JOIN history h ON h.pos_id = l.beneficiary_id
  LEFT JOIN prev pr ON pr.pos_id = l.beneficiary_id
  LEFT JOIN burst bu ON bu.pos_id = l.beneficiary_id
  LEFT JOIN closed cl ON cl.pos_id = l.beneficiary_id
  WHERE l.batch_id = :batch_id AND l.beneficiary_type = 'pos'
)
"""

APPLY_SQL = (
    FLAGS_SQL
    + """
MERGE INTO {catalog}.commission.batch_lines t
USING computed s
ON t.batch_id = :batch_id AND t.beneficiary_type = 'pos' AND t.beneficiary_id = s.beneficiary_id
WHEN MATCHED THEN UPDATE SET t.flags = s.flags
"""
)

SUMMARY_SQL = """
SELECT flag, COUNT(*) AS lines
FROM (SELECT explode(flags) AS flag FROM {catalog}.commission.batch_lines
      WHERE batch_id = :batch_id)
GROUP BY flag
"""


def _draft() -> Any:
    return importlib.import_module("commission.draft")


def _rules() -> Any:
    return importlib.import_module("commission.rules")


def _tier_expr(field: str) -> str:
    """`CASE` SQL sobre `base`, gerado de `rules.TIERS` (índice da faixa ou taxa)."""
    tiers = sorted(_rules().TIERS, key=lambda t: t.floor, reverse=True)
    parts = []
    for tier in tiers[:-1]:
        idx = sorted(_rules().TIERS, key=lambda t: t.floor).index(tier)
        value = idx if field == "index" else tier.rate
        parts.append(f"WHEN base >= {tier.floor} THEN {value}")
    last = tiers[-1]
    otherwise = 0 if field == "index" else last.rate
    return "CASE " + " ".join(parts) + f" ELSE {otherwise} END"


def flags_sql(catalog: str, template: str = APPLY_SQL) -> str:
    """SQL dos flags para `catalog` (identificador validado)."""
    _draft().check_identifier(catalog, "catalog name")
    return template.format(
        catalog=catalog,
        history=SPIKE_HISTORY_MONTHS,
        tier_index=_tier_expr("index"),
        tier_rate=_tier_expr("rate"),
        window=FRACTION_WINDOW_MICROS,
        amount=FRACTION_AMOUNT,
        min_count=FRACTION_MIN_COUNT,
        spike=SPIKE_FACTOR,
        jump=TIER_JUMP_STEPS,
    )


def flag_draft(spark: Any, catalog: str, batch_id: str) -> dict[str, int]:
    """Grava os flags do lote `draft` e devolve a contagem de linhas por flag."""
    draft = _draft()
    draft.check_identifier(catalog, "catalog name")
    header = spark.sql(
        f"SELECT status FROM {catalog}.commission.batches WHERE batch_id = :batch_id",  # noqa: S608
        args={"batch_id": batch_id},
    ).first()
    if header is None:
        raise RuntimeError(f"{batch_id} não existe; rode o rascunho antes")
    if header["status"] != "draft":
        raise RuntimeError(f"{batch_id} está em {header['status']}; só se marca um draft")

    spark.sql(flags_sql(catalog), args={"batch_id": batch_id})
    rows = spark.sql(SUMMARY_SQL.format(catalog=catalog), args={"batch_id": batch_id}).collect()
    counts = {flag: 0 for flag in FLAG_ORDER}
    counts.update({row["flag"]: int(row["lines"]) for row in rows})
    return counts


def main(catalog: str, root: str, reference_month: str = "") -> None:
    from datetime import datetime

    from pyspark.sql import SparkSession  # só existe no workspace

    if root not in sys.path:
        sys.path.insert(0, root)  # raiz do bundle, onde mora o pacote `commission`

    draft = _draft()
    month = draft.resolve_reference_month(reference_month, datetime.now(draft.SAO_PAULO))
    batch_id = draft.batch_id_for(month)  # o job do rascunho só cria a v1
    spark: Any = SparkSession.builder.getOrCreate()
    counts = flag_draft(spark, catalog, batch_id)
    print(f"flags gravados em {batch_id}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    # sem sys.exit: no serverless, `SystemExit` (até com 0) marca a task como falha
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
