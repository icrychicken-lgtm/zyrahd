"""Kurzzeit-Cache für Rollen und Kanäle vom Discord-Server."""

from __future__ import annotations

import time
from typing import Any, Optional

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL = 30.0  # Sekunden


def get_cached(key: str) -> Optional[Any]:
    item = _CACHE.get(key)
    if not item:
        return None
    expires, value = item
    if time.time() > expires:
        _CACHE.pop(key, None)
        return None
    return value


def set_cached(key: str, value: Any, ttl: float = _TTL) -> Any:
    _CACHE[key] = (time.time() + ttl, value)
    return value


def invalidate(prefix: str = "") -> None:
    if not prefix:
        _CACHE.clear()
        return
    for key in list(_CACHE.keys()):
        if key.startswith(prefix):
            _CACHE.pop(key, None)
