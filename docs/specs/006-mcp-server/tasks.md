# Tasks — 006-mcp-server

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 11 — MCP server

### P11.1 🤖 Esqueleto FastMCP no App `atlas-mcp` com `health`

- **Depende de:** P3.8
- **Pronto quando:** Critério 1 da SPEC-006 §7

### P11.2 🤖 `list_metrics` + `query_metric` com validação por lista fechada e parâmetros vinculados

- **Depende de:** P11.1, P7.1
- **Pronto quando:** Critérios 3 e 4 (injeção) da SPEC-006 §7

### P11.3 🤖 `top_regions` + `compare_months` + erros padronizados

- **Depende de:** P11.2
- **Pronto quando:** Contrato de erros da SPEC-006 §4 coberto (os 4 códigos que não dependem do limitador; o `RATE_LIMITED` é da P11.4)
- **Passos:**
  - `errors.py` com `INVALID_ARGUMENT`, `PERMISSION_DENIED`, `WAREHOUSE_UNAVAILABLE` e `RESULT_TOO_LARGE`; nunca stack trace ao cliente; aplicado também ao `query_metric`
  - `sql_client.py` classifica as falhas do warehouse nesses códigos; `WAREHOUSE_UNAVAILABLE` só depois de 1 nova tentativa (20s)
  - `top_regions` e `compare_months` só sobre `mv_recharges`, reaproveitando `build_query` (lista fechada, binds); `level` mapeia para `region`, `uf`, `municipality_ibge_code` + `municipality_name` e `ddd`
  - `compare_months` com Δ absoluto e Δ% (nulo se a base é 0) e `RESULT_TOO_LARGE` acima de 500 linhas
  - Testes unitários com o cliente SQL mockado e `scripts/check_mcp_tools.py` para o mantenedor conferir no `dev`

### P11.4 🤖 Traces MLflow, rate limit por usuário, logs estruturados + teste de paridade com o golden set

- **Depende de:** P11.3, P9.1, P3.5
- **Pronto quando:** Critérios 6 a 10 da SPEC-006 §7 (o 9 na forma do plano B, se o S0.5 cair nele)
- **Passos:**
  - Span manual `mlflow.start_span` por tool, só com atributos (nunca `@mlflow.trace`), experiment `/Shared/atlas/mcp`
  - Comentário `request_id` no SQL das tools que consultam o warehouse
  - Limitador de 30 chamadas/min por usuário antes da query, com `RATE_LIMITED`
  - Página "Uso do MCP" no AI/BI sobre `atlas.observability.mcp_*`

### P11.5 🤝 Conectar ao Claude Code/Desktop e documentar no README

- **Ordem:** executada no fim da Fase 12 (depois da P12.9, antes da Fase 13); o agente prepara a integração e o mantenedor executa.
- **Depende de:** P11.4, P12.8
- **Pronto quando:** Você pergunta no Claude e recebe a resposta com `source`
