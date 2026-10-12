# AgentBridge OSS — independent evaluator kit (alpha)

**Audience:** developers evaluating consequential AI-agent actions and verifiable
evidence. This is an invitation for a **bounded, synthetic/read-only**
evaluation, not an authorized production use.

## 1. Install a fixed review commit

Download the source for a reviewed PR #34 commit and create a Python 3.11/3.12
virtual environment. Install the local wheel using the built artifact from
the CI release-review check. Run `agentbridge --version`, import
`src.governance.trust_sdk.verify_action_evidence`, and run:

```bash
python -m pytest tests/test_trust_sdk_evidence.py \
  tests/test_sandbox_readback_lost_ack.py \
  tests/test_sandbox_observer_service.py -q
```

Never copy signing secrets into issues, logs or evaluation forms.

## 2. What to attempt

- Denied action never dispatches; reusing operation ID does not replay.
- Synthetic destination commits but acknowledgment is dropped: outcome
  remains unknown and reservation is preserved.
- Read-only sandbox observer supplies a separate signed state statement;
  unset, modified or mismatched evidence fails closed.
- Signed operator approval refers to the exact operation and evidence.
- Verify an independently retrieved audit-witness checkpoint.
- Restore an older synthetic governance database with witness state intact;
  detect rollback rather than claiming intact history.

## 3. Questions for an outside evaluator

What framework and tool/protocol are you using? Which human or automated
decisions are consequential? Does the current gateway/framework already
provide precise authorization, outcome recovery and exportable evidence?
How long did first installation and first verified action take? Which
interfaces broke or were confusing? Would you deploy an open-source library
rather than a central gateway? What credible scenario would justify a
paid hosted version and who owns that budget?

## 4. Minimal falsifiable adoption gates

**First 3 independent teams:** reproduce installation and evidence validation
without access to developer internals. Require a feedback log and a recorded
fix per material integration problem.

**Commercial discovery:** at least five qualified buyer interviews in the
same target segment; distinguish urgent, budgeted execution-risk pain from
interest in generic agent interoperability. Do not infer willingness to pay
from opens, stars or meetings.

**Pilot acceptance:** one bounded external action flow with target owner
consent, separately administered readback and security review; contractual
scope forbids unsupervised consequential actions until accepted.

## 5. Scope and nonclaims

Supported protocol scope is limited to the documented SDK/wire subsets;
see `docs/PROTOCOL_COMPATIBILITY_2026.md`. This alpha does not guarantee
exactly-once execution against arbitrary systems, complete MCP/A2A
conformance, independent physical-outcome proof or enterprise certification.

Track outside feedback as GitHub issues only with permission; redact
credentials, organization-sensitive logs and private operational details.
