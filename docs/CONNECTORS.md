# Connectors and supported protocol servers

AgentBridge translates a documented subset of tool-call shapes. It can connect
to a compatible, operator-approved protocol server through an explicitly selected
transport. Compatibility, authentication and permissions must be verified for
that server and its pinned SDK/version; a protocol name alone is not qualification.

## Bounded local example

Install the project with its MCP extra and run `python examples/quickstart.py`.
That example translates an OpenAI-shaped call and invokes the bundled synthetic
MCP `add` tool over stdio. It does not need third-party credentials.

`AgentClient`, `InlineProxy`, `bridge_tool_call` and direct transport helpers are
developer/embedding interfaces. They do not automatically enforce the HTTP
gateway's signed-agent identity, approvals, budgets or audit policy. The embedding
application owns their destination selection and security controls.

## Governed execution

The legacy HTTP governance path is `/control/route`, using a signed agent
request and an operator-configured `target_id`. The separately constructed
opt-in tenant factory provides `/v2/route` with enrolled tenant/agent/user
authority; it does not tenant-enable the legacy endpoint. See
[tenant runtime](TENANT_RUNTIME_2026-10-14.md). Production configuration also
requires agent/target permissions, capability and cost policy, durable operation
identity and the documented network boundary. Raw agent-selected target
configurations are rejected. Governance covers only that enforced path.

The standalone stdio MCP gateway has a separate outbound origin allowlist and
proxy gate. Enabling a bridge tool there does not add governance budget or
approval checks. External systems still require their own authentication, OAuth
lifecycle, destination enforcement and authoritative readback integration.

See [protocol compatibility](PROTOCOL_COMPATIBILITY_2026.md),
[security policy](../SECURITY.md), [framework integration](INTEGRATIONS.md), and
[current alpha status](CURRENT_ALPHA_STATUS.md).

No server catalog is a promise that every tool or lifecycle feature works.
Evaluate each integration with synthetic/read-only state before proposing a
consented external workflow. Existing Apache-2.0 rights remain unchanged.
