"""Redis client helper (queue, cache, OAuth state)."""

from __future__ import annotations

from functools import lru_cache

from redis import Redis

from app.core.config import settings


@lru_cache
def get_redis() -> Redis:
    """Return a cached Redis client (decode_responses on)."""
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3.0,
        socket_timeout=3.0,
    )
