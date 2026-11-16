# Tasks — 005-business-agent

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 10 — Agente de negócio

### P10.1 🤖 UC functions `fn_list_metrics`, `fn_metric_by_region`, `fn_compare_months`

- **Depende de:** P7.1
- **Pronto quando:** Retornos batem com as metric views; `measure` inválido gera erro

### P10.2 🤖 Esqueleto do App `atlas-agent` a partir do template oficial, LLM via Unity Gateway

- **Depende de:** P3.8
- **Pronto quando:** Responde "olá"; o trace aparece no experiment; uso em `system.ai_gateway.usage`
- **Passos:**
  - `ATLAS_GATEWAY_MODE` conforme o resultado do S0.1

### P10.3 🤖 Tools: `ask_genie` + UC functions (lista fechada)

- **Depende de:** P10.1, P10.2
- **Pronto quando:** Uma pergunta simples do golden set acerta
- **Passos:**
  - Validar o que a SPEC-005 §5 deixou pendente: `request_tags` na chamada ao LLM (ligar `ATLAS_LLM_REQUEST_TAGS=1` e conferir a coluna `request_tags` da `usage`; se o formato do `extra_params` for inválido, corrigir ou remover o opt-in), `ask_genie` aparecer como `MCP_SERVICE` na `usage` e o span de cada tool chegar ao experiment a partir do App

### P10.4 🤖 System prompt: citação `Fonte:`, recusa, último mês fechado, PT-BR

- **Depende de:** P10.3
- **Pronto quando:** Os casos de recusa do golden set passam
- **Passos:**
  - Versionar em `apps/agent/prompts/` com `prompt_version`

### P10.5 🤝 Rate limit, spend cap e guardrails no gateway + trace tables em `atlas.observability`

- **Depende de:** P10.2
- **Pronto quando:** 429 testado; política de PII ativa
- **Passos:**
  - Na P10.2 um turno chegou a 143.841 tokens (65.285 de saída; histórico reenviado mais raciocínio do `gpt-oss-120b`): dimensionar o spend cap com isso e avaliar limitar `max_tokens` e o histórico enviado

### P10.6 🤖 Avaliação offline completa: acurácia ≥ 90%

- **Depende de:** P9.3, P10.4
- **Pronto quando:** Run do MLflow linkado no PR
- **Passos:**
  - Iterar no prompt e nas descrições das metric views

### P10.7 🤖 Gate de CI `agent-eval.yml` com path filter + comentário no PR

- **Depende de:** P10.6
- **Pronto quando:** Critérios 2 e 3 da SPEC-008 §7

### P10.8 🤝 Production monitoring (ou o plano B) + página "Qualidade do agente" + alerta

- **Depende de:** P10.6
- **Pronto quando:** Critérios 5 e 6 da SPEC-008 §7
