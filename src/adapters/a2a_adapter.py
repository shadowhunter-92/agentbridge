"""
A2A (Agent-to-Agent) Protocol Adapter
=====================================
Handles parsing and serialization of A2A protocol messages.

A2A is Google's protocol for agent-to-agent collaboration.
Reference: https://google.github.io/A2A/

Author: MiniMax Agent
"""

import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class A2ATaskStatus(str, Enum):
    """A2A task status values."""
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class A2ATaskKind(str, Enum):
    """A2A task kind types."""
    MESSAGE = "message"
    TASK = "task"


@dataclass
class A2AArtifact:
    """A2A artifact representation."""
    uri: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    kind: str = "file"
    mime_type: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class A2AAgentInfo:
    """A2A agent information."""
    name: str
    description: Optional[str] = None
    url: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None
    skills: List[str] = field(default_factory=list)
    version: str = "1.0"


@dataclass
class A2AMessage:
    """A2A message representation."""
    id: str
    role: str = "agent"
    parts: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class A2ATask:
    """A2A task representation."""
    id: str
    kind: str = A2ATaskKind.TASK.value
    status: str = A2ATaskStatus.SUBMITTED.value
    agent: Optional[str] = None
    sessionId: Optional[str] = None
    messages: List[A2AMessage] = field(default_factory=list)
    artifacts: List[A2AArtifact] = field(default_factory=list)
    push_notification: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class A2AStatusUpdate:
    """A2A status update."""
    state: str
    message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class A2ATaskRequest:
    """A2A task request for translation from MCP."""
    task_id: str
    task_type: str
    description: str
    parameters: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None
    expected_output: Optional[str] = None
    session_id: Optional[str] = None
    agent_info: Optional[A2AAgentInfo] = None


@dataclass
class A2ATaskResponse:
    """A2A task response for translation to MCP."""
    task_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    artifacts: List[A2AArtifact] = field(default_factory=list)
    status_update: Optional[A2AStatusUpdate] = None


class A2AAdapter:
    """
    A2A Protocol Adapter for Agent Bridge.

    Handles A2A message parsing, serialization, and transformation.
    Supports A2A Protocol Specification 1.0.
    """

    SUPPORTED_METHODS = [
        "tasks/send",
        "tasks/sendSubscribe",
        "tasks/get",
        "tasks/cancel",
        "tasks/pushNotificationSubscribe",
        "agent/info",
    ]

    # Field mappings from A2A to MCP canonical format
    FIELD_MAPPINGS = {
        "agent_id": "name",
        "parameters": "input",
        "body": "content",
        "message": "text",
        "artifacts": "results",
        "error": "isError",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize A2A adapter with optional configuration."""
        self.config = config or {}
        self.agent_info = self.config.get("agent_info", {})
        self.default_timeout = self.config.get("timeout", 60)
        self.push_enabled = self.config.get("push_enabled", False)
        logger.info(f"A2A Adapter initialized for agent: {self.agent_info.get('name', 'unknown')}")

    def parse_message(self, raw_message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse incoming A2A JSON-RPC message.

        Args:
            raw_message: Raw A2A JSON message

        Returns:
            Dict containing parsed message data
        """
        try:
            jsonrpc = raw_message.get("jsonrpc", "2.0")
            method = raw_message.get("method", "")
            msg_id = raw_message.get("id")
            params = raw_message.get("params", {})

            parsed = {
                "jsonrpc": jsonrpc,
                "method": method,
                "id": msg_id,
                "params": params,
                "type": self._get_message_type(method)
            }

            logger.debug(f"Parsed A2A message: {method}")
            return parsed

        except Exception as e:
            logger.error(f"Failed to parse A2A message: {e}")
            raise ValueError(f"Invalid A2A message format: {e}")

    def serialize_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Serialize internal data to A2A JSON-RPC format.

        Args:
            data: Internal data to serialize

        Returns:
            Dict: A2A JSON-RPC message
        """
        msg = {
            "jsonrpc": "2.0",
            "id": data.get("id", self._generate_id())
        }

        if "result" in data:
            msg["result"] = data["result"]
        if "error" in data:
            msg["error"] = data["error"]
        if "method" in data:
            msg["method"] = data["method"]

        return msg

    def create_task(self, task_request: A2ATaskRequest) -> Dict[str, Any]:
        """
        Create A2A task from canonical request format.

        Args:
            task_request: Task request in canonical format

        Returns:
            Dict: A2A task JSON for tasks/send call
        """
        task_id = task_request.task_id
        description = task_request.description

        # Build message parts
        parts = [
            {
                "kind": "text",
                "text": description
            }
        ]

        # Add parameters as structured data
        if task_request.parameters:
            parts.append({
                "kind": "data",
                "data": task_request.parameters
            })

        # Create task payload
        task_payload = {
            "id": task_id,
            "kind": A2ATaskKind.TASK.value,
            "status": {
                "state": A2ATaskStatus.SUBMITTED.value,
                "message": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": description}]
                }
            },
            "messages": [
                {
                    "role": "agent",
                    "parts": parts
                }
            ],
            "metadata": task_request.context or {}
        }

        # Add session ID if provided
        if task_request.session_id:
            task_payload["sessionId"] = task_request.session_id

        # Add push notification if enabled
        if self.push_enabled:
            task_payload["pushNotification"] = {
                "url": self.config.get("push_url", ""),
                "token": self.config.get("push_token", "")
            }

        return {
            "method": "tasks/send",
            "params": {
                "task": task_payload
            }
        }

    def parse_task_response(self, response: Dict[str, Any]) -> A2ATaskResponse:
        """
        Parse A2A task response for MCP translation.

        Args:
            response: A2A task response

        Returns:
            A2ATaskResponse: Normalized task response
        """
        result = response.get("result", {})
        task = result.get("task", {})

        # Extract status
        status_info = task.get("status", {})
        state = status_info.get("state", A2ATaskStatus.WORKING.value)

        # Extract artifacts
        artifacts = []
        for artifact in task.get("artifacts", []):
            artifacts.append(A2AArtifact(
                uri=artifact.get("uri"),
                name=artifact.get("name"),
                description=artifact.get("description"),
                kind=artifact.get("kind", "file"),
                mime_type=artifact.get("mimeType"),
                content=artifact.get("content")
            ))

        # Extract result from last message
        last_message = task.get("messages", [{}])[-1]
        parts = last_message.get("parts", [])
        result_text = ""
        for part in parts:
            if part.get("kind") == "text":
                result_text += part.get("text", "")

        return A2ATaskResponse(
            task_id=task.get("id", ""),
            status=state,
            result={"message": result_text, "parts": parts},
            artifacts=artifacts,
            status_update=A2AStatusUpdate(state=state, message=result_text)
        )

    def create_status_update(self, task_id: str, state: str,
                            message: Optional[str] = None) -> Dict[str, Any]:
        """
        Create A2A status update notification.

        Args:
            task_id: Task ID
            state: New state
            message: Optional status message

        Returns:
            Dict: A2A status update message
        """
        return {
            "jsonrpc": "2.0",
            "method": "tasks/statusUpdated",
            "params": {
                "taskId": task_id,
                "status": {
                    "state": state,
                    "message": message
                }
            }
        }

    def get_agent_info_response(self) -> Dict[str, Any]:
        """
        Get agent info response for A2A agent/info endpoint.

        Returns:
            Dict: Agent info response
        """
        return {
            "name": self.agent_info.get("name", "Agent Bridge"),
            "description": self.agent_info.get("description",
                "Universal Agent Translator - MCP/A2A Protocol Bridge"),
            "url": self.agent_info.get("url", "http://localhost:8000"),
            "version": "1.0.0",
            "capabilities": {
                "streaming": False,
                "pushNotifications": self.push_enabled,
                "tasks": {
                    "supportsCreate": True,
                    "supportsSubscribe": True,
                    "supportsCancel": True,
                    "supportsGet": True
                }
            },
            "skills": [
                {
                    "id": "mcp-to-a2a",
                    "name": "MCP to A2A Translation",
                    "description": "Translates MCP protocol messages to A2A format"
                },
                {
                    "id": "a2a-to-mcp",
                    "name": "A2A to MCP Translation",
                    "description": "Translates A2A protocol messages to MCP format"
                }
            ]
        }

    def _get_message_type(self, method: str) -> str:
        """Determine A2A message type from method."""
        if method.startswith("tasks/"):
            return "task"
        elif method == "agent/info":
            return "agent_info"
        return "unknown"

    def _generate_id(self) -> str:
        """Generate unique message ID."""
        import uuid
        return str(uuid.uuid4())

    def validate_task(self, task: Dict[str, Any]) -> bool:
        """
        Validate A2A task format.

        Args:
            task: Task data to validate

        Returns:
            bool: True if valid
        """
        required_fields = ["id"]
        for field in required_fields:
            if field not in task:
                return False
        return True

    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get A2A adapter capabilities.

        Returns:
            Dict containing supported capabilities
        """
        return {
            "protocol": "A2A",
            "version": "1.0",
            "supported_methods": self.SUPPORTED_METHODS,
            "features": [
                "task_creation",
                "task_subscription",
                "task_cancellation",
                "status_updates",
                "artifact_transfer"
            ],
            "transformations": {
                "to_mcp": self._get_to_mcp_mapping(),
                "from_mcp": self._get_from_mcp_mapping()
            }
        }

    def _get_to_mcp_mapping(self) -> Dict[str, str]:
        """Get A2A to MCP field mapping."""
        return {v: k for k, v in self.FIELD_MAPPINGS.items()}

    def _get_from_mcp_mapping(self) -> Dict[str, str]:
        """Get MCP to A2A field mapping."""
        return self.FIELD_MAPPINGS

    def create_error_response(self, task_id: str, code: int,
                            message: str) -> Dict[str, Any]:
        """
        Create A2A error response.

        Args:
            task_id: Original request ID
            code: Error code
            message: Error message

        Returns:
            Dict: A2A error response
        """
        return {
            "jsonrpc": "2.0",
            "id": task_id,
            "error": {
                "code": code,
                "message": message
            }
        }