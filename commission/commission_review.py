# Databricks notebook source
# MAGIC %md
# MAGIC # commission_review
# MAGIC Revisão de um lote de comissão (SPEC-003 §5.4): totais e reconciliação, top 20, linhas
# MAGIC com flag e comparação com o mês anterior. **Somente leitura**: não aprova nem altera nada.
# MAGIC As consultas são as mesmas do dashboard (`commission/review_sql`).
# MAGIC Preencha `catalog` e `batch_id` nos widgets.

# COMMAND ----------

import os
import sys

# o notebook mora em <raiz do bundle>/commission; a raiz tem o pacote `commission`
sys.path.insert(0, os.path.dirname(os.getcwd()))

from commission import review_report

dbutils.widgets.text("catalog", "atlas_dev")  # type: ignore[name-defined]  # noqa: F821
dbutils.widgets.text("batch_id", "")  # type: ignore[name-defined]  # noqa: F821
catalog = dbutils.widgets.get("catalog")  # type: ignore[name-defined]  # noqa: F821
batch_id = dbutils.widgets.get("batch_id")  # type: ignore[name-defined]  # noqa: F821
frames = review_report.run(spark, catalog, batch_id)  # type: ignore[name-defined]  # noqa: F821

# COMMAND ----------

# MAGIC %md
# MAGIC ## Totais e reconciliação

# COMMAND ----------

display(frames["ds_totals"])  # type: ignore[name-defined]  # noqa: F821

# COMMAND ----------

# MAGIC %md
# MAGIC ## Top 20 maiores linhas

# COMMAND ----------

display(frames["ds_top20"])  # type: ignore[name-defined]  # noqa: F821

# COMMAND ----------

# MAGIC %md
# MAGIC ## Flags

# COMMAND ----------

display(frames["ds_flag_counts"])  # type: ignore[name-defined]  # noqa: F821
display(frames["ds_flagged"])  # type: ignore[name-defined]  # noqa: F821

# COMMAND ----------

# MAGIC %md
# MAGIC ## Comparação com o mês anterior (último lote `locked`)

# COMMAND ----------

display(frames["ds_previous_totals"])  # type: ignore[name-defined]  # noqa: F821
display(frames["ds_previous_pos"])  # type: ignore[name-defined]  # noqa: F821
