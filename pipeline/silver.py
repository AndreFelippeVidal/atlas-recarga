"""Camada silver do pipeline `atlas_medallion` (SPEC-002 §3), tasks P6.2, P6.3 e P6.4.

Limpa, tipa e deduplica as recargas do bronze e valida as dimensões (PDV, distribuidor,
município).

* Dedup por `recharge_id`: o stream mantém a primeira linha que chega, isto é, a de menor
  `_ingested_at_utc` entre micro-batches (os duplicados do gerador vêm em arquivos diferentes;
  dentro de um mesmo micro-batch as cópias são idênticas, então a escolha não muda o resultado).
* `recharge_date`: o dia de negócio, derivado de `recharge_ts_utc` em America/Sao_Paulo (então uma
  recarga tardia cai no dia certo, não no do arquivo).
* `recharge_hour_local`: hora 0 a 23 no fuso da UF do PDV.
* Expectations: `drop` para defeito linha a linha esperado na fonte; `warn` para regra em
  observação.

P6.3: recarga cujo `pos_id` não existe em `silver.pos` não entra em `silver.recharges`; vai para
`silver.recharges_quarantine`, que as retém (não as descarta). `pos_id` nulo não é órfão:
`pos_not_null` o descarta em `silver.recharges`. As duas tabelas particionam o bronze sem
sobreposição.
P6.4: as dimensões (`silver.municipalities`, `silver.distributors`, `silver.pos`) são materialized
views com `expect_or_fail`: dimensão corrompida derruba o pipeline e o gold do dia anterior segue
servido (SPEC-002 §4). Expectation só enxerga colunas da própria linha, então a referência
cruzada vira uma coluna booleana `_*_in_reference` (left join) e a unicidade da PK vira
`_pk_rows` (contagem por chave); o `expect_or_fail` confere essas colunas. Essas colunas `_*`
fazem parte do schema silver e não devem ser herdadas pelo gold.
Limitação conhecida (stream-static): o lado estático (`silver.pos`) é um snapshot por atualização.
Uma recarga que chega antes do seu PDV vai para a quarentena e lá fica, sem voltar para
`silver.recharges` (reprocessar a quarentena é trabalho futuro).
"""

from pyspark import pipelines as dp
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

spark = SparkSession.getActiveSession()
if spark is None:
    raise RuntimeError("o pipeline roda dentro de uma sessão Spark ativa")

BUSINESS_TZ = "America/Sao_Paulo"

# Offset fixo em relação ao UTC por UF (o Brasil não tem horário de verão desde 2019).
# AC UTC-5; AM, RO, RR, MT, MS UTC-4; as demais UTC-3 (SPEC-002 §3).
DEFAULT_UTC_OFFSET = "-03:00"
UTC_OFFSET_BY_UF = {
    "AC": "-05:00",
    "AM": "-04:00",
    "RO": "-04:00",
    "RR": "-04:00",
    "MT": "-04:00",
    "MS": "-04:00",
}


def utc_offset_for_uf(uf: str | None) -> str:
    """Offset UTC da UF; UF desconhecida ou nula (PDV órfão) cai no padrão de Brasília."""
    return UTC_OFFSET_BY_UF.get(uf or "", DEFAULT_UTC_OFFSET)


def local_offset(uf: Column) -> Column:
    """Mesmo mapa de `utc_offset_for_uf`, como expressão Spark."""
    mapping = F.create_map(*[F.lit(x) for kv in UTC_OFFSET_BY_UF.items() for x in kv])
    return F.coalesce(mapping[uf], F.lit(DEFAULT_UTC_OFFSET))


def known_pos() -> DataFrame:
    """`pos_id` dos PDVs existentes (`silver.pos`)."""
    return dp.read("silver.pos").select("pos_id")


def pos_uf() -> DataFrame:
    """`pos_id` -> `uf` do município do PDV."""
    return dp.read("silver.pos").select("pos_id", "uf")


@dp.table(
    name="silver.recharges",
    comment=(
        "Recargas limpas e deduplicadas por recharge_id, com recharge_date em "
        "America/Sao_Paulo e recharge_hour_local no fuso da UF do PDV."
    ),
)
@dp.expect_or_drop("pos_not_null", "pos_id IS NOT NULL")
@dp.expect_or_drop("positive_amount", "amount_brl > 0")
@dp.expect_or_drop("valid_status", "status IN ('approved','reversed')")
@dp.expect("face_value", "amount_brl IN (10,15,20,25,30,40,50,100)")
def recharges() -> DataFrame:
    deduped = dp.read_stream("bronze.recharges").dropDuplicates(["recharge_id"])
    # inner: recarga de PDV órfão sai daqui e vai para a quarentena; `pos_id` nulo também
    # não casa, e é o `pos_not_null` quem o descarta, então não precisa de tratamento extra.
    joined = deduped.join(F.broadcast(pos_uf()), "pos_id", "inner")
    local_ts = F.from_utc_timestamp(F.col("recharge_ts_utc"), local_offset(F.col("uf")))
    return joined.select(
        "recharge_id",
        "recharge_ts_utc",
        F.to_date(F.from_utc_timestamp(F.col("recharge_ts_utc"), BUSINESS_TZ)).alias(
            "recharge_date"
        ),
        F.hour(local_ts).alias("recharge_hour_local"),
        "pos_id",
        "subscriber_id",
        "amount_brl",
        "status",
        "_source_file",
        "_ingested_at_utc",
    )


@dp.table(
    name="silver.recharges_quarantine",
    comment=(
        "Recargas retidas porque o pos_id não existe em silver.pos (PDV órfão). "
        "Ficam aqui para análise; não entram em silver.recharges."
    ),
)
def recharges_quarantine() -> DataFrame:
    deduped = (
        dp.read_stream("bronze.recharges")
        .where(F.col("pos_id").isNotNull())
        .dropDuplicates(["recharge_id"])
    )
    orphans = deduped.join(F.broadcast(known_pos()), "pos_id", "left_anti")
    return orphans.select(
        "recharge_id",
        "recharge_ts_utc",
        "pos_id",
        "subscriber_id",
        "amount_brl",
        "status",
        "_source_file",
        "_ingested_at_utc",
    )


def with_pk_rows(df: DataFrame, key: str) -> DataFrame:
    """`_pk_rows`: quantas linhas têm a mesma chave (1 = única); nula conta como 0."""
    counted = F.count(F.lit(1)).over(Window.partitionBy(key))
    return df.withColumn("_pk_rows", F.when(F.col(key).isNull(), F.lit(0)).otherwise(counted))


@dp.materialized_view(
    name="silver.municipalities",
    comment="Municípios (referência IBGE) tipados; PK municipality_ibge_code de 7 dígitos.",
)
@dp.expect_or_fail("municipality_pk_valid", "_pk_rows = 1")
def municipalities() -> DataFrame:
    raw = dp.read("bronze.municipalities")
    return with_pk_rows(
        raw.select(
            "municipality_ibge_code",
            "municipality_name",
            "uf",
            "region",
            F.col("population").cast("int").alias("population"),
            F.col("ddd").cast("string").alias("ddd"),
        ),
        "municipality_ibge_code",
    )


@dp.materialized_view(
    name="silver.distributors",
    comment="Distribuidores tipados; PK distributor_id.",
)
@dp.expect_or_fail("distributor_pk_valid", "_pk_rows = 1")
def distributors() -> DataFrame:
    raw = dp.read("bronze.distributors")
    return with_pk_rows(
        raw.select("distributor_id", "distributor_name", "hq_uf", "created_date"),
        "distributor_id",
    )


@dp.materialized_view(
    name="silver.pos",
    comment="Pontos de venda com município e distribuidor existentes; PK pos_id.",
)
@dp.expect_or_fail("pos_pk_valid", "_pk_rows = 1")
@dp.expect_or_fail("pos_municipality_known", "_municipality_in_reference")
@dp.expect_or_fail("pos_has_distributor", "_distributor_in_reference")
def pos() -> DataFrame:
    municipalities = dp.read("silver.municipalities").select(
        "municipality_ibge_code", "uf", F.lit(True).alias("_municipality_in_reference")
    )
    distributors = dp.read("silver.distributors").select(
        "distributor_id", F.lit(True).alias("_distributor_in_reference")
    )
    joined = (
        dp.read("bronze.pos")
        .join(municipalities, "municipality_ibge_code", "left")
        .join(distributors, "distributor_id", "left")
    )
    return with_pk_rows(
        joined.select(
            "pos_id",
            "distributor_id",
            "pos_name",
            "pos_type",
            "municipality_ibge_code",
            "uf",
            "opened_date",
            "closed_date",
            F.coalesce("_municipality_in_reference", F.lit(False)).alias(
                "_municipality_in_reference"
            ),
            F.coalesce("_distributor_in_reference", F.lit(False)).alias(
                "_distributor_in_reference"
            ),
        ),
        "pos_id",
    )
