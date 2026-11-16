SELECT b.batch_id,
       b.status,
       b.reference_month,
       b.demo_mode,
       b.total_pos_brl,
       b.total_distributor_brl,
       COALESCE(n.pos_lines, 0) AS pos_lines,
       COALESCE(n.distributor_lines, 0) AS distributor_lines,
       COALESCE(n.flagged_lines, 0) AS flagged_lines,
       r.status AS reconciliation_status,
       r.lines_compared,
       r.max_line_diff_brl,
       r.total_diff_brl,
       r.pos_control_diff_brl,
       r.distributor_control_diff_brl
FROM batches b
LEFT JOIN (
  SELECT batch_id,
         COUNT_IF(beneficiary_type = 'pos') AS pos_lines,
         COUNT_IF(beneficiary_type = 'distributor') AS distributor_lines,
         COUNT_IF(size(flags) > 0) AS flagged_lines
  FROM batch_lines
  GROUP BY batch_id
) n ON n.batch_id = b.batch_id
LEFT JOIN (
  SELECT *
  FROM reconciliation
  QUALIFY row_number() OVER (PARTITION BY batch_id ORDER BY checked_at_utc DESC) = 1
) r ON r.batch_id = b.batch_id
