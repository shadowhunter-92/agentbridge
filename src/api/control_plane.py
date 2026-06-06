"""
Meta-Bridge Control Plane (HTTP API) — the shipped product surface.

Exposes the two things that matter:
  - the N-protocol mesh: any-to-any translation across registered protocols
  - the governance plane: identities (DIDs), budgets, approvals, audit, and GOVERNED routing
    to live agents.

Security (fixed from the deep review):
  - OPERATOR endpoints (manage identities/budgets/approvals, read audit) require the admin key
    via `X-Admin-Key` (env `AGENTBRIDGE_ADMIN_KEY`; auto-generated + logged if unset).
  - AGENT endpoints (`/control/route`, `/control/authorize`) require a SIGNED request:
    headers `X-Agent-Id`, `X-Nonce`, `X-Signature` (Ed25519 over agent_id+nonce+body).
  - Persistence: set `AGENTBRIDGE_DB=/path/to.db` for durable SQLite; default is in-memory.

Run:  uvicorn src.api.control_plane:app    (docs at /docs)
"""

import logging
import os
import secrets
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel, Field

from ..protocols import default_registry
from ..governance import (
    AgentIdentity, IdentityRegistry, BudgetManager, Budget, ApprovalQueue,
    PolicyEngine, AuditLog, GovernanceGateway, GovernanceError,
    RequestAuthenticator, InMemoryStore, SqliteStore,
)

logger = logging.getLogger("control_plane")

# --- admin key + persistence wiring --------------------------------------------------
ADMIN_KEY = os.getenv("AGENTBRIDGE_ADMIN_KEY") or secrets.token_hex(16)
if not os.getenv("AGENTBRIDGE_ADMIN_KEY"):
    logger.warning("AGENTBRIDGE_ADMIN_KEY not set; generated one for this run: %s", ADMIN_KEY)

_db = os.getenv("AGENTBRIDGE_DB")
store = SqliteStore(_db) if _db else InMemoryStore()

app = FastAPI(title="AgentBridge Meta-Bridge Control Plane", version="1.0.0")

registry = default_registry
identities = IdentityRegistry(store=store)
budgets = BudgetManager(store=store)
approvals = ApprovalQueue()
policy = PolicyEngine(identities, budgets, approvals=approvals)
audit = AuditLog(store=store)
gateway = GovernanceGateway(identities=identities, budgets=budgets, approvals=approvals,
                            policy=policy, audit=audit, registry=registry)
authenticator = RequestAuthenticator(identities)


# --- guards ---------------------------------------------------------------------------

def require_admin(x_admin_key: Optional[str] = Header(None)):
    if not x_admin_key or not secrets.compare_digest(x_admin_key, ADMIN_KEY):
        raise HTTPException(401, "admin key required (X-Admin-Key)")


async def authenticate_agent(request: Request) -> str:
    agent_id = request.headers.get("X-Agent-Id", "")
    nonce = request.headers.get("X-Nonce", "")
    signature = request.headers.get("X-Signature", "")
    body = await request.body()
    ok, reason = authenticator.authenticate(agent_id, nonce, body, signature)
    if not ok:
        raise HTTPException(401, f"agent auth failed: {reason}")
    return agent_id


# --- models ---------------------------------------------------------------------------

class TranslateBody(BaseModel):
    src: str
    dst: str
    wire: Dict[str, Any]


class IdentityBody(BaseModel):
    agent_id: str
    public_key_hex: Optional[str] = Field(None, description="register a client-owned key; "
                                          "if omitted the server generates one and returns it ONCE")


class BudgetBody(BaseModel):
    spend_limit: float = 100.0
    rate_limit: int = 1000
    window_seconds: int = 3600


# --- public: mesh translation (pure function, no governance) --------------------------

@app.get("/health")
def health():
    return {"status": "ok", "protocols": registry.protocols()}


@app.get("/control/protocols")
def list_protocols():
    return {"protocols": registry.protocols()}


@app.post("/control/translate/call")
def translate_call(body: TranslateBody):
    try:
        return {"wire": registry.translate_call(body.wire, body.src, body.dst)}
    except KeyError as e:
        raise HTTPException(400, str(e))


@app.post("/control/translate/result")
def translate_result(body: TranslateBody):
    try:
        return {"wire": registry.translate_result(body.wire, body.src, body.dst)}
    except KeyError as e:
        raise HTTPException(400, str(e))


# --- operator plane (admin-key) -------------------------------------------------------

@app.post("/control/identities")
def register_identity(body: IdentityBody, x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key)
    if body.public_key_hex:
        ident = identities.register_public_key(body.agent_id, body.public_key_hex)
        return {"agent_id": body.agent_id, "did": ident.did}
    # Server-generated: return the private key ONCE so the agent can sign thereafter.
    ident = AgentIdentity.generate(body.agent_id)
    identities.register(ident)
    return {"agent_id": body.agent_id, "did": ident.did,
            "private_key_hex": ident.private_key_hex,
            "note": "store this key now; it is not retrievable later"}


@app.post("/control/identities/{agent_id}/revoke")
def revoke_identity(agent_id: str, x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key)
    if not identities.revoke(agent_id):
        raise HTTPException(404, "unknown identity")
    return {"agent_id": agent_id, "revoked": True}


@app.get("/control/identities")
def list_identities(x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key)
    return {"identities": [
        {"agent_id": i["agent_id"], "did": "did:key:ed25519:" + i["public_key_hex"],
         "revoked": i.get("revoked", False)}
        for i in store.list_identities()
    ]}


@app.put("/control/budgets/{agent_id}")
def set_budget(agent_id: str, body: BudgetBody, x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key)
    budgets.set_budget(agent_id, Budget(spend_limit=body.spend_limit,
                                        rate_limit=body.rate_limit,
                                        window_seconds=body.window_seconds))
    return {"agent_id": agent_id, "spend_limit": body.spend_limit, "rate_limit": body.rate_limit}


@app.get("/control/budgets/{agent_id}")
def get_budget(agent_id: str, x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key)
    b = budgets.get(agent_id)
    return {"agent_id": agent_id, "spent": b.spent, "remaining": b.remaining(),
            "spend_limit": b.spend_limit, "rate_limit": b.rate_limit}


@app.post("/control/capabilities/sensitive")
def mark_sensitive(capability: str, x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key)
    approvals.mark_sensitive(capability)
    return {"capability": capability, "requires_approval": True}


@app.get("/control/approvals")
def list_pending(x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key)
    return {"pending": [vars(r) for r in approvals.pending()]}


@app.post("/control/approvals/{request_id}/approve")
def approve(request_id: str, x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key)
    if not approvals.approve(request_id):
        raise HTTPException(404, "no such pending request")
    return {"request_id": request_id, "status": "approved"}


@app.post("/control/approvals/{request_id}/deny")
def deny(request_id: str, x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key)
    if not approvals.deny(request_id):
        raise HTTPException(404, "no such pending request")
    return {"request_id": request_id, "status": "denied"}


@app.get("/control/audit")
def get_audit(x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key)
    return {
        "integrity_ok": audit.verify_integrity(),
        "entries": [
            {"seq": e.seq, "actor": e.actor, "decision": e.decision,
             "src": e.source_protocol, "dst": e.target_protocol,
             "capability": e.capability, "cost": e.cost, "reason": e.reason,
             "hash": e.entry_hash[:12]}
            for e in audit.entries()
        ],
    }


@app.get("/control/audit/export")
def export_audit(x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key)
    return {"jsonl": audit.export_jsonl()}


# --- agent plane (signed requests) ----------------------------------------------------

async def _invoke_target(dst_proto: str, dst_wire: Dict[str, Any],
                         target: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Invoke a live target if one is specified, else return the translated wire."""
    if not target:
        return {"translated_wire": dst_wire}
    from ..proxy import transport
    kind = target.get("kind")
    if kind == "mcp_stdio":
        params = dst_wire.get("params", {})
        res = await transport.call_mcp_tool(target["command"], target.get("args", []),
                                            params.get("name"), params.get("arguments", {}))
        return {"result": res}
    if kind == "a2a_http":
        canonical_text = dst_wire.get("history", [{}])[0]
        return {"result": await transport.send_a2a_message(target["base_url"],
                                                           str(dst_wire))}
    if kind == "acp_http":
        return {"result": await transport.call_acp_agent(target["base_url"],
                                                          target.get("agent_name", "agent"),
                                                          str(dst_wire))}
    raise HTTPException(400, f"unknown target kind '{kind}'")


@app.post("/control/route")
async def governed_route(request: Request):
    agent_id = await authenticate_agent(request)
    import json
    body = json.loads(await request.body() or b"{}")
    src, dst, wire = body.get("src"), body.get("dst"), body.get("wire")
    cost = float(body.get("cost", 1.0))
    target = body.get("target")
    if not (src and dst and wire is not None):
        raise HTTPException(400, "src, dst, wire required")

    async def _invoke(dst_wire):
        return await _invoke_target(dst, dst_wire, target)

    try:
        result = await gateway.route_call(agent_id=agent_id, src_proto=src, dst_proto=dst,
                                          src_wire=wire, invoke=_invoke, cost=cost)
        return {"decision": "allow", **result}
    except GovernanceError as e:
        detail = {"reason": str(e)}
        if e.approval_id:
            detail["approval_id"] = e.approval_id
        raise HTTPException(403, detail=detail)
    except KeyError as e:
        raise HTTPException(400, detail=str(e))


@app.post("/control/authorize")
async def authorize(request: Request):
    agent_id = await authenticate_agent(request)
    import json
    body = json.loads(await request.body() or b"{}")
    d = policy.authorize(agent_id=agent_id, capability=body.get("capability", ""),
                         cost=float(body.get("cost", 1.0)))
    return {"allowed": d.allowed, "reason": d.reason, "needs_approval": d.needs_approval}
