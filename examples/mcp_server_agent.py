"""
A real, runnable MCP server agent (official MCP SDK / FastMCP).

This is a genuine MCP agent — not a mock. It runs as its own process over stdio
and speaks the real Model Context Protocol. Used by live_mcp_handshake.py to prove
the bridge can sit in front of a real agent.

Run standalone:  python examples/mcp_server_agent.py   (waits for an MCP client on stdio)
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agentbridge-demo-mcp")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


@mcp.tool()
def echo(text: str) -> str:
    """Echo the provided text back to the caller."""
    return f"echo: {text}"


if __name__ == "__main__":
    mcp.run()  # stdio transport
