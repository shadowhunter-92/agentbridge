# Evaluation checklist

Record executable source `f309a35cb5c3ec4164acea5ba2622dc04be6807c`, the
documentation revision, OS, architecture, Python/Docker/Compose versions and
start/end times. Use only a disposable synthetic workspace.

- [ ] Record installation/download time and every error, including failed attempts.
- [ ] Run `success` with explicit APPROVE. Inspect exactly one destination
      effect, committed accounting and accepted offline verification.
- [ ] Run `denied` with DENY in a fresh directory. Inspect zero effects and
      no success accounting.
- [ ] Run `lost-ack` with APPROVE in a fresh directory. Inspect one effect,
      UNKNOWN, reserved exposure, readback verification and no automatic resend.
- [ ] Run `tool-error` and `timeout` with APPROVE in separate fresh directories.
      Inspect UNKNOWN/reserved exposure and the controlled zero-effect target;
      absence must not be treated as a failed/refunded operation.
- [ ] Run `split-brain` with APPROVE. Inspect bounded concurrent admission:
      at most one effect; it is not a physical HA/partition experiment.
- [ ] Inspect replay refusal in each admitted scenario. A duplicate does not
      obtain a second dispatch.
- [ ] Try the offline verifier against a copied, modified evidence bundle,
      mismatched expected action or wrong public root. It must refuse.
- [ ] Keep original evidence bytes. A stale attestation should fail the
      existing 300-second freshness check; retain earlier verification results.
- [ ] Explain what your existing framework/gateway already covers, the missing
      workflow, integration cost and whether you would run a supervised evaluation.

Native fault syntax, output fields and approval instructions are in the
[demo guide](../../demo/governed-mcp-demo/README.md). Container fault results
must be recorded as container executions; native test success is not a
container result. Do not expand testing to third-party systems without their
owner's authorization.
