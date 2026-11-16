SELECT batch_id,
       beneficiary_type,
       beneficiary_id,
       tier,
       base_amount_brl,
       commission_brl,
       array_join(flags, ', ') AS flags
FROM batch_lines
WHERE size(flags) > 0
ORDER BY batch_id, commission_brl DESC, beneficiary_id
