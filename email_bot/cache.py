"""Simple in‑memory cache with TTL and thread safety."""

import time
import threading
from typing import Any, Optional

class TTLCache:
    """Generic cache with per‑key TTL."""

    def __init__(self, default_ttl: int = 300):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        """Return cached value if fresh, else None."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            value, expiry = entry
            if time.time() > expiry:
                del self._cache[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Store value with optional TTL (seconds)."""
        ttl = ttl or self.default_ttl
        with self._lock:
            self._cache[key] = (value, time.time() + ttl)

    def invalidate(self, key: str):
        """Remove a key from cache."""
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()