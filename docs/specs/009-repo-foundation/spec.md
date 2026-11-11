# SPEC-009 — Fundação do repositório

> Roadmap: Fase 0 · ADR: [0014](../../adr/0014-branch-protection-solo-maintainer.md) · Status: aprovado (2026-11-11)

## 1. Objetivo
O repositório se comporta como o de um time profissional: a `main` só muda por PR, as validações automáticas rodam em todo PR e bloqueiam o que não deveria passar, os segredos nunca entram e uma pessoa nova consegue se orientar sem perguntar.

## 2. Layout do monorepo

```
atlas-recarga/
├── cli/                 # atlas-cli (SPEC-001)
├── pipeline/            # Lakeflow SDP (SPEC-002)
├── semantic/            # metric views YAML (SPEC-004)
├── commission/          # regras e jobs de comissão (SPEC-003) — CODEOWNERS
├── apps/
│   ├── agent/           # atlas-agent (SPEC-005)
│   ├── mcp/             # atlas-mcp (SPEC-006)
│   └── web/             # atlas-web (SPEC-007)
├── eval/                # golden set e scorers (SPEC-008)
├── scripts/             # utilitários de build (referência IBGE, geo)
├── data/reference/      # dados públicos versionados (IBGE)
├── spikes/              # notebooks descartáveis (SPEC-000)
├── tests/               # testes de nível de repositório (higiene, consistência SDD)
├── docs/                # discovery, PRD, specs, ADRs, arquitetura
├── .github/             # CI, templates, CODEOWNERS, dependabot
├── pyproject.toml       # raiz do workspace uv + configuração de ruff/mypy/pytest
└── uv.lock
```

- Cada pasta de código nasce com um `README.md` de uma linha dizendo qual spec a governa. Isso evita pastas vazias e orienta o agente de código.
- Pacotes Python entram no workspace `uv` (`[tool.uv.workspace].members`) quando são criados (a partir da P4.1).

## 3. Branches, commits e PRs

| Regra | Valor |
|---|---|
| Branch principal | `main` (protegida, ver §5) |
| Branch de trabalho | `task/<ID>-<slug>`, por exemplo `task/P4.3-pos-generation`. Uma task do roadmap por branch |
| Commits | [Conventional Commits](https://www.conventionalcommits.org/): `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`, com escopo opcional (`feat(cli): …`) |
| Título do PR | `<ID> <tipo>: <descrição>`, por exemplo `P4.3 feat(cli): generate POS with regional weights` |
| Merge | **Squash merge only**; o título do PR vira a mensagem do commit na `main` |
| Branch após o merge | Apagada automaticamente |
| Fechamento da task | O próprio PR marca `[x]` na task do `roadmap.md` com o número do PR |

**Template de PR** (`.github/pull_request_template.md`), com seções obrigatórias:
1. Task do roadmap e spec (links).
2. O que mudou.
3. Por quê (decisão; ADR se houver).
4. Como testar.
5. Checklist dos princípios da [mission](../mission.md): sem métrica fora de `semantic`, IA só leitura, sem segredo, spec atualizada se o comportamento mudou.

## 4. Validações automáticas (`.github/workflows/ci.yml`)

Disparo: `pull_request` para a `main` e `push` na `main`.

| Job | Roda quando | O que faz | Bloqueia se |
|---|---|---|---|
| `changes` | sempre | `dorny/paths-filter` detecta mudanças em `python` (`**/*.py`, `pyproject.toml`, `uv.lock`) e em `docs` (`**/*.md`) | — |
| `lint` | `python` mudou | `ruff check` + `ruff format --check` | qualquer violação |
| `types` | `python` mudou | `mypy` (config estrita no `pyproject.toml`) | qualquer erro |
| `test` | `python` **ou** `docs` mudou | `pytest`, incluindo os testes de consistência SDD (§6) | teste falhando |
| `secrets` | sempre | `gitleaks` no histórico do PR | qualquer achado |
| `docs` | `docs` mudou | `lychee --offline` (só links internos) | link quebrado |
| `ci-ok` | sempre (`if: always()`) | Agrega o resultado dos jobs acima | algum job `failure` ou `cancelled` (`skipped` é aceito) |

- **Só o `ci-ok` é check obrigatório na proteção da branch.** Assim, adicionar jobs novos (web na P12.4, `bundle validate` na P5.1, `agent-eval` na P10.7) não exige mexer na proteção, e jobs pulados por path filter não travam o PR.
- As actions ficam **fixadas por SHA de commit**, com a tag em comentário. O Dependabot atualiza `github-actions` e `uv` semanalmente.
- `pre-commit` local espelha `ruff`, `gitleaks` e higiene de arquivo (fim de linha e espaços), para o erro aparecer antes do push.

## 5. Proteção da `main`
Regra de proteção da branch `main` (decisão no [ADR-0014](../../adr/0014-branch-protection-solo-maintainer.md)):

| Configuração | Valor |
|---|---|
| Exigir PR antes do merge | sim |
| Aprovações obrigatórias | **0** (mantenedor único; ver ADR-0014) |
| Checks obrigatórios | `ci-ok`, com a branch atualizada com a `main` (strict) |
| Exigir resolução das conversas | sim |
| Histórico linear | sim |
| Vale para admins | **sim** |
| Force push / delete | proibidos |

A revisão humana é garantida pelo processo: **só o mantenedor faz o merge**. A partir da Fase 1, o harness nega `gh pr merge` ao agente de código (SPEC-010).

## 6. Testes de higiene e consistência (`tests/`)
Rodam no job `test` e protegem a organização do SDD:

1. Nenhum arquivo versionado casa com `.env`, `.env.*` (exceto `.env.example`), `*.pem`, `*.key` ou `*token*`.
2. Toda pasta `docs/specs/NNN-*/` contém `spec.md` e `tasks.md`.
3. Os IDs de task no `roadmap.md` são únicos, e todo ID do roadmap existe em algum `tasks.md` (e vice-versa).
4. Toda task marcada `[x]` no roadmap referencia um PR (`(#N)`) ou um commit (`(<sha>)`).
5. Todo ADR em `docs/adr/` (exceto o template) tem `Status:` e pelo menos 2 itens em "Opções consideradas".
6. Os arquivos obrigatórios existem: `README.md`, `.gitignore`, `.editorconfig`, `CONTRIBUTING.md`, `.github/pull_request_template.md`, `.github/CODEOWNERS`, cada um a partir da task que o cria.

## 7. Segredos
- `.gitignore` cobre `.env*` (exceto `.env.example`), `.databricks/`, `*.pem`, `*.key`, `data/generated/`, `.venv/`, `node_modules/`.
- Segredos de runtime ficam em Databricks secrets ou nos recursos do bundle; os de CI (a partir da P10.7) ficam em GitHub Actions secrets com escopo mínimo.
- O `gitleaks` roda no CI (bloqueante) e no `pre-commit`.

## 8. CODEOWNERS
Os paths sensíveis têm dono explícito: `/commission/`, `/semantic/`, `/docs/specs/mission.md`, `/docs/adr/`, `/.claude/` e `/.github/`. Com 0 aprovações obrigatórias, o CODEOWNERS **documenta e notifica** quem é responsável; ele vira bloqueante se o projeto ganhar um segundo mantenedor (gatilho do ADR-0014).

## 9. Critérios de aceite
- **Dado** um push direto na `main`, **então** o GitHub rejeita (P0.7).
- **Dado** um PR com o job `ci-ok` vermelho, **então** o botão de merge fica bloqueado.
- **Dado** um PR que adiciona um arquivo com uma chave AWS falsa (formato válido), **então** o `secrets` falha e o `ci-ok` falha.
- **Dado** um PR só de docs, **então** `lint` e `types` ficam `skipped`, `test` e `docs` rodam e o `ci-ok` passa.
- **Dado** um link interno quebrado num `.md`, **então** o `docs` falha.
- **Dado** uma task `[x]` sem referência a PR ou commit, **então** o `test` falha.
- **Dado** uma pessoa nova, **quando** ela lê o README e o CONTRIBUTING, **então** sabe como pegar uma task, nomear a branch, abrir o PR e o que o CI exige.

## 10. Fora de escopo
Checks web (P12.4), `bundle validate` (P5.1), gate de avaliação do agente (P10.7), releases automáticos (P13.4).
