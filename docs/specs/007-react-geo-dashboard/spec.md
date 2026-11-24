# SPEC-007 — Dashboard React com mapa do Brasil (`atlas-web`)

> PRD: F8 · ADRs: [0004](../../adr/0004-ibge-code-geojson-geo.md), [0009](../../adr/0009-three-apps-allocation.md), [0023](../../adr/0023-dashboard-agent-chat-streaming.md) · Status: rascunho

## 1. Objetivo
Uma tela executiva de impacto: KPIs do mês e um **mapa coroplético do Brasil por região**. Ao clicar numa região, o mapa **dá zoom e mostra só as UFs** dela; ao clicar numa UF, **dá zoom e mostra os municípios** daquele estado, tudo colorido pela mesma métrica (Brasil › Região › UF › município). Os dados vêm só das metric views.

## 2. Arquitetura

| Camada | Escolha |
|---|---|
| Frontend | React 18 + TypeScript + Vite; mapa em **SVG com `d3-geo`** (projeção `geoMercator` com `fitSize`), sem tiles nem chave de API externa |
| Backend | FastAPI no mesmo Databricks App, servindo o build estático e `/api/*`. O build do Vite fica **versionado** em `apps/web/static` (o App não tem Node; o CI confere que está atualizado) e as malhas saem de `apps/web/public/geo/` em `/geo` |
| Dados | `databricks-sql-connector` → SQL warehouse → `atlas.semantic.mv_recharges` |
| Geometria | Malhas do IBGE (API de malhas v3), baixadas **no build** por `scripts/fetch_geo.py`, simplificadas (mapshaper, ~1–5% dos vértices) e versionadas em `apps/web/public/geo/` |
| Auth | Autenticação nativa do Databricks App; o backend consulta os dados com o service principal (`SELECT` em `semantic`). O chat é a exceção: repassa o **token do usuário** (OBO, `user_api_scopes`) ao `agent-atlas` (ADR-0023; escopo `apps`, confirmado na P12.14) |
| Chat | Painel recolhível; `POST /api/chat` repassa a pergunta ao `agent-atlas` e devolve a resposta **em streaming SSE**. O `atlas-web` não roda LLM, não lê o Genie e não calcula métrica; o SP dele não ganha permissão nenhuma no agente |

Arquivos de geometria:
- `geo/br-uf.json`: 27 UFs (TopoJSON, ≤ 300 KB), com as propriedades `uf` e `region` (`N`, `NE`, `CO`, `SE`, `S`, de `dim_municipality`). Não há geometria própria de região: no nível Brasil as UFs são pintadas com o valor da sua região e as fronteiras das regiões ficam em destaque; o zoom usa o bounding box das UFs da região.
- `geo/mun/<UF>.json`: municípios de cada UF (TopoJSON, ≤ 1,5 MB cada), com propriedade `municipality_ibge_code`. Carregados **sob demanda** no clique.

## 3. API do backend

| Endpoint | Query params | Retorno |
|---|---|---|
| `GET /api/kpis` | `month`, `pos_type`, `distributor` | `gross_revenue`, `recharge_count`, `avg_ticket`, `active_pos`, com o valor do mês anterior e Δ% |
| `GET /api/map/region` | `month`, `measure`, `pos_type`, `distributor` | `[{region, value}]` para as 5 regiões |
| `GET /api/map/uf` | `month`, `measure`, `region` (opcional), `pos_type`, `distributor` | `[{uf, value}]` para as 27 UFs, ou só as da região |
| `GET /api/map/municipality` | `month`, `measure`, `uf`, `pos_type`, `distributor` | `[{municipality_ibge_code, municipality_name, value}]` (`uf` obrigatório) |
| `GET /api/months` | — | Meses disponíveis (para o seletor) |
| `GET /api/filters` | — | `{pos_types: [...], distributors: [...]}`: os valores válidos dos filtros, lidos da metric view |
| `GET /api/reading` | `month`, `level` (`brasil` ou `region`), `region` (com `level=region`), `pos_type`, `distributor` | Itens da "Leitura do mapa" (abaixo) |
| `GET /api/health` | — | Status do App e do warehouse |
| `POST /api/chat` | corpo `{message, conversation_id?}` | Stream SSE com a resposta do agente (abaixo) |

`measure ∈ {gross_revenue, recharge_count, avg_ticket, active_pos, mom_change}`. `mom_change` = Δ% de `gross_revenue` contra o mês anterior; vale `null` quando o mês anterior não tem base (ausente ou zero). **A partir da v1.1 o valor vem de `MEASURE(revenue_mom_change)` (SPEC-004 §5)**, convertido para pontos percentuais com 2 casas; o backend não faz mais a divisão (antes da P15.7 ele ainda a faz).
**Filtros (v1.1).** `pos_type` e `distributor` são opcionais e valem para KPIs, mapa, ranking, `mom_change` e leitura. `pos_type` só aceita os 5 valores da lista fechada (`newsstand`, `pharmacy`, `grocery`, `lottery`, `partner_app`); `distributor` só aceita um valor devolvido por `/api/filters`; qualquer outro é **400**. Os dois entram como **parâmetros vinculados** na consulta, nunca concatenados, e fazem parte da chave do cache. Os filtros recortam o `WHERE` da metric view antes da conta, então `avg_ticket` e `active_pos` continuam corretos. O chat não recebe os filtros. Um mês que existe no total, mas **sem recarga no recorte filtrado**, devolve `200`: listas vazias nos mapas e KPIs com `"0.00"` ou `"0"` (`avg_ticket`, `previous` e `delta_pct` em `null`); `404` fica só para o mês sem nenhuma recarga no total, e `/api/months` não é filtrado.
**Leitura do mapa (`/api/reading`, v1.1).** Texto **determinístico, sem IA**, só sobre UFs (`level=brasil`: as 27 UFs; `level=region`: as UFs da região); não existe leitura no nível município, onde uma base minúscula produz variações de +300% que enganam. O backend **só escolhe e ordena valores devolvidos por `MEASURE()`**, sem somar nem dividir: `items` é uma lista de `{kind, uf, value, delta_pct}` com `kind ∈ {top_revenue, top_rise, top_drop}`: a UF de maior `gross_revenue`, a de maior alta e a de maior queda de `revenue_mom_change`. Sem mês anterior, ou sem nenhuma UF com variação, só `top_revenue` aparece; uma UF com variação `null` não entra. O frontend monta a frase com os formatadores que já existem, e a frase cita o valor, nunca calcula. O valor de cada nível vem de `MEASURE()` agrupado pela dimensão do nível (`region`, `uf`, `municipality_ibge_code`): o frontend **nunca** soma UFs para obter a região, porque `avg_ticket` e `active_pos` não são aditivos. Qualquer outro valor retorna **400**, assim como `region` fora de `N`, `NE`, `CO`, `SE`, `S` e `uf` ausente ou fora das 27 siglas. As listas trazem só as linhas com valor no mês (regiões, UFs ou municípios sem recarga ficam de fora; o frontend os trata como "sem recargas"); um mês sem nenhuma recarga é **404**, e uma UF sem recarga num mês que existe é lista vazia.
**Formato:** valores numéricos saem como **string decimal** (`"4122460.00"`), sem float; `delta_pct` em pontos percentuais com 2 casas. No primeiro mês da série `previous` e `delta_pct` são `null`. Erros: `400 INVALID_ARGUMENT` (parâmetro inválido), `404 NOT_FOUND` (mês sem dados), `503 WAREHOUSE_UNAVAILABLE`. `/api/health` devolve `status` (do App, sempre `healthy` se responde) e `warehouse` (estado, sem acordá-lo).
**Chat (`POST /api/chat`, ADR-0023):** `message` não vazia e com no máximo 2.000 caracteres (senão `400 INVALID_ARGUMENT`); `conversation_id` opcional vai ao agente como `context.conversation_id`. A resposta é `text/event-stream` com os eventos `delta` (`{text}`, trecho a acrescentar), `done` (`{text}`, texto final completo que **substitui** o acumulado) e `error` (`{code, message}`, terminal; `AGENT_UNAVAILABLE`, `RATE_LIMITED`, `TIMEOUT`, `AGENT_ERROR`). Antes do primeiro byte, os erros são HTTP: `400 INVALID_ARGUMENT`, `403 PERMISSION_DENIED` (o usuário sem `CAN_USE` no `agent-atlas`), `429 RATE_LIMITED` (limite por usuário) e `503 AGENT_UNAVAILABLE`. Timeouts: 10 s para conectar, 60 s sem byte do agente e 120 s no total, com `: ping` (comentário SSE) a cada 15 s ao navegador; sem retentativa e sem cache; 10 mensagens por minuto por usuário. O backend não interpreta o texto: o número vem do agente, com o bloco `Fonte:`.
**Detalhes do chat (P12.13):** `conversation_id` tem no máximo 128 caracteres (senão `400`). Sem o cabeçalho `x-forwarded-access-token` a rota devolve `403 PERMISSION_DENIED` e nunca chama o agente com outra identidade. O limite por usuário usa `x-forwarded-email` (ou, na falta dele, um hash do token) e conta só as mensagens que passaram na validação. O agente respondendo `401`, `403` ou redirect antes do primeiro byte vira `403 PERMISSION_DENIED`; outro status de erro ou conexão recusada vira `503 AGENT_UNAVAILABLE`; um `429` do agente antes do primeiro byte vira `200` com o evento `error RATE_LIMITED` (o `429` HTTP é só o limite por usuário do `atlas-web`). O `done` leva o texto da **última mensagem não vazia** do agente; um stream que acaba sem mensagem vira `error AGENT_ERROR`, sem inventar resposta. O cliente HTTP assíncrono é o `httpx2`.
**Cache:** em memória por `(endpoint, params)` por 10 minutos (os dados são D-1). Na subida, o backend aquece o cache da tela do último mês (meses, KPIs, regiões e UFs) em segundo plano, sem bloquear a subida, e o renova a cada 8 minutos, antes do TTL (ADR-0022). A conexão com o warehouse é reaproveitada, uma por thread.

## 4. Comportamento da tela

**Layout (desktop ≥ 1280px):** linha de 4 KPI cards no topo; mapa ocupando ~65% à esquerda; painel lateral com o ranking top 10 (regiões, UFs ou municípios, conforme o nível) e uma breadcrumb `Brasil › Norte › PA`. Em mobile os blocos empilham.

| Interação | Resultado |
|---|---|
| Carregar a página | Último mês fechado; medida `gross_revenue`; nível Brasil (5 regiões) |
| Trocar mês ou medida | Recolore o mapa e atualiza KPIs e ranking, sem recarregar a geometria |
| Trocar o filtro de tipo de PDV ou de distribuidor (v1.1) | Dois seletores ao lado do mês e da medida, cada um com "Todos" como padrão; o recorte vale para KPIs, mapa, ranking e leitura e **mantém o nível e o zoom atuais**. Uma combinação sem recarga mostra o estado vazio "Sem recargas neste recorte" com o botão "Limpar filtros". O estado dos filtros fica só na memória da página |
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

**Leitura do mapa (v1.1):** bloco no painel lateral, abaixo do ranking, com o título "Leitura do mapa" e até 3 frases, por exemplo "Maior receita: SP (R$ 1,38 mi)", "Maior alta contra set de 2026: AC (+12,40%)" e "Maior queda: RR (−8,10%), onde olhar primeiro". Acompanha o nível (Brasil ou região); no nível UF e município o bloco some. Não substitui o ranking nem o tooltip, e a informação nunca depende só da cor.

**Painel de chat:** botão "Perguntar ao agente" abre um painel recolhível (teclado: Enter envia, Shift+Enter quebra a linha, Esc fecha). A resposta aparece aos poucos conforme os `delta`, e o `done` troca o texto pelo final. O painel renderiza o **Markdown** da resposta (ADR-0024: `react-markdown` + `remark-gfm`, `skipHtml`, só os elementos parágrafo, ênfase, listas, código, citação, tabela, título e link `http(s)` com `rel="noopener noreferrer"`; imagens e HTML cru nunca) e mostra o bloco final `Fonte:` destacado como citação, com o texto do agente intacto, **sem calcular, somar nem reformatar número**, e não altera o mapa nem os KPIs. Visual: balões de pergunta e de resposta, indicador de digitação durante o streaming, botão flutuante e tokens claro/escuro do dashboard, com foco visível e contraste AA. Estados: vazio (sugestões fixas de perguntas), enviando (o botão vira "Parar", que aborta a conexão), erro por código (`RATE_LIMITED`: "Limite de uso atingido, tente em 1 minuto"; `AGENT_UNAVAILABLE`: "O agente está parado ou indisponível"; `PERMISSION_DENIED`: "Você não tem acesso ao agente"; `TIMEOUT`) com "Tentar de novo". O histórico fica só na memória da página.

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
- **Dado** o filtro `pos_type = pharmacy` (v1.1), **então** a soma das UFs e a das regiões de `gross_revenue` são iguais ao KPI filtrado, e o KPI é igual ao SQL direto no gold com o mesmo filtro; o mesmo vale para um distribuidor e para os dois juntos.
- **Dado** `pos_type=foo`, `distributor` fora de `/api/filters` ou `level=municipality` em `/api/reading`, **então** `400`; **dado** um filtro sem recarga num mês existente, **então** `200` com o estado vazio, e a tela não quebra.
- **Dado** o `mom_change` lido da metric view (v1.1), **então** os valores nos 3 níveis são iguais, com 2 casas, aos de antes da mudança.
- **Dado** um mês, **então** a "Leitura do mapa" cita a UF de maior receita (a mesma do topo do ranking), a de maior alta e a de maior queda de `mom_change`, e o teste confere o resultado contra o SQL direto no gold.
- **Dado** a P15.9 no `dev`, **então** o p95 de `/api/map/municipality` com e sem filtro fica abaixo de 3 s (P12.8) e o `atlas-web` continua sem SQL fora de `semantic`.
- **Dado** GS-001 perguntado pelo painel (conferência manual na P12.14), **então** o texto vai chegando em `delta`, termina com o mesmo valor do agente (R$ 4.122.460,00) e o bloco `Fonte:`; o trace do agente tem a tag `user` com o usuário do dashboard.
- **Dado** uma mensagem vazia ou com mais de 2.000 caracteres, **então** `400`; **dado** o agente parado ou lento demais, **então** o painel mostra o erro do §4 e o resto do dashboard segue funcionando.
- **Dado** o chat em uso, **então** o p95 de `/api/map/municipality` (P12.8) não piora e o `atlas-web` continua sem SQL fora de `semantic`.

## 7. Fora de escopo
Histórico de conversas entre sessões, o chat alterar o mapa ou os filtros, qualquer ação de escrita pelo chat. Aprovação de comissão na UI (v2), filtros de região, UF e faixa de meses (depois da Fase 15), leitura no nível município, texto gerado por IA, mapa de pontos por PDV (v2, com geo híbrido), exportar em PDF ou imagem.
