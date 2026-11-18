# apps/mcp

Databricks App `atlas-mcp` (FastMCP, Streamable HTTP em `/mcp`). Governado pela
[SPEC-006](../../docs/specs/006-mcp-server/spec.md) e pelo [ADR-0008](../../docs/adr/0008-fastmcp-on-databricks-apps.md).

**Estado (P11.2):** `health()`, `list_metrics()` e `query_metric(...)`. `top_regions` e
`compare_months` entram na P11.3; observabilidade e rate limit na P11.4.

- `query_metric` valida view, medidas, dimensões e chaves de `filters` contra uma **lista fechada**
  (`atlas_mcp/catalog.json`) e vincula todo valor (filtros e meses) como parâmetro; nenhum SQL livre.
  Erro de argumento: `INVALID_ARGUMENT`, sem executar query. O contrato completo de erros é da P11.3.
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

O service principal do App só consulta o estado do warehouse (`CAN_USE`); as consultas de dados
rodam com o `SELECT` do próprio usuário em `atlas.semantic`.
