# Resultados do Spike S0

> [SPEC-000](../specs/000-platform-spike/spec.md) §3. Um bloco por item, com data, resultado, evidência e decisão.
> Resultados **não** são preenchidos pelo agente: quem roda no workspace registra.

## S0.1 — Unity Gateway + model service Claude

- **Data:** _(preencher)_
- **ADR:** [0007](../adr/0007-unity-gateway-llm-governance.md)
- **Notebook:** `spikes/s0_1_unity_gateway.py` (descartável)

### Observações do workspace (2026-11-11, antes de rodar)

- Unity Gateway visível, com as abas Models, Providers, MCPs, Skills e Agents.
- **Models** (`system.ai`): `qwen35-122b-a10b`, `gpt-oss-20b`, `gpt-oss-120b`, `meta-llama-3-3-70b…`, `meta-llama-3-1-8b-i…`, `qwen3-next-80b-a3…`, `llama-4-maverick`, `gemma-3-12b`; embeddings `gte-large-en`, `bge-large-en`, `qwen3-embedding-…`; e `databricks-genie` (escopo Workspace). **Nenhum modelo Claude listado.**
- **MCPs** (`system.ai`): `genie_one_mcp` e `dbsql` (Beta) ativos; `atlassian`, `github` e `gmail` com "Action needed".
- Evidências: _(anexar os 2 prints da aba Models e o da aba MCPs)_

### Execução do notebook (2026-11-11)

- A 1ª tentativa com o nome curto `gpt-oss-120b` deu `403 PERMISSION_DENIED`: "is no longer available. Use Unity Catalog model services". O nome curto cai no endpoint legado; o model service é endereçado por **três partes** (`system.ai.<nome>`).
- `ChatDatabricks(model="system.ai.gpt-oss-120b", use_ai_gateway=True)` respondeu `ok`.
- `system.ai.claude-sonnet-4-5` falhou com `404 ENDPOINT_NOT_FOUND`.
- `system.ai_gateway.usage` existe e registra chamadas a model services (`MODEL_SERVICE`, `PAY_PER_TOKEN_FOUNDATION_MODEL`, `status_code`, tokens, `requester_type`, `api_type`). Nas 20 linhas lidas (de uma query ordenada por `account_id`, ou seja, sem ordem útil) havia chamadas anteriores a `system.ai.gpt-oss-120b`, mas **nenhuma comprovadamente da execução de hoje**. A query do notebook foi corrigida para filtrar por `event_time`.
- Pelo `model_metadata`, cada model service tem `rate_limits` e `service_policies` configuráveis (vazios por padrão).
- Não colar e-mail ou IP do solicitante nas evidências.

### Checklist

| Verificação | Resultado | Evidência |
|---|---|---|
| Há um model service Claude em `system.ai`? | ❌ não: aba Models sem Claude; `system.ai.claude-sonnet-4-5` → 404 | prints; saída do notebook |
| Chamada via `ChatDatabricks(use_ai_gateway=True)` retorna 200 | ✅ com `system.ai.gpt-oss-120b` | saída do notebook |
| Linha em `system.ai_gateway.usage` da chamada de hoje | ⏳ pendente: reexecutar a query filtrada | _(preencher)_ |

### Resultado

**Passou com ressalva** (pendente a linha em `usage`): o Unity Gateway funciona na Free Edition, mas **não há model service Claude** em `system.ai`.

### Decisão

Decisão do mantenedor (2026-11-11): manter o Unity Gateway com um modelo não-Claude, `ATLAS_LLM_SERVICE` provisório = `system.ai.gpt-oss-120b` (nome de três partes). O plano B (AI Gateway clássico) não foi acionado. Ajustes em SPEC-005 e SPEC-000 na P3.8; ADR-0007 atualizado.
