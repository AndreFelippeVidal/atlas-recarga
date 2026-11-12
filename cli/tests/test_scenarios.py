import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
from atlas_cli.main import app
from atlas_cli.manifest import MANIFEST_NAME, sha256_file
from atlas_cli.reference import load_municipalities
from atlas_cli.scenarios import SCENARIO_IDS, catalog, parse_scenarios
from atlas_cli.scenarios.regional_drop import BAIXO_AMAZONAS, target_month
from typer.testing import CliRunner

REPO = Path(__file__).resolve().parents[2]
REFERENCE = REPO / "data" / "reference" / "municipalities_ibge.csv"
SP = ZoneInfo("America/Sao_Paulo")
ROWS = 60_000
runner = CliRunner()


def _generate(out: Path, scenarios: str, rows: int = ROWS, seed: int = 42) -> dict[str, Any]:
    result = runner.invoke(
        app,
        [
            "generate", "--rows", str(rows), "--pos", "1500", "--months", "3",
            "--end-month", "2026-11", "--scenarios", scenarios, "--seed", str(seed),
            "--out", str(out),
        ],
        env={"ATLAS_REFERENCE_PATH": str(REFERENCE)},
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    manifest: dict[str, Any] = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    return manifest


@pytest.fixture(scope="module")
def all_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    out = tmp_path_factory.mktemp("all")
    return out, _generate(out, "all")


@pytest.fixture(scope="module")
def none_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    out = tmp_path_factory.mktemp("none")
    return out, _generate(out, "none")


def _recharges(out: Path) -> pa.Table:
    """Recargas com as colunas `dt` (partição) e `part` (nome do arquivo)."""
    tables = []
    for path in sorted((out / "recharges").glob("dt=*/part-*.parquet")):
        table = pq.read_table(path)
        n = table.num_rows
        table = table.append_column("dt", pa.array([path.parent.name[3:]] * n, pa.string()))
        tables.append(table.append_column("part", pa.array([path.stem] * n, pa.string())))
    return pa.concat_tables(tables)


def _sp_date(ts: datetime) -> str:
    return ts.astimezone(SP).date().isoformat()


def test_parse_and_catalog_cover_every_scenario() -> None:
    assert parse_scenarios("all") == SCENARIO_IDS
    assert [entry[0] for entry in catalog()] == list(SCENARIO_IDS)
    assert all(description for _, description, _ in catalog())


def test_scenario_list_command() -> None:
    result = runner.invoke(app, ["scenario", "list"])
    assert result.exit_code == 0
    for scenario_id in SCENARIO_IDS:
        assert scenario_id in result.output


def test_baixo_amazonas_codes_exist_in_reference_as_pa() -> None:
    muni = load_municipalities()
    by_code = dict(zip(muni.code, muni.uf, strict=True))
    assert len(BAIXO_AMAZONAS) == 13
    assert all(by_code.get(code) == "PA" for code in BAIXO_AMAZONAS)


def test_target_month_is_the_penultimate_month() -> None:
    days = tuple(date(2026, 8, 1) + timedelta(days=i) for i in range(92))  # ago a out
    assert target_month(days) == (2026, 9)
    assert target_month((date(2026, 10, 1), date(2026, 10, 31))) is None


def test_none_has_empty_scenarios_and_clean_data(none_run: tuple[Path, dict[str, Any]]) -> None:
    out, manifest = none_run
    assert manifest["scenarios"] == {}
    table = _recharges(out)
    assert table.num_rows == manifest["counts"]["recharges"] == ROWS
    assert table["pos_id"].null_count == 0
    assert len(pc.unique(table["recharge_id"])) == table.num_rows
    assert set(table["part"].to_pylist()) == {"part-0000"}


def test_manifest_counts_match_files(all_run: tuple[Path, dict[str, Any]]) -> None:
    out, manifest = all_run
    table = _recharges(out)
    pos = pq.read_table(out / "pos" / "pos.parquet")
    counts = manifest["counts"]
    assert counts["recharges"] == table.num_rows
    assert counts["pos"] == pos.num_rows == 1500
    assert (
        counts["distributors"]
        == pq.read_table(out / "distributors" / "distributors.parquet").num_rows
    )
    assert counts["partitions"] == len({p.parent for p in (out / "recharges").glob("dt=*/*")})
    assert set(manifest["scenarios"]) == set(SCENARIO_IDS)


def test_total_stays_within_one_percent(all_run: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = all_run
    assert abs(manifest["counts"]["recharges"] - ROWS) <= ROWS * 0.01


def test_null_and_unknown_pos_counts(all_run: tuple[Path, dict[str, Any]]) -> None:
    out, manifest = all_run
    table = _recharges(out)
    known = set(pq.read_table(out / "pos" / "pos.parquet")["pos_id"].to_pylist())
    pos_ids = table["pos_id"].to_pylist()
    assert manifest["scenarios"]["null_pos"]["rows"] == sum(p is None for p in pos_ids) == 30
    unknown = [p for p in pos_ids if p is not None and p not in known]
    assert manifest["scenarios"]["unknown_pos"]["rows"] == len(unknown) == 30


def test_negative_amount_count(all_run: tuple[Path, dict[str, Any]]) -> None:
    out, manifest = all_run
    negatives = pc.sum(pc.less(_recharges(out)["amount_brl"], 0).cast(pa.int64())).as_py()
    assert manifest["scenarios"]["negative_amount"]["rows"] == negatives == 10


def test_duplicates_repeat_ids_across_files(all_run: tuple[Path, dict[str, Any]]) -> None:
    out, manifest = all_run
    table = _recharges(out)
    ids = Counter(table["recharge_id"].to_pylist())
    repeated = {i for i, c in ids.items() if c > 1}
    assert manifest["scenarios"]["duplicates"]["rows"] == sum(ids.values()) - len(ids)
    assert len(repeated) == manifest["scenarios"]["duplicates"]["rows"] == 120
    rows = table.to_pylist()
    for rid in list(repeated)[:25]:
        copies = [r for r in rows if r["recharge_id"] == rid]
        assert len(copies) == 2
        assert copies[0]["dt"] != copies[1]["dt"]  # em arquivos diferentes
        assert copies[0]["pos_id"] == copies[1]["pos_id"]
        assert copies[0]["amount_brl"] == copies[1]["amount_brl"]


def test_late_arrival_goes_to_next_partition(all_run: tuple[Path, dict[str, Any]]) -> None:
    out, manifest = all_run
    table = _recharges(out)
    late = [r for r in table.to_pylist() if r["part"] == "part-0001"]
    assert len(late) == manifest["scenarios"]["late_arrival"]["rows"] > 0
    for row in late:
        day_before = date.fromisoformat(row["dt"]) - timedelta(days=1)
        assert _sp_date(row["recharge_ts_utc"]) == day_before.isoformat()
        expected = datetime.combine(
            date.fromisoformat(row["dt"]) + timedelta(days=1), datetime.min.time(), UTC
        )
        assert row["ingested_at_utc"] == expected.replace(hour=9)


def test_fractioning_bursts(all_run: tuple[Path, dict[str, Any]]) -> None:
    out, manifest = all_run
    table = _recharges(out)
    groups: dict[tuple[str, str], list[datetime]] = {}
    for row in table.to_pylist():
        if row["amount_brl"] == 10 and row["pos_id"] and row["status"] == "approved":
            groups.setdefault((row["pos_id"], row["subscriber_id"]), []).append(
                row["recharge_ts_utc"]
            )
    bursts = {k: v for k, v in groups.items() if len(v) >= 30}
    assert len(bursts) == manifest["scenarios"]["fractioning"]["bursts"] == 3
    assert len({pos for pos, _ in bursts}) == 3
    for stamps in bursts.values():
        assert max(stamps) - min(stamps) < timedelta(minutes=2)
    assert manifest["scenarios"]["fractioning"]["rows"] == 90


def test_regional_drop_removes_rows_only_in_the_target_month(
    all_run: tuple[Path, dict[str, Any]], none_run: tuple[Path, dict[str, Any]]
) -> None:
    stats = all_run[1]["scenarios"]["regional_drop"]
    assert stats["month"] == "2026-09"
    assert 0 < stats["rows"] <= stats["candidate_rows"]
    # Os demais cenários preservam o total: a diferença contra `none` é a queda regional.
    assert none_run[1]["counts"]["recharges"] - all_run[1]["counts"]["recharges"] == stats["rows"]


def test_regional_drop_alone_is_about_fourteen_percent(tmp_path: Path) -> None:
    clean = _generate(tmp_path / "a", "none", rows=400_000)
    dropped = _generate(tmp_path / "b", "regional_drop", rows=400_000)
    stats = dropped["scenarios"]["regional_drop"]
    assert clean["counts"]["recharges"] - dropped["counts"]["recharges"] == stats["rows"]
    assert 0.08 <= stats["rows"] / stats["candidate_rows"] <= 0.20


def test_manifest_sha256_matches_files(all_run: tuple[Path, dict[str, Any]]) -> None:
    out, manifest = all_run
    files = manifest["files"]
    assert "distributors/distributors.parquet" in files
    assert "pos/pos.parquet" in files
    assert "municipalities/municipalities.csv" in files
    assert manifest["counts"]["municipalities"] == 5570
    on_disk = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert set(files) == on_disk - {"_manifest.json"}
    for name, entry in files.items():
        assert entry["sha256"] == sha256_file(out / name)


def test_same_seed_same_manifest(tmp_path: Path, all_run: tuple[Path, dict[str, Any]]) -> None:
    again = _generate(tmp_path / "again", "all")
    assert again == all_run[1]
    assert (tmp_path / "again" / MANIFEST_NAME).read_bytes() == (
        all_run[0] / MANIFEST_NAME
    ).read_bytes()


def test_single_scenario_only_injects_that_scenario(tmp_path: Path) -> None:
    manifest = _generate(tmp_path / "one", "null_pos")
    assert set(manifest["scenarios"]) == {"null_pos"}
    assert manifest["flags"]["scenarios"] == ["null_pos"]
    assert manifest["counts"]["recharges"] == ROWS
