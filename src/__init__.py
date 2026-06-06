"""
Universal Agent Translator - Protocol Bridge
============================================
A lightweight translation layer between MCP and A2A protocols.
Enables seamless communication between agents using different protocols.

Author: MiniMax Agent
License: Apache 2.0
"""

__version__ = "1.0.0"
__author__ = "MiniMax Agent"

from .adapters.mcp_adapter import MCPAdapter
from .adapters.a2a_adapter import A2AAdapter
from .engine.translation_engine import TranslationEngine
from .routing.routing_mesh import RoutingMesh

__all__ = [
    "MCPAdapter",
    "A2AAdapter",
    "TranslationEngine",
    "RoutingMesh",
]