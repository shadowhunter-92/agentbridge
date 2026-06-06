"""
AgentBridge — Main Entry Point (the Meta-Bridge control plane).

Launches the N-protocol mesh + governance control plane. The legacy MCP<->A2A app
(`src/api/api.py`) is deprecated and no longer the default entrypoint.

Env:
  PORT, HOST                  — bind address (default 0.0.0.0:8000)
  AGENTBRIDGE_ADMIN_KEY       — operator key for /control admin endpoints (auto-gen if unset)
  AGENTBRIDGE_DB              — path to a SQLite file for durable governance (default in-memory)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.api.control_plane import app, ADMIN_KEY  # noqa: E402

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    print(f"""
╔════════════════════════════════════════════════════════════════╗
║  AgentBridge — Meta-Bridge Control Plane                        ║
║  N-protocol mesh (MCP/A2A/ACP/OpenAI/Gemini/AGNTCY) + governance ║
║  API:  http://{host}:{port}     Docs: http://{host}:{port}/docs ║
╚════════════════════════════════════════════════════════════════╝
""")
    if not os.environ.get("AGENTBRIDGE_ADMIN_KEY"):
        print(f"[admin key for this run] X-Admin-Key: {ADMIN_KEY}")
    if not os.environ.get("AGENTBRIDGE_DB"):
        print("[persistence] in-memory (set AGENTBRIDGE_DB=/path/to.db for durable governance)")

    uvicorn.run(app, host=host, port=port, log_level="info")
