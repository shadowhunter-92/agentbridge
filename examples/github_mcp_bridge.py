"""
GitHub "integration" — the right way: reach the LIVE GitHub MCP server through AgentBridge.

There is no GitHub *connector* to build. GitHub ships an MCP server; AgentBridge points at
it and routes (and, if you want, governs) the call. The same pattern reaches Slack, Notion,
Sentry, and the thousands of other tools that now ship MCP servers — see docs/CONNECTORS.md.

PREREQS (this calls the real GitHub API, so it needs your token):
    set GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxx          # a fine-grained or classic PAT
    # the GitHub MCP server is run via npx (Node required):
    #   npx -y @modelcontextprotocol/server-github

Run: python examples/github_mcp_bridge.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.serve.agent_client import AgentClient, AgentRef
from src.integrations import bridge_tool_call
from src.proxy import transport

# How to launch the GitHub MCP server (stdio). The PAT is read from the environment by the
# server itself; we pass it through via the npx command's inherited env.
GITHUB_MCP_CMD = "npx"
GITHUB_MCP_ARGS = ["-y", "@modelcontextprotocol/server-github"]


async def main():
    if not os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN"):
        print("Set GITHUB_PERSONAL_ACCESS_TOKEN first (this example calls the real GitHub API).")
        return

    client = AgentClient()
    gh = AgentRef.mcp(GITHUB_MCP_CMD, GITHUB_MCP_ARGS)

    # 1) DISCOVER what GitHub's MCP server exposes — no connector code, just discovery.
    info = await client.discover(gh)
    print("GitHub MCP tools discovered:", [t["name"] for t in info["tools"]][:10], "...\n")

    # 2) CALL it directly (human -> GitHub agent).
    res = await client.call(gh, tool="search_repositories",
                            arguments={"query": "model context protocol stars:>1000"})
    print("Direct call result (first 300 chars):", " ".join(res.get("raw", []))[:300], "\n")

    # 3) Reach the SAME GitHub tool from an OpenAI-shaped call, GOVERNED through the bridge.
    #    (Any framework that emits OpenAI tool-calls can do this — LangChain, CrewAI, ...)
    out = await bridge_tool_call(
        "search_repositories", {"query": "agent governance"}, to="mcp",
        invoke=lambda w: transport.call_mcp_tool(GITHUB_MCP_CMD, GITHUB_MCP_ARGS,
                                                 w["params"]["name"], w["params"]["arguments"]),
    )
    print("Bridged (OpenAI->MCP) GitHub result shape:", out.get("role"), "\n")
    print("That's the GitHub 'integration': no connector built — bridged via its MCP server.")


if __name__ == "__main__":
    asyncio.run(main())
