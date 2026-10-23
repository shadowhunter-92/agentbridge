"""Shared same-store owned-token settlement, without evidence or auth bypasses."""

from __future__ import annotations

from .budget import _checked_cost
from .operation_ledger import OperationConflict
from .store import PostgresStore


def _execute(store, query, values=()):
    return store._db.execute(query.replace("?", "%s") if isinstance(store, PostgresStore) else query, values)


def lock_unknown_operation(store, agent_id, operation_id):
    """Caller owns sql_atomic; trust policy locks, if any, precede this call."""
    if isinstance(store, PostgresStore):
        _execute(store, "SELECT pg_advisory_xact_lock(hashtext(?))", ("operation:" + agent_id + ":" + operation_id,))
    row = _execute(store, "SELECT state,fingerprint FROM agent_operations WHERE agent_id=? AND operation_id=?" +
                   (" FOR UPDATE" if isinstance(store, PostgresStore) else ""), (agent_id, operation_id)).fetchone()
    if row is None or row["state"] != "unknown":
        raise OperationConflict("operation missing or already settled; inspect its durable outcome")
    return row


def settle_owned_reservation(store, budgets, operations, *, agent_id, operation_id, token, outcome, expected_cost=None):
    """The operation is already locked; settle only its exact existing token.

    This function neither creates budget defaults nor accepts a caller-provided
    evidence validator. Concrete gateway/reconciliation participants supply the
    verified outcome and own the encompassing result/lifecycle/audit transaction.
    """
    if outcome not in ("succeeded", "failed") or budgets.store is not store or operations.store is not store:
        raise ValueError("same-store concrete settlement participants required")
    reservation = _execute(store, "SELECT token FROM operation_reservations WHERE agent_id=? AND operation_id=?",
                           (agent_id, operation_id)).fetchone()
    if reservation is None or reservation["token"] != token:
        raise OperationConflict("exact owned operation reservation required")
    if isinstance(store, PostgresStore):
        _execute(store, "SELECT pg_advisory_xact_lock(hashtext(?))", ("budget:" + agent_id,))
    state = store.get_budget(agent_id)
    amount = state.get("reserved", {}).get(token) if isinstance(state, dict) else None
    if type(amount) not in (int, float):
        raise OperationConflict("budget reservation missing; reconcile outcome")
    _checked_cost(amount)
    if expected_cost is not None and amount != expected_cost:
        raise OperationConflict("owned reservation amount does not match admission")
    changed = budgets.commit(agent_id, token) if outcome == "succeeded" else budgets.release(agent_id, token)
    if not changed:
        raise OperationConflict("budget reservation missing; reconcile outcome")
    operations.finish(agent_id, operation_id, outcome)
    return amount
