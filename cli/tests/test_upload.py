import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from atlas_cli.main import app
from atlas_cli.manifest import MANIFEST_NAME
from atlas_cli.upload import DatabricksVolume, UploadError, upload_directory
from atlas_cli.validate import ValidateError
from typer.testing import CliRunner

REPO = Path(__file__).resolve().parents[2]
ENV = {"ATLAS_REFERENCE_PATH": str(REPO / "data" / "reference" / "municipalities_ibge.csv")}
DEST = "/Volumes/atlas/raw/landing/"
runner = CliRunner()


class FakeVolume:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.fail_on: str | None = None

    def read_text(self, path: str) -> str | None:
        data = self.files.get(path)
        return None if data is None else data.decode("utf-8")

    def upload(self, local: Path, path: str) -> None:
        if self.fail_on and path.endswith(self.fail_on):
            raise RuntimeError("boom")
        self.files[path] = local.read_bytes()
        self.puts.append(path)


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("gen")
    args = ["generate", "--rows", "5000", "--pos", "300", "--months", "1"]
    args += ["--end-month", "2026-11", "--out", str(out)]
    result = runner.invoke(app, args, env=ENV)
    assert result.exit_code == 0, result.output
    return out


def test_first_upload_sends_everything_manifest_last(generated: Path) -> None:
    client = FakeVolume()
    result = upload_directory(generated, DEST, client)
    assert len(result.uploaded) > 0
    assert result.skipped == 0
    assert client.puts[-1] == f"/Volumes/atlas/raw/landing/{MANIFEST_NAME}"
    assert "/Volumes/atlas/raw/landing/pos/pos.parquet" in client.files


def test_repeated_upload_sends_nothing(generated: Path) -> None:
    client = FakeVolume()
    first = upload_directory(generated, DEST, client)
    client.puts.clear()
    second = upload_directory(generated, DEST, client)
    assert second.uploaded == ()
    assert second.skipped == len(first.uploaded)
    assert client.puts == []


def test_changed_file_is_resent(generated: Path) -> None:
    client = FakeVolume()
    upload_directory(generated, DEST, client)
    key = f"{DEST}pos/pos.parquet"
    # força hash remoto diferente do local
    remote = json.loads(client.files[f"{DEST}{MANIFEST_NAME}"])
    remote["files"]["pos/pos.parquet"]["sha256"] = "0" * 64
    client.files[f"{DEST}{MANIFEST_NAME}"] = json.dumps(remote).encode()
    client.puts.clear()
    result = upload_directory(generated, DEST, client)
    assert result.uploaded == ("pos/pos.parquet",)
    assert client.puts == [key, f"{DEST}{MANIFEST_NAME}"]


def test_failure_does_not_publish_manifest(generated: Path) -> None:
    client = FakeVolume()
    client.fail_on = "pos/pos.parquet"
    with pytest.raises(UploadError):
        upload_directory(generated, DEST, client)
    assert f"{DEST}{MANIFEST_NAME}" not in client.files


def test_local_file_changed_after_manifest_is_rejected(generated: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(generated, copy)
    (copy / "pos" / "pos.parquet").write_bytes(b"corrompido")
    with pytest.raises(ValidateError):
        upload_directory(copy, DEST, FakeVolume())


def test_dest_must_be_a_volume() -> None:
    result = runner.invoke(app, ["upload", "--profile", "x", "--dest", "/dados/x"])
    assert result.exit_code == 2


def test_corrupt_remote_manifest_resends_all(
    generated: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeVolume()
    client.files[f"{DEST}{MANIFEST_NAME}"] = b"{nao e json"
    result = upload_directory(generated, DEST, client)
    assert result.skipped == 0
    assert len(result.uploaded) > 0
    assert "ilegível" in capsys.readouterr().err


def test_manifest_resent_when_only_manifest_differs(generated: Path) -> None:
    client = FakeVolume()
    upload_directory(generated, DEST, client)
    key = f"{DEST}{MANIFEST_NAME}"
    remote = json.loads(client.files[key])
    remote["seed"] = 999
    client.files[key] = json.dumps(remote).encode()
    client.puts.clear()
    result = upload_directory(generated, DEST, client)
    assert result.uploaded == ()
    assert client.puts == [key]


def test_databricks_volume_maps_sdk_calls(tmp_path: Path) -> None:
    from databricks.sdk.errors import NotFound

    with patch("databricks.sdk.WorkspaceClient") as ws:
        files = ws.return_value.files
        volume = DatabricksVolume("p")
        ws.assert_called_once_with(profile="p")
        files.download.side_effect = NotFound("x")
        assert volume.read_text("/Volumes/a") is None
        files.download.side_effect = None
        files.download.return_value = MagicMock(contents=None)
        assert volume.read_text("/Volumes/a") is None
        files.download.return_value.contents = MagicMock()
        files.download.return_value.contents.read.return_value = "olá".encode()
        assert volume.read_text("/Volumes/a") == "olá"
        local = tmp_path / "f.bin"
        local.write_bytes(b"1")
        volume.upload(local, "/Volumes/a/f.bin")
        assert files.upload.call_args.args[0] == "/Volumes/a/f.bin"
        assert files.upload.call_args.kwargs == {"overwrite": True}


class _Boom:
    def __init__(self, profile: str) -> None:
        raise UploadError("sem rede")


def test_cli_happy_path_uses_env_profile(generated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeVolume()
    monkeypatch.setattr("atlas_cli.main.DatabricksVolume", lambda profile: client)
    env = {"ATLAS_DATABRICKS_PROFILE": "p"}
    args = ["upload", "--out", str(generated)]
    first = runner.invoke(app, args, env=env)
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, args, env=env)
    assert second.exit_code == 0
    assert "0 enviado(s)" in second.output


def test_cli_upload_failure_exits_4(generated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("atlas_cli.main.DatabricksVolume", _Boom)
    result = runner.invoke(app, ["upload", "--out", str(generated), "--profile", "p"])
    assert result.exit_code == 4


def test_cli_local_divergence_exits_2(
    generated: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(generated, copy)
    (copy / "pos" / "pos.parquet").write_bytes(b"x")
    monkeypatch.setattr("atlas_cli.main.DatabricksVolume", lambda profile: FakeVolume())
    result = runner.invoke(app, ["upload", "--out", str(copy), "--profile", "p"])
    assert result.exit_code == 2


def test_dest_rejects_parent_traversal() -> None:
    result = runner.invoke(app, ["upload", "--profile", "x", "--dest", "/Volumes/a/../b"])
    assert result.exit_code == 2
