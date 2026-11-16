# apps/agent

Databricks App `agent-atlas` (componente `atlas-agent`). Governado pela
[SPEC-005](../../docs/specs/005-business-agent/spec.md). O prefixo `agent-` do nome é o que lista o
App em AI Gateway > Agents (S0.2).

**P10.2 (esqueleto):** o agente responde em PT-BR pelo Unity Gateway, sem tools (`ask_genie` e as
UC functions entram na P10.3). Os traces vão para o experiment do bundle (`/Shared/atlas/agent`;
no `dev` o nome leva o prefixo do usuário) com as tags `user`, `app_version`, `prompt_version` e
`llm_service`.

## Origem

Baseado no template oficial `agent-langgraph` de
[databricks/app-templates](https://github.com/databricks/app-templates) (MLflow `AgentServer`,
LangGraph, chat UI). Vêm **sem alteração** do template (excluídos do ruff): `scripts/start_app.py`,
`scripts/app_diagnostics.py`, `agent_server/utils.py`, `agent_server/start_server.py`. Nosso código:
`agent_server/config.py` e `agent_server/agent.py`. O `start_app.py` clona a chat UI
(`e2e-chatbot-app-next`) na subida do App.

## Configuração

| Variável | Padrão | O que faz |
|---|---|---|
| `ATLAS_GATEWAY_MODE` | `unity` | Só `unity`; o plano B `classic` (ADR-0007) não foi implementado e falha na subida |
| `ATLAS_LLM_SERVICE` | `system.ai.gpt-oss-120b` | Model service de **três partes** (o nome curto cai no endpoint legado, 403) |
| `ATLAS_LLM_REQUEST_TAGS` | `0` | `1` envia `request_tags` ao gateway (não validado; ver abaixo) |
| `ATLAS_APP_VERSION`, `ATLAS_PROMPT_VERSION` | `dev`, `p10.2-skeleton` | Tags do trace |

## Deploy e conferência (mantenedor)

1. `databricks bundle deploy -t dev --profile andrevidal` e `databricks bundle run agent_atlas -t dev --profile andrevidal`.
2. Dê ao service principal do App acesso ao model service `system.ai.gpt-oss-120b` no Unity Gateway
   (permissão de serving endpoint não vale; lição do S0.1/S0.2).
3. Abra o App e escreva "olá".
4. Depois de alguns minutos até ~1 h: `uv run python scripts/check_agent_skeleton.py --profile andrevidal --warehouse-id <id>`.
5. Confira na UI o trace com as tags. Para validar `request_tags`, ponha `ATLAS_LLM_REQUEST_TAGS=1`
   no `app.yaml`/bundle, redeploye e veja se a coluna `request_tags` da `usage` vem preenchida.

## Pendências de validação (SPEC-005 §5)

- `request_tags` na chamada ao LLM (opt-in acima; formato do `extra_params` ainda não validado).
- `ask_genie` via `genie_one_mcp` como `MCP_SERVICE` e span de tool no experiment: P10.3, quando
  houver tools.
