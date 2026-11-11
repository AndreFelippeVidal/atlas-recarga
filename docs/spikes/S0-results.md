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

### Checklist

| Verificação | Resultado | Evidência |
|---|---|---|
| Há um model service Claude em `system.ai`? | ❌ não listado (confirmar em Providers / `+ Model`) | prints |
| Chamada via `ChatDatabricks(use_ai_gateway=True)` com um modelo disponível retorna 200 | _(preencher)_ | saída do notebook |
| Chamada ao candidato Claude | _(preencher; colar o erro exato)_ | saída do notebook |
| Linha correspondente em `system.ai_gateway.usage` | _(preencher)_ | query + resultado |

### Resultado

_(passou · falhou → plano B · passou com ressalva)_

### Decisão

_(ex.: manter o gateway com o modelo X; ou plano B do ADR-0007; e o que muda em `ATLAS_LLM_SERVICE`)_
