# SPEC-002 — Pipeline medalhão (Lakeflow Spark Declarative Pipelines)

> PRD: F2 · ADRs: [0001](../../adr/0001-databricks-free-edition.md), [0002](../../adr/0002-lakeflow-declarative-pipelines.md), [0003](../../adr/0003-medallion-unity-catalog.md) · Status: rascunho

## 1. Objetivo
Transformar os arquivos de landing em tabelas **bronze → silver → gold** no Unity Catalog, com linhagem nativa, regras de qualidade declaradas e entrega do gold D-1 até 08:00.

## 2. Recursos

| Recurso | Definição |
|---|---|
| Pipeline | `atlas_medallion`: **um único** pipeline SDP serverless (a Free Edition permite 1 ativo por tipo), em Python com `from pyspark import pipelines as dp` |
| Catálogo padrão | `atlas`. Cada dataset declara o schema destino (`bronze`, `silver`, `gold`) |
| Fonte | Volume `/Volumes/atlas/raw/landing/` (SPEC-001) |
| Orquestração | Job `atlas_daily` às 06:00 (America/Sao_Paulo): task 1 = refresh do pipeline; task 2 = rascunho de comissão (só no dia 1º, SPEC-003); task 3 = verificação de frescor |

## 3. Datasets

### Bronze: cópia fiel, só acrescenta metadados
| Tabela | Tipo | Fonte | Regras |
|---|---|---|---|
| `bronze.recharges` | streaming table | Auto Loader `cloudFiles` parquet de `recharges/` | + `_source_file`, `_ingested_at_utc`. **Sem** expectations que descartem linhas |
| `bronze.pos` | materialized view | `pos/` | idem |
| `bronze.distributors` | materialized view | `distributors/` | idem |
| `bronze.municipalities` | materialized view | Referência IBGE carregada no Volume | idem |

### Silver: limpa, tipada, deduplicada
| Tabela | Tipo | Regras e expectations |
|---|---|---|
| `silver.recharges` | streaming table | Dedup por `recharge_id` (mantém o menor `_ingested_at_utc`); `recharge_date` derivado de `recharge_ts_utc` em America/Sao_Paulo; `recharge_hour_local` (INT, 0 a 23) derivado de `recharge_ts_utc` no fuso da UF do PDV (AC UTC−5; AM, RO, RR, MT, MS UTC−4; demais UTC−3). Expectations: `expect_or_drop("pos_not_null", "pos_id IS NOT NULL")`, `expect_or_drop("positive_amount", "amount_brl > 0")`, `expect_or_drop("valid_status", "status IN ('approved','reversed')")`, `expect("face_value", "amount_brl IN (10,15,20,25,30,40,50,100)")` (warn) |
| `silver.recharges_quarantine` | streaming table | Linhas com `pos_id` inexistente em `silver.pos`. Ficam retidas, não somem |
| `silver.pos` | materialized view | `expect_or_fail("pos_municipality_known", "municipality_ibge_code IN referência")`, `expect_or_fail("pos_has_distributor", ...)` |
| `silver.distributors`, `silver.municipalities` | materialized view | `expect_or_fail` em PK não nula e única |

> **Política:** `drop` para defeitos linha a linha esperados na fonte; `fail` para integridade de dimensões, porque dimensão corrompida contamina toda a comissão; `warn` para regras de negócio ainda em observação.

### Gold: modelo dimensional consumido pelas metric views
| Tabela | Grão | Colunas-chave |
|---|---|---|
| `gold.dim_municipality` | município | `municipality_ibge_code`, `municipality_name`, `uf`, `region`, `ddd`, `population` |
| `gold.dim_pos` | PDV | `pos_id`, `pos_type`, `distributor_id`, `municipality_ibge_code`, `opened_date`, `closed_date` |
| `gold.dim_distributor` | distribuidor | `distributor_id`, `distributor_name`, `hq_uf` |
| `gold.fct_recharges` | recarga | `recharge_id`, `recharge_date`, `recharge_month` (DATE, 1º dia), `recharge_hour_local`, `pos_id`, `amount_brl`, `status`, `subscriber_id` |
| `gold.agg_pos_month` | PDV × mês | `pos_id`, `recharge_month`, `approved_amount_brl`, `approved_count`, `reversed_count`, `distinct_subscribers`. Base da comissão (SPEC-003) |

Regras de `gold.agg_pos_month`:
- **Grão e linhas:** uma linha por PDV ativo em cada mês presente em `fct_recharges`, com zeros para o PDV aberto sem recarga no mês. Ativo no mês = `opened_date` até o último dia do mês e `closed_date` nula ou a partir do primeiro dia. Um PDV com recarga no mês entra mesmo fora dessa janela, para a soma bater com `fct_recharges`.
- **Status:** `approved_amount_brl`, `approved_count` e `distinct_subscribers` contam só `status = 'approved'`; `reversed_count` conta `status = 'reversed'`.
- **Tipos:** `approved_amount_brl` é `DECIMAL(14,2)`; as contagens são `BIGINT`.

Todas as gold têm `COMMENT` na tabela e em cada coluna, porque o Genie e o agente leem essas descrições.

## 4. Falhas e comportamento

| Situação | Comportamento |
|---|---|
| Arquivo do dia não chegou às 06:00 | O pipeline roda com o que existe; a task 3 marca `freshness_status = 'stale'` em `observability.pipeline_freshness` |
| `expect_or_fail` violado | O pipeline falha e o gold do dia anterior continua servido (as MVs não são substituídas); o job notifica por e-mail o dono do workspace |
| Mais de 1% de linhas descartadas no silver em um dia | A task 3 registra `quality_status = 'degraded'`. Não bloqueia no MVP; bloqueia na v2 |
| Reprocessamento total | Full refresh do pipeline; o bronze é reconstruído a partir do Volume (fonte imutável) |

**`observability.pipeline_freshness` (task 3 do job):** uma linha por execução, com `run_ts_utc`, `business_date`, `max_recharge_date`, `freshness_status`, `ingested_count`, `dropped_count`, `dropped_ratio` e `quality_status`. `stale` = `max(recharge_date)` de `gold.fct_recharges` anterior a D-1 em America/Sao_Paulo (ou fato vazia). `degraded` = mais de 1% dos `recharge_id` ingeridos no bronze nas últimas 24 h ausentes de `silver.recharges` e de `silver.recharges_quarantine` (duplicados e quarentena não contam como descarte). A task de comissão (dia 1º) entra no job junto com a SPEC-003.

## 5. Critérios de aceite
- **Dado** o dataset padrão com `--scenarios all`, **quando** o pipeline roda, **então** `silver.recharges` = total gerado − duplicados − nulos − negativos − órfãos, conforme o `_manifest.json`, com diferença exata de 0.
- **Dado** os órfãos injetados, **então** `silver.recharges_quarantine` contém exatamente as linhas `unknown_pos`.
- **Dado** um `late_arrival`, **então** a recarga entra no `recharge_date` correto e não no dia do arquivo.
- **Dado** um PDV com município fora da referência, **quando** o pipeline roda, **então** ele falha em `pos_municipality_known`.
- **Dado** uma execução bem-sucedida, **quando** abro a linhagem no Catalog Explorer, **então** vejo `landing → bronze → silver → gold → semantic.mv_*`.
- **Dado** o job das 06:00 com o tamanho padrão, **então** o gold D-1 está pronto antes das 08:00 (meta < 30 min).

## 6. Fora de escopo
Lakehouse Monitoring e expectations bloqueantes de volume ou anomalia (v2), CDC e SCD2 de PDV (v2; no MVP a dimensão é SCD1), streaming contínuo.
