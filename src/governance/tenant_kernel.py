"""Authenticated tenant facade over the existing governance kernel.

Runtime namespaces are operator-bound. Each public session method revalidates
current authority. This module does not automatically convert legacy ingress or
activate unassigned historical stores. Async task execution is a separate layer.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import secrets
from dataclasses import dataclass
from functools import wraps
from types import MappingProxyType

from ..api.trusted_targets import resolve_target, validate_cost
from ..protocols import default_registry
from ..protocols.durable_task_lifecycle import DurableTaskLifecycle
from .audit import AuditLog
from .audit_trust import AuditTrustStore
from .authority import AuthorityDenied, Principal, _identifier, _scopes, _subject
from .budget import BudgetManager
from .durable_policy import DurableApprovalQueue, DurablePolicySet
from .gateway import GovernanceGateway
from .identity import IdentityRegistry
from .operation_ledger import OperationLedger
from .policy import PolicyEngine
from .policy_rules import PolicyContext
from .rbac import require
from .store import sql_atomic
from .task_admission import TaskAdmissionStore
from .task_intents import IntentLimits, TaskIntentStore, parse_submission
from .tenant_store import TenantStoreRegistry


def binding_owner(binding):
    """Stable exact-scope ownership, never authority to mint a principal.

    Exclude grant identity/revisions and request lifetime so a legitimate
    same-scope renewal retains access. Include agent and complete scope to
    prevent a narrow delegate inheriting the human's broader history.
    Missing historical material is unassigned authority, not an empty default.
    """
    try:
        if not isinstance(binding, dict) or binding["kind"] not in ("machine", "delegated_human"):
            raise ValueError("agent resource owner required")
        issuer = binding["issuer"]
        if not isinstance(issuer, str) or not 1 <= len(issuer) <= 2048 or any(ord(c) < 32 for c in issuer):
            raise ValueError("invalid issuer")
        material = {
            "domain": "agentbridge.resource-owner.v2",
            "tenant_id": _identifier(binding["tenant_id"], "tenant_id"),
            "kind": binding["kind"],
            "issuer": issuer,
            "subject": _subject(binding["subject"]),
            "agent_id": _identifier(binding["agent_id"], "agent_id"),
            "capabilities": _scopes(binding["capabilities"]),
            "targets": _scopes(binding["targets"]),
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityDenied("resource ownership is incomplete or unavailable") from exc


def principal_owner(principal):
    return binding_owner(principal.binding())


@dataclass(frozen=True)
class _Runtime:
    store: object
    identities: IdentityRegistry
    budgets: BudgetManager
    approvals: DurableApprovalQueue
    rules: DurablePolicySet
    audit: AuditLog
    policy: PolicyEngine
    gateway: GovernanceGateway
    operations: OperationLedger
    tasks: DurableTaskLifecycle
    task_intents: TaskIntentStore
    task_admissions: TaskAdmissionStore
    audit_trust: AuditTrustStore


class TenantKernel:
    def __init__(self, directory, stores, *, costs, targets=None, deadline_seconds=30):
        if (
            isinstance(deadline_seconds, bool)
            or not isinstance(deadline_seconds, (int, float))
            or not math.isfinite(deadline_seconds)
            or not 0.05 <= deadline_seconds <= 120
        ):
            raise ValueError("bounded request deadline required")
        self.directory = directory
        self.storage = TenantStoreRegistry(directory, stores)
        self.deadline_seconds = deadline_seconds
        self.registry = default_registry
        self._queued_preparation_key = secrets.token_bytes(32)
        self.environment = os.getenv("AGENTBRIDGE_ENV", "development").lower()
        self.costs = MappingProxyType(
            {t: MappingProxyType({c: validate_cost(v) for c, v in schedule.items()}) for t, schedule in costs.items()}
        )
        targets = json.loads(json.dumps(targets or {}, allow_nan=False))
        self._target_env = MappingProxyType(
            {
                tenant: MappingProxyType(
                    {
                        "AGENTBRIDGE_ENV": self.environment,
                        "AGENTBRIDGE_TARGETS_JSON": json.dumps(targets.get(tenant, {})),
                        "AGENTBRIDGE_EGRESS_PROXY_URL": os.getenv("AGENTBRIDGE_EGRESS_PROXY_URL", ""),
                    }
                )
                for tenant in stores
            }
        )
        runtimes = {}
        for tenant, store in stores.items():
            identities = IdentityRegistry(store)
            budgets = BudgetManager(store)
            approvals = DurableApprovalQueue(store)
            rules = DurablePolicySet(store)
            audit = AuditLog(store)
            policy = PolicyEngine(
                identities, budgets, approvals=approvals, policy_set=rules, authority=directory, tenant_id=tenant
            )
            gateway = GovernanceGateway(
                identities=identities,
                budgets=budgets,
                approvals=approvals,
                policy=policy,
                audit=audit,
                authority=directory,
                tenant_id=tenant,
            )
            operations = gateway._operation_ledger()
            tasks = DurableTaskLifecycle(store)
            task_intents = TaskIntentStore(store, tasks)
            task_admissions = TaskAdmissionStore(store)
            audit_trust = AuditTrustStore(store)
            store.seal_writes()
            runtimes[tenant] = _Runtime(
                store, identities, budgets, approvals, rules, audit, policy, gateway, operations, tasks,
                task_intents, task_admissions, audit_trust
            )
        self._runtimes = MappingProxyType(runtimes)
        for runtime in runtimes.values():
            runtime.gateway._queued_kernel = self

    def session(self, principal, *, tenant_id=None):
        store = self.storage.resolve(principal, tenant_id=tenant_id)
        return TenantSession(self, principal, store.tenant_id)

    def _prepare_queued_intent(self, tenant_id, owner_id, task_id, expected_intent_sha256):
        """Private preparation only; no execution or reusable request authority."""
        from .queued_intent_preparation import _prepare

        return _prepare(self, tenant_id, owner_id, task_id, expected_intent_sha256)

    def _assert_prepared_queued_intent(self, prepared):
        from .queued_intent_preparation import _assert_prepared

        return _assert_prepared(self, prepared)

    def _admit_queued_intent(self, tenant_id, owner_id, task_id, expected_intent_sha256):
        """Private first admission only; returns durable metadata, never an action."""
        with self._prepare_queued_intent(tenant_id, owner_id, task_id, expected_intent_sha256) as prepared:
            return self._runtimes[tenant_id].gateway._admit_queued_intent(prepared)

    def _queued_admission(self, tenant_id, owner_id, task_id, expected_intent_sha256):
        runtime = self._runtimes.get(tenant_id)
        if runtime is None or self.storage._stores.get(tenant_id) is not runtime.store:
            raise AuthorityDenied("operator-bound admission store required")
        return runtime.task_admissions.get(owner_id, task_id, expected_intent_sha256)

    def _link_queued_admission(self, gateway, prepared, request_scope, token, decision):
        from .task_admission import _link

        return _link(gateway, prepared, request_scope, token, decision)


def _guarded(*, write=False):
    def decorate(method):
        @wraps(method)
        def guarded(self, *args, **kwargs):
            with self.kernel.directory.guard(self.principal, write=write):
                return method(self, *args, **kwargs)

        return guarded

    return decorate


@dataclass(frozen=True)
class TenantSession:
    kernel: TenantKernel
    principal: Principal
    tenant_id: str

    def _runtime(self, permission=None):
        store = self.kernel.storage.resolve(self.principal, tenant_id=self.tenant_id)
        if permission is not None:
            role = {
                "platform_admin": "admin",
                "tenant_admin": "admin",
                "tenant_operator": "operator",
                "tenant_viewer": "viewer",
            }.get(self.principal.kind)
            if role is None:
                raise AuthorityDenied("operator authority required")
            require(role, permission)
        runtime = self.kernel._runtimes[self.tenant_id]
        if runtime.store is not store:
            raise AuthorityDenied("tenant runtime binding changed")
        return runtime

    def _audit(self, runtime, action):
        actor = "principal:v1:" + json.dumps(
            {**self.principal.binding(), "resource_tenant_id": self.tenant_id}, sort_keys=True, separators=(",", ":")
        )
        runtime.audit.record(
            actor=actor,
            action=action,
            source_protocol="mcp",
            target_protocol="mcp",
            capability="administration",
            decision="allow",
        )

    @_guarded(write=False)
    def list_identities(self):
        runtime = self._runtime("identities:read")
        return runtime.store.list_identities()

    @_guarded(write=True)
    def enroll_agent(self, agent_id, public_key_hex, *, capabilities=(), targets=()):
        runtime = self._runtime("identities:write")
        self.kernel.directory.enroll_agent(
            self.principal, self.tenant_id, agent_id, public_key_hex, capabilities=capabilities, targets=targets
        )
        runtime.identities.register_public_key(agent_id, public_key_hex.lower())
        self._audit(runtime, "enroll_agent")

    @_guarded(write=True)
    def revoke_agent(self, agent_id):
        runtime = self._runtime("identities:write")
        self.kernel.directory.revoke_agent(self.principal, self.tenant_id, agent_id)
        runtime.identities.revoke(agent_id)
        self._audit(runtime, "revoke_agent")

    @_guarded(write=False)
    def set_budget(self, agent_id, *, spend_limit, rate_limit=1000, window_seconds=3600):
        runtime = self._runtime("budgets:write")
        spend_limit = validate_cost(spend_limit)
        if (
            type(rate_limit) is not int
            or not 1 <= rate_limit <= 1000000
            or type(window_seconds) is not int
            or not 1 <= window_seconds <= 31536000
        ):
            raise ValueError("bounded budget rate/window required")

        def mutate(state):
            runtime.budgets._seed(agent_id, state)
            exposure = state.get("spent", 0) + sum(state.get("reserved", {}).values())
            if spend_limit < exposure:
                raise ValueError("spend limit cannot remove existing spend or outstanding exposure")
            state.update(spend_limit=spend_limit, rate_limit=rate_limit, window_seconds=window_seconds)

        runtime.store.mutate_budget(agent_id, mutate)
        self._audit(runtime, "set_budget")

    @_guarded(write=False)
    def get_budget(self, agent_id):
        return self._runtime("budgets:read").budgets.get(agent_id).state()

    @_guarded(write=True)
    def set_quotas(self, **limits):
        from .admission_quotas import QuotaLimits
        runtime = self._runtime("policy:write")
        runtime.gateway._operation_ledger()
        runtime.gateway._quotas.set_policy(QuotaLimits(**limits), audit=lambda: self._audit(runtime, "set_quotas"))

    @_guarded(write=False)
    def get_quotas(self):
        runtime = self._runtime("budgets:read")
        runtime.gateway._operation_ledger()
        return runtime.gateway._quotas.inspect()

    @_guarded(write=False)
    def task_history_capacity(self):
        return self._runtime("budgets:read").tasks.history_capacity()

    @_guarded(write=True)
    def set_task_history_capacity(self, max_tasks):
        runtime = self._runtime("policy:write")
        runtime.tasks.set_history_capacity(max_tasks, audit=lambda: self._audit(runtime, "set_task_history_capacity"))

    @_guarded(write=False)
    def task_event_capacity(self):
        return self._runtime("budgets:read").tasks.event_capacity()

    @_guarded(write=True)
    def set_task_event_capacity(self, max_event_bytes):
        runtime = self._runtime("policy:write")
        runtime.tasks.set_event_capacity(max_event_bytes, audit=lambda: self._audit(runtime, "set_task_event_capacity"))

    @_guarded(write=False)
    def pending_approvals(self):
        return self._runtime("approvals:read").approvals.pending()

    @_guarded(write=False)
    def approve(self, request_id, *, granted=True):
        runtime = self._runtime("approvals:write")
        result = runtime.approvals.approve(request_id) if granted else runtime.approvals.deny(request_id)
        if result:
            self._audit(runtime, "approve" if granted else "deny")
        return result

    @_guarded(write=True)
    def mark_sensitive(self, capability):
        runtime = self._runtime("policy:write")
        with sql_atomic(runtime.store):
            runtime.approvals.mark_sensitive(capability)
            self._audit(runtime, "mark_sensitive")

    @_guarded(write=True)
    def add_policy(self, rule):
        runtime = self._runtime("policy:write")
        with sql_atomic(runtime.store):
            runtime.rules.add(rule)
            self._audit(runtime, "add_policy")

    @_guarded(write=False)
    def policy_rules(self):
        return self._runtime("policy:read").rules.rules

    @_guarded(write=False)
    def audit_records(self):
        return self._runtime("audit:read").store.load_audit()

    @_guarded(write=False)
    def export_audit(self):
        return self._runtime("audit:export").audit.export_jsonl()

    @_guarded(write=False)
    def set_legal_hold(self, name, enabled):
        runtime = self._runtime("audit:export")
        if type(enabled) is not bool:
            raise ValueError("explicit hold boolean required")
        runtime.audit_trust.set_hold(name, enabled)
        self._audit(runtime, "set_legal_hold")

    @_guarded(write=False)
    def operation(self, agent_id, operation_id):
        runtime = self._runtime()
        if self.principal.kind in ("machine", "delegated_human"):
            binding = runtime.operations.authority_binding(agent_id, operation_id)
            if binding is None or binding_owner(binding) != principal_owner(self.principal):
                raise AuthorityDenied("operation unavailable for authenticated principal")
        else:
            self._runtime("audit:read")
        row = runtime.operations.get(agent_id, operation_id)
        if row is None:
            raise AuthorityDenied("operation unavailable")
        return {**row, "authority": runtime.operations.authority_binding(agent_id, operation_id)}

    @_guarded(write=False)
    def task(self, task_id):
        runtime = self._runtime()
        return runtime.tasks.get(principal_owner(self.principal), task_id)

    @_guarded(write=False)
    def task_events(self, task_id, *, after_sequence=-1, limit=100):
        runtime = self._runtime()
        return runtime.tasks.events(
            principal_owner(self.principal), task_id, after_sequence=after_sequence, limit=limit
        )

    @_guarded(write=False)
    def task_intent(self, task_id):
        runtime = self._runtime()
        return runtime.task_intents.get(principal_owner(self.principal), task_id)

    @_guarded(write=False)
    def task_intent_capacity(self):
        return self._runtime("budgets:read").task_intents.capacity()

    @_guarded(write=True)
    def set_task_intent_capacity(self, **limits):
        runtime = self._runtime("policy:write")
        runtime.task_intents.set_capacity(
            IntentLimits(**limits), audit=lambda: self._audit(runtime, "set_task_intent_capacity")
        )

    @_guarded(write=False)
    def submit_task(self, body, *, nonce):
        """Persist scope-authorized intent only; fresh execution admission is pending."""
        runtime = self._runtime()
        directory, principal = self.kernel.directory, self.principal
        directory.assert_request(principal, body=body, nonce=nonce)
        request = parse_submission(body)
        try:
            self.kernel.registry.get(request.dst)
            call = self.kernel.registry.get(request.src).to_canonical_call(request.wire)
            self.kernel.registry.translate_call(request.wire, request.src, request.dst)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError("unsupported protocol or malformed action") from exc
        directory.authorize(principal, call.capability, request.target_id)
        with directory._transaction() as cur:
            enrolled = directory._agent(cur, self.tenant_id, principal.agent_id)
        identity = runtime.identities.get(principal.agent_id)
        if not runtime.identities.is_registered(principal.agent_id) or identity is None or \
                identity.public_key_hex != enrolled["public_key_hex"]:
            raise AuthorityDenied("tenant identity and enrollment disagree")
        schedule = self.kernel.costs.get(self.tenant_id, {})
        if call.capability not in schedule:
            raise AuthorityDenied("operator-owned tenant cost schedule missing")
        cost = schedule[call.capability]
        target = resolve_target(
            request.target_id, request.dst, call.capability, agent_id=principal.agent_id,
            env=self.kernel._target_env[self.tenant_id],
        )
        # The full PolicyEngine gate may seed/prune budget state and request
        # approvals. Evaluate only existing pure rules here. Approval and budget
        # admission, policy refresh and target revalidation belong to execution.
        with sql_atomic(runtime.store):
            rule = runtime.rules.evaluate(PolicyContext(
                agent_id=principal.agent_id, capability=call.capability, cost=cost,
                src_protocol=request.src, dst_protocol=request.dst,
            ))
            if not rule.allowed:
                raise AuthorityDenied("current declarative policy denies queued intent")
            provenance = {
                "authentication": "enrolled-tenant-request-v2",
                "authority": principal.binding(),
                "authorization_expires_at": principal.valid_until,
                "request_body": body.decode("utf-8"),
                "request_body_sha256": hashlib.sha256(body).hexdigest(),
                "request_nonce": nonce,
                "signer_public_key_hex": enrolled["public_key_hex"],
                "capability": call.capability,
                "operator_cost": cost,
                "target_configuration_sha256": hashlib.sha256(json.dumps(
                    target, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()).hexdigest(),
                "approval_required_at_submission": bool(
                    rule.needs_approval or runtime.approvals.requires_approval(call.capability)
                ),
            }

            def accepted(fingerprint):
                directory.authorize(principal, call.capability, request.target_id)
                runtime.audit.record(
                    actor="principal:v1:" + json.dumps(principal.binding(), sort_keys=True, separators=(",", ":")),
                    action="task.submit", source_protocol=request.src, target_protocol=request.dst,
                    capability=call.capability, decision="allow", cost=0.0,
                    reason="queued intent sha256:" + fingerprint + "; fresh execution admission required",
                )

            return runtime.task_intents._accept(principal_owner(principal), request, provenance, audit=accepted)

    async def route(self, body, *, nonce):
        runtime = await asyncio.to_thread(self._runtime)
        principal = self.principal
        await asyncio.to_thread(self.kernel.directory.assert_request, principal, body=body, nonce=nonce)
        try:
            request = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("JSON request required") from exc
        if (
            not isinstance(request, dict)
            or "target" in request
            or "principal" in request
            or ("tenant_id" in request and request["tenant_id"] != self.tenant_id)
        ):
            raise AuthorityDenied("caller-selected authority or target configuration prohibited")
        src, dst, wire = request.get("src"), request.get("dst"), request.get("wire")
        try:
            self.kernel.registry.get(dst)
            call = self.kernel.registry.get(src).to_canonical_call(wire)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("unsupported protocol or malformed action") from exc
        capability = call.capability
        await asyncio.to_thread(self.kernel.directory.authorize, principal, capability, request.get("target_id"))
        schedule = self.kernel.costs.get(self.tenant_id, {})
        if capability not in schedule:
            raise AuthorityDenied("operator-owned tenant cost schedule missing")
        target = resolve_target(
            request.get("target_id"),
            dst,
            capability,
            agent_id=principal.agent_id,
            env=self.kernel._target_env[self.tenant_id],
        )

        async def invoke(translated):
            from ..proxy.transport import invoke_target

            return await invoke_target(dst, translated, target, registry=self.kernel.registry)

        async with asyncio.timeout(self.kernel.deadline_seconds):
            return await runtime.gateway.route_call(
                agent_id=principal.agent_id,
                src_proto=src,
                dst_proto=dst,
                src_wire=wire,
                invoke=invoke,
                cost=schedule[capability],
                target_id=request.get("target_id"),
                operation_id=request.get("operation_id"),
                signed_body=body,
                signed_nonce=nonce,
                principal=principal,
            )
