"""Build the simplified IBGE geometry for the map (SPEC-007 §2, task P12.1, ADR-0004).

Run **once** by the maintainer (or when the IBGE mesh changes); the generated TopoJSON
files are committed. Never runs at runtime and never in the pipeline: the App only
serves the committed files.

    uv run python scripts/fetch_geo.py

Needs network (IBGE malhas API v3) and Node (`npx`) for mapshaper, pinned below.

Output, in ``apps/web/public/geo/``:
- ``br-uf.json``: the 27 UFs (object ``uf``), properties ``uf`` and ``region``.
- ``mun/<UF>.json``: the municipalities of each UF (object ``municipalities``),
  property ``municipality_ibge_code`` (7 digits, as STRING).

``region`` and the set of municipalities come from ``data/reference/municipalities_ibge.csv``
(the same snapshot that feeds ``gold.dim_municipality``). The IBGE mesh has one more
municipality than the snapshot (Boa Esperança do Norte, MT, created after the Censo 2022 and
without population); its polygon is dropped here, so the mesh and ``dim_municipality`` match
100% (SPEC-007 §6). A snapshot municipality **without** a polygon is an error.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "data" / "reference" / "municipalities_ibge.csv"
OUTPUT = ROOT / "apps" / "web" / "public" / "geo"

API = "https://servicodados.ibge.gov.br/api/v3/malhas"
QUALITY = "maxima"
MAPSHAPER = "mapshaper@0.8.5"

# Share of vertices kept by mapshaper (Visvalingam, keep-shapes so no municipality vanishes).
UF_KEEP = "2%"
MUN_KEEP = "4%"
# Coordinates are quantized in the TopoJSON (units per axis); 1e5 is ~1 m at Brazil's scale.
QUANTIZATION = 100000

# Limits from SPEC-007 §2 (bytes); the test in tests/test_geo_files.py enforces the same numbers.
MAX_UF_BYTES = 300 * 1024
MAX_MUN_BYTES = 1536 * 1024

Feature = dict[str, Any]
Collection = dict[str, Any]


def load_reference(path: Path = REFERENCE) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def uf_of(code: str, reference: list[dict[str, str]]) -> str:
    """Sigla of an IBGE UF code (the first 2 digits of any municipality code)."""
    for row in reference:
        if row["municipality_ibge_code"].startswith(code):
            return row["uf"]
    raise ValueError(f"UF code {code} not in the reference")


def tag_ufs(collection: Collection, reference: list[dict[str, str]]) -> Collection:
    """Replace ``codarea`` by ``uf`` + ``region`` on the UF mesh."""
    region_by_uf = {row["uf"]: row["region"] for row in reference}
    features: list[Feature] = []
    for feature in collection["features"]:
        uf = uf_of(str(feature["properties"]["codarea"]), reference)
        features.append(
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": {"uf": uf, "region": region_by_uf[uf]},
            }
        )
    missing = sorted(set(region_by_uf) - {f["properties"]["uf"] for f in features})
    if missing:
        raise ValueError(f"UFs without a polygon: {missing}")
    return {"type": "FeatureCollection", "features": sorted(features, key=_uf_key)}


def _uf_key(feature: Feature) -> str:
    return str(feature["properties"]["uf"])


def tag_municipalities(
    collection: Collection, uf: str, reference: list[dict[str, str]]
) -> tuple[Collection, list[str]]:
    """Keep ``municipality_ibge_code`` only; drop polygons absent from the reference.

    Returns the cleaned collection and the dropped codes. Raises if a municipality of the
    UF in the reference has no polygon.
    """
    expected = {r["municipality_ibge_code"] for r in reference if r["uf"] == uf}
    features: list[Feature] = []
    dropped: list[str] = []
    for feature in collection["features"]:
        code = str(feature["properties"]["codarea"])
        if code not in expected:
            dropped.append(code)
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": {"municipality_ibge_code": code},
            }
        )
    found = {f["properties"]["municipality_ibge_code"] for f in features}
    if found != expected:
        raise ValueError(f"{uf}: municipalities without a polygon: {sorted(expected - found)}")
    features.sort(key=lambda f: str(f["properties"]["municipality_ibge_code"]))
    return {"type": "FeatureCollection", "features": features}, sorted(dropped)


def download(url: str, retries: int = 3) -> Collection:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310  (https, fixed host)
                data: Collection = json.load(response)
                return data
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last = error
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"download failed: {url}: {last}")


def mesh_url(path: str, inner: str) -> str:
    return f"{API}/{path}?formato=application/vnd.geo+json&qualidade={QUALITY}&intrarregiao={inner}"


def simplify(source: Path, target: Path, layer: str, keep: str) -> None:
    """GeoJSON -> simplified TopoJSON with mapshaper (pinned version, no shell)."""
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx not found: install Node 22 LTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        npx,
        "--yes",
        MAPSHAPER,
        str(source),
        "-simplify",
        "visvalingam",
        keep,
        "keep-shapes",
        "-rename-layers",
        layer,
        "-o",
        str(target),
        "format=topojson",
        f"quantization={QUANTIZATION}",
        "force",
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603


def build(output: Path, reference: list[dict[str, str]]) -> dict[str, int]:
    """Download, tag, simplify and write everything. Returns ``{relative path: bytes}``."""
    sizes: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        ufs = tag_ufs(download(mesh_url("paises/BR", "UF")), reference)
        raw = work / "br-uf.geojson"
        raw.write_text(json.dumps(ufs), encoding="utf-8")
        simplify(raw, output / "br-uf.json", "uf", UF_KEEP)
        sizes["br-uf.json"] = (output / "br-uf.json").stat().st_size

        for uf in sorted({row["uf"] for row in reference}):
            code = uf_of_code(uf, reference)
            collection = download(mesh_url(f"estados/{code}", "municipio"))
            tagged, dropped = tag_municipalities(collection, uf, reference)
            if dropped:
                print(f"{uf}: polygons dropped (not in the reference): {dropped}")
            raw = work / f"{uf}.geojson"
            raw.write_text(json.dumps(tagged), encoding="utf-8")
            target = output / "mun" / f"{uf}.json"
            simplify(raw, target, "municipalities", MUN_KEEP)
            sizes[f"mun/{uf}.json"] = target.stat().st_size
    return sizes


def uf_of_code(uf: str, reference: list[dict[str, str]]) -> str:
    """IBGE UF code (2 digits) of a sigla."""
    for row in reference:
        if row["uf"] == uf:
            return row["municipality_ibge_code"][:2]
    raise ValueError(f"unknown UF {uf}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT, help="destination directory")
    args = parser.parse_args(argv)

    sizes = build(args.output, load_reference())
    too_big = {
        name: size
        for name, size in sizes.items()
        if size > (MAX_UF_BYTES if name == "br-uf.json" else MAX_MUN_BYTES)
    }
    for name, size in sorted(sizes.items()):
        print(f"{size / 1024:8.1f} KB  {name}")
    if too_big:
        print(f"over the SPEC-007 §2 limit: {too_big}; lower UF_KEEP/MUN_KEEP", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
