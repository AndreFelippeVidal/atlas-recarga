# apps/agent

Databricks App `agent-atlas` (componente `atlas-agent`). Governado pela
[SPEC-005](../../docs/specs/005-business-agent/spec.md). O prefixo `agent-` do nome é o que lista o
App em AI Gateway > Agents (S0.2).

**P10.2 (esqueleto):** o agente responde em PT-BR pelo Unity Gateway.
**P10.3 (tools):** a lista fechada da SPEC-005 §3: `ask_genie` (Genie Agent MCP, restrito ao Space
`Atlas Recarga`; **não** passa pelo Unity Gateway) e as UC functions `fn_list_metrics`,
`fn_metric_by_region` e `fn_compare_months`. As tools usam os nomes curtos que o scorer
`read_only_tools` espera. Os traces vão para o experiment do bundle (`/Shared/atlas/agent-traces` desde a P10.5; antes, `/Shared/atlas/agent`;
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
| `ATLAS_LLM_SERVICE` | `system.ai.gpt-oss-120b` | Model service de **três partes** (o nome curto cai no endpoint legado, 403). No bundle: `<catalog>.observability.agent_llm` (P10.5) |
| `ATLAS_LLM_REQUEST_TAGS` | `0` | `1` envia `request_tags` ao gateway, no cabeçalho `Databricks-Ai-Gateway-Request-Tags` |
| `ATLAS_CATALOG` | `atlas` | Catálogo das UC functions (`atlas_dev` no `dev`; o bundle injeta) |
| `ATLAS_GENIE_SPACE_ID` | (recurso `genie-space`) | Space do `ask_genie`; o App recebe `CAN_RUN` |
| `ATLAS_APP_VERSION`, `ATLAS_PROMPT_VERSION` | `dev`, `v2` | Tags do trace; `ATLAS_PROMPT_VERSION` escolhe o arquivo `prompts/<versão>.md` |

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
`semantic` para o service principal do App (`semantic_grants` no bundle, ADR-0017; `USE CATALOG` por
`scripts/setup_workspace.py --reader <client_id>`, ADR-0016).

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

O system prompt é `prompts/v1.md` (SPEC-005 §3 e §4): lista fechada de tools e seus argumentos,
`Fonte:`, recusa sem tool, último mês fechado, total da rede pelo `ask_genie` (nunca somando
regiões) e PT-BR. A versão vai na tag `prompt_version` do trace e nas `request_tags`.

**Um prompt publicado não se edita.** `prompts/MANIFEST.json` guarda o sha256 de cada versão e o
teste `test_every_prompt_is_in_the_manifest_with_the_published_hash` falha se `v1.md` mudar. Para
mudar o texto: crie `v2.md`, acrescente a linha no manifesto (`sha256` do texto sem espaços nas
pontas) e ponha `ATLAS_PROMPT_VERSION=v2`. O gate da SPEC-008 filtra por `prompts/**`.

Conferência (mantenedor), a partir da raiz, com o ambiente do App:

```bash
uv run --project apps/agent python scripts/check_agent_refusals.py --profile andrevidal \
  --catalog atlas_dev --warehouse-id <id> --genie-space-id <id>
```

13 checagens, todas imprimem a resposta: as 5 recusas do golden set (GS-026 a GS-030), 5 sondas de
recusa mais difíceis (X-01 a X-05), uma métrica com mês (`Fonte:` cita `mv_recharges`, sem fingir
que assumiu o período), uma pergunta sem período (declara o mês assumido, vindo de tool) e o
ticket médio da rede (vem do `ask_genie` e bate com a metric view, pelo `numeric_match` da P9.3).
O 429 do endpoint é tentado de novo.

**Limite conhecido:** a regra do período ausente é obedecida em cerca de 60 a 75% das execuções
(medido em 9 execuções; reposicionar a regra no prompt não melhorou). As demais checagens
passaram em todas. O golden set não tem caso sem período, então o gate de 90% não o pega: ver o
follow-up no PR.

## Limites e guardrails (P10.5, ADR-0021)

- **Gateway:** o bundle cria o model service `<catalog>.observability.agent_llm` (destino
  `system.ai.gpt-oss-120b`) com 30 req/min (`USER_DEFAULT`, que para o gateway é o service principal
  do App, não o usuário final), 500.000 tokens/hora no serviço (o freio de gasto; o pior turno da
  P10.2 foi de 143.841) e inference table `agent_llm_payload`. O App recebe `EXECUTE` pelo bundle.
- **App:** `agent_server/guardrails.py` mascara CPF, telefone e e-mail na resposta final (o
  texto sai inteiro no fim, sem deltas de token) e marca o trace com `pii_masked = true`. Um 429 do
  gateway vira "Limite de uso atingido, tente em 1 minuto." e a tag `error_type = rate_limited`.
- **Gasto mensal:** o gateway não bloqueia por mês. O aviso é um orçamento de conta, criado pelo
  mantenedor com um perfil de **conta** (`databricks account budgets create --json @budget.json`):
  `resource_type` `BUDGET_RESOURCE_TYPE_UNITY_AI_GATEWAY`, filtro `workspace_id`, alerta
  `CUMULATIVE_SPENDING_EXCEEDED` mensal por e-mail com o valor que você escolher. Ele avisa e não
  bloqueia.

Conferência (mantenedor), nesta ordem:

1. `databricks bundle deploy -t dev --profile andrevidal` (cria o model service e o grant; se o
   App já roda, `databricks bundle run agent_atlas -t dev --profile andrevidal` para pegar o novo
   `ATLAS_LLM_SERVICE`).
2. Trace tables: `uv run --project apps/agent python scripts/setup_agent_trace_tables.py --profile
   andrevidal --catalog atlas_dev --warehouse-id <id> --experiment-id <id do atlas_agent_traces> --app-sp <client_id>`
   (dry-run; acrescente `--apply`). **Não foi exercitado contra o workspace.**
3. `uv run python scripts/check_agent_guardrails.py --profile andrevidal --warehouse-id <id>
   --catalog atlas_dev` (configuração, rajada com 429 e inference table).
4. No App: confirme que a resposta **aparece** na chat UI (o texto agora chega inteiro, sem deltas); faça a pergunta com o CPF e a rajada de mais de 30 mensagens (o script imprime o texto). Se um novo `bundle deploy` recriar o experiment, rode o passo 2 de novo; se o deploy falhar por recurso ainda inexistente, rode-o outra vez.
