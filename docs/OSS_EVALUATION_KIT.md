# AgentBridge OSS — independent evaluator kit (alpha)

**Audience:** developers evaluating consequential AI-agent actions and verifiable
evidence. This is an invitation for a **bounded, synthetic/read-only**
evaluation, not an authorized production use.

## Current evaluation candidate — October 16, 2026

Use exact candidate `d0881b937d2568e4e01fb02044bf466aea609e9a` from
PR #63's then-unmerged stack. This is a historical evaluator source pin;
its 24 hosted checks passed in
[CI run 38846044004](https://github.com/shadowhunter-92/agentbridge/actions/runs/38846044004).
This is not the default branch or a published production release. A local wheel
from this source passed fresh Python 3.11/Linux and 3.12/Windows installations,
hash-locked core dependencies, installed imports outside the checkout, both
synthetic examples, `pip check` and CLI version. These internal checks do not
count as unrelated developer evaluations or installation from a public registry.
The separately prepared evaluator packet records the wheel hash and build tools.
No independent custody or production acceptance is implied.

The wheel remains **local, unsigned and unpublished** at that older source pin;
it is not rebuilt from the cumulative `46777f8` source. Source checkout commands
below install the selected source and dependencies, not this wheel. Do not infer
public-registry availability or trusted provenance from version `1.0.0`.
See [current source/artifact distinction](CURRENT_ALPHA_STATUS.md).

## 1. Source installation for the pinned evaluator

For source evaluation, use the exact older evaluator source explicitly:

```bash
git clone https://github.com/shadowhunter-92/agentbridge.git
cd agentbridge
git checkout --detach d0881b937d2568e4e01fb02044bf466aea609e9a
python -m venv .venv
# Activate the environment before installing.
python -m pip install -e ".[test]"
```

For the separately prepared local wheel, use its packet manifest/hash and clean
installation instructions; no public download is asserted here. The historical
`483bc982` pin below remains historical. Run `agentbridge --version`, import
`src.governance.trust_sdk.verify_action_evidence`, and run:

```bash
python -m pytest tests/test_trust_sdk_evidence.py \
  tests/test_sandbox_readback_lost_ack.py \
  tests/test_sandbox_observer_service.py -q
```

Never copy signing secrets into issues, logs or evaluation forms.

## Fast, reproducible offline example

From a checked-out, pinned reviewed commit in a fresh Python 3.11/3.12
environment, after installing the project dependencies:

```bash
python -m examples.verify_synthetic_action_evidence
```

Expected output includes `signed_receipt_verified: true`,
`separately_signed_readback_verified: true`,
`altered_outcome_rejected: true`, and
`external_production_truth_verified: false`. The example uses an isolated
temporary SQLite destination and two newly generated signing keys. It makes
no network calls and is not evidence of separately administered signing-key
custody or customer-system outcomes.

Record the exact source SHA, operating system, Python version, installation
duration and any command failure. Do not post private keys, API tokens, or
customer data.

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
see [protocol compatibility](PROTOCOL_COMPATIBILITY_2026.md). This alpha does not guarantee
exactly-once execution against arbitrary systems, complete MCP/A2A
conformance, independent physical-outcome proof or enterprise certification.

Track outside feedback as GitHub issues only with permission; redact
credentials, organization-sensitive logs and private operational details.

## Historical independent installation checklist (superseded candidate)

Use **main commit `483bc98234ced2b876a6b296a1e1fd292747942c`**, not a floating
release branch or a version-number-only reference. PR #41 has merged. The exact candidate must pass CI first. Start
from a clean checkout with Python 3.11 or 3.12.

```bash
python -m venv .venv
# Activate it: macOS/Linux source .venv/bin/activate
# Windows PowerShell .venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m examples.verify_synthetic_action_evidence
python -m pytest tests/test_trust_sdk_evidence.py tests/test_fenced_sqlite_destination.py -q
```

No live service, API key, production database or cloud credential is required.
Record the exact commit, platform, Python/pip versions, elapsed setup minutes,
stdout/exit codes (with secrets redacted), and 1–5 ratings for documentation,
installation, conceptual clarity and perceived usefulness.

**Expected negative test:** a modified claimed outcome is rejected; an unknown
remote outcome is not magically resolved. `external_production_truth_verified`
must be false in the demo.

The internal integration candidate's Python 3.11/3.12 job passed on
`6fab0dd798e2e625d8aa33af4f718a75ba0b7455` in CI #366. That is
internal evidence and **not** independent installation evidence. In a
fresh external installation, a submitted report (not an invitation, stars
or a CI badge) is required to close the evaluator milestone.

## Independent feedback submission

Use [`docs/INDEPENDENT_EVALUATOR_REPORT_TEMPLATE.md`](INDEPENDENT_EVALUATOR_REPORT_TEMPLATE.md) for a structured report. Submit it through [the open evaluator invitation](https://github.com/shadowhunter-92/agentbridge/issues/36) only with your consent. A qualifying result needs an external participant, exact commit, fresh-environment output, explicit limitations and reproducible feedback; internal CI alone never counts toward three external integrations.
