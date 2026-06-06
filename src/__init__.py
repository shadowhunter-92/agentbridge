"""
AgentBridge — the Meta-Bridge.

A neutral, protocol-agnostic interoperability + governance layer for multi-agent systems.
Core packages:
  - src.protocols   : the N-protocol canonical mesh (any-to-any translation)
  - src.governance  : identity, audit, budgets, approvals, policy (the moat)
  - src.proxy       : real transport clients + in-line proxy
  - src.serve       : drop-in MCP server packaging
  - src.api.control_plane : the HTTP control plane (the shipped surface)
"""

__version__ = "1.0.0"
