import csv
import hashlib
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from atlas_cli.entities import generate_distributors, generate_pos, month_window
from atlas_cli.exit_codes import ExitCode
from atlas_cli.geo import UF_NEIGHBORS
from atlas_cli.main import app
from atlas_cli.reference import REFERENCE_ENV, load_municipalities
from typer.testing import CliRunner

REPO = Path(__file__).resolve().parents[2]
REFERENCE = REPO / "data" / "reference" / "municipalities_ibge.csv"
WINDOW = month_window(date(2026, 11, 1), 12)
runner = CliRunner()


@pytest.fixture(scope="module")
def municipalities():  # type: ignore[no-untyped-def]
    return load_municipalities(REFERENCE)


@pytest.fixture(scope="module")
def entities(municipalities):  # type: ignore[no-untyped-def]
    dist = generate_distributors(42, 40, municipalities, WINDOW)
    return dist, generate_pos(42, 5_000, municipalities, dist, WINDOW)


def test_month_window() -> None:
    assert WINDOW.start == date(2025, 11, 1)
    assert WINDOW.end == date(2026, 10, 31)
    assert month_window(date(2026, 1, 1), 1).end == date(2025, 12, 31)


def test_uf_graph_is_symmetric_and_connected() -> None:
    assert len(UF_NEIGHBORS) == 27
    for uf, neighbors in UF_NEIGHBORS.items():
        for other in neighbors:
            assert uf in UF_NEIGHBORS[other]
    seen, stack = set(), ["SP"]
    while stack:
        uf = stack.pop()
        if uf not in seen:
            seen.add(uf)
            stack.extend(UF_NEIGHBORS[uf])
    assert len(seen) == 27


def test_invariant_3_every_municipality_exists_in_reference(entities) -> None:  # type: ignore[no-untyped-def]
    with REFERENCE.open(encoding="utf-8") as f:
        codes = {r["municipality_ibge_code"] for r in csv.DictReader(f)}
    pos_codes = entities[1]["municipality_ibge_code"].to_pylist()
    assert set(pos_codes) <= codes
    assert all(len(c) == 7 for c in pos_codes)


def test_invariant_4_all_27_ufs_have_a_pos(entities, municipalities) -> None:  # type: ignore[no-untyped-def]
    uf_of = dict(zip(municipalities.code, municipalities.uf, strict=True))
    ufs = {uf_of[c] for c in entities[1]["municipality_ibge_code"].to_pylist()}
    assert len(ufs) == 27


def test_pos_fk_and_served_ufs(entities, municipalities) -> None:  # type: ignore[no-untyped-def]
    dist, pos = entities
    uf_of = dict(zip(municipalities.code, municipalities.uf, strict=True))
    for dist_id, code in zip(
        pos["distributor_id"].to_pylist(), pos["municipality_ibge_code"].to_pylist(), strict=True
    ):
        assert uf_of[code] in dist.served_ufs[dist_id]
    assert all(1 <= len(u) <= 4 for u in dist.served_ufs.values())


def test_served_ufs_are_contiguous(entities) -> None:  # type: ignore[no-untyped-def]
    for ufs in entities[0].served_ufs.values():
        seen, stack = set(), [ufs[0]]
        while stack:
            uf = stack.pop()
            if uf not in seen:
                seen.add(uf)
                stack.extend(n for n in UF_NEIGHBORS[uf] if n in ufs)
        assert seen == set(ufs)


def test_regional_prepaid_weight_shapes_density(municipalities) -> None:  # type: ignore[no-untyped-def]
    """PDVs por habitante: N deve ficar perto de 1,4/0,8 = 1,75x o de S (SPEC-001 §4)."""
    dist = generate_distributors(42, 40, municipalities, WINDOW)
    pos = generate_pos(42, 20_000, municipalities, dist, WINDOW)
    region_of: dict[str, str] = {}
    with REFERENCE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        region_of[r["municipality_ibge_code"]] = r["region"]
    population: Counter[str] = Counter()
    for r in rows:
        population[r["region"]] += int(r["population"])
    count = Counter(region_of[c] for c in pos["municipality_ibge_code"].to_pylist())
    density = {k: count[k] / population[k] for k in population}
    assert 1.5 < density["N"] / density["S"] < 2.0
    assert 1.3 < density["NE"] / density["SE"] < 1.65  # esperado 1,3/0,9 = 1,44


def test_pos_type_mix_and_closed_share(entities) -> None:  # type: ignore[no-untyped-def]
    pos = entities[1]
    mix = Counter(pos["pos_type"].to_pylist())
    assert abs(mix["grocery"] / 5_000 - 0.30) < 0.03
    closed = [d for d in pos["closed_date"].to_pylist() if d is not None]
    assert len(closed) == 150
    assert all(WINDOW.start <= d <= WINDOW.end for d in closed)
    assert all(o < WINDOW.start for o in pos["opened_date"].to_pylist())


def test_ids_are_sequential(entities) -> None:  # type: ignore[no-untyped-def]
    assert entities[0].table["distributor_id"][0].as_py() == "DST-0001"
    assert entities[1]["pos_id"][4999].as_py() == "POS-005000"


def test_small_pos_count_is_best_effort(municipalities) -> None:  # type: ignore[no-untyped-def]
    dist = generate_distributors(1, 3, municipalities, WINDOW)
    assert generate_pos(1, 10, municipalities, dist, WINDOW).num_rows == 10


def _sha_tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_generate_same_seed_same_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REFERENCE_ENV, str(REFERENCE))
    args = [
        "generate",
        "--rows",
        "1000",
        "--end-month",
        "2026-11",
        "--pos",
        "500",
        "--distributors",
        "30",
    ]
    a, b = tmp_path / "a", tmp_path / "b"
    assert runner.invoke(app, [*args, "--out", str(a)]).exit_code == 0
    assert runner.invoke(app, [*args, "--out", str(b)]).exit_code == 0
    assert _sha_tree(a) == _sha_tree(b)
    entity_files = {"distributors/distributors.parquet", "pos/pos.parquet"}
    assert entity_files <= set(_sha_tree(a))
    c = tmp_path / "c"
    assert runner.invoke(app, [*args, "--seed", "7", "--out", str(c)]).exit_code == 0
    assert _sha_tree(a) != _sha_tree(c)


def test_generate_csv_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REFERENCE_ENV, str(REFERENCE))
    result = runner.invoke(
        app,
        [
            "generate",
            "--rows",
            "1000",
            "--end-month",
            "2026-11",
            "--format",
            "csv",
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert (tmp_path / "pos" / "pos.csv").is_file()


def test_generate_missing_reference_exits_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "nope.csv"
    monkeypatch.setenv(REFERENCE_ENV, str(missing))
    result = runner.invoke(app, ["generate", "--out", str(tmp_path / "out")])
    assert result.exit_code == ExitCode.REFERENCE_DATA_INVALID
    assert str(missing) in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["--pos", "0"],
        ["--end-month", "2026-13"],
        ["--format", "xlsx"],
        ["--months", "0"],
        ["--seed", "-1"],
    ],
)
def test_generate_invalid_flag_exits_2(args: list[str], tmp_path: Path) -> None:
    result = runner.invoke(app, ["generate", *args, "--out", str(tmp_path)])
    assert result.exit_code == ExitCode.INVALID_FLAG
