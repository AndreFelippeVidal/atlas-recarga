CREATE TABLE IF NOT EXISTS ${catalog}.commission.locked_lines (
  batch_id STRING NOT NULL COMMENT 'Lote travado',
  beneficiary_type STRING NOT NULL COMMENT 'pos ou distributor',
  beneficiary_id STRING NOT NULL COMMENT 'pos_id ou distributor_id',
  base_amount_brl DECIMAL(14,2) NOT NULL COMMENT 'Volume aprovado no mês sobre o qual a taxa incide',
  tier STRING COMMENT 'Faixa do PDV (bronze, silver, gold, diamond); nulo para distribuidor',
  rate DECIMAL(5,4) NOT NULL COMMENT 'Taxa aplicada (0.0200 = 2%)',
  commission_brl DECIMAL(14,2) NOT NULL COMMENT 'Comissão da linha, ROUND_HALF_EVEN em centavos',
  flags ARRAY<STRING> COMMENT 'Flags de revisão humana (SPEC-003 §5)'
)
USING DELTA
COMMENT 'Cópia das linhas no lock; append-only; fonte oficial da metric view de comissão (SPEC-003 §3)'
TBLPROPERTIES ('delta.appendOnly' = 'true')
