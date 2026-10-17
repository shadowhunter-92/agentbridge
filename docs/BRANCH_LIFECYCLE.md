# Branch lifecycle

The intended lifecycle is main, one integration line and short-lived feature
PRs. The recorded draft stack is an explicit exception while review is pending:
PRs #56–#69 are 14 cumulative draft dependencies, ending at `46777f8`; none is
treated as merged by these docs. The October 17 inventory records 19 remote
heads, distinct from older cached counts. See [current alpha status](CURRENT_ALPHA_STATUS.md) and
[branch documentation dispositions](BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md).
The [October 13 branch audit](BRANCH_REVIEW_2026-10-13.md) records its historical
heads/tests. Historical release branches are evidence references, not production
releases. Remote cleanup and retained commit ancestry are distinct facts.

Preserve exact SHAs and unique behavior before cleanup. Ancestry proves commit
inclusion; a squash merge requires content review. Do not bulk-merge stale heads,
force-push history, delete an open PR target or remove unexplained unique work.
Only the owner may approve online publication, merges and deletion. Protected
historical branches need a separately reviewed retention/deletion decision.
