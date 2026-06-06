"""
MCP (Model Context Protocol) Adapter
=====================================
Handles parsing and serialization of MCP protocol messages.

MCP is Anthropic's protocol for agent-tool connections.
Reference: https://modelcontextprotocol.io/

Author: MiniMax Agent
"""

import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class MCPToolKind(str, Enum):
    """MCP tool types."""
    EXECUTE = "execute"
    READ = "read"
    WRITE = "write"
    LIST = "list"


@dataclass
class MCPResource:
    """MCP resource representation."""
    uri: str
    name: str
    mime_type: Optional[str] = None
    description: Optional[str] = None
    annotations: Optional[Dict[str, Any]] = None


@dataclass
class MCPTool:
    """MCP tool representation."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    annotations: Optional[Dict[str, Any]] = None


@dataclass
class MCPMessage:
    """Internal representation of MCP message."""
    id: str
    method: str
    params: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    protocol_version: str = "2024-11-05"


@dataclass
class MCPTaskRequest:
    """MCP task request for translation to A2A."""
    task_id: str
    task_type: str
    description: str
    parameters: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None
    tools: List[str] = field(default_factory=list)
    expected_output: Optional[str] = None


@dataclass
class MCPTaskResponse:
    """MCP task response from translation."""
    task_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    artifacts: List[Dict[str, Any]] = field(default_factory=list)


class MCPAdapter:
    """
    MCP Protocol Adapter for Agent Bridge.

    Handles MCP message parsing, serialization, and transformation.
    Supports MCP 2024-11-05 specification.
    """

    SUPPORTED_METHODS = [
        "tools/list",
        "tools/call",
        "resources/list",
        "resources/read",
        "resources/subscribe",
        "prompts/list",
        "prompts/get",
        "roots/list",
        "sampling/create",
    ]

    # Field mappings from MCP to A2A canonical format
    FIELD_MAPPINGS = {
        "name": "agent_id",
        "input": "parameters",
        "arguments": "parameters",
        "content": "body",
        "text": "message",
        "results": "artifacts",
        "isError": "error",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize MCP adapter with optional configuration."""
        self.config = config or {}
        self.protocol_version = self.config.get("protocol_version", "2024-11-05")
        self.timeout = self.config.get("timeout", 30)
        self.max_retries = self.config.get("max_retries", 3)
        logger.info(f"MCP Adapter initialized with protocol version {self.protocol_version}")

    def parse_message(self, raw_message: Dict[str, Any]) -> MCPMessage:
        """
        Parse incoming MCP message into internal format.

        Args:
            raw_message: Raw MCP JSON message

        Returns:
            MCPMessage: Parsed message in internal format
        """
        try:
            jsonrpc = raw_message.get("jsonrpc", "2.0")
            method = raw_message.get("method", "")
            msg_id = raw_message.get("id")
            params = raw_message.get("params", {})
            result = raw_message.get("result", {})
            error = raw_message.get("error", {})

            message = MCPMessage(
                id=str(msg_id) if msg_id else self._generate_id(),
                method=method,
                params=params,
                result=result,
                error=error
            )

            logger.debug(f"Parsed MCP message: {message.id} - {message.method}")
            return message

        except Exception as e:
            logger.error(f"Failed to parse MCP message: {e}")
            raise ValueError(f"Invalid MCP message format: {e}")

    def serialize_message(self, message: MCPMessage) -> Dict[str, Any]:
        """
        Serialize internal MCP message to JSON format.

        Args:
            message: Internal MCP message

        Returns:
            Dict[str, Any]: JSON-serializable MCP message
        """
        msg = {
            "jsonrpc": "2.0",
            "id": message.id,
            "method": message.method,
        }

        if message.params:
            msg["params"] = message.params
        if message.result:
            msg["result"] = message.result
        if message.error:
            msg["error"] = message.error

        return msg

    def extract_task(self, message: MCPMessage) -> MCPTaskRequest:
        """
        Extract task information from MCP message for A2A translation.

        Args:
            message: MCP message

        Returns:
            MCPTaskRequest: Task request in canonical format
        """
        params = message.params or {}

        # Handle tools/call method
        if message.method == "tools/call":
            tool_name = params.get("name", params.get("tool", "unknown"))
            tool_args = params.get("arguments", params.get("input", {}))

            return MCPTaskRequest(
                task_id=message.id,
                task_type="tool_execution",
                description=f"Execute MCP tool: {tool_name}",
                parameters=tool_args,
                context={"tool_name": tool_name, "protocol": "mcp"},
                tools=[tool_name],
                expected_output=params.get("expected_output")
            )

        # Handle resources/read method
        elif message.method == "resources/read":
            uri = params.get("uri", "")
            return MCPTaskRequest(
                task_id=message.id,
                task_type="resource_read",
                description=f"Read MCP resource: {uri}",
                parameters={"uri": uri},
                context={"uri": uri, "protocol": "mcp"}
            )

        # Default handling for other methods
        return MCPTaskRequest(
            task_id=message.id,
            task_type=self._normalize_method_type(message.method),
            description=f"MCP task: {message.method}",
            parameters=params,
            context={"method": message.method, "protocol": "mcp"}
        )

    def create_task_response(self, task_id: str, status: str,
                           result: Optional[Any] = None,
                           error: Optional[str] = None) -> MCPMessage:
        """
        Create MCP task response from A2A result.

        Args:
            task_id: Original task ID
            status: Task status
            result: Task result data
            error: Error message if any

        Returns:
            MCPMessage: MCP message response
        """
        if error:
            return MCPMessage(
                id=task_id,
                method="",
                error={
                    "code": -32603,
                    "message": error,
                    "data": None
                }
            )

        # Transform result to MCP format
        mcp_result = self._transform_result_to_mcp(result)

        return MCPMessage(
            id=task_id,
            method="",
            result=mcp_result
        )

    def _transform_result_to_mcp(self, result: Any) -> Dict[str, Any]:
        """Transform A2A result to MCP format."""
        if isinstance(result, dict):
            # Map A2A fields to MCP format
            mcp_result = {}
            for key, value in result.items():
                if key == "artifacts":
                    mcp_result["content"] = self._format_artifacts(value)
                elif key == "status":
                    mcp_result["success"] = value in ["completed", "success"]
                elif key == "message":
                    mcp_result["text"] = value
                else:
                    mcp_result[key] = value
            return mcp_result
        return {"result": result}

    def _format_artifacts(self, artifacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format artifacts for MCP response."""
        formatted = []
        for artifact in artifacts:
            content = artifact.get("content", str(artifact))
            if isinstance(content, dict):
                formatted.append({
                    "type": artifact.get("type", "text"),
                    "text": json.dumps(content)
                })
            else:
                formatted.append({
                    "type": "text",
                    "text": str(content)
                })
        return formatted

    def _normalize_method_type(self, method: str) -> str:
        """Normalize MCP method to task type."""
        method_map = {
            "tools/list": "list_tools",
            "tools/call": "tool_execution",
            "resources/list": "list_resources",
            "resources/read": "resource_read",
            "prompts/list": "list_prompts",
            "prompts/get": "get_prompt",
        }
        return method_map.get(method, method.replace("/", "_"))

    def _generate_id(self) -> str:
        """Generate unique message ID."""
        import uuid
        return str(uuid.uuid4())

    def validate_message(self, message: MCPMessage) -> bool:
        """
        Validate MCP message format and fields.

        Args:
            message: MCP message to validate

        Returns:
            bool: True if valid, False otherwise
        """
        if not message.id:
            return False
        if not message.method and not message.result and not message.error:
            return False
        if message.method and message.method not in self.SUPPORTED_METHODS:
            logger.warning(f"Unknown MCP method: {message.method}")
            return False
        return True

    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get MCP adapter capabilities.

        Returns:
            Dict containing supported capabilities
        """
        return {
            "protocol": "MCP",
            "version": self.protocol_version,
            "supported_methods": self.SUPPORTED_METHODS,
            "features": [
                "tool_execution",
                "resource_read",
                "resource_list",
                "prompt_handling"
            ],
            "transformations": {
                "to_a2a": self._get_to_a2a_mapping(),
                "from_a2a": self._get_from_a2a_mapping()
            }
        }

    def _get_to_a2a_mapping(self) -> Dict[str, str]:
        """Get MCP to A2A field mapping."""
        return self.FIELD_MAPPINGS

    def _get_from_a2a_mapping(self) -> Dict[str, str]:
        """Get A2A to MCP field mapping (inverse)."""
        return {v: k for k, v in self.FIELD_MAPPINGS.items()}

    def create_heartbeat(self) -> MCPMessage:
        """Create MCP heartbeat/ping message."""
        return MCPMessage(
            id=self._generate_id(),
            method="ping",
            params={"timestamp": datetime.now(timezone.utc).isoformat()}
        )

    def parse_capabilities(self, capabilities: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse and validate MCP capabilities from remote agent.

        Args:
            capabilities: Remote agent capabilities

        Returns:
            Dict containing normalized capabilities
        """
        return {
            "tools": capabilities.get("tools", []),
            "resources": capabilities.get("resources", []),
            "prompts": capabilities.get("prompts", []),
            "protocol_version": capabilities.get("protocolVersion", self.protocol_version)
        }