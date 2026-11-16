# ADR-0019 — Usar a chat UI do template oficial no `agent-atlas`, clonada na subida

- **Status:** proposto
- **Data:** 2026-11-16
- **Decisores:** mantenedor
- **Relacionados:** SPEC-005, ADR-0006, ADR-0009, ADR-0007

## Contexto
A SPEC-005 §2 manda partir do template oficial de agente em Apps, que inclui uma chat UI (`e2e-chatbot-app-next`). O `scripts/start_app.py` do template **clona** essa UI de `github.com/databricks/app-templates` (ramo padrão, sem commit fixado) e roda `npm install` e `npm build` a cada subida do App. O App roda com o service principal do agente e sobe de novo a cada auto-stop de 24h (ADR-0009). Isso é código remoto não fixado em runtime, não coberto pelo `tech-stack.md`.

## Critérios de decisão
- Entregar a chat UI sem escrever frontend (a P10.2 é um esqueleto; o React com mapa é da SPEC-007).
- Reprodutibilidade: a demo não pode quebrar por uma mudança externa no meio do caminho.
- Superfície de supply chain no service principal do agente (somente leitura, sem permissão fora de `semantic`).
- Custo de manutenção para um mantenedor único.

## Opções consideradas
1. **Usar a UI do template, clonada na subida, sem fixar o commit** (o que o template faz)
2. **Usar a UI do template e fixar o commit** (editar o `start_app.py` vendorizado para dar `checkout` num SHA)
3. **Escrever a chat UI própria** (React, no `apps/agent`)
4. **Sem chat UI**: o agente só expõe `/invocations`, chamado por script ou pelo Genie/Playground

> Regra deste repositório: um ADR com menos de 2 alternativas descartadas não é aceito no review.

## Decisão
Escolhemos a **opção 1 para o MVP**, com a opção 2 como gatilho de revisão. O ganho é uma chat UI funcionando sem frontend próprio; o risco é limitado: o App é somente leitura, o service principal só alcança `semantic`, o Genie Space e o model service, e a UI é um pacote npm de um repositório da própria Databricks. Em 2026-11-16 o `main` do `app-templates` estava em `71f815f6a6b0`, e a subida do `dev` funcionou com ele.

## Prós e contras das opções
### 1. UI do template, sem fixar
- 👍 Zero código nosso; recebe correções do template.
- 👎 Uma mudança no `main` do template pode quebrar a subida ou alterar a UI sem aviso; código remoto executado no App.
### 2. UI do template, com SHA fixado
- 👍 Reprodutível; fecha o risco de supply chain.
- 👎 Exige editar um arquivo vendorizado (divergência do template a cada atualização) e atualizar o SHA à mão.
### 3. Chat UI própria
- 👍 Controle total; sem clone em runtime.
- 👎 Frontend extra para manter, fora do escopo da P10.2; duplica trabalho da SPEC-007.
### 4. Sem chat UI
- 👍 Sem frontend nem clone.
- 👎 O critério "responde olá" e a demo para a Diretoria Comercial perdem a interface; o golden set (SPEC-008) não precisa dela, mas a demo sim.

## Consequências
- **Positivas:** a chat UI existe desde a P10.2; nada de frontend para manter.
- **Negativas, aceitas conscientemente:** dependência de um repositório externo a cada subida; `npm install` no start aumenta o tempo de subida (cerca de 30 s no `dev`); o `README` de `apps/agent` registra a origem.
- **Plano B / gatilho para revisitar:** reabrir e passar para a opção 2 se a subida quebrar por mudança no template, se a demo (P13) exigir reprodutibilidade estrita, ou antes do `v1.0.0`; passar para a opção 3 se a SPEC-007 passar a oferecer um componente de chat reutilizável.
