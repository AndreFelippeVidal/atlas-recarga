# Tasks — 009-repo-foundation

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 0 — Fundação do repositório

### P0.1 🤖 Escrever a SPEC-009 (fundação do repo)

- **Pronto quando:** SPEC-009 e ADR-0014 aprovados
- **Passos:**
  - Detalhar o layout do monorepo, a política de branches, os checks obrigatórios e o template de PR
  - Critérios de aceite em Given/When/Then

### P0.2 🤖 `.gitignore` completo, `.editorconfig`, layout de pastas (SPEC-009 §2) e README esqueleto

- **Depende de:** P0.1
- **Pronto quando:** PR mergeado; as pastas da SPEC-009 §2 existem, cada uma com um README de uma linha
- **Passos:**
  - `.gitignore` cobrindo `.env*`, `data/generated/`, `.venv/`, `node_modules/`, `.databricks/`
  - Pastas: `cli/ pipeline/ semantic/ commission/ apps/agent apps/mcp apps/web eval/ spikes/ docs/`
  - README com seções vazias (será completado na Fase 13)

### P0.3 👤 Criar o repositório no GitHub e fazer o push inicial

- **Depende de:** P0.2
- **Pronto quando:** `origin/main` existe com o commit de bootstrap
- **Passos:**
  - `gh repo create --public --source=. --push`
  - `git remote add origin …` + `git push -u origin main`

### P0.4 🤖 Template de PR, template de issue e CONTRIBUTING (Conventional Commits, 1 task = 1 PR)

- **Depende de:** P0.3
- **Pronto quando:** PR mergeado com os templates; o próximo PR já usa o template
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

### P0.6 🤖 CODEOWNERS dos paths sensíveis (SPEC-009 §8)

- **Depende de:** P0.4
- **Pronto quando:** CODEOWNERS válido (sem erros na aba do GitHub); informativo com 0 aprovações (ADR-0014)
- **Passos:**
  - Owner = você; documentar no CONTRIBUTING por que esses paths são sensíveis

### P0.7 👤 Branch protection da `main` conforme SPEC-009 §5 (PR + `ci-ok`, 0 aprovações, vale para admins)

- **Depende de:** P0.5, P0.6
- **Pronto quando:** Um push direto na `main` é rejeitado
- **Passos:**
  - `gh api -X PUT repos/:owner/:repo/branches/main/protection` com os valores da SPEC-009 §5
  - Check obrigatório: só `ci-ok`
  - Verificar: um push direto na `main` é rejeitado
  - Exceção (ADR-0014): executada pelo agente por autorização explícita do mantenedor
