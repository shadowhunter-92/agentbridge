"""
Middleware Module
=================

API authentication and rate limiting middleware.

Author: MiniMax Agent
"""

from .auth import (
    AuthService,
    APIKey,
    RateLimitResult,
    RateLimitStrategy,
    get_current_api_key,
    optional_api_key,
    api_key_header,
)

__all__ = [
    "AuthService",
    "APIKey",
    "RateLimitResult",
    "RateLimitStrategy",
    "get_current_api_key",
    "optional_api_key",
    "api_key_header",
]