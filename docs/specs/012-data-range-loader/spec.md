# SPEC-012 — Carga de dados por intervalo de datas

> Roadmap: Fase 14 · PRD: F1, F2 · ADRs: [0001](../../adr/0001-databricks-free-edition.md), [0003](../../adr/0003-medallion-unity-catalog.md) · Status: rascunho

## 1. Objetivo
Quem monta a demo passa um intervalo de datas e um único comando gera os dados sintéticos desse intervalo, envia para a landing (`/Volumes/atlas/raw/landing/`) e dispara o pipeline. É o primeiro passo do README. Não há geração nova: o script orquestra o `atlas-cli` (SPEC-001) e o job `atlas_daily` (SPEC-002).

## 2. Interface

```bash
uv run python scripts/load_data.py --from 2026-08-01 --to 2026-10-31 --profile <perfil> [--target dev]
```

| Flag | Padrão | Regra |
|---|---|---|
| `--from`, `--to` | — (obrigatórias) | `YYYY-MM-DD`, inclusivas; `from` ≤ `to`; no máximo 366 dias |
| `--profile` | — (obrigatória) | Perfil da CLI do Databricks. O script não escolhe um sozinho |
| `--target` | `dev` | `dev` ou `demo`; define o Volume (`dev`: `/Volumes/atlas_dev/raw/landing/`; `demo`: `/Volumes/atlas/raw/landing/`, igual ao catálogo do `databricks.yml`) e o job (`bundle run -t`) |
| `--seed` | `42` | A mesma seed das cargas anteriores |
| `--rows` | `2_000_000` | Total da janela base (SPEC-001); os dias do intervalo são a fração proporcional |
| `--base-end-month` | `2026-11` | Janela base: o último mês gerado é este − 1 |
| `--base-months` | `12` | Meses da janela base |
| `--out` | `./data/generated-range` | Diretório local (não versionado) |
| `--no-run` | desligado | Gera, valida e envia, mas não dispara o `atlas_daily` |
| `--dry-run` | desligado | Só imprime o plano (janela base, dias de fora, comandos) |

## 3. Comportamento
1. **Plano.** Valida as flags e separa os dias do intervalo em *dentro da janela base* e *fora* dela.
2. **Janela base fixa.** Roda `atlas-cli generate` com `--end-month`/`--months` da janela base, `--seed`, `--rows` e os demais padrões. A janela é fixa **porque `pos` e `distributors` dependem dela** (SPEC-001 §4: datas de abertura e fechamento são relativas ao início da janela). Mudar a janela muda o `pos.parquet` e deixa as recargas já carregadas com PDV órfão. Os padrões de `--base-end-month` e `--base-months` reproduzem o histórico já carregado (2025-11 a 2026-10).
3. **Dias fora da janela.** Para cada dia do intervalo fora da janela base, roda `atlas-cli generate --incremental-day <dia>` (SPEC-001 §2).
4. **Poda.** Remove as partições `recharges/dt=` fora de `[from, to]` e atualiza o manifest (SPEC-001 §2, "Poda"). O que sobra são só os dias pedidos.
5. **Validação.** Roda `atlas-cli validate`; qualquer `FALHA` interrompe antes do upload.
6. **Upload.** Roda `atlas-cli upload --dest <Volume do target>` (idempotente; nunca apaga). Antes, compara o sha256 local do `pos/pos.parquet` e do `distributors/distributors.parquet` com o do manifest remoto: se diferirem, **aborta** (a janela ou a seed não são as da carga anterior), exceto no primeiro envio (sem manifest remoto).
7. **Processamento.** Roda `databricks bundle run atlas_daily -t <target> --profile <perfil>` e espera o término. Imprime o estado final do run. `--no-run` pula este passo.

O script é idempotente: repetir com o mesmo intervalo, seed e flags reenvia 0 arquivos e roda o pipeline de novo sem mudar o gold.

## 4. Limites conhecidos (documentados no README)
- Cenários que dependem de vários dias (`regional_drop`, `duplicates`, `late_arrival`) e os que sorteiam um dia da janela (`fractioning`, `negative_amount`) só aparecem se o dia deles cair dentro do intervalo, e nunca em dias fora da janela base (SPEC-001 §2, `--incremental-day`).
- O manifest no Volume passa a descrever só o último envio; os arquivos de cargas anteriores continuam no Volume (o `upload` nunca apaga).
- Dois intervalos que se sobrepõem substituem os dias comuns pelos mesmos bytes (determinismo).
- O disparo do `atlas_daily` exige o bundle já implantado no `target` (`databricks bundle deploy`).

## 5. Falhas
| Falha | Efeito | Saída |
|---|---|---|
| Flag inválida (`from` > `to`, formato, > 366 dias) | Nada é gerado | `2` |
| `validate` com `FALHA` | Interrompe antes do upload | `1` |
| `pos` ou `distributors` diferem do manifest remoto | Interrompe antes do upload; mensagem com a janela esperada | `2` |
| Upload falha | O `upload` já deixa o manifest por último; repetir é seguro | `4` |
| `atlas_daily` termina sem sucesso | Dados já estão na landing; imprime o estado e o link do run | `5` |

## 6. Critérios de aceite
- **Dado** `--from 2026-08-01 --to 2026-08-31 --dry-run`, **então** o plano lista a janela base, 0 dias fora dela e a poda de tudo que não é agosto, sem gerar nem enviar nada.
- **Dado** um intervalo dentro da janela base, **quando** rodo com `--no-run`, **então** `recharges/` local tem só as partições do intervalo, `validate` passa e o manifest bate com os arquivos.
- **Dado** um intervalo que inclui dias depois da janela base (ex.: `2026-11-01` a `2026-11-10`), **então** esses dias vêm de `--incremental-day` e `validate` passa.
- **Dado** a mesma execução repetida, **então** o `upload` reenvia 0 arquivos.
- **Dado** `--base-end-month` diferente do usado na carga anterior, **então** o script aborta antes do upload com a mensagem de PDV divergente.
- **Dado** o `atlas_daily` com sucesso, **então** `scripts/check_bronze_counts.py` e `check_silver_recharges.py` conferem as contagens do intervalo (feito pelo mantenedor no `dev`).

## 7. Fora de escopo
Cargas em tempo real; apagar dados da landing; gerar mais de uma janela base; intervalos de vários anos; `--from`/`--to` direto no `atlas-cli generate` (decisão: o contrato do CLI não muda além da poda).
