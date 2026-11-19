"""Cache em memória por `(endpoint, params)` com TTL de 10 minutos (SPEC-007 §3; dados D-1)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

TTL_S = 600


class TTLCache:
    def __init__(self, ttl_s: float = TTL_S, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_s
        self._clock = clock
        self._items: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def get_or_set(self, key: tuple[Any, ...], compute: Callable[[], Any]) -> Any:
        """Devolve o valor em cache ou calcula. Falhas não entram no cache."""
        now = self._clock()
        hit = self._items.get(key)
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        value = compute()
        self._items[key] = (self._clock(), value)
        return value

    def refresh(self, key: tuple[Any, ...], compute: Callable[[], Any]) -> Any:
        """Recalcula e grava sem olhar o TTL. Se `compute` falhar, o valor antigo fica."""
        value = compute()
        self._items[key] = (self._clock(), value)
        return value

    def clear(self) -> None:
        self._items.clear()
