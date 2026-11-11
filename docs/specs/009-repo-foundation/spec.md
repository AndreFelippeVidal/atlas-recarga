# SPEC-009 — Fundação do repositório

> Roadmap: Fase 0 · Status: **a escrever** (primeira task da fase: P0.1)

## Objetivo
O repositório se comporta como o de um time profissional: `main` protegida, mudanças só por PR, validações automáticas que bloqueiam, segredos fora e um README que permite rodar sem perguntar.

## Escopo inicial (a detalhar em P0.1)
- Layout do monorepo e `.gitignore`
- Política de branches (`task/<id>-<slug>`), Conventional Commits, template de PR
- Checks obrigatórios do CI: ruff, mypy, pytest, gitleaks, links dos docs, `bundle validate`, tsc/eslint/vitest
- CODEOWNERS dos paths sensíveis e branch protection
