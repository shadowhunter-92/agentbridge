"""Routine audit telemetry must not deserialize all historical evidence."""
from src.governance.audit import AuditLog


def append(log):
    return log.record(actor="worker", action="route_call", source_protocol="mcp",
                      target_protocol="a2a", capability="read", decision="allow")


def test_sql_startup_and_append_count_head_do_not_load_entire_history(network_sql_stores, monkeypatch):
    store = network_sql_stores()
    def forbidden():
        raise AssertionError("hot path loaded all historical audit entries")
    monkeypatch.setattr(store, "load_audit", forbidden)
    audit = AuditLog(store)
    assert audit.count() == 0
    assert audit.head_hash() == AuditLog.GENESIS
    entry = append(audit)
    assert audit.count() == 1
    assert audit.head_hash() == entry.entry_hash


def test_counts_and_head_observe_other_worker_and_restart_without_full_read(network_sql_stores, monkeypatch):
    first, second = network_sql_stores(), network_sql_stores()
    writer, reader = AuditLog(first), AuditLog(second)
    entry = append(writer)
    assert reader.count() == 1
    assert reader.head_hash() == entry.entry_hash
    for _ in range(15):
        entry = append(writer)
    def forbidden():
        raise AssertionError("routine count/head must not read historical evidence")
    monkeypatch.setattr(second, "load_audit", forbidden)
    restarted = AuditLog(second)
    assert restarted.count() == 16
    assert restarted.head_hash() == entry.entry_hash
    # Explicit full-chain verification/export continue to read full evidence.
    assert writer.verify_integrity()
    assert len(writer.export_jsonl().splitlines()) == 16
