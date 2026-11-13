CREATE TABLE IF NOT EXISTS ${catalog}.commission.batch_lines (
  batch_id STRING NOT NULL COMMENT 'Lote ao qual a linha de rascunho pertence',
  beneficiary_type STRING NOT NULL COMMENT 'pos ou distributor',
  beneficiary_id STRING NOT NULL COMMENT 'pos_id ou distributor_id',
  base_amount_brl DECIMAL(14,2) NOT NULL COMMENT 'Volume aprovado no mês sobre o qual a taxa incide',
  tier STRING COMMENT 'Faixa do PDV (bronze, silver, gold, diamond); nulo para distribuidor',
  rate DECIMAL(5,4) NOT NULL COMMENT 'Taxa aplicada (0.0200 = 2%)',
  commission_brl DECIMAL(14,2) NOT NULL COMMENT 'Comissão da linha, ROUND_HALF_EVEN em centavos',
  flags ARRAY<STRING> COMMENT 'Flags de revisão humana (SPEC-003 §5)'
)
USING DELTA
COMMENT 'Linhas de rascunho do lote; mutáveis até o lock (SPEC-003 §3)'
