# SPEC-010 — Harness do agente de código (Claude Code)

> Roadmap: Fase 1 · Status: **a escrever** (primeira task da fase: P1.1)

## Objetivo
Tornar explícito e aplicável pela ferramenta o que o agente de código pode fazer sozinho, o que exige você e como o código dele é revisado antes da `main` (detalha o ADR-0012).

## Escopo inicial (a detalhar em P1.1)
- `CLAUDE.md` apontando para a constituição (mission, tech-stack, roadmap)
- `.claude/settings.json` com allow/deny
- Hooks `PreToolUse` com bloqueios testados
- Commands `/next-task` e `/close-task`
- Fluxo de revisão: subagente → `/code-review` → revisão humana
