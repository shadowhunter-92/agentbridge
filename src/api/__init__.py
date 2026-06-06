"""
API package.

Note: we intentionally do NOT eagerly import the legacy `api.app` here, so that importing
the meta-bridge control plane (`src.api.control_plane`) does not pull in the legacy
redis/engine stack. Import what you need explicitly:
    from src.api.control_plane import app   # the shipped meta-bridge
    from src.api.api import app             # legacy MCP<->A2A app (deprecated)
"""
