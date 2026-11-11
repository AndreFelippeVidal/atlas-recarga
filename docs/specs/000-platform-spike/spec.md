# SPEC-000 — Spike S0: validações de plataforma na Free Edition

> Roadmap: Fase 3 · ADRs: [0005](../../adr/0005-metric-views-semantic-layer.md), [0007](../../adr/0007-unity-gateway-llm-governance.md), [0008](../../adr/0008-fastmcp-on-databricks-apps.md), [0010](../../adr/0010-commission-human-in-the-loop.md), [0013](../../adr/0013-mlflow-genai-evaluation-monitoring.md) · Status: rascunho

## 1. Objetivo
Confirmar **no workspace real** os recursos que a documentação mostra existir mas que podem não estar disponíveis (ou estar em Beta) na Free Edition, **antes** de implementar algo que dependa deles. Cada item termina em `passou` ou `falhou → plano B`, e o ADR correspondente é atualizado.

## 2. Itens

| # | Validar | Como (passo mínimo) | Passou se | Se falhar | ADR |
|---|---|---|---|---|---|
| S0.1 | Unity Gateway beta e model service Claude `system.ai.*` | Habilitar em *Previews*; chamar o model service com `ChatDatabricks(use_ai_gateway=True)` num notebook | Resposta 200 e linha em `system.ai_gateway.usage` | AI Gateway clássico num endpoint pay-per-token | 0007 |
| S0.2 | Agent service (Beta) | Registrar um agente "hello" deployado como App | O agente aparece no Unity Gateway com uso registrado | Governar só o LLM; o agente fica como App direto | 0007 |
| S0.3 | Production monitoring MLflow 3 (Beta) | Agendar um scorer de código num experiment com 5 traces sintéticos | Feedback anexado aos traces | Job diário com `search_traces` + `evaluate` | 0013 |
| S0.4 | Metric views + Genie | Criar uma metric view mínima sobre `samples` e um Genie Space em cima dela | `MEASURE()` funciona e o Genie responde usando a view | Views SQL + Genie sobre o gold | 0005 |
| S0.5 | OAuth de cliente externo num App MCP | Deploy do template MCP "health" e `claude mcp add --transport http` | O tool `health` responde a partir do Claude Code; uma query do App aparece em `system.query.history` com `executed_by` = usuário (on-behalf-of-user) | Proxy `mcp-remote` com token do `databricks auth`; sem OBO, a auditoria por usuário fica só no trace (SPEC-006 §6) | 0008 |
| S0.6 | Mais de um usuário no workspace | Tentar convidar um segundo usuário | O segundo usuário entra e recebe um grupo | Modo `ALLOW_SAME_APPROVER_DEMO` | 0010 |
| S0.7 | Cotas práticas | Rodar o CLI com 2M de linhas e um pipeline mínimo | Termina sem erro de cota em < 30 min | Reduzir o `--rows` padrão e registrar no PRD | 0001 |

## 3. Saída
- `docs/spikes/S0-results.md`: um bloco por item com data, resultado, evidência (print, query ou trace id) e decisão.
- Cada ADR afetado atualizado para `aceito` ou `aceito com plano B`.
- Nenhum código de spike vai para a `main`, exceto notebooks em `spikes/` marcados como descartáveis.

## 4. Critérios de aceite
- **Dado** o fim da Fase 3, **então** todos os itens S0.1 a S0.7 têm um resultado registrado e os ADRs 0001, 0005, 0007, 0008, 0010 e 0013 têm o status atualizado.
- **Dado** um item que falhou, **então** a spec afetada (005, 006, 008 ou 003) foi ajustada por PR antes de começar a fase que a implementa.
