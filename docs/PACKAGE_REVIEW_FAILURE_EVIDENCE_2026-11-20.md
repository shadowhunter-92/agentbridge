# Package review failure evidence — November 20, 2026

Status: **PARTIALLY TESTED**. Hosted failure-upload behavior has not run.
This local correction starts from
`f309a35cb5c3ec4164acea5ba2622dc04be6807c`. Publication and an exact-head hosted
run require separate approval; no hosted result is claimed for this change.

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

These checks establish local structure and documentation only. Artifact upload
after a failed audit and downstream hosted job behavior remain unverified in hosted CI
until this exact change is separately approved for publication and exercised in
GitHub Actions. No implementation-mirroring test was added for this one-line
workflow correction.
