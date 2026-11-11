# Contribuindo com o Atlas Recarga

Este projeto segue **Spec-Driven Development**: nenhum código sem uma spec aprovada que o descreva. Leia primeiro a constituição: [mission](docs/specs/mission.md) · [tech-stack](docs/specs/tech-stack.md) · [roadmap](docs/specs/roadmap.md).

## Fluxo de uma task

```
roadmap (próxima [ ] com dependências [x]) → branch → commits → PR → CI verde → merge (mantenedor) → [x] no roadmap
```

1. **Escolha a task.** É a primeira `[ ]` do [roadmap](docs/specs/roadmap.md) cujas dependências estão `[x]`. Os passos estão no `tasks.md` da spec correspondente. Tasks 👤 são só do mantenedor.
2. **Crie a branch:** `task/<ID>-<slug>`, por exemplo `task/P4.3-pos-generation`. **Uma task por branch.**
3. **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) (`feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`), com escopo opcional: `feat(cli): add seasonality`.
4. **Se a implementação revelar que a spec está errada ou incompleta**, corrija a spec **no mesmo PR, num commit separado `docs(specs): …`**, antes do código. Mudança de decisão vira ADR.
5. **Abra o PR** com o template preenchido. Título: `<ID> <tipo>(escopo): descrição`.
6. **No mesmo PR**, marque a task `[x]` no roadmap com o número do PR: `- [x] **P4.3** … (#12)`.
7. **CI verde** (`ci-ok`) é obrigatório. **Merge: squash, feito pelo mantenedor.**

## Paths sensíveis
Listados em [`.github/CODEOWNERS`](.github/CODEOWNERS) _(P0.6)_. Mudanças em `commission/` (etapa irreversível), `semantic/` (definição única das métricas), `docs/specs/mission.md`, `docs/adr/`, `.claude/` e `.github/` exigem atenção redobrada na revisão e justificativa no PR.

## Proteção da `main`
PR obrigatório, `ci-ok` obrigatório, histórico linear, sem force push, valendo também para admins. São 0 aprovações formais porque o projeto tem um único mantenedor e o GitHub não permite autoaprovação; a revisão humana é garantida por **só o mantenedor fazer o merge**. Ver [ADR-0014](docs/adr/0014-branch-protection-solo-maintainer.md).

## Agente de código
O projeto é construído com Claude Code. O que o agente pode fazer sozinho, o que é bloqueado e como o trabalho dele é revisado será definido na [SPEC-010](docs/specs/010-agent-harness/spec.md) (Fase 1).

## Segredos
Nunca no repositório. Runtime: Databricks secrets ou recursos do bundle. CI: GitHub Actions secrets. O `gitleaks` bloqueia o PR se encontrar algo.
