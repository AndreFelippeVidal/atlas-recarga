# scripts

Utilitários de build (referência IBGE, malhas geográficas). Não rodam em runtime.

## `setup_workspace.py` (P5.2)

Cria, de forma idempotente, o catálogo, os schemas (ADR-0003), o Volume `raw.landing` e os
grupos `atlas_readers`, `atlas_commission_analysts` e `atlas_commission_directors`. Quem roda
é o mantenedor; use `--dry-run` primeiro:

```bash
uv run python scripts/setup_workspace.py --target dev --profile andrevidal --dry-run
uv run python scripts/setup_workspace.py --target dev --profile andrevidal
```

`dev` usa o catálogo `atlas_dev` e `demo` usa `atlas`, como no `databricks.yml`. Os grants ficam
para a P7.3 e a SPEC-003.
