"""Controller-signed destination/observer key histories for bounded deployments.

Only public keys and signed configuration are stored. Controllers must be pinned
outside the governed database. A restored journal needs externally retained
minimum revisions; signatures alone cannot prove the latest revision was served.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .observer_key_registry import ObserverKey, ObserverTrustRegistry, validate_rotation
from .store import PostgresStore, SqliteStore


class TrustJournalDenied(ValueError):
    pass


def _hex(value, length):
    return isinstance(value, str) and len(value) == length and all(c in "0123456789abcdef" for c in value)


def canonical_registry_payload(envelope):
    """Signing contract: exact domain, sequence, predecessor and ordered key list."""
    return b"agentbridge-signing-registry-v1:" + json.dumps(
        {k: envelope[k] for k in ("domain", "revision", "previous_sha256", "keys")},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def registry_digest(envelope):
    return hashlib.sha256(canonical_registry_payload(envelope)).hexdigest()


class SigningTrustJournal:
    """Authenticated, append-only application policy; not WORM/HSM custody.

    Rotation and settlement share a transaction lock. Independent processes
    reload and validate the current history rather than caching active keys.
    The same store instance must be used by Reconciliation. Minimum revisions
    are operator inputs, never supplied by the party submitting evidence.
    """

    _LOCK = 911005

    def __init__(self, store, *, controller_keys, minimum_revisions=None):
        if not isinstance(store, (SqliteStore, PostgresStore)):
            raise TrustJournalDenied("durable governance store required")
        if not isinstance(controller_keys, dict) or set(controller_keys) != {
            "destination",
            "readback",
        }:
            raise TrustJournalDenied("pin both registry controller public keys")
        if any(not _hex(k, 64) for k in controller_keys.values()):
            raise TrustJournalDenied("canonical controller public keys required")
        floors = {} if minimum_revisions is None else minimum_revisions
        if (
            not isinstance(floors, dict)
            or set(floors) - set(controller_keys)
            or any(type(v) is not int or v < 1 for v in floors.values())
        ):
            raise TrustJournalDenied("positive minimum registry revisions required")
        self.store = store
        self._controllers = dict(controller_keys)
        self._floors = dict(floors)
        with self._transaction() as cur:
            if isinstance(store, PostgresStore):
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (911004,))
            cur.execute(
                "CREATE TABLE IF NOT EXISTS signing_trust_revisions ("
                "domain TEXT NOT NULL, revision INTEGER NOT NULL, envelope TEXT NOT NULL, "
                "PRIMARY KEY(domain, revision))"
            )

    @contextmanager
    def _transaction(self):
        store = self.store
        with store._lock:
            if isinstance(store, SqliteStore):
                store._db.execute("BEGIN IMMEDIATE")
                try:
                    cur = store._db.cursor()
                    try:
                        yield cur
                    finally:
                        cur.close()
                    store._db.execute("COMMIT")
                except BaseException:
                    store._db.execute("ROLLBACK")
                    raise
            else:
                with store._db.transaction(), store._db.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (self._LOCK,))
                    yield cur

    def _verify(self, envelope):
        if not isinstance(envelope, dict) or set(envelope) != {
            "domain",
            "revision",
            "previous_sha256",
            "keys",
            "signature_hex",
        }:
            raise TrustJournalDenied("unexpected registry fields")
        domain = envelope["domain"]
        if not isinstance(domain, str) or domain not in self._controllers:
            raise TrustJournalDenied("unknown registry domain")
        if type(envelope["revision"]) is not int or not 1 <= envelope["revision"] <= 2147483647:
            raise TrustJournalDenied("invalid registry revision")
        if not _hex(envelope["previous_sha256"], 64) or not _hex(envelope["signature_hex"], 128):
            raise TrustJournalDenied("invalid registry signature or predecessor")
        rows = envelope["keys"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
            raise TrustJournalDenied("bounded registry key list required")
        if any(not isinstance(row, dict) or set(row) != {"key_id", "public_key_hex", "state"} for row in rows):
            raise TrustJournalDenied("invalid registry key fields")
        try:
            registry = ObserverTrustRegistry([ObserverKey(**row) for row in rows])
            if [row["key_id"] for row in rows] != sorted(row["key_id"] for row in rows):
                raise ValueError("keys must be ordered by identity")
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(self._controllers[domain])).verify(
                bytes.fromhex(envelope["signature_hex"]),
                canonical_registry_payload(envelope),
            )
        except Exception as exc:
            raise TrustJournalDenied("untrusted registry signature or keys") from exc
        return registry

    def _load(self, cur, domain, *, enforce_floor=True):
        placeholder = "?" if isinstance(self.store, SqliteStore) else "%s"
        cur.execute(
            f"SELECT revision,envelope FROM signing_trust_revisions WHERE domain={placeholder} ORDER BY revision",
            (domain,),
        )
        rows = cur.fetchall()
        previous, registry = None, None
        for row in rows:
            try:
                envelope = json.loads(row["envelope"])
            except (TypeError, ValueError) as exc:
                raise TrustJournalDenied("corrupt registry history") from exc
            candidate = self._verify(envelope)
            expected = 1 if previous is None else previous["revision"] + 1
            predecessor = "0" * 64 if previous is None else registry_digest(previous)
            if (
                row["revision"] != expected
                or envelope["revision"] != expected
                or envelope["domain"] != domain
                or envelope["previous_sha256"] != predecessor
            ):
                raise TrustJournalDenied("registry history was forked or truncated")
            if previous is not None:
                try:
                    validate_rotation(registry, candidate)
                except ValueError as exc:
                    raise TrustJournalDenied("invalid signed key transition") from exc
            previous, registry = envelope, candidate
        if enforce_floor and (previous is None or previous["revision"] < self._floors.get(domain, 1)):
            raise TrustJournalDenied("registry is missing or behind pinned minimum revision")
        return previous, registry

    def publish(self, envelope):
        # Copy JSON-compatible values before verification; retain no caller-owned mutable lists.
        try:
            envelope = json.loads(json.dumps(envelope, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise TrustJournalDenied("invalid registry envelope") from exc
        candidate = self._verify(envelope)
        domain = envelope["domain"]
        with self._transaction() as cur:
            previous, registry = self._load(cur, domain, enforce_floor=False)
            if previous and previous["revision"] < self._floors.get(domain, 1):
                raise TrustJournalDenied("cannot append to rolled-back registry")
            if previous and envelope == previous:
                return registry_digest(previous)
            expected = 1 if previous is None else previous["revision"] + 1
            predecessor = "0" * 64 if previous is None else registry_digest(previous)
            if envelope["revision"] != expected or envelope["previous_sha256"] != predecessor:
                raise TrustJournalDenied("stale or conflicting registry publication")
            if envelope["revision"] < self._floors.get(domain, 1):
                raise TrustJournalDenied("registry publication behind pinned minimum")
            if registry is not None:
                try:
                    validate_rotation(registry, candidate)
                except ValueError as exc:
                    raise TrustJournalDenied("invalid signed key transition") from exc
            p = "?" if isinstance(self.store, SqliteStore) else "%s"
            cur.execute(
                f"INSERT INTO signing_trust_revisions VALUES({p},{p},{p})",
                (domain, expected, json.dumps(envelope, sort_keys=True)),
            )
        self._floors[domain] = max(self._floors.get(domain, 1), expected)
        return registry_digest(envelope)

    def settlement_keys(self, cur, *, destination_key_id, observer_key_id):
        """Called inside the settlement transaction; serializes against rotation."""
        if isinstance(self.store, PostgresStore):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (self._LOCK,))
        result = {}
        for domain, key_id in (
            ("destination", destination_key_id),
            ("readback", observer_key_id),
        ):
            if not isinstance(key_id, str):
                raise TrustJournalDenied("enrolled signing key identities required")
            envelope, registry = self._load(cur, domain)
            try:
                result[domain + "_key_hex"] = registry.resolve_active(key_id)
            except ValueError as exc:
                raise TrustJournalDenied("signing key staged, revoked or unknown") from exc
            self._floors[domain] = envelope["revision"]
            result[domain + "_registry_sha256"] = registry_digest(envelope)
            result[domain + "_revision"] = envelope["revision"]
        result["destination_key_id"] = destination_key_id
        result["observer_key_id"] = observer_key_id
        return result
