# ADR-0012 — Usar Claude Code como harness do agente de código, com limites explícitos

- **Status:** proposto (detalhado no PR de configuração do harness) · **Data:** 2026-11-11 · **Relacionados:** ADR-0010, todas as SPECs

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

## Limites (resumo; o detalhe vai para o `CLAUDE.md` e os hooks)

| O agente **pode** sozinho | O agente **não pode** (bloqueado por hook ou permissão) |
|---|---|
| Implementar código a partir de uma SPEC aprovada | Alterar `docs/specs/**` ou `docs/adr/**` sem pedido explícito |
| Rodar testes, lint, `atlas-cli` local e `databricks bundle validate` | `databricks bundle deploy -t demo`, `databricks jobs run-now atlas_commission_review` |
| Abrir branch, commitar e abrir PR | Fazer push na `main`, `--force`, merge de PR |
| Rodar a avaliação do agente (SPEC-008) | Alterar faixas de comissão (`commission/rules.py`) sem a aprovação do CODEOWNER |
| Ler logs e traces | Ler ou gravar `.env`, secrets ou tokens |

**Revisão:** todo PR passa pelo CI (lint, tipos, testes, segurança e, quando aplicável, o gate de avaliação), por um subagente de revisão e pela **revisão humana obrigatória** (branch protection). Os paths `commission/**` e `semantic/**` têm CODEOWNERS.

## Consequências
- **Positivas:** os limites são verificáveis (o hook nega e loga) e não dependem de o modelo "lembrar".
- **Negativas aceitas:** atrito: o deploy em `demo` e a aprovação de comissão são sempre manuais.
- **Revisitar:** depois das primeiras 3 features, medindo quantos bloqueios foram falsos positivos.
