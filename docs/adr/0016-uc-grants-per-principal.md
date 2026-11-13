# ADR-0016 — Conceder acesso no Unity Catalog por principal, não por grupo de workspace

- **Status:** proposto
- **Data:** 2026-11-13
- **Decisores:** mantenedor
- **Relacionados:** SPEC-004 §7, SPEC-003, ADR-0010, ADR-0003

## Contexto
A P7.3 aplicou `GRANT` em `atlas_readers` (USE CATALOG, USE SCHEMA, SELECT em `semantic`). Ao provar o critério 4 da SPEC-004 §8 com um service principal membro do grupo, o `PERMISSION_DENIED` em gold, silver, bronze e commission apareceu, mas o `SELECT` em `mv_recharges` também falhou: `does not have USE CATALOG on Catalog 'atlas_dev'`. O grupo criado pelo bundle e pelo `groups create` é um **WorkspaceGroup**: `is_member('atlas_readers')` é `true` e `is_account_group_member('atlas_readers')` é `false`. O Unity Catalog só avalia grants para grupos de conta. Os grupos `atlas_commission_*` (ADR-0010) têm o mesmo limite.

## Critérios de decisão
- O leitor lê só `semantic` e nada nas outras camadas.
- Funciona na Free Edition, sem console de conta.
- Reprodutível e idempotente pelo `setup_workspace.py`.

## Opções consideradas
1. **Grant direto a cada principal** (service principals e usuários), numa lista no script.
2. **Grupo de conta (account group)** com os grants no grupo.
3. **Dar `SELECT` ao grupo `users` ou `account users`.**

> Regra deste repositório: um ADR com menos de 2 alternativas descartadas não é aceito no review.

## Decisão
**Opção 1.** O `setup_workspace.py` aceita `--reader <principal>` (repetível) e concede os três grants a cada um. Os grants no grupo `atlas_readers` continuam, para o dia em que ele virar grupo de conta.

## Prós e contras das opções
### 1. Grant por principal
- 👍 Funciona hoje, verificado com um service principal no `dev`.
- 👎 Cada novo leitor (agente, MCP, React, Helena) exige rodar o script de novo.
### 2. Grupo de conta
- 👍 É o desenho original e escala.
- 👎 Não confirmado na Free Edition; depende de acesso ao console de conta. Descartada por ora.
### 3. Grupo `users`
- 👍 Simples.
- 👎 Abre `semantic` a todo usuário do workspace e quebra o princípio do menor privilégio. Descartada.

## Consequências
- **Positivas:** a leitura restrita a `semantic` passa a ser verificável de ponta a ponta.
- **Negativas, aceitas conscientemente:** lista de principals a manter no script; a segregação de funções da comissão (ADR-0010) precisa do mesmo tratamento na SPEC-003.
- **Plano B / gatilho para revisitar:** se a Free Edition passar a permitir grupos de conta, voltar à opção 2 e remover `--reader`.
