# Tasks — 007-react-geo-dashboard

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 12 — Dashboard React com mapa

### P12.1 🤖 `scripts/fetch_geo.py`: malhas do IBGE → TopoJSON simplificado em `apps/web/public/geo/`

- **Depende de:** P4.2
- **Pronto quando:** Tamanhos dentro do limite; teste de match de 100% com `dim_municipality`

### P12.2 🤖 Backend FastAPI: `/api/months`, `/api/kpis`, `/api/health` + cache

- **Depende de:** P7.1
- **Pronto quando:** Os KPIs batem com o AI/BI

### P12.3 🤖 `/api/map/region`, `/api/map/uf` e `/api/map/municipality` (com `mom_change`) + validação de `measure`

- **Depende de:** P12.2
- **Pronto quando:** 400 para medida inválida; a soma das regiões e a das UFs são iguais ao KPI

### P12.4 🤖 Frontend: esqueleto Vite + React + TS, layout, KPI cards

- **Depende de:** P0.5
- **Pronto quando:** Build no CI (`tsc`, `eslint`, `vitest`)

### P12.5 🤖 Mapa por região (UFs pintadas pela região) com `d3-geo`, escala de quantis, legenda, tooltip

- **Depende de:** P12.1, P12.3, P12.4
- **Pronto quando:** Visual conferido por você
- **Passos:**
  - Usar o skill dataviz para a paleta e a legenda

### P12.6 🤖 Drill-down: Brasil → região → UF → municípios, com zoom; breadcrumb e Esc

- **Depende de:** P12.5
- **Pronto quando:** Critério 1 da SPEC-007 §6 (queda no PA visível)

### P12.7 🤖 Escala divergente `mom_change`, estados de loading e erro, acessibilidade

- **Depende de:** P12.6
- **Pronto quando:** Critério 6 da SPEC-007 §6 + navegação por teclado

### P12.8 🤝 Deploy do App `atlas-web` + medição de p95

- **Depende de:** P12.7
- **Pronto quando:** p95 < 3s registrado
