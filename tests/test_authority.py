"""Authority comes from enrolled keys/issuers, never caller-selected tenant data."""
import dataclasses
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.api.auth_oidc import OidcConfig, OidcVerifier
from src.governance.authority import (
    AuthorityDenied,
    AuthorityDirectory,
    AuthorityMigrationDenied,
    Principal,
    sign_tenant_request,
)
from src.governance.identity import AgentIdentity

ISSUER = "https://identity.example.test"
OTHER_ISSUER = "https://other-identity.example.test"


@pytest.fixture
def authority(network_sql_stores):
    keys = {issuer: Ed25519PrivateKey.generate() for issuer in (ISSUER, OTHER_ISSUER)}
    verifiers = {issuer: OidcVerifier(OidcConfig(
        issuer=issuer, audience="agentbridge-authority", algorithms=("EdDSA",),
        public_key_pem=key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
    )) for issuer, key in keys.items()}

    def token(subject, *, issuer=ISSUER, tenant=None, **extra):
        claims = {"iss": issuer, "aud": "agentbridge-authority", "sub": subject,
                  "exp": time.time() + 1800, **extra}
        if tenant is not None:
            claims["tenant_id"] = tenant
        return jwt.encode(claims, keys[issuer], algorithm="EdDSA")

    directory = AuthorityDirectory(network_sql_stores(), verifiers=verifiers)
    directory.bootstrap_platform_admin(ISSUER, "owner")
    owner = directory.authenticate_operator(ISSUER, token("owner"))
    for tenant in ("alpha", "beta"):
        directory.set_tenant(owner, tenant, active=True)
        directory.enroll_member(owner, tenant, ISSUER, "administrator", role="tenant_admin",
                                capabilities=("read", "write"), targets=("ledger",))
        directory.enroll_member(owner, tenant, ISSUER, "human", role="tenant_operator",
                                capabilities=("read",), targets=("ledger",))
    return directory, owner, token, network_sql_stores, verifiers


def agent_request(directory, tenant="alpha", identity=None, delegation=None, body=b'{"action":"read"}', nonce=None):
    identity = identity or AgentIdentity.generate("worker")
    nonce = nonce or f"{time.time()}:{uuid.uuid4().hex}"
    signature = sign_tenant_request(identity, tenant, nonce, body, delegation_id=delegation)
    return directory.authenticate_agent(tenant, identity.agent_id, nonce, body, signature,
                                        delegation_id=delegation)


def enrolled(directory, owner, tenant="alpha", identity=None):
    identity = identity or AgentIdentity.generate("worker")
    directory.enroll_agent(owner, tenant, identity.agent_id, identity.public_key_hex,
                           capabilities=("read", "write"), targets=("ledger",))
    return identity


def test_only_explicit_bootstrap_creates_platform_authority(authority):
    directory, owner, token, _, _ = authority
    assert owner.kind == "platform_admin" and owner.tenant_id is None
    with pytest.raises(AuthorityDenied):
        directory.bootstrap_platform_admin(ISSUER, "attacker")
    with pytest.raises(AuthorityDenied):
        directory.authenticate_operator(ISSUER, token("attacker", role="admin"))
    with pytest.raises(AuthorityDenied):
        directory.authenticate_operator(ISSUER, token("owner", tenant="alpha"))


def test_roles_and_tenant_membership_are_enrolled_not_claimed(authority):
    directory, owner, token, _, _ = authority
    directory.enroll_member(owner, "alpha", ISSUER, "reader", role="tenant_viewer")
    reader = directory.authenticate_operator(ISSUER, token("reader", tenant="alpha", role="platform_admin"), tenant_id="alpha")
    assert reader.kind == "tenant_viewer"
    with pytest.raises(AuthorityDenied):
        directory.set_tenant(reader, "evil", active=True)
    with pytest.raises(AuthorityDenied):
        directory.enroll_agent(reader, "alpha", "evil", AgentIdentity.generate("evil").public_key_hex)
    with pytest.raises(AuthorityDenied):
        directory.authenticate_operator(ISSUER, token("reader", tenant="beta"), tenant_id="alpha")
    with pytest.raises(AuthorityDenied):
        directory.authenticate_operator(OTHER_ISSUER, token("reader", tenant="alpha"), tenant_id="alpha")
    with pytest.raises(AuthorityDenied):
        directory.authenticate_operator(ISSUER, token("reader", tenant="beta"), tenant_id="beta")


def test_operator_requires_expiry_and_configured_verified_issuer(authority):
    directory, _, token, _, _ = authority
    with pytest.raises(AuthorityDenied):
        directory.authenticate_operator("https://untrusted.example.test", token("owner"))
    with pytest.raises(AuthorityDenied):
        directory.authenticate_operator(ISSUER, token("owner", exp=None))
    with pytest.raises(AuthorityDenied):
        directory.authenticate_operator(ISSUER, token("owner", exp=time.time()-10))


def test_tenant_admin_cannot_cross_tenants_or_create_platform_admin(authority):
    directory, _, token, _, _ = authority
    admin = directory.authenticate_operator(ISSUER, token("administrator", tenant="alpha"), tenant_id="alpha")
    with pytest.raises(AuthorityDenied):
        directory.enroll_member(admin, "beta", ISSUER, "evil", role="tenant_admin")
    with pytest.raises(ValueError):
        directory.enroll_member(admin, "alpha", ISSUER, "evil", role="platform_admin")
    with pytest.raises(AuthorityDenied):
        directory.enroll_platform_admin(admin, ISSUER, "evil")
    assert {r["tenant_id"] for r in directory.list_agents(admin, "alpha")} <= {"alpha"}
    with pytest.raises(AuthorityDenied):
        directory.list_agents(admin, "beta")


def test_same_agent_ids_are_isolated_by_enrollment_and_signed_domain(authority):
    directory, owner, _, _, _ = authority
    a = enrolled(directory, owner)
    b = enrolled(directory, owner, "beta")
    assert agent_request(directory, identity=a).tenant_id == "alpha"
    assert agent_request(directory, "beta", b).tenant_id == "beta"
    nonce, body = f"{time.time()}:{uuid.uuid4().hex}", b'{}'
    signature = sign_tenant_request(a, "alpha", nonce, body)
    with pytest.raises(AuthorityDenied):
        directory.authenticate_agent("beta", "worker", nonce, body, signature)
    # Even a key deliberately enrolled in both tenants cannot replay a signed
    # alpha request in beta, because the signature covers the selected domain.
    enrolled(directory, owner, "beta", a)
    with pytest.raises(AuthorityDenied):
        directory.authenticate_agent("beta", "worker", nonce, body, signature)
    assert agent_request(directory, "beta", a).tenant_id == "beta"


def test_unsigned_self_selected_tenant_and_tampering_fail(authority):
    directory, owner, _, _, _ = authority
    a = enrolled(directory, owner)
    nonce, body = f"{time.time()}:{uuid.uuid4().hex}", b'{"tenant_id":"alpha"}'
    signature = sign_tenant_request(a, "alpha", nonce, body)
    with pytest.raises(AuthorityDenied):
        directory.authenticate_agent("new-tenant", "worker", nonce, body, signature)
    with pytest.raises(AuthorityDenied):
        directory.authenticate_agent("alpha", "worker", nonce, body+b' ', signature)
    with pytest.raises(AuthorityDenied):
        directory.authenticate_agent("alpha", "worker", nonce, body, "00"*64)
    with pytest.raises(AuthorityDenied):
        agent_request(directory, identity=a, nonce="not-a-timestamp:"+uuid.uuid4().hex)


def test_principal_is_immutable_and_tamper_evident(authority):
    directory, owner, _, _, _ = authority
    a = enrolled(directory, owner)
    principal = agent_request(directory, identity=a)
    with pytest.raises(dataclasses.FrozenInstanceError):
        principal.tenant_id = "beta"
    with pytest.raises(AuthorityDenied):
        directory.assert_current(dataclasses.replace(principal, tenant_id="beta"))
    with pytest.raises(AuthorityDenied):
        directory.assert_current(dataclasses.replace(principal, kind="platform_admin", tenant_id=None))
    with pytest.raises(AuthorityDenied):
        directory.assert_current(dataclasses.replace(principal, capabilities=("erase",)))
    with pytest.raises(AuthorityDenied):
        directory.assert_current(Principal(None, "owner", ISSUER, "platform_admin", 1))
    directory.authorize(principal, "read", "ledger")
    with pytest.raises(AuthorityDenied):
        directory.authorize(principal, "erase", "ledger")
    with pytest.raises(AuthorityDenied):
        directory.authorize(principal, "read", "different-ledger")


def test_machine_principal_does_not_invent_human_delegation(authority):
    directory, owner, _, _, _ = authority
    a = enrolled(directory, owner)
    p = agent_request(directory, identity=a)
    assert p.kind == "machine" and p.delegation_id is None and p.agent_id == "worker"
    assert p.binding()["tenant_id"] == "alpha"
    assert p.binding()["agent_revision"] == 1
    directory.revoke_agent(owner, "alpha", "worker")
    with pytest.raises(AuthorityDenied):
        directory.authorize(p, "read", "ledger")
    enrolled(directory, owner, identity=a)
    assert agent_request(directory, identity=a).agent_revision == 3
    with pytest.raises(AuthorityDenied):
        directory.assert_current(p)


def delegated(authority):
    directory, owner, token, _, _ = authority
    a = enrolled(directory, owner)
    user = directory.authenticate_operator(ISSUER, token("human", tenant="alpha"), tenant_id="alpha")
    admin = directory.authenticate_operator(ISSUER, token("administrator", tenant="alpha"), tenant_id="alpha")
    grant = directory.grant_delegation(admin, user, "worker", capabilities=("read",), targets=("ledger",), expires_at=time.time()+600)
    return directory, owner, a, user, admin, grant


def test_human_delegation_binds_enrollment_user_scope_and_grantor(authority):
    directory, owner, a, user, admin, grant = delegated(authority)
    p = agent_request(directory, identity=a, delegation=grant)
    assert p.kind == "delegated_human" and p.subject == "human" and p.issuer == ISSUER
    assert p.delegation_id == grant and p.capabilities == ("read",)
    directory.authorize(p, "read", "ledger")
    with pytest.raises(AuthorityDenied):
        directory.authorize(p, "write", "ledger")
    with pytest.raises(AuthorityDenied):
        directory.grant_delegation(admin, user, "worker", capabilities=("write",), targets=("ledger",), expires_at=time.time()+600)
    with pytest.raises(AuthorityDenied):
        directory.grant_delegation(owner, dataclasses.replace(user, subject="administrator"), "worker", capabilities=("read",), targets=("ledger",), expires_at=time.time()+600)
    with pytest.raises(AuthorityDenied):
        directory.grant_delegation(owner, user, "worker", capabilities=("read",), targets=("other",), expires_at=time.time()+600)


@pytest.mark.parametrize("revocation", ["grant", "agent", "user", "grantor", "tenant"])
def test_revocation_is_rechecked_not_cached(authority, revocation):
    directory, owner, a, _, _, grant = delegated(authority)
    p = agent_request(directory, identity=a, delegation=grant)
    if revocation == "grant":
        directory.revoke_delegation(owner, "alpha", grant)
    elif revocation == "agent":
        directory.revoke_agent(owner, "alpha", "worker")
    elif revocation == "user":
        directory.revoke_member(owner, "alpha", ISSUER, "human")
    elif revocation == "grantor":
        directory.revoke_member(owner, "alpha", ISSUER, "administrator")
    else:
        directory.set_tenant(owner, "alpha", active=False)
    with pytest.raises(AuthorityDenied):
        directory.authorize(p, "read", "ledger")
    with pytest.raises(AuthorityDenied):
        agent_request(directory, identity=a, delegation=grant)


def test_grant_selector_cannot_be_swapped_outside_signed_proof(authority):
    directory, _, a, _, _, grant = delegated(authority)
    nonce, body = f"{time.time()}:{uuid.uuid4().hex}", b'{}'
    signature = sign_tenant_request(a, "alpha", nonce, body)
    with pytest.raises(AuthorityDenied):
        directory.authenticate_agent("alpha", "worker", nonce, body, signature, delegation_id=grant)
    p = directory.authenticate_agent("alpha", "worker", nonce, body, signature)
    assert p.kind == "machine"


def test_expired_principal_and_grant_cannot_extend_authority(authority, monkeypatch):
    directory, _, a, _, _, grant = delegated(authority)
    p = agent_request(directory, identity=a, delegation=grant)
    monkeypatch.setattr("src.governance.authority.time.time", lambda: p.valid_until+601)
    with pytest.raises(AuthorityDenied):
        directory.assert_current(p)
    with pytest.raises(AuthorityDenied):
        agent_request(directory, identity=a, delegation=grant)


def test_restart_reauthenticates_persistent_authority_without_reusing_context(authority):
    directory, owner, token, factory, verifiers = authority
    a = enrolled(directory, owner)
    p = agent_request(directory, identity=a)
    restarted = AuthorityDirectory(factory(), verifiers=verifiers)
    with pytest.raises(AuthorityDenied):
        restarted.assert_current(p)
    assert restarted.authenticate_operator(ISSUER, token("owner")).kind == "platform_admin"
    assert agent_request(restarted, identity=a).tenant_id == "alpha"


def test_nonce_claim_is_atomic_across_independent_connections(authority):
    directory, owner, _, factory, verifiers = authority
    a = enrolled(directory, owner)
    workers = [AuthorityDirectory(factory(), verifiers=verifiers) for _ in range(4)]
    nonce = f"{time.time()}:{uuid.uuid4().hex}"
    def claim(worker):
        try:
            agent_request(worker, identity=a, nonce=nonce)
            return True
        except AuthorityDenied:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(claim, workers)).count(True) == 1


def test_additive_schema_does_not_rewrite_legacy_state(authority):
    directory, _, _, factory, verifiers = authority
    store = directory.store
    store.upsert_identity("legacy", AgentIdentity.generate("legacy").public_key_hex)
    store.upsert_budget("legacy", {"spent":3,"reserved":7,"pending":{"unknown-token":7}})
    store.append_audit({"seq":0,"entry_hash":"preserve-exact-old-bytes","legacy":True})
    before = (store.get_identity("legacy"), store.get_budget("legacy"), store.load_audit())
    AuthorityDirectory(factory(), verifiers=verifiers)
    assert before == (store.get_identity("legacy"), store.get_budget("legacy"), store.load_audit())
    # Unknown or modified migration metadata must fail closed.
    with directory._transaction(write=True) as cur:
        cur.execute("UPDATE authority_schema SET digest=? WHERE singleton=1", ("tampered",))
    with pytest.raises(AuthorityMigrationDenied):
        AuthorityDirectory(factory(), verifiers=verifiers)
    assert before == (store.get_identity("legacy"), store.get_budget("legacy"), store.load_audit())


def test_bounded_scopes_and_invalid_enrollments_rejected(authority):
    directory, owner, _, _, _ = authority
    a = AgentIdentity.generate("worker")
    with pytest.raises(ValueError):
        directory.enroll_agent(owner, "alpha", "worker", "bad")
    with pytest.raises(ValueError):
        directory.enroll_agent(owner, "alpha", "worker", a.public_key_hex, capabilities=("*",))
    with pytest.raises(ValueError):
        directory.enroll_agent(owner, "alpha", "worker", a.public_key_hex, capabilities=tuple(str(n) for n in range(129)))
    with pytest.raises(ValueError):
        directory.set_tenant(owner, "../escape", active=True)
    with pytest.raises(AuthorityDenied):
        directory.revoke_platform_admin(owner, ISSUER, "owner")


def test_same_subject_different_issuer_is_not_same_principal(authority):
    directory, owner, token, _, _ = authority
    directory.enroll_member(owner, "alpha", OTHER_ISSUER, "human", role="tenant_viewer")
    first = directory.authenticate_operator(ISSUER, token("human", tenant="alpha"), tenant_id="alpha")
    second = directory.authenticate_operator(OTHER_ISSUER, token("human", issuer=OTHER_ISSUER, tenant="alpha"), tenant_id="alpha")
    assert first.kind == "tenant_operator" and second.kind == "tenant_viewer"
    assert first.binding() != second.binding()


def test_replay_retention_requires_platform_and_keeps_valid_nonces(authority):
    directory, owner, token, _, _ = authority
    a = enrolled(directory, owner)
    nonce = f"{time.time()}:{uuid.uuid4().hex}"
    agent_request(directory, identity=a, nonce=nonce)
    assert directory.prune_replays(owner) == 0
    tenant_admin = directory.authenticate_operator(ISSUER, token("administrator", tenant="alpha"), tenant_id="alpha")
    with pytest.raises(AuthorityDenied):
        directory.prune_replays(tenant_admin)
    with pytest.raises(AuthorityDenied):
        agent_request(directory, identity=a, nonce=nonce)


def test_tenant_reactivation_does_not_revive_old_human_grants(authority):
    directory, owner, a, _, _, grant = delegated(authority)
    directory.set_tenant(owner, "alpha", active=False)
    directory.set_tenant(owner, "alpha", active=True)
    # Existing machine enrollment is explicitly re-enabled with the tenant, but
    # an old consent/grant cannot silently regain authority under a new epoch.
    assert agent_request(directory, identity=a).kind == "machine"
    with pytest.raises(AuthorityDenied):
        agent_request(directory, identity=a, delegation=grant)


def test_authenticated_context_is_bound_to_exact_request_but_renewal_binding_stable(authority):
    directory, owner, _, _, _ = authority
    a = enrolled(directory, owner)
    nonce = f"{time.time()}:{uuid.uuid4().hex}"
    p = agent_request(directory, identity=a, body=b'{}', nonce=nonce)
    directory.assert_request(p, body=b'{}', nonce=nonce)
    with pytest.raises(AuthorityDenied):
        directory.assert_request(p, body=b'{"changed":true}', nonce=nonce)
    with pytest.raises(AuthorityDenied):
        directory.assert_request(p, body=b'{}', nonce='other')
    renewed = agent_request(directory, identity=a, body=b'{}')
    assert p.binding() == renewed.binding()
