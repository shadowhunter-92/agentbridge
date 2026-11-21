"""Bounded upstream propagator contracts, not an AgentBridge exploit proof.

Inputs are at most 513 characters; the ordering control prevents regex use on
an oversized input. No long-running stress, network, or consequential action.
"""
import pytest
from opentelemetry import trace
from opentelemetry.trace.propagation import tracecontext


TRACE_ID = "1234567890abcdef1234567890abcdef"
SPAN_ID = "1234567890abcdef"
VALID = f"00-{TRACE_ID}-{SPAN_ID}-01"


def context(value):
    extracted = tracecontext.TraceContextTextMapPropagator().extract({"traceparent": value})
    return trace.get_current_span(extracted).get_span_context()


def test_valid_trace_context_preserves_identity_and_flags():
    result = context(VALID)
    assert result.is_valid and result.is_remote
    assert result.trace_id == int(TRACE_ID, 16)
    assert result.span_id == int(SPAN_ID, 16)
    assert result.trace_flags.sampled


def test_absent_traceparent_leaves_the_default_context_empty():
    extracted = tracecontext.TraceContextTextMapPropagator().extract({})
    assert not trace.get_current_span(extracted).get_span_context().is_valid


@pytest.mark.parametrize("carrier", [{}, {"traceparent": "invalid"}])
def test_missing_or_invalid_carrier_preserves_supplied_context(carrier):
    local_span = trace.NonRecordingSpan(trace.SpanContext(
        trace_id=int(TRACE_ID, 16),
        span_id=int(SPAN_ID, 16),
        is_remote=False,
    ))
    supplied = trace.set_span_in_context(local_span)
    extracted = tracecontext.TraceContextTextMapPropagator().extract(carrier, context=supplied)
    assert extracted is supplied
    assert trace.get_current_span(extracted) is local_span


@pytest.mark.parametrize("value", [
    "",
    "not-a-trace-context",
    f"00-{'0' * 32}-{SPAN_ID}-01",
    f"ff-{TRACE_ID}-{SPAN_ID}-01",
    VALID + "\ninvalid",
])
def test_bounded_invalid_carrier_does_not_create_a_remote_context(value):
    assert len(value) <= 64
    assert not context(value).is_valid


def test_maximum_length_legitimate_context_is_preserved():
    value = VALID + " " * (512 - len(VALID))
    assert len(value) == 512
    assert context(value).is_valid


def test_oversized_carrier_is_not_accepted_as_a_valid_context():
    value = VALID + " " * (513 - len(VALID))
    assert len(value) == 513
    assert not context(value).is_valid


def test_oversized_carrier_refuses_before_regex_processing(monkeypatch):
    value = VALID + " " * (513 - len(VALID))

    def forbidden_regex(*args, **kwargs):
        raise AssertionError("oversized carrier reached regex processing")

    monkeypatch.setattr(tracecontext.re, "search", forbidden_regex)
    assert not context(value).is_valid
