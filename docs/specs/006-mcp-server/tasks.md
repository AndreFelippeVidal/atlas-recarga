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
- **Pronto quando:** Contrato de erros da SPEC-006 §4 coberto

### P11.4 🤖 Traces MLflow, rate limit por usuário, logs estruturados + teste de paridade com o golden set

- **Depende de:** P11.3, P9.1
- **Pronto quando:** Critérios 6 a 9 da SPEC-006 §7
- **Passos:**
  - `@mlflow.trace` em cada tool, experiment `/Shared/atlas/mcp`, tags do §6
  - Limitador de 30 chamadas/min por usuário antes da query, com `RATE_LIMITED`
  - Página "Uso do MCP" no AI/BI (traces + `system.query.history`)

### P11.5 👤 Conectar ao Claude Code/Desktop e documentar no README

- **Depende de:** P11.4
- **Pronto quando:** Você pergunta no Claude e recebe a resposta com `source`
