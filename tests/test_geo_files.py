"""Checks of the committed map geometry (SPEC-007 §2 and §6, task P12.1).

Reads only the TopoJSON in ``apps/web/public/geo/`` and the IBGE snapshot that feeds
``gold.dim_municipality``: no network, no script run.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / "apps" / "web" / "public" / "geo"
REFERENCE = ROOT / "data" / "reference" / "municipalities_ibge.csv"

# `scripts` also names a package under apps/agent, so load the script by path.
_spec = importlib.util.spec_from_file_location("fetch_geo", ROOT / "scripts" / "fetch_geo.py")
assert _spec and _spec.loader
fetch_geo = importlib.util.module_from_spec(_spec)
sys.modules["fetch_geo"] = fetch_geo
_spec.loader.exec_module(fetch_geo)


@pytest.fixture(scope="module")
def reference() -> list[dict[str, str]]:
    with REFERENCE.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _properties(path: Path, layer: str) -> list[dict[str, Any]]:
    topology = json.loads(path.read_text(encoding="utf-8"))
    assert topology["type"] == "Topology"
    assert list(topology["objects"]) == [layer]
    return [g["properties"] for g in topology["objects"][layer]["geometries"]]


def test_uf_mesh_has_the_27_ufs_with_region(reference: list[dict[str, str]]) -> None:
    path = GEO / "br-uf.json"
    assert path.stat().st_size <= 300 * 1024
    props = _properties(path, "uf")
    region_by_uf = {row["uf"]: row["region"] for row in reference}
    assert len(props) == 27
    assert {p["uf"]: p["region"] for p in props} == region_by_uf


def test_municipality_meshes_match_dim_municipality_100_percent(
    reference: list[dict[str, str]],
) -> None:
    expected: dict[str, set[str]] = {}
    for row in reference:
        expected.setdefault(row["uf"], set()).add(row["municipality_ibge_code"])
    assert sorted(p.stem for p in (GEO / "mun").glob("*.json")) == sorted(expected)

    total = 0
    for uf, codes in expected.items():
        path = GEO / "mun" / f"{uf}.json"
        assert path.stat().st_size <= 1536 * 1024, uf
        found = [p["municipality_ibge_code"] for p in _properties(path, "municipalities")]
        assert len(found) == len(set(found)), f"{uf}: duplicated polygons"
        assert set(found) == codes, uf
        total += len(found)
    assert total == len(reference) == 5570


def test_municipality_codes_are_7_digit_strings() -> None:
    for path in (GEO / "mun").glob("*.json"):
        for prop in _properties(path, "municipalities"):
            code = prop["municipality_ibge_code"]
            assert isinstance(code, str)
            assert len(code) == 7
            assert set(prop) == {"municipality_ibge_code"}


def test_size_limits_in_the_script_match_the_spec() -> None:
    assert fetch_geo.MAX_UF_BYTES == 300 * 1024
    assert fetch_geo.MAX_MUN_BYTES == 1536 * 1024


# --- the pure steps of the script, on tiny fixtures ---------------------------------------

POINT = {"type": "Point", "coordinates": [0, 0]}
REF = [
    {"municipality_ibge_code": "1100015", "uf": "RO", "region": "N"},
    {"municipality_ibge_code": "1100023", "uf": "RO", "region": "N"},
    {"municipality_ibge_code": "5100102", "uf": "MT", "region": "CO"},
]


def _collection(*codes: str) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": POINT, "properties": {"codarea": c}} for c in codes
        ],
    }


def test_tag_municipalities_drops_polygons_outside_the_reference() -> None:
    tagged, dropped = fetch_geo.tag_municipalities(
        _collection("1100023", "1100015", "1199999"), "RO", REF
    )
    assert dropped == ["1199999"]
    assert [f["properties"] for f in tagged["features"]] == [
        {"municipality_ibge_code": "1100015"},
        {"municipality_ibge_code": "1100023"},
    ]


def test_tag_municipalities_fails_when_a_reference_municipality_has_no_polygon() -> None:
    with pytest.raises(ValueError, match="without a polygon"):
        fetch_geo.tag_municipalities(_collection("1100015"), "RO", REF)


def test_tag_ufs_adds_uf_and_region_and_requires_every_uf() -> None:
    tagged = fetch_geo.tag_ufs(_collection("51", "11"), REF)
    assert [f["properties"] for f in tagged["features"]] == [
        {"uf": "MT", "region": "CO"},
        {"uf": "RO", "region": "N"},
    ]
    with pytest.raises(ValueError, match="UFs without a polygon"):
        fetch_geo.tag_ufs(_collection("11"), REF)
