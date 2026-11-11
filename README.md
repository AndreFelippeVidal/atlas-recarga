# Atlas Recarga

Plataforma de dados e IA no **Databricks Free Edition** para a rede de recarga pré-paga da **Eaí? Telecom** (empresa fictícia; dados 100% sintéticos). Mostra no mapa do Brasil onde a recarga acontece, fecha a comissão de canal com revisão humana e responde a perguntas de negócio com números rastreáveis.

> 🚧 Em construção, guiado por Spec-Driven Development. O status está no [roadmap](docs/specs/roadmap.md).

## Comece por aqui
| Quero… | Leia |
|---|---|
| Entender o problema | [Discovery](docs/discovery.md) |
| Ver o escopo e as métricas | [PRD](docs/prd.md) |
| Conhecer os princípios e a stack | [Mission](docs/specs/mission.md) · [Tech stack](docs/specs/tech-stack.md) |
| Ver o que vem a seguir | [Roadmap](docs/specs/roadmap.md) |
| Entender as decisões | [ADRs](docs/adr/README.md) |
| Ver como as peças se encaixam | [Arquitetura](docs/architecture.md) |

## Arquitetura
Componentes, onde ficam os dados, a fronteira do humano (comissão) e a da IA (só leitura): [docs/architecture.md](docs/architecture.md).

## Como rodar
_A plataforma em si vem a partir da Fase 4; este README será completado na P13.3._

Checks locais (os mesmos do CI):
```bash
uv sync                      # Python 3.12 + ruff, mypy, pytest, pre-commit
uv run pre-commit install    # ruff + gitleaks antes de cada commit
uv run ruff check . && uv run mypy && uv run pytest
```

## Estrutura do repositório
```
cli/ pipeline/ semantic/ commission/ apps/{agent,mcp,web}/ eval/ scripts/ data/reference/ spikes/ tests/ docs/
```
Cada pasta tem um README dizendo qual spec a governa.

## Contribuindo
Veja [CONTRIBUTING.md](CONTRIBUTING.md).
