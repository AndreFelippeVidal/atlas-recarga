# SPEC-007 — Dashboard React com mapa do Brasil (`atlas-web`)

> PRD: F8 · ADRs: [0004](../../adr/0004-ibge-code-geojson-geo.md), [0009](../../adr/0009-three-apps-allocation.md) · Status: rascunho

## 1. Objetivo
Uma tela executiva de impacto: KPIs do mês e um **mapa coroplético do Brasil por região**. Ao clicar numa região, o mapa **dá zoom e mostra só as UFs** dela; ao clicar numa UF, **dá zoom e mostra os municípios** daquele estado, tudo colorido pela mesma métrica (Brasil › Região › UF › município). Os dados vêm só das metric views.

## 2. Arquitetura

| Camada | Escolha |
|---|---|
| Frontend | React 18 + TypeScript + Vite; mapa em **SVG com `d3-geo`** (projeção `geoMercator` com `fitSize`), sem tiles nem chave de API externa |
| Backend | FastAPI no mesmo Databricks App, servindo o build estático e `/api/*` |
| Dados | `databricks-sql-connector` → SQL warehouse → `atlas.semantic.mv_recharges` |
| Geometria | Malhas do IBGE (API de malhas v3), baixadas **no build** por `scripts/fetch_geo.py`, simplificadas (mapshaper, ~1–5% dos vértices) e versionadas em `web/public/geo/` |
| Auth | Autenticação nativa do Databricks App; o backend consulta com o service principal (`SELECT` em `semantic`) |

Arquivos de geometria:
- `geo/br-uf.json`: 27 UFs (TopoJSON, ≤ 300 KB), com as propriedades `uf` e `region` (`N`, `NE`, `CO`, `SE`, `S`, de `dim_municipality`). Não há geometria própria de região: no nível Brasil as UFs são pintadas com o valor da sua região e as fronteiras das regiões ficam em destaque; o zoom usa o bounding box das UFs da região.
- `geo/mun/<UF>.json`: municípios de cada UF (TopoJSON, ≤ 1,5 MB cada), com propriedade `municipality_ibge_code`. Carregados **sob demanda** no clique.

## 3. API do backend

| Endpoint | Query params | Retorno |
|---|---|---|
| `GET /api/kpis` | `month` | `gross_revenue`, `recharge_count`, `avg_ticket`, `active_pos`, com o valor do mês anterior e Δ% |
| `GET /api/map/region` | `month`, `measure` | `[{region, value}]` para as 5 regiões |
| `GET /api/map/uf` | `month`, `measure`, `region` (opcional) | `[{uf, value}]` para as 27 UFs, ou só as da região |
| `GET /api/map/municipality` | `month`, `measure`, `uf` | `[{municipality_ibge_code, municipality_name, value}]` |
| `GET /api/months` | — | Meses disponíveis (para o seletor) |
| `GET /api/health` | — | Status do App e do warehouse |

`measure ∈ {gross_revenue, recharge_count, avg_ticket, active_pos, mom_change}`. `mom_change` = Δ% de `gross_revenue` contra o mês anterior, calculado no backend a partir de duas consultas. O valor de cada nível vem de `MEASURE()` agrupado pela dimensão do nível (`region`, `uf`, `municipality_ibge_code`): o frontend **nunca** soma UFs para obter a região, porque `avg_ticket` e `active_pos` não são aditivos. Qualquer outro valor retorna **400**.
**Cache:** em memória por `(endpoint, params)` por 10 minutos (os dados são D-1).

## 4. Comportamento da tela

**Layout (desktop ≥ 1280px):** linha de 4 KPI cards no topo; mapa ocupando ~65% à esquerda; painel lateral com o ranking top 10 (regiões, UFs ou municípios, conforme o nível) e uma breadcrumb `Brasil › Norte › PA`. Em mobile os blocos empilham.

| Interação | Resultado |
|---|---|
| Carregar a página | Último mês fechado; medida `gross_revenue`; nível Brasil (5 regiões) |
| Trocar mês ou medida | Recolore o mapa e atualiza KPIs e ranking, sem recarregar a geometria |
| Hover numa UF ou município | Tooltip: nome, valor formatado (`R$ 1,2 mi`, `12.345`), posição no ranking |
| **Clique numa região** | Busca `/api/map/uf?region=<R>`; transição de zoom de 600 ms até o bounding box das UFs da região; só as UFs da região ficam no centro, coloridas por UF; as outras regiões somem ou ficam esmaecidas |
| **Clique numa UF** (a partir do nível região ou do ranking) | Busca `geo/mun/<UF>.json` e `/api/map/municipality`; transição de zoom de 600 ms até o bounding box da UF; municípios coloridos; as outras UFs ficam esmaecidas |
| Clicar na breadcrumb ("Brasil", região) ou apertar Esc | Sobe um nível (município → UF → região → Brasil) com a transição inversa |
| Clicar num item do ranking | Mesmo efeito de clicar no polígono do nível atual |

**Escala de cor:**
- Medidas de volume: escala **sequencial** em 5 classes por **quantis** calculados no nível atual (no zoom, os quantis são recalculados entre as UFs da região ou entre os municípios da UF).
- `mom_change`: escala **divergente** centrada em 0%, com vermelho para queda e azul para alta e simetria em ±max(|min|, |max|).
- Município sem dado: cinza claro com padrão hachurado e o rótulo "sem recargas" no tooltip.
- A legenda sempre mostra os limites das classes e a unidade. As cores passam em contraste AA e funcionam em tema claro e escuro.

**Estados:** skeleton durante o carregamento; em erro de API, um banner "Não foi possível carregar os dados (código)" com botão para tentar de novo, mantendo o mapa anterior; com o warehouse frio, a mensagem "Aquecendo o banco de dados…" depois de 3s.

## 5. Acessibilidade
Cada polígono tem `role="button"`, `aria-label` com o nome e o valor, e navegação por Tab no ranking. A informação nunca depende só da cor, porque o ranking e o tooltip repetem o valor.

## 6. Critérios de aceite
- **Dado** o cenário `regional_drop`, **quando** seleciono o penúltimo mês e `mom_change` e clico no PA, **então** os municípios do Baixo Amazonas aparecem na classe de maior queda.
- **Dado** um mês, **então** a soma de `/api/map/region` e a de `/api/map/uf` para `gross_revenue` são iguais ao KPI `gross_revenue` e ao valor do AI/BI Dashboard.
- **Dado** um clique numa região, **então** só as UFs dela ficam visíveis e centralizadas; **dado** um clique numa UF, **então** o mapa mostra direto os municípios dela.
- **Dado** um clique numa UF, **então** a renderização dos municípios termina em p95 < 3s com cache frio de API e geometria em cache do navegador.
- **Dado** `measure=foo`, **então** a API retorna 400.
- **Dado** qualquer UF, **então** 100% dos municípios da malha do IBGE têm match por `municipality_ibge_code` (teste automatizado entre geometria e `dim_municipality`).
- **Dado** a API fora do ar, **então** o banner de erro aparece e a página não quebra.

## 7. Fora de escopo
Aprovação de comissão na UI (v2), filtros por distribuidor e tipo de PDV no mapa (v1.1), mapa de pontos por PDV (v2, com geo híbrido), exportar em PDF ou imagem.
