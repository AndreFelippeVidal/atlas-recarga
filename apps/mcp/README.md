# apps/mcp

Databricks App `atlas-mcp` (FastMCP, Streamable HTTP em `/mcp`). Governado pela
[SPEC-006](../../docs/specs/006-mcp-server/spec.md) e pelo [ADR-0008](../../docs/adr/0008-fastmcp-on-databricks-apps.md).

**Estado (P11.4):** `health()`, `list_metrics()`, `query_metric(...)`, `top_regions(...)` e
`compare_months(...)`, com os erros padronizados do §4, rate limit por usuário, traces MLflow e
logs estruturados (SPEC-006 §6).

- **Rate limit:** 30 chamadas de tool por minuto por usuário (`x-forwarded-email`), em memória, antes
  de qualquer query. A 31ª recebe `RATE_LIMITED: ... retry_after_s=<s> request_id=<uuid>` e nenhuma
  query roda. Vale por instância e zera num restart. Sem os cabeçalhos do proxy, todas as chamadas
  caem no usuário `unknown` e dividem um único balde.
- **Traces:** cada chamada abre um span manual (`mlflow.start_span`) no experiment
  `/Shared/atlas/mcp` com **só atributos** (`request_id`, `user`, `tool`, `app_version`,
  `sql_fingerprint`, `rows`, `error_code`, `duration_ms`); nunca `@mlflow.trace`, então nenhum valor
  de resultado vai ao trace. Sem `MLFLOW_EXPERIMENT_ID` ou sem MLflow, o span vira no-op e a tool
  continua.
- **Auditoria:** o SQL das tools de consulta começa com `/* atlas-mcp request_id=<uuid> */`, o mesmo
  `request_id` do trace, visível na `system.query.history`. O `compare_months` roda 2 queries (um
  mês cada) com o mesmo `request_id`: uma chamada pode ter 2 linhas na history.
- **Logs:** uma linha JSON por chamada no stdout (`tool`, `user`, `duration_ms`, `rows`,
  `sql_fingerprint`, `error_code`, `request_id`).

- `query_metric` valida view, medidas, dimensões e chaves de `filters` contra uma **lista fechada**
  (`atlas_mcp/catalog.json`) e vincula todo valor (filtros e meses) como parâmetro; nenhum SQL livre.
  Erro de argumento: `INVALID_ARGUMENT`, sem executar query.
- `top_regions` e `compare_months` só leem `mv_recharges`; `level` ∈ `region`, `uf`, `municipality`
  (código + nome) e `ddd`. `compare_months` devolve `value_a`, `value_b`, `delta_abs` (b − a) e
  `delta_pct` (nulo se a base é 0).
- Erros chegam como `CODIGO: mensagem`, sem stack trace: `INVALID_ARGUMENT`, `PERMISSION_DENIED`,
  `WAREHOUSE_UNAVAILABLE` (depois de 1 nova tentativa em 20s) e `RESULT_TOO_LARGE` (> 500 linhas).
- `month_from`/`month_to` (`YYYY-MM`, inclusivos) filtram `recharge_month` (`mv_recharges`) ou
  `reference_month` (`mv_commission`). `order_by`: coluna do resultado com `asc`/`desc` opcional.
- Os dados são lidos **como o usuário** (OBO, escopo `sql`, cabeçalho `x-forwarded-access-token`).
  Dentro do App, sem o token, a chamada falha (não cai no service principal). A credencial padrão
  do SDK só vale fora do App (dev local).
- `catalog.json` é gerado de `semantic/*.yaml`; depois de mudar uma metric view:
  `uv run python scripts/build_mcp_catalog.py` (um teste falha se ficar velho).

## Rodar local

```bash
uv sync
DATABRICKS_APP_PORT=8000 uv run atlas-mcp   # http://localhost:8000/mcp
uv run pytest apps/mcp/tests
```

Sem `DATABRICKS_WAREHOUSE_ID` (ou sem credencial), `health` devolve `warehouse: UNKNOWN` ou
`UNREACHABLE`; o servidor continua `healthy`.

## Deploy e conferência (mantenedor)

```bash
databricks bundle deploy -t dev --profile andrevidal
databricks bundle run atlas_mcp -t dev --profile andrevidal
uv run python scripts/check_mcp_health.py --profile andrevidal
uv run python scripts/check_mcp_query.py --profile andrevidal --month 2026-10   # P11.2
```

### P11.4: traces, rate limit e paridade (mantenedor)

```bash
databricks bundle deploy -t dev --profile andrevidal      # experiment, CAN_EDIT do App, dashboard
databricks bundle run atlas_mcp -t dev --profile andrevidal
# Trace tables mcp_* + GRANTs mínimos + view mcp_usage_daily (uma vez por target; sem --apply só mostra)
uv run --project apps/mcp python scripts/setup_mcp_trace_tables.py --profile andrevidal \
    --catalog atlas_dev --warehouse-id <id> --experiment-id <id do atlas_mcp_traces> \
    --app-sp <client_id do atlas-mcp> --apply
uv run python scripts/check_mcp_parity.py --profile andrevidal --warehouse-id <id> --catalog atlas_dev
uv run --project apps/mcp python scripts/check_mcp_observability.py --profile andrevidal \
    --warehouse-id <id> --experiment-id <id do atlas_mcp_traces>   # --mode service-principal no plano B
```

O dashboard "Atlas — Uso do MCP" lê `observability.mcp_usage_daily`. Depois de reiniciar o App,
espere 1 minuto antes de repetir o `check_mcp_observability.py` (o limite é por usuário).

O service principal do App só consulta o estado do warehouse (`CAN_USE`); as consultas de dados
rodam com o `SELECT` do próprio usuário em `atlas.semantic`.

## Conectar ao Claude Code (P11.5)

Guia completo, com o motivo de o OAuth interativo não funcionar, os cuidados com o token e a
evidência: [docs/mcp-claude-code.md](../../docs/mcp-claude-code.md). Resumo:

```bash
claude mcp add --transport http atlas https://<atlas-mcp-app-host>/mcp \
  --header "Authorization: Bearer $DATABRICKS_USER_TOKEN"   # token de curta duração, só na sessão
```

O token nunca vai para o repositório. A consulta roda como o usuário (OBO).
