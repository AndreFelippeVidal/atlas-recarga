"""`upload` idempotente para o Volume UC (SPEC-001 §3).

A Files API não devolve sha256, então o `_manifest.json` enviado ao Volume é a fonte do hash
remoto: só vai o arquivo cujo sha256 difere do manifest remoto (ou que ele não cita). O manifest
sobe por último, então uma execução interrompida nunca declara arquivo que não chegou. Nunca apaga.
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from atlas_cli.manifest import MANIFEST_NAME, sha256_file
from atlas_cli.validate import ValidateError, load_manifest

DEFAULT_DEST = "/Volumes/atlas/raw/landing/"


class UploadError(Exception):
    """Falha ao falar com o Volume (exit 4)."""


class VolumeClient(Protocol):
    def read_text(self, path: str) -> str | None:
        """Conteúdo do arquivo remoto, ou `None` se ele não existe."""

    def upload(self, local: Path, path: str) -> None:
        """Envia `local` para `path`, sobrescrevendo."""


@dataclass(frozen=True)
class UploadResult:
    uploaded: tuple[str, ...]
    skipped: int


class DatabricksVolume:
    """`VolumeClient` sobre a Files API do databricks-sdk."""

    def __init__(self, profile: str) -> None:
        from databricks.sdk import WorkspaceClient

        self._client = WorkspaceClient(profile=profile)

    def read_text(self, path: str) -> str | None:
        from databricks.sdk.errors import NotFound

        try:
            response = self._client.files.download(path)
        except NotFound:
            return None
        if response.contents is None:
            return None
        return response.contents.read().decode("utf-8")

    def upload(self, local: Path, path: str) -> None:
        with local.open("rb") as handle:
            self._client.files.upload(path, handle, overwrite=True)


def _remote_hashes(text: str | None) -> dict[str, str]:
    if text is None:
        return {}
    try:
        files: dict[str, Any] = json.loads(text)["files"]
        return {name: entry["sha256"] for name, entry in files.items()}
    except (ValueError, KeyError, TypeError):
        print("aviso: manifest remoto ilegível; reenviando tudo.", file=sys.stderr)
        return {}


def upload_directory(out: Path, dest: str, client: VolumeClient) -> UploadResult:
    manifest = load_manifest(out)
    base = dest.rstrip("/")
    remote_text = client.read_text(f"{base}/{MANIFEST_NAME}")
    remote = _remote_hashes(remote_text)
    pending: list[str] = []
    skipped = 0
    for name, entry in manifest["files"].items():
        local = out / name
        if not local.is_file():
            raise ValidateError(f"{local} está no manifest mas não existe: rode `generate`.")
        if sha256_file(local) != entry["sha256"]:
            raise ValidateError(f"{local} difere do manifest: rode `atlas-cli validate`.")
        if remote.get(name) == entry["sha256"]:
            skipped += 1
        else:
            pending.append(name)
    try:
        for name in pending:
            client.upload(out / name, f"{base}/{name}")
        if pending or remote_text != (out / MANIFEST_NAME).read_text(encoding="utf-8"):
            client.upload(out / MANIFEST_NAME, f"{base}/{MANIFEST_NAME}")
    except Exception as exc:
        raise UploadError(f"falha ao enviar para {base}: {exc}") from exc
    return UploadResult(uploaded=tuple(pending), skipped=skipped)
