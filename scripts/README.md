# scripts

Utilitários de build (referência IBGE, malhas geográficas). Não rodam em runtime.

## `setup_workspace.py` (P5.2)

Cria, de forma idempotente, o catálogo, os schemas (ADR-0003), o Volume `raw.landing` e os
grupos `atlas_readers`, `atlas_commission_analysts` e `atlas_commission_directors`. Quem roda
é o mantenedor; use `--dry-run` primeiro:

```bash
uv run python scripts/setup_workspace.py --target dev --profile <perfil> --dry-run
uv run python scripts/setup_workspace.py --target dev --profile <perfil>
```

`dev` usa o catálogo `atlas_dev` e `demo` usa `atlas`, como no `databricks.yml`. Desde a P7.3 ele também
aplica os grants de `atlas_readers`: `USE CATALOG` e `USE SCHEMA` + `SELECT` só em `semantic`. Os
grants de `commission` ficam para a SPEC-003.

## `check_readers_permissions.py` (P7.3)

Roda com o perfil de um usuário que está **só** em `atlas_readers`. Confere que o `SELECT` em
`semantic.mv_recharges` funciona e que `gold`, `silver`, `bronze` e `commission` dão
`PERMISSION_DENIED` (SPEC-004 §8, critério 4):

```bash
uv run python scripts/check_readers_permissions.py --target dev --profile <perfil-do-leitor> --warehouse-id <id>
```
