# Tasks — 009-repo-foundation

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 0 — Fundação do repositório

### P0.1 🤖 Escrever a SPEC-009 (fundação do repo)

- **Pronto quando:** spec.md aprovado por você na revisão local (ainda não há repo remoto)
- **Passos:**
  - Detalhar o layout do monorepo, a política de branches, os checks obrigatórios e o template de PR
  - Critérios de aceite em Given/When/Then

### P0.2 🤖 `git init`, `.gitignore`, `.editorconfig`, layout de pastas vazio e README esqueleto

- **Depende de:** P0.1
- **Pronto quando:** Primeiro commit local `chore: bootstrap repository` contendo também todo o `docs/` já escrito
- **Passos:**
  - `.gitignore` cobrindo `.env*`, `data/generated/`, `.venv/`, `node_modules/`, `.databricks/`
  - Pastas: `cli/ pipeline/ semantic/ commission/ apps/agent apps/mcp apps/web eval/ spikes/ docs/`
  - README com seções vazias (será completado na Fase 13)

### P0.3 👤 Criar o repositório no GitHub e fazer o push inicial

- **Depende de:** P0.2
- **Pronto quando:** `origin/main` existe com o commit de bootstrap
- **Passos:**
  - Criar o repo na UI do GitHub (sem gh CLI)
  - `git remote add origin …` + `git push -u origin main`

### P0.4 🤖 Template de PR, template de issue e CONTRIBUTING (Conventional Commits, 1 task = 1 PR)

- **Depende de:** P0.3
- **Pronto quando:** PR #1 aberto com os templates
- **Passos:**
  - `.github/pull_request_template.md` com: task do roadmap, spec, o que mudou, por quê, como testar, checklist dos princípios
  - `CONTRIBUTING.md` com o fluxo `roadmap → branch → PR → review → merge`

### P0.5 🤖 CI base: ruff, mypy, pytest, gitleaks, link check dos docs

- **Depende de:** P0.4
- **Pronto quando:** Workflow `ci.yml` verde no PR e vermelho num PR de teste com segredo falso
- **Passos:**
  - `.github/workflows/ci.yml` com jobs separados (lint, types, test, secrets, docs)
  - `pre-commit` com ruff e gitleaks
  - Path filters para não rodar o Python em PRs só de docs

### P0.6 🤖 CODEOWNERS para `commission/**`, `semantic/**`, `docs/specs/mission.md`, `.claude/**`

- **Depende de:** P0.4
- **Pronto quando:** Arquivo no PR; a revisão do owner é exigida
- **Passos:**
  - Owner = você; documentar no CONTRIBUTING por que esses paths são sensíveis

### P0.7 👤 Branch protection da `main`: PR obrigatório, 1 aprovação, checks obrigatórios, sem force push

- **Depende de:** P0.5, P0.6
- **Pronto quando:** Um push direto na `main` é rejeitado
- **Passos:**
  - Settings → Branches → regra `main`
  - Marcar como obrigatórios os jobs do `ci.yml`
  - Exigir revisão de CODEOWNERS
