# ADR-0025 — Medidas com janela na metric view `mv_recharges`

- **Status:** aceito
- **Data:** 2026-11-25
- **Decisores:** mantenedor
- **Relacionados:** SPEC-004 §5, [spike P15.2](../spikes/P15.2-window-measures.md), SPEC-007, ADR-0005, princípio 1 da mission

## Contexto
O `atlas-web` calcula o `mom_change` no backend, o que contraria o princípio 1 (métrica definida só na camada semântica). A v1.1 quer `gross_revenue_t3m`, `gross_revenue_ytd` e `revenue_mom_change` como medidas da metric view. A sintaxe `window` é experimental (documentada com `version: 0.1`) e a `mv_recharges` usa `version: 1.1`, necessária para `synonyms` e `format`. O spike P15.2 (rodado no `dev` em 2026-11-25) confirmou que as duas convivem e que `WHERE recharge_month = M` preserva a janela agrupando por região, UF ou município, com resultados iguais ao gold.

## Critérios de decisão
- Uma única definição por métrica (princípio 1).
- A janela sobrevive ao filtro de mês e ao agrupamento geográfico (a SPEC-007 depende disso).
- Resultado igual ao SQL direto no gold (ao centavo; 4 casas na variação).
- Menor superfície nova: consumidores, grants, Genie e lista fechada do MCP.
- Latência aceitável (p95 do dashboard < 3 s).

## Opções consideradas
1. **A. Janelas na `mv_recharges`.** Três medidas novas na view existente.
2. **B. View separada `mv_recharges_trend` (`version: 0.1`).** Repete as dimensões necessárias; entra em `semantic_grants`, no Genie e no MCP.
3. **C. Manter a conta no backend.** Declara a exceção ao princípio 1 e fecha P15.5 a P15.7 como "documentar".


## Decisão
Escolhemos **A: janelas na `mv_recharges`**, porque o spike mostrou que `window` aceita `version: 1.1` com `synonyms` e `format`, que a janela sobrevive ao filtro de mês e ao agrupamento geográfico, que o filtro `pos_type` vale antes dela (o de distribuidor fica para o `check_mv_windows.py` da P15.5) e que os valores batem com o gold ao centavo (`revenue_mom_change` em 4 casas), em 3 meses e 2 recortes (ver "Não conferido" no spike). Uma consulta isolada por UF levou o mesmo tempo com e sem janela; o p95 do dashboard (< 3 s) não foi medido e fica para a P15.9. Descartadas: **B** (view separada, sem ganho e com custo de grants, Genie e MCP) e **C** (manter no backend, que deixaria a métrica no consumidor). A SPEC-004 §5 não muda de ramo; o formato de consulta e os detalhes (`trailing 2` mais o mês atual, `COALESCE`, `recharge_year`) entram nela e na P15.5.

## Prós e contras das opções
### A. Janelas na `mv_recharges`
- 👍 Uma só view; nenhum grant, Genie ou catálogo novo.
- 👎 Sintaxe experimental no Databricks (risco de mudança).

### B. View separada `mv_recharges_trend`
- 👍 Isola a sintaxe experimental; `mv_recharges` não corre risco.
- 👎 Repete dimensões; mais uma view para grants, Genie e MCP; exige corrigir SPEC-004 §6 e §7 e a SPEC-006.

### C. Manter no backend
- 👍 Nenhum risco de plataforma.
- 👎 Mantém métrica calculada em consumidor (violação do princípio 1, só tolerável como exceção declarada).

## Consequências
- **Positivas:** `mom_change`, YTD e janela móvel passam a ter uma só definição, lida igualmente por AI/BI, Genie, agente, MCP e React.
- **Negativas, aceitas conscientemente:** o Δ% de `recharge_count`, `avg_ticket` e `active_pos` e o `compare_months` do MCP seguem calculados no consumidor (exceção declarada na SPEC-004 §5).
- **Plano B / gatilho para revisitar:** se o Databricks mudar a sintaxe de `window` ou a Free Edition deixar de aceitá-la, cair para B e depois C. `t3m` vale 0,00 onde `gross_revenue` é `NULL` (sem recarga aprovada); aceito.
