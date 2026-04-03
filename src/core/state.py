"""
TaskDeskr Voice Core — Call State Manager
==========================================
Provides a Redis-backed persistent store for per-call state.
Falls back to an in-memory dict if Redis is unavailable, so the
service degrades gracefully rather than crashing.

Each call's state is stored as a JSON-serialised hash in Redis under
the key  ``call:{call_id}``  with a TTL of 2 hours (7200 s).

Usage
-----
    from src.core.state import call_state

    # Write
    await call_state.set(call_id, {"contact_id": "abc", "phone": "+1..."})

    # Read
    state = await call_state.get(call_id)

    # Update a subset of keys
    await call_state.update(call_id, {"opportunity_id": "xyz"})

    # Delete (end of call)
    await call_state.delete(call_id)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.core.config import settings

logger = logging.getLogger(__name__)

# TTL for each call's state in Redis (2 hours)
_CALL_TTL = 7200

# ─────────────────────────────────────────────────────────────────────────────
# Redis client — lazy-initialised once on first use
# ─────────────────────────────────────────────────────────────────────────────
_redis_client = None
_redis_available = False


async def _get_redis():
    """Return the Redis client, initialising it on first call."""
    global _redis_client, _redis_available
    if _redis_client is not None:
        return _redis_client if _redis_available else None

    redis_url = settings.REDIS_URL
    if not redis_url:
        logger.warning("REDIS_URL not configured — using in-memory fallback")
        _redis_available = False
        return None

    try:
        import redis.asyncio as aioredis  # type: ignore

        _redis_client = aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        # Ping to verify connectivity
        await _redis_client.ping()
        _redis_available = True
        logger.info("Redis connected", extra={"url": redis_url[:30]})
    except Exception as exc:
        logger.warning(
            "Redis unavailable — falling back to in-memory state",
            extra={"error": str(exc)},
        )
        _redis_available = False
        _redis_client = None

    return _redis_client if _redis_available else None


# ─────────────────────────────────────────────────────────────────────────────
# In-memory fallback
# ─────────────────────────────────────────────────────────────────────────────
_memory_store: dict[str, dict[str, Any]] = {}


def _key(call_id: str) -> str:
    return f"call:{call_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
class CallStateManager:
    """Async key-value store for per-call state, backed by Redis with memory fallback."""

    async def get(self, call_id: str) -> dict[str, Any]:
        """Return the full state dict for a call (empty dict if not found)."""
        r = await _get_redis()
        if r:
            try:
                raw = await r.get(_key(call_id))
                return json.loads(raw) if raw else {}
            except Exception as exc:
                logger.error("Redis GET error", extra={"call_id": call_id, "error": str(exc)})
        return _memory_store.get(call_id, {})

    async def set(self, call_id: str, state: dict[str, Any]) -> None:
        """Overwrite the full state dict for a call."""
        r = await _get_redis()
        if r:
            try:
                await r.set(_key(call_id), json.dumps(state), ex=_CALL_TTL)
                return
            except Exception as exc:
                logger.error("Redis SET error", extra={"call_id": call_id, "error": str(exc)})
        _memory_store[call_id] = state

    async def update(self, call_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Merge ``updates`` into the existing state and return the new full state."""
        state = await self.get(call_id)
        state.update(updates)
        await self.set(call_id, state)
        return state

    async def delete(self, call_id: str) -> dict[str, Any]:
        """Remove and return the state for a call (returns empty dict if not found)."""
        r = await _get_redis()
        if r:
            try:
                raw = await r.get(_key(call_id))
                state = json.loads(raw) if raw else {}
                await r.delete(_key(call_id))
                return state
            except Exception as exc:
                logger.error("Redis DELETE error", extra={"call_id": call_id, "error": str(exc)})
        return _memory_store.pop(call_id, {})

    async def exists(self, call_id: str) -> bool:
        """Return True if state exists for this call."""
        r = await _get_redis()
        if r:
            try:
                return bool(await r.exists(_key(call_id)))
            except Exception as exc:
                logger.error("Redis EXISTS error", extra={"call_id": call_id, "error": str(exc)})
        return call_id in _memory_store


# Singleton instance used across the entire application
call_state = CallStateManager()
