# Specs — Atlas Recarga

## Constituição (leia primeiro)

| Arquivo | Responde | Muda |
|---|---|---|
| [mission.md](mission.md) | Por que existimos, para quem, **princípios inegociáveis** | Raramente (PR + justificativa) |
| [tech-stack.md](tech-stack.md) | Com o que construímos, convenções e **o que é proibido** | Com um ADR |
| [roadmap.md](roadmap.md) | Em que ordem, em tasks pequenas, e **o status de cada uma** | A cada PR mergeado |

## Specs

Cada spec vive na própria pasta: `NNN-nome/spec.md` (comportamento, contratos e critérios de aceite) + `NNN-nome/tasks.md` (passos de cada task do roadmap). Os IDs são estáveis e **não** indicam ordem de execução; a ordem está no [roadmap](roadmap.md).

Se quem implementa (pessoa ou agente de código) precisa adivinhar, a spec está errada e é corrigida por PR antes do código.

| Spec | Tema | Fase(s) | PRD | ADRs | Status |
|---|---|---|---|---|---|
| [000](000-platform-spike/spec.md) | Spike S0: validações na Free Edition | 3 | — | 0001, 0005, 0007, 0008, 0010, 0013 | rascunho |
| [001](001-synthetic-data-cli/spec.md) | CLI de dados sintéticos | 4 | F1 | 0004, 0011 | rascunho |
| [002](002-medallion-pipeline/spec.md) | Bundle, catálogo e pipeline medalhão | 5, 6 | F2 | 0001, 0002, 0003 | rascunho |
| [003](003-commission-closing/spec.md) | Fechamento de comissão | 8 | F3 | 0010 | rascunho |
| [004](004-metric-views/spec.md) | Metric views, AI/BI e Genie | 7 | F4, F5 | 0005 | rascunho |
| [005](005-business-agent/spec.md) | Agente de negócio | 10 | F6 | 0006, 0007, 0009 | rascunho |
| [006](006-mcp-server/spec.md) | MCP server (FastMCP) | 11 | F7 | 0008, 0009 | rascunho |
| [007](007-react-geo-dashboard/spec.md) | Dashboard React com mapa | 12 | F8 | 0004, 0009 | rascunho |
| [008](008-agent-evaluation/spec.md) | Avaliação e monitoramento do agente | 9, 10 | F9 | 0013 | rascunho |
| [009](009-repo-foundation/spec.md) | Fundação do repositório | 0 | — | — | a escrever (P0.1) |
| [010](010-agent-harness/spec.md) | Harness do agente de código | 1 | — | 0012 | a escrever (P1.1) |
| [011](011-architecture/spec.md) | Arquitetura explicada | 2 | — | todos | a escrever (P2.1) |

Convenções globais (nomes, dinheiro, tempo, geo, segredos): [tech-stack.md § Convenções globais](tech-stack.md#convenções-globais).
