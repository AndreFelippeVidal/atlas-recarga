# ADR-0021 — Limites do agente no gateway; PII no App; gasto só com alerta

- **Status:** proposto
- **Data:** 2026-11-17
- **Decisores:** mantenedor
- **Relacionados:** SPEC-005 §4 a §6, ADR-0007, ADR-0013, ADR-0016

## Contexto
A SPEC-005 §4 pede ao Unity Gateway quatro controles que o S0.1 não chegou a validar: rate limit de 30 requisições por minuto por usuário, teto de gasto mensal, detecção de PII na saída e bloqueio de tópicos. O spike da P10.5 (CLI 1.24.0, perfil `andrevidal`, 2026-11-17) leu o `system.ai.gpt-oss-120b` e a API de model services:

- O model service só aceita `routing`, `rate_limits` e `inference_table` (e `comment`). **Não há campo de guardrail** (PII, tópico): o `service_policies` citado no S0.1 não está na API do CLI.
- Os limites têm a chave `RATE_LIMIT_KEY_USER`, `_USER_GROUP`, `_SERVICE_PRINCIPAL`, `_SERVICE` ou `_USER_DEFAULT`, com `requests` e/ou `tokens` por minuto ou hora. Não existe período mensal.
- O orçamento de conta (`BUDGET_RESOURCE_TYPE_UNITY_AI_GATEWAY`) **avisa e não bloqueia**, e é uma operação de conta.
- O `system.ai.gpt-oss-120b` é um serviço de sistema compartilhado e sem limite; alterá-lo afetaria o workspace todo.
- O gateway enxerga o **service principal do App** como `requester`, não o usuário final. "Por usuário" no gateway é, na prática, "por App".

## Critérios de decisão
- Controle aplicado fora do código do agente sempre que a plataforma permitir (ADR-0007).
- Não afetar outros usos do workspace.
- Cada lacuna da plataforma tem um substituto explícito e testável.
- Nada de IA ou de heurística opaca no controle.

## Opções consideradas
1. **Model service próprio no bundle**, com destino `system.ai.gpt-oss-120b`, `rate_limits` e `inference_table`; PII por filtro determinístico no App; gasto por limite de tokens/hora no serviço mais alerta de orçamento.
2. **Aplicar os limites no `system.ai.gpt-oss-120b`.**
3. **Tudo no código do App** (rate limit, contador de gasto, PII), sem tocar o gateway.
4. **Aceitar a ausência** de PII e de teto, só com o rate limit.

## Decisão
**Opção 1.**
- **Rate limit:** `RATE_LIMIT_KEY_USER_DEFAULT` de 30 requisições por minuto, como na spec. Como o requester é o service principal do App, o limite vale para o App inteiro; a identificação do usuário final fica na tag `user` do trace.
- **Teto de gasto:** `RATE_LIMIT_KEY_SERVICE` de 500.000 tokens por hora. O pior turno medido na P10.2 foi de 143.841 tokens, então o teto permite cerca de 3 turnos dessa extensão por hora, e um turno comum fica muito abaixo disso. É um freio por hora, não por mês; o aviso mensal vem do orçamento de conta com alerta por e-mail, criado pelo mantenedor (ele notifica, não bloqueia).
- **PII:** filtro determinístico no App sobre o texto final (CPF, telefone, e-mail), que substitui o trecho por uma máscara e marca o trace com `pii_masked = true`. O bloqueio de tópicos continua sendo o prompt `v1` (recusa sem tool), medido pelo golden set.
- **Inference table:** `atlas_<env>.observability.agent_llm_payload`, no mesmo schema das trace tables.

## Prós e contras das opções
### Opção 1
- 👍 Limite aplicado pelo gateway, mesmo com bug no agente; não toca o serviço de sistema; configuração versionada no bundle.
- 👎 O limite por usuário real não existe no gateway; PII fica no código do agente; teto por hora, não por mês.
### Opção 2
- 👍 Nenhum serviço novo.
- 👎 Afeta todo o workspace e depende de `MANAGE` num recurso de sistema; fora do bundle.
### Opção 3
- 👍 Controle por usuário real e por mês.
- 👎 O guardrail vive no código que ele deveria proteger (o motivo do ADR-0007).
### Opção 4
- 👍 Nenhum código novo.
- 👎 Deixa a saída sem política de PII, que a spec exige.

## Consequências
- **Positivas:** o 429 é testável de ponta a ponta; o gasto tem freio e alerta; o payload do LLM fica auditável.
- **Negativas, aceitas conscientemente:** sem limite por usuário final no gateway; sem teto mensal que bloqueie; a máscara de PII é por padrão (regex) e não pega todo dado pessoal.
- **Plano B / gatilho para revisitar:** se o gateway ganhar guardrails ou `service_policies` na API, mover a PII para lá; se o App passar a repassar o usuário ao gateway, trocar a chave para `RATE_LIMIT_KEY_USER`.
