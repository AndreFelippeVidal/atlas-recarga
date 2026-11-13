"""Camada bronze do pipeline `atlas_medallion` (SPEC-002 §3).

Cópia fiel do landing, só acrescenta metadados (`_source_file`, `_ingested_at_utc`).
Nenhuma expectation aqui: o bronze nunca descarta linha (as regras vivem no silver).
O caminho do landing vem da configuração `atlas.landing_path`, definida no `databricks.yml`
(um Volume por target), para o mesmo código servir a `dev` e a `demo`.
"""

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

spark = SparkSession.getActiveSession()
if spark is None:
    raise RuntimeError("o pipeline roda dentro de uma sessão Spark ativa")


def _landing(folder: str) -> str:
    base = spark.conf.get("atlas.landing_path").rstrip("/")
    return f"{base}/{folder}"


def with_metadata(df: DataFrame) -> DataFrame:
    """Acrescenta os metadados de linhagem do bronze."""
    return df.select(
        "*",
        F.col("_metadata.file_path").alias("_source_file"),
        F.current_timestamp().alias("_ingested_at_utc"),
    )


@dp.table(
    name="bronze.recharges",
    comment="Recargas como chegaram do landing (Auto Loader), com metadados de ingestão.",
)
def recharges() -> DataFrame:
    stream = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .option("cloudFiles.inferColumnTypes", "true")
        .load(_landing("recharges"))
    )
    return with_metadata(stream)


@dp.materialized_view(
    name="bronze.pos",
    comment="Pontos de venda como chegaram do landing, com metadados de ingestão.",
)
def pos() -> DataFrame:
    return with_metadata(spark.read.format("parquet").load(_landing("pos")))


@dp.materialized_view(
    name="bronze.distributors",
    comment="Distribuidores como chegaram do landing, com metadados de ingestão.",
)
def distributors() -> DataFrame:
    return with_metadata(spark.read.format("parquet").load(_landing("distributors")))


@dp.materialized_view(
    name="bronze.municipalities",
    comment="Referência IBGE de municípios (dado público) copiada para o landing.",
)
def municipalities() -> DataFrame:
    # Sem inferSchema: tudo chega como STRING, então o código IBGE de 7 dígitos não perde zero.
    csv = spark.read.format("csv").option("header", "true").load(_landing("municipalities"))
    return with_metadata(csv)
