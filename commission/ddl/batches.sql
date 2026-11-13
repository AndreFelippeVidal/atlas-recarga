CREATE TABLE IF NOT EXISTS ${catalog}.commission.batches (
  batch_id STRING NOT NULL COMMENT 'COM-YYYY-MM-vN (ou COM-YYYY-MM-ADJ-n no lote de ajuste)',
  reference_month DATE NOT NULL COMMENT 'Primeiro dia do mês civil de referência (America/Sao_Paulo)',
  version INT NOT NULL COMMENT 'Versão do lote no mês; uma rejeição gera a versão seguinte',
  status STRING NOT NULL COMMENT 'draft, under_review, analyst_approved, approved, rejected ou locked (SPEC-003 §4)',
  total_pos_brl DECIMAL(14,2) COMMENT 'Soma das comissões de PDV já arredondadas por linha',
  total_distributor_brl DECIMAL(14,2) COMMENT 'Soma das comissões de distribuidor já arredondadas por linha',
  source_snapshot_version BIGINT COMMENT 'Versão Delta de gold.agg_pos_month usada no cálculo',
  remittance_sha256 STRING COMMENT 'sha256 da remessa simulada; preenchido no lock',
  demo_mode BOOLEAN NOT NULL COMMENT 'true quando ALLOW_SAME_APPROVER_DEMO foi usado (SPEC-003 §9)',
  created_at_utc TIMESTAMP NOT NULL COMMENT 'Criação do lote, em UTC'
)
USING DELTA
COMMENT 'Cabeçalho dos lotes de comissão (SPEC-003 §3)'
