# ADR-0007 — Governar o tráfego de IA pelo Unity Gateway

- **Status:** aceito, com o plano B do S0.2 (governar só o LLM) em versão parcial ("parcial": o agente é listado no gateway como App `agent-*`, mas sem uso nativo por agente; a governança fica no LLM; S0.1 com ressalva: sem Claude; S0.2 com ressalva: sem uso nativo por agente) · **Data:** 2026-11-11 · **Relacionados:** SPEC-005, ADR-0008

## Contexto
O requisito principal do projeto é ter **o agente passando pelo Unity Gateway**, com tracing, controle de uso e limites. A documentação atual mostra:
- O Unity Gateway é GA e funciona como o "plano de controle de agentes": roteia para **model services** e **MCP services**, aplica rate limits, spend caps e guardrails (service policies), e registra uso em `system.ai_gateway.usage`.
- **Agent services** (registrar um agente no gateway) e parte das capacidades de MCP estão em **Beta**, habilitadas pelo admin da conta em *Previews*.
- No AI Gateway clássico de *serving endpoints*, os endpoints de agente suportam apenas inference tables; o controle completo fica no endpoint do LLM.

## Critérios de decisão
- Toda chamada ao LLM tem dono, custo e limite rastreáveis.
- Guardrails aplicados fora do código do agente (não dependem só do prompt).
- Funcionar na Free Edition, com plano B se o Beta não estiver disponível.

## Opções consideradas
1. **Unity Gateway model service para o LLM (`ChatDatabricks(..., use_ai_gateway=True)`) + registro do agente como agent service (Beta)**
2. **AI Gateway clássico** configurado num serving endpoint de foundation model pay-per-token
3. **Chamar a API do provedor diretamente** (Anthropic) com a chave em secret
4. **Sem gateway:** limites e logs implementados no código do agente

## Decisão
**Opção 1**, com a **Opção 2 como plano B automático** se o Spike S0.1 falhar. A governança fica em **duas camadas**: o LLM (rate limit de 30 req/min por usuário, spend cap mensal, guardrail de PII e tópicos, inference e trace tables) e, se o S0.2 passar, o agente como agent service.

## Prós e contras
**Unity Gateway.** 👍 Um só lugar para custo, permissão e limite; o uso aparece em uma system table consultável no dashboard. 👎 Recursos em Beta; a disponibilidade na Free Edition precisa ser comprovada; a API pode mudar.
**AI Gateway clássico.** 👍 Maduro: rate limit, guardrails e inference tables. 👎 Governança por endpoint, não centralizada; o agente em si fica fora dela.
**API direta.** 👍 Acesso a qualquer modelo. 👎 Chave para gerenciar, sem governança no UC; contradiz o objetivo do projeto.
**Sem gateway.** 👍 Simples. 👎 O guardrail vive no mesmo código que ele deveria proteger.

## Consequências
- **Positivas:** o custo e o volume do agente ficam visíveis no AI/BI ("Qualidade do agente" + uso); os limites são aplicados mesmo que haja um bug no agente.
- **Negativas aceitas:** dependência de Beta; o código lê `ATLAS_LLM_SERVICE` e `ATLAS_GATEWAY_MODE` (`unity` | `classic`) para alternar sem refatorar.
- **Revisitar:** quando o agent services virar GA, ou se o S0.1 falhar (atualizar para "aceito com plano B").

## Resultado do Spike S0.1 (2026-11-11)
- O Unity Gateway está disponível na Free Edition, e `ChatDatabricks(model="system.ai.gpt-oss-120b", use_ai_gateway=True)` respondeu 200. A chamada apareceu em `system.ai_gateway.usage` (com atraso de minutos), inclusive a tentativa Claude que deu 404; evidência em `docs/spikes/S0-results.md`.
- **Não há model service Claude em `system.ai`** neste workspace (aba Models sem Claude; tentativa de chamar um Claude → 404 `ENDPOINT_NOT_FOUND`). A suposição "LLM Claude" do contexto deste ADR e da SPEC-005 não se confirma.
- O nome curto do modelo (`gpt-oss-120b`) cai no endpoint legado e dá 403; o model service é endereçado pelo **nome de três partes**.
- **Decisão:** manter a Opção 1 (Unity Gateway) com um modelo não-Claude; `ATLAS_LLM_SERVICE` padrão provisório = `system.ai.gpt-oss-120b`. O plano B (Opção 2) **não** foi acionado. A SPEC-005 e a SPEC-000 são ajustadas na P3.8.

## Resultado do Spike S0.2 (2026-11-11)
- Um App com nome `agent-*` aparece na aba Agents do AI Gateway, sem passo de registro. Sem o prefixo (`atlas-hello-agent`), não aparece. A aba leva à página do App; as métricas são do App (viewers, uptime, requests, latência, CPU, memória), sem tokens nem custo.
- As chamadas do agente ao `system.ai.gpt-oss-120b` aparecem em `system.ai_gateway.usage` (atraso de cerca de 1 hora) com `requester_type = SERVICE_PRINCIPAL` (o do App), `auth_mode = OAUTH` e `invocation_metadata.source = DATABRICKS_APPS`. A tabela não tem tipo de serviço para agente; só `MODEL_SERVICE`, `MCP_SERVICE` e `MODEL_PROVIDER_SERVICE`.
- O registro como agent service (REST, `AGENT_SERVICE_TYPE_EXTERNAL`, exige conexão do UC) é para agentes externos e, em Beta, não tem invocação em runtime; não foi usado.
- **Decisão (proposta; o mantenedor confirma no PR #15):** a camada do agente **não** é governada pelo gateway além da listagem. A governança de custo, limite e guardrail fica na camada do LLM (Opção 1, primeira camada). O agente é um App `agent-*` (ex.: `agent-atlas`); o consumo é atribuído pelo service principal do App. A SPEC-005 é ajustada na P3.8. Evidência em `docs/spikes/S0-results.md`.
- **Pendências (P3.8 / P10.2):** validar `request_tags` do agente, o `ask_genie` via `genie_one_mcp` como `MCP_SERVICE` na `usage` e o trace de tool call num App. Em princípio o gateway do LLM só vê o pedido e a resposta do modelo, não a execução das tools (premissa a validar): ela seria observada pelo trace MLflow e limitada pelas permissões do Unity Catalog e pela lista fechada de tools.
