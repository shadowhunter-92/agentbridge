# External Evidence verifier and bounded HTTPS destination review

This experimental increment exposes `tools/verify_external_evidence.py`, which checks an action receipt and readback attestation against **separately supplied** public-key configuration and the exact caller-expected action identity. It rejects missing trust roots, revoked/staged observer keys, changed operation fingerprints, invalid signatures, and stale proofs. The verifier performs no network calls and uses no private credentials.

## Bounded destination interface

The existing `src/governance/https_readback_adapter.py` is reused, not duplicated. Additional tests check that non-HTTPS origins, userinfo, IP-literal hosts, localhost, redirects/paths and non-standard ports are rejected and that absent observer credentials fail before sending any request. Tests use synthetic signed receipts and never send external traffic.

**Do not overclaim:** These checks demonstrate input validation and cryptographic verification, **not** independent observer custody, true third-party destination enforcement, DNS rebinding resistance in a deployed CNI, mTLS, or live remote integration. Actual independent operation requires a distinct administrator to enroll and hold signing keys, manage read-only credentials, attest observed source-of-truth state and control revocation/retention. A test controlled by the same owner cannot close that gate.

## Acceptance

```bash
python -m pip install -e ".[test]"
python -m pytest tests/test_external_evidence_verifier.py tests/test_bounded_https_destination_contract.py tests/test_evidence_sdk_adversarial_contract.py -q
```

For offline verification, independently provision the trust policy and expected action. The evidence bundle contains `receipt`, `readback`, `expected` and `observer_key_id`. The trust policy contains `destination_public_key_hex` and `observers` entries (`key_id`, `public_key_hex`, `state`). The separately retained expected action contains `agent_id`, `operation_id`, `fingerprint`, `outcome` and `external_reference`; it must exactly match the bundle. Never take either the trust roots or the expected action from the evidence producer without independent review.

After installing the wheel, run `agentbridge-verify-evidence --bundle BUNDLE.json --trust TRUST.json --expected EXPECTED.json` from any directory. The source-checkout compatibility command is `python -m tools.verify_external_evidence` with the same flags. Each input is bounded to 1 MiB. The library's legacy `verify_bundle` call remains usable, but only reports externally expected action verification when the separate `expected_action` argument is supplied.

## Remaining external proof

- Independent reviewer with administrative control over observer read-only rights, signing/revocation and key issuance.
- Authorized destination owner permitting bounded synthetic transaction tests, with real destination-side fencing and readback.
- A true HTTPS service running in permitted staging with hostname validation, egress controls, DNS/IPv6 bypass rejection and rotated credentials.
- Immutable third-party retention and independent verification of retained artifacts.

## Recruiting

Two prior developers received updated, non-sensitive invitations via Gmail. No acceptance or independent report is asserted. Five buyer interviews remain to be arranged; no buyer interest, willingness to pay or market validation has been established.
