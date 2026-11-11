# Tasks — 010-agent-harness

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 1 — Harness do agente de código

### P1.1 🤖 Escrever a SPEC-010 (harness): o que o agente faz, o que é bloqueado, como é revisado

- **Depende de:** P0.7
- **Pronto quando:** spec.md aprovado; ADR-0012 vira `aceito`
- **Passos:**
  - Matriz pode/não pode do ADR-0012 em regras verificáveis
  - Lista de hooks com o comando bloqueado e a mensagem

### P1.2 🤖 `CLAUDE.md`: missão resumida, princípios, mapa do repo, comandos, como pegar a próxima task

- **Depende de:** P1.1
- **Pronto quando:** O agente, numa sessão nova, responde corretamente "qual a próxima task?"
- **Passos:**
  - Apontar para `docs/specs/mission.md`, `tech-stack.md` e `roadmap.md` em vez de duplicar
  - Seção "Nunca faça" espelhando o Proibido do tech-stack

### P1.3 🤖 `.claude/settings.json`: permissões allow/deny

- **Depende de:** P1.1
- **Pronto quando:** `deny` cobre `.env*`, `git push origin main`, `--force`, `bundle deploy -t demo`, `jobs run-now *commission_review*`
- **Passos:**
  - Allow: testes, lint, `atlas-cli`, `databricks bundle validate`
  - Deny explícito para os itens do ADR-0012

### P1.4 🤖 Hooks `PreToolUse` que bloqueiam edições em `docs/specs/**` e `docs/adr/**` sem a flag da task e em `commission/rules.py`

- **Depende de:** P1.3
- **Pronto quando:** Teste manual: o agente tenta editar e o hook nega com uma mensagem clara
- **Passos:**
  - Script em `.claude/hooks/` com testes em pytest
  - Logar os bloqueios em `.claude/hooks.log` (ignorado no git)

### P1.5 🤖 Commands `/next-task` (lê o roadmap e propõe a próxima task aberta) e `/close-task` (marca [x] e linka o PR)

- **Depende de:** P1.2
- **Pronto quando:** `/next-task` devolve a primeira task aberta cujas dependências estão concluídas
- **Passos:**
  - `.claude/commands/next-task.md` e `close-task.md`
  - `/next-task` nunca começa uma task 👤

### P1.6 🤖 Fluxo de revisão: subagente revisor + checklist de princípios no PR + revisão humana obrigatória

- **Depende de:** P1.5
- **Pronto quando:** Seção "Como reviso o agente" no CONTRIBUTING e um PR de exemplo revisado
- **Passos:**
  - Subagente com foco em princípios, segurança e aderência à spec
  - Usar `/code-review` antes de pedir a revisão humana
