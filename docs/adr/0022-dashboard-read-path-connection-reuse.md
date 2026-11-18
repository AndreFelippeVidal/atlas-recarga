# ADR-0022 — Ler o dashboard do warehouse com conexão reaproveitada; descartar o Lakebase

- **Status:** proposto
- **Data:** 2026-11-18
- **Decisores:** mantenedor
- **Relacionados:** SPEC-007 §2, §3 e §6, ADR-0005, ADR-0009, [spike P12.10](../spikes/P12.10-dashboard-latency.md)

## Contexto
A SPEC-007 §6 pede p95 < 3 s para renderizar os municípios de uma UF com o cache de API frio. O spike P12.10 mediu o `atlas-web` no `dev`: com o cache frio, todo endpoint levava de 2,7 a 5,5 s (um clique em UF, de 2,9 a 4,0 s), com o warehouse quente ou não. Com o cache quente, 2 ms. O agregado pré-calculado não ajudou (p50 3.145 ms contra 3.374 ms na metric view): o tempo não estava na consulta. O `sql_client.py` abre uma conexão nova (`Config()`, auth, `dbsql.connect`) a cada `execute`; reaproveitar a conexão levou a consulta de UFs de 3.362 ms para 343 ms (p50; p95 4.581 para 496 ms). O Lakebase leu em 142 ms (p50), com a synced table `ONLINE` em ~6 min.

## Critérios de decisão
- Cumprir o p95 < 3 s com o menor número de peças novas (Free Edition, 3 slots de App, limite de pipelines).
- Princípio 1: uma definição por métrica; consumidores só leem `atlas.semantic`.
- Custo de operação: o que precisa ser reconstruído a cada `atlas_daily`.

## Opções consideradas
1. **Reaproveitar a conexão do warehouse + aquecer o cache na subida (em paralelo)**
2. **Lakebase com uma synced table de um agregado derivado de `mv_recharges`**
3. **Agregado pré-calculado em `semantic`, lido pelo warehouse**
4. **Manter como está** (conexão nova por consulta)

## Decisão
Escolhemos a **opção 1**. A latência estava na abertura da conexão, e consertá-la entrega 343 ms (p50) sem peça nova. O aquecimento em paralelo da subida (7 consultas: 24 s em sequência, 6,4 s em 4 threads, medidas com conexão nova a cada uma) deixa de importar na prática com a conexão reaproveitada, mas segue como reforço barato contra o 1º acesso após o auto-stop de 24 h.

## Prós e contras das opções
### 1. Conexão reaproveitada + aquecimento
- 👍 Corrige a causa medida; nenhuma tecnologia nova; segue lendo `mv_recharges` por `MEASURE()` (princípio 1 intacto).
- 👎 Conexão longa precisa de reconexão em caso de erro e de cuidado com threads (uma conexão por thread, ou um pool pequeno).

### 2. Lakebase (descartada)
- 👍 Leitura mais rápida, 142 ms (p50) contra 343 ms (p50) da opção 1, uma diferença de ~200 ms que o usuário não percebe.
- 👎 Adiciona uma tecnologia estrutural (exige `tech-stack.md` e uma revisão do ADR-0009), um pipeline gerenciado na sync e um agregado derivado que precisa ser regenerado e ressincronizado após cada `atlas_daily`. A sync SNAPSHOT leva ~6 min. O Postgres não executa `MEASURE()`, então o agregado vira uma segunda cópia das métricas em `semantic` (risco ao princípio 1). Conexão nova ao Postgres custa 1,5 s, então também exige reaproveitar conexão.

### 3. Agregado em `semantic` lido pelo warehouse (descartada)
- 👍 Respeita o princípio 1 (derivado de `MEASURE()`).
- 👎 Não ganha nada medido (p50 3.145 ms contra 3.374 ms) e acrescenta um passo de refresh.

### 4. Manter (descartada)
- 👎 Falha o critério da §6 (p95 de 4,5 s na consulta, antes da geometria).

## Consequências
- **Positivas:** o critério de p95 < 3 s fica ao alcance sem mudar a arquitetura; nada a atualizar em `tech-stack.md` nem no ADR-0009.
- **Negativas, aceitas conscientemente:** o código do `sql_client.py` passa a gerenciar o ciclo de vida da conexão (reconexão e threads), e a medida atual veio de fora do App; o p95 real é da P12.8. O spike não mediu o warehouse parado de verdade (o "frio" não ficou pior que o "quente", provavelmente porque o warehouse retoma rápido). A decisão não depende disso, mas o 1º acesso após o auto-stop de 24 h deve ser medido na P12.8.
- **Plano B / gatilho para revisitar:** se na P12.8 o p95 em produção passar de 3 s mesmo com a conexão reaproveitada, reabrir o Lakebase. Ele já foi testado (synced table SNAPSHOT `ONLINE`; o `atlas_daily` rodou normalmente com o pipeline da sync existente, mas os dois pipelines rodando ao mesmo tempo não foram testados; ver o spike).
