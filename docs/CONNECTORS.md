# Connectors — reach any tool, without building connectors

A common question: "does AgentBridge have a GitHub / Slack / Notion connector?" The honest,
architectural answer is that **you don't build connectors for AgentBridge — you point it at the
tool's existing protocol server.** That's the whole advantage of being a *bridge* instead of a
*connector catalog*.

## The model

Most real tools now ship an **MCP server** (and increasingly an **A2A agent**). AgentBridge
already speaks MCP, A2A, ACP, OpenAI, Gemini and AGNTCY — so it routes a call from *any* of
those to the tool's server, and (optionally) governs it with identity / budget / audit.

```
Your agent (any protocol) ──▶ AgentBridge (translate + govern) ──▶ Tool's MCP/A2A server ──▶ Tool
```

No per-tool adapter code. No OAuth refresh logic to maintain. When the tool updates its MCP
server, you get the update for free.

## Worked example: GitHub

GitHub ships an MCP server. Reaching it through AgentBridge — discover its tools, call it
directly, or bridge an OpenAI-shaped call to it, governed — is `examples/github_mcp_bridge.py`:

```bash
set GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxx
python examples/github_mcp_bridge.py     # needs Node (the GitHub MCP server runs via npx)
```

Or with the human client:

```bash
python -m src.serve.agent_client discover --mcp "npx -y @modelcontextprotocol/server-github"
python -m src.serve.agent_client call --mcp "npx -y @modelcontextprotocol/server-github" \
    --tool search_repositories --args '{"query":"agent governance"}'
```

## Tools you can reach today (a sample — all via their MCP servers)

| Tool | Server | How |
|------|--------|-----|
| **GitHub** | official GitHub MCP server | `npx -y @modelcontextprotocol/server-github` |
| **Slack** | Slack MCP server | community/official MCP server (stdio/HTTP) |
| **Notion** | Notion MCP server | official Notion MCP server |
| **Sentry / Linear / Stripe / Postgres / Filesystem / …** | their MCP servers | point `--mcp` at the server command |

The catalog of public MCP servers is large and growing (see e.g. the `awesome-mcp-servers`
list); each one is reachable through AgentBridge with governance applied, the moment you point
the bridge at it.

## When *would* you build a native connector?

Only if a paying customer needs a tool that has **no** MCP/A2A server and you want to ship it
first-party. Then it goes in `src/serve/` as an MCP-tool the bridge can serve. Until then,
building and maintaining an OAuth connector catalog (the Composio model) is a different,
full-time product — not where a neutral bridge's value lies.

## Governance applies to every tool call

Because the call flows through the gateway, the same controls (Ed25519 identity, per-agent
budget, human-in-the-loop approval, hash-chained audit, policy rules) apply to a GitHub or
Slack call exactly as they do to any other — see `docs/ENTERPRISE.md`. That is the thing a raw
connector catalog does not give you.
