# apps/mcp

Databricks App `atlas-mcp` (FastMCP, Streamable HTTP em `/mcp`). Governado pela
[SPEC-006](../../docs/specs/006-mcp-server/spec.md) e pelo [ADR-0008](../../docs/adr/0008-fastmcp-on-databricks-apps.md).

**Estado (P11.1):** só a tool `health()` (`status`, estado do SQL warehouse e versão). As tools de
dados entram nas P11.2 e P11.3; observabilidade e rate limit na P11.4.

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
```

O App só consulta o estado do warehouse (`CAN_USE`); o acesso a `atlas.semantic` vem com a P11.2.
