CREATE TABLE IF NOT EXISTS ${catalog}.commission.reconciliation (
  batch_id STRING NOT NULL COMMENT 'Lote reconciliado',
  status STRING NOT NULL COMMENT 'passed ou failed; só passed libera draft -> under_review',
  lines_compared BIGINT NOT NULL COMMENT 'Linhas comparadas entre o PySpark e o SQL independente',
  max_line_diff_brl DECIMAL(14,2) NOT NULL COMMENT 'Maior diferença absoluta por linha; esperado 0.00',
  total_diff_brl DECIMAL(14,2) NOT NULL COMMENT 'Diferença entre os totais das duas implementações; esperado 0.00',
  pos_control_diff_brl DECIMAL(14,2) NOT NULL COMMENT 'Base dos PDVs menos o volume aprovado em fct_recharges; esperado 0.00',
  distributor_control_diff_brl DECIMAL(14,2) NOT NULL COMMENT 'Base dos distribuidores menos a soma por distribuidor; esperado 0.00',
  checked_at_utc TIMESTAMP NOT NULL COMMENT 'Momento da reconciliação, em UTC'
)
USING DELTA
COMMENT 'Resultado da reconciliação por lote (SPEC-003 §5)'
