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

## Arquitetura
_Em breve (Fase 2, [SPEC-011](docs/specs/011-architecture/spec.md))._

## Como rodar
_Em breve (Fase 4 em diante). Este README será completado na P13.3._

## Estrutura do repositório
```
cli/ pipeline/ semantic/ commission/ apps/{agent,mcp,web}/ eval/ scripts/ data/reference/ spikes/ tests/ docs/
```
Cada pasta tem um README dizendo qual spec a governa.

## Contribuindo
Veja [CONTRIBUTING.md](CONTRIBUTING.md).
