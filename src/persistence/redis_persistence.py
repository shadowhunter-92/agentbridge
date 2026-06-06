"""
Persistence Layer - Redis Integration
=====================================

Redis-based persistence for sessions, translation history, and state management.

Author: MiniMax Agent
"""

import json
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum

import redis.asyncio as redis


class CacheStrategy(str, Enum):
    """Cache strategies."""
    LRU = "lru"
    LFU = "lfu"
    TTL = "ttl"


@dataclass
class TranslationRecord:
    """Translation history record."""
    id: str
    source_protocol: str
    target_protocol: str
    source_data: Dict
    target_data: Dict
    duration_ms: float
    status: str  # success, partial, failed
    endpoint_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict = field(default_factory=dict)


class RedisPersistence:
    """
    Redis-based persistence layer for Agent Bridge.
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self._connected = False

    async def connect(self):
        """Test and establish Redis connection."""
        try:
            await self.redis.ping()
            self._connected = True
            return True
        except Exception:
            self._connected = False
            return False

    async def is_connected(self) -> bool:
        """Check if Redis is connected."""
        if not self._connected:
            return False
        try:
            await self.redis.ping()
            return True
        except:
            self._connected = False
            return False

    # Translation History
    async def store_translation(self, record: TranslationRecord) -> bool:
        """
        Store translation record in history.

        Args:
            record: TranslationRecord to store

        Returns:
            True if stored successfully
        """
        try:
            key = f"translation:{record.id}"
            data = json.dumps(asdict(record), ensure_ascii=False, default=str)

            await self.redis.set(key, data)
            await self.redis.expire(key, 86400 * 7)  # 7 days TTL

            # Add to user's history list
            user_id = record.metadata.get("user_id", "anonymous")
            await self.redis.lpush(f"translations:user:{user_id}", record.id)
            await self.redis.expire(f"translations:user:{user_id}", 86400 * 30)  # 30 days

            return True
        except Exception as e:
            print(f"Failed to store translation: {e}")
            return False

    async def get_translation(self, translation_id: str) -> Optional[TranslationRecord]:
        """Get translation record by ID."""
        try:
            key = f"translation:{translation_id}"
            data = await self.redis.get(key)

            if data:
                return TranslationRecord(**json.loads(data))
            return None
        except Exception:
            return None

    async def get_user_translations(self, user_id: str, limit: int = 100) -> List[TranslationRecord]:
        """Get translation history for a user."""
        try:
            translation_ids = await self.redis.lrange(f"translations:user:{user_id}", 0, limit - 1)

            records = []
            for tid in translation_ids:
                record = await self.get_translation(tid)
                if record:
                    records.append(record)

            return records
        except Exception:
            return []

    # Endpoint State
    async def store_endpoint_state(self, endpoint_id: str, state: Dict) -> bool:
        """Store endpoint state."""
        try:
            key = f"endpoint:state:{endpoint_id}"
            await self.redis.hset(key, mapping={k: json.dumps(v) for k, v in state.items()})
            await self.redis.expire(key, 3600)  # 1 hour TTL
            return True
        except Exception:
            return False

    async def get_endpoint_state(self, endpoint_id: str) -> Optional[Dict]:
        """Get endpoint state."""
        try:
            key = f"endpoint:state:{endpoint_id}"
            data = await self.redis.hgetall(key)

            if data:
                return {k: json.loads(v) for k, v in data.items()}
            return None
        except Exception:
            return None

    async def update_endpoint_health(self, endpoint_id: str, is_healthy: bool, latency_ms: float):
        """Update endpoint health metrics."""
        try:
            key = f"endpoint:health:{endpoint_id}"

            await self.redis.hset(key, mapping={
                "is_healthy": str(is_healthy),
                "latency_ms": str(latency_ms),
                "last_check": str(time.time())
            })

            # Add to health history (last 100 checks)
            await self.redis.lpush(f"endpoint:health:history:{endpoint_id}",
                                   json.dumps({"healthy": is_healthy, "latency": latency_ms, "time": time.time()}))
            await self.redis.ltrim(f"endpoint:health:history:{endpoint_id}", 0, 99)

            # Update aggregate stats
            await self.redis.hincrby(f"endpoint:stats:{endpoint_id}", "total_checks", 1)
            if is_healthy:
                await self.redis.hincrby(f"endpoint:stats:{endpoint_id}", "healthy_checks", 1)

        except Exception:
            pass

    # Session Management
    async def create_session(self, session_id: str, ttl: int = 3600) -> bool:
        """Create a new session."""
        try:
            key = f"session:{session_id}"
            await self.redis.hset(key, mapping={
                "created_at": str(time.time()),
                "active": "true"
            })
            await self.redis.expire(key, ttl)
            return True
        except Exception:
            return False

    async def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session data."""
        try:
            key = f"session:{session_id}"
            data = await self.redis.hgetall(key)

            if data:
                return {k.decode(): v.decode() for k, v in data.items()}
            return None
        except Exception:
            return None

    async def update_session(self, session_id: str, data: Dict) -> bool:
        """Update session data."""
        try:
            key = f"session:{session_id}"
            await self.redis.hset(key, mapping={k: json.dumps(v) for k, v in data.items()})
            await self.redis.expire(key, 3600)  # Reset TTL
            return True
        except Exception:
            return False

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        try:
            key = f"session:{session_id}"
            await self.redis.delete(key)
            return True
        except Exception:
            return False

    # Rate Limiting Support
    async def rate_limit_check(self, key: str, limit: int, window: int) -> tuple:
        """
        Check rate limit using sliding window.

        Args:
            key: Rate limit key (e.g., user_id or api_key)
            limit: Max requests allowed
            window: Time window in seconds

        Returns:
            Tuple of (allowed: bool, remaining: int, reset_at: int)
        """
        try:
            now = time.time()
            window_start = now - window

            # Remove old entries
            await self.redis.zremrangebyscore(f"ratelimit:{key}", 0, window_start)

            # Count current requests
            current = await self.redis.zcard(f"ratelimit:{key}")

            if current >= limit:
                oldest = await self.redis.zrange(f"ratelimit:{key}", 0, 0, withscores=True)
                reset_at = int(oldest[0][1] + window) if oldest else int(now + window)

                return False, 0, reset_at

            # Add current request
            await self.redis.zadd(f"ratelimit:{key}", {str(now): now})
            await self.redis.expire(f"ratelimit:{key}", window + 60)

            return True, limit - current - 1, int(now + window)

        except Exception:
            return True, limit, int(time.time() + window)

    # Cache Operations
    async def cache_set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set cache value."""
        try:
            cache_key = f"cache:{key}"
            await self.redis.set(cache_key, json.dumps(value, default=str), ex=ttl)
            return True
        except Exception:
            return False

    async def cache_get(self, key: str) -> Optional[Any]:
        """Get cache value."""
        try:
            cache_key = f"cache:{key}"
            data = await self.redis.get(cache_key)

            if data:
                return json.loads(data)
            return None
        except Exception:
            return None

    async def cache_delete(self, key: str) -> bool:
        """Delete cache value."""
        try:
            cache_key = f"cache:{key}"
            await self.redis.delete(cache_key)
            return True
        except Exception:
            return False

    # Analytics
    async def increment_counter(self, name: str, labels: Dict = None, by: float = 1) -> float:
        """Increment a counter."""
        try:
            key = f"counter:{name}"
            if labels:
                for k, v in sorted(labels.items()):
                    key += f":{k}={v}"

            return await self.redis.incrbyfloat(key, by)

        except Exception:
            return 0

    async def get_counter(self, name: str, labels: Dict = None) -> float:
        """Get counter value."""
        try:
            key = f"counter:{name}"
            if labels:
                for k, v in sorted(labels.items()):
                    key += f":{k}={v}"

            value = await self.redis.get(key)
            return float(value) if value else 0

        except Exception:
            return 0

    async def get_all_stats(self) -> Dict:
        """Get all statistics."""
        stats = {}

        # Get all counters
        keys = await self.redis.keys("counter:*")
        for key in keys:
            name = key.decode().replace("counter:", "")
            stats[name] = await self.get_counter(name)

        return stats

    # Cleanup
    async def cleanup_old_data(self, days: int = 7):
        """Clean up old translation records."""
        try:
            cutoff = time.time() - (days * 86400)

            # Find and delete old translation records
            keys = await self.redis.keys("translation:*")
            for key in keys:
                # Get creation time from record
                data = await self.redis.get(key)
                if data:
                    record = json.loads(data)
                    created = datetime.fromisoformat(record["created_at"]).timestamp()
                    if created < cutoff:
                        await self.redis.delete(key)

        except Exception as e:
            print(f"Cleanup error: {e}")


class InMemoryPersistence:
    """
    Fallback in-memory persistence when Redis is unavailable.
    """

    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._timestamps: Dict[str, float] = {}

    async def connect(self):
        return True

    async def is_connected(self):
        return True

    async def store_translation(self, record: TranslationRecord) -> bool:
        key = f"translation:{record.id}"
        self._data[key] = asdict(record)
        self._timestamps[key] = time.time()
        return True

    async def get_translation(self, translation_id: str) -> Optional[TranslationRecord]:
        key = f"translation:{translation_id}"
        if key in self._data:
            return TranslationRecord(**self._data[key])
        return None

    async def cache_set(self, key: str, value: Any, ttl: int = 300) -> bool:
        cache_key = f"cache:{key}"
        self._data[cache_key] = value
        self._timestamps[cache_key] = time.time() + ttl
        return True

    async def cache_get(self, key: str) -> Optional[Any]:
        cache_key = f"cache:{key}"
        if cache_key in self._data:
            if self._timestamps.get(cache_key, 0) > time.time():
                return self._data[cache_key]
            else:
                del self._data[cache_key]
        return None

    def __getattr__(self, name):
        """Passthrough for other methods."""
        return lambda *args, **kwargs: None


async def create_persistence(redis_url: str = None) -> RedisPersistence:
    """
    Create persistence layer with Redis connection.

    Falls back to in-memory if Redis unavailable.
    """
    if redis_url:
        try:
            client = redis.from_url(redis_url, decode_responses=True)
            persistence = RedisPersistence(client)

            if await persistence.connect():
                return persistence
        except Exception:
            pass

    return InMemoryPersistence()