# Apply AgentBridge GitHub branch protections

**Required: repository owner in an authenticated terminal.** This cannot be completed by the currently connected ChatGPT GitHub app because it has no repository ruleset administration action. Do not send GitHub tokens in chats or PRs.

## Immediate incident containment

A GitHub personal access token was pasted in a conversation. Treat it as exposed: **revoke it now** at https://github.com/settings/personal-access-tokens. Revocation is separate from branch protection. A replacement should be provisioned only with the minimum permissions needed, preferably as short-lived access via `gh auth login` in your own terminal.

## Ruleset bootstrap (no PAT in commands)

```bash
gh auth login
gh auth status
python tools/protect_github_repository.py              # inspect dry-run
python tools/protect_github_repository.py --apply      # owner-approved operation
gh api repos/shadowhunter-92/agentbridge/rulesets
```

Use a local copy of the script from this PR. The script never accepts or prints a token. It applies an active branch ruleset to `main`, `release/*` and `integration/*` with no deletions or force-pushes, PR-only changes, resolved discussions and current passing Python 3.11/3.12 checks. It includes a repository-admin emergency bypass to avoid irreversibly locking a solo-maintainer repository. Review that bypass and audit its use.

**Important limitation:** GitHub does not allow someone to approve their own pull request. Requiring one approving CODEOWNERS review for a sole contributor would deadlock merges. This bootstrap therefore requires a PR but initially sets approving-review count to zero. After appointing an independently trusted maintainer, raise to one approval and enable code-owner review in the ruleset. This is a deliberate *partial* protection, not full mandatory review enforcement.

If GitHub rejects the request, check account plan eligibility and GitHub token permission `Administration: write` on repository `shadowhunter-92/agentbridge`. Do not broaden token scopes indiscriminately.

## Separate GitHub settings

The script cannot enable these account/security switches and must not claim they are active:

- Settings → Code security and analysis: secret scanning, push protection, Dependabot alerts and security updates, CodeQL or equivalent.
- Settings → Security → Private vulnerability reporting where supported.
- Settings → Actions → General: least-privilege default workflow token; require approvals for untrusted external contributors and release environments.
- Configure releases through environment protection, independent artifact signing and an auditable key-custody policy.
- Enable mandatory CODEOWNERS review after a different trusted reviewer can approve.

## Verify

After applying, check `gh api repos/shadowhunter-92/agentbridge/rulesets`, the active ruleset in Settings → Rules → Rulesets, and a safe throwaway PR on a protected branch. Confirm each status context exists; unavailable checks should be corrected before enabling a rule that would deadlock contributions.

**Never treat this documentation or a CODEOWNERS file as proof that GitHub administrative controls are enabled.** Revoke the exposed token regardless of whether the ruleset bootstrap succeeds.
