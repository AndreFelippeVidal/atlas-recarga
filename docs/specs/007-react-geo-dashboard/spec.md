# SPEC-007 — Dashboard React com mapa do Brasil (`atlas-web`)

> PRD: F8 · ADRs: [0004](../../adr/0004-ibge-code-geojson-geo.md), [0009](../../adr/0009-three-apps-allocation.md) · Status: rascunho

## 1. Objetivo
Uma tela executiva de impacto: KPIs do mês e um **mapa coroplético do Brasil por região**. Ao clicar numa região, o mapa **dá zoom e mostra só as UFs** dela; ao clicar numa UF, **dá zoom e mostra os municípios** daquele estado, tudo colorido pela mesma métrica (Brasil › Região › UF › município). Os dados vêm só das metric views.

## 2. Arquitetura

| Camada | Escolha |
|---|---|
| Frontend | React 18 + TypeScript + Vite; mapa em **SVG com `d3-geo`** (projeção `geoMercator` com `fitSize`), sem tiles nem chave de API externa |
| Backend | FastAPI no mesmo Databricks App, servindo o build estático e `/api/*`. O build do Vite fica **versionado** em `apps/web/static` (o App não tem Node; o CI confere que está atualizado) e as malhas saem de `apps/web/public/geo/` em `/geo` |
| Dados | `databricks-sql-connector` → SQL warehouse → `atlas.semantic.mv_recharges` |
| Geometria | Malhas do IBGE (API de malhas v3), baixadas **no build** por `scripts/fetch_geo.py`, simplificadas (mapshaper, ~1–5% dos vértices) e versionadas em `apps/web/public/geo/` |
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
| `GET /api/map/municipality` | `month`, `measure`, `uf` | `[{municipality_ibge_code, municipality_name, value}]` (`uf` obrigatório) |
| `GET /api/months` | — | Meses disponíveis (para o seletor) |
| `GET /api/health` | — | Status do App e do warehouse |

`measure ∈ {gross_revenue, recharge_count, avg_ticket, active_pos, mom_change}`. `mom_change` = Δ% de `gross_revenue` contra o mês anterior, calculado no backend a partir de uma consulta com os dois meses; vale `null` quando o mês anterior não tem base (ausente ou zero). O valor de cada nível vem de `MEASURE()` agrupado pela dimensão do nível (`region`, `uf`, `municipality_ibge_code`): o frontend **nunca** soma UFs para obter a região, porque `avg_ticket` e `active_pos` não são aditivos. Qualquer outro valor retorna **400**, assim como `region` fora de `N`, `NE`, `CO`, `SE`, `S` e `uf` ausente ou fora das 27 siglas. As listas trazem só as linhas com valor no mês (regiões, UFs ou municípios sem recarga ficam de fora; o frontend os trata como "sem recargas"); um mês sem nenhuma recarga é **404**, e uma UF sem recarga num mês que existe é lista vazia.
**Formato:** valores numéricos saem como **string decimal** (`"4122460.00"`), sem float; `delta_pct` em pontos percentuais com 2 casas. No primeiro mês da série `previous` e `delta_pct` são `null`. Erros: `400 INVALID_ARGUMENT` (parâmetro inválido), `404 NOT_FOUND` (mês sem dados), `503 WAREHOUSE_UNAVAILABLE`. `/api/health` devolve `status` (do App, sempre `healthy` se responde) e `warehouse` (estado, sem acordá-lo).
**Cache:** em memória por `(endpoint, params)` por 10 minutos (os dados são D-1). Na subida, o backend aquece o cache da tela do último mês (meses, KPIs, regiões e UFs) em segundo plano, sem bloquear a subida, e o renova a cada 8 minutos, antes do TTL (ADR-0022). A conexão com o warehouse é reaproveitada, uma por thread.

## 4. Comportamento da tela

**Layout (desktop ≥ 1280px):** linha de 4 KPI cards no topo; mapa ocupando ~65% à esquerda; painel lateral com o ranking top 10 (regiões, UFs ou municípios, conforme o nível) e uma breadcrumb `Brasil › Norte › PA`. Em mobile os blocos empilham.

| Interação | Resultado |
|---|---|
| Carregar a página | Último mês fechado; medida `gross_revenue`; nível Brasil (5 regiões) |
| Trocar mês ou medida | Recolore o mapa e atualiza KPIs e ranking, sem recarregar a geometria |
| Hover numa UF ou município | Tooltip: nome, valor formatado (`R$ 1,2 mi`, `12.345`), posição no ranking |
| **Clique numa região** | Busca `/api/map/uf?region=<R>`; o mapa é enquadrado no bounding box das UFs da região, com transição de 600 ms (entrada com fade e leve zoom, sem animação intermediária de câmera); só as UFs da região ficam no centro, coloridas por UF; as outras regiões **somem**. Um botão "← Ver o Brasil inteiro" acima do mapa volta direto ao nível Brasil |
| **Clique numa UF** (a partir do nível região ou do ranking) | Busca `geo/mun/<UF>.json` e `/api/map/municipality`; o mapa é enquadrado no bounding box da UF, com a mesma transição de 600 ms; municípios coloridos e centralizados; as outras UFs **somem** |
| Clicar na breadcrumb ("Brasil", região) ou apertar Esc | Sobe um nível (município → UF → região → Brasil) com a mesma transição |
| Clicar num item do ranking | Mesmo efeito de clicar no polígono do nível atual |

**Escala de cor:**
- Medidas de volume: escala **sequencial** em 5 classes por **quantis** calculados no nível atual (no zoom, os quantis são recalculados entre as UFs da região ou entre os municípios da UF).
- `mom_change`: escala **divergente** centrada em 0%, com vermelho para queda e azul para alta. O limite simétrico é o **percentil 90 de |valor|** no nível atual (não o máximo: um município com base minúscula e +1.400% apagaria o resto da escala); o que passa do limite fica na classe extrema e a legenda avisa "extremos agrupados". Se o percentil 90 for 0, o limite é o máximo de |valor|. Em qualquer tema, **quanto mais escura a cor, mais extrema a variação**, seja queda ou alta; o neutro ("perto de 0%") é a classe mais clara. O ranking de `mom_change` mostra as 5 maiores altas e as 5 maiores quedas (com mais de 10 itens), pois o top 10 por valor decrescente esconderia as quedas.
- Município sem dado: cinza claro com padrão hachurado e o rótulo "sem recargas" no tooltip.
- A legenda sempre mostra os limites das classes e a unidade. As cores passam em contraste AA e funcionam em tema claro e escuro.

**Estados:** skeleton durante o carregamento; em erro de API, um banner "Não foi possível carregar os dados (código)" com botão para tentar de novo, mantendo o mapa anterior; com o warehouse frio, a mensagem "Aquecendo o banco de dados…" depois de 3s.

## 5. Acessibilidade
Cada polígono tem `role="button"`, `aria-label` com o nome e o valor, e navegação por Tab no ranking. A informação nunca depende só da cor, porque o ranking e o tooltip repetem o valor.

## 6. Critérios de aceite
- **Dado** o cenário `regional_drop` (−14% de recargas nos 13 municípios do Baixo Amazonas no penúltimo mês, SPEC-001 §5), **quando** seleciono o penúltimo mês e `mom_change` e clico no PA, **então** o tooltip e o ranking mostram o Δ% desses municípios (queda em torno de −14%, mais o ruído do dado). A classe de cor segue a escala do §4 (limite no percentil 90) e **não** é critério: uma queda de −14% cai em "perto de 0%" quando outros municípios variam ±70% ou mais.
- **Dado** um mês, **então** a soma de `/api/map/region` e a de `/api/map/uf` para `gross_revenue` são iguais ao KPI `gross_revenue` e ao valor do AI/BI Dashboard.
- **Dado** um clique numa região, **então** só as UFs dela ficam visíveis e centralizadas; **dado** um clique numa UF, **então** o mapa mostra direto os municípios dela.
- **Dado** um clique numa UF, **então** a renderização dos municípios termina em p95 < 3s com cache frio de API e geometria em cache do navegador. A medição (`scripts/measure_web_p95.py`) é a da **API** (`/api/map/municipality` por UF e medida, cache frio), contra o App implantado; o JSON da geometria e a renderização no navegador ficam fora dela.
- **Dado** `measure=foo`, **então** a API retorna 400.
- **Dado** qualquer UF, **então** 100% dos municípios da referência (a mesma que alimenta `dim_municipality`) têm polígono por `municipality_ibge_code`, e o único polígono da malha do IBGE sem linha na referência (Boa Esperança do Norte, MT) é descartado (teste automatizado entre geometria e referência).
- **Dado** a API fora do ar, **então** o banner de erro aparece e a página não quebra.

## 7. Fora de escopo
Aprovação de comissão na UI (v2), filtros por distribuidor e tipo de PDV no mapa (v1.1), mapa de pontos por PDV (v2, com geo híbrido), exportar em PDF ou imagem.
