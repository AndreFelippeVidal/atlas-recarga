SELECT batch_id,
       flag,
       COUNT(*) AS lines
FROM (SELECT batch_id, explode(flags) AS flag FROM batch_lines)
GROUP BY batch_id, flag
ORDER BY batch_id, flag
