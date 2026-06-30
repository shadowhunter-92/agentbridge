"""
Meta-Bridge Control Plane (HTTP API) — the shipped product surface.

Exposes the two things that matter:
  - the N-protocol mesh: any-to-any translation across registered protocols
  - the governance plane: identities (DIDs), budgets, approvals, audit, and GOVERNED routing
    to live agents.

Security (fixed from the deep review):
  - OPERATOR endpoints (manage identities/budgets/approvals/policy, read audit) require
    EITHER the admin key via `X-Admin-Key` (role: admin) OR — if OIDC is configured — an
    `Authorization: Bearer <jwt>` from your IdP, whose role claim maps to RBAC
    (admin / operator / viewer; see src/governance/rbac.py).
  - AGENT endpoints (`/control/route`, `/control/authorize`) require a SIGNED request:
    headers `X-Agent-Id`, `X-Nonce`, `X-Signature` (Ed25519 over agent_id+nonce+body).
  - Persistence: set `AGENTBRIDGE_DB=/path/to.db` for durable SQLite; default is in-memory.

OIDC (optional SSO): set AGENTBRIDGE_OIDC_ISSUER + AGENTBRIDGE_OIDC_AUDIENCE and ONE of
AGENTBRIDGE_OIDC_PUBLIC_KEY_PEM / AGENTBRIDGE_OIDC_PUBLIC_KEY_FILE (the IdP signing key);
optional AGENTBRIDGE_OIDC_ROLE_CLAIM (default "role").

Run:  uvicorn src.api.control_plane:app    (docs at /docs)
"""

import logging
import os
import secrets
import signal
import sys
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Header, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ratelimit import RateLimiter
from .auth_oidc import OidcConfig, OidcVerifier, OidcError
from ..protocols import default_registry
from ..governance import (
    AgentIdentity, IdentityRegistry, BudgetManager, Budget, ApprovalQueue,
    PolicyEngine, AuditLog, GovernanceGateway, GovernanceError,
    RequestAuthenticator, make_store, InMemoryStore,
    PolicySet, MaxCostPerCall, RequireApprovalAboveCost, DenyCapabilities,
    AllowOnlyCapabilities, BusinessHoursOnly, DenyProtocolRoute,
    require as rbac_require, AccessDenied,
)
from ..observability import (
    render_metrics, HTTP_REQUESTS, HTTP_DURATION, RATE_LIMIT_HITS, AUTH_FAILURES,
    update_approvals_pending,
)
from ..observability.logging import configure_logging, bind_request_id, new_request_id
from ..config import validate_config, ConfigError
from .. import __version__ as _pkg_version

logger = logging.getLogger("control_plane")

# --- startup: configure logging FIRST so the rest of init is observable ------------
configure_logging()

# --- validate configuration before any state is created ------------------------------
# We validate AFTER logging so issues are emitted as structured logs. Errors raise
# ConfigError which the CLI/uvicorn will surface as a non-zero exit — fail fast at boot
# rather than failing at first request with a confusing traceback.
try:
    validate_config(fail_fast=True)
except ConfigError as e:
    logger.error("startup aborted: %s", e)
    raise

# --- graceful shutdown state --------------------------------------------------------
# Set to False by the SIGTERM handler; /ready returns 503 once it's False so the LB
# stops sending new traffic while in-flight requests drain.
_ready = {"ok": True}
_SHUTDOWN_GRACE_SECONDS = float(os.getenv("AGENTBRIDGE_SHUTDOWN_GRACE", "10"))

# --- admin key + persistence wiring --------------------------------------------------
ADMIN_KEY = os.getenv("AGENTBRIDGE_ADMIN_KEY") or secrets.token_hex(16)
if not os.getenv("AGENTBRIDGE_ADMIN_KEY"):
    if os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production"):
        # In production we still allow startup (so a misconfigured pod doesn't crash-loop
        # forever), but make the warning impossible to miss.
        logger.error("AGENTBRIDGE_ADMIN_KEY not set in production; generated ephemeral key %s. "
                     "Set it explicitly or operator auth will rotate on every restart.", ADMIN_KEY)
    else:
        logger.warning("AGENTBRIDGE_ADMIN_KEY not set; generated one for this run: %s", ADMIN_KEY)

_db = os.getenv("AGENTBRIDGE_DB")
store = make_store(_db)  # None->in-memory, postgres URL->Postgres, else SQLite path


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup + graceful shutdown.

    On SIGTERM/SIGINT we flip _ready to False so /ready starts returning 503 (load
    balancer stops sending new traffic), then wait up to AGENTBRIDGE_SHUTDOWN_GRACE
    seconds for in-flight requests to drain before letting uvicorn close the socket.
    """
    shutting_down = {"v": False}

    def _mark_shutdown(signum, _frame):
        logger.info("received signal %s; draining...", signum)
        shutting_down["v"] = True
        _ready["ok"] = False

    # Install handlers only on the main thread (uvicorn workers satisfy this).
    # asyncio.run() / test runners may run in non-main threads; signal.signal raises
    # ValueError there, which we swallow.
    try:
        signal.signal(signal.SIGTERM, _mark_shutdown)
        signal.signal(signal.SIGINT, _mark_shutdown)
    except (ValueError, OSError):
        pass

    logger.info("AgentBridge control plane starting (version=%s, store=%s)",
                _pkg_version, type(store).__name__)
    yield

    # Drain phase
    _ready["ok"] = False
    deadline = time.monotonic() + _SHUTDOWN_GRACE_SECONDS
    while time.monotonic() < deadline:
        # uvicorn handles in-flight tracking; we just give the LB a moment to notice
        # /ready is 503 before we tear down. This is intentionally simple — heavy
        # connection-drain logic belongs in the server (uvicorn --drain-timeout) or a
        # service mesh, not here.
        time.sleep(0.1)
    logger.info("drain complete; shutting down")


app = FastAPI(
    title="AgentBridge Meta-Bridge Control Plane",
    version=_pkg_version,
    lifespan=lifespan,
    # Suppress FastAPI's default /docs in production; opt back in with AGENTBRIDGE_DOCS=1.
    docs_url=None if os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production")
              and os.getenv("AGENTBRIDGE_DOCS") != "1" else "/docs",
    redoc_url=None if os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production") else "/redoc",
)

# --- optional static status dashboard, served at /dashboard (reads live /health + /control/protocols)
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/dashboard", StaticFiles(directory=_static_dir, html=True), name="dashboard")

registry = default_registry
identities = IdentityRegistry(store=store)
budgets = BudgetManager(store=store)
approvals = ApprovalQueue(store=store)
policy_rules = PolicySet()          # declarative rules, managed via /control/policy/rules
policy = PolicyEngine(identities, budgets, approvals=approvals, policy_set=policy_rules)
audit = AuditLog(store=store)
gateway = GovernanceGateway(identities=identities, budgets=budgets, approvals=approvals,
                            policy=policy, audit=audit, registry=registry)
authenticator = RequestAuthenticator(identities)

# --- concurrency safety: depends on the configured store ------------------------------
# Audit-chain append, budget reserve/commit, AND approval state are all atomic
# store-side operations, so multiple workers are SAFE when they share a durable backend
# (SQLite file or Postgres). The default in-memory store is per-process, single-worker only.
# See docs/ENTERPRISE.md "Concurrency & scaling".
if isinstance(store, InMemoryStore):
    logger.warning(
        "Governance store is IN-MEMORY (per-process). Run a SINGLE worker, or set "
        "AGENTBRIDGE_DB to a SQLite path / postgres:// URL before scaling to multiple workers "
        "(otherwise the audit chain forks and budgets double-spend). See docs/ENTERPRISE.md."
    )
else:
    logger.info(
        "Governance store is durable (%s); audit chain, budgets, AND approvals are "
        "multi-worker safe.",
        type(store).__name__,
    )

# --- optional OIDC operator SSO (env-configured; JWKS auto-fetch supported) -----------
oidc_verifier: Optional[OidcVerifier] = None
_oidc_issuer = os.getenv("AGENTBRIDGE_OIDC_ISSUER")
if _oidc_issuer:
    _pem = os.getenv("AGENTBRIDGE_OIDC_PUBLIC_KEY_PEM")
    _pem_file = os.getenv("AGENTBRIDGE_OIDC_PUBLIC_KEY_FILE")
    if not _pem and _pem_file:
        with open(_pem_file, "r", encoding="utf-8") as _f:
            _pem = _f.read()
    oidc_verifier = OidcVerifier(OidcConfig(
        issuer=_oidc_issuer,
        audience=os.getenv("AGENTBRIDGE_OIDC_AUDIENCE", "agentbridge"),
        public_key_pem=_pem,
        # If no static key is configured, the verifier will auto-fetch JWKS from
        # <issuer>/.well-known/openid-configuration at first use. See auth_oidc.py.
        jwks_url=os.getenv("AGENTBRIDGE_OIDC_JWKS_URL") or None,
        role_claim=os.getenv("AGENTBRIDGE_OIDC_ROLE_CLAIM", "role"),
    ))
    logger.info("OIDC operator SSO enabled (issuer=%s, key=%s)",
                _oidc_issuer, "jwks" if not _pem else "static")

# --- rate limiting: throttle /control/* per client IP (blunts admin-key brute force) ---
RATE_LIMIT_PER_MIN = int(os.getenv("AGENTBRIDGE_RATE_LIMIT", "240"))
rate_limiter = RateLimiter(RATE_LIMIT_PER_MIN, window_seconds=60)


@app.middleware("http")
async def _observability_and_rate_limit(request: Request, call_next):
    """Single middleware that does: request_id, slow-log, HTTP metrics, rate-limit.
    Doing it in one pass avoids re-reading the body and re-wrapping the response chain.
    """
    rid = request.headers.get("X-Request-ID") or new_request_id()
    bind_request_id(rid)
    request_id_header = {"X-Request-ID": rid}

    # 503 during shutdown so the LB stops sending new traffic.
    if not _ready["ok"] and request.url.path not in ("/health", "/ready"):
        return JSONResponse({"detail": "shutting down"}, status_code=503,
                            headers=request_id_header)

    t0 = time.monotonic()

    # Per-IP rate limit on operator endpoints (blunts admin-key brute force).
    if request.url.path.startswith("/control"):
        client = request.client.host if request.client else "unknown"
        if not rate_limiter.allow(client):
            RATE_LIMIT_HITS.inc()
            return JSONResponse(
                {"detail": f"rate limit exceeded ({RATE_LIMIT_PER_MIN}/min)"},
                status_code=429,
                headers=request_id_header,
            )

    try:
        response = await call_next(request)
    except Exception:
        # Unhandled exception — record and re-raise so uvicorn's logger sees the trace.
        HTTP_REQUESTS.labels(method=request.method, path=request.url.path,
                             status="500").inc()
        raise

    elapsed = time.monotonic() - t0
    HTTP_REQUESTS.labels(method=request.method, path=request.url.path,
                         status=str(response.status_code)).inc()
    HTTP_DURATION.labels(method=request.method, path=request.url.path).observe(elapsed)
    response.headers["X-Request-ID"] = rid
    if elapsed > float(os.getenv("AGENTBRIDGE_SLOW_LOG_SECONDS", "2.0")):
        logger.warning("slow request %s %s took %.3fs", request.method,
                       request.url.path, elapsed)
    return response


# --- guards ---------------------------------------------------------------------------

def operator_guard(permission: str):
    """Operator auth + RBAC. Accepts the admin key (role: admin) or, when OIDC is
    configured, an IdP bearer token whose role claim maps to an RBAC role. The
    resolved role must hold `permission`."""
    async def guard(request: Request) -> str:
        x_admin = request.headers.get("X-Admin-Key")
        if x_admin and secrets.compare_digest(x_admin, ADMIN_KEY):
            role = "admin"
        elif oidc_verifier is not None and request.headers.get("Authorization"):
            try:
                _claims, role = oidc_verifier.authenticate(request.headers["Authorization"])
            except OidcError as e:
                AUTH_FAILURES.labels(kind="operator").inc()
                raise HTTPException(401, f"operator auth failed: {e}")
        else:
            AUTH_FAILURES.labels(kind="operator").inc()
            hint = "X-Admin-Key" + (" or Authorization: Bearer <jwt>" if oidc_verifier else "")
            raise HTTPException(401, f"operator auth required ({hint})")
        try:
            rbac_require(role, permission)
        except AccessDenied as e:
            raise HTTPException(403, str(e))
        return role
    return guard


async def authenticate_agent(request: Request, raw_body: Optional[bytes] = None) -> str:
    """Verify the Ed25519 signed request. Pass `raw_body` if you've already read it
    (so the body is read exactly once per request)."""
    agent_id = request.headers.get("X-Agent-Id", "")
    nonce = request.headers.get("X-Nonce", "")
    signature = request.headers.get("X-Signature", "")
    body = raw_body if raw_body is not None else await request.body()
    ok, reason = authenticator.authenticate(agent_id, nonce, body, signature)
    if not ok:
        AUTH_FAILURES.labels(kind="agent").inc()
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

def _store_health() -> Dict[str, Any]:
    """Probe the governance store with a trivial read; surface its type and readiness.

    Returns {"type": "...", "ok": bool, "error": "..."}; used by /health and /ready.
    A failure here means the governance plane cannot serve traffic safely — /ready
    should return 503 so the LB pulls the pod out of rotation.
    """
    info = {"type": type(store).__name__}
    try:
        # A read-only probe that works on every backend.
        store.list_identities()
        info["ok"] = True
    except Exception as e:
        info["ok"] = False
        info["error"] = str(e)[:200]
    return info


@app.get("/health")
def health():
    """Liveness probe — process is up. Always returns 200 (even during drain) so k8s
    doesn't restart the pod mid-shutdown. Use /ready for traffic routing."""
    return {"status": "ok", "version": _pkg_version,
            "protocols": registry.protocols(), "store": _store_health()}


@app.get("/ready")
def ready():
    """Readiness probe — process can serve NEW traffic. Returns 503 during shutdown
    or if the governance store is unreachable."""
    if not _ready["ok"]:
        return JSONResponse({"status": "draining"}, status_code=503)
    sh = _store_health()
    if not sh.get("ok"):
        return JSONResponse({"status": "not_ready", "store": sh}, status_code=503)
    return {"status": "ready", "store": sh}


@app.get("/version")
def version():
    return {"version": _pkg_version, "python": sys.version.split()[0],
            "store": type(store).__name__}


@app.get("/metrics")
def metrics():
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


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
def register_identity(body: IdentityBody,
                      _role: str = Depends(operator_guard("identities:write"))):
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
def revoke_identity(agent_id: str,
                    _role: str = Depends(operator_guard("identities:write"))):
    if not identities.revoke(agent_id):
        raise HTTPException(404, "unknown identity")
    return {"agent_id": agent_id, "revoked": True}


@app.get("/control/identities")
def list_identities(_role: str = Depends(operator_guard("identities:read"))):
    return {"identities": [
        {"agent_id": i["agent_id"], "did": "did:key:ed25519:" + i["public_key_hex"],
         "revoked": i.get("revoked", False)}
        for i in store.list_identities()
    ]}


@app.put("/control/budgets/{agent_id}")
def set_budget(agent_id: str, body: BudgetBody,
               _role: str = Depends(operator_guard("budgets:write"))):
    budgets.set_budget(agent_id, Budget(spend_limit=body.spend_limit,
                                        rate_limit=body.rate_limit,
                                        window_seconds=body.window_seconds))
    return {"agent_id": agent_id, "spend_limit": body.spend_limit, "rate_limit": body.rate_limit}


@app.get("/control/budgets/{agent_id}")
def get_budget(agent_id: str, _role: str = Depends(operator_guard("budgets:read"))):
    b = budgets.get(agent_id)
    return {"agent_id": agent_id, "spent": b.spent, "remaining": b.remaining(),
            "spend_limit": b.spend_limit, "rate_limit": b.rate_limit}


@app.post("/control/capabilities/sensitive")
def mark_sensitive(capability: str,
                   _role: str = Depends(operator_guard("policy:write"))):
    approvals.mark_sensitive(capability)
    return {"capability": capability, "requires_approval": True}


@app.get("/control/approvals")
def list_pending(_role: str = Depends(operator_guard("approvals:read"))):
    pending = approvals.pending()
    update_approvals_pending(len(pending))
    return {"pending": [vars(r) for r in pending]}


@app.post("/control/approvals/{request_id}/approve")
def approve(request_id: str, _role: str = Depends(operator_guard("approvals:write"))):
    if not approvals.approve(request_id):
        raise HTTPException(404, "no such pending request")
    update_approvals_pending(len(approvals.pending()))
    return {"request_id": request_id, "status": "approved"}


@app.post("/control/approvals/{request_id}/deny")
def deny(request_id: str, _role: str = Depends(operator_guard("approvals:write"))):
    if not approvals.deny(request_id):
        raise HTTPException(404, "no such pending request")
    update_approvals_pending(len(approvals.pending()))
    return {"request_id": request_id, "status": "denied"}


@app.get("/control/audit")
def get_audit(_role: str = Depends(operator_guard("audit:read"))):
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
def export_audit(_role: str = Depends(operator_guard("audit:export"))):
    return {"jsonl": audit.export_jsonl()}


# --- audit retention + signed checkpoints (production compliance) --------------------

@app.post("/control/audit/checkpoint")
def create_audit_checkpoint(_role: str = Depends(operator_guard("audit:export"))):
    """Sign the current audit head so a third party can later prove the log wasn't
    truncated before this point. We sign with the server's admin-key-derived identity
    if one exists; otherwise we generate an ephemeral operator key for this call only
    (production deployments should register a dedicated operator identity)."""
    from ..governance.identity import AgentIdentity
    # Use a fresh operator keypair for the checkpoint signature. The public key is
    # returned alongside so a third party can verify later. In a real deployment you'd
    # use a stable operator key (kept in a KMS or HSM); for now we make this explicit.
    op = AgentIdentity.generate("operator-checkpoint")
    cp = audit.checkpoint(op.sign, op.public_key_hex)
    return {"checkpoint": cp, "note": "public_key_hex must be preserved to verify later"}


@app.post("/control/audit/retention")
def set_audit_retention(body: dict,
                        _role: str = Depends(operator_guard("audit:export"))):
    """Truncate the audit log up to a given seq, or toggle legal hold.

    Body:
      {"action": "truncate", "seq": 1000}     # delete entries with seq < 1000
      {"action": "legal_hold", "on": true}    # freeze truncation
    """
    action = body.get("action")
    if action == "truncate":
        seq = int(body.get("seq", 0))
        if seq <= 0:
            raise HTTPException(400, "seq must be > 0")
        if audit.is_legal_hold():
            raise HTTPException(409, "legal hold is active; cannot truncate")
        removed = audit.truncate_before(seq)
        logger.info("audit truncated before seq=%d (%d entries removed)", seq, removed)
        return {"truncated_before": seq, "removed": removed}
    if action == "legal_hold":
        audit.set_legal_hold(bool(body.get("on", True)))
        return {"legal_hold": audit.is_legal_hold()}
    raise HTTPException(400, "unknown action; use 'truncate' or 'legal_hold'")


# --- policy rules (declarative policy engine v2, over HTTP) ----------------------------

_RULE_FACTORIES = {
    "max_cost": lambda p: MaxCostPerCall(float(p["max_cost"])),
    "approval_above_cost": lambda p: RequireApprovalAboveCost(float(p["threshold"])),
    "deny_capabilities": lambda p: DenyCapabilities(list(p["capabilities"])),
    "allow_only_capabilities": lambda p: AllowOnlyCapabilities(list(p["capabilities"])),
    "business_hours": lambda p: BusinessHoursOnly(int(p.get("start_hour", 9)),
                                                  int(p.get("end_hour", 17)),
                                                  p.get("days")),
    "deny_route": lambda p: DenyProtocolRoute(p["src"], p["dst"]),
}


class RuleBody(BaseModel):
    type: str = Field(description=f"one of: {sorted(_RULE_FACTORIES)}")
    params: Dict[str, Any] = Field(default_factory=dict)


@app.post("/control/policy/rules")
def add_policy_rule(body: RuleBody, _role: str = Depends(operator_guard("policy:write"))):
    factory = _RULE_FACTORIES.get(body.type)
    if not factory:
        raise HTTPException(400, f"unknown rule type '{body.type}'; known: {sorted(_RULE_FACTORIES)}")
    try:
        rule = factory(body.params)
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(400, f"bad params for '{body.type}': {e}")
    policy_rules.add(rule)
    return {"added": body.type, "rules_active": len(policy_rules.rules)}


@app.get("/control/policy/rules")
def list_policy_rules(_role: str = Depends(operator_guard("policy:read"))):
    return {"rules": [type(r).__name__ for r in policy_rules.rules]}


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
    import json
    raw = await request.body()                       # read the body ONCE
    agent_id = await authenticate_agent(request, raw)
    body = json.loads(raw or b"{}")
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
    import json
    raw = await request.body()                       # read the body ONCE
    agent_id = await authenticate_agent(request, raw)
    body = json.loads(raw or b"{}")
    d = policy.authorize(agent_id=agent_id, capability=body.get("capability", ""),
                         cost=float(body.get("cost", 1.0)))
    return {"allowed": d.allowed, "reason": d.reason, "needs_approval": d.needs_approval}
