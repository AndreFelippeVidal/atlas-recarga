# scripts

Utilitários de build (referência IBGE, malhas geográficas). Não rodam em runtime.

## `setup_workspace.py` (P5.2)

Bootstrap idempotente do que o bundle não declara (ADR-0017): o catálogo, os grupos `atlas_readers`,
`atlas_commission_analysts` e `atlas_commission_directors`, os membros e `USE CATALOG`. Os schemas
(ADR-0003), o Volume `raw.landing` e os grants em `semantic` vêm do `databricks.yml`: rode este
script **antes** do primeiro `bundle deploy`. Quem roda é o mantenedor; use `--dry-run` primeiro:

```bash
uv run python scripts/setup_workspace.py --target dev --profile <perfil> --dry-run
uv run python scripts/setup_workspace.py --target dev --profile <perfil>
```

`dev` usa o catálogo `atlas_dev` e `demo` usa `atlas`, como no `databricks.yml`. O grupo de workspace
não vale no UC (ADR-0016), então `--reader <principal>` (repetível) dá `USE CATALOG` a cada leitor.
`USE SCHEMA`, `SELECT` e `EXECUTE` em `semantic` são a variável `semantic_grants` do bundle: o padrão
cobre `atlas_readers` e os service principals dos Apps; leitores por principal vão em
`databricks.local.yml` (modelo em `databricks.example-local.yml`). Os grants do bundle são
autoritativos no schema `semantic`: quem não está na lista perde o acesso no deploy.

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

## `check_agent_functions.py` (P10.1)

Confere as UC functions do agente: `fn_metric_by_region` igual a `MEASURE()` direto na
`mv_recharges` (7 medidas x 4 níveis), `fn_compare_months` igual à diferença das consultas diretas,
`fn_list_metrics` com as 7 medidas e 10 dimensões, e `INVALID_MEASURE`/`INVALID_LEVEL` para
valores fora da lista. Só lê.

```bash
uv run python scripts/check_agent_functions.py --target dev --profile <perfil> --warehouse-id <id> \
    --month 2026-10-01 --previous-month 2026-09-01
```

## `check_golden_set.py` (P9.1)

Roda cada `reference_sql` de `eval/golden_set.yaml` no workspace e confere que devolve 1 valor
numérico. Só lê.

```bash
uv run python scripts/check_golden_set.py --target dev --profile <perfil> --warehouse-id <id>
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

## `fetch_geo.py` (P12.1)

Baixa as malhas do IBGE (API v3, qualidade `maxima`), simplifica com `mapshaper` (versão fixa, via
`npx`; precisa de Node) e grava TopoJSON em `apps/web/public/geo/`: `br-uf.json` (27 UFs, com `uf`
e `region`) e `mun/<UF>.json` (municípios, com `municipality_ibge_code`). Quem roda é o mantenedor,
uma vez (ou quando a malha mudar); o resultado é versionado e o script nunca roda em runtime
(ADR-0004). `region` e o conjunto de municípios vêm de `data/reference/municipalities_ibge.csv`,
a mesma referência da `gold.dim_municipality`; o polígono de Boa Esperança do Norte (MT), que não
está na referência, é descartado, e um município da referência sem polígono é erro:

```bash
uv run python scripts/fetch_geo.py
```

O `tests/test_geo_files.py` confere, sem rede, os limites de tamanho da SPEC-007 §2 e o match de
100% entre as malhas e a referência (5.570 municípios).

## `spike_dashboard_latency.py` e `spike_lakebase_read.py` (P12.10)

Medem a latência do `atlas-web` (por endpoint, com cache e warehouse frios e quentes), testam um
agregado derivado de `mv_recharges` e a leitura de uma synced table do Lakebase. Quem roda é o
mantenedor, no `dev`; o roteiro e as tabelas de resultado estão em
[docs/spikes/P12.10-dashboard-latency.md](../docs/spikes/P12.10-dashboard-latency.md).

## `measure_web_p95.py` (P12.8)

Mede o p95 dos municípios de uma UF no App `atlas-web` implantado (SPEC-007 §6): uma chamada fria por
UF e medida, logo depois do deploy ou do `apps start`. Quem roda é o mantenedor, no `dev`; o roteiro
está em [apps/web/README.md](../apps/web/README.md). Sai com 0 se o p95 < 3 s.

## `apps_start.py` (P13.1)

Religa os 3 Apps (`agent-atlas`, `atlas-mcp`, `atlas-web`) depois do auto-stop de 24 h e espera os
healthchecks. Use pelo `make apps-start PROFILE=<perfil>`; o roteiro e os sintomas estão no
[README da raiz](../README.md#runbook-de-demo-religar-os-3-apps). O `PROFILE` é obrigatório (não há
perfil padrão). Não faz deploy. Sai com 0 se os 3 Apps estão de pé.
