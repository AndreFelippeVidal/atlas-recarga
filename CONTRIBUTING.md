# Contribuindo com o Atlas Recarga

Este projeto segue **Spec-Driven Development**: nenhum código sem uma spec aprovada que o descreva. Leia primeiro a constituição: [mission](docs/specs/mission.md) · [tech-stack](docs/specs/tech-stack.md) · [roadmap](docs/specs/roadmap.md).

## Fluxo de uma task

```
roadmap (próxima [ ] com dependências [x]) → branch → commits → PR → CI verde → merge (mantenedor) → [x] no roadmap
```

1. **Escolha a task.** É a primeira `[ ]` do [roadmap](docs/specs/roadmap.md) cujas dependências estão `[x]`. Os passos estão no `tasks.md` da spec correspondente. Tasks 👤 são só do mantenedor.
2. **Crie a branch:** `task/<ID>-<slug>`, por exemplo `task/P4.3-pos-generation`. **Uma task por branch.**
   - **Exceção: agrupar tasks** só com pedido explícito do mantenedor. A branch leva o intervalo (`task/P1.3-P1.6-harness`), o título do PR lista os IDs e o corpo diz quem pediu o agrupamento e por quê. Todas as tasks do grupo recebem o mesmo `(#N)`.
3. **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) (`feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`), com escopo opcional: `feat(cli): add seasonality`.
4. **Se a implementação revelar que a spec está errada ou incompleta**, corrija a spec **no mesmo PR, num commit separado `docs(specs): …`**, antes do código. Mudança de decisão vira ADR.
5. **Abra o PR** com o template preenchido. Título: `<ID> <tipo>(escopo): descrição`.
6. **No mesmo PR**, marque a task `[x]` no roadmap com o número do PR: `- [x] **P4.3** … (#12)`.
7. **CI verde** (`ci-ok`) é obrigatório. **Merge: squash, feito pelo mantenedor.**

## Paths sensíveis
Listados em [`.github/CODEOWNERS`](.github/CODEOWNERS). Mudanças em `commission/` (etapa irreversível), `semantic/` (definição única das métricas), `docs/specs/mission.md`, `docs/adr/`, `.claude/` e `.github/` exigem atenção redobrada na revisão e justificativa no PR.

## Proteção da `main`
PR obrigatório, `ci-ok` obrigatório, histórico linear, sem force push, valendo também para admins. São 0 aprovações formais porque o projeto tem um único mantenedor e o GitHub não permite autoaprovação; a revisão humana é garantida por **só o mantenedor fazer o merge**. Ver [ADR-0014](docs/adr/0014-branch-protection-solo-maintainer.md).

## Agente de código
O projeto é construído com Claude Code. O contexto do agente está no [CLAUDE.md](CLAUDE.md); os limites estão na [SPEC-010](docs/specs/010-agent-harness/spec.md), aplicados em três camadas: permissões em [`.claude/settings.json`](.claude/settings.json), o hook [`.claude/hooks/guard.py`](.claude/hooks/guard.py) (testado em `tests/test_guard_hook.py`) e a proteção da `main` no GitHub.

| O agente… | Exemplos |
|---|---|
| **faz sozinho** | Implementar a partir de uma spec aprovada, rodar checks, commitar, fazer push da própria branch `task/*`, abrir PR |
| **pede a sua confirmação** | Editar `spec.md`, ADRs, `mission.md`, `tech-stack.md`, `commission/`, `semantic/`, `.claude/`, CI; deploy em `dev`; upload ao Volume |
| **nunca faz** | Merge, push na `main`, force push, `--no-verify`, mexer na proteção ou nas configurações do repo, deploy em `demo`, executar a aprovação de comissão, ler segredos |

Os commands do projeto: `/next-task` (mostra a próxima task aberta e para) e `/close-task <ID> <PR>` (marca `[x]` com o PR).

## Como reviso o agente
Todo PR do agente passa por quatro portões, nesta ordem:

1. **Checks locais** (o agente roda antes do push): `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`.
2. **Revisão automática antes do PR** (o agente roda e corrige o que for bloqueante):
   - o subagente [`spec-reviewer`](.claude/agents/spec-reviewer.md): aderência à spec, princípios da mission, Proibido do tech-stack, spec × código, testes;
   - o `/code-review`: bugs de correção no diff.

   Achados não corrigidos vão para o corpo do PR com o motivo.
3. **CI** (`ci-ok`): lint, tipos, testes (incluindo higiene do SDD e regras do hook), segredos e links.
4. **Revisão humana (você):** leia o diff e o checklist do template, confira se o comportamento novo está na spec e dê atenção redobrada aos paths do CODEOWNERS. **Só você faz o merge** (ADR-0014). Se algo não bate, peça mudanças no PR; o agente corrige na mesma branch.

Sinais de alerta na revisão: comportamento novo sem mudança na spec, diff em `commission/` ou `semantic/` sem justificativa, teste que não falharia se o código estivesse errado, escopo além do "pronto quando".

## Segredos
Nunca no repositório. Runtime: Databricks secrets ou recursos do bundle. CI: GitHub Actions secrets. O `gitleaks` bloqueia o PR se encontrar algo.
