# Resultados do Spike S0

> [SPEC-000](../specs/000-platform-spike/spec.md) §3. Um bloco por item, com data, resultado, evidência e decisão.
> Resultados **não** são preenchidos pelo agente: quem roda no workspace registra.

## S0.1 — Unity Gateway + model service Claude

- **Data:** 2026-11-11
- **ADR:** [0007](../adr/0007-unity-gateway-llm-governance.md)
- **Notebook:** `spikes/s0_1_unity_gateway.py` (descartável)

### Observações do workspace (2026-11-11, antes de rodar)

- Unity Gateway visível, com as abas Models, Providers, MCPs, Skills e Agents.
- **Models** (`system.ai`): `qwen35-122b-a10b`, `gpt-oss-20b`, `gpt-oss-120b`, `meta-llama-3-3-70b…`, `meta-llama-3-1-8b-i…`, `qwen3-next-80b-a3…`, `llama-4-maverick`, `gemma-3-12b`; embeddings `gte-large-en`, `bge-large-en`, `qwen3-embedding-…`; e `databricks-genie` (escopo Workspace). **Nenhum modelo Claude listado.**
- **MCPs** (`system.ai`): `genie_one_mcp` e `dbsql` (Beta) ativos; `atlassian`, `github` e `gmail` com "Action needed".
- Evidências: capturas de tela das abas Models e MCPs, guardadas pelo mantenedor (não versionadas); a lista acima as transcreve.

### Execução do notebook (2026-11-11)

- A 1ª tentativa com o nome curto `gpt-oss-120b` deu `403 PERMISSION_DENIED`: "is no longer available. Use Unity Catalog model services". O nome curto cai no endpoint legado; o model service é endereçado por **três partes** (`system.ai.<nome>`).
- `ChatDatabricks(model="system.ai.gpt-oss-120b", use_ai_gateway=True)` respondeu `ok`.
- A tentativa Claude falhou com `404 ENDPOINT_NOT_FOUND`. O notebook usa `system.ai.claude-sonnet-4-5`; a `usage` registrou o destino como `system.ai.databricks-claude-sonnet-4-5`. Em ambos os casos o endpoint não existe.
- `system.ai_gateway.usage` existe e registra chamadas a model services (`MODEL_SERVICE`, `PAY_PER_TOKEN_FOUNDATION_MODEL`, `status_code`, tokens, `requester_type`, `api_type`). A 1ª leitura (ordenada por `account_id`) não mostrou a execução de hoje e a linha só apareceu minutos depois, filtrando por `event_time`; ver a tabela abaixo.
- Pelo `model_metadata`, cada model service tem `rate_limits` e `service_policies` configuráveis (vazios por padrão).
- Não colar e-mail ou IP do solicitante nas evidências.

### Evidência na `system.ai_gateway.usage` (2026-11-11, UTC)

| event_time | destination_name | status_code | input_tokens | output_tokens | requester_type | api_type |
|---|---|---|---|---|---|---|
| 19:55:06 | `system.ai.gpt-oss-120b` | 200 | 107 | 24 | USER | `mlflow/v1/chat/completions` |
| 19:55:11 | `system.ai.databricks-claude-sonnet-4-5` | 404 | null | null | USER | `mlflow/v1/chat/completions` |

A tabela registra também a tentativa que falhou (404). A linha aparece com atraso (minutos), então qualquer dashboard de uso deve tolerar isso.

### Checklist

| Verificação | Resultado | Evidência |
|---|---|---|
| Há um model service Claude em `system.ai`? | ❌ não: aba Models sem Claude; tentativa Claude → 404 | capturas da aba Models; tabela de uso |
| Chamada via `ChatDatabricks(use_ai_gateway=True)` retorna 200 | ✅ com `system.ai.gpt-oss-120b` | saída do notebook |
| Linha em `system.ai_gateway.usage` da chamada de hoje | ✅ sim, com atraso de alguns minutos na system table | tabela de evidência acima |

### Resultado

**Passou com ressalva:** o Unity Gateway funciona na Free Edition, mas **não há model service Claude** em `system.ai`.

### Decisão

Decisão do mantenedor (2026-11-11): manter o Unity Gateway com um modelo não-Claude, `ATLAS_LLM_SERVICE` provisório = `system.ai.gpt-oss-120b` (nome de três partes). O plano B (AI Gateway clássico) não foi acionado. Ajustes em SPEC-005 e SPEC-000 na P3.8; ADR-0007 atualizado.

## S0.2 — Agent service (Beta)

- **Data:** 2026-11-11
- **ADR:** [0007](../adr/0007-unity-gateway-llm-governance.md)
- **Notebook:** `spikes/s0_2_agent_service.py` e App `spikes/s0_2_hello_agent/` (descartáveis)

### Observações do workspace (antes de rodar)

- Tentativa 1: App `atlas-hello-agent` não apareceu na aba Agents. A UI agora se chama AI Gateway.
- Hipótese (docs): só Apps com nome `agent-*` entram na lista; agent services registrados por REST são só de agentes externos e sem invocação em runtime (Beta).
- Tentativa 2: App `agent-hello` **apareceu na aba Agents do AI Gateway** (o prefixo `agent-` é o que lista o App; o nome `atlas-hello-agent` não aparecia). Sem passo extra de registro.
- Na aba Agents, o agente leva à página do próprio App (Databricks Apps > Insights). As métricas são **do App** (viewers únicos, uptime, requests por minuto por status HTTP, latência, CPU, memória), não do agente nem do LLM; não há tokens, custo nem por chamada ao modelo.
- `POST /invocations` pelo notebook devolve a tela de Sign In (status 200): Apps exige OAuth de usuário.
- `databricks ai-gateway` (CLI v1.24.0) não tem operações de agent service.

### Execução

- Deploy do App `agent-hello` funcionou (recriado com o prefixo `agent-`).
- `POST /invocations` com token OAuth de usuário (terminal): resposta `{"output":"ok"}`.
- Registro como agent service: não houve passo de registro; o App aparece na aba Agents pelo prefixo. O registro por REST (agent service externo, sem invocação em runtime) não foi tentado.

### Evidência na `system.ai_gateway.usage` (UTC)

| event_time | destination_name | status_code | requester_type | api_type |
|---|---|---|---|---|
| _(preencher)_ | | | | |

### Checklist

| Verificação | Resultado | Evidência |
|---|---|---|
| O App hello responde em `/invocations` (OAuth) | ✅ `{"output":"ok"}` | saída do curl |
| O agente aparece no AI Gateway (aba Agents) | ✅ com o prefixo `agent-` | aba Agents |
| Uso do agente registrado no gateway | ⚠️ só métricas do App (Insights); uso do LLM: _(pendente da query)_ | captura do Insights |

### Resultado

_(passou | passou com ressalva | falhou → plano B)_

### Decisão

_(mantenedor)_
