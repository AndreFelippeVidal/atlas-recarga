-- S0.4 (descartável): metric view mínima sobre samples.tpch.orders.
-- Roda em workspace.atlas_spike_s0_4 (o catálogo `atlas` só nasce na P5.2).

CREATE SCHEMA IF NOT EXISTS workspace.atlas_spike_s0_4;

CREATE OR REPLACE VIEW workspace.atlas_spike_s0_4.mv_orders
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
comment: "Spike S0.4: pedidos TPC-H, análogo a recargas"
source: samples.tpch.orders
dimensions:
  - name: order_month
    expr: DATE_TRUNC('MONTH', o_orderdate)
    comment: "Mês do pedido"
    display_name: "Mês"
    synonyms: ["mês", "período"]
  - name: order_status
    expr: o_orderstatus
    comment: "Status do pedido (F, O, P)"
    synonyms: ["status"]
  - name: order_priority
    expr: o_orderpriority
    comment: "Prioridade do pedido"
measures:
  - name: gross_revenue
    expr: SUM(o_totalprice)
    comment: "Soma do valor total dos pedidos"
    display_name: "Receita bruta"
    synonyms: ["receita", "faturamento"]
  - name: order_count
    expr: COUNT(1)
    comment: "Quantidade de pedidos"
    synonyms: ["pedidos"]
  - name: avg_ticket
    expr: MEASURE(gross_revenue) / MEASURE(order_count)
    comment: "Ticket médio = receita bruta / pedidos"
    synonyms: ["ticket médio"]
$$;

-- Verificações
SELECT order_status, MEASURE(gross_revenue) AS gross_revenue, MEASURE(order_count) AS orders, MEASURE(avg_ticket) AS avg_ticket
FROM workspace.atlas_spike_s0_4.mv_orders
GROUP BY order_status;

-- Consistência com SQL direto
SELECT o_orderstatus, SUM(o_totalprice), COUNT(1), SUM(o_totalprice)/COUNT(1)
FROM samples.tpch.orders GROUP BY o_orderstatus;
