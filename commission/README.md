# commission

Regras e jobs do fechamento de comissão. Governado pela [SPEC-003](../docs/specs/003-commission-closing/spec.md). **Path sensível (etapa irreversível):** CODEOWNERS; o agente de código não altera as regras sem pedido explícito.

## Rascunho do lote (P8.3)

`draft.py` calcula o lote `COM-YYYY-MM-v1` em `draft` a partir de `gold.agg_pos_month` (job `atlas_commission_draft`). Faixas e taxas vêm de `rules.TIERS`; o arredondamento é HALF_EVEN por linha (`bround`). O mês é o anterior ao corrente em America/Sao_Paulo, ou o `reference_month` (`YYYY-MM`) do job. Se o `v1` já existe, o job recusa e não altera nada. `reconcile.py` (task `reconcile_draft`, a seguinte no mesmo job) recalcula o lote em SQL puro sobre `gold.fct_recharges`, confere os totais de controle e grava `commission.reconciliation` (uma linha por lote; falha o job se a diferença não for R$ 0,00). Como `calculate_draft` recusa um `v1` já existente, depois de corrigir uma falha de reconciliação use *Repair run* só da task `reconcile_draft`, não um novo run do job. `flags.py` (task `flag_draft`, depois da reconciliação) grava em `batch_lines.flags` os flags `spike_3x`, `fractioning_suspect`, `tier_jump` e `closed_pos` nas linhas de PDV (só destaque, não bloqueia; reexecutar substitui). Precisa de `gold.fct_recharges.recharge_ts_utc`, então rode o pipeline `atlas_medallion` antes. A aprovação é o job `atlas_commission_review` (seção abaixo).

## Lote de ajuste `ADJ` (P8.10)

Um lote `locked` nunca muda (SPEC-003 §7). Para corrigir um erro descoberto depois, rode o job `atlas_commission_draft` com `adjust_batch_id` = um lote `locked` do mês (ex.: `COM-2026-10-v1`). `adjust.py` recalcula o mês com `rules.py` sobre o gold atual e grava `COM-2026-10-ADJ-n` em `draft` só com a **diferença** contra a soma das `locked_lines` de todos os lotes `locked` do mês (linhas positivas ou negativas; sem diferença, nenhum lote nasce). A reconciliação do ajuste confere o **acumulado** (`locked_lines` + ajuste) contra o recálculo SQL sobre `fct_recharges`, com diferença R$ 0,00; os flags não se aplicam. Dali em diante é o fluxo normal do `atlas_commission_review` (`submit`, duas aprovações, lock e remessa). Recusa se o mês já tem um ajuste em andamento.

## Relatório de revisão `commission_review` (P8.8)

O que a analista e a diretora olham antes de aprovar (SPEC-003 §5.4): totais e reconciliação, top 20 maiores linhas, linhas com flag e comparação com o mês anterior (o último lote `locked` do mês civil anterior; lotes `ADJ` não contam). **Somente leitura de `commission.*`**: não calcula, não aprova, não grava. As consultas ficam em `review_sql/*.sql` e têm duas saídas:

- **Dashboard** "Atlas — Revisão de Comissão" (`semantic/dashboards/commission_review.lvdash.json`, no bundle). Escolha o lote no filtro **Lote**. O JSON é **gerado**: depois de mexer em `review_sql/` ou em `review_report.py`, rode `uv run python scripts/build_commission_review_dashboard.py` (um teste falha se divergir).
- **Notebook** `commission_review.py`: widgets `catalog` e `batch_id`; as mesmas consultas, restritas ao lote.

O dashboard lê `commission.*` por ser o relatório do próprio domínio, não um consumidor da camada semântica (ADR-0018; a `mv_commission` só tem lotes `locked`). Quem vê os dados é a identidade que publica o dashboard; os grupos `atlas_commission_*` são de workspace e não valem como grant no Unity Catalog (ADR-0016). Confira com `scripts/check_commission_review.py --target dev --profile <perfil> --warehouse-id <id> --batch-id COM-2026-10-v1`.

## Lock e remessa simulada (P8.7)

Na mesma execução em que a diretora aprova (`approved`), `lock.py` confere que `batch_lines` soma o que o lote declara, grava `<batch_id>.csv` (`beneficiary_type, beneficiary_id, commission_brl`, ordenado, 2 casas) e `<batch_id>.sha256` em `/Volumes/<catalog>/commission/remittance/` (Volume criado pelo `atlas_commission_deploy`), copia as linhas para `locked_lines` (append-only), grava `batches.remittance_sha256` e leva o lote a `locked`, com o evento `approved -> locked` do ator `system`. **Nada sai do workspace.** Se a execução cair depois do `approved`, repita `approve` (diretora): o lock é idempotente e completa sem nova aprovação. Confira com `scripts/check_commission_lock.py`.

## Revisão e aprovação (P8.6)

`review.py` (job `atlas_commission_review`, **disparado por uma pessoa**; nenhum agente o executa, ADR-0010) faz **uma** transição por execução e a grava em `batch_events`. Parâmetros: `batch_id`, `decision` (`submit`, `approve`, `reject`), `justification` e `allow_same_approver_demo` (`false`). Dispare pelo workspace (*Run now with different parameters*), depois do `bundle deploy`.

| decision | de → para | quem |
|---|---|---|
| `submit` | `draft → under_review` | qualquer pessoa; exige `reconciliation.status = 'passed'` |
| `approve` | `under_review → analyst_approved` | grupo `atlas_commission_analysts` |
| `approve` | `analyst_approved → approved` | grupo `atlas_commission_directors`, **ator diferente** do analista |
| `reject` | `under_review` ou `analyst_approved` → `rejected` | analista ou diretora; justificativa com 20+ caracteres |

Erros: `SEGREGATION_OF_DUTIES_VIOLATION` (a tentativa fica em `batch_events` com `to_status = 'denied'`, que não conta como aprovação), `JUSTIFICATION_REQUIRED`, `INVALID_TRANSITION`, `RECONCILIATION_NOT_PASSED`, `ROLE_NOT_ALLOWED`. O ator é o `creator_user_name` da execução (o job roda como o dono do bundle, então `current_user()` não serve) e os grupos vêm da API SCIM. `allow_same_approver_demo=true` (SPEC-003 §9) grava `role = 'demo_override'` e `batches.demo_mode = true`.

**Quem pode aprovar:** os grupos `atlas_commission_*` nascem vazios. Adicione pessoas com `uv run python scripts/setup_workspace.py --target dev --profile <perfil> --analyst <e-mail> --director <e-mail>` (repetíveis, idempotente; só mexe nesses dois grupos).

Fora desta task: a versão `vN+1` depois de uma rejeição (o rascunho só cria a `v1`).

```bash
databricks bundle deploy -t dev --profile <perfil>
databricks bundle run atlas_commission_deploy -t dev --profile <perfil>   # só na primeira vez
databricks bundle run atlas_commission_draft -t dev --profile <perfil>
uv run python scripts/check_commission_draft.py --target dev --profile <perfil> \
    --warehouse-id <id> --batch-id COM-2026-10-v1
uv run python scripts/check_commission_flags.py --target dev --profile <perfil> \
    --warehouse-id <id> --batch-id COM-2026-10-v1
```
