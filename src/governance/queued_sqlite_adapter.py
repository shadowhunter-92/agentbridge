"""Operator-provisioned binding to the existing fenced demo and RO observer."""

from __future__ import annotations

import json
import math

from .destination_receipts import canonical_queued_authorization_payload
from .fenced_sqlite_destination import FencedSqliteTarget
from .queued_destination_contract import canonical_queued_json, normalize_queued_descriptor
from .sandbox_readback import SandboxReadOnlyObserver
from .signing_trust_journal import SigningTrustJournal, TrustJournalDenied


class QueuedSqliteAdapter:
    """Provisioned by the embedding operator; no request supplies these signers.

    The callbacks stay private and out of target fingerprints or durable rows.
    Deployment still needs independently administered destination/observer keys
    and read credentials; this supervised local adapter is not production proof.
    """

    def __init__(self, descriptor, *, authorizer_sign, destination_sign, observer_sign, trust_journal=None):
        descriptor = normalize_queued_descriptor(descriptor)
        if not all(callable(signer) for signer in (authorizer_sign, destination_sign, observer_sign)):
            raise ValueError("three operator-provisioned signing callbacks required")
        if trust_journal is not None and not isinstance(trust_journal, SigningTrustJournal):
            raise ValueError("existing configured signing trust journal required")
        self._descriptor_json = canonical_queued_json(descriptor).decode()
        self._authorizer_sign, self._destination_sign, self._observer_sign = authorizer_sign, destination_sign, observer_sign
        self.trust_journal = trust_journal

    @property
    def descriptor(self):
        return json.loads(self._descriptor_json)

    def acquire(self, scope, owner):
        descriptor = self.descriptor
        with FencedSqliteTarget(descriptor["path"], sign=self._destination_sign, queued_descriptor=descriptor) as target:
            epoch = target.acquire(scope=scope, owner=owner, ttl_seconds=math.ceil(descriptor["call_timeout_seconds"]) + 1)
            expiry = target.db.execute("SELECT expires_seconds FROM ab_destination_fences WHERE scope=?", (scope,)).fetchone()[0]
        return epoch, float(expiry)

    def authorize(self, authorization):
        signature = self._authorizer_sign(canonical_queued_authorization_payload(authorization))
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise ValueError("operator authorizer did not issue a valid signature")
        return {**authorization, "signature_hex": signature.hex()}

    def commit(self, authorization, action_bytes):
        descriptor = self.descriptor
        with FencedSqliteTarget(descriptor["path"], sign=self._destination_sign, queued_descriptor=descriptor) as target:
            return target.commit_queued(authorization, action_bytes)

    def observe(self, authorization, action_bytes):
        descriptor = self.descriptor
        with SandboxReadOnlyObserver(descriptor["path"], destination_public_key_hex=descriptor["destination_public_key_hex"],
                                     sign=self._observer_sign) as observer:
            return observer.observe_queued(authorization, action_bytes, descriptor)

    def settlement_trust(self, runtime, cur):
        """Acquire current trust policy before operation/accounting locks."""
        if self.trust_journal is None:
            return {}
        if self.trust_journal.store is not runtime.store:
            raise TrustJournalDenied("queued signing trust must share the exact tenant store")
        descriptor = self.descriptor
        keys = self.trust_journal.settlement_keys(cur, destination_key_id=descriptor["destination_key_id"],
                                                 observer_key_id=descriptor["observer_key_id"])
        if keys["destination_key_hex"] != descriptor["destination_public_key_hex"] or \
                keys["readback_key_hex"] != descriptor["observer_public_key_hex"]:
            raise TrustJournalDenied("current signing trust disagrees with queued descriptor")
        return keys
