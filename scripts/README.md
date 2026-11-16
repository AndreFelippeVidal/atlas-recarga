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
aplica os grants de leitura (ADR-0016: o grupo de workspace não vale no UC, então use `--reader <principal>`, repetível): `USE CATALOG` e `USE SCHEMA` + `SELECT` só em `semantic`. Os
grants de `commission` ficam para a SPEC-003.

## `check_readers_permissions.py` (P7.3)

Roda com o perfil de um usuário que está **só** em `atlas_readers`. Confere que o `SELECT` em
`semantic.mv_recharges` funciona e que `gold`, `silver`, `bronze` e `commission` dão
`PERMISSION_DENIED` (SPEC-004 §8, critério 4):

```bash
uv run python scripts/check_readers_permissions.py --target dev --profile <perfil-do-leitor> --warehouse-id <id>
```

## `check_mv_commission.py` (P8.11)

Confere que `semantic.mv_commission` só tem lotes `locked` (rascunho nunca aparece) e que
`MEASURE(commission_total)` por mês bate ao centavo com `locked_lines`. Só lê.

```bash
uv run python scripts/check_mv_commission.py --target dev --profile <perfil> --warehouse-id <id>
```

## `check_commission_flags.py` (P8.5)

Depois do job `atlas_commission_draft` (que inclui a task `flag_draft`), confere os flags de `commission.batch_lines`: só os quatro da SPEC-003 §5, nenhum em linha de distribuidor, `closed_pos` igual aos PDVs fechados no mês e `fractioning_suspect` igual aos PDVs com rajada no mês do lote, por consulta independente (critério 3 da §8). Só leitura.

```bash
uv run python scripts/check_commission_flags.py --target dev --profile <perfil> --warehouse-id <id> --batch-id COM-2026-10-v1
```

## `check_commission_reconciliation.py` (P8.4)

Depois do job `atlas_commission_draft` (que inclui a task `reconcile_draft`), confere `commission.reconciliation`: uma linha do lote com `status = 'passed'`, todas as diferenças em 0.00 e as linhas comparadas iguais às de `batch_lines` (SPEC-003 §5 e §8, critério 1). Só leitura.

```bash
uv run python scripts/check_commission_reconciliation.py --target dev --profile <perfil> --warehouse-id <id> --batch-id COM-2026-10-v1
```

## `check_commission_draft.py` (P8.3)

Depois de rodar o job `atlas_commission_draft`, confere o rascunho `COM-YYYY-MM-v1` (SPEC-003 §2 a §4): status `draft`, totais iguais à soma das linhas, base dos PDVs igual ao volume aprovado do mês no gold, faixa e taxa coerentes e o evento inicial em `batch_events`. Só leitura; a reconciliação independente é a P8.4.

```bash
uv run python scripts/check_commission_draft.py --target dev --profile <perfil> --warehouse-id <id> --batch-id COM-2026-10-v1
```
