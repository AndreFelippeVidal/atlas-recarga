"""Camada gold do pipeline `atlas_medallion` (SPEC-002 §3), tasks P6.5 e P6.6.

Modelo dimensional consumido pelas metric views (SPEC-004): `dim_municipality`, `dim_pos`,
`dim_distributor`, `fct_recharges` e `agg_pos_month`. Todas são materialized views.

* Cada tabela declara o schema em DDL com `COMMENT` em **todas** as colunas, além do `comment` da
  tabela, porque o Genie e o agente leem essas descrições (SPEC-002 §3, última linha).
* As colunas técnicas `_*` do silver (`_pk_rows`, `_*_in_reference`, `_source_file`,
  `_ingested_at_utc`) não são herdadas: o `select` lista só as colunas do gold.
* `fct_recharges` lê só `silver.recharges`; a quarentena (PDV órfão) fica fora do gold.
* Dinheiro é `DECIMAL(14,2)` (tech-stack, Proibido: DOUBLE/FLOAT).
"""

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

spark = SparkSession.getActiveSession()
if spark is None:
    raise RuntimeError("o pipeline roda dentro de uma sessão Spark ativa")

# (nome, tipo SQL, descrição). Fonte única do schema declarado e do `select`.
Column = tuple[str, str, str]

DIM_MUNICIPALITY: list[Column] = [
    (
        "municipality_ibge_code",
        "STRING",
        "Código IBGE do município, 7 dígitos. Chave primária.",
    ),
    ("municipality_name", "STRING", "Nome do município."),
    ("uf", "STRING", "Sigla da unidade da federação (UF) do município."),
    ("region", "STRING", "Região do Brasil: Norte, Nordeste, Centro-Oeste, Sudeste ou Sul."),
    ("ddd", "STRING", "DDD aproximado do município, por região imediata."),
    ("population", "INT", "População do município (referência IBGE)."),
]

DIM_DISTRIBUTOR: list[Column] = [
    ("distributor_id", "STRING", "Identificador do distribuidor. Chave primária."),
    ("distributor_name", "STRING", "Nome do distribuidor (fictício)."),
    ("hq_uf", "STRING", "UF da sede do distribuidor."),
]

DIM_POS: list[Column] = [
    ("pos_id", "STRING", "Identificador do ponto de venda (PDV). Chave primária."),
    (
        "pos_type",
        "STRING",
        (
            "Tipo do PDV: newsstand (banca), pharmacy (farmácia), grocery (mercearia), "
            "lottery (lotérica) ou partner_app (app parceiro)."
        ),
    ),
    ("distributor_id", "STRING", "Distribuidor que atende o PDV. Liga em dim_distributor."),
    (
        "municipality_ibge_code",
        "STRING",
        "Município do PDV, código IBGE de 7 dígitos. Liga em dim_municipality.",
    ),
    ("opened_date", "DATE", "Data de abertura do PDV."),
    ("closed_date", "DATE", "Data de fechamento do PDV; nula enquanto o PDV está aberto."),
]

FCT_RECHARGES: list[Column] = [
    ("recharge_id", "STRING", "Identificador único da recarga. Chave primária."),
    (
        "recharge_date",
        "DATE",
        "Dia de negócio da recarga, em America/Sao_Paulo, derivado do instante em UTC.",
    ),
    (
        "recharge_month",
        "DATE",
        "Mês de negócio da recarga: primeiro dia do mês de recharge_date.",
    ),
    (
        "recharge_hour_local",
        "INT",
        "Hora da recarga, de 0 a 23, no fuso da UF do PDV.",
    ),
    ("pos_id", "STRING", "PDV onde a recarga foi vendida. Liga em dim_pos."),
    (
        "amount_brl",
        "DECIMAL(14,2)",
        "Valor de face da recarga, em reais (BRL).",
    ),
    ("status", "STRING", "Situação da recarga: approved (aprovada) ou reversed (estornada)."),
    ("subscriber_id", "STRING", "Identificador anônimo do assinante que recarregou."),
]

AGG_POS_MONTH: list[Column] = [
    ("pos_id", "STRING", "PDV. Liga em dim_pos. Chave primária junto com recharge_month."),
    (
        "recharge_month",
        "DATE",
        "Mês de negócio: primeiro dia do mês, em America/Sao_Paulo. Chave primária com pos_id.",
    ),
    (
        "approved_amount_brl",
        "DECIMAL(14,2)",
        "Soma, em reais (BRL), das recargas aprovadas do PDV no mês. Base da comissão.",
    ),
    ("approved_count", "BIGINT", "Quantidade de recargas aprovadas do PDV no mês."),
    ("reversed_count", "BIGINT", "Quantidade de recargas estornadas do PDV no mês."),
    (
        "distinct_subscribers",
        "BIGINT",
        "Assinantes distintos com recarga aprovada no PDV no mês.",
    ),
]


def ddl(columns: list[Column]) -> str:
    """Schema em DDL com `COMMENT` por coluna (o que o Catalog, o Genie e o agente leem)."""
    parts = []
    for name, sql_type, comment in columns:
        escaped = comment.replace("'", "\\'")
        parts.append(f"{name} {sql_type} COMMENT '{escaped}'")
    return ", ".join(parts)


def project(df: DataFrame, columns: list[Column]) -> DataFrame:
    """Seleciona só as colunas do gold, com o tipo declarado, e deixa de fora as `_*` do silver."""
    return df.select(*[F.col(name).cast(sql_type).alias(name) for name, sql_type, _ in columns])


@dp.materialized_view(
    name="gold.dim_municipality",
    comment=(
        "Dimensão de município (referência IBGE): UF, região, DDD e população. Grão: município."
    ),
    schema=ddl(DIM_MUNICIPALITY),
)
def dim_municipality() -> DataFrame:
    return project(dp.read("silver.municipalities"), DIM_MUNICIPALITY)


@dp.materialized_view(
    name="gold.dim_distributor",
    comment="Dimensão de distribuidor da rede de recarga. Grão: distribuidor.",
    schema=ddl(DIM_DISTRIBUTOR),
)
def dim_distributor() -> DataFrame:
    return project(dp.read("silver.distributors"), DIM_DISTRIBUTOR)


@dp.materialized_view(
    name="gold.dim_pos",
    comment=(
        "Dimensão de ponto de venda (PDV) com tipo, distribuidor, município e datas de "
        "abertura e fechamento. Grão: PDV. Histórico simples (SCD1)."
    ),
    schema=ddl(DIM_POS),
)
def dim_pos() -> DataFrame:
    return project(dp.read("silver.pos"), DIM_POS)


@dp.materialized_view(
    name="gold.fct_recharges",
    comment=(
        "Fato de recargas vendidas nos PDVs, já limpas e deduplicadas; recargas de PDV "
        "órfão ficam fora (em silver.recharges_quarantine). Grão: recarga."
    ),
    schema=ddl(FCT_RECHARGES),
)
def fct_recharges() -> DataFrame:
    base = dp.read("silver.recharges").withColumn(
        "recharge_month", F.trunc(F.col("recharge_date"), "month")
    )
    return project(base, FCT_RECHARGES)


@dp.materialized_view(
    name="gold.agg_pos_month",
    comment=(
        "Agregado de recargas por PDV e mês, base da comissão. Só recargas aprovadas entram "
        "nos valores e em assinantes distintos; estornos aparecem em reversed_count. Inclui "
        "o PDV ativo sem recarga no mês, com zeros. Grão: PDV x mês."
    ),
    schema=ddl(AGG_POS_MONTH),
)
def agg_pos_month() -> DataFrame:
    facts = dp.read("gold.fct_recharges")
    pos = dp.read("gold.dim_pos")
    months = facts.select("recharge_month").distinct()

    # PDV ativo no mês: aberto até o último dia do mês e não fechado antes do primeiro dia.
    active = pos.join(
        months,
        (F.col("opened_date") <= F.last_day(F.col("recharge_month")))
        & (F.col("closed_date").isNull() | (F.col("closed_date") >= F.col("recharge_month"))),
    ).select("pos_id", "recharge_month")
    # Quem tem recarga no mês entra mesmo fora da janela, para a soma bater com a fato.
    keys = active.unionByName(facts.select("pos_id", "recharge_month")).distinct()

    totals = facts.groupBy("pos_id", "recharge_month").agg(
        F.sum(F.when(F.col("status") == "approved", F.col("amount_brl"))).alias(
            "approved_amount_brl"
        ),
        F.count(F.when(F.col("status") == "approved", 1)).alias("approved_count"),
        F.count(F.when(F.col("status") == "reversed", 1)).alias("reversed_count"),
        F.countDistinct(F.when(F.col("status") == "approved", F.col("subscriber_id"))).alias(
            "distinct_subscribers"
        ),
    )
    joined = keys.join(totals, ["pos_id", "recharge_month"], "left").fillna(
        0,
        subset=["approved_count", "reversed_count", "distinct_subscribers"],
    )
    joined = joined.withColumn(
        "approved_amount_brl", F.coalesce(F.col("approved_amount_brl"), F.lit(0))
    )
    return project(joined, AGG_POS_MONTH)
