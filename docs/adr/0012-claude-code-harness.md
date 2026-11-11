# ADR-0012 — Usar Claude Code como harness do agente de código, com limites explícitos

- **Status:** aceito (detalhado na SPEC-010) · **Data:** 2026-11-11 · **Relacionados:** SPEC-010, ADR-0010, ADR-0014

## Contexto
O desafio exige construir com um agente de código e deixar explícito o que ele faz sozinho, o que passa por revisão humana e como o código dele é revisado antes da `main`. O projeto mexe com uma etapa financeira irreversível (comissão) e com permissões de dados.

## Critérios de decisão
- Contexto do projeto carregado de forma confiável (SPECs, convenções, limites).
- Limites **aplicados pela ferramenta** (hooks e permissões), não só pedidos em texto.
- Integração com o fluxo de PR e com as validações automáticas.

## Opções consideradas
1. **Claude Code** com `CLAUDE.md`, skills/commands, hooks e permissões em `.claude/settings.json`
2. **Cursor** com rules
3. **Codex CLI ou Aider** com `AGENTS.md`

## Decisão
**Claude Code.** Hooks (`PreToolUse`) permitem **bloquear** ações perigosas de forma determinística; as permissões são declaradas no repositório; o fluxo SDD (spec → implementação → revisão) já é a forma de trabalho do autor.

## Prós e contras
**Claude Code.** 👍 Hooks e permissões versionados; subagentes de revisão; funciona no terminal junto do Databricks CLI. 👎 Vendor-specific; o `CLAUDE.md` precisa de manutenção ativa.
**Cursor.** 👍 Ótima experiência no IDE. 👎 Limites menos determinísticos (rules são orientação, não bloqueio).
**Codex ou Aider.** 👍 `AGENTS.md` é um padrão aberto. 👎 Menos mecanismos de bloqueio por hook nativo.

## Limites
A matriz completa e verificável está na [SPEC-010 §3](../specs/010-agent-harness/spec.md). Ela tem três níveis:
- **Livre:** implementar a partir de uma spec aprovada, rodar checks e o CLI local, commitar, fazer push da própria branch `task/*`, abrir PR.
- **Exige confirmação (`ask`):** editar specs, ADRs, a constituição, `commission/`, `semantic/`, `.claude/` e o CI; fazer deploy em `dev`; fazer upload para o Volume.
- **Proibido (`deny`):** merge de PR, push na `main`, force push, mexer na proteção do repo, deploy em `demo`, executar a aprovação de comissão, ler segredos, `--no-verify`.

A aplicação é feita em **três camadas**: permissões no `settings.json`, o hook `PreToolUse` (que inspeciona o comando inteiro, porque uma regra Bash casa só com o comando como foi escrito) e a proteção da `main` no GitHub (ADR-0014).

**Revisão:** checks locais → `/code-review` → PR com template → CI (`ci-ok`) → **revisão e merge humanos**. O agente nunca faz merge.

## Consequências
- **Positivas:** os limites são verificáveis (o hook nega e loga) e não dependem de o modelo "lembrar".
- **Negativas aceitas:** atrito: editar uma spec ou um path sensível exige confirmação, e o deploy em `demo` e a aprovação de comissão são sempre manuais. O hook é código próprio: mantê-lo e testá-lo é custo do projeto.
- **Revisitar:** depois das primeiras 3 features, medindo quantos bloqueios foram falsos positivos.
