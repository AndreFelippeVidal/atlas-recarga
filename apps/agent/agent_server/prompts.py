"""Carrega o system prompt versionado (SPEC-005 §4): `prompts/<prompt_version>.md`.

Sem imports pesados: testado no CI sem mlflow nem langchain.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PromptError(ValueError):
    """Versão de prompt inválida ou sem arquivo."""


def load_prompt(version: str, directory: Path = PROMPTS_DIR) -> str:
    # A versão vira nome de arquivo: só caracteres simples, sem `/` nem `..` (sem path traversal).
    if not _VERSION.fullmatch(version) or ".." in version:
        raise PromptError(f"prompt_version inválida: {version!r}")
    path = directory / f"{version}.md"
    if not path.is_file():
        raise PromptError(f"não existe {path.name} em {directory}")
    return path.read_text(encoding="utf-8").strip()


def prompt_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def published_hashes(directory: Path = PROMPTS_DIR) -> dict[str, str]:
    """Versão -> sha256 do texto, em `prompts/MANIFEST.json`.

    Um prompt publicado não se edita (ele é o que o gate de avaliação e os traces nomeiam): mudou o
    texto, crie `v2.md` e acrescente a linha no manifesto. O teste confere os dois lados.
    """
    data = json.loads((directory / "MANIFEST.json").read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}
