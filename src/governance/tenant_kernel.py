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
from .rbac import require
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
            operations = OperationLedger(store)
            tasks = DurableTaskLifecycle(store)
            audit_trust = AuditTrustStore(store)
            store.seal_writes()
            runtimes[tenant] = _Runtime(
                store, identities, budgets, approvals, rules, audit, policy, gateway, operations, tasks, audit_trust
            )
        self._runtimes = MappingProxyType(runtimes)

    def session(self, principal, *, tenant_id=None):
        store = self.storage.resolve(principal, tenant_id=tenant_id)
        return TenantSession(self, principal, store.tenant_id)


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

    @_guarded(write=False)
    def mark_sensitive(self, capability):
        runtime = self._runtime("policy:write")
        runtime.approvals.mark_sensitive(capability)
        self._audit(runtime, "mark_sensitive")

    @_guarded(write=False)
    def add_policy(self, rule):
        runtime = self._runtime("policy:write")
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
