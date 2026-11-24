import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from atlas_cli.main import app
from atlas_cli.manifest import MANIFEST_NAME
from atlas_cli.prune import PruneError, prune_recharges
from typer.testing import CliRunner

REPO = Path(__file__).resolve().parents[2]
ENV = {"ATLAS_REFERENCE_PATH": str(REPO / "data" / "reference" / "municipalities_ibge.csv")}
runner = CliRunner()


def _generate(out: Path) -> None:
    result = runner.invoke(
        app,
        [
            "generate",
            *("--rows", "20000"),
            *("--pos", "800"),
            *("--months", "2"),
            *("--end-month", "2026-11"),
            *("--scenarios", "none"),
            *("--out", str(out)),
        ],
        env=ENV,
    )
    assert result.exit_code == 0, result.output


def _manifest(out: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    return manifest


@pytest.fixture(scope="module")
def full(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("full")
    _generate(out)
    return out


def _copy(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


def test_prune_keeps_only_the_range_and_the_manifest_stays_consistent(
    full: Path, tmp_path: Path
) -> None:
    out = _copy(full, tmp_path / "out")
    before = _manifest(out)
    result = prune_recharges(out, date(2026, 10, 5), date(2026, 10, 9))

    days = sorted(p.name for p in (out / "recharges").glob("dt=*"))
    assert days == [f"dt=2026-10-0{d}" for d in range(5, 10)]
    manifest = _manifest(out)
    assert manifest["pruned"] == {"from": "2026-10-05", "to": "2026-10-09"}
    assert manifest["counts"]["partitions"] == 5 == result.kept_partitions
    kept_rows = sum(
        pq.read_metadata(f).num_rows for f in (out / "recharges").glob("dt=*/part-*.parquet")
    )
    assert manifest["counts"]["recharges"] == kept_rows == result.kept_rows
    assert result.removed_rows + kept_rows == before["counts"]["recharges"]
    # os dias mantidos têm os mesmos bytes da geração completa
    for name, entry in manifest["files"].items():
        assert before["files"][name] == entry
    assert manifest["counts"]["pos"] == before["counts"]["pos"]

    check = runner.invoke(app, ["validate", "--out", str(out)], env=ENV)
    assert check.exit_code == 0, check.output
    assert "invariante 5" in check.output and "pulado" in check.output


def test_prune_is_idempotent(full: Path, tmp_path: Path) -> None:
    out = _copy(full, tmp_path / "out")
    prune_recharges(out, date(2026, 10, 5), date(2026, 10, 9))
    first = (out / MANIFEST_NAME).read_text(encoding="utf-8")
    again = prune_recharges(out, date(2026, 10, 5), date(2026, 10, 9))
    assert again.removed_partitions == 0
    assert (out / MANIFEST_NAME).read_text(encoding="utf-8") == first


def test_prune_range_outside_the_window_removes_everything(full: Path, tmp_path: Path) -> None:
    out = _copy(full, tmp_path / "out")
    result = prune_recharges(out, date(2027, 1, 1), date(2027, 1, 2))
    assert result.kept_partitions == 0 and result.kept_rows == 0
    assert _manifest(out)["counts"]["recharges"] == 0


def test_prune_rejects_inverted_range_and_missing_manifest(full: Path, tmp_path: Path) -> None:
    with pytest.raises(PruneError, match="depois de"):
        prune_recharges(full, date(2026, 10, 9), date(2026, 10, 5))
    with pytest.raises(PruneError, match=r"_manifest\.json"):
        prune_recharges(tmp_path, date(2026, 10, 1), date(2026, 10, 2))
