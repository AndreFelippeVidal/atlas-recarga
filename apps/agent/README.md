# apps/agent

Databricks App `agent-atlas` (componente `atlas-agent`). Governado pela
[SPEC-005](../../docs/specs/005-business-agent/spec.md). O prefixo `agent-` do nome é o que lista o
App em AI Gateway > Agents (S0.2).

**P10.2 (esqueleto):** o agente responde em PT-BR pelo Unity Gateway.
**P10.3 (tools):** a lista fechada da SPEC-005 §3: `ask_genie` (Genie Agent MCP, restrito ao Space
`Atlas Recarga`; **não** passa pelo Unity Gateway) e as UC functions `fn_list_metrics`,
`fn_metric_by_region` e `fn_compare_months`. As tools usam os nomes curtos que o scorer
`read_only_tools` espera. Os traces vão para o experiment do bundle (`/Shared/atlas/agent`;
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
| `ATLAS_CATALOG` | `atlas` | Catálogo das UC functions (`atlas_dev` no `dev`; o bundle injeta) |
| `ATLAS_GENIE_SPACE_ID` | (recurso `genie-space`) | Space do `ask_genie`; o App recebe `CAN_RUN` |
| `ATLAS_APP_VERSION`, `ATLAS_PROMPT_VERSION` | `dev`, `p10.3-tools` | Tags do trace |

## Deploy e conferência (mantenedor)

1. `databricks bundle deploy -t dev --profile andrevidal` e `databricks bundle run agent_atlas -t dev --profile andrevidal`.
2. Dê ao service principal do App acesso ao model service `system.ai.gpt-oss-120b` no Unity Gateway
   (permissão de serving endpoint não vale; lição do S0.1/S0.2).
3. Abra o App e escreva "olá".
4. Depois de alguns minutos até ~1 h: `uv run python scripts/check_agent_skeleton.py --profile andrevidal --warehouse-id <id>`.
5. Confira na UI o trace com as tags. Para validar `request_tags`, ponha `ATLAS_LLM_REQUEST_TAGS=1`
   no `app.yaml`/bundle, redeploye e veja se a coluna `request_tags` da `usage` vem preenchida.

## Conferência da P10.3 (mantenedor)

Pré-requisito: `EXECUTE` + `SELECT` em
`semantic` para o service principal do App (`scripts/setup_workspace.py --reader <client_id>`,
ADR-0016).

1. Deploy e `bundle run` como acima, com `ATLAS_LLM_REQUEST_TAGS=1` no bundle.
2. No App, pergunte o GS-001: "Qual foi a receita de recarga da rede em outubro de 2026?"
3. `uv run python scripts/check_agent_tools.py --profile andrevidal --warehouse-id <id> --catalog atlas_dev`
   (traz o valor esperado do GS-001 e confere `request_tags` na `usage`).
4. Na aba Traces do experiment, confira os spans TOOL `ask_genie` e `fn_*`.

Verificado contra o workspace: o Genie Agent MCP expõe `query_space_<id>` (argumento `query`) e
`poll_response_<id>` (`conversation_id`, `message_id`); a resposta traz `conversationId`,
`messageId` e `status` (`COMPLETED` ao fim). Não verificado ainda: o formato do `extra_params` de
`request_tags` e se o `DatabricksMCPClient` emite um span próprio.
