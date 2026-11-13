# pipeline

Pipeline Lakeflow Spark Declarative Pipelines (bronze → silver → gold). Governado pela [SPEC-002](../docs/specs/002-medallion-pipeline/spec.md).

`freshness.py` não faz parte do pipeline: é a task 3 do job `atlas_daily` (frescor e qualidade em `observability.pipeline_freshness`).
