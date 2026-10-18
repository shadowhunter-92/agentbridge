"""Enrolled tenant/principal authority; additive foundation, not tenant activation.

The directory owns trusted issuer configuration and operator-managed enrollment.
A tenant/grant selector is signed and matched to enrolled authority. It is never
membership proof by itself. Contexts are process-local, sealed, immutable and
revalidated against durable revisions. Existing single-tenant tables are untouched.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..api.auth_oidc import OidcError, OidcVerifier
from .store import PostgresStore, SqliteStore

_ROLES = frozenset({"tenant_admin", "tenant_operator", "tenant_viewer"})
_LOCK = 911005
_VERSION = 1
_DDL = (
    "CREATE TABLE IF NOT EXISTS authority_schema (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL, digest TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS authority_tenants (tenant_id TEXT PRIMARY KEY, revision BIGINT NOT NULL, active INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS authority_platform_admins (issuer TEXT NOT NULL, subject TEXT NOT NULL, revision BIGINT NOT NULL, active INTEGER NOT NULL, PRIMARY KEY(issuer,subject))",
    "CREATE TABLE IF NOT EXISTS authority_members (tenant_id TEXT NOT NULL, issuer TEXT NOT NULL, subject TEXT NOT NULL, role TEXT NOT NULL, revision BIGINT NOT NULL, active INTEGER NOT NULL, capabilities TEXT NOT NULL, targets TEXT NOT NULL, PRIMARY KEY(tenant_id,issuer,subject))",
    "CREATE TABLE IF NOT EXISTS authority_agents (tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL, public_key_hex TEXT NOT NULL, revision BIGINT NOT NULL, active INTEGER NOT NULL, capabilities TEXT NOT NULL, targets TEXT NOT NULL, PRIMARY KEY(tenant_id,agent_id))",
    "CREATE TABLE IF NOT EXISTS authority_delegations (tenant_id TEXT NOT NULL, grant_id TEXT NOT NULL, agent_id TEXT NOT NULL, agent_revision BIGINT NOT NULL, user_issuer TEXT NOT NULL, user_subject TEXT NOT NULL, user_revision BIGINT NOT NULL, grantor_issuer TEXT NOT NULL, grantor_subject TEXT NOT NULL, grantor_kind TEXT NOT NULL, grantor_revision BIGINT NOT NULL, capabilities TEXT NOT NULL, targets TEXT NOT NULL, not_before DOUBLE PRECISION NOT NULL, expires_at DOUBLE PRECISION NOT NULL, tenant_revision BIGINT NOT NULL, revision BIGINT NOT NULL, active INTEGER NOT NULL, PRIMARY KEY(tenant_id,grant_id))",
    "CREATE TABLE IF NOT EXISTS authority_replays (tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL, nonce TEXT NOT NULL, at DOUBLE PRECISION NOT NULL, PRIMARY KEY(tenant_id,agent_id,nonce))",
    "CREATE INDEX IF NOT EXISTS authority_replays_at ON authority_replays(at)",
)
_DIGEST = hashlib.sha256("\n".join(_DDL).encode()).hexdigest()


class AuthorityDenied(PermissionError):
    """No authenticated, current and appropriately scoped authority."""


class AuthorityMigrationDenied(RuntimeError):
    """Unknown or altered authority migration; do not activate tenant mode."""


def _identifier(value, label="identifier"):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError("invalid bounded " + label)
    return value


def _subject(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or value.strip() != value
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("invalid bounded subject")
    return value


def _scopes(values):
    if not isinstance(values, (tuple, list)) or len(values) > 128:
        raise ValueError("explicit bounded scopes required")
    if any(
        not isinstance(v, str) or not 1 <= len(v) <= 128 or v.strip() != v or "*" in v or any(ord(c) < 32 for c in v)
        for v in values
    ):
        raise ValueError("invalid scope; wildcards are prohibited")
    return tuple(sorted(set(values)))


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_tenant_payload(tenant_id, agent_id, nonce, body, *, delegation_id=None):
    """Domain-separated v2 proof, including both selectors and exact body bytes."""
    _identifier(tenant_id, "tenant_id")
    _identifier(agent_id, "agent_id")
    if delegation_id is not None:
        _identifier(delegation_id, "delegation_id")
    if not isinstance(nonce, str) or not isinstance(body, bytes):
        raise ValueError("nonce string and exact body bytes required")
    return _json(
        {
            "domain": "agentbridge.tenant-request.v2",
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "delegation_id": delegation_id,
            "nonce": nonce,
            "body_sha256": hashlib.sha256(body).hexdigest(),
        }
    ).encode()


def sign_tenant_request(identity, tenant_id, nonce, body, *, delegation_id=None):
    return identity.sign(
        canonical_tenant_payload(tenant_id, identity.agent_id, nonce, body, delegation_id=delegation_id)
    ).hex()


@dataclass(frozen=True)
class Principal:
    tenant_id: str | None
    subject: str
    issuer: str
    kind: str
    revision: int
    tenant_revision: int = 0
    agent_id: str | None = None
    agent_revision: int = 0
    delegation_id: str | None = None
    delegation_revision: int = 0
    user_revision: int = 0
    grantor_revision: int = 0
    valid_until: float = 0
    capabilities: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()
    request_body_sha256: str = ""
    request_nonce: str = ""
    _proof: bytes = field(default=b"", repr=False, compare=False)

    def binding(self):
        """Stable authority fingerprint material, independent of JWT renewal.

        Expiry remains sealed and checked on each use, but a token refresh with
        unchanged enrollment/grant revision does not alter a pending approval.
        This does not authenticate a serialized context; the directory does.
        """
        return {
            k: v
            for k, v in asdict(self).items()
            if k not in ("_proof", "valid_until", "request_body_sha256", "request_nonce")
        }


class _Cursor:
    def __init__(self, cursor, postgres):
        self.cursor, self.postgres = cursor, postgres

    def execute(self, sql, args=()):
        return self.cursor.execute(sql.replace("?", "%s") if self.postgres else sql, args)


class AuthorityDirectory:
    """Trusted authority service using existing SQL store transactions.

    Instantiating this directory does not retrofit tenant isolation into legacy
    stores or APIs. The subsequent scoped-runtime layer must explicitly activate
    tenant mode only after all its entry points and migration are qualified.
    """

    def __init__(self, store, *, verifiers):
        if not isinstance(store, (SqliteStore, PostgresStore)):
            raise ValueError("durable SQL authority store required")
        with store._lock:
            if isinstance(store, SqliteStore):
                if not store._db.execute("PRAGMA database_list").fetchone()["file"]:
                    raise ValueError("authority requires a durable, separate SQL namespace")
                bound = store._db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tenant_store_binding'"
                ).fetchone()
            else:
                with store._db.cursor() as cur:
                    cur.execute("SELECT to_regclass('tenant_store_binding') AS binding")
                    bound = cur.fetchone()["binding"]
            if bound:
                raise ValueError("authority directory cannot inhabit a tenant data namespace")
        self.store = store
        self.verifiers = dict(verifiers)
        if not self.verifiers:
            raise ValueError("operator-configured trusted issuers required")
        for issuer, verifier in self.verifiers.items():
            parsed = urlsplit(issuer)
            if (
                not isinstance(verifier, OidcVerifier)
                or verifier.config.issuer != issuer
                or parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or not verifier.config.audience
            ):
                raise ValueError("explicit HTTPS issuer, audience and verifier required")
        self._context_key = secrets.token_bytes(32)
        self._transaction_context = threading.local()
        # Same DDL bootstrap lock as the underlying PostgresStore avoids concurrent
        # first-use catalog races across separate workers/instances.
        with self._transaction(write=True, bootstrap=True) as cur:
            for ddl in _DDL:
                cur.execute(ddl)
            row = cur.execute("SELECT version,digest FROM authority_schema WHERE singleton=1").fetchone()
            if row and (row["version"] != _VERSION or row["digest"] != _DIGEST):
                raise AuthorityMigrationDenied("unknown or altered authority schema")
            if not row:
                cur.execute("INSERT INTO authority_schema VALUES(1,?,?)", (_VERSION, _DIGEST))

    @contextmanager
    def _transaction(self, *, write=False, claim=False, bootstrap=False):
        store = self.store
        active = getattr(self._transaction_context, "active", None)
        if active is not None:
            cursor, writing, claiming = active
            if (write and not writing) or (claim and not (writing or claiming)) or bootstrap:
                raise RuntimeError("nested authority transaction cannot escalate its lock")
            yield cursor
            return
        with store._lock:
            if isinstance(store, SqliteStore):
                store._db.execute("BEGIN IMMEDIATE" if write or claim else "BEGIN")
                try:
                    cursor = _Cursor(store._db, False)
                    self._transaction_context.active = (cursor, write, claim)
                    try:
                        yield cursor
                    finally:
                        self._transaction_context.active = None
                    store._db.execute("COMMIT")
                except BaseException:
                    store._db.execute("ROLLBACK")
                    raise
            else:
                with store._db.transaction(), store._db.cursor() as raw:
                    # Enrollment/revocation is exclusive; request/nonce claims
                    # share the lock and retain concurrent independent inserts.
                    lock = "pg_advisory_xact_lock" if write else "pg_advisory_xact_lock_shared"
                    raw.execute("SELECT " + lock + "(%s)", (_LOCK,))
                    # Governance paths hold authority before helper schema DDL.
                    # Bootstrap must use the same order across connections.
                    if bootstrap:
                        raw.execute("SELECT pg_advisory_xact_lock(%s)", (911004,))
                    cursor = _Cursor(raw, True)
                    self._transaction_context.active = (cursor, write, claim)
                    try:
                        yield cursor
                    finally:
                        self._transaction_context.active = None

    @contextmanager
    def guard(self, principal, *, write=False):
        """Serialize a bounded local governance operation with authority changes.

        This is a local SQL linearization boundary. It does not make a remote
        effect atomic; qualified destination execution must enforce that itself.
        Nested reads reuse the same transaction, never silently upgrade locks.
        """
        # WAL readers do not block writers. A SQLite local governance guard
        # therefore needs BEGIN IMMEDIATE even for a read-only authority check;
        # PostgreSQL retains its shared advisory lock for concurrent admissions.
        with self._transaction(write=write, claim=isinstance(self.store, SqliteStore)) as cur:
            self._current(cur, principal)
            yield

    def _mint(self, **values):
        principal = Principal(**values)
        return replace(principal, _proof=self._seal(principal))

    def _agent_principal(self, tenant, agent, grant, *, valid_until, request_body_sha256="", request_nonce=""):
        """Derive a process context from already validated enrollment rows."""
        common = dict(
            tenant_id=tenant["tenant_id"], tenant_revision=tenant["revision"],
            agent_id=agent["agent_id"], agent_revision=agent["revision"],
            revision=agent["revision"], request_body_sha256=request_body_sha256, request_nonce=request_nonce,
        )
        if grant is not None:
            return self._mint(
                **common, subject=grant["user_subject"], issuer=grant["user_issuer"], kind="delegated_human",
                delegation_id=grant["grant_id"], delegation_revision=grant["revision"],
                user_revision=grant["user_revision"], grantor_revision=grant["grantor_revision"],
                valid_until=min(grant["expires_at"], valid_until),
                capabilities=tuple(json.loads(grant["capabilities"])), targets=tuple(json.loads(grant["targets"])),
            )
        return self._mint(
            **common, subject=agent["agent_id"], issuer="urn:agentbridge:enrollment", kind="machine",
            valid_until=valid_until, capabilities=tuple(json.loads(agent["capabilities"])),
            targets=tuple(json.loads(agent["targets"])),
        )

    def _guard_queued_intent(self, bound_intents, owner_id, task_id, expected_intent_sha256):
        """Private retained-row preparation guard; never authenticates a request."""
        from .queued_intent_preparation import _guard_queued_intent

        return _guard_queued_intent(self, bound_intents, owner_id, task_id, expected_intent_sha256)

    def _assert_queued_intent(self, context, bound_intents):
        from .queued_intent_preparation import _assert_queued_intent

        return _assert_queued_intent(self, context, bound_intents)

    def _seal(self, principal):
        values = asdict(principal)
        values.pop("_proof")
        return hmac.digest(self._context_key, _json(values).encode(), "sha256")

    def _verify_seal(self, principal):
        try:
            valid = (
                isinstance(principal, Principal)
                and isinstance(principal._proof, bytes)
                and isinstance(principal.capabilities, tuple)
                and isinstance(principal.targets, tuple)
                and hmac.compare_digest(principal._proof, self._seal(principal))
                and math.isfinite(principal.valid_until)
                and principal.valid_until > time.time()
            )
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise AuthorityDenied("unverified, altered or expired principal context")

    def _tenant(self, cur, tenant_id):
        row = cur.execute("SELECT * FROM authority_tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
        if not row or not row["active"]:
            raise AuthorityDenied("tenant unavailable")
        return row

    def _platform(self, cur, issuer, subject):
        row = cur.execute(
            "SELECT * FROM authority_platform_admins WHERE issuer=? AND subject=?", (issuer, subject)
        ).fetchone()
        if not row or not row["active"]:
            raise AuthorityDenied("platform authority unavailable")
        return row

    def _member(self, cur, tenant_id, issuer, subject):
        row = cur.execute(
            "SELECT * FROM authority_members WHERE tenant_id=? AND issuer=? AND subject=?", (tenant_id, issuer, subject)
        ).fetchone()
        if not row or not row["active"]:
            raise AuthorityDenied("tenant membership unavailable")
        return row

    def _agent(self, cur, tenant_id, agent_id):
        row = cur.execute(
            "SELECT * FROM authority_agents WHERE tenant_id=? AND agent_id=?", (tenant_id, agent_id)
        ).fetchone()
        if not row or not row["active"]:
            raise AuthorityDenied("agent enrollment unavailable")
        return row

    def _grant(self, cur, tenant_id, grant_id, agent):
        row = cur.execute(
            "SELECT * FROM authority_delegations WHERE tenant_id=? AND grant_id=?", (tenant_id, grant_id)
        ).fetchone()
        now = time.time()
        if (
            not row
            or not row["active"]
            or not row["not_before"] <= now < row["expires_at"]
            or row["agent_id"] != agent["agent_id"]
            or row["agent_revision"] != agent["revision"]
        ):
            raise AuthorityDenied("delegation unavailable or stale")
        if row["tenant_revision"] != self._tenant(cur, tenant_id)["revision"]:
            raise AuthorityDenied("delegation tenant revision changed")
        user = self._member(cur, tenant_id, row["user_issuer"], row["user_subject"])
        if row["grantor_kind"] == "platform_admin":
            grantor = self._platform(cur, row["grantor_issuer"], row["grantor_subject"])
        else:
            grantor = self._member(cur, tenant_id, row["grantor_issuer"], row["grantor_subject"])
            if grantor["role"] != "tenant_admin":
                raise AuthorityDenied("delegation grantor no longer an administrator")
        if user["revision"] != row["user_revision"] or grantor["revision"] != row["grantor_revision"]:
            raise AuthorityDenied("delegation enrollment revision changed")
        return row

    def _current(self, cur, principal):
        self._verify_seal(principal)
        if principal.kind == "platform_admin":
            row = self._platform(cur, principal.issuer, principal.subject)
            if principal.tenant_id is not None or row["revision"] != principal.revision:
                raise AuthorityDenied("platform authority changed")
            return
        tenant = self._tenant(cur, principal.tenant_id)
        if tenant["revision"] != principal.tenant_revision:
            raise AuthorityDenied("tenant authority changed")
        if principal.kind in _ROLES:
            row = self._member(cur, principal.tenant_id, principal.issuer, principal.subject)
            if row["role"] != principal.kind or row["revision"] != principal.revision:
                raise AuthorityDenied("membership authority changed")
        elif principal.kind in ("machine", "delegated_human"):
            row = self._agent(cur, principal.tenant_id, principal.agent_id)
            if row["revision"] != principal.agent_revision:
                raise AuthorityDenied("agent authority changed")
            if principal.kind == "delegated_human":
                row = self._grant(cur, principal.tenant_id, principal.delegation_id, row)
                if row["revision"] != principal.delegation_revision:
                    raise AuthorityDenied("delegation revision changed")
        else:
            raise AuthorityDenied("unsupported principal kind")

    def assert_current(self, principal):
        with self._transaction() as cur:
            self._current(cur, principal)
        return principal

    def assert_request(self, principal, *, body, nonce):
        """A request-authenticated context cannot authorize different body bytes."""
        self.assert_current(principal)
        if (
            principal.kind not in ("machine", "delegated_human")
            or not isinstance(body, bytes)
            or principal.request_body_sha256 != hashlib.sha256(body).hexdigest()
            or principal.request_nonce != nonce
        ):
            raise AuthorityDenied("principal proof is bound to a different request")
        return principal

    def _admin(self, cur, actor, tenant_id=None):
        self._current(cur, actor)
        if actor.kind == "platform_admin":
            return
        if tenant_id is None or actor.kind != "tenant_admin" or actor.tenant_id != tenant_id:
            raise AuthorityDenied("appropriately scoped administrator required")

    def bootstrap_platform_admin(self, issuer, subject):
        """Explicit trusted-operator setup, never called as a login side effect."""
        if issuer not in self.verifiers:
            raise ValueError("trusted issuer required")
        _subject(subject)
        with self._transaction(write=True) as cur:
            if cur.execute("SELECT count(*) AS n FROM authority_platform_admins").fetchone()["n"]:
                raise AuthorityDenied("platform bootstrap is permanently closed")
            cur.execute("INSERT INTO authority_platform_admins VALUES(?,?,1,1)", (issuer, subject))

    def authenticate_operator(self, issuer, token, *, tenant_id=None):
        verifier = self.verifiers.get(issuer)
        if verifier is None or not isinstance(token, str) or not 1 <= len(token) <= 16384:
            raise AuthorityDenied("trusted issuer and bounded signed token required")
        try:
            claims = verifier.verify(token)
            subject = _subject(claims.get("sub"))
            expires = claims.get("exp")
            if (
                isinstance(expires, bool)
                or not isinstance(expires, (int, float))
                or not math.isfinite(expires)
                or expires <= time.time()
            ):
                raise ValueError("explicit token expiry required")
            if claims.get("iss") != issuer or ("tenant_id" in claims and claims["tenant_id"] != tenant_id):
                raise ValueError("conflicting verified tenant or issuer")
            if tenant_id is not None:
                _identifier(tenant_id, "tenant_id")
        except (OidcError, ValueError, TypeError) as exc:
            raise AuthorityDenied("operator token is not valid for enrolled authority") from exc
        with self._transaction() as cur:
            if tenant_id is None:
                row = self._platform(cur, issuer, subject)
                return self._mint(
                    tenant_id=None,
                    subject=subject,
                    issuer=issuer,
                    kind="platform_admin",
                    revision=row["revision"],
                    valid_until=expires,
                )
            tenant = self._tenant(cur, tenant_id)
            row = self._member(cur, tenant_id, issuer, subject)
            return self._mint(
                tenant_id=tenant_id,
                subject=subject,
                issuer=issuer,
                kind=row["role"],
                revision=row["revision"],
                tenant_revision=tenant["revision"],
                valid_until=expires,
                capabilities=tuple(json.loads(row["capabilities"])),
                targets=tuple(json.loads(row["targets"])),
            )

    def set_tenant(self, actor, tenant_id, *, active):
        _identifier(tenant_id, "tenant_id")
        if type(active) is not bool:
            raise ValueError("explicit tenant activation boolean required")
        with self._transaction(write=True) as cur:
            self._admin(cur, actor)
            cur.execute(
                "INSERT INTO authority_tenants VALUES(?,1,?) ON CONFLICT(tenant_id) DO UPDATE SET revision=authority_tenants.revision+1,active=excluded.active",
                (tenant_id, int(active)),
            )

    def enroll_platform_admin(self, actor, issuer, subject):
        if issuer not in self.verifiers:
            raise ValueError("trusted issuer required")
        _subject(subject)
        with self._transaction(write=True) as cur:
            self._admin(cur, actor)
            cur.execute(
                "INSERT INTO authority_platform_admins VALUES(?,?,1,1) ON CONFLICT(issuer,subject) DO UPDATE SET revision=authority_platform_admins.revision+1,active=1",
                (issuer, subject),
            )

    def revoke_platform_admin(self, actor, issuer, subject):
        with self._transaction(write=True) as cur:
            self._admin(cur, actor)
            self._platform(cur, issuer, subject)
            if cur.execute("SELECT count(*) AS n FROM authority_platform_admins WHERE active=1").fetchone()["n"] <= 1:
                raise AuthorityDenied("cannot revoke the last active platform administrator")
            cur.execute(
                "UPDATE authority_platform_admins SET revision=revision+1,active=0 WHERE issuer=? AND subject=?",
                (issuer, subject),
            )

    def enroll_member(self, actor, tenant_id, issuer, subject, *, role, capabilities=(), targets=()):
        _identifier(tenant_id, "tenant_id")
        _subject(subject)
        if role not in _ROLES or issuer not in self.verifiers:
            raise ValueError("enrolled tenant role and configured issuer required")
        capabilities, targets = _scopes(capabilities), _scopes(targets)
        with self._transaction(write=True) as cur:
            self._admin(cur, actor, tenant_id)
            self._tenant(cur, tenant_id)
            cur.execute(
                "INSERT INTO authority_members VALUES(?,?,?,?,1,1,?,?) ON CONFLICT(tenant_id,issuer,subject) DO UPDATE SET role=excluded.role,revision=authority_members.revision+1,active=1,capabilities=excluded.capabilities,targets=excluded.targets",
                (tenant_id, issuer, subject, role, _json(capabilities), _json(targets)),
            )

    def enroll_agent(self, actor, tenant_id, agent_id, public_key_hex, *, capabilities=(), targets=()):
        _identifier(tenant_id, "tenant_id")
        _identifier(agent_id, "agent_id")
        try:
            if not isinstance(public_key_hex, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", public_key_hex):
                raise ValueError("invalid key")
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        except (TypeError, ValueError) as exc:
            raise ValueError("32-byte Ed25519 enrollment key required") from exc
        capabilities, targets = _scopes(capabilities), _scopes(targets)
        with self._transaction(write=True) as cur:
            self._admin(cur, actor, tenant_id)
            self._tenant(cur, tenant_id)
            cur.execute(
                "INSERT INTO authority_agents VALUES(?,?,?,1,1,?,?) ON CONFLICT(tenant_id,agent_id) DO UPDATE SET public_key_hex=excluded.public_key_hex,revision=authority_agents.revision+1,active=1,capabilities=excluded.capabilities,targets=excluded.targets",
                (tenant_id, agent_id, public_key_hex.lower(), _json(capabilities), _json(targets)),
            )

    def revoke_agent(self, actor, tenant_id, agent_id):
        with self._transaction(write=True) as cur:
            self._admin(cur, actor, tenant_id)
            self._agent(cur, tenant_id, agent_id)
            cur.execute(
                "UPDATE authority_agents SET revision=revision+1,active=0 WHERE tenant_id=? AND agent_id=?",
                (tenant_id, agent_id),
            )

    def revoke_member(self, actor, tenant_id, issuer, subject):
        with self._transaction(write=True) as cur:
            self._admin(cur, actor, tenant_id)
            self._member(cur, tenant_id, issuer, subject)
            cur.execute(
                "UPDATE authority_members SET revision=revision+1,active=0 WHERE tenant_id=? AND issuer=? AND subject=?",
                (tenant_id, issuer, subject),
            )

    def list_agents(self, actor, tenant_id):
        with self._transaction() as cur:
            self._admin(cur, actor, tenant_id)
            self._tenant(cur, tenant_id)
            return [
                dict(r)
                for r in cur.execute(
                    "SELECT tenant_id,agent_id,public_key_hex,revision,active FROM authority_agents WHERE tenant_id=? ORDER BY agent_id",
                    (tenant_id,),
                ).fetchall()
            ]

    def grant_delegation(self, actor, user, agent_id, *, capabilities, targets, expires_at, not_before=None):
        self._verify_seal(user)
        if user.kind not in _ROLES or user.tenant_id is None:
            raise AuthorityDenied("authenticated tenant user consent context required")
        capabilities, targets = _scopes(capabilities), _scopes(targets)
        now = time.time()
        not_before = now if not_before is None else not_before
        if any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in (expires_at, not_before)
        ) or not now <= not_before < expires_at <= min(user.valid_until, now + 3600):
            raise ValueError("bounded delegation inside authenticated consent lifetime required")
        grant = uuid.uuid4().hex
        with self._transaction(write=True) as cur:
            self._admin(cur, actor, user.tenant_id)
            self._current(cur, user)
            agent = self._agent(cur, user.tenant_id, _identifier(agent_id, "agent_id"))
            if (
                not capabilities
                or not set(capabilities) <= set(user.capabilities) & set(json.loads(agent["capabilities"]))
                or not set(targets) <= set(user.targets) & set(json.loads(agent["targets"]))
            ):
                raise AuthorityDenied("delegation exceeds enrolled user or agent scopes")
            cur.execute(
                "INSERT INTO authority_delegations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1)",
                (
                    user.tenant_id,
                    grant,
                    agent_id,
                    agent["revision"],
                    user.issuer,
                    user.subject,
                    user.revision,
                    actor.issuer,
                    actor.subject,
                    actor.kind,
                    actor.revision,
                    _json(capabilities),
                    _json(targets),
                    not_before,
                    expires_at,
                    user.tenant_revision,
                ),
            )
        return grant

    def revoke_delegation(self, actor, tenant_id, grant_id):
        with self._transaction(write=True) as cur:
            self._admin(cur, actor, tenant_id)
            changed = cur.execute(
                "UPDATE authority_delegations SET active=0,revision=revision+1 WHERE tenant_id=? AND grant_id=?",
                (tenant_id, grant_id),
            ).rowcount
            if not changed:
                raise AuthorityDenied("delegation unavailable")

    def authenticate_agent(self, tenant_id, agent_id, nonce, body, signature_hex, *, delegation_id=None):
        try:
            if (
                not isinstance(body, bytes)
                or len(body) > 1048576
                or not isinstance(nonce, str)
                or len(nonce) > 256
                or not isinstance(signature_hex, str)
                or not re.fullmatch(r"[a-fA-F0-9]{128}", signature_hex)
            ):
                raise ValueError("invalid signed request")
            data = canonical_tenant_payload(tenant_id, agent_id, nonce, body, delegation_id=delegation_id)
            stamp, random = nonce.split(":", 1)
            stamp = float(stamp)
            if not math.isfinite(stamp) or abs(time.time() - stamp) > 300 or len(random) < 16:
                raise ValueError("fresh bounded timestamp nonce required")
        except (ValueError, TypeError, OverflowError) as exc:
            raise AuthorityDenied("invalid signed tenant request") from exc
        with self._transaction(claim=True) as cur:
            tenant = self._tenant(cur, tenant_id)
            agent = self._agent(cur, tenant_id, agent_id)
            try:
                Ed25519PublicKey.from_public_bytes(bytes.fromhex(agent["public_key_hex"])).verify(
                    bytes.fromhex(signature_hex), data
                )
            except (InvalidSignature, ValueError) as exc:
                raise AuthorityDenied("enrolled request signature required") from exc
            grant = self._grant(cur, tenant_id, delegation_id, agent) if delegation_id is not None else None
            changed = cur.execute(
                "INSERT INTO authority_replays VALUES(?,?,?,?) ON CONFLICT(tenant_id,agent_id,nonce) DO NOTHING",
                (tenant_id, agent_id, nonce, time.time()),
            ).rowcount
            if changed != 1:
                raise AuthorityDenied("signed request replay denied")
            return self._agent_principal(
                tenant, agent, grant, valid_until=stamp + 300,
                request_body_sha256=hashlib.sha256(body).hexdigest(), request_nonce=nonce,
            )

    def authorize(self, principal, capability, target_id=None):
        with self._transaction() as cur:
            self._current(cur, principal)
            if (
                principal.kind not in ("machine", "delegated_human")
                or capability not in principal.capabilities
                or (target_id is not None and target_id not in principal.targets)
            ):
                raise AuthorityDenied("action outside authenticated principal scope")
        return principal

    def prune_replays(self, actor, *, limit=1000):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("bounded replay retention batch required")
        with self._transaction(write=True) as cur:
            self._admin(cur, actor)
            # Future-dated nonces are accepted at most300 seconds ahead; retain
            # a further300 seconds so no still-valid signature becomes reusable.
            return cur.execute(
                "DELETE FROM authority_replays WHERE (tenant_id,agent_id,nonce) IN (SELECT tenant_id,agent_id,nonce FROM authority_replays WHERE at<? ORDER BY at LIMIT ?)",
                (time.time() - 600, limit),
            ).rowcount
