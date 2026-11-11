# Tasks — 008-agent-evaluation

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 9 — Avaliação do agente: golden set antes do agente

### P9.1 🤖 `eval/golden_set.yaml` com ~30 casos (20 métricas, 5 comparativos, 5 recusas)

- **Depende de:** P7.5, P8.11
- **Pronto quando:** Toda `reference_sql` executa e retorna 1 valor

### P9.2 🤖 Sync do golden set para `atlas.eval.agent_golden_set` (dataset MLflow)

- **Depende de:** P9.1
- **Pronto quando:** O dataset aparece no UC com versão

### P9.3 🤖 Scorers de código (`numeric_match`, `cites_metric_view`, `read_only_tools`, `no_tool_on_refusal`) + testes unitários com traces fake

- **Depende de:** P9.1
- **Pronto quando:** Cobertura ≥ 90% nos scorers
