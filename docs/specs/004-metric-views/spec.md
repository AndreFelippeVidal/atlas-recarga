# SPEC-004 — Metric views, AI/BI Dashboard e Genie

> PRD: F4, F5 · ADR: [0005](../../adr/0005-metric-views-semantic-layer.md) · Status: rascunho

## 1. Objetivo
Uma **camada semântica única** em `atlas.semantic`: toda métrica de negócio tem **uma** definição, consumida igualmente pelo AI/BI Dashboard, pelo Genie, pelo agente, pelo MCP e pelo React. É assim que se elimina "cada área calcula a receita de um jeito".

## 2. Sintaxe
Metric views via `CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML AS $$ ... $$` (YAML `version: 1.1`), versionadas em `semantic/*.yaml` no repo e aplicadas pelo bundle. Medidas são consultadas com `MEASURE(<nome>)`.

**Deploy:** o job `atlas_semantic_deploy` (sob demanda) roda `semantic/apply_metric_views.py` como `spark_python_task` serverless: troca `${catalog}` pelo catálogo do target e executa o `CREATE OR REPLACE VIEW` com o YAML literal, sem reindentar (ADR-0005). Não é `sql_task` porque o catálogo muda por target (`atlas_dev` e `atlas`) e o YAML não aceita parâmetro.

## 3. `atlas.semantic.mv_recharges`

**Fonte:** `gold.fct_recharges`, com joins `pos` → `gold.dim_pos`, `pos.municipality` → `gold.dim_municipality` e `pos.distributor` → `gold.dim_distributor`.

> Os joins se chamam `dim_pos` (com `dim_municipality` e `dim_distributor` aninhados), não `pos`: um alias que é prefixo de coluna da fato (`pos_id`) falha com `INVALID_EXTRACT_BASE_FIELD_TYPE`. Na tabela abaixo, `pos.municipality.x` significa `dim_pos.dim_municipality.x`.

**Campos (dimensões)**

| nome | expressão | sinônimos |
|---|---|---|
| `recharge_date` | `recharge_date` | data, dia |
| `recharge_month` | `DATE_TRUNC('MONTH', recharge_date)` | mês |
| `recharge_hour_local` | `recharge_hour_local` | hora, horário, horário de pico (hora local do PDV, 0 a 23) |
| `region` | `pos.municipality.region` | região |
| `uf` | `pos.municipality.uf` | estado, UF |
| `municipality_ibge_code` | `pos.municipality.municipality_ibge_code` | código IBGE |
| `municipality_name` | `pos.municipality.municipality_name` | município, cidade |
| `ddd` | `pos.municipality.ddd` | DDD, código de área |
| `pos_type` | `pos.pos_type` | tipo de PDV, canal |
| `distributor_name` | `pos.distributor.distributor_name` | distribuidor |

**Medidas**

| nome | expressão | formato | sinônimos |
|---|---|---|---|
| `gross_revenue` | `SUM(amount_brl) FILTER (WHERE status = 'approved')` | BRL, 2 casas | receita, faturamento, volume |
| `recharge_count` | `COUNT(1) FILTER (WHERE status = 'approved')` | inteiro | recargas, quantidade |
| `avg_ticket` | `MEASURE(gross_revenue) / MEASURE(recharge_count)` | BRL | ticket médio |
| `active_pos` | `COUNT(DISTINCT pos_id) FILTER (WHERE status = 'approved')` | inteiro | PDVs ativos |
| `revenue_per_active_pos` | `MEASURE(gross_revenue) / MEASURE(active_pos)` | BRL | receita por PDV |
| `reversal_rate` | `COUNT(1) FILTER (WHERE status='reversed') / COUNT(1)` | % | taxa de estorno |
| `distinct_subscribers` | `COUNT(DISTINCT subscriber_id) FILTER (WHERE status='approved')` | inteiro | assinantes |

> Definição oficial: **PDV ativo** = PDV com pelo menos 1 recarga aprovada **no período filtrado**. A descrição da medida no YAML diz isso literalmente, porque o agente lê.

## 4. `atlas.semantic.mv_commission`

**Fonte:** `commission.locked_lines` com `batches`. **Só lotes `locked`**: rascunhos nunca aparecem na camada semântica.

| Dimensões | Medidas |
|---|---|
| `reference_month`, `beneficiary_type`, `tier`, `uf`, `region`, `municipality_name`, `distributor_name`, `batch_id` | `commission_total` (`SUM(commission_brl)`), `commission_base` (`SUM(base_amount_brl)`), `effective_rate` (`commission_total / commission_base`), `paid_beneficiaries` (`COUNT(DISTINCT beneficiary_id)`) |

## 5. Comparações temporais
A variação mês contra mês **não** vira medida no MVP. O consumidor consulta dois períodos e calcula. Motivo: manter as definições simples e auditáveis. As medidas com janela (`window`) da v1.1 serão avaliadas depois do golden set.

## 6. Consumidores

| Consumidor | Como usa |
|---|---|
| **AI/BI Dashboard** `Atlas — Visão Comercial` | Páginas: Brasil (KPIs + ranking de UFs), Região/UF (tabela municipal), Rede (PDVs ativos por tipo), Comissão (só `mv_commission`). Filtros globais: mês, região, UF. O mapa coroplético fica na SPEC-007 (React): o mapa nativo do AI/BI não reconhece UFs do Brasil e não há lat/lon no MVP (ADR-0004) |
| **Genie Space** `Atlas Recarga` | Fontes: **só** `mv_recharges` e `mv_commission`. Instruções em PT-BR com as definições oficiais e 10 perguntas de exemplo (subconjunto do golden set). Usado pelo agente (SPEC-005) |
| **Agente, MCP e React** | Consultam via SQL warehouse com `MEASURE()`. Nunca leem `gold.*` diretamente |

## 7. Permissões
O grupo `atlas_readers` (Helena, gerentes e os service principals do agente, do MCP e do React) recebe `SELECT` em `atlas.semantic.*` e **nada** em `gold`, `silver`, `bronze` e `commission`. As metric views são a única porta de leitura.

> **Limite de plataforma (ADR-0016):** `atlas_readers` é um grupo de workspace e o Unity Catalog não avalia grants dele. Na prática o `SELECT` é concedido **a cada principal** (`setup_workspace.py --reader`); o grant no grupo fica para quando ele for um grupo de conta.

## 8. Critérios de aceite
- **Dado** o mês M, **quando** consulto `MEASURE(gross_revenue)` na metric view e o SQL de referência direto no gold, **então** os valores são iguais ao centavo.
- **Dado** um rascunho de comissão em `draft`, **então** `mv_commission` não retorna nenhuma linha dele.
- **Dado** o mesmo mês e UF, **então** AI/BI, Genie, agente, MCP e React mostram o mesmo `gross_revenue` (teste de consistência do PRD).
- **Dado** o service principal do agente, **quando** ele tenta um `SELECT` em `gold.fct_recharges`, **então** recebe `PERMISSION_DENIED`.
- **Dado** o Genie Space, **quando** pergunto "qual a receita por DDD em outubro?", **então** ele usa `ddd` e `gross_revenue` de `mv_recharges`.

## 9. Fora de escopo
Metas e forecast como medidas (v2), RLS por região (v3), medidas com janela (v1.1).
