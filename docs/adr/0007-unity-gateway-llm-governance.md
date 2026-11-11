# ADR-0007 — Governar o tráfego de IA pelo Unity Gateway

- **Status:** aceito (depende do Spike S0.1/S0.2) · **Data:** 2026-11-11 · **Relacionados:** SPEC-005, ADR-0008

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
