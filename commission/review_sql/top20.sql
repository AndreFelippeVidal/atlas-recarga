SELECT batch_id,
       rnk,
       beneficiary_type,
       beneficiary_id,
       tier,
       base_amount_brl,
       rate,
       commission_brl,
       array_join(COALESCE(flags, array()), ', ') AS flags
FROM (
  SELECT l.*,
         row_number() OVER (
           PARTITION BY batch_id
           ORDER BY commission_brl DESC, beneficiary_type, beneficiary_id
         ) AS rnk
  FROM batch_lines l
)
WHERE rnk <= 20
ORDER BY batch_id, rnk
