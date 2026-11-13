# commission

Regras e jobs do fechamento de comissão. Governado pela [SPEC-003](../docs/specs/003-commission-closing/spec.md). **Path sensível (etapa irreversível):** CODEOWNERS; o agente de código não altera as regras sem pedido explícito.

## Rascunho do lote (P8.3)

`draft.py` calcula o lote `COM-YYYY-MM-v1` em `draft` a partir de `gold.agg_pos_month` (job `atlas_commission_draft`). Faixas e taxas vêm de `rules.TIERS`; o arredondamento é HALF_EVEN por linha (`bround`). O mês é o anterior ao corrente em America/Sao_Paulo, ou o `reference_month` (`YYYY-MM`) do job. Se o `v1` já existe, o job recusa e não altera nada. Reconciliação, flags e aprovação vêm nas P8.4 a P8.6.

```bash
databricks bundle deploy -t dev --profile <perfil>
databricks bundle run atlas_commission_deploy -t dev --profile <perfil>   # só na primeira vez
databricks bundle run atlas_commission_draft -t dev --profile <perfil>
uv run python scripts/check_commission_draft.py --target dev --profile <perfil> \
    --warehouse-id <id> --batch-id COM-2026-10-v1
```
