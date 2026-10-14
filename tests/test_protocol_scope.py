"""The documented protocol matrix must match actually registered adapters."""
from src.protocols import default_registry
from src.protocols.canonical import CanonicalCall


REVIEWED_CALL_SUBSET = frozenset(("mcp","a2a","acp","openai","gemini","agntcy"))


def test_registry_matches_declared_supported_call_subsets():
    assert set(default_registry.protocols()) == REVIEWED_CALL_SUBSET


def test_all_registered_adapters_roundtrip_simple_tool_call():
    operation = CanonicalCall("echo", {"text":"safe-read-only"})
    for source in sorted(REVIEWED_CALL_SUBSET):
        wire = default_registry.get(source).from_canonical_call(operation)
        for destination in sorted(REVIEWED_CALL_SUBSET):
            translated = default_registry.translate_call(wire,source,destination)
            canonical = default_registry.get(destination).to_canonical_call(translated)
            assert canonical.capability == "echo", (source,destination)
            assert canonical.arguments == {"text":"safe-read-only"}, (source,destination)
