# Databricks notebook source
# MAGIC %md
# MAGIC # S0.7 — Cotas práticas (DESCARTÁVEL)
# MAGIC
# MAGIC Spike da [SPEC-000](../docs/specs/000-platform-spike/spec.md) §2, item S0.7.
# MAGIC Não é código de produção e não deve ser reaproveitado.
# MAGIC
# MAGIC **Passou se:** o CLI com 2M de linhas e um pipeline mínimo (bronze + silver) terminam
# MAGIC **sem erro de cota em menos de 30 min**.
# MAGIC Plano B (ADR-0001): reduzir o `--rows` padrão e registrar no PRD.
# MAGIC
# MAGIC ## Roteiro (mantenedor)
# MAGIC 1. Local: `uv run atlas-cli generate --out data/generated` (padrão: 2M linhas,
# MAGIC    `--scenarios all`).
# MAGIC    Anotar o tempo, o tamanho em disco e `counts.recharges` do `_manifest.json`.
# MAGIC 2. Subir `data/generated/` para o Volume do spike (UI do Catalog Explorer ou
# MAGIC    `databricks fs cp -r --profile <perfil> data/generated
# MAGIC    dbfs:/Volumes/<catalog>/<schema>/s0_7_landing/`).
# MAGIC    O Volume do spike é **separado** de `atlas.raw.landing` (que só nasce na P5.2).
# MAGIC 3. Rodar as células abaixo em compute **serverless**, marcando o tempo total.
# MAGIC 4. Anotar qualquer erro de cota **com o texto exato** (compute, storage, concorrência).
# MAGIC 5. Rodar a etapa 5 (limpeza) e registrar tudo em `docs/spikes/S0-results.md`.
# MAGIC    Não colar e-mail, token ou IP nas evidências.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")  # noqa: F821
dbutils.widgets.text("schema", "default")  # noqa: F821
CATALOG = dbutils.widgets.get("catalog")  # noqa: F821
SCHEMA = dbutils.widgets.get("schema")  # noqa: F821
VOLUME = "s0_7_landing"
BASE = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
T_BRONZE = f"{CATALOG}.{SCHEMA}.s0_7_bronze_recharges"
T_SILVER = f"{CATALOG}.{SCHEMA}.s0_7_silver_recharges"

import time  # noqa: E402

T0 = time.time()
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME}")  # noqa: F821
print("Volume:", BASE)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Conferir o que subiu

# COMMAND ----------

files = dbutils.fs.ls(f"{BASE}/recharges")  # noqa: F821
print("partições (dt=...):", len(files))
with open(f"{BASE}/_manifest.json") as fh:
    print(fh.read()[:600])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Bronze: leitura em lote do Parquet (Auto Loader fica para a P6.1)
# MAGIC
# MAGIC O spike mede cota de compute e de armazenamento, não o Auto Loader.

# COMMAND ----------

t = time.time()
(
    spark.read.parquet(f"{BASE}/recharges")  # noqa: F821
    .write.mode("overwrite")
    .saveAsTable(T_BRONZE)
)
n_bronze = spark.table(T_BRONZE).count()  # noqa: F821
print(f"bronze: {n_bronze:,} linhas em {time.time() - t:.0f}s")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Silver: dedup por `recharge_id`, data em America/Sao_Paulo, sem nulos/negativos

# COMMAND ----------

t = time.time()
spark.sql(  # noqa: F821
    f"""
    CREATE OR REPLACE TABLE {T_SILVER} AS
    SELECT recharge_id, recharge_ts_utc,
           CAST(from_utc_timestamp(recharge_ts_utc, 'America/Sao_Paulo') AS DATE) AS recharge_date,
           pos_id, subscriber_id, amount_brl, status, ingested_at_utc
    FROM (
      SELECT *, row_number() OVER (PARTITION BY recharge_id ORDER BY ingested_at_utc) AS rn
      FROM {T_BRONZE}
      WHERE recharge_id IS NOT NULL AND amount_brl IS NOT NULL AND amount_brl > 0
    ) WHERE rn = 1
    """  # noqa: S608
)
n_silver = spark.table(T_SILVER).count()  # noqa: F821
print(f"silver: {n_silver:,} linhas em {time.time() - t:.0f}s")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Resultado
# MAGIC Critério: total < 30 min (1800 s) e nenhum erro de cota.

# COMMAND ----------

total = time.time() - T0
print(f"bronze={n_bronze:,} silver={n_silver:,} total={total:.0f}s")
print("PASSOU" if total < 1800 else "FALHOU (tempo)", "(se não houve erro de cota)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Limpeza

# COMMAND ----------

# spark.sql(f"DROP TABLE IF EXISTS {T_SILVER}")
# spark.sql(f"DROP TABLE IF EXISTS {T_BRONZE}")
# spark.sql(f"DROP VOLUME IF EXISTS {CATALOG}.{SCHEMA}.{VOLUME}")
