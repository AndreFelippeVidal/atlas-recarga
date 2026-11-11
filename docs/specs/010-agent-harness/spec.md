# SPEC-010 — Harness do agente de código (Claude Code)

> Roadmap: Fase 1 · ADRs: [0012](../../adr/0012-claude-code-harness.md), [0014](../../adr/0014-branch-protection-solo-maintainer.md) · Status: aprovado (#8); ajustado na implementação (P1.3–P1.6)

## 1. Objetivo
Deixar explícito, e **aplicado pela ferramenta**, o que o agente de código pode fazer sozinho, o que precisa da sua confirmação, o que é proibido e como o trabalho dele é revisado antes de entrar na `main`. Um limite que depende de o modelo "lembrar" não é um limite (princípio 9 da [mission](../mission.md)).

## 2. Três camadas de defesa

| Camada | Mecanismo | O que garante | Limitação conhecida |
|---|---|---|---|
| **1. Permissões** | `.claude/settings.json` (`allow`, `ask`, `deny`), versionado | Prompts mínimos para o fluxo comum; `deny` vale em todos os modos de permissão | Uma regra Bash casa com o comando **como foi escrito**: `sh -c '…'`, um caminho absoluto ou um alias escapam |
| **2. Hook `PreToolUse`** | `.claude/hooks/guard.py` (stdlib, sem dependências), testado em pytest | Inspeciona o comando **inteiro** e o caminho do arquivo com regex, cobrindo o que a camada 1 deixa passar; decide `deny` ou `ask` com mensagem clara | Não impede um processo que o próprio agente lance fora das tools |
| **3. Servidor (GitHub)** | Proteção da `main` (SPEC-009 §5) | Nada chega à `main` sem PR e `ci-ok` verde, seja qual for o cliente | Não impede o merge por quem tem permissão; por isso o merge é negado ao agente nas camadas 1 e 2 |

Nenhuma camada sozinha basta; o desenho supõe que cada uma pode falhar.

**Limitações conhecidas e aceitas** (encontradas na revisão da implementação):
- **Escrita via Bash em paths sensíveis** (`sed -i … commission/rules.py`, `echo > .claude/settings.json`) não passa pelas regras de path do hook. Ela fica contida porque nenhum desses comandos está no `allow`, então cai no prompt padrão. A revisão humana do diff é a última barreira.
- **Ofuscação deliberada** (variáveis montadas em runtime, `eval`, base64) não é detectável por regex. O hook cobre erros e atalhos, não um adversário; para isso existe a camada 3.
- **Aliases do shell** do usuário não são expandidos. `gh alias set` é negado para que o agente não crie aliases novos.

## 3. Matriz de capacidades

### 3.1 Livre (sem prompt): `allow`
| Ação | Regras |
|---|---|
| Ler código e docs | `Read`, `Grep`, `Glob` (exceto o que está em §3.3) |
| Checks locais | `Bash(uv sync*)`, `Bash(uv run pytest*)`, `Bash(uv run ruff *)`, `Bash(uv run mypy*)`, `Bash(uv run pre-commit *)` |
| CLI do projeto | `Bash(uv run atlas-cli *)` (geração local; o `upload` cai em §3.2 pelo hook) |
| Git local | `Bash(git status*)`, `Bash(git diff*)`, `Bash(git log*)`, `Bash(git show*)`, `Bash(git add *)`, `Bash(git commit *)`, `Bash(git switch *)`, `Bash(git fetch*)`, `Bash(git pull*)` |
| Push da própria branch | `Bash(git push -u origin task/*)`, `Bash(git push origin task/*)`, `Bash(git push)` (o hook nega se a branch atual for `main`) |
| PRs (leitura e abertura) | `Bash(gh pr create *)`, `Bash(gh pr view *)`, `Bash(gh pr checks *)`, `Bash(gh pr list*)`, `Bash(gh pr diff *)`, `Bash(gh run view *)`, `Bash(gh run list*)` |
| Databricks (somente leitura e validação) | `Bash(databricks bundle validate*)` |
| Editar código | `Edit`/`Write` em qualquer path **fora** dos listados em §3.2 e §3.3 |

### 3.2 Exige a sua confirmação: `ask`
| Ação | Camada | Por quê |
|---|---|---|
| Editar `docs/specs/**/spec.md`, `docs/specs/mission.md`, `docs/specs/tech-stack.md`, `docs/adr/**` | hook | Spec antes de código: mudar o contrato é decisão humana. **Exceção:** `roadmap.md` e `tasks.md` são livres (o agente marca `[x]` no PR) |
| Editar `commission/rules.py` e `commission/**/*.yaml` | hook | Faixas e taxas de comissão: a etapa irreversível (ADR-0010) |
| Editar `semantic/**` | hook | Definição única das métricas (ADR-0005) |
| Editar `.claude/**`, `.github/workflows/**`, `.github/CODEOWNERS` | hook | O agente não afrouxa os próprios limites nem o CI |
| `databricks bundle deploy -t dev`, `databricks fs cp/rm/mv`, `databricks jobs run-now`, `databricks pipelines start-update`, `uv run atlas-cli upload` | settings + hook | Efeito no workspace (mesmo que em `dev`) |
| Qualquer outro `databricks …`, `git push` não coberto em §3.1, `gh` não coberto | settings (fora do `allow` → prompt padrão) | Padrão seguro |

### 3.3 Proibido: `deny` (settings **e** hook)
| Ação | Padrão verificado pelo hook (em qualquer parte do comando) | Mensagem |
|---|---|---|
| Merge de PR | `gh pr merge` (inclusive com `-R`/`--repo`), `gh api -X PUT …/pulls/N/merge`, `gh api …/merges`, GraphQL `mergePullRequest`, `gh alias set/import` | "Merge é do mantenedor (ADR-0014). Peça a revisão no PR." |
| Push para a `main` | `git push … main`, `git push … HEAD:main`, `git push` estando na `main` | "A main só muda por PR (SPEC-009 §5)." |
| Force push e reescrita ou remoção de branch remota | `--force`, `--force-with-lease`, `--force-if-includes`, flags curtas com `f`/`d` (`-f`, `-uf`, `-d`), `+ref`, `:ref`, `--delete`, `--mirror`, `--prune` | "Reescrita ou remoção de branch remota é proibida." |
| Mexer na proteção ou nas configurações do repo | `gh api … /protection` ou `/rulesets`, `gh api -X PATCH/PUT/DELETE repos/<o>/<r>`, `gh repo edit/delete/rename/archive`, `gh secret`, `gh variable`, `gh ruleset` | "Configuração do repositório é do mantenedor." |
| Deploy no ambiente de demo | `bundle deploy … -t demo`, `--target demo` | "Deploy em demo é manual (ADR-0012)." |
| Executar a aprovação de comissão | Comando `databricks …` ou `run-now` que cite `commission_review` (um `grep` ou `pytest` que cite o nome não é bloqueado; qualquer `databricks jobs run-now` já cai em `ask`) | "Aprovar comissão é decisão humana (ADR-0010)." |
| Ler segredos | `Read`/`Edit`/`Bash` com `.env`, `.env.*` (exceto `.env.example`), `.databrickscfg`, `*.pem`, `*.key`; `gh auth token`, `databricks auth token`; `printenv`, `env`, `set` ou `export -p` sem argumento | "Segredos nunca passam pelo agente." |
| Pular os hooks locais | `--no-verify`, `git commit -n` (inclusive em `-anm`), `-c core.hooksPath=…`, `SKIP=…` | "Os hooks de pre-commit não podem ser pulados." |

## 4. O hook `guard.py`

**Registro** (em `.claude/settings.json`): `PreToolUse` com `matcher: "Bash|Edit|Write|MultiEdit|NotebookEdit|Read|Grep|Glob"` (Grep e Glob pelo campo `path`), comando `"$CLAUDE_PROJECT_DIR"/.claude/hooks/guard.py`.

**Contrato:**
- **Entrada:** JSON no stdin (`tool_name`, `tool_input.command` ou `tool_input.file_path`/`notebook_path`).
- **Saída:**
  - Sem objeção → exit 0 sem stdout (segue o fluxo normal de permissões).
  - Proibido → exit 0 com `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "<mensagem da §3.3>"}}`.
  - Exige confirmação → mesmo formato com `"permissionDecision": "ask"` e o motivo da §3.2.
- **Falha interna** (JSON inválido, exceção): **nega** com "guard.py falhou; revise o log". Na dúvida, fecha (*fail closed*).
- **Normalização antes do regex:** cada regra é testada contra duas versões do comando: (a) espaços colapsados, com quebras de linha viradas `;` para preservar a fronteira de segmento; (b) a versão (a) sem aspas e sem opções globais (`git -C . push` → `git push`, `gh -R o/r pr merge` → `gh pr merge`). Os caminhos são resolvidos para relativos à raiz do repo. Os padrões valem **em qualquer posição** (cobre `sh -c`, `&&`, `;`, `$(…)`, subshells).
- **Compatível com Python 3.9:** o shebang `python3` pode cair no `/usr/bin/python3` do macOS (3.9). Um erro de import sai com exit 1, que o Claude Code trata como não bloqueante, ou seja, abriria tudo. Um teste roda o hook nesse interpretador quando ele existe.
- **Branch atual:** para os pushes, o hook consulta `git rev-parse --abbrev-ref HEAD`.
- **Log:** cada `deny`/`ask` é acrescentado a `.claude/hooks.log` (ignorado no git): timestamp, tool, decisão, regra e o comando ou path (segredos nunca aparecem no log, porque o hook só loga o nome da regra para casos de segredo).

**Limitação aceita (falso positivo):** como o hook lê o comando inteiro, uma mensagem de commit ou o corpo de PR passados inline que *citem* um comando proibido são negados. A saída documentada no `CLAUDE.md` é escrever o texto num arquivo (`git commit -F`, `gh pr create --body-file`). Preferimos esse atrito a afrouxar o regex.

**As regras são dados, não código espalhado:** uma tabela `RULES = [(id, tool, regex, decision, message), …]` no topo do arquivo, com um teste pytest para cada regra (um caso positivo e um negativo) em `tests/test_guard_hook.py`.

## 5. Contexto do agente (`CLAUDE.md`)
O `CLAUDE.md` na raiz deve conter, nesta ordem, **sem duplicar** a constituição (aponta para ela):
1. Uma frase do que é o projeto + links para `mission.md`, `tech-stack.md`, `roadmap.md`.
2. **Como trabalhar uma task:** a próxima task é a primeira `[ ]` com dependências `[x]`; uma task = uma branch `task/<ID>-<slug>` = um PR; tasks 👤 nunca; rodar `uv run pytest && uv run ruff check . && uv run mypy` antes de cada push; marcar `[x]` com `(#N)` no próprio PR.
3. **Se a spec estiver ambígua ou errada:** parar e perguntar, nunca adivinhar; propor a correção da spec num commit `docs(specs):` separado.
4. Mapa do repositório (uma linha por pasta, apontando a spec).
5. **Nunca faça:** espelho da seção Proibido do `tech-stack.md` + §3.3 desta spec.
6. Comandos úteis (checks, CLI, bundle validate).

Tamanho máximo: **150 linhas**. Detalhes ficam nas specs.

## 6. Commands do projeto (`.claude/commands/`)
| Command | Faz | Não faz |
|---|---|---|
| `/next-task` | Lê o `roadmap.md`, encontra a primeira `[ ]` com dependências `[x]`, mostra o ID, o executor, o "pronto quando" e os passos do `tasks.md`, e propõe o nome da branch | Não começa a task sozinho; se o executor for 👤, informa e para |
| `/close-task <ID> <PR>` | Marca `[x]` na linha da task com `(#PR)` e roda `uv run pytest` (teste de higiene) | Não faz merge |

## 7. Como o trabalho do agente é revisado
```
agente implementa → checks locais → /code-review (subagente) → corrige → abre PR (template + checklist)
     → CI (ci-ok) → VOCÊ revisa o diff e faz o merge (squash)
```
1. **Antes do PR:** o agente roda os checks locais e o `/code-review` no diff, e corrige os achados de correção. Os achados que ele decidir não corrigir vão para o corpo do PR com o motivo.
2. **No PR:** o template exige a task, a spec, o porquê e o checklist dos princípios. Um PR que muda comportamento sem mudar a spec é sinal de alerta.
3. **Revisão humana:** você lê o diff, confere o checklist e faz o merge. **O agente nunca faz merge** (§3.3), nem quando o CI está verde.
4. **Paths sensíveis** (CODEOWNERS) recebem atenção redobrada; um diff em `commission/` ou `semantic/` sem justificativa no PR é motivo para pedir mudanças.

## 8. Critérios de aceite
- **Dado** o agente numa sessão nova, **quando** pergunto "qual a próxima task?", **então** ele responde com o ID correto lendo o roadmap (P1.2).
- **Dado** `gh pr merge 9 --squash`, **ou** `sh -c "gh pr merge 9"`, **então** o hook nega com a mensagem do ADR-0014.
- **Dado** a branch atual `main`, **quando** o agente roda `git push`, **então** o hook nega.
- **Dado** `git push --force origin task/x`, **então** o hook nega.
- **Dado** um `Edit` em `docs/specs/003-commission-closing/spec.md` ou em `commission/rules.py`, **então** o hook pede confirmação (`ask`); **dado** um `Edit` em `docs/specs/roadmap.md`, **então** não há objeção.
- **Dado** `cat .env` ou `Read` de `.env.local`, **então** é negado; **dado** `Read` de `.env.example`, **então** é permitido.
- **Dado** `databricks bundle deploy -t demo`, **então** é negado; **dado** `-t dev`, **então** é `ask`.
- **Dado** um JSON de entrada malformado, **então** o hook nega (*fail closed*).
- **Dado** `tests/test_guard_hook.py`, **então** toda regra da tabela `RULES` tem um caso positivo e um negativo, e o CI roda esses testes.
- **Dado** `/next-task` com a próxima task 👤, **então** o command informa e não começa a task.

## 9. Fora de escopo
Sandbox de rede ou de sistema de arquivos no nível do SO, subagentes especializados por domínio (v2), MCPs de terceiros no harness (cada um exigiria um ADR).
