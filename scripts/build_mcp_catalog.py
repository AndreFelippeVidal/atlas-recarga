"""Gera `apps/mcp/atlas_mcp/catalog.json` a partir de `semantic/*.yaml` (SPEC-006 §3, task P11.2).

O App `atlas-mcp` só leva `apps/mcp` no deploy, então não enxerga `semantic/`. Este snapshot
carrega a **lista fechada** (medidas e dimensões por view, com o comentário oficial) sem
duplicar a definição: a fonte continua sendo o YAML, e um teste falha se o JSON ficar velho.

    uv run python scripts/build_mcp_catalog.py          # reescreve o JSON
    uv run python scripts/build_mcp_catalog.py --check  # sai com 1 se estiver desatualizado
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parent.parent
SEMANTIC_DIR = ROOT / "semantic"
CATALOG_PATH = ROOT / "apps" / "mcp" / "atlas_mcp" / "catalog.json"

# Dimensão de mês de cada view: `month_from`/`month_to` filtram por ela (SPEC-006 §3).
PERIOD_DIMENSION = {"mv_recharges": "recharge_month", "mv_commission": "reference_month"}

# Medidas com janela (SPEC-004 §5): entram na lista fechada marcadas com `window`; o `query_metric`
# as aceita só com um mês (SPEC-006 §3). As `aux_*` são pedaços de composição e nunca entram.
AUX_PREFIX = "aux_"
WINDOW_MEASURES = frozenset({"gross_revenue_t3m", "gross_revenue_ytd", "revenue_mom_change"})


def _is_consumable(measure: dict[str, Any]) -> bool:
    return not str(measure["name"]).startswith(AUX_PREFIX)


def _items(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for e in entries:
        item: dict[str, Any] = {
            "name": e["name"],
            "description": " ".join(str(e.get("comment", "")).split()),
        }
        if e["name"] in WINDOW_MEASURES:
            item["window"] = True
        items.append(item)
    return items


def build_catalog(directory: Path = SEMANTIC_DIR) -> dict[str, Any]:
    views: dict[str, Any] = {}
    for view, period in PERIOD_DIMENSION.items():
        doc = yaml.safe_load((directory / f"{view}.yaml").read_text(encoding="utf-8"))
        dimensions = _items(doc["dimensions"])
        if period not in {d["name"] for d in dimensions}:
            raise ValueError(f"{view}: dimensão de período {period!r} não existe no YAML")
        views[view] = {
            "description": " ".join(str(doc["comment"]).split()),
            "period_dimension": period,
            "measures": _items([m for m in doc["measures"] if _is_consumable(m)]),
            "dimensions": dimensions,
        }
    return {"views": views}


def render(catalog: dict[str, Any]) -> str:
    return json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="só confere, não escreve")
    args = parser.parse_args(argv)
    expected = render(build_catalog())
    if args.check:
        current = CATALOG_PATH.read_text(encoding="utf-8") if CATALOG_PATH.exists() else ""
        if current != expected:
            print("catalog.json desatualizado: rode scripts/build_mcp_catalog.py", file=sys.stderr)
            return 1
        return 0
    CATALOG_PATH.write_text(expected, encoding="utf-8")
    print(f"escrito {CATALOG_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
