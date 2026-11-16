"""Gera `semantic/dashboards/commission_review.lvdash.json` a partir de `commission/review_sql`.

Utilitário de build (nunca roda em runtime). Depois de mexer nas consultas ou em
`commission/review_report.py`, rode `uv run python scripts/build_commission_review_dashboard.py`;
`commission/tests/test_review_report.py` falha se o JSON versionado divergir do gerado.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "semantic" / "dashboards" / "commission_review.lvdash.json"


def render() -> str:
    sys.path.insert(0, str(ROOT))
    from commission import review_report

    return json.dumps(review_report.build_dashboard(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"escrito: {OUT.relative_to(ROOT)}")
