"""Private guard-scoped preparation of retained intent; never execution admission.

Current enrolled rows supply authority. Retained JSON supplies binding constraints
only. Internal process seals do not authenticate a new public request. No worker,
operation claim, accounting, results or external invocation is implemented here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

from ..api.trusted_targets import resolve_queued_target
from .authority import AuthorityDenied, Principal
from .budget import _checked_cost
from .policy_rules import PolicyContext
from .store import SqliteStore


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _require_read_committed(cur):
    if cur.postgres and cur.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] != "read committed":
        raise AuthorityDenied("queued intent preparation requires PostgreSQL READ COMMITTED")


@dataclass(frozen=True, slots=True)
class _StoredIntent:
    owner_id: str
    task_id: str
    agent_id: str
    operation_id: str
    intent_sha256: str
    record_json: str = field(repr=False)
    result_limit_bytes: int

    @property
    def record(self):
        # Return a copy: mutating caller JSON cannot alter the validated record.
        return json.loads(self.record_json)


@dataclass(frozen=True, slots=True)
class _QueuedIntentAuthority:
    intent: _StoredIntent
    principal: Principal = field(repr=False)
    store_id: str
    original_deadline: float
    _lease: object = field(repr=False, compare=False)
    _proof: bytes = field(default=b"", repr=False, compare=False)


def _authority_seal(directory, context):
    material = {
        "domain": "agentbridge.private-queued-authority.v1", "store_id": context.store_id,
        "owner_id": context.intent.owner_id, "task_id": context.intent.task_id,
        "intent_sha256": context.intent.intent_sha256, "result_limit_bytes": context.intent.result_limit_bytes,
        "original_deadline": context.original_deadline, "lease": id(context._lease),
        "principal_proof": context.principal._proof.hex(),
    }
    return hmac.digest(directory._context_key, _json(material).encode(), "sha256")


def _derive(directory, cur, bound_intents, intent, *, valid_until):
    provenance = intent.record["provenance"]
    binding = provenance["authority"]
    try:
        nonce = provenance["request_nonce"]
        stamp, random = nonce.split(":", 1)
        stamp = float(stamp)
        if not isinstance(nonce, str) or len(nonce) > 256 or not math.isfinite(stamp) or len(random) < 16:
            raise ValueError("invalid original nonce")
        tenant = directory._tenant(cur, bound_intents.store.tenant_id)
        agent = directory._agent(cur, tenant["tenant_id"], intent.agent_id)
        grant = None
        if binding["kind"] == "delegated_human":
            grant = directory._grant(cur, tenant["tenant_id"], binding["delegation_id"], agent)
        original_deadline = min(stamp + 300, grant["expires_at"]) if grant is not None else stamp + 300
        if provenance["authorization_expires_at"] != original_deadline or time.time() >= original_deadline:
            raise ValueError("original authorization expired or changed")
        principal = directory._agent_principal(
            tenant, agent, grant, valid_until=min(valid_until, original_deadline)
        )
        if _json(principal.binding()) != _json(binding) or agent["public_key_hex"] != provenance["signer_public_key_hex"]:
            raise ValueError("accepted enrollment binding changed")
        identity = bound_intents.store.get_identity(intent.agent_id)
        if identity is None or identity.get("revoked", False) or identity["public_key_hex"] != agent["public_key_hex"]:
            raise ValueError("tenant identity and enrollment disagree")
        directory._current(cur, principal)
        return principal, float(original_deadline)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise AuthorityDenied("queued intent authority or original deadline unavailable") from exc


@contextmanager
def _guard_queued_intent(directory, bound_intents, owner_id, task_id, expected_intent_sha256):
    from .task_intents import TaskIntentStore

    if not isinstance(bound_intents, TaskIntentStore):
        raise AuthorityDenied("operator-bound retained intent store required")
    with directory._transaction(claim=isinstance(directory.store, SqliteStore)) as cur:
        _require_read_committed(cur)
        intent = bound_intents._load_for_execution(owner_id, task_id, expected_intent_sha256)
        principal, deadline = _derive(directory, cur, bound_intents, intent, valid_until=time.time() + 30)
        # The opaque lease is registered only on this directory/thread while
        # its authority transaction is active. Copies cannot reactivate it.
        lease = object()
        guards = getattr(directory._transaction_context, "queued_intent_guards", None)
        if guards is None:
            guards = directory._transaction_context.queued_intent_guards = set()
        guards.add(lease)
        try:
            context = _QueuedIntentAuthority(intent, principal, bound_intents.store.store_id, deadline, lease)
            context = replace(context, _proof=_authority_seal(directory, context))
            _assert_queued_intent(directory, context, bound_intents)
            yield context
        finally:
            guards.discard(lease)
            if not guards:
                del directory._transaction_context.queued_intent_guards


def _verify_queued_scope(directory, context, bound_intents):
    try:
        guards = getattr(directory._transaction_context, "queued_intent_guards", ())
        valid = isinstance(context, _QueuedIntentAuthority) and type(context._lease) is object and \
            context._lease in guards and context.store_id == bound_intents.store.store_id and \
            isinstance(context._proof, bytes) and hmac.compare_digest(context._proof, _authority_seal(directory, context))
    except (TypeError, ValueError, AttributeError, OverflowError):
        valid = False
    if not valid:
        raise AuthorityDenied("unverified or inactive queued intent context")


def _assert_queued_lifetime(directory, context, bound_intents):
    """Final admission gate only: no assertion that status is still SUBMITTED."""
    _verify_queued_scope(directory, context, bound_intents)
    with directory._transaction() as cur:
        _require_read_committed(cur)
        directory._current(cur, context.principal)
        principal, deadline = _derive(
            directory, cur, bound_intents, context.intent, valid_until=context.principal.valid_until
        )
        if principal != context.principal or deadline != context.original_deadline:
            raise AuthorityDenied("queued admission scope or lifetime changed")


def _assert_queued_intent(directory, context, bound_intents):
    _verify_queued_scope(directory, context, bound_intents)
    with directory._transaction() as cur:
        _require_read_committed(cur)
        if context._lease not in getattr(directory._transaction_context, "queued_intent_guards", ()):
            raise AuthorityDenied("queued intent guard is no longer active")
        directory._current(cur, context.principal)
        current = bound_intents._load_for_execution(
            context.intent.owner_id, context.intent.task_id, context.intent.intent_sha256
        )
        if current != context.intent:
            raise AuthorityDenied("retained queued intent changed")
        principal, deadline = _derive(
            directory, cur, bound_intents, current, valid_until=context.principal.valid_until
        )
        if principal != context.principal or deadline != context.original_deadline:
            raise AuthorityDenied("queued intent scope or lifetime changed")
        return context


@dataclass(frozen=True, slots=True)
class _PreparedQueuedIntent:
    tenant_id: str
    plan_json: str = field(repr=False)
    _authority: _QueuedIntentAuthority = field(repr=False)
    _proof: bytes = field(default=b"", repr=False, compare=False)

    @property
    def plan(self):
        return json.loads(self.plan_json)


def _plan(kernel, runtime, authority):
    intent = authority.intent
    record = intent.record
    provenance = record["provenance"]
    submission = record["submission"]
    try:
        kernel.registry.get(submission["dst"])
        call = kernel.registry.get(submission["src"]).to_canonical_call(submission["wire"])
        kernel.registry.translate_call(submission["wire"], submission["src"], submission["dst"])
        kernel.directory.authorize(authority.principal, call.capability, submission["target_id"])
        cost = _checked_cost(kernel.costs[runtime.store.tenant_id][call.capability])
        if type(provenance["operator_cost"]) not in (int, float) or \
                call.capability != provenance["capability"] or cost != _checked_cost(provenance["operator_cost"]):
            raise ValueError("accepted capability or operator cost changed")
        target = resolve_queued_target(submission["target_id"], submission["dst"], call.capability,
                                       tenant_id=runtime.store.tenant_id, wire=submission["wire"],
                                       agent_id=intent.agent_id, env=kernel._target_env[runtime.store.tenant_id])
        if target is not None and target.get("kind") == "queued_fenced_sqlite_v2":
            kernel._queued_adapter(runtime.store.tenant_id, submission["target_id"], target)
        digest = hashlib.sha256(_json(target).encode()).hexdigest()
        if target is None or digest != provenance["target_configuration_sha256"]:
            raise ValueError("accepted target configuration changed")
        rule = runtime.rules.evaluate(PolicyContext(
            agent_id=intent.agent_id, capability=call.capability, cost=cost,
            src_protocol=submission["src"], dst_protocol=submission["dst"],
        ))
        if not rule.allowed:
            raise ValueError("current declarative policy denies intent preparation")
        return _json({
            "domain": "agentbridge.private-queued-preparation.v1", "tenant_id": runtime.store.tenant_id,
            "owner_id": intent.owner_id, "task_id": intent.task_id, "context_id": submission["context_id"],
            "operation_id": intent.operation_id, "intent_sha256": intent.intent_sha256,
            "src": submission["src"], "dst": submission["dst"], "wire": submission["wire"],
            "capability": call.capability, "cost": cost,
            "target_id": submission["target_id"], "target": target, "target_configuration_sha256": digest,
            "original_authorization_expires_at": authority.original_deadline,
            "result_limit_bytes": intent.result_limit_bytes,
            "approval_required_now": bool(rule.needs_approval or runtime.approvals.requires_approval(call.capability)),
            "execution_admitted": False,
        })
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise AuthorityDenied("queued intent action, target, cost or current policy changed") from exc


def _prepared_seal(kernel, prepared):
    return hmac.digest(kernel._queued_preparation_key, _json({
        "domain": "agentbridge.private-prepared-seal.v1", "tenant_id": prepared.tenant_id,
        "plan_json": prepared.plan_json, "authority_proof": prepared._authority._proof.hex(),
    }).encode(), "sha256")


@contextmanager
def _prepare(kernel, tenant_id, owner_id, task_id, expected_intent_sha256):
    runtime = kernel._runtimes.get(tenant_id)
    if runtime is None or kernel.storage._stores.get(tenant_id) is not runtime.store:
        raise AuthorityDenied("operator-configured tenant runtime required")
    with kernel.directory._guard_queued_intent(runtime.task_intents, owner_id, task_id, expected_intent_sha256) as authority:
        prepared = _PreparedQueuedIntent(tenant_id, _plan(kernel, runtime, authority), authority)
        prepared = replace(prepared, _proof=_prepared_seal(kernel, prepared))
        _assert_prepared(kernel, prepared)
        yield prepared


def _prepared_runtime(kernel, prepared):
    try:
        valid = isinstance(prepared, _PreparedQueuedIntent) and isinstance(prepared._proof, bytes) and \
            hmac.compare_digest(prepared._proof, _prepared_seal(kernel, prepared))
    except (TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise AuthorityDenied("unverified queued preparation")
    runtime = kernel._runtimes.get(prepared.tenant_id)
    if runtime is None or kernel.storage._stores.get(prepared.tenant_id) is not runtime.store:
        raise AuthorityDenied("prepared tenant runtime changed")
    return runtime


def _assert_admission_lifetime(kernel, prepared):
    runtime = _prepared_runtime(kernel, prepared)
    _assert_queued_lifetime(kernel.directory, prepared._authority, runtime.task_intents)


def _assert_prepared(kernel, prepared):
    runtime = _prepared_runtime(kernel, prepared)
    kernel.directory._assert_queued_intent(prepared._authority, runtime.task_intents)
    if _plan(kernel, runtime, prepared._authority) != prepared.plan_json:
        raise AuthorityDenied("queued preparation changed")
    return prepared
