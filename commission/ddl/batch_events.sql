CREATE TABLE IF NOT EXISTS ${catalog}.commission.batch_events (
  event_id STRING NOT NULL COMMENT 'Identificador único do evento',
  batch_id STRING NOT NULL COMMENT 'Lote da transição',
  from_status STRING COMMENT 'Estado anterior; nulo na criação',
  to_status STRING NOT NULL COMMENT 'Estado novo',
  actor STRING NOT NULL COMMENT 'current_user() de quem executou a transição',
  role STRING NOT NULL COMMENT 'analyst, director, system ou demo_override',
  justification STRING COMMENT 'Texto da decisão; obrigatório (20+ caracteres) na rejeição',
  event_ts_utc TIMESTAMP NOT NULL COMMENT 'Momento do evento, em UTC'
)
USING DELTA
COMMENT 'Trilha de auditoria das transições; append-only (SPEC-003 §3)'
TBLPROPERTIES ('delta.appendOnly' = 'true')
