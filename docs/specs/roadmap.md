# Roadmap — Atlas Recarga

> Constituição do projeto, parte 3 de 3 · [mission](mission.md) · [tech-stack](tech-stack.md) · [roadmap](roadmap.md)

## Como usar

- **Este arquivo é a única fonte de status.** Os `tasks.md` de cada spec têm o detalhe (passos), mas **não** têm checkbox.
- **1 task = 1 branch = 1 PR.** Branch: `task/P4.3-pos-generation`. O título do PR começa com o ID da task.
- **Próxima task** = a primeira `[ ]` cujas dependências estão todas `[x]`. Peça: *"aplique a próxima task aberta do roadmap"* (ou `/next-task` depois da P1.5).
- Ao fazer o merge, marque `[x]` e acrescente o PR: `- [x] **P4.3** … (#12)`.
- Os IDs de spec (000–011) são estáveis e **não** indicam ordem de execução; a ordem é a das fases abaixo.
- Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você. Tasks 👤 nunca são iniciadas pelo agente.

## Visão geral

| Fase | Tema | Spec | Tasks |
|---|---|---|---|
| 0 | Fundação do repositório | [009-repo-foundation](009-repo-foundation/spec.md) | 7 |
| 1 | Harness do agente de código | [010-agent-harness](010-agent-harness/spec.md) | 6 |
| 2 | Arquitetura explicada | [011-architecture](011-architecture/spec.md) | 2 |
| 3 | Spike S0: validações de plataforma | [000-platform-spike](000-platform-spike/spec.md) | 8 |
| 4 | Dados sintéticos | [001-synthetic-data-cli](001-synthetic-data-cli/spec.md) | 9 |
| 5 | Bundle e catálogo como código | [002-medallion-pipeline](002-medallion-pipeline/spec.md) | 2 |
| 6 | Pipeline medalhão | [002-medallion-pipeline](002-medallion-pipeline/spec.md) | 7 |
| 7 | Camada semântica (recargas) | [004-metric-views](004-metric-views/spec.md) | 5 |
| 8 | Fechamento de comissão | [003-commission-closing](003-commission-closing/spec.md) | 11 |
| 9 | Avaliação do agente: golden set antes do agente | [008-agent-evaluation](008-agent-evaluation/spec.md) | 3 |
| 10 | Agente de negócio | [005-business-agent](005-business-agent/spec.md) | 8 |
| 11 | MCP server | [006-mcp-server](006-mcp-server/spec.md) | 5 |
| 12 | Dashboard React com mapa | [007-react-geo-dashboard](007-react-geo-dashboard/spec.md) | 8 |
| 13 | Demo e release v1.0 | — | 4 |

## Fase 0 — Fundação do repositório → [009-repo-foundation](009-repo-foundation/spec.md)

_Repositório com cara de time: main protegida, PR obrigatório, CI que bloqueia, segredos fora._

- [x] **P0.1** 🤖 Escrever a SPEC-009 (fundação do repo) — _pronto quando:_ SPEC-009 e ADR-0014 aprovados (#1)
- [x] **P0.2** 🤖 `.gitignore` completo, `.editorconfig`, layout de pastas (SPEC-009 §2) e README esqueleto — _pronto quando:_ PR mergeado; as pastas da SPEC-009 §2 existem, cada uma com um README de uma linha (#2) · depende de P0.1
- [x] **P0.3** 👤 Criar o repositório no GitHub e fazer o push inicial — _pronto quando:_ `origin/main` existe com o commit de bootstrap (8616bd6; feito antes da P0.2 por pedido do mantenedor)
- [x] **P0.4** 🤖 Template de PR, template de issue e CONTRIBUTING (Conventional Commits, 1 task = 1 PR) — _pronto quando:_ PR mergeado com os templates; o próximo PR já usa o template (#3) · depende de P0.3
- [x] **P0.5** 🤖 CI base: ruff, mypy, pytest, gitleaks, link check dos docs — _pronto quando:_ Workflow `ci.yml` verde no PR e vermelho num PR de teste com segredo falso (#4) · depende de P0.4
- [x] **P0.6** 🤖 CODEOWNERS dos paths sensíveis (SPEC-009 §8) — _pronto quando:_ CODEOWNERS válido (sem erros na aba do GitHub); informativo com 0 aprovações (ADR-0014) (#6) · depende de P0.4
- [x] **P0.7** 👤 Branch protection da `main` conforme SPEC-009 §5 (PR + `ci-ok`, 0 aprovações, vale para admins) — _pronto quando:_ Um push direto na `main` é rejeitado (#7) — GH006 verificado em 2026-11-11; aplicado pelo agente por autorização do mantenedor (ADR-0014) · depende de P0.5, P0.6

## Fase 1 — Harness do agente de código → [010-agent-harness](010-agent-harness/spec.md)

_O Claude Code trabalha neste repo com contexto e limites aplicados pela ferramenta (ADR-0012)._

- [x] **P1.1** 🤖 Escrever a SPEC-010 (harness): o que o agente faz, o que é bloqueado, como é revisado — _pronto quando:_ spec.md aprovado; ADR-0012 vira `aceito` (#8) · depende de P0.7
- [x] **P1.2** 🤖 `CLAUDE.md`: missão resumida, princípios, mapa do repo, comandos, como pegar a próxima task — _pronto quando:_ O agente, numa sessão nova, responde corretamente "qual a próxima task?" (#9) · depende de P1.1
- [x] **P1.3** 🤖 `.claude/settings.json`: permissões allow/deny — _pronto quando:_ allow/ask/deny conforme SPEC-010 §3; o hook é registrado no mesmo arquivo (#10) · depende de P1.1
- [x] **P1.4** 🤖 Hook `PreToolUse` `guard.py` com as regras deny/ask da SPEC-010 §3–§4 — _pronto quando:_ `tests/test_guard_hook.py` cobre cada regra (positivo e negativo) no CI; teste manual de `gh pr merge` negado (#10) · depende de P1.3
- [x] **P1.5** 🤖 Commands `/next-task` (lê o roadmap e propõe a próxima task aberta) e `/close-task` (marca [x] e linka o PR) — _pronto quando:_ `/next-task` devolve a primeira task aberta cujas dependências estão concluídas (#10) · depende de P1.2
- [x] **P1.6** 🤖 Fluxo de revisão: subagente revisor + checklist de princípios no PR + revisão humana obrigatória — _pronto quando:_ Seção "Como reviso o agente" no CONTRIBUTING e um PR de exemplo revisado (#10) · depende de P1.5

## Fase 2 — Arquitetura explicada → [011-architecture](011-architecture/spec.md)

_Um desenho e um texto curto: componentes, onde estão os dados, onde entram a IA e o humano, o que acontece na falha._

- [x] **P2.1** 🤖 Escrever `docs/architecture.md` com o diagrama Mermaid (C4 nível 2) — _pronto quando:_ Revisado por PR; todos os componentes do PRD aparecem (#11) · depende de P1.6
- [x] **P2.2** 🤖 Tabela de modos de falha por componente (o que quebra, o efeito, a detecção, a recuperação) — _pronto quando:_ Cada linha aponta para a spec que define o comportamento (#12) · depende de P2.1

## Fase 3 — Spike S0: validações de plataforma → [000-platform-spike](000-platform-spike/spec.md)

_Confirmar na Free Edition os recursos em Beta antes de depender deles._

- [x] **P3.1** 🤝 S0.1 Unity Gateway + model service Claude — _pronto quando:_ Resultado em `docs/spikes/S0-results.md`; ADR-0007 atualizado (#13) — passou com ressalva: sem Claude em `system.ai`; ver ADR-0007 · depende de P2.2
- [x] **P3.2** 🤝 S0.2 Agent service (Beta) — _pronto quando:_ Idem; ADR-0007 (#15) — passou com ressalva: App `agent-*` listado em Agents; sem uso nativo por agente; ver ADR-0007 · depende de P3.1
- [x] **P3.3** 🤝 S0.3 Production monitoring MLflow 3 — _pronto quando:_ Idem; ADR-0013 (#16) — passou: scorer de código agendado anexou feedback aos traces; plano B validado · depende de P2.2
- [x] **P3.4** 🤝 S0.4 Metric views + Genie — _pronto quando:_ Idem; ADR-0005 (#17) — passou: `MEASURE()` e Genie sobre a metric view funcionam; plano B não acionado · depende de P2.2
- [x] **P3.5** 🤝 S0.5 OAuth de cliente externo num App MCP — _pronto quando:_ Idem; ADR-0008 (#18) — passou com ressalva: token de usuário no cabeçalho, OAuth interativo nativo não testado; Claude Code chamou o App FastMCP e a query rodou como o usuário (OBO) · depende de P2.2
- [x] **P3.6** 👤 S0.6 Múltiplos usuários — _pronto quando:_ Idem; ADR-0010 (#19) — passou: segundo usuário entrou no grupo `users` e foi adicionado a `atlas_readers`; `ALLOW_SAME_APPROVER_DEMO` só como contingência · depende de P2.2
- [x] **P3.7** 🤝 S0.7 Cotas práticas (rodar depois de P4.6) — _pronto quando:_ Idem; ADR-0001 (#27) — passou: 2M de recargas em bronze + silver em 113 s, sem erro de cota; `--rows` mantido · depende de P4.6
- [x] **P3.8** 🤖 Ajustar as specs afetadas pelos planos B — _pronto quando:_ PR único com os ajustes; a Fase 3 é fechada (#20) · depende de P3.1, P3.2, P3.3, P3.4, P3.5, P3.6

## Fase 4 — Dados sintéticos → [001-synthetic-data-cli](001-synthetic-data-cli/spec.md)

_`atlas-cli` gera o dataset determinístico com cenários e o envia ao Volume._

- [x] **P4.1** 🤖 Esqueleto do pacote `cli/` (uv, Typer, `atlas-cli --help`, testes rodando no CI) — _pronto quando:_ `atlas-cli --help` lista os comandos; CI verde (#21) · depende de P3.8
- [x] **P4.2** 🤖 Snapshot da referência IBGE (`data/reference/municipalities_ibge.csv`) com população e DDD aproximado por região imediata — _pronto quando:_ 5.570 linhas; teste de unicidade e de 7 dígitos (#22) · depende de P4.1
- [x] **P4.3** 🤖 `generate`: distributors + pos com pesos regionais — _pronto quando:_ Invariantes 3 e 4 da SPEC-001 passam (#23) · depende de P4.2
- [x] **P4.4** 🤖 `generate`: recharges com valores de face, curva intradiária e status — _pronto quando:_ Invariantes 2 e 5 passam com `--scenarios none` (#24) · depende de P4.3
- [x] **P4.5** 🤖 Sazonalidade (salário, dezembro, fevereiro, domingo) — _pronto quando:_ Teste estatístico simples de que os dias 5 a 10 têm volume > média (#25) · depende de P4.4
- [x] **P4.6** 🤖 Cenários da SPEC-001 §5 + `_manifest.json` com contagens e sha256 — _pronto quando:_ Os testes leem o manifest e conferem cada contagem (#26) · depende de P4.5
- [x] **P4.7** 🤖 `validate` + teste de determinismo (seed igual = sha igual) — _pronto quando:_ Critério 1 da SPEC-001 §7 (#28) · depende de P4.6
- [x] **P4.8** 🤖 `--incremental-day` — _pronto quando:_ Critério 3 da SPEC-001 §7 (#29) · depende de P4.7
- [x] **P4.9** 🤝 `upload` idempotente para `/Volumes/atlas/raw/landing/` — _pronto quando:_ Critério 5 da SPEC-001 §7 (o agente implementa; você roda contra o workspace) (#32) · depende de P4.8, P5.2

## Fase 5 — Bundle e catálogo como código → [002-medallion-pipeline](002-medallion-pipeline/spec.md)

_`databricks.yml` cria o catálogo, os schemas, o Volume e os grupos, de forma reproduzível._

- [x] **P5.1** 🤖 `databricks.yml` com targets `dev`/`demo` e `bundle validate` no CI — _pronto quando:_ `databricks bundle validate -t dev` passa no CI (#30) · depende de P3.8
- [x] **P5.2** 🤝 Catálogo `atlas`, schemas, Volume `raw.landing` e grupos `atlas_readers`, `atlas_commission_*` — _pronto quando:_ Deploy em `dev` feito por você; os objetos aparecem no Catalog Explorer; o CI valida também `-t demo` (#31) — deploy em `dev` feito pelo mantenedor em 2026-11-12; objetos conferidos no Catalog Explorer · depende de P5.1

## Fase 6 — Pipeline medalhão → [002-medallion-pipeline](002-medallion-pipeline/spec.md)

_Bronze → silver → gold com expectations e linhagem; gold D-1 até 08:00._

- [x] **P6.1** 🤖 Bronze: Auto Loader de `recharges`, MVs de `pos`, `distributors`, `municipalities` — _pronto quando:_ As contagens no bronze são iguais às do manifest (#33) — conferência no workspace pelo mantenedor via `scripts/check_bronze_counts.py` · depende de P4.9, P5.2
- [x] **P6.2** 🤖 Silver `recharges`: dedup, `recharge_date` em America/Sao_Paulo, expectations drop/warn — _pronto quando:_ Critério 1 da SPEC-002 §5 (#34) — conferência no workspace pelo mantenedor via `scripts/check_silver_recharges.py` (órfãos ainda dentro até a P6.3) · depende de P6.1
- [x] **P6.3** 🤖 Silver `recharges_quarantine` (PDV órfão) — _pronto quando:_ Critério 2 da SPEC-002 §5 (#35) — conferência no workspace pelo mantenedor via `scripts/check_silver_recharges.py` · depende de P6.2
- [x] **P6.4** 🤖 Silver das dimensões com `expect_or_fail` — _pronto quando:_ Critério 4 da SPEC-002 §5 (teste com um PDV de município inválido) (#36) — conferido no `dev` pelo mantenedor via `scripts/check_silver_pos_integrity.py` · depende de P6.1
- [x] **P6.5** 🤖 Gold: `dim_*` + `fct_recharges` com COMMENT em tabelas e colunas — _pronto quando:_ Linhagem visível; todas as colunas descritas (#37) — conferido no `dev` pelo mantenedor: contagens batem com o silver, COMMENT em tabelas e colunas, `amount_brl` DECIMAL(14,2), 0 fatos sem PDV, linhagem visível · depende de P6.3, P6.4
- [x] **P6.6** 🤖 Gold `agg_pos_month` — _pronto quando:_ A soma bate com `fct_recharges` por mês (#38) — conferido no `dev` pelo mantenedor via `scripts/check_gold_agg_pos_month.py`: 12 meses (2025-11 a 2026-10) com valor aprovado, aprovadas e estornadas iguais à `fct_recharges`; 0 duplicatas · depende de P6.5
- [x] **P6.7** 🤝 Job `atlas_daily` (06:00) + task de frescor em `observability.pipeline_freshness` — _pronto quando:_ Execução agendada termina antes das 08:00 (#39) — conferido no `dev` pelo mantenedor via `scripts/check_atlas_daily.py`: run manual SUCCESS em 2,6 min (meta < 30); o disparo das 06:00 não foi observado (aceito pelo mantenedor); `stale` esperado, pois os dados vão até 2026-10-31 · depende de P6.6

## Fase 7 — Camada semântica (recargas) → [004-metric-views](004-metric-views/spec.md)

_`mv_recharges` como a única porta de leitura, com AI/BI e Genie em cima._

- [x] **P7.1** 🤖 `semantic/mv_recharges.yaml` + deploy — _pronto quando:_ `SELECT MEASURE(gross_revenue)` funciona (#41) — conferido no `dev` pelo mantenedor via `scripts/check_mv_recharges.py`: as 7 medidas respondem (`gross_revenue` 48.880.720,00) e a soma das 5 regiões bate com o total; o job `atlas_semantic_deploy` aplicou o YAML pelo `spark.sql` · depende de P6.5
- [x] **P7.2** 🤖 Teste de consistência metric view × SQL direto no gold — _pronto quando:_ Critério 1 da SPEC-004 §8 (#42) — conferido no `dev` pelo mantenedor via `scripts/check_mv_consistency.py`: 12 meses (2025-11 a 2026-10) e o total (48.880.720,00) iguais ao centavo entre `MEASURE(gross_revenue)` e o gold · depende de P7.1
- [x] **P7.3** 🤝 Grants: `atlas_readers` só em `semantic` + teste de PERMISSION_DENIED — _pronto quando:_ Critério 4 da SPEC-004 §8 (#43) — conferido no `dev` via `scripts/check_readers_permissions.py` com um service principal de teste: `SELECT` em `mv_recharges` permitido; `PERMISSION_DENIED` em gold, silver, bronze e commission. Grants por principal (`--reader`), pois grupo de workspace não vale no UC (ADR-0016) · depende de P7.1
- [x] **P7.4** 🤝 AI/BI Dashboard "Atlas — Visão Comercial" (páginas Brasil, UF, Rede) — _pronto quando:_ Publicado; filtros de mês, região e UF (#45) — conferido no `dev` pelo mantenedor: ranking de UFs e filtros funcionam; o mapa nativo não reconhece UFs do Brasil, então o coroplético fica na SPEC-007 · depende de P7.1
- [x] **P7.5** 🤝 Genie Space "Atlas Recarga" com instruções e 10 exemplos — _pronto quando:_ Critério 5 da SPEC-004 §8 (#48) — Space no bundle (só `mv_recharges`; `mv_commission` entra na P8.11); conferido no `dev` pelo mantenedor via `scripts/check_genie_space.py`: para "qual a receita por DDD em outubro?" o Genie gerou SQL com `ddd` e `MEASURE(gross_revenue)` sobre `atlas_dev.semantic.mv_recharges`, sem tocar gold, silver, bronze ou commission · depende de P7.1

## Fase 8 — Fechamento de comissão → [003-commission-closing](003-commission-closing/spec.md)

_Cálculo determinístico, reconciliação, 2 aprovações humanas e lote imutável._

- [x] **P8.1** 🤖 `commission/rules.py` (faixas, taxas, arredondamento) + testes de borda — _pronto quando:_ Critério 2 da SPEC-003 §8; cobertura ≥ 95% no módulo (#49) — cobertura 100% medida com `pytest-cov` · depende de P6.6
- [x] **P8.2** 🤖 Tabelas `commission.*` com `delta.appendOnly` em `batch_events` e `locked_lines` — _pronto quando:_ Teste: um UPDATE é rejeitado (#50) — DDL e job `atlas_commission_deploy` prontos; a rejeição de UPDATE/DELETE **ainda a conferir** no `dev` pelo mantenedor, via `scripts/check_commission_append_only.py` · depende de P8.1
- [ ] **P8.3** 🤖 Cálculo do rascunho (`draft`) em PySpark — _pronto quando:_ Lote `COM-YYYY-MM-v1` criado para o último mês fechado · depende de P8.2
- [ ] **P8.4** 🤖 Reconciliação independente em SQL + totais de controle — _pronto quando:_ Critério 1 da SPEC-003 §8 (R$ 0,00) · depende de P8.3
- [ ] **P8.5** 🤖 Flags de revisão (`spike_3x`, `fractioning_suspect`, `tier_jump`, `closed_pos`) — _pronto quando:_ Critério 3 da SPEC-003 §8 · depende de P8.4
- [ ] **P8.6** 🤖 Job `atlas_commission_review`: máquina de estados, segregação de funções, justificativa — _pronto quando:_ Critérios 4 e 6 da SPEC-003 §8 · depende de P8.5
- [ ] **P8.7** 🤖 Lock + remessa simulada + sha256 — _pronto quando:_ Critério 7 da SPEC-003 §8 · depende de P8.6
- [ ] **P8.8** 🤖 Dashboard/notebook `commission_review` — _pronto quando:_ A analista vê os totais, o top 20, os flags e a comparação com o mês anterior · depende de P8.5
- [ ] **P8.9** 👤 Primeiro fechamento ponta a ponta (você aprova nas 2 etapas) — _pronto quando:_ Lote `locked` com 2 eventos de aprovação · depende de P8.7, P8.8
- [ ] **P8.10** 🤖 Lote de ajuste `ADJ` — _pronto quando:_ SPEC-003 §7 coberto por teste · depende de P8.7
- [ ] **P8.11** 🤖 `semantic/mv_commission.yaml` (só `locked`) + página Comissão no AI/BI — _pronto quando:_ Critério 2 da SPEC-004 §8 · depende de P8.9

## Fase 9 — Avaliação do agente: golden set antes do agente → [008-agent-evaluation](008-agent-evaluation/spec.md)

_Escrever o teste antes do agente: golden set e scorers prontos._

- [ ] **P9.1** 🤖 `eval/golden_set.yaml` com ~30 casos (20 métricas, 5 comparativos, 5 recusas) — _pronto quando:_ Toda `reference_sql` executa e retorna 1 valor · depende de P7.5, P8.11
- [ ] **P9.2** 🤖 Sync do golden set para `atlas.eval.agent_golden_set` (dataset MLflow) — _pronto quando:_ O dataset aparece no UC com versão · depende de P9.1
- [ ] **P9.3** 🤖 Scorers de código (`numeric_match`, `cites_metric_view`, `read_only_tools`, `no_tool_on_refusal`) + testes unitários com traces fake — _pronto quando:_ Cobertura ≥ 90% nos scorers · depende de P9.1

## Fase 10 — Agente de negócio → [005-business-agent](005-business-agent/spec.md)

_Agente somente leitura, via Unity Gateway, com tracing, aprovado no golden set._

- [ ] **P10.1** 🤖 UC functions `fn_list_metrics`, `fn_metric_by_region`, `fn_compare_months` — _pronto quando:_ Retornos batem com as metric views; `measure` inválido gera erro · depende de P7.1
- [ ] **P10.2** 🤖 Esqueleto do App `atlas-agent` a partir do template oficial, LLM via Unity Gateway — _pronto quando:_ Responde "olá"; o trace aparece no experiment; uso em `system.ai_gateway.usage` · depende de P3.8
- [ ] **P10.3** 🤖 Tools: `ask_genie` + UC functions (lista fechada) — _pronto quando:_ Uma pergunta simples do golden set acerta · depende de P10.1, P10.2
- [ ] **P10.4** 🤖 System prompt: citação `Fonte:`, recusa, último mês fechado, PT-BR — _pronto quando:_ Os casos de recusa do golden set passam · depende de P10.3
- [ ] **P10.5** 🤝 Rate limit, spend cap e guardrails no gateway + trace tables em `atlas.observability` — _pronto quando:_ 429 testado; política de PII ativa · depende de P10.2
- [ ] **P10.6** 🤖 Avaliação offline completa: acurácia ≥ 90% — _pronto quando:_ Run do MLflow linkado no PR · depende de P9.3, P10.4
- [ ] **P10.7** 🤖 Gate de CI `agent-eval.yml` com path filter + comentário no PR — _pronto quando:_ Critérios 2 e 3 da SPEC-008 §7 · depende de P10.6
- [ ] **P10.8** 🤝 Production monitoring (ou o plano B) + página "Qualidade do agente" + alerta — _pronto quando:_ Critérios 5 e 6 da SPEC-008 §7 · depende de P10.6

## Fase 11 — MCP server → [006-mcp-server](006-mcp-server/spec.md)

_FastMCP em App, somente leitura, conectado ao Claude._

- [ ] **P11.1** 🤖 Esqueleto FastMCP no App `atlas-mcp` com `health` — _pronto quando:_ Critério 1 da SPEC-006 §7 · depende de P3.8
- [ ] **P11.2** 🤖 `list_metrics` + `query_metric` com validação por lista fechada e parâmetros vinculados — _pronto quando:_ Critérios 3 e 4 (injeção) da SPEC-006 §7 · depende de P11.1, P7.1
- [ ] **P11.3** 🤖 `top_regions` + `compare_months` + erros padronizados — _pronto quando:_ Contrato de erros da SPEC-006 §4 coberto · depende de P11.2
- [ ] **P11.4** 🤖 Traces MLflow, rate limit por usuário, logs estruturados + teste de paridade com o golden set — _pronto quando:_ Critérios 6 a 10 da SPEC-006 §7 · depende de P11.3, P9.1, P3.5
- [ ] **P11.5** 👤 Conectar ao Claude Code/Desktop e documentar no README — _pronto quando:_ Você pergunta no Claude e recebe a resposta com `source` · depende de P11.4

## Fase 12 — Dashboard React com mapa → [007-react-geo-dashboard](007-react-geo-dashboard/spec.md)

_KPIs + mapa coroplético UF → município, p95 < 3s._

- [ ] **P12.1** 🤖 `scripts/fetch_geo.py`: malhas do IBGE → TopoJSON simplificado em `apps/web/public/geo/` — _pronto quando:_ Tamanhos dentro do limite; teste de match de 100% com `dim_municipality` · depende de P4.2
- [ ] **P12.2** 🤖 Backend FastAPI: `/api/months`, `/api/kpis`, `/api/health` + cache — _pronto quando:_ Os KPIs batem com o AI/BI · depende de P7.1
- [ ] **P12.3** 🤖 `/api/map/region`, `/api/map/uf` e `/api/map/municipality` (com `mom_change`) + validação de `measure` — _pronto quando:_ 400 para medida inválida; a soma das regiões e a das UFs são iguais ao KPI · depende de P12.2
- [ ] **P12.4** 🤖 Frontend: esqueleto Vite + React + TS, layout, KPI cards — _pronto quando:_ Build no CI (`tsc`, `eslint`, `vitest`) · depende de P0.5
- [ ] **P12.5** 🤖 Mapa por região (UFs pintadas pela região) com `d3-geo`, escala de quantis, legenda, tooltip — _pronto quando:_ Visual conferido por você · depende de P12.1, P12.3, P12.4
- [ ] **P12.6** 🤖 Drill-down: Brasil → região → UF → municípios, com zoom; breadcrumb e Esc — _pronto quando:_ Critério 1 da SPEC-007 §6 (queda no PA visível) · depende de P12.5
- [ ] **P12.7** 🤖 Escala divergente `mom_change`, estados de loading e erro, acessibilidade — _pronto quando:_ Critério 6 da SPEC-007 §6 + navegação por teclado · depende de P12.6
- [ ] **P12.8** 🤝 Deploy do App `atlas-web` + medição de p95 — _pronto quando:_ p95 < 3s registrado · depende de P12.7

## Fase 13 — Demo e release v1.0

_Qualquer pessoa roda a demo a partir do README; as métricas do PRD são medidas e publicadas._

- [ ] **P13.1** 🤖 `make apps-start` + runbook de demo (auto-stop de 24h) — _pronto quando:_ Os 3 Apps sobem com um comando e os healthchecks passam · depende de P10.8, P11.5, P12.8
- [ ] **P13.2** 🤖 Teste de consistência entre os 5 consumidores — _pronto quando:_ Mesmo `gross_revenue` no AI/BI, Genie, agente, MCP e React · depende de P13.1
- [ ] **P13.3** 🤖 README final (repo-readme-generator) com as métricas medidas do PRD §4 — _pronto quando:_ Uma pessoa nova roda a demo sem perguntar nada · depende de P13.2
- [ ] **P13.4** 👤 Tag `v1.0.0` + release notes — _pronto quando:_ Release publicado · depende de P13.3

## Depois do MVP

| Versão | Item |
|---|---|
| v1.1 | Geo híbrido: CEP → código IBGE em tabela de referência cacheada (ADR-0004) |
| v1.1 | Medidas com janela nas metric views; filtros de distribuidor e tipo de PDV no mapa |
| v1.1 | Painel "Leitura do mapa" / "Onde crescer" no dashboard React, sem IA: texto determinístico calculado no backend (maior UF do mês, maior queda contra o mês anterior) |
| v1.1 | Filtros de recorte e escopo no dashboard React (hoje só mês e medida) |
| v2 | Forecast e metas regionais com backtesting |
| v2 | Personas do agente (Helena, Analista, Regional) com golden set por persona |
| v2 | DQ por camada + Lakehouse Monitoring; expectations de volume bloqueantes |
| v2 | UI de aprovação de comissão (novo ADR sobre o slot de App) |
| v2 | Dashboard React com abas (Hierarquia, Indicadores, Território) em vez de tela única |
| v2 | "Pergunte ao Genie" embutido no `atlas-web`: pede ADR novo sobre a alocação de Apps (ADR-0009) |
| v3 | Row-level security por região; alertas proativos de queda regional |
