# SPEC-006 — MCP server (`atlas-mcp`, FastMCP)

> PRD: F7 · ADRs: [0008](../../adr/0008-fastmcp-on-databricks-apps.md), [0009](../../adr/0009-three-apps-allocation.md) · Status: rascunho

## 1. Objetivo
Expor a camada semântica do Atlas como **MCP server somente leitura**, para que a Helena (ou qualquer cliente MCP, como Claude Code ou Claude Desktop) consulte os dados de onde já trabalha, com a mesma definição de métrica do dashboard e do agente.

## 2. Runtime
- **FastMCP** (Python), transporte **Streamable HTTP**, escutando em `0.0.0.0:$DATABRICKS_APP_PORT` (padrão 8000), path `/mcp`.
- Hospedado como Databricks App `atlas-mcp` (`app.yaml`: `command: ['uv', 'run', 'atlas-mcp']`).
- URL do cliente: `https://<atlas-mcp-app-host>/mcp`.
- Acesso a dados: `databricks-sql-connector` → SQL warehouse 2X-Small → `atlas.semantic.*`.
- **Autorização:** *on-behalf-of-user* (o token do usuário do App), para que as permissões do UC do próprio usuário sejam aplicadas. Se isso não estiver disponível, usa o service principal do App restrito a `SELECT` em `semantic` (ADR-0008).

> Limitação documentada: hoje o Unity Gateway **não permite registrar um MCP hospedado em Databricks Apps como MCP Service do UC** (doc *Register an MCP service*, Limitations); o cliente conecta direto ao App. O rate limit e a auditoria que o gateway daria são feitos no próprio App (§6). Ver ADR-0008.

## 3. Tools

Todas são somente leitura e todas montam SQL **parametrizado** a partir de listas fechadas. Nenhuma aceita SQL livre.

| Tool | Parâmetros | Retorno |
|---|---|---|
| `health()` | — | `{"status": "healthy", "warehouse": "<state>", "version": "<semver>"}` |
| `list_metrics()` | — | Medidas e dimensões de `mv_recharges` e `mv_commission` com a descrição oficial |
| `query_metric(view, measures[], dimensions[], filters{}, month_from, month_to, order_by?, limit=50)` | `view ∈ {mv_recharges, mv_commission}`; `measures` e `dimensions` ⊂ a lista da view; `filters` com chaves ⊂ `dimensions` e valores escalares ou listas; `limit ≤ 500` | `{"columns": [...], "rows": [...], "source": {...}, "sql_fingerprint": "<sha1>"}` |
| `top_regions(measure, level, month, n=10, uf?)` | `level ∈ {region, uf, municipality, ddd}`; `n ≤ 50` | Ranking + `source` |
| `compare_months(measure, month_a, month_b, level, uf?)` | igual | Valores, Δ absoluto, Δ% + `source` |

O campo `source` de toda resposta repete o contrato de citação do agente (view, medidas, filtros, período).

## 4. Erros (padronizados, nunca stack trace)

| Código | Quando |
|---|---|
| `INVALID_ARGUMENT` | Medida, dimensão ou filtro fora da lista fechada; `limit` acima do máximo; mês inválido |
| `PERMISSION_DENIED` | O usuário não tem `SELECT` na metric view |
| `WAREHOUSE_UNAVAILABLE` | Warehouse parado ou em timeout depois de 1 nova tentativa (20s) |
| `RESULT_TOO_LARGE` | Mais de 500 linhas: sugere agregar mais ou filtrar |
| `RATE_LIMITED` | Mais de 30 chamadas de tool por minuto do mesmo usuário; a resposta traz `retry_after_s` e nenhuma query é executada |

## 5. Conexão (documentada no README)
- **Claude Code:** `claude mcp add --transport http atlas https://<atlas-mcp-app-host>/mcp`, com autenticação OAuth do Databricks App, a ser confirmada no Spike S0.5.
- **Plano B (S0.5 falhar):** proxy local `mcp-remote` com o header `Authorization: Bearer $(databricks auth token ...)`. O token nunca vai para o repositório.

## 6. Observabilidade e controle (no lugar do Unity Gateway)

O MCP não chama LLM, então os controles de tokens e de PII na saída do gateway não se aplicam a ele. O que o gateway daria e faz falta é **auditoria central** e **rate limit**. Os dois são feitos no App:

| O gateway daria | No `atlas-mcp` |
|---|---|
| Registro de uso em `system.ai_gateway.usage` | **MLflow traces:** cada tool decorada com `@mlflow.trace`, no experiment `/Shared/atlas/mcp`, com as tags `user`, `tool`, `app_version`, `sql_fingerprint`, `rows`, `error_code`. Sem os valores dos resultados |
| Auditoria de acesso a dados | **`system.query.history`:** toda tool vira SQL no warehouse. Com on-behalf-of-user, `executed_by` é o usuário real. No plano B (service principal), o usuário fica só no trace |
| Rate limit por usuário | Limitador em memória de **30 chamadas por minuto por usuário** (o mesmo teto do agente), antes de qualquer query. Erro `RATE_LIMITED` (§4) |
| Painel de uso | Página "Uso do MCP" no AI/BI Dashboard: chamadas, erros por código e latência p95 por tool e por dia, a partir dos traces |

Os logs JSON no stdout do App continuam (`tool`, `user`, `duration_ms`, `rows`, `sql_fingerprint`, `error_code`), para depuração.

**Limitações aceitas:** o limitador vale por instância do App e zera num restart (o App tem uma instância na Free Edition); não há teto de gasto, porque o custo do MCP é o do warehouse, e o 2X-Small já é o teto natural.

## 7. Critérios de aceite
- **Dado** um cliente MCP conectado, **quando** chamo `health`, **então** recebo `status: healthy`.
- **Dado** `query_metric(view='mv_recharges', measures=['gross_revenue'], dimensions=['uf'], month_from='2026-10', month_to='2026-10')`, **então** os valores batem ao centavo com o AI/BI Dashboard.
- **Dado** `measures=['DROP TABLE x']` ou uma dimensão inexistente, **então** recebo `INVALID_ARGUMENT` e nenhuma query é executada.
- **Dado** um `filters` com um valor contendo aspas ou `;`, **então** o valor é passado como parâmetro vinculado, sem concatenação (teste de injeção).
- **Dado** o service principal do App, **então** ele não tem permissão fora de `atlas.semantic`.
- **Dado** o golden set, **quando** reformulado via `query_metric`, **então** os números são iguais aos do SQL de referência (reaproveita a SPEC-008).
- **Dado** 31 chamadas de tool do mesmo usuário em 60s, **então** a 31ª recebe `RATE_LIMITED` e não aparece em `system.query.history`.
- **Dado** qualquer chamada de tool, **então** existe um trace em `/Shared/atlas/mcp` com as tags do §6 e sem valores de resultado.
- **Dado** o modo on-behalf-of-user, **então** a query da tool aparece em `system.query.history` com `executed_by` igual ao usuário do cliente MCP.

## 8. Fora de escopo
Tools de escrita (nunca), registro como MCP Service no Unity Gateway (bloqueado pela plataforma hoje; revisar no ADR-0008), resources e prompts MCP (v2).
