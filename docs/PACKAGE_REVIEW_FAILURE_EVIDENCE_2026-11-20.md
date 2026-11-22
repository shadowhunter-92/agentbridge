# Package review failure evidence — November 20, 2026

**Failure upload: VERIFIED IN CI.** The November 21 run at
`af9450dc5ddce1f569fa7b819b28afebc15dde12` exercised the failure path on
base `f309a35cb5c3ec4164acea5ba2622dc04be6807c`. The November 22 branch update
includes patched main `53882b153df230861ff3b3aa2761ff26c0301327` for the
success-path check. Each result belongs to the commit that ran.

The `package-review` dependency audit writes
`release-review-vulnerabilities.json` and its exit-code record before returning
a nonzero status. The following evidence-upload step previously used the
implicit success condition, so a failed audit prevented those files from being
uploaded. The correction adds `if: always()` only to the existing
`Upload release review evidence` step in `.github/workflows/ci.yml`.

The upload retains its ten literal file paths, pinned upload action, artifact
name and 30-day retention. The paths cover review inventories, digests, SBOM,
audit JSON and exit code, detached manifest and signature, and the ephemeral
**public** key. They contain no directory or wildcard. The private signing key
at `/tmp/review-signing.key` is outside this allowlist, including if its existing
cleanup command was not reached. No upload path or workflow permission is added.

The audit's nonzero exit remains a failure. The subsequent image-build steps
retain their success conditions, and `container-security-review` still has
`needs: package-review` with no override. This correction preserves diagnostics;
it does not resolve an advisory or qualify a release. Earlier failures may leave
some listed evidence files absent; this change does not fabricate them.

Local validation on November 20, 2026:

- YAML parsing and comparison against the baseline confirmed that the upload
  condition is the only workflow change, all ten paths are unchanged, and the
  private key is excluded.
- `python tools/check_documentation.py` checked local Markdown targets.
- `git diff --check` checked patch whitespace.

`actionlint` was not installed locally and was not run. No tool was installed
for this bounded change.

## Hosted failure-path result

The [package review job](https://github.com/shadowhunter-92/agentbridge/actions/runs/44909193518/job/136861169509)
reported the OpenTelemetry API 1.45.1 advisory with audit exit 1. The job
remained failed, and the [dependent container review](https://github.com/shadowhunter-92/agentbridge/actions/runs/44909193518/job/136861504364)
was skipped.

GitHub retained the [release review evidence archive](https://github.com/shadowhunter-92/agentbridge/actions/runs/44909193518/artifacts/14709153352).
The downloaded bytes matched GitHub's SHA-256 digest
`c2e0af0097f8a3548229cf8f998c85fdac81a16a92fc678452e86548b53a9464`.
All ten members matched the fixed allowlist. The advisory JSON and exit-code
file contained the recorded failure, and the archive excluded the signing
private key. The newer head requires its own CI to check the successful
audit, evidence upload and downstream container review together.
