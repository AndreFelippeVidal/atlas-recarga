# SPEC-001 — CLI de dados sintéticos (`atlas-cli`)

> PRD: F1 · ADRs: [0004](../../adr/0004-ibge-code-geojson-geo.md), [0011](../../adr/0011-deterministic-synthetic-cli.md) · Status: rascunho

## 1. Objetivo
Gerar um dataset sintético, realista e **determinístico** da rede de recarga da Eaí? Telecom, com anomalias injetadas de propósito para exercitar o pipeline, o mapa, a comissão e o agente.

## 2. Interface

Pacote Python `atlas_cli` (Typer), instalável com `uv`, e executável `atlas-cli`.

| Comando | Faz |
|---|---|
| `atlas-cli generate` | Gera as entidades em arquivos locais |
| `atlas-cli upload` | Envia os arquivos gerados para o Volume UC `/Volumes/atlas/raw/landing/` |
| `atlas-cli scenario list` | Lista as anomalias disponíveis e seus parâmetros |
| `atlas-cli validate` | Confere os invariantes da seção 6 sobre um diretório gerado |

### `generate` — flags

| Flag | Tipo | Padrão | Regra |
|---|---|---|---|
| `--rows` | int | `2_000_000` | Total aproximado de recargas (±1%). Mín. 1.000, máx. 10.000.000 |
| `--months` | int | `12` | Meses retroativos até o mês civil anterior ao `--end-month` |
| `--end-month` | `YYYY-MM` | mês corrente | O último mês gerado é `end-month - 1` (mês fechado) |
| `--pos` | int | `5_000` | Quantidade de PDVs |
| `--distributors` | int | `40` | Quantidade de distribuidores |
| `--seed` | int | `42` | **Mesma seed e mesmas flags produzem arquivos byte a byte idênticos** |
| `--scenarios` | lista CSV | `all` | Anomalias a injetar (seção 5). `none` desliga todas |
| `--out` | path | `./data/generated` | Diretório de saída |
| `--format` | `parquet`\|`csv` | `parquet` | |
| `--incremental-day` | `YYYY-MM-DD` | — | Gera só as recargas desse dia (simula a carga D-1 diária) |

Códigos de saída: `0` sucesso · `2` flag inválida · `3` arquivo de referência IBGE ausente ou inválido · `4` falha de upload.

## 3. Saída (layout)

```
<out>/
├── distributors/distributors.parquet
├── pos/pos.parquet
├── recharges/dt=YYYY-MM-DD/part-0000.parquet   # uma partição por dia
└── _manifest.json                               # seed, flags, contagens, sha256 por arquivo, versão do CLI
```

`upload` replica o mesmo layout em `/Volumes/atlas/raw/landing/`. É idempotente: arquivo com o mesmo sha256 não é reenviado.

## 4. Schemas

**Referência (versionada no repo, dado público):** `data/reference/municipalities_ibge.csv`, com os 5.570 municípios do Censo 2022 (Boa Esperança do Norte, MT, criado depois, fica de fora por não ter população), população do Censo 2022 e DDD. Colunas: `municipality_ibge_code, municipality_name, uf, region, population, ddd`. O `ddd` é **aproximado**: não há fonte pública por município, então cada município recebe o DDD da sua região imediata do IBGE (tabela mantida em `scripts/build_reference.py`). Serve para dados sintéticos e para separar o mapa por DDD, não como referência de telecom.

**distributors**

| coluna | tipo | regra |
|---|---|---|
| `distributor_id` | STRING | `DST-0001`… |
| `distributor_name` | STRING | Nome fictício (Faker pt_BR, seedado) |
| `hq_uf` | STRING | UF da sede |
| `created_date` | DATE | |

**pos**

| coluna | tipo | regra |
|---|---|---|
| `pos_id` | STRING | `POS-000001`… |
| `distributor_id` | STRING | FK; cada distribuidor atende 1 a 4 UFs contíguas |
| `pos_name` | STRING | Fictício |
| `pos_type` | STRING | `newsstand` 25%, `pharmacy` 20%, `grocery` 30%, `lottery` 15%, `partner_app` 10% |
| `municipality_ibge_code` | STRING(7) | Amostrado com peso ∝ população **× peso de pré-pago regional** (N 1,4 · NE 1,3 · CO 1,0 · SE 0,9 · S 0,8) |
| `opened_date` | DATE | |
| `closed_date` | DATE nullable | ~3% fecham durante o período |

**recharges**

| coluna | tipo | regra |
|---|---|---|
| `recharge_id` | STRING | UUIDv5 determinístico (seed + sequência) |
| `recharge_ts_utc` | TIMESTAMP | Curva intradiária com pico entre 11h e 13h e entre 18h e 21h (horário local) |
| `pos_id` | STRING | FK |
| `subscriber_id` | STRING | Hash sintético (`SUB-` + 10 hex). **Nunca** um número de telefone com formato real |
| `amount_brl` | DECIMAL(10,2) | Valores de face {10, 15, 20, 25, 30, 40, 50, 100} com pesos {22, 18, 20, 10, 12, 6, 9, 3}% |
| `status` | STRING | `approved` 98,5% · `reversed` 1,5% |
| `ingested_at_utc` | TIMESTAMP | Determinístico (invariante 1): 06:00 de `America/Sao_Paulo` do dia seguinte ao `dt=` da partição (09:00 UTC), o horário do job `atlas_daily`. Não é o relógio da máquina |

**Escolha do PDV e volume.** Só PDVs ativos no dia recebem recarga (`opened_date <= dia` e `closed_date` nula ou `>= dia`). O peso de cada PDV é sorteado com a seed, lognormal (σ = 0,8) × raiz quadrada da população do município, o que dá cauda longa (top PDVs e outliers para a comissão). O volume diário é uniforme até a sazonalidade abaixo ser implementada (P4.5). A flag `--scenarios` é validada desde já, mas a injeção só existe a partir da P4.6.

**Fuso e hora local.** `recharge_ts_utc` é o instante real em UTC. A curva intradiária é aplicada na **hora local do município do PDV**, e o fuso vem da UF (mapa fixo em código, sem exceções por município no MVP): AC em UTC−5; AM, RO, RR, MT e MS em UTC−4; as demais UFs em UTC−3 (horário de Brasília). A partição `dt=YYYY-MM-DD` usa o dia em `America/Sao_Paulo`, igual ao `recharge_date` do silver. Assim, uma recarga das 22h no AC (03h UTC do dia seguinte, 00h em São Paulo) cai na partição do dia seguinte. A hora local alimenta a análise de horários de pico (SPEC-002 e SPEC-004).

Sazonalidade: dia 5 a 10 (salário) +18%, dezembro +25%, fevereiro −8%, domingos −30%.

## 5. Cenários (anomalias injetadas)

| id | O que injeta | Quem deve detectar |
|---|---|---|
| `regional_drop` | −14% de volume nos municípios do oeste do PA (mesorregião Baixo Amazonas) no penúltimo mês | Mapa (SPEC-007) e agente (golden set) |
| `fractioning` | 3 PDVs fazendo dezenas de recargas de R$ 10 ao mesmo assinante em < 2 min | Flag de outlier na comissão (SPEC-003) |
| `duplicates` | 0,2% de `recharge_id` repetidos em arquivos diferentes | Deduplicação no silver (SPEC-002) |
| `null_pos` | 0,05% de recargas com `pos_id` nulo | Expectation drop no silver |
| `unknown_pos` | 0,05% de recargas com `pos_id` inexistente | Quarentena no silver |
| `late_arrival` | 0,5% das recargas de um dia aparecem no arquivo do dia seguinte | Silver usa `recharge_ts_utc`, não a partição |
| `negative_amount` | 10 recargas com valor negativo | Expectation drop no silver |

O `_manifest.json` lista as contagens exatas injetadas por cenário. Essa é a verdade-base para os testes.

## 6. Invariantes (verificados por `validate` e pelos testes)
1. A mesma seed e as mesmas flags produzem o mesmo sha256 em todos os arquivos.
2. Com `--scenarios none`: 0 nulos, 0 duplicados, 0 FKs órfãs e 0 valores fora do conjunto de valores de face.
3. Todo `municipality_ibge_code` de `pos` existe na referência IBGE.
4. Todas as 27 UFs têm pelo menos 1 PDV com o tamanho padrão.
5. O total de linhas fica dentro de ±1% de `--rows`.
6. Nenhum campo contém CPF, telefone, e-mail ou endereço com formato real.

## 7. Critérios de aceite
- **Dado** `--seed 42` rodado duas vezes, **quando** comparo os `_manifest.json`, **então** os sha256 são idênticos.
- **Dado** os parâmetros padrão, **quando** rodo `generate` numa máquina de 4 vCPUs e 16 GB, **então** termina em menos de 5 min e a pasta ocupa menos de 300 MB em parquet.
- **Dado** `--incremental-day 2026-11-10`, **quando** rodo, **então** só é gerada `recharges/dt=2026-11-10/`, coerente com os PDVs existentes.
- **Dado** que `municipalities_ibge.csv` está ausente, **quando** rodo, **então** o código de saída é `3` e a mensagem indica o caminho esperado.
- **Dado** um upload repetido sem mudanças, **quando** rodo `upload`, **então** 0 arquivos são reenviados.

## 8. Fora de escopo
CEP e endereço (v1.1, geo híbrido), dados de assinante além do hash, dados de concorrentes.
