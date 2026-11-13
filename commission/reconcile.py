"""Reconciliação independente do rascunho de comissão (SPEC-003 §5, itens 1 e 2, task P8.4).

Roda como segunda task do job `atlas_commission_draft`, logo depois de `calculate_draft`.
Recalcula o lote em **SQL puro sobre `gold.fct_recharges`** (sem `agg_pos_month`, sem
`rules.py`, sem o PySpark do `draft.py`) e compara com `commission.batch_lines`:

1. diferença por linha (base e comissão) e no total (cabeçalho do lote contra o recálculo): R$ 0,00;
2. totais de controle: base dos PDVs = volume aprovado do mês em `fct_recharges`; base dos
   distribuidores = soma do volume por distribuidor.

As faixas e taxas estão **escritas de novo** em `RECOMPUTE_SQL` de propósito: reusar
`rules.TIERS` tornaria a conferência dependente do que ela confere. O teste
`test_reconcile.py` garante que as duas tabelas não divergem.

Grava uma linha por lote em `commission.reconciliation` (reexecutar substitui a linha). Se
alguma diferença não for R$ 0,00, grava `status = 'failed'` e levanta erro: o lote fica em
`draft` e a P8.6 só libera `draft -> under_review` com `status = 'passed'`. Sem IA, só leitura
em `gold`; escreve apenas em `commission.reconciliation`.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

ZERO = Decimal("0.00")

# Faixas da SPEC-003 §2, repetidas de propósito (ver docstring do módulo).
RECOMPUTE_SQL = """
WITH batch AS (
  SELECT batch_id, reference_month, total_pos_brl, total_distributor_brl
  FROM {catalog}.commission.batches
  WHERE batch_id = :batch_id
),
pos_volume AS (
  SELECT f.pos_id, SUM(f.amount_brl) AS base
  FROM {catalog}.gold.fct_recharges f
  JOIN batch b ON f.recharge_month = b.reference_month
  WHERE f.status = 'approved'
  GROUP BY f.pos_id
  HAVING SUM(f.amount_brl) > 0
),
expected AS (
  SELECT 'pos' AS beneficiary_type, pos_id AS beneficiary_id,
         CAST(base AS DECIMAL(14,2)) AS base_amount_brl,
         CAST(BROUND(base * CASE
           WHEN base >= 50000.00 THEN 0.05
           WHEN base >= 20000.00 THEN 0.04
           WHEN base >= 5000.00 THEN 0.03
           ELSE 0.02 END, 2) AS DECIMAL(14,2)) AS commission_brl
  FROM pos_volume
  UNION ALL
  SELECT 'distributor', p.distributor_id,
         CAST(SUM(v.base) AS DECIMAL(14,2)),
         CAST(BROUND(SUM(v.base) * 0.03, 2) AS DECIMAL(14,2))
  FROM pos_volume v
  JOIN {catalog}.gold.dim_pos p ON p.pos_id = v.pos_id
  GROUP BY p.distributor_id
),
actual AS (
  SELECT beneficiary_type, beneficiary_id, base_amount_brl, commission_brl
  FROM {catalog}.commission.batch_lines
  WHERE batch_id = :batch_id
),
cmp AS (
  SELECT
    ABS(COALESCE(a.commission_brl, 0) - COALESCE(e.commission_brl, 0)) AS commission_diff,
    ABS(COALESCE(a.base_amount_brl, 0) - COALESCE(e.base_amount_brl, 0)) AS base_diff
  FROM actual a
  FULL OUTER JOIN expected e
    ON a.beneficiary_type = e.beneficiary_type AND a.beneficiary_id = e.beneficiary_id
)
SELECT
  (SELECT COUNT(*) FROM batch) AS batch_found,
  (SELECT COUNT(*) FROM cmp) AS lines_compared,
  (SELECT CAST(COALESCE(MAX(GREATEST(commission_diff, base_diff)), 0) AS DECIMAL(14,2))
     FROM cmp) AS max_line_diff_brl,
  (SELECT CAST(COALESCE(MAX(b.total_pos_brl + b.total_distributor_brl), 0)
                 - COALESCE((SELECT SUM(commission_brl) FROM expected), 0) AS DECIMAL(14,2))
     FROM batch b) AS total_diff_brl,
  (SELECT CAST(COALESCE(SUM(base_amount_brl), 0)
                 - COALESCE((SELECT SUM(base) FROM pos_volume), 0) AS DECIMAL(14,2))
     FROM actual WHERE beneficiary_type = 'pos') AS pos_control_diff_brl,
  (SELECT CAST(COALESCE(SUM(base_amount_brl), 0)
                 - COALESCE((SELECT SUM(base_amount_brl) FROM expected
                             WHERE beneficiary_type = 'distributor'), 0) AS DECIMAL(14,2))
     FROM actual WHERE beneficiary_type = 'distributor') AS distributor_control_diff_brl
"""


@dataclass(frozen=True)
class Result:
    batch_id: str
    lines_compared: int
    max_line_diff_brl: Decimal
    total_diff_brl: Decimal
    pos_control_diff_brl: Decimal
    distributor_control_diff_brl: Decimal

    @property
    def status(self) -> str:
        return decide_status(self)


def decide_status(result: Result) -> str:
    """`passed` só com ao menos uma linha e **todas** as diferenças em R$ 0,00."""
    diffs = (
        result.max_line_diff_brl,
        result.total_diff_brl,
        result.pos_control_diff_brl,
        result.distributor_control_diff_brl,
    )
    if result.lines_compared <= 0:
        return "failed"
    return "passed" if all(d == ZERO for d in diffs) else "failed"


def recompute_sql(catalog: str) -> str:
    """SQL da reconciliação para `catalog` (já validado como identificador)."""
    draft = _draft()
    draft.check_identifier(catalog, "catalog name")
    return RECOMPUTE_SQL.format(catalog=catalog)


def _draft() -> Any:
    return importlib.import_module("commission.draft")


def reconcile(spark: Any, catalog: str, batch_id: str) -> Result:
    """Reconcilia o lote, grava `commission.reconciliation` e devolve o resultado."""
    from pyspark.sql.types import (
        DecimalType,
        LongType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )

    draft = _draft()
    draft.check_identifier(catalog, "catalog name")
    batches_t = f"{catalog}.commission.batches"
    table = f"{catalog}.commission.reconciliation"

    header = spark.sql(
        f"SELECT status FROM {batches_t} WHERE batch_id = :batch_id",  # noqa: S608
        args={"batch_id": batch_id},
    ).first()
    if header is None:
        raise RuntimeError(f"{batch_id} não existe; rode o rascunho antes")
    if header["status"] != "draft":
        raise RuntimeError(f"{batch_id} está em {header['status']}; só se reconcilia um draft")

    row = spark.sql(recompute_sql(catalog), args={"batch_id": batch_id}).first()
    if row is None:  # a consulta sempre devolve uma linha; defensivo
        raise RuntimeError("a consulta de reconciliação não devolveu resultado")
    result = Result(
        batch_id=batch_id,
        lines_compared=int(row["lines_compared"]),
        max_line_diff_brl=Decimal(row["max_line_diff_brl"]),
        total_diff_brl=Decimal(row["total_diff_brl"]),
        pos_control_diff_brl=Decimal(row["pos_control_diff_brl"]),
        distributor_control_diff_brl=Decimal(row["distributor_control_diff_brl"]),
    )

    money = DecimalType(14, 2)
    schema = StructType(
        [
            StructField("batch_id", StringType(), False),
            StructField("status", StringType(), False),
            StructField("lines_compared", LongType(), False),
            StructField("max_line_diff_brl", money, False),
            StructField("total_diff_brl", money, False),
            StructField("pos_control_diff_brl", money, False),
            StructField("distributor_control_diff_brl", money, False),
            StructField("checked_at_utc", TimestampType(), False),
        ]
    )
    record = spark.createDataFrame(
        [
            (
                batch_id,
                result.status,
                result.lines_compared,
                result.max_line_diff_brl,
                result.total_diff_brl,
                result.pos_control_diff_brl,
                result.distributor_control_diff_brl,
                datetime.now(ZoneInfo("UTC")),
            )
        ],
        schema,
    )
    # Uma linha por lote: reexecutar substitui (a tabela não é append-only).
    spark.sql(f"DELETE FROM {table} WHERE batch_id = :batch_id", args={"batch_id": batch_id})  # noqa: S608
    record.writeTo(table).append()

    if result.status != "passed":
        raise RuntimeError(
            f"reconciliação de {batch_id} FALHOU: linhas={result.lines_compared}, "
            f"max_line={result.max_line_diff_brl}, total={result.total_diff_brl}, "
            f"pos={result.pos_control_diff_brl}, dist={result.distributor_control_diff_brl}"
        )
    return result


def main(catalog: str, root: str, reference_month: str = "") -> None:
    from pyspark.sql import SparkSession  # só existe no workspace

    if root not in sys.path:
        sys.path.insert(0, root)  # raiz do bundle, onde mora o pacote `commission`

    draft = _draft()
    month = draft.resolve_reference_month(reference_month, datetime.now(draft.SAO_PAULO))
    batch_id = draft.batch_id_for(month)  # o job do rascunho só cria a v1
    spark: Any = SparkSession.builder.getOrCreate()
    result = reconcile(spark, catalog, batch_id)
    print(f"reconciliação passed: {batch_id} ({result.lines_compared} linhas, diferença R$ 0,00)")


if __name__ == "__main__":
    # sem sys.exit: no serverless, `SystemExit` (até com 0) marca a task como falha
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
