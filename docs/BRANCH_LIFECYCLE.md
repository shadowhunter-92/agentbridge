# Branch lifecycle

The maintained target is main plus one integration line, with short-lived feature
PRs. Current frozen heads, tests and archival recommendations are in
[the branch audit](BRANCH_REVIEW_2026-10-13.md). Historical release branches are
evidence references, not independent production releases.

Preserve exact SHAs and unique behavior before cleanup. Ancestry proves commit
inclusion; a squash merge requires content review. Do not bulk-merge stale heads,
force-push history, delete an open PR target or remove unexplained unique work.
Only the owner may approve online publication, merges and deletion. Protected
historical branches need a separately reviewed retention/deletion decision.
