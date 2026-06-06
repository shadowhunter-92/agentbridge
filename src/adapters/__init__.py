"""
Adapters Module
==============
Protocol adapters for MCP and A2A protocols.

Author: MiniMax Agent
"""

from .mcp_adapter import MCPAdapter, MCPTaskRequest, MCPTaskResponse, MCPMessage
from .a2a_adapter import A2AAdapter, A2ATaskRequest, A2ATaskResponse, A2ATask

__all__ = [
    "MCPAdapter",
    "A2AAdapter",
    "MCPTaskRequest",
    "MCPTaskResponse",
    "MCPMessage",
    "A2ATaskRequest",
    "A2ATaskResponse",
    "A2ATask"
]