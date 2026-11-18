"""Cada teste começa com um limitador novo e sem MLflow (SPEC-006 §6)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from atlas_mcp import observability, server


@pytest.fixture(autouse=True)
def fresh_observer(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(server, "observer", observability.Observer(spans=observability._noop_span))
    yield
