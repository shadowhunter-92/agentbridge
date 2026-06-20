# AgentBridge Examples

This directory contains working examples that demonstrate every major feature of AgentBridge.

## Quick Start Examples

| File | What it shows | Run time | Governance |
|------|--------------|----------|------------|
| `quickstart.py` | Zero-setup translation: MCP → A2A (no keys, no budgets) | < 5 sec | ❌ No |
| `demo_story.py` | The full 60-second demo — every protocol, governance, budget, audit | ~60 sec | ✅ Yes |

## Protocol-Specific Server Examples

| File | Protocol | What it does |
|------|----------|-------------|
| `mcp_server_agent.py` | MCP | A simple MCP server that exposes `add` and `multiply` tools |
| `a2a_server_agent.py` | A2A | An A2A agent that exposes a `send_message` task |
| `acp_server_agent.py` | ACP | An ACP agent that exposes a `get_weather` skill |

## Live Handshake Examples (real SDK interaction)

| File | What it does | Prerequisites |
|------|-------------|-------------|
| `live_mcp_handshake.py` | Starts a real MCP server, bridges to it, and validates the response | `pip install mcp` |
| `live_a2a_handshake.py` | Starts an A2A agent, bridges to it, and validates against the A2A SDK | `pip install a2a-sdk` |
| `live_nprotocol_proxy.py` | Demonstrates routing a live tool call across the canonical mesh | All protocol SDKs installed |
| `live_governed_proxy.py` | Same as above, but with identity + budget + audit enabled | Governance configured |
| `live_inline_proxy.py` | Direct proxy between a real A2A agent and a real MCP server | Both SDKs installed |

## Integration Examples

| File | What it shows |
|------|--------------|
| `github_mcp_bridge.py` | How to use the GitHub MCP bridge |
| `policy_guardrails_demo.py` | Policy engine: deny, cost caps, business hours, approvals |

## Running an Example

```bash
# Basic (no governance)
python examples/quickstart.py

# With governance (requires env setup)
export AGENTBRIDGE_ADMIN_KEY=dev
export AGENTBRIDGE_DB=agentbridge.db
python examples/demo_story.py

# Or use the Makefile shortcut
make demo
```

## Adding a New Example

If you create a new example, please:
1. Add a `.py` file in this directory
2. Update this README with a one-line description
3. Make sure it runs with `python examples/your_example.py`
4. Keep it focused — one concept per example
