# SPEC-006 — MCP server (`atlas-mcp`, FastMCP)

> PRD: F7 · ADRs: [0008](../../adr/0008-fastmcp-on-databricks-apps.md), [0009](../../adr/0009-three-apps-allocation.md) · Status: rascunho

## 1. Objetivo
Expor a camada semântica do Atlas como **MCP server somente leitura**, para que a Helena (ou qualquer cliente MCP, como Claude Code ou Claude Desktop) consulte os dados de onde já trabalha, com a mesma definição de métrica do dashboard e do agente.

## 2. Runtime
- **FastMCP** (Python), transporte **Streamable HTTP**, escutando em `0.0.0.0:$DATABRICKS_APP_PORT` (padrão 8000), path `/mcp`.
- Hospedado como Databricks App `atlas-mcp` (`app.yaml`: `command: ['uv', 'run', 'atlas-mcp']`).
- URL do cliente: `https://<atlas-mcp-app-host>/mcp`.
- Acesso a dados: `databricks-sql-connector` → SQL warehouse 2X-Small → `atlas.semantic.*`.
- **Autorização:** *on-behalf-of-user* (o token do usuário do App), para que as permissões do UC do próprio usuário sejam aplicadas. Se isso não estiver disponível, usa o service principal do App restrito a `SELECT` em `semantic` (ADR-0008).

> Limitação documentada: hoje o Unity Gateway **não permite registrar um MCP hospedado em Databricks Apps como MCP Service do UC** (doc *Register an MCP service*, Limitations); o cliente conecta direto ao App. O rate limit e a auditoria que o gateway daria são feitos no próprio App (§6). Ver ADR-0008.

## 3. Tools

Todas são somente leitura e todas montam SQL **parametrizado** a partir de listas fechadas. Nenhuma aceita SQL livre.

| Tool | Parâmetros | Retorno |
|---|---|---|
| `health()` | — | `{"status": "healthy", "warehouse": "<state>", "version": "<semver>"}` |
| `list_metrics()` | — | Medidas e dimensões de `mv_recharges` e `mv_commission` com a descrição oficial |
| `query_metric(view, measures[], dimensions[], filters{}, month_from, month_to, order_by?, limit=50)` | `view ∈ {mv_recharges, mv_commission}`; `measures` e `dimensions` ⊂ a lista da view; `filters` com chaves ⊂ `dimensions` e valores escalares ou listas; `limit ≤ 500` | `{"columns": [...], "rows": [...], "source": {...}, "sql_fingerprint": "<sha1>"}` |
| `top_regions(measure, level, month, n=10, uf?)` | `level ∈ {region, uf, municipality, ddd}`; `n ≤ 50` | Ranking + `source` |
| `compare_months(measure, month_a, month_b, level, uf?)` | igual | Valores, Δ absoluto, Δ% + `source` |

O campo `source` de toda resposta repete o contrato de citação do agente (view, medidas, filtros, período).

**Detalhes de `query_metric` (P11.2):**
- `month_from` e `month_to` são obrigatórios, no formato `YYYY-MM` e inclusivos; filtram a dimensão de mês da view (`recharge_month` em `mv_recharges`, `reference_month` em `mv_commission`), com os valores vinculados.
- `filters`: valor escalar vira `= :p`; lista vira `IN (:p0, :p1, …)`, com no máximo 100 valores. Chaves são dimensões da view; valores são `str`, `int` ou `float` (não `bool`, `null` nem objetos).
- `order_by`: uma coluna do resultado (medida ou dimensão) com `asc` ou `desc` opcional; sem direção, medida em `desc` e dimensão em `asc`. Sem `order_by`, a ordem é a primeira medida em `desc`, para o `limit` não cortar linhas arbitrárias.
- `limit` acima de 500 é `INVALID_ARGUMENT`; o `RESULT_TOO_LARGE` do §4 fica para o `compare_months`, que não tem `limit` (o `top_regions` é limitado por `n ≤ 50`).
- `sql_fingerprint` é o sha1 do SQL parametrizado, sem o comentário `request_id` e sem os valores.
- A lista fechada de medidas e dimensões vem de `apps/mcp/atlas_mcp/catalog.json`, gerado de `semantic/*.yaml` por `scripts/build_mcp_catalog.py` (o App só leva `apps/mcp` no deploy); um teste falha se o snapshot ficar velho.
- O erro de argumento chega ao cliente como erro de tool com a mensagem prefixada por `INVALID_ARGUMENT:`.

**Detalhes de `top_regions` e `compare_months` (P11.3):**
- Só leem `mv_recharges` (a única view com `ddd`); `measure` é uma medida dela. `level` mapeia para as dimensões `region`, `uf`, `municipality_ibge_code` + `municipality_name` e `ddd`. `month`, `month_a` e `month_b` são `YYYY-MM`; `uf` (opcional) é um filtro escalar vinculado.
- `top_regions` ordena a medida em `desc` e corta em `n` (1 a 50); nunca dá `RESULT_TOO_LARGE`.
- `compare_months` roda a mesma consulta nos dois meses (mesmo SQL, só os binds mudam) e devolve, por região, `value_a`, `value_b`, `delta_abs` (b − a) e `delta_pct` (arredondado a 2 casas, `ROUND_HALF_EVEN`; nulo se a base é 0 ou falta um dos meses; o denominador é `abs(base)`), com a maior variação absoluta primeiro. Se qualquer mês ou a união das regiões passar de 500 linhas: `RESULT_TOO_LARGE`, sugerindo filtrar por `uf` ou usar um `level` mais agregado.
- A mensagem de `PERMISSION_DENIED` e de `WAREHOUSE_UNAVAILABLE` é fixa: o texto original do conector (host, caminho, SQL) não vai ao cliente.

## 4. Erros (padronizados, nunca stack trace)

| Código | Quando |
|---|---|
| `INVALID_ARGUMENT` | Medida, dimensão ou filtro fora da lista fechada; `limit` acima do máximo; mês inválido |
| `PERMISSION_DENIED` | O usuário não tem `SELECT` na metric view |
| `WAREHOUSE_UNAVAILABLE` | Warehouse parado ou em timeout depois de 1 nova tentativa (20s) |
| `RESULT_TOO_LARGE` | Mais de 500 linhas: sugere agregar mais ou filtrar |
| `RATE_LIMITED` | Mais de 30 chamadas de tool por minuto do mesmo usuário; a resposta traz `retry_after_s` e nenhuma query é executada |

## 5. Conexão (documentada no README)
- **Claude Code (caminho validado na P11.5):** `claude mcp add --transport http atlas https://<atlas-mcp-app-host>/mcp --header "Authorization: Bearer $DATABRICKS_USER_TOKEN"`, com um token de curta duração do usuário (expira em tempo curto; estimativa de cerca de 1 hora, não medida). A query roda como esse usuário (OBO), como o Spike S0.5 já tinha mostrado. O `--header` grava o token em texto puro no `~/.claude.json`, fora do repositório.
- **OAuth interativo nativo (`/mcp` no Claude Code): não funciona hoje.** O Databricks recusa com `access_denied: Scopes 'iam.access-control:read iam.current-user:read sql' are not assigned to the client https://claude.ai/oauth/claude-code-client-metadata`, pois o client público do Claude Code não está registrado no workspace e a Free Edition não permite criar a OAuth app connection. Revisar se a plataforma aceitar esse client.
- **Alternativa com proxy (não testada na P11.5):** `mcp-remote` com o mesmo cabeçalho `Authorization: Bearer`. O token nunca vai para o repositório.
- Guia, evidência e cuidados: [docs/mcp-claude-code.md](../../mcp-claude-code.md).

## 6. Observabilidade e controle (no lugar do Unity Gateway)

O MCP não chama LLM, então os controles de tokens e de PII na saída do gateway não se aplicam a ele. O que o gateway daria e faz falta é **auditoria central** e **rate limit**. Os dois são feitos no App:

| O gateway daria | No `atlas-mcp` |
|---|---|
| Registro de uso em `system.ai_gateway.usage` | **MLflow traces:** cada chamada de tool abre um span **manual** (`mlflow.start_span`) no experiment `/Shared/atlas/mcp` e grava só atributos: `request_id`, `user`, `tool`, `app_version`, `sql_fingerprint`, `rows`, `error_code`, `duration_ms`. **Não** se usa `@mlflow.trace`, porque o decorator grava o retorno da função; os valores dos resultados nunca entram no span. Os traces vão para as trace tables `atlas.observability.mcp_*` no UC, pelo mesmo mecanismo do agente (SPEC-005 §5) |
| Auditoria de acesso a dados | **`system.query.history`:** as tools que consultam o warehouse (`query_metric`, `top_regions`, `compare_months`) prefixam o SQL com o comentário `/* atlas-mcp request_id=<uuid> */`, que liga cada query ao trace. `health` e `list_metrics` não geram SQL de dados. Com on-behalf-of-user, `executed_by` é o usuário real; no plano B (service principal), o usuário fica só no trace. A `system.query.history` está disponível na Free Edition (S0.5). O App só recebe o token do usuário (`x-forwarded-access-token`) com a autorização do usuário (OBO) habilitada, com o escopo `sql` |
| Rate limit por usuário | Limitador em memória de **30 chamadas por minuto por usuário** (o mesmo teto do agente), antes de qualquer query. Erro `RATE_LIMITED` (§4) |
| Painel de uso | Página **"Uso do MCP"** no AI/BI Dashboard (separada da "Qualidade do agente"): chamadas, erros por código e latência p95 por tool e por dia, lidos de `atlas.observability.mcp_*` |

**Identidade:** o service principal do App recebe `CAN_EDIT` só no experiment `/Shared/atlas/mcp` para gravar traces. É um objeto do workspace, não dado do UC; o critério 5 (nada fora de `atlas.semantic`) continua valendo para dados.

Os logs JSON no stdout do App continuam (`tool`, `user`, `duration_ms`, `rows`, `sql_fingerprint`, `error_code`), para depuração.

**Limitações aceitas:** o limitador vale por instância do App e zera num restart (o App tem uma instância na Free Edition); não há teto de gasto, porque o custo do MCP é o do warehouse, e o 2X-Small já é o teto natural.

## 7. Critérios de aceite
- **Dado** um cliente MCP conectado, **quando** chamo `health`, **então** recebo `status: healthy`.
- **Dado** `query_metric(view='mv_recharges', measures=['gross_revenue'], dimensions=['uf'], month_from='2026-10', month_to='2026-10')`, **então** os valores batem ao centavo com o AI/BI Dashboard.
- **Dado** `measures=['DROP TABLE x']` ou uma dimensão inexistente, **então** recebo `INVALID_ARGUMENT` e nenhuma query é executada.
- **Dado** um `filters` com um valor contendo aspas ou `;`, **então** o valor é passado como parâmetro vinculado, sem concatenação (teste de injeção).
- **Dado** o service principal do App, **então** ele não tem permissão fora de `atlas.semantic`.
- **Dado** o golden set, **quando** reformulado via `query_metric`, **então** os números são iguais aos do SQL de referência (reaproveita a SPEC-008).
- **Dado** 31 chamadas de `query_metric` do mesmo usuário em 60s, **então** a 31ª recebe `RATE_LIMITED` com o seu `request_id`, e nenhuma linha de `system.query.history` contém esse `request_id` (no teste de unidade: o cliente SQL mockado não é chamado).
- **Dado** qualquer chamada de tool, **então** existe um trace em `/Shared/atlas/mcp` com os atributos do §6 e **sem outputs** (teste: o span não tem `outputs` nem valores das linhas).
- **Dado** o modo on-behalf-of-user (confirmado no S0.5 com token de usuário no cabeçalho; o OAuth interativo nativo foi tentado na P11.5 e não funciona, ver §5), **então** a query da tool aparece em `system.query.history` com `executed_by` igual ao usuário do cliente MCP. **No plano B**, o critério passa a ser: o `user` do trace é o do cliente e `executed_by` é o service principal.
- **Dado** a página "Uso do MCP", **então** ela mostra chamadas, erros por código e p95 por tool para o último dia com tráfego.

## 8. Fora de escopo
Tools de escrita (nunca), registro como MCP Service no Unity Gateway (bloqueado pela plataforma hoje; revisar no ADR-0008), resources e prompts MCP (v2).
