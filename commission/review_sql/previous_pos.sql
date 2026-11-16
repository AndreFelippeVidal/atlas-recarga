-- Os 50 PDVs com maior mudança de comissão contra o último lote locked do mês anterior
-- (a mesma definição de `previous_totals.sql`). Sem lote anterior, não há linhas.
WITH previous AS (
  SELECT b.batch_id, p.batch_id AS previous_batch_id
  FROM batches b
  JOIN batches p
    ON p.reference_month = add_months(b.reference_month, -1)
   AND p.status = 'locked'
   AND p.batch_id NOT LIKE '%-ADJ-%'
  QUALIFY row_number() OVER (PARTITION BY b.batch_id ORDER BY p.version DESC) = 1
),
compared AS (
  SELECT l.batch_id,
         pv.previous_batch_id,
         l.beneficiary_id,
         l.tier,
         o.tier AS previous_tier,
         l.commission_brl,
         o.commission_brl AS previous_commission_brl,
         l.commission_brl - COALESCE(o.commission_brl, 0) AS change_brl,
         array_join(COALESCE(l.flags, array()), ', ') AS flags
  FROM batch_lines l
  JOIN previous pv ON pv.batch_id = l.batch_id
  LEFT JOIN batch_lines o
    ON o.batch_id = pv.previous_batch_id
   AND o.beneficiary_type = 'pos'
   AND o.beneficiary_id = l.beneficiary_id
  WHERE l.beneficiary_type = 'pos'
)
SELECT *
FROM compared
QUALIFY row_number() OVER (
  PARTITION BY batch_id ORDER BY abs(change_brl) DESC, beneficiary_id
) <= 50
ORDER BY batch_id, abs(change_brl) DESC, beneficiary_id
