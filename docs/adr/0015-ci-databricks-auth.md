# ADR-0015 — Autenticar o `bundle validate` do CI com secrets num GitHub Environment

- **Status:** aceito · **Data:** 2026-11-12 · **Relacionados:** SPEC-002, ADR-0001, ADR-0014

## Contexto
A P5.1 exige `databricks bundle validate -t dev` no CI, e o comando precisa autenticar num workspace. O repositório é público, o mantenedor é único e a Free Edition só tem o usuário do mantenedor (sem service principal). Segredo versionado é proibido.

## Critérios de decisão
- O segredo nunca aparece no repositório nem nos logs.
- Um PR de fork não consegue usá-lo.
- Revogar e trocar o token é barato.
- O `ci-ok` fecha sem aprovação manual (ADR-0014).

## Opções consideradas
1. **PAT em secrets de um GitHub Environment (`ci-databricks`)**, job com `permissions: contents: read`, gatilhos `pull_request` e `push` na `main` (nunca `pull_request_target`), e o job pulado em PR de fork e em PR do Dependabot
2. **Validate offline**, sem workspace
3. **Job não bloqueante**, fora do `ci-ok`, até existirem secrets
4. **Secrets no nível do repositório**, sem Environment

## Decisão
**Opção 1.** O token tem validade de 90 dias e é revogável. O Environment isola os secrets e mostra cada uso na aba *Deployments*. O Environment também é usado no `push` na `main`. O Dependabot não recebe secrets de Environment (só "Dependabot secrets"), então o job é pulado nos PRs dele em vez de falhar. Sem "Required reviewers" (travaria o `ci-ok`) e sem restrição por branch (PRs rodam em `refs/pull/N/merge`). O CLI fica fixado em 1.24.0 e a action, por SHA.

## Prós e contras
**Opção 1.** 👍 Valida de verdade; segredo isolado; fork não acessa. 👎 O token é do usuário e tem os poderes dele; quem faz merge de um workflow alterado pode tentar exfiltrá-lo; precisa de rotação.
**Opção 2.** 👍 Sem segredo. 👎 O CLI exige workspace para resolver o target; só validaria YAML, o que não cumpre o critério da task.
**Opção 3.** 👍 Sem fricção. 👎 O gate não bloqueia, então a validação existe só no papel.
**Opção 4.** 👍 Mais simples. 👎 Qualquer workflow do repositório lê o segredo; não há trilha de uso.

## Consequências
- **Positivas:** o CI valida o bundle de verdade; revogar o token é suficiente em caso de vazamento.
- **Negativas aceitas:** o token pessoal tem poderes amplos. Nunca usar `pull_request_target` nem imprimir o token. Renovar o token a cada 90 dias (lembrete do mantenedor).
- **Gatilho para revisitar:** disponibilidade de service principal na Free Edition, ou um segundo mantenedor.
