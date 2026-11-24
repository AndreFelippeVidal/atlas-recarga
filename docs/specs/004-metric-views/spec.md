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
| `reference_month`, `beneficiary_type`, `tier`, `uf`, `region`, `municipality_name`, `distributor_name`, `batch_id` | `commission_total` (`SUM(commission_brl)`), `commission_base` (`SUM(base_amount_brl)` só das linhas de PDV), `effective_rate` (`commission_total` das linhas de PDV / `commission_base`), `paid_beneficiaries` (`COUNT(DISTINCT beneficiary_id)`) |

Regras desta view:
- **Base só de PDV.** A base de uma linha de distribuidor é o volume dos PDVs dele (SPEC-003 §2); somá-la com a dos PDVs contaria o mesmo volume duas vezes. Por isso `commission_base` e `effective_rate` consideram só `beneficiary_type = 'pos'`; `commission_total` soma PDV e distribuidor.
- **Dimensões geográficas e `tier` só existem para PDV.** Nas linhas de distribuidor `uf`, `region`, `municipality_name` e `tier` são vazios, então um ranking por UF ou região soma menos que `commission_total`. `distributor_name` é o próprio distribuidor ou o que atende o PDV.
- **Todos os lotes `locked` entram**, inclusive os de ajuste `ADJ` (linhas de diferença, possivelmente negativas; original + ajustes = valor final pago) e os de `demo_mode = true`. `batch_id` é a forma de separá-los.

## 5. Comparações temporais e janelas (v1.1, Fase 15)
No MVP a variação mês contra mês **não** era medida: o consumidor consultava dois períodos e calculava (o `atlas-web` calcula o `mom_change` no backend). Calcular métrica no código de um consumidor contraria o princípio 1, então a v1.1 move essas contas para a metric view, com **medidas com janela** ordenadas por `recharge_month`:

| nome | definição | formato | sinônimos |
|---|---|---|---|
| `gross_revenue_t3m` | `gross_revenue` somada no mês e nos 2 meses anteriores (janela móvel de 3 meses) | BRL, 2 casas | últimos 3 meses, trimestre móvel |
| `gross_revenue_ytd` | `gross_revenue` acumulada de janeiro até o mês, **zerando a cada janeiro** | BRL, 2 casas | acumulado no ano, YTD |
| `revenue_mom_change` | `(gross_revenue do mês − gross_revenue do mês anterior) / gross_revenue do mês anterior`; `NULL` sem mês anterior ou com base zero | % (fração) | variação contra o mês anterior, crescimento |

Regras:
- **A sintaxe é experimental.** A documentação do Databricks traz `window` com `version: 0.1`; a `mv_recharges` está em `version: 1.1` (precisa de `synonyms` e `format`). A task P15.2 (spike) confirma se as duas convivem na Free Edition e como a consulta deve ser escrita. Se não convivem, o ADR-0025 decide entre uma view separada (`mv_recharges_trend`) e manter a conta no backend; a spec é corrigida antes do código.
- **O filtro de mês não pode cortar a janela.** `WHERE recharge_month = M` precisa continuar enxergando os meses anteriores; a forma de consulta que garante isso é definida no spike e vale para todos os consumidores.
- **Os filtros de PDV valem antes da janela.** `pos_type` e `distributor_name` no `WHERE` recortam a base; a janela é calculada sobre o recorte.
- **Mês aberto fica parcial.** As janelas herdam a regra do "último mês fechado" (SPEC-005): o mês corrente, se houver, aparece com o que já foi carregado.
- **Unidade na API.** O `mom_change` do `atlas-web` continua em pontos percentuais com 2 casas; a conversão da fração (× 100, em Decimal) é só formatação, não métrica.
- Cada medida tem `comment` com a definição literal, porque o agente lê.

## 6. Consumidores

| Consumidor | Como usa |
|---|---|
| **AI/BI Dashboard** `Atlas — Visão Comercial` | Páginas: Brasil (KPIs + ranking de UFs), Região/UF (tabela municipal), Rede (PDVs ativos por tipo), Comissão (só `mv_commission`). Filtros globais: mês, região, UF. O mapa coroplético fica na SPEC-007 (React): o mapa nativo do AI/BI não reconhece UFs do Brasil e não há lat/lon no MVP (ADR-0004) |
| **Genie Space** `Atlas Recarga` | Fontes: **só** `mv_recharges` e `mv_commission`. Instruções em PT-BR com as definições oficiais e 10 perguntas de exemplo (subconjunto do golden set); a Fase 15 acrescenta 3 exemplos com as medidas com janela. Usado pelo agente (SPEC-005) |
| **Agente, MCP e React** | Consultam via SQL warehouse com `MEASURE()`. Nunca leem `gold.*` diretamente |

## 7. Permissões
O grupo `atlas_readers` (Helena, gerentes e os service principals do agente, do MCP e do React) recebe `SELECT` em `atlas.semantic.*` e **nada** em `gold`, `silver`, `bronze` e `commission`. As metric views são a única porta de leitura.

> **Limite de plataforma (ADR-0016):** `atlas_readers` é um grupo de workspace e o Unity Catalog não avalia grants dele. Na prática o `SELECT` é concedido **a cada principal** (variável `semantic_grants` do bundle, ADR-0017; `USE CATALOG` por `setup_workspace.py --reader`); o grant no grupo fica para quando ele for um grupo de conta.

## 8. Critérios de aceite
- **Dado** o mês M, **quando** consulto `MEASURE(gross_revenue)` na metric view e o SQL de referência direto no gold, **então** os valores são iguais ao centavo.
- **Dado** um rascunho de comissão em `draft`, **então** `mv_commission` não retorna nenhuma linha dele.
- **Dado** o mesmo mês e UF, **então** AI/BI, Genie, agente, MCP e React mostram o mesmo `gross_revenue` (teste de consistência do PRD).
- **Dado** o service principal do agente, **quando** ele tenta um `SELECT` em `gold.fct_recharges`, **então** recebe `PERMISSION_DENIED`.
- **Dado** o Genie Space, **quando** pergunto "qual a receita por DDD em outubro?", **então** ele usa `ddd` e `gross_revenue` de `mv_recharges`.
- **Dado** um mês M (v1.1), **quando** consulto `gross_revenue_t3m`, `gross_revenue_ytd` e `revenue_mom_change` na metric view e o SQL de referência direto no gold, **então** os valores de `gross_revenue_t3m` e `gross_revenue_ytd` são iguais ao centavo e o de `revenue_mom_change` é igual em 4 casas decimais. Em janeiro o YTD é a receita de janeiro; no primeiro mês da série o `revenue_mom_change` é `NULL`, sem erro de divisão por zero.
- **Dado** o filtro `pos_type = 'pharmacy'` (e depois um distribuidor), **então** as três medidas com janela batem com o SQL direto no gold com o mesmo filtro.
- **Dado** o `mom_change` do `atlas-web` lido de `revenue_mom_change`, **então** ele é igual, com 2 casas, ao valor calculado no backend antes da v1.1, nos 3 níveis do mapa.

## 9. Fora de escopo
Metas e forecast como medidas (v2), RLS por região (v3). Janelas de outros tamanhos além de 3 meses e do ano, e medidas com janela em `mv_commission`, ficam fora da Fase 15.
