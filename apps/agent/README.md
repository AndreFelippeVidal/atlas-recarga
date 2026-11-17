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
| `ATLAS_LLM_REQUEST_TAGS` | `0` | `1` envia `request_tags` ao gateway, no cabeçalho `Databricks-Ai-Gateway-Request-Tags` |
| `ATLAS_CATALOG` | `atlas` | Catálogo das UC functions (`atlas_dev` no `dev`; o bundle injeta) |
| `ATLAS_GENIE_SPACE_ID` | (recurso `genie-space`) | Space do `ask_genie`; o App recebe `CAN_RUN` |
| `ATLAS_APP_VERSION`, `ATLAS_PROMPT_VERSION` | `dev`, `v1` | Tags do trace; `ATLAS_PROMPT_VERSION` escolhe o arquivo `prompts/<versão>.md` |

## Deploy e conferência (mantenedor)

1. `databricks bundle deploy -t dev --profile andrevidal` e `databricks bundle run agent_atlas -t dev --profile andrevidal`.
2. Dê ao service principal do App acesso ao model service `system.ai.gpt-oss-120b` no Unity Gateway
   (permissão de serving endpoint não vale; lição do S0.1/S0.2).
3. Abra o App e escreva "olá".
4. Depois de alguns minutos até ~1 h: `uv run python scripts/check_agent_skeleton.py --profile andrevidal --warehouse-id <id>`.
5. Confira na UI o trace com as tags. A coluna `request_tags` da `usage` vem preenchida porque o
   bundle liga `ATLAS_LLM_REQUEST_TAGS=1`.

## Conferência da P10.3 (mantenedor)

Pré-requisito: `EXECUTE` + `SELECT` em
`semantic` para o service principal do App (`scripts/setup_workspace.py --reader <client_id>`,
ADR-0016).

1. Deploy e `bundle run` como acima.
2. No App, pergunte o GS-001: "Qual foi a receita de recarga da rede em outubro de 2026?"
3. `uv run python scripts/check_agent_tools.py --profile andrevidal --warehouse-id <id> --catalog atlas_dev`
   (traz o valor esperado do GS-001 e confere `request_tags` na `usage`).
4. Na aba Traces do experiment, confira os spans TOOL `ask_genie` e `fn_*`.

Verificado contra o workspace: o Genie Agent MCP expõe `query_space_<id>` (argumento `query`) e
`poll_response_<id>` (`conversation_id`, `message_id`); a resposta traz `conversationId`,
`messageId` e `status` (`COMPLETED` ao fim). `request_tags` vai no cabeçalho do gateway como mapa
JSON (no corpo dá 400). Os spans do App se chamam `ask_genie` e `fn_*`.

## Prompt (P10.4)

O system prompt é `prompts/v1.md` (SPEC-005 §4): lista fechada de tools e seus argumentos, `Fonte:`,
recusa sem tool, último mês fechado e PT-BR. A versão vai na tag `prompt_version` do trace e nas
`request_tags`. **Mudou o texto, crie `v2.md`**: o arquivo publicado não se edita, e o gate da
SPEC-008 filtra por `prompts/**`.

Conferência (mantenedor), a partir de `apps/agent`, com o ambiente do App:

```bash
uv run --project apps/agent python scripts/check_agent_refusals.py --profile andrevidal \
  --catalog atlas_dev --warehouse-id <id> --genie-space-id <id>
```

Roda GS-026 a GS-030 (nenhuma tool chamada, pelo scorer da P9.3), uma métrica (bloco `Fonte:`) e
uma pergunta sem período (declara o mês assumido). Imprime as respostas para você julgar a recusa.
O 429 do endpoint é tentado de novo, e a resposta de um LLM varia: rode duas ou três vezes.
