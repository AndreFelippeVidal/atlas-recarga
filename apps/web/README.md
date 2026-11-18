# apps/web

Databricks App `atlas-web` (FastAPI + React). Governado pela [SPEC-007](../../docs/specs/007-react-geo-dashboard/spec.md).

`public/geo/` guarda as malhas do mapa (TopoJSON simplificado do IBGE), geradas por [`scripts/fetch_geo.py`](../../scripts/fetch_geo.py); não edite à mão.

## Backend (P12.2)

`atlas_web/` é o FastAPI: `GET /api/months`, `GET /api/kpis?month=YYYY-MM` e `GET /api/health`. Lê só `atlas.semantic.mv_recharges` por `MEASURE()`, com o service principal do App, e guarda cada resposta em memória por 10 minutos. Valores monetários e contagens saem como string decimal (sem float). No primeiro mês da série, `previous` e `delta_pct` são `null`. Os endpoints do mapa chegam na P12.3.

```bash
uv run pytest apps/web
uv run python scripts/check_web_kpis.py   # no dev, pelo mantenedor (ver o docstring)
```
