"""
db_cache.py — Thread-safe in-memory cache for PayrollPro
=========================================================
Caches workers, skill wages, attendance, units, and banks.
Invalidates on any write so data is always fresh after mutations.
"""

import threading
import time
from typing import Any, Optional


class _Cache:
    """Simple TTL key-value store, thread-safe."""

    def __init__(self, ttl: float = 30.0):
        self._data: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._data[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (value, time.monotonic())

    def invalidate(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._data.pop(k, None)
        self._bump_server_change()

    def invalidate_prefix(self, prefix: str) -> None:
        with self._lock:
            to_del = [k for k in self._data if k.startswith(prefix)]
            for k in to_del:
                del self._data[k]
        self._bump_server_change()

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def _bump_server_change(self) -> None:
        """Inform the background Flask server of local database modifications."""
        try:
            import sync_server
            sync_server._bump_change()
        except Exception:
            pass


# ── Global cache instance (imported by database.py) ───────────────────────────
cache = _Cache(ttl=60.0)
