import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from atlas_cli.exit_codes import ExitCode
from atlas_cli.main import app
from atlas_cli.manifest import MANIFEST_NAME, sha256_file
from typer.testing import CliRunner

REPO = Path(__file__).resolve().parents[2]
ENV = {"ATLAS_REFERENCE_PATH": str(REPO / "data" / "reference" / "municipalities_ibge.csv")}
runner = CliRunner()


def _generate(out: Path, scenarios: str, seed: int = 42, fmt: str = "parquet") -> None:
    result = runner.invoke(
        app,
        [
            "generate", "--rows", "20000", "--pos", "800", "--months", "2",
            "--end-month", "2026-11", "--scenarios", scenarios, "--seed", str(seed),
            "--format", fmt, "--out", str(out),
        ],
        env=ENV,
    )  # fmt: skip
    assert result.exit_code == 0, result.output


def _validate(out: Path) -> tuple[int, str]:
    result = runner.invoke(app, ["validate", "--out", str(out)], env=ENV)
    return result.exit_code, result.output


def _rewrite_manifest(out: Path) -> None:
    """Recalcula os sha256 depois de adulterar um arquivo, para isolar o invariante testado."""
    path = out / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for rel in manifest["files"]:
        manifest["files"][rel]["sha256"] = sha256_file(out / rel)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def clean(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("clean")
    _generate(out, "none")
    return out


@pytest.fixture
def copy_of_clean(clean: Path, tmp_path: Path) -> Path:
    out = tmp_path / "copy"
    shutil.copytree(clean, out)
    return out


def test_same_seed_same_sha256_in_every_file(tmp_path: Path, clean: Path) -> None:
    """SPEC-001 §6 invariante 1 e §7 critério 1."""
    _generate(tmp_path / "again", "all")
    _generate(tmp_path / "all", "all")
    first = json.loads((tmp_path / "again" / MANIFEST_NAME).read_text(encoding="utf-8"))
    second = json.loads((tmp_path / "all" / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert first["files"] == second["files"]
    assert first == second
    for rel, entry in first["files"].items():
        assert sha256_file(tmp_path / "again" / rel) == entry["sha256"]
        assert sha256_file(tmp_path / "all" / rel) == entry["sha256"]


def test_different_seed_changes_sha256(tmp_path: Path) -> None:
    _generate(tmp_path / "a", "none", seed=1)
    _generate(tmp_path / "b", "none", seed=2)
    a = json.loads((tmp_path / "a" / MANIFEST_NAME).read_text(encoding="utf-8"))["files"]
    b = json.loads((tmp_path / "b" / MANIFEST_NAME).read_text(encoding="utf-8"))["files"]
    assert a["pos/pos.parquet"] != b["pos/pos.parquet"]


def test_clean_run_passes(clean: Path) -> None:
    code, output = _validate(clean)
    assert code == 0, output
    assert "FALHA" not in output
    assert "[ok] invariante 2" in output
    assert "[pulado] invariante 4" in output  # 800 PDVs < tamanho padrão


def test_run_with_scenarios_passes_and_skips_invariant_2(tmp_path: Path) -> None:
    _generate(tmp_path / "all", "all")
    code, output = _validate(tmp_path / "all")
    assert code == 0, output
    assert "[pulado] invariante 2" in output


def test_csv_run_passes(tmp_path: Path) -> None:
    _generate(tmp_path / "csv", "none", fmt="csv")
    code, output = _validate(tmp_path / "csv")
    assert code == 0, output


def test_tampered_file_fails_on_sha256(copy_of_clean: Path) -> None:
    pos = copy_of_clean / "pos" / "pos.parquet"
    pos.write_bytes(pos.read_bytes() + b"x")
    code, output = _validate(copy_of_clean)
    assert code == ExitCode.VALIDATION_FAILED
    assert "sha256 difere: pos/pos.parquet" in output


def test_missing_and_extra_files_fail(copy_of_clean: Path) -> None:
    next((copy_of_clean / "recharges").glob("dt=*/part-0000.parquet")).unlink()
    (copy_of_clean / "stray.parquet").write_bytes(b"")
    code, output = _validate(copy_of_clean)
    assert code == ExitCode.VALIDATION_FAILED
    assert "ausente" in output
    assert "não listado: stray.parquet" in output


def _mutate_recharges(out: Path, column: str, value: object) -> None:
    path = next((out / "recharges").glob("dt=*/part-0000.parquet"))
    table = pq.read_table(path)
    idx = table.schema.get_field_index(column)
    values = table[column].to_pylist()
    values[0] = value
    table = table.set_column(
        idx, table.schema.field(column), pa.array(values, table.schema.field(column).type)
    )
    pq.write_table(table, path, compression="snappy")
    _rewrite_manifest(out)


def test_orphan_pos_fails_invariant_2(copy_of_clean: Path) -> None:
    _mutate_recharges(copy_of_clean, "pos_id", "POS-999999")
    code, output = _validate(copy_of_clean)
    assert code == ExitCode.VALIDATION_FAILED
    assert "órfão" in output


def test_null_pos_fails_invariant_2(copy_of_clean: Path) -> None:
    _mutate_recharges(copy_of_clean, "pos_id", None)
    code, output = _validate(copy_of_clean)
    assert code == ExitCode.VALIDATION_FAILED
    assert "nulos" in output


def test_duplicate_id_fails_invariant_2(copy_of_clean: Path) -> None:
    path = next((copy_of_clean / "recharges").glob("dt=*/part-0000.parquet"))
    table = pq.read_table(path)
    _mutate_recharges(copy_of_clean, "recharge_id", table["recharge_id"][1].as_py())
    code, output = _validate(copy_of_clean)
    assert code == ExitCode.VALIDATION_FAILED
    assert "duplicado" in output


def test_non_face_amount_fails_invariant_2(copy_of_clean: Path) -> None:
    from decimal import Decimal

    _mutate_recharges(copy_of_clean, "amount_brl", Decimal("12.34"))
    code, output = _validate(copy_of_clean)
    assert code == ExitCode.VALIDATION_FAILED
    assert "fora da face" in output


def test_unknown_municipality_fails_invariant_3(copy_of_clean: Path) -> None:
    path = copy_of_clean / "pos" / "pos.parquet"
    table = pq.read_table(path)
    codes = table["municipality_ibge_code"].to_pylist()
    codes[0] = "0000000"
    table = table.set_column(
        table.schema.get_field_index("municipality_ibge_code"),
        "municipality_ibge_code",
        pa.array(codes, pa.string()),
    )
    pq.write_table(table, path, compression="snappy")
    _rewrite_manifest(copy_of_clean)
    code, output = _validate(copy_of_clean)
    assert code == ExitCode.VALIDATION_FAILED
    assert "código desconhecido" in output


def test_total_outside_tolerance_fails_invariant_5(copy_of_clean: Path) -> None:
    path = copy_of_clean / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["flags"]["rows"] = 40_000
    path.write_text(json.dumps(manifest), encoding="utf-8")
    code, output = _validate(copy_of_clean)
    assert code == ExitCode.VALIDATION_FAILED
    assert "invariante 5" in output


@pytest.mark.parametrize(
    "value",
    ["123.456.789-09", "ana@example.com", "(11) 98765-4321", "+55 11 98765-4321", "11987654321"],
)
def test_pii_shaped_value_fails_invariant_6(copy_of_clean: Path, value: str) -> None:
    _mutate_recharges(copy_of_clean, "subscriber_id", value)
    code, output = _validate(copy_of_clean)
    assert code == ExitCode.VALIDATION_FAILED
    assert "invariante 6" in output
    assert "subscriber_id" in output


def test_synthetic_ids_are_not_pii(clean: Path) -> None:
    code, output = _validate(clean)
    assert code == 0, output
    assert "[ok] invariante 6" in output


def test_missing_manifest_is_invalid_flag(tmp_path: Path) -> None:
    code, output = _validate(tmp_path)
    assert code == ExitCode.INVALID_FLAG
    assert "atlas-cli generate" in output


def test_missing_reference_exits_3(clean: Path) -> None:
    result = runner.invoke(
        app, ["validate", "--out", str(clean)], env={"ATLAS_REFERENCE_PATH": "/nao/existe.csv"}
    )
    assert result.exit_code == ExitCode.REFERENCE_DATA_INVALID
