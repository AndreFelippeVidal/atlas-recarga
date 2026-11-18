# apps/web

Databricks App `atlas-web` (FastAPI + React). Governado pela [SPEC-007](../../docs/specs/007-react-geo-dashboard/spec.md).

`public/geo/` guarda as malhas do mapa (TopoJSON simplificado do IBGE), geradas por [`scripts/fetch_geo.py`](../../scripts/fetch_geo.py); não edite à mão.
