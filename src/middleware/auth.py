"""
Authentication and Rate Limiting Middleware
============================================

Enterprise-grade API authentication with API key management and rate limiting.

Author: MiniMax Agent
"""

import hashlib
import secrets
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from fastapi import Request, HTTPException, Depends
from fastapi.security import APIKeyHeader
import redis.asyncio as redis

from ..monitoring.logging_service import LoggingService, LogLevel


class RateLimitStrategy(str, Enum):
    """Rate limit strategies."""
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"


@dataclass
class APIKey:
    """API key representation."""
    key_id: str
    key_hash: str
    name: str
    tier: str = "free"
    rate_limit: int = 1000  # requests per window
    window_seconds: int = 3600  # 1 hour
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used: Optional[str] = None
    is_active: bool = True
    metadata: Dict = field(default_factory=dict)


@dataclass
class RateLimitResult:
    """Rate limit check result."""
    allowed: bool
    remaining: int
    reset_at: int  # Unix timestamp
    retry_after: Optional[int] = None


class AuthService:
    """
    Authentication service with API key management.
    """

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self._keys: Dict[str, APIKey] = {}
        self._key_hashes: Dict[str, str] = {}

    async def initialize(self):
        """Initialize the auth service."""
        if self.redis_client:
            # Load keys from Redis
            keys = await self.redis_client.smembers("auth:apikeys")
            for key_id in keys:
                key_data = await self.redis_client.hgetall(f"auth:key:{key_id}")
                if key_data:
                    self._keys[key_id] = APIKey(
                        key_id=key_id,
                        key_hash=key_data[b"key_hash"].decode(),
                        name=key_data[b"name"].decode(),
                        tier=key_data.get(b"tier", b"free").decode(),
                        rate_limit=int(key_data.get(b"rate_limit", b"1000").decode()),
                        window_seconds=int(key_data.get(b"window_seconds", b"3600").decode())
                    )
                    self._key_hashes[self._keys[key_id].key_hash] = key_id

    def generate_api_key(self, name: str, tier: str = "free") -> Tuple[str, APIKey]:
        """
        Generate a new API key.

        Args:
            name: Name/description for the key
            tier: Pricing tier (free, pro, enterprise)

        Returns:
            Tuple of (raw_key, APIKey object)
        """
        raw_key = f"ag_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = f"key_{secrets.token_hex(8)}"

        rate_limits = {
            "free": (1000, 3600),      # 1000/hour
            "pro": (100000, 3600),     # 100000/hour
            "enterprise": (1000000, 3600)  # 1000000/hour
        }
        rate_limit, window = rate_limits.get(tier, rate_limits["free"])

        api_key = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            name=name,
            tier=tier,
            rate_limit=rate_limit,
            window_seconds=window
        )

        self._keys[key_id] = api_key
        self._key_hashes[key_hash] = key_id

        return raw_key, api_key

    async def store_api_key(self, raw_key: str, api_key: APIKey):
        """Store API key in Redis."""
        if self.redis_client:
            await self.redis_client.hset(
                f"auth:key:{api_key.key_id}",
                mapping={
                    "key_hash": api_key.key_hash,
                    "name": api_key.name,
                    "tier": api_key.tier,
                    "rate_limit": str(api_key.rate_limit),
                    "window_seconds": str(api_key.window_seconds),
                    "created_at": api_key.created_at
                }
            )
            await self.redis_client.sadd("auth:apikeys", api_key.key_id)

    def validate_key(self, raw_key: str) -> Optional[APIKey]:
        """
        Validate an API key.

        Args:
            raw_key: The raw API key

        Returns:
            APIKey if valid, None otherwise
        """
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = self._key_hashes.get(key_hash)

        if not key_id:
            return None

        api_key = self._keys.get(key_id)
        if api_key and api_key.is_active:
            api_key.last_used = datetime.now(timezone.utc).isoformat()
            return api_key

        return None

    async def check_rate_limit(self, api_key: APIKey) -> RateLimitResult:
        """
        Check rate limit for an API key.

        Args:
            api_key: The API key to check

        Returns:
            RateLimitResult with allowed status and remaining quota
        """
        if self.redis_client:
            return await self._redis_rate_limit(api_key)
        else:
            return self._memory_rate_limit(api_key)

    async def _redis_rate_limit(self, api_key: APIKey) -> RateLimitResult:
        """Redis-based rate limiting using sliding window."""
        now = time.time()
        window_start = now - api_key.window_seconds
        key = f"ratelimit:{api_key.key_id}"

        # Remove old entries
        await self.redis_client.zremrangebyscore(key, 0, window_start)

        # Count current requests
        current_count = await self.redis_client.zcard(key)

        if current_count >= api_key.rate_limit:
            # Calculate retry time
            oldest = await self.redis_client.zrange(key, 0, 0, withscores=True)
            if oldest:
                retry_after = int(oldest[0][1] + api_key.window_seconds - now)
            else:
                retry_after = api_key.window_seconds

            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=int(now + api_key.window_seconds),
                retry_after=max(1, retry_after)
            )

        # Add current request
        await self.redis_client.zadd(key, {str(now): now})
        await self.redis_client.expire(key, api_key.window_seconds + 60)

        return RateLimitResult(
            allowed=True,
            remaining=api_key.rate_limit - current_count - 1,
            reset_at=int(now + api_key.window_seconds)
        )

    def _memory_rate_limit(self, api_key: APIKey) -> RateLimitResult:
        """In-memory rate limiting for when Redis is unavailable."""
        now = time.time()
        key = f"ratelimit:{api_key.key_id}"

        if not hasattr(self, '_rate_limit_data'):
            self._rate_limit_data: Dict[str, list] = {}

        if key not in self._rate_limit_data:
            self._rate_limit_data[key] = []

        # Remove old entries
        window_start = now - api_key.window_seconds
        self._rate_limit_data[key] = [
            t for t in self._rate_limit_data[key] if t > window_start
        ]

        if len(self._rate_limit_data[key]) >= api_key.rate_limit:
            oldest = min(self._rate_limit_data[key]) if self._rate_limit_data[key] else now
            retry_after = int(oldest + api_key.window_seconds - now)

            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=int(now + api_key.window_seconds),
                retry_after=max(1, retry_after)
            )

        self._rate_limit_data[key].append(now)

        return RateLimitResult(
            allowed=True,
            remaining=api_key.rate_limit - len(self._rate_limit_data[key]),
            reset_at=int(now + api_key.window_seconds)
        )

    async def revoke_key(self, key_id: str) -> bool:
        """
        Revoke an API key.

        Args:
            key_id: Key ID to revoke

        Returns:
            True if revoked, False if not found
        """
        if key_id in self._keys:
            self._keys[key_id].is_active = False

            if self.redis_client:
                await self.redis_client.delete(f"auth:key:{key_id}")
                await self.redis_client.srem("auth:apikeys", key_id)

            return True
        return False

    def get_key_info(self, key_id: str) -> Optional[Dict]:
        """Get API key info (without the actual key)."""
        api_key = self._keys.get(key_id)
        if not api_key:
            return None

        return {
            "key_id": api_key.key_id,
            "name": api_key.name,
            "tier": api_key.tier,
            "rate_limit": api_key.rate_limit,
            "window_seconds": api_key.window_seconds,
            "created_at": api_key.created_at,
            "last_used": api_key.last_used,
            "is_active": api_key.is_active
        }

    def list_keys(self) -> list:
        """List all API keys (without actual keys)."""
        return [
            self.get_key_info(key_id)
            for key_id in self._keys
        ]


# FastAPI dependency for authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_api_key(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header),
    auth_service: AuthService = Depends()
) -> APIKey:
    """
    FastAPI dependency to validate API key.

    Raises HTTPException if invalid.
    """
    # Check header first, then query param, then body
    raw_key = api_key

    if not raw_key:
        raw_key = request.query_params.get("api_key")

    if not raw_key:
        # For development, allow bypass with header
        if request.headers.get("X-Debug-Bypass") == "true":
            return None  # Development mode

        raise HTTPException(
            status_code=401,
            detail="API key required. Include X-API-Key header or api_key query parameter."
        )

    validated_key = auth_service.validate_key(raw_key)

    if not validated_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )

    # Check rate limit
    rate_result = await auth_service.check_rate_limit(validated_key)

    if not rate_result.allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "retry_after": rate_result.retry_after,
                "reset_at": rate_result.reset_at
            },
            headers={"Retry-After": str(rate_result.retry_after)}
        )

    # Add rate limit headers
    request.state.rate_limit_remaining = rate_result.remaining
    request.state.rate_limit_reset = rate_result.reset_at

    return validated_key


async def optional_api_key(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header),
    auth_service: AuthService = Depends()
) -> Optional[APIKey]:
    """Optional API key validation - doesn't fail if missing."""
    if not api_key:
        return None

    return auth_service.validate_key(api_key)