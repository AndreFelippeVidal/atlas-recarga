"""Camada silver do pipeline `atlas_medallion` (SPEC-002 §3), tasks P6.2 e P6.3.

Limpa, tipa e deduplica as recargas do bronze.

* Dedup por `recharge_id`: o stream mantém a primeira linha que chega, isto é, a de menor
  `_ingested_at_utc` entre micro-batches (os duplicados do gerador vêm em arquivos diferentes;
  dentro de um mesmo micro-batch as cópias são idênticas, então a escolha não muda o resultado).
* `recharge_date`: o dia de negócio, derivado de `recharge_ts_utc` em America/Sao_Paulo (então uma
  recarga tardia cai no dia certo, não no do arquivo).
* `recharge_hour_local`: hora 0 a 23 no fuso da UF do PDV.
* Expectations: `drop` para defeito linha a linha esperado na fonte; `warn` para regra em
  observação.

Provisório até a P6.4: a UF vem de `bronze.pos` + `bronze.municipalities`; lá troca para
`silver.pos`. Risco conhecido até lá: chave repetida em `bronze.pos`/`municipalities` duplicaria
linhas no join (o script de conferência pega pela unicidade de `recharge_id`).
P6.3: recarga cujo `pos_id` não existe em `bronze.pos` (provisório até a P6.4, quando vira
`silver.pos`) não entra em `silver.recharges`; vai para `silver.recharges_quarantine`, que as retém
(não as descarta). `pos_id` nulo não é órfão: `pos_not_null` o descarta em `silver.recharges`.
As duas tabelas particionam o bronze sem sobreposição.
"""

from pyspark import pipelines as dp
from pyspark.sql import Column, DataFrame, SparkSession
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
    """`pos_id` dos PDVs existentes (provisório: `bronze.pos` até a P6.4)."""
    return dp.read("bronze.pos").select("pos_id").distinct()


def pos_uf() -> DataFrame:
    """`pos_id` -> `uf` do município do PDV."""
    pos = dp.read("bronze.pos").select("pos_id", "municipality_ibge_code")
    municipalities = dp.read("bronze.municipalities").select("municipality_ibge_code", "uf")
    return pos.join(municipalities, "municipality_ibge_code", "left").select("pos_id", "uf")


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
