# CLAUDE.md — Atlas Recarga

Plataforma de dados e IA no Databricks Free Edition para a rede de recarga da **Eaí? Telecom** (fictícia, dados 100% sintéticos). Construída por **Spec-Driven Development**.

**Antes de qualquer coisa, a constituição** (não está duplicada aqui; leia lá):
- [mission.md](docs/specs/mission.md): por que existimos e os **9 princípios inegociáveis**. Um conflito entre um princípio e uma spec se resolve a favor do princípio.
- [tech-stack.md](docs/specs/tech-stack.md): stack, convenções e a lista **Proibido**.
- [roadmap.md](docs/specs/roadmap.md): ordem das tasks e o **único lugar com status**.

## Como trabalhar uma task

1. **Ache a próxima task:** a primeira `- [ ]` do `roadmap.md` cujas dependências (`depende de …`) estão todas `[x]`. Os passos ficam em `docs/specs/<spec>/tasks.md` (procure pelo ID).
2. **Executor:** 🤖 você faz · 🤝 você prepara e o mantenedor executa ou aprova no workspace · 👤 **nunca comece**: informe e pare.
3. **Leia a spec inteira** (`docs/specs/<spec>/spec.md`) e os ADRs que ela cita antes de escrever código.
4. **Branch:** `task/<ID>-<slug>` a partir da `main` atualizada. **Uma task = uma branch = um PR.**
5. **Commits:** Conventional Commits (`feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`), com escopo opcional. Termine com a linha `Co-Authored-By` de atribuição.
6. **Antes de cada push**, rode e deixe verde:
   ```bash
   uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
   ```
7. **No próprio PR**, marque a task `[x]` no `roadmap.md` com o número do PR **exatamente** no formato `(#N)`. O teste de higiene falha com outro formato.
8. **Abra o PR** com `.github/pull_request_template.md` preenchido. Título: `<ID> <tipo>(escopo): descrição`.
9. **Espere o `ci-ok` verde e pare.** O merge é **sempre** do mantenedor (ADR-0014). Depois do merge: `git switch main && git pull` e apague a branch local.

## Quando a spec não basta

- **Ambígua ou incompleta:** pare e pergunte. **Não adivinhe.** Se precisa adivinhar, a spec está errada.
- **Errada:** proponha a correção num commit `docs(specs): …` **separado e anterior** ao código, no mesmo PR, e explique no corpo do PR. Mudar uma spec ou um ADR pede confirmação do mantenedor (hook).
- **Decisão nova** de arquitetura, segurança ou custo → um ADR novo com pelo menos 2 alternativas descartadas (template em `docs/adr/0000-template.md`).

## Mapa do repositório

| Pasta | O que é | Spec |
|---|---|---|
| `cli/` | `atlas-cli`, gerador de dados sintéticos | [001](docs/specs/001-synthetic-data-cli/spec.md) |
| `pipeline/` | Lakeflow Spark Declarative Pipelines (bronze → gold) | [002](docs/specs/002-medallion-pipeline/spec.md) |
| `commission/` | Fechamento de comissão: **etapa irreversível** | [003](docs/specs/003-commission-closing/spec.md) |
| `semantic/` | Metric views YAML: **definição única das métricas** | [004](docs/specs/004-metric-views/spec.md) |
| `apps/agent/` | Agente de negócio (Databricks App) | [005](docs/specs/005-business-agent/spec.md) |
| `apps/mcp/` | MCP server FastMCP (Databricks App) | [006](docs/specs/006-mcp-server/spec.md) |
| `apps/web/` | FastAPI + React com mapa (Databricks App) | [007](docs/specs/007-react-geo-dashboard/spec.md) |
| `eval/` | Golden set e scorers do agente | [008](docs/specs/008-agent-evaluation/spec.md) |
| `scripts/` | Utilitários de build (IBGE, geo); nunca rodam em runtime | — |
| `data/reference/` | Dados **públicos** versionados (IBGE) | [001](docs/specs/001-synthetic-data-cli/spec.md) |
| `spikes/` | Notebooks descartáveis | [000](docs/specs/000-platform-spike/spec.md) |
| `tests/` | Testes de repositório (higiene, consistência SDD, hook) | [009](docs/specs/009-repo-foundation/spec.md) |
| `docs/` | Discovery, PRD, specs, ADRs, arquitetura | — |
| `.claude/` | Este harness: permissões, hooks, commands | [010](docs/specs/010-agent-harness/spec.md) |

## Nunca faça

São bloqueados por permissão e por hook (SPEC-010 §3.3), mas não tente contornar:
- **Merge de PR**, push na `main`, `--force`, `--no-verify`, `git push --delete`.
- Mexer na proteção ou nas configurações do repositório (`gh api …/protection`, `gh repo edit`, `gh secret`).
- `databricks bundle deploy -t demo`; executar `atlas_commission_review` de qualquer forma.
- Ler ou exibir segredos: `.env*` (exceto `.env.example`), `.databrickscfg`, `*.pem`, `*.key`, `gh auth token`, `databricks auth token`.

E, do `tech-stack.md` (Proibido):
- `DOUBLE`/`FLOAT` para dinheiro: use `DECIMAL(14,2)` e `ROUND_HALF_EVEN` por linha.
- SQL livre em tools do agente ou do MCP: só listas fechadas e parâmetros vinculados.
- Um consumidor (agente, MCP, apps, dashboards) lendo `gold`, `silver`, `bronze` ou `commission`: só `atlas.semantic`.
- Calcular métrica no frontend, no prompt ou no código de um consumidor.
- Chamar uma API externa no pipeline.
- `UPDATE`/`DELETE` em `commission.locked_lines` ou `commission.batch_events`.
- IA no cálculo ou na aprovação de comissão.
- Dados reais, PII ou telefones com formato real; segredo ou token versionado.
- Adicionar uma tecnologia estrutural sem atualizar o `tech-stack.md` e escrever um ADR.

## Limites do harness (SPEC-010)

- Deny/ask vêm do `.claude/settings.json` e do hook `.claude/hooks/guard.py`. Uma negação traz o motivo: leia e ajuste, **não tente contornar** (ex.: `sh -c`).
- **Falso positivo conhecido:** o hook lê o comando inteiro, então uma mensagem de commit ou o corpo de PR que **cite** um comando proibido (ex.: o texto "gh pr merge") é negado. Escreva a mensagem num arquivo temporário e use `git commit -F <arquivo>` / `gh pr create --body-file <arquivo>`.
- Antes do PR: subagente `spec-reviewer` + `/code-review` (CONTRIBUTING, "Como reviso o agente").

## Comandos úteis

```bash
uv sync                                  # ambiente Python 3.12 + ferramentas de dev
uv run pytest                            # testes (inclui higiene e consistência do SDD)
uv run ruff check . && uv run ruff format .
uv run mypy
uv run pre-commit run --all-files        # o mesmo que o pre-commit local
gh pr create / gh pr checks <N>          # abrir PR e acompanhar o CI (nunca gh pr merge)
databricks bundle validate -t dev        # a partir da P5.1
```

## Convenções rápidas

- Código, tabelas e colunas em inglês e `snake_case`; documentação em PT-BR.
- Timestamps em UTC (`*_ts_utc`); datas e "mês" de negócio em `America/Sao_Paulo`.
- Município = `municipality_ibge_code STRING` com 7 dígitos.
- Configuração por variáveis `ATLAS_*`; segredos só em Databricks secrets ou no bundle.
