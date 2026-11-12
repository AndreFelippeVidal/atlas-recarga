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

### Evidência na `system.ai_gateway.usage` (2026-11-11, UTC)

Duas chamadas do agente ao modelo, feitas via `/invocations` com token OAuth no terminal (a chamada do notebook só recebeu a tela de login e não chegou ao agente; o mantenedor registrou o resultado de uma delas):

| event_time | service_type | destination_name | status_code | input/output tokens | requester_type | auth_mode | invocation_metadata.source |
|---|---|---|---|---|---|---|---|
| 22:46:31 | MODEL_SERVICE | `system.ai.gpt-oss-120b` | 200 | 107 / 28 | SERVICE_PRINCIPAL | OAUTH | DATABRICKS_APPS |
| 22:55:38 | MODEL_SERVICE | `system.ai.gpt-oss-120b` | 200 | 107 / 32 | SERVICE_PRINCIPAL | OAUTH | DATABRICKS_APPS |

- O `requester` é o service principal do App (UUID não colado aqui), não o usuário que chamou o `curl`.
- `invocation_metadata.source = DATABRICKS_APPS` identifica que a chamada veio de um App; `user_agent` = `DatabricksOpenAI/Python`; `request_tags` vazio.
- `service_type` só admite `MODEL_SERVICE`, `MCP_SERVICE` e `MODEL_PROVIDER_SERVICE`: **não há tipo de agente** na tabela. Não há coluna com o nome do App; o App só é distinguível pelo service principal em `requester` e por `source`.
- Atraso de cerca de uma hora até a linha aparecer na system table (na S0.1 foram minutos).

### Checklist

| Verificação | Resultado | Evidência |
|---|---|---|
| O App hello responde em `/invocations` (OAuth) | ✅ `{"output":"ok"}` | saída do curl |
| O agente aparece no AI Gateway (aba Agents) | ✅ com o prefixo `agent-` | aba Agents |
| Uso do agente registrado no gateway | ⚠️ parcial: as chamadas do agente ao LLM aparecem (requester = service principal do App, `source` = DATABRICKS_APPS); não há entidade "agente" na `usage` e as métricas do agente na aba Agents são só as do App | tabela de evidência; captura do Insights |

### Resultado

**Passou com ressalva:** o agente `agent-*` é listado na aba Agents e as chamadas dele ao LLM passam pelo gateway e são rastreáveis por service principal. **Não há uso nativo por agente** (sem `service_type` de agente, sem tokens ou custo na aba Agents) e o registro como agent service (REST, só agentes externos, sem invocação em runtime) não foi necessário nem tentado.

### Pendências para a P3.8 / P10.2 (não validadas no S0.2)

- `request_tags`: o agente consegue enviar tags na chamada ao modelo e elas aparecem na `usage`? Sem isso, o consumo por agente só se atribui pelo service principal do App.
- `ask_genie` via `genie_one_mcp`: a chamada aparece como `MCP_SERVICE` (com `mcp_metadata.tool_name`) na `usage`? Define se o gateway governa essa tool.
- Trace de tool call: o span de cada tool aparece no experiment MLflow a partir de um App? Os acessos do service principal também devem ser conferidos em `system.access.audit`.
- Limite: a `usage` atrasa cerca de 1 hora, então alertas de uso quase em tempo real devem vir do trace; registrar isso em `docs/architecture.md`.

### Decisão

Proposta (a confirmar pelo mantenedor no PR): seguir o plano B da spec, em versão parcial (o agente é listado em Agents, mas sem uso nativo por agente). A governança e a medição ficam na **camada do LLM**; o agente é um App com prefixo `agent-` e a atribuição de uso é por `requester` (service principal do App) e `invocation_metadata.source`. O agente deve enviar `request_tags` se quisermos dimensionar por agente (não validado). Ajustes na SPEC-005 na P3.8.

## S0.3 — Production monitoring MLflow 3 (Beta)

- **Data:** 2026-11-12
- **ADR:** [0013](../adr/0013-mlflow-genai-evaluation-monitoring.md)
- **Notebook:** `spikes/s0_3_mlflow_monitoring.py` (descartável)

### Observações antes de rodar

- Segundo a documentação do MLflow open source (consultada via ctx7, não verificada na Databricks), o production monitoring (automatic evaluation) suporta só LLM judges, e que `@scorer` de código exige servidor self-hosted com job containers. O spike testou se isso vale na Databricks Free Edition: **a observação contradiz essa limitação** para um `@scorer` de código simples (mlflow 3.18.0). A afirmação da doc não traz versão ou link nesta nota.

### Execução (mlflow 3.18.0, experiment_id `2340593215239739`)

- 5 traces sintéticos criados (o notebook define 3 com bloco `Fonte:` e 2 sem).
- `has_source.register(...)` devolveu `name='has_source'` e `start(sampling_config=ScorerSamplingConfig(sample_rate=1.0))` terminou com `start() ok`, sem erro. Um scorer de código foi aceito.
- Plano B (`search_traces` + `evaluate`): rodou e registrou o run `languid-stork-757` com `has_source/mean = 0.6` (3 de 5), igual ao esperado.

### Evidência da 1ª rodada: assessments nos traces

| trace_id | assessments `has_source` |
|---|---|
| `tr-c947d887…` | False, False |
| `tr-eeea31a2…` | False, False |
| `tr-1951af80…` | True, True |
| `tr-e5982a2f…` | True, True |
| `tr-047042cd…` | True, True |

Os valores batem com o esperado (3 `True` e 2 `False`). Cada trace tem **duas** assessments com o mesmo nome; a 2ª rodada abaixo mostra que uma vem do monitoring e a outra do `evaluate`. O consumidor do feedback deve tolerar duplicatas quando o `evaluate` roda sobre traces já avaliados.

### 2ª rodada (2026-11-12, 12:04 UTC), mesmo experiment, etapa 4 antes da 5

- `start()` de novo sem erro. O experiment passou a ter 10 traces (5 da 1ª rodada + 5 novos).
- Leitura às 12:04:37 UTC, **antes** do `evaluate`: os 5 traces novos tinham **1** assessment `has_source` cada, com `source_type='CODE'` e `source_id='has_source'` (2 `False` e 3 `True`, como esperado). Como o `evaluate` ainda não tinha rodado, o feedback veio do scorer agendado. Atenção: o campo `source` não distingue as duas origens (o `evaluate` também grava `CODE` com o nome do scorer); a prova é a **ordem** das leituras, reportada pelo mantenedor, e a saída das células não foi versionada.
- Os 5 traces da 1ª rodada continuam com 2 assessments cada, o que bate com a explicação: uma do monitoring e outra do `evaluate` da etapa 5 daquela rodada.
- Plano B: `evaluate` sobre os 10 traces, run `charming-pig-605`, `has_source/mean = 0.6` (3 de 5 nos novos; a média também bate com a rodada anterior).
- Não medida: a latência entre a criação do trace e a assessment (só há o horário da leitura).

### Checklist

| Verificação | Resultado | Evidência |
|---|---|---|
| Scorer de código registrado e iniciado no experiment | ✅ | saída da etapa 3 (2 rodadas) |
| Feedback anexado aos traces **pelo scorer agendado** | ✅ 2ª rodada: 1 assessment `CODE` por trace novo antes do `evaluate` | saída da etapa 4 (2ª rodada) |
| Plano B (`search_traces` + `evaluate`) funciona | ✅ `has_source/mean = 0.6` | capturas dos runs `languid-stork-757` e `charming-pig-605` |

### Resultado

**Passou:** na 2ª rodada, um scorer de código agendado (`start()`) anexou feedback `CODE` aos traces novos sem nenhuma chamada ao `evaluate`. A 1ª rodada era ambígua porque o `evaluate` também grava assessments; a duplicata dos traces antigos vem daí. O plano B também foi validado.

### Decisão

Manter o production monitoring com scorer de código como caminho preferencial (ADR-0013), com o job diário `atlas_agent_monitoring` como plano B já validado. Pendências para a P10.8: latência entre trace e assessment (não medida), LLM judge em amostra de 20% (não testado) e se o scorer continua ativo depois de `stop()`/redeploy.

## S0.4 — Metric views + Genie

- **Data:** 2026-11-12
- **ADR:** [0005](../adr/0005-metric-views-semantic-layer.md)
- **Artefatos:** `spikes/s0_4_metric_view.sql` e `spikes/s0_4_genie_space.json` (descartáveis)

### Execução

- Fonte: `samples.tpch.orders` (o catálogo `atlas` só nasce na P5.2). Schema descartável `workspace.atlas_spike_s0_4`.
- `CREATE VIEW … WITH METRICS LANGUAGE YAML` (version 1.1, `comment`, `display_name` e `synonyms`) funcionou no SQL warehouse da Free Edition. Medidas: `gross_revenue`, `order_count` e a composta `avg_ticket = MEASURE(gross_revenue) / MEASURE(order_count)`.
- `MEASURE()` por `order_status` devolveu os mesmos valores do SQL direto sobre `samples.tpch.orders`, incluindo o `avg_ticket` (a composta fica correta no agrupamento):

| order_status | gross_revenue | orders | avg_ticket |
|---|---|---|---|
| F | 549181919365.27 | 3654501 | 150275.487505755232 |
| O | 548923692869.55 | 3654310 | 150212.678417963993 |
| P | 35333603011.43 | 191189 | 184809.811293693675 |

- Genie Space criado por `databricks genie create-space` (`serialized_space` v2) com **só a metric view** como fonte. O JSON enviado declara a view em `data_sources.metric_views`, mas o `serialized_space` devolvido pelo `create-space` a lista em `data_sources.tables` (a API normaliza); a P7.5 deve reler o space com `get-space --include-serialized-space` antes de versionar o JSON.
- Conversation API (`start-conversation`), 2 perguntas em PT-BR, ambas `COMPLETED` (as outras 2 perguntas de exemplo do JSON não foram testadas; os `conversation_id` não foram guardados, então a evidência é o texto abaixo e a query de comparação em `spikes/s0_4_metric_view.sql`):
  - "Qual o ticket médio por status do pedido?" → `MEASURE(avg_ticket) … GROUP BY ALL` sobre `mv_orders`; valores iguais aos da tabela acima. O Genie mapeou "ticket médio" pelo `synonyms`.
  - "Qual a receita bruta total por mês em 1995, os 3 maiores?" → `MEASURE(gross_revenue)` com `RANK()`; jan/1995 14.690.432.880,22, jul 14.581.176.323,30 e mar 14.574.503.669,87, iguais ao SQL direto.

### Achados práticos para a P7.1 / P7.5

- `databricks experimental aitools tools query` **remove a indentação** do SQL, o que quebra o YAML do `AS $$ … $$` (`Failed to parse YAML`). Para criar metric views, use a SQL Statement API (`databricks api post /api/2.0/sql/statements`) ou o `sql_task` de um job/bundle.
- O `create-space` não exigiu `parent_path`.
- Não testado: grants por schema (P7.3), recusa de pergunta fora do escopo, `COMMENT`/instruções do space com 10 exemplos (P7.5), AI/BI Dashboard sobre a view.

### Checklist

| Verificação | Resultado | Evidência |
|---|---|---|
| Metric view criada na Free Edition | ✅ | `CREATE VIEW … WITH METRICS` |
| `MEASURE()` funciona e bate com o SQL direto | ✅ 3 grupos, incluindo a medida composta | tabela acima |
| Genie responde usando a view | ✅ as 2 perguntas geraram SQL com `MEASURE()` sobre a view | conversation API |

### Resultado

**Passou.** Metric views e Genie funcionam na Free Edition; o plano B (views SQL + Genie sobre o gold) não é acionado.

### Decisão

ADR-0005 mantido como `aceito`, com a nota do S0.4. Os objetos do spike (`workspace.atlas_spike_s0_4` e o Genie Space `01f1dea09d7d1c7ebd204024f1350b36`) devem ser removidos pelo mantenedor depois da revisão.

## S0.5 — OAuth de cliente externo num App MCP

- **Data:** 2026-11-12
- **ADR:** [0008](../adr/0008-fastmcp-on-databricks-apps.md)
- **Artefatos:** `spikes/s0_5_mcp_hello/` (template oficial `databricks/app-templates/mcp-server-hello-world`, FastMCP, mais a tool `whoami_query`; descartável) e o `RUNBOOK.md` da pasta

### Execução

- App `atlas-s0-5-mcp` criado e implantado com o recurso SQL warehouse (`sql-warehouse`) e a autorização do usuário (OBO) com o escopo `sql`. O primeiro deploy falhou ("No command to run") porque o `databricks sync` partiu da raiz do repo e o `app.yaml` não ficou na raiz do source path; o runbook foi corrigido.
- Cliente: Claude Code, via `claude mcp add --transport http atlas-s0-5 https://<app-url>/mcp`, autenticado como o usuário (Opção A do runbook). Nenhuma credencial foi versionada nem registrada aqui.
- `health` respondeu: `{"status":"healthy","message":"Custom MCP Server is healthy and connected to Databricks Apps."}`.
- `whoami_query` (`SELECT current_user() AS u /* atlas-s0.5 */`, executada com a identidade do usuário) retornou o usuário do mantenedor (e-mail omitido); `statement_id` `01f1dea7-a747-184d-a93c-12978cbf0892`.
- `system.query.history` (consulta às 14:45 UTC): a linha do `SELECT current_user() … /* atlas-s0.5 */` (14:45:07 UTC) tem `executed_by` = o usuário do mantenedor (e-mail omitido), o usuário e não o service principal do App.

### Achados práticos para a P11.1 / P11.4

- No template, `get_user_authenticated_workspace_client()` lê o header `x-forwarded-access-token`; o App só o recebe com a autorização do usuário habilitada.
- `system.query.history` está disponível na Free Edition e permite a auditoria por `request_id` em comentário do SQL (SPEC-006 §6).
- O `app.yaml` do template é só `command`; `env` com `valueFrom` liga o warehouse ao App.
- Não testado: o fluxo OAuth interativo nativo do Claude Code, a expiração e a renovação da credencial, mais de um usuário (S0.6), rate limit e traces MLflow no App.

### Checklist

| Verificação | Resultado | Evidência |
|---|---|---|
| App MCP FastMCP implantado na Free Edition | ✅ | deploy `atlas-s0-5-mcp` |
| `health` responde a partir do Claude Code | ✅ | saída do Claude Code |
| Query do App em `system.query.history` com `executed_by` = usuário (OBO) | ✅ | `statement_id` acima e consulta à system table |

### Resultado

**Passou com ressalva.** Um cliente externo (Claude Code) conectou ao App MCP e a query rodou como o usuário (OBO), com a auditoria por usuário disponível. Ressalva: a autenticação foi um token de usuário enviado no cabeçalho; o fluxo OAuth interativo nativo do cliente não foi exercitado (fica para a P11.4/P11.5). O plano B (proxy `mcp-remote`, auditoria só no trace) não é acionado.

### Decisão

ADR-0008 mantido como `aceito`, com a nota do S0.5. O ajuste do texto da SPEC-006 §5/§6/§7 (de "a ser confirmado" para "confirmado") fica para a P3.8. O App `atlas-s0-5-mcp` deve ser removido pelo mantenedor depois da revisão (libera o slot para as P10.2, P11.1 e P12.8).

## S0.6 — Múltiplos usuários

- **Data:** 2026-11-12
- **ADR:** [0010](../adr/0010-commission-human-in-the-loop.md)
- **Notebook:** nenhum (verificação na UI do workspace)

### Execução (2026-11-12)

- Segundo usuário convidado para o workspace Free Edition. Ele aceitou o convite e entrou.
- Ao entrar, o usuário já ficou **direto no grupo `users`** (grupo padrão do workspace), sem atribuição manual.
- Criado o grupo `atlas_readers` e confirmado que o novo usuário pode ser adicionado a ele.
- Não colar e-mail ou nome do segundo usuário nas evidências.
- Não criados ainda: `atlas_commission_*`. O mecanismo é o mesmo do `atlas_readers`; a criação por bundle fica na P5.2.

### Checklist

| Verificação | Resultado | Evidência |
|---|---|---|
| O workspace aceita um segundo usuário | ✅ sim, ele entrou | captura da lista de usuários (não versionada) |
| O usuário recebe um grupo | ✅ `users` (padrão) | captura do usuário/grupo (não versionada) |
| É possível criar um grupo `atlas_*` e adicionar o usuário | ✅ `atlas_readers` | captura do grupo (não versionada) |
| Existem 2 identidades distintas para as 2 aprovações da comissão | ✅ sim | idem |

### Resultado

**Passou:** a Free Edition aceita um segundo usuário, que entra, recebe um grupo e pode ser adicionado a um grupo `atlas_*` criado por nós.

### Decisão

O modo `ALLOW_SAME_APPROVER_DEMO` **não é necessário como padrão**: há duas identidades distintas e grupos próprios atribuíveis. Ele permanece só como contingência explícita, auditada e marcada no lote, nunca como padrão. ADR-0010 atualizado; nenhum ajuste de spec por causa do S0.6 na P3.8.
