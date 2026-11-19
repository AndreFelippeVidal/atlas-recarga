"""Entrypoint do App `atlas-web` (SPEC-007 §2): FastAPI + build do React + malhas do mapa."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from atlas_web.app import create_app

WEB_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = WEB_DIR / "static"  # build do Vite, versionado (o App não tem Node)
GEO_DIR = WEB_DIR / "public" / "geo"


def build_app() -> FastAPI:
    return create_app(static_dir=STATIC_DIR, geo_dir=GEO_DIR)


def main() -> None:
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    uvicorn.run(build_app(), host="0.0.0.0", port=port)  # noqa: S104 - o App escuta atrás do proxy


if __name__ == "__main__":
    main()
