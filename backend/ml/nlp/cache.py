"""Cache helper for NLP results."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

try:
    from redis import Redis
except ImportError:  # pragma: no cover - optional dependency
    Redis = None  # type: ignore[assignment]


class IntentCache:
    """Cache NLP predictions in Redis with an in-memory fallback."""

    def __init__(self, redis_url: str | None = None, ttl_seconds: int = 24 * 60 * 60, namespace: str = "nlp:intent:v1") -> None:
        self.ttl_seconds = ttl_seconds
        self.namespace = namespace.strip() or "nlp:intent:v1"
        self._memory_store: dict[str, str] = {}
        self._redis = None
        self._logger = logging.getLogger(__name__)

        if redis_url and Redis is not None:
            try:
                self._redis = Redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
                self._logger.info("IntentCache connected to Redis at %s with namespace %s", redis_url, self.namespace)
            except Exception:
                self._redis = None
                self._logger.warning("IntentCache falling back to in-memory store; Redis unavailable at %s", redis_url)
        else:
            self._logger.info("IntentCache using in-memory store with namespace %s", self.namespace)

    def _make_key(self, query: str) -> str:
        digest = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()
        return f"{self.namespace}:{digest}"

    def get(self, query: str) -> dict[str, Any] | None:
        key = self._make_key(query)

        if self._redis is not None:
            payload = self._redis.get(key)
            if payload:
                return json.loads(payload)

        payload = self._memory_store.get(key)
        if payload:
            return json.loads(payload)

        return None

    def set(self, query: str, value: dict[str, Any]) -> None:
        self.set_with_ttl(query, value, self.ttl_seconds)

    def set_with_ttl(self, query: str, value: dict[str, Any], ttl_seconds: int) -> None:
        key = self._make_key(query)
        payload = json.dumps(value, ensure_ascii=False)

        if self._redis is not None:
            self._redis.setex(key, ttl_seconds, payload)
            return

        self._memory_store[key] = payload

    @property
    def mode(self) -> str:
        return "redis" if self._redis is not None else "memory"

    def clear(self) -> None:
        if self._redis is not None:
            for key in self._redis.scan_iter(f"{self.namespace}:*"):
                self._redis.delete(key)

        self._memory_store.clear()
