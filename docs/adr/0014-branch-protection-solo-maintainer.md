# ADR-0014 — Proteger a `main` com PR + checks obrigatórios e 0 aprovações (mantenedor único)

- **Status:** aceito · **Data:** 2026-11-11 · **Relacionados:** SPEC-009, ADR-0012

## Contexto
O desafio exige uma branch principal protegida, com mudanças entrando por pull request. O projeto tem **um único mantenedor humano** e um agente de código. O GitHub **não permite que o autor de um PR o aprove**, e os PRs são abertos pelo mantenedor (via agente, com as credenciais dele). Exigir 1 aprovação travaria todo merge.

## Critérios de decisão
- Nenhuma mudança chega à `main` sem PR e sem CI verde.
- A regra vale para todos, inclusive o admin (sem bypass rotineiro).
- A revisão humana de fato acontece, em vez de existir só no papel.

## Opções consideradas
1. **PR obrigatório + check `ci-ok` obrigatório + 0 aprovações, valendo para admins**; a revisão humana é garantida porque só o mantenedor faz o merge (o agente é bloqueado pelo harness)
2. **1 aprovação obrigatória + bypass de admin**
3. **1 aprovação dada por uma segunda conta ou bot** (por exemplo, o agente com outro token)
4. **Sem proteção**, com a disciplina documentada

## Decisão
**Opção 1.** A proteção técnica cobre o que uma máquina pode garantir (PR, CI, histórico linear, sem force push). A revisão humana é garantida pela **separação de quem pode fazer o merge**: o agente de código nunca faz merge (deny de `gh pr merge` no harness, SPEC-010).

## Prós e contras
**Opção 1.** 👍 Sem bypass; a regra vale para o admin; honesta sobre o contexto. 👎 A "aprovação" não aparece como review formal no GitHub; a garantia depende do harness (Fase 1). **Exceção registrada:** até o fim da Fase 0, o agente fez o merge dos PRs P0.x por autorização explícita do mantenedor.
**Opção 2.** 👍 Aparenta rigor. 👎 Todo merge vira um bypass; a regra existe só no papel.
**Opção 3.** 👍 Review formal visível. 👎 O revisor seria o próprio agente, o que é teatro de revisão; ainda viola a separação entre quem escreve e quem aprova.
**Opção 4.** 👍 Zero atrito. 👎 Não atende ao desafio; um push acidental na `main` passa.

## Consequências
- **Positivas:** um push direto na `main` é rejeitado; todo merge tem CI verde e histórico linear.
- **Negativas aceitas:** o CODEOWNERS fica informativo (exigir a revisão do owner travaria o merge pelo mesmo motivo).
- **Gatilho para revisitar:** entrada de um segundo mantenedor humano. Nesse caso, subir para 1 aprovação + revisão de CODEOWNERS obrigatória.
