# ADR-0023 — O `atlas-web` chama o `atlas-agent` por streaming, como o usuário (OBO)

- **Status:** proposto
- **Data:** 2026-11-19
- **Decisores:** mantenedor
- **Relacionados:** SPEC-005, SPEC-007, ADR-0008, ADR-0009, ADR-0016, ADR-0021

## Contexto
O dashboard (`atlas-web`) vai ganhar um painel de chat para a Diretoria Comercial perguntar sem sair do mapa. O agente já existe como App (`agent-atlas`, SPEC-005) e responde em `/invocations`, no formato Responses, com `stream=true`. O mantenedor decidiu que o `atlas-web` **chama** o agente (3 Apps mantidos, ADR-0009) e que a resposta **chega em streaming**, com o texto aparecendo aos poucos.

Há um conflito a resolver: hoje o agente **descarta os deltas de texto** e só emite o item de saída completo, porque o filtro de PII (ADR-0021) mascara o texto depois de pronto; um delta cru sairia antes da máscara. Streaming de verdade exige mascarar o fluxo.

Restrições: o `atlas-web` só lê `semantic` e não calcula métrica (princípios da mission); o agente segue somente leitura e com a citação `Fonte:`; o trace do agente precisa identificar o usuário (P12.14).

## Critérios de decisão
- Menor privilégio: o SP do `atlas-web` não pode ganhar acesso a dados nem ao Genie.
- Identidade do usuário no trace do agente.
- Nenhum PII sai do agente, nem em pedaços.
- Texto aparecendo aos poucos, sem que o frontend calcule nada.
- Custo de manutenção para um mantenedor único.

## Opções consideradas
1. **`atlas-web` repassa a chamada ao `atlas-agent`, com o token do usuário (OBO), em streaming SSE** (escolhida)
2. **`atlas-web` chama o `atlas-agent` com o próprio service principal**
3. **Agente embutido no processo do `atlas-web`**
4. **Link ou iframe para a chat UI do `agent-atlas`**
5. **Resposta inteira, sem streaming** (descartada pelo mantenedor em 2026-11-19: quer ver o texto se completando)

> Regra deste repositório: um ADR com menos de 2 alternativas descartadas não é aceito no review.

## Decisão
**Opção 1.**

**Autenticação.** O `atlas-web` declara `user_api_scopes` e repassa o token do usuário (`x-forwarded-access-token`) no cabeçalho `Authorization: Bearer` da chamada ao `agent-atlas`. O agente enxerga o usuário real (a tag `user` do trace já sai de `current_user.me()` com esse token, SPEC-005 §5). O escopo exato que o Databricks exige para um App chamar outro App em nome do usuário **não está verificado**: a P12.14 o confirma no `dev` e, se o OBO não funcionar, reabre este ADR (gatilho abaixo).

**Permissões.** O SP do `atlas-web` continua só com `SELECT` em `semantic` e `CAN_USE` no warehouse. Ele **não** ganha `CAN_RUN` no Genie nem `EXECUTE` em nada. O usuário precisa de `CAN_USE` no `agent-atlas` (permissão do App, concedida pelo mantenedor no workspace); sem ela a rota devolve `403 PERMISSION_DENIED`.

**Contrato da rota** `POST /api/chat`:
- Corpo: `{"message": str, "conversation_id": str | null}`. `message` não vazia após `strip` e com no máximo **2.000 caracteres**; fora disso, `400 INVALID_ARGUMENT`. O `conversation_id` (opcional, gerado pelo frontend) vai ao agente como `context.conversation_id`, o mesmo que alimenta a sessão do trace.
- Resposta: `200 text/event-stream` (SSE) com três eventos: `delta` (`{"text": "..."}`, trecho a acrescentar), `done` (`{"text": "..."}`, o texto final completo, que **substitui** o acumulado) e `error` (`{"code": "...", "message": "..."}`, terminal). Nenhum outro dado cruza o contrato: o `atlas-web` não interpreta números, só repassa texto.
- Erros antes do primeiro byte viram status HTTP: `400 INVALID_ARGUMENT`, `403 PERMISSION_DENIED`, `429 RATE_LIMITED` (limite por usuário do `atlas-web`), `503 AGENT_UNAVAILABLE`. Depois do primeiro byte viram o evento `error`: `AGENT_UNAVAILABLE` (agente parado ou 5xx), `RATE_LIMITED` (429 do agente ou do gateway), `TIMEOUT` e `AGENT_ERROR`.
- Timeouts: 10 s para conectar, **60 s sem nenhum byte vindo do agente** (idle, pois o agente chama Genie e tools antes do primeiro texto) e **120 s** no total. O `atlas-web` envia ao navegador um comentário SSE (`: ping`) a cada 15 s, que não é evento e o painel ignora. Estourar um timeout encerra com `error TIMEOUT`; o `atlas-web` fecha a conexão com o agente.
- Sem retentativa automática (a pergunta pode ter custo de LLM) e sem cache de respostas.
- Um limite por usuário de **10 mensagens por minuto**, em memória por instância (o App tem uma). Ele é um freio de abuso, não uma garantia sobre o gateway: os 30 req/min do gateway valem para o App do agente inteiro e uma mensagem pode virar várias chamadas de LLM (ADR-0021). O número é provisório e a P12.14 o confere com o uso real.

**Streaming sem furar o filtro de PII.** O agente passa a emitir os deltas de texto, mas por um **mascarador de fluxo** (algoritmo na SPEC-005 §4): só libera texto até uma fronteira de espaço que deixe pelo menos 40 caracteres retidos no fim, de modo que um CPF, telefone ou e-mail cortado entre deltas é mascarado inteiro (e-mail e CPF não têm espaço; telefone com DDD e rótulo de CPF cabem nos 40). O item `response.output_item.done` traz o texto completo mascarado, que é a fonte da verdade (o evento `done` da rota). O trace continua marcando `pii_masked = true`. Isso altera a SPEC-005 §4 e o ADR-0021 (nota de alteração nele); a mudança entra na P12.13 junto com a rota, e o golden set (SPEC-008) roda sobre o item final e não muda.

**Citação.** O bloco `Fonte:` faz parte do texto do agente; o painel o exibe sem tratar, e o frontend não calcula nem reformata métrica.

## Prós e contras das opções
### 1. Repasse com OBO, SSE
- 👍 O trace do agente identifica o usuário; o SP do web não soma permissões; o agente é o único dono da lógica e da recusa.
- 👎 O escopo de OBO entre Apps não está confirmado; o streaming exige um mascarador no agente e um proxy SSE no web; o limite de 30 req/min do gateway é compartilhado com a chat UI do próprio agente.
### 2. Chamada com o SP do web
- 👍 Simples: sem escopo de usuário; um grant fixo (`CAN_USE`) no SP.
- 👎 O trace identifica o SP, não a pessoa (falha o critério da P12.14); a identidade teria de viajar num cabeçalho confiado, forjável por quem alcança o agente; qualquer usuário do dashboard passa a usar o agente com a permissão do SP.
### 3. Agente embutido no `atlas-web`
- 👍 Sem chamada de rede entre Apps; um slot a menos de configuração.
- 👎 Soma as permissões do agente (Genie, model service, trace tables) ao SP do web, o que reabre a opção 4 do ADR-0009 (monolito); um deploy do dashboard derruba o agente; duplica dependências (LangGraph, MLflow) num App que hoje é só FastAPI.
### 4. Link ou iframe para a chat UI do agente
- 👍 Zero código novo.
- 👎 Fora do dashboard: o usuário sai do mapa, perde o contexto de mês e medida e a experiência única; a UI vem do template clonado (ADR-0019) e não pode ser incorporada com a mesma autenticação sem mexer no template.
### 5. Sem streaming
- 👍 Contrato mais simples (um JSON), sem mascarador de fluxo.
- 👎 A resposta leva segundos para aparecer inteira (p95 do agente na SPEC-005 §7 é 15 s); rejeitada pelo mantenedor.

## Consequências
- **Positivas:** chat no mapa sem novo slot de App; identidade do usuário ponta a ponta; o `atlas-web` segue lendo só `semantic` e sem lógica de métrica.
- **Negativas, aceitas conscientemente:** o `atlas-web` ganha um proxy SSE e um limite por usuário; o agente ganha o mascarador de fluxo (o texto aparece com um atraso de pelo menos 40 caracteres); o gateway é compartilhado, então o chat do dashboard e a chat UI do agente disputam os mesmos 30 req/min; o auto-stop de 24 h agora também deixa o chat fora do ar quando o `agent-atlas` está parado (erro `AGENT_UNAVAILABLE`, runbook do ADR-0009).
- **Plano B / gatilho para revisitar:** reabrir se a P12.14 mostrar que o token do usuário não autentica o `agent-atlas` (passar à opção 2 com `CAN_USE` no SP e a identidade conferida pelo agente), se o mascarador deixar vazar PII em teste, ou se o p95 do dashboard (P12.8) piorar com o chat.
