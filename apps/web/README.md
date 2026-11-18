# apps/web

Databricks App `atlas-web` (FastAPI + React). Governado pela [SPEC-007](../../docs/specs/007-react-geo-dashboard/spec.md).

`public/geo/` guarda as malhas do mapa (TopoJSON simplificado do IBGE), geradas por [`scripts/fetch_geo.py`](../../scripts/fetch_geo.py); não edite à mão.

## Backend (P12.2, P12.3)

`atlas_web/` é o FastAPI: `GET /api/months`, `GET /api/kpis?month=YYYY-MM` e `GET /api/health`. Lê só `atlas.semantic.mv_recharges` por `MEASURE()`, com o service principal do App, e guarda cada resposta em memória por 10 minutos. Valores monetários e contagens saem como string decimal (sem float). No primeiro mês da série, `previous` e `delta_pct` são `null`.

O mapa (P12.3): `GET /api/map/region`, `/api/map/uf` (`region` opcional) e `/api/map/municipality` (`uf` obrigatório), todos com `month` e `measure` (`gross_revenue`, `recharge_count`, `avg_ticket`, `active_pos`, `mom_change`). Cada nível vem de `MEASURE()` agrupado pela dimensão do nível. O `mom_change` (Δ% de `gross_revenue`) é calculado no backend e vale `null` sem base no mês anterior. Medida, região ou UF fora da lista fechada dão `400`; mês sem dados, `404`.

```bash
uv run pytest apps/web
uv run python scripts/check_web_kpis.py   # no dev, pelo mantenedor (ver o docstring)
uv run python scripts/check_web_map.py    # idem; confere soma das regiões e UFs = KPI
```

## Frontend (P12.4)

`frontend/` é o Vite + React 18 + TypeScript (pnpm, Node 22). Em desenvolvimento, `vite` faz proxy de `/api` para `localhost:8000` (o FastAPI) e serve `public/geo/` pelo `publicDir`. O FastAPI ainda não serve o build estático (P12.8).

```bash
cd apps/web/frontend
pnpm install && pnpm dev            # http://localhost:5173
pnpm typecheck && pnpm lint && pnpm format:check && pnpm test && pnpm build   # o mesmo job `web-frontend` do CI
```

Os valores chegam como string decimal e o frontend só formata; nenhuma métrica é calculada aqui.
