"""Task 3 do job `atlas_daily`: frescor e qualidade do dia (SPEC-002 §2 e §4, task P6.7).

Roda como `spark_python_task` serverless depois do refresh do pipeline e acrescenta uma linha em
`<catalog>.observability.pipeline_freshness`. Não é carregado pelo pipeline (não está em
`libraries` no `databricks.yml`). Só lê o gold e o silver; nunca falha o job por dado ruim: a
decisão vira `stale` e `degraded` na tabela (não bloqueia no MVP; bloqueia na v2).

* `freshness_status`: `fresh` se `max(recharge_date)` de `gold.fct_recharges` é D-1 ou mais
  novo em America/Sao_Paulo; `stale` se for mais antigo ou se a fato estiver vazia.
* `quality_status`: `degraded` se mais de 1% das recargas (por `recharge_id`) ingeridas nas últimas
  24 h no bronze não chegaram a `silver.recharges` nem à `silver.recharges_quarantine`. Duplicados
  não contam como descarte; a quarentena também não (ficam retidas, SPEC-002 §3).
"""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from typing import Any

BUSINESS_TZ = "America/Sao_Paulo"
DEGRADED_THRESHOLD = 0.01
WINDOW_HOURS = 24
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")

DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.observability.pipeline_freshness (
  run_ts_utc TIMESTAMP COMMENT 'Quando a verificação rodou (UTC)',
  business_date DATE COMMENT 'Hoje em America/Sao_Paulo; o gold esperado vai até D-1',
  max_recharge_date DATE COMMENT 'Maior recharge_date em gold.fct_recharges',
  freshness_status STRING COMMENT 'fresh ou stale (max_recharge_date < D-1)',
  ingested_count BIGINT COMMENT 'recharge_id distintos ingeridos no bronze nas últimas 24 h',
  dropped_count BIGINT COMMENT 'Desses, quantos não estão no silver nem na quarentena',
  dropped_ratio DECIMAL(7,6) COMMENT 'dropped_count / ingested_count (0 se não houve ingestão)',
  quality_status STRING COMMENT 'ok ou degraded (dropped_ratio > 1%)'
)
COMMENT 'Frescor e qualidade de cada execução do job atlas_daily (SPEC-002 §4)'
"""

COUNTS_QUERY = """
WITH ingested AS (
  SELECT DISTINCT recharge_id FROM {catalog}.bronze.recharges
  WHERE _ingested_at_utc >= current_timestamp() - INTERVAL {hours} HOURS
)
SELECT
  (SELECT MAX(recharge_date) FROM {catalog}.gold.fct_recharges) AS max_recharge_date,
  (SELECT COUNT(*) FROM ingested) AS ingested_count,
  (SELECT COUNT(*) FROM ingested i
     WHERE NOT EXISTS (SELECT 1 FROM {catalog}.silver.recharges s WHERE s.recharge_id = i.recharge_id)
       AND NOT EXISTS (SELECT 1 FROM {catalog}.silver.recharges_quarantine q
                       WHERE q.recharge_id = i.recharge_id)) AS dropped_count
"""  # noqa: E501


def check_catalog(catalog: str) -> str:
    """O catálogo vem do parâmetro do job; valida antes de entrar no SQL."""
    if not _IDENTIFIER.fullmatch(catalog):
        raise ValueError(f"invalid catalog name: {catalog!r}")
    return catalog


def freshness_status(max_recharge_date: date | None, business_date: date) -> str:
    """`stale` se o gold não chega a D-1 (ou está vazio); senão `fresh`."""
    if max_recharge_date is None or max_recharge_date < business_date - timedelta(days=1):
        return "stale"
    return "fresh"


def dropped_ratio(ingested: int, dropped: int) -> float:
    return dropped / ingested if ingested else 0.0


def quality_status(ratio: float) -> str:
    """`degraded` só acima de 1% (exatamente 1% ainda é ok)."""
    return "degraded" if ratio > DEGRADED_THRESHOLD else "ok"


def main(catalog: str) -> int:
    from pyspark.sql import SparkSession  # só existe no workspace

    catalog = check_catalog(catalog)
    spark: Any = SparkSession.builder.getOrCreate()
    spark.sql(DDL.format(catalog=catalog))
    row = spark.sql(COUNTS_QUERY.format(catalog=catalog, hours=WINDOW_HOURS)).first()
    today = spark.sql(
        f"SELECT CAST(from_utc_timestamp(current_timestamp(), '{BUSINESS_TZ}') AS DATE)"
    ).first()[0]
    ingested, dropped = int(row["ingested_count"]), int(row["dropped_count"])
    ratio = dropped_ratio(ingested, dropped)
    fresh = freshness_status(row["max_recharge_date"], today)
    quality = quality_status(ratio)
    spark.sql(
        f"INSERT INTO {catalog}.observability.pipeline_freshness "
        "SELECT current_timestamp(), :business_date, :max_date, :fresh, :ingested, :dropped, "
        "CAST(:ratio AS DECIMAL(7,6)), :quality",
        args={
            "business_date": today,
            "max_date": row["max_recharge_date"],
            "fresh": fresh,
            "ingested": ingested,
            "dropped": dropped,
            "ratio": ratio,
            "quality": quality,
        },
    )
    print(f"freshness={fresh} quality={quality} ingested={ingested} dropped={dropped}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
