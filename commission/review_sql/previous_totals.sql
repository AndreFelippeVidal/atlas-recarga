-- Lote anterior = último lote locked do mês civil anterior (maior versão; lotes ADJ não contam).
WITH previous AS (
  SELECT b.batch_id, p.batch_id AS previous_batch_id
  FROM batches b
  JOIN batches p
    ON p.reference_month = add_months(b.reference_month, -1)
   AND p.status = 'locked'
   AND p.batch_id NOT LIKE '%-ADJ-%'
  QUALIFY row_number() OVER (PARTITION BY b.batch_id ORDER BY p.version DESC) = 1
)
SELECT b.batch_id,
       pv.previous_batch_id,
       b.total_pos_brl,
       p.total_pos_brl AS previous_total_pos_brl,
       b.total_distributor_brl,
       p.total_distributor_brl AS previous_total_distributor_brl
FROM batches b
LEFT JOIN previous pv ON pv.batch_id = b.batch_id
LEFT JOIN batches p ON p.batch_id = pv.previous_batch_id
