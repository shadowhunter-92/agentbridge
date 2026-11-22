# Bounded security review scope

**Template / PARTIALLY TESTED.** This is internally prepared scope, not an
independent review. Review executable source
`f309a35cb5c3ec4164acea5ba2622dc04be6807c`; record the actual selected revision
if a later reviewed patch is used.

The demo's entry points are its CLI/stdin approval, optional MCP client
boundary, owned local tool stdio, SQLite state, readback connection and offline
bundle verifier. Client/tool/database administrators are trusted by this local
demo. They are not tenant-hostile isolation boundaries. Public HTTP, task
streams and the generic transport path have separate, larger review scope.

| Boundary | Review focus | Required negative evidence |
| --- | --- | --- |
| Request / identity | Exact action, signer and fingerprint | Changed principal/parameters refuse before success |
| Approval / budget / operation | One-shot request binding, exposure, concurrent claim | Denial, replay and racing claim cannot add an effect or refund UNKNOWN |
| MCP invocation | isError, malformed result, task augmentation, timeout | No error or unsupported task becomes success accounting |
| Destination / fencing | Exact operation, stale epoch, committed lost ACK | At most one controlled effect; no automatic resend |
| Readback / evidence | Expected action, independent verification, freshness | Wrong root/action/signature, stale/missing observation refuse |
| Retained outputs | Synthetic bounded files and local key handling | No private key export; preserve original failures and UNKNOWN |

The broader [review matrix](../../docs/INDEPENDENT_SECURITY_AND_PILOT_REVIEW.md)
and [security policy](../../SECURITY.md) remain applicable. Agree on owner,
scope, systems and disclosure route before accessing anyone else's deployment.
No testing access, credential grant or external engagement is provided here.
The isolated P35 candidate is outside this package pending its separate review.
