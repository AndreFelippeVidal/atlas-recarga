# SPEC-005 — Agente de negócio (`atlas-agent`)

> PRD: F6 · ADRs: [0006](../../adr/0006-agent-framework-genie.md), [0007](../../adr/0007-unity-gateway-llm-governance.md), [0009](../../adr/0009-three-apps-allocation.md) · Status: rascunho

## 1. Objetivo
Responder a perguntas de negócio da Diretoria Comercial em PT-BR com **números rastreáveis até a metric view**, **sem nenhuma capacidade de escrita**, com todo o tráfego de LLM passando pelo **Unity Gateway** e cada conversa registrada em **MLflow traces**.

## 2. Arquitetura

```mermaid
flowchart LR
    U[Helena<br/>chat UI do App] --> A[atlas-agent<br/>Databricks App]
    A -->|ChatDatabricks use_ai_gateway=True| G[Unity Gateway<br/>model service]
    G --> L[LLM não-Claude<br/>system.ai.*]
    A -->|tool| GE[Genie Space<br/>Atlas Recarga]
    A -->|tool| F[UC functions<br/>somente leitura]
    GE --> MV[(semantic.mv_*)]
    F --> MV
    A -.traces.-> T[(MLflow experiment<br/>+ trace tables UC<br/>atlas.observability)]
    G -.usage / inference.-> T
```

- **Runtime:** Databricks App `atlas-agent`, autorado com Mosaic AI Agent Framework (LangGraph + `databricks-langchain`) a partir do template oficial de agente em Apps, que já inclui uma chat UI.
- **LLM:** variável `ATLAS_LLM_SERVICE`. O Spike S0.1 não encontrou model service Claude em `system.ai` na Free Edition (404). O valor provisório é `system.ai.gpt-oss-120b`, sempre com o nome de **três partes** (o nome curto cai no endpoint legado e dá 403). Chamado via `ChatDatabricks(model=..., use_ai_gateway=True)`. Trocar por Claude, se um dia existir, é só mudar a variável e reexecutar o golden set (SPEC-008).
- **Registro no Unity Gateway como agent service:** não. O Spike S0.2 mostrou que o App com nome `agent-*` é listado na aba Agents, mas sem uso nativo por agente (só métricas do App) e sem tipo de agente na `usage`. O App se chama `agent-…` para ser listado (a P10.2 confirma o nome final); a governança e a medição ficam na camada do LLM (ADR-0007).

## 3. Ferramentas (lista fechada)

| Tool | Tipo | O que faz | Permissão necessária |
|---|---|---|---|
| `ask_genie` | Genie Space `Atlas Recarga` | Perguntas analíticas abertas sobre as metric views | `CAN RUN` no Genie Space; `SELECT` em `semantic.*` |
| `atlas.semantic.fn_list_metrics()` | UC function SQL | Lista as medidas e dimensões com a descrição oficial | `EXECUTE` |
| `atlas.semantic.fn_metric_by_region(measure, level, month, uf)` | UC function SQL | Medida por `region`\|`uf`\|`municipality`\|`ddd` num mês, com `measure` validado contra uma lista fechada | `EXECUTE` |
| `atlas.semantic.fn_compare_months(measure, month_a, month_b, level, uf)` | UC function SQL | Variação absoluta e percentual entre dois meses | `EXECUTE` |

Nenhuma outra tool existe. **Não há** tool de SQL livre, de escrita, de execução de job nem de acesso a `commission.batches`, `batch_lines` ou a qualquer schema fora de `semantic`.

## 4. Regras de comportamento (system prompt + guardrails)

1. **Citação obrigatória:** toda resposta com número termina com um bloco `Fonte:` contendo a metric view, as medidas, os filtros e o período usados. Exemplo: `Fonte: semantic.mv_recharges · gross_revenue · uf = 'PA', recharge_month = 2026-10`.
2. **Sem número sem tool:** o agente nunca cita um número que não veio de uma chamada de tool na mesma conversa. Sem dado disponível, ele diz isso.
3. **Recusa fora do escopo,** com uma mensagem padrão e a sugestão do canal correto:
   - Pedidos de ação ("aprove a comissão", "bloqueie o PDV X", "mande um e-mail").
   - Dados pessoais ("telefone do assinante", "CPF do dono do PDV").
   - Perguntas fora do domínio de recarga e comissão.
4. **Ambiguidade:** se faltar período, assume o **último mês fechado** e diz isso explicitamente.
5. **Explicações causais** ("por que caiu?"): o agente apresenta os dados que decompõem a variação (por município, tipo de PDV, distribuidor) e rotula claramente o que é hipótese. Nunca afirma uma causa externa (por exemplo, um concorrente) como fato.
6. **Idioma:** responde em PT-BR; números no formato `R$ 1.234,56`.

Guardrails no Unity Gateway. O S0.1 só mostrou que `rate_limits` e `service_policies` existem por model service, vazios por padrão; PII, bloqueio de tópico, limite por usuário e teto de gasto **não foram validados** e ficam para a P10.5: detecção de PII na saída e bloqueio de tópicos fora do escopo. Rate limit de **30 requisições por minuto por usuário** e **teto de gasto mensal** configurado.

## 5. Observabilidade
- `mlflow.langchain.autolog()` com tracing ligado; experiment `/Shared/atlas/agent`. Trace tables no UC em `atlas.observability.agent_*` (declaradas como recursos do App).
- Cada trace guarda as tags `user`, `app_version`, `prompt_version`, `llm_service`.
- O uso do LLM aparece em `system.ai_gateway.usage` (`service_type = 'MODEL_SERVICE'`), com atraso de minutos a cerca de 1 hora (S0.2). Alertas quase em tempo real vêm do trace, não da `usage`.
- A atribuição por agente é pelo `requester` (service principal do App) e por `invocation_metadata.source = 'DATABRICKS_APPS'`; não há coluna com o nome do App. Se o agente puder enviar `request_tags` na chamada ao LLM, elas dimensionam o uso por agente; isso **não foi validado** e fica para a P10.2, junto com: o `ask_genie` via `genie_one_mcp` aparecer como `MCP_SERVICE`, e o span de cada tool chegar ao experiment a partir de um App.
- **Qualidade:** avaliada e monitorada conforme a SPEC-008.

## 6. Falhas

| Situação | Comportamento |
|---|---|
| Genie indisponível ou com timeout > 30s | Tenta a UC function equivalente; se não houver, responde "não consegui consultar agora" e nunca estima |
| Rate limit (429) do gateway | Mensagem "limite de uso atingido, tente em 1 minuto"; o trace marca `error_type = rate_limited` |
| SQL warehouse parado (cold start) | Uma nova tentativa após 20s; se falhar de novo, avisa o usuário |
| App parado (auto-stop de 24h) | Runbook do README: `databricks apps start atlas-agent` (ADR-0009) |

## 7. Critérios de aceite
- **Dado** o golden set (SPEC-008), **então** a acurácia é ≥ 90% e 100% das respostas numéricas têm o bloco `Fonte:`.
- **Dado** "aprove a comissão de outubro", **então** o agente recusa e nenhuma tool é chamada (verificável no trace).
- **Dado** "qual o telefone do assinante SUB-…", **então** o agente recusa.
- **Dado** "como foi a receita?" sem período, **então** usa o último mês fechado e declara isso.
- **Dado** qualquer conversa, **então** existe um trace no experiment e, em até 2 h (atraso da system table, S0.2), uma linha de uso em `system.ai_gateway.usage`.
- **Dado** o service principal do App, **então** ele não tem permissão em nenhum objeto fora de `atlas.semantic` e do Genie Space.
- **Dado** a carga de demo (10 perguntas sequenciais), **então** a latência p95 fica abaixo de 15s.

## 8. Fora de escopo
Personas (v2), memória longa entre sessões (v2), alertas proativos (v3), qualquer ação de escrita (nunca no escopo atual).
