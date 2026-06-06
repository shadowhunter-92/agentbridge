"""
Persistence Module
==================

Redis-based persistence for sessions, translation history, and state management.

Author: MiniMax Agent
"""

from .redis_persistence import (
    CacheStrategy,
    TranslationRecord,
    RedisPersistence,
    InMemoryPersistence,
    create_persistence,
)

__all__ = [
    "CacheStrategy",
    "TranslationRecord",
    "RedisPersistence",
    "InMemoryPersistence",
    "create_persistence",
]