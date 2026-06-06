"""
Translation Engine
==================
Core translation logic between MCP and A2A protocols.

Handles semantic mapping, field transformations, and protocol translation.

Author: MiniMax Agent
"""

import json
import logging
import hashlib
from typing import Dict, Any, Optional, List, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class TranslationDirection(str, Enum):
    """Translation direction."""
    MCP_TO_A2A = "mcp_to_a2a"
    A2A_TO_MCP = "a2a_to_mcp"


class TranslationStatus(str, Enum):
    """Translation status."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    FALLBACK = "fallback"


@dataclass
class FieldMapping:
    """Field mapping definition."""
    source_field: str
    target_field: str
    transform: Optional[Callable] = None
    required: bool = False
    default_value: Any = None


@dataclass
class SemanticMapping:
    """Semantic mapping for protocol translation."""
    source_protocol: str
    target_protocol: str
    mappings: List[FieldMapping]
    type_overrides: Dict[str, str] = field(default_factory=dict)


@dataclass
class TranslationResult:
    """Result of a translation operation."""
    success: bool
    direction: str
    status: str
    source_data: Dict[str, Any]
    target_data: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TranslationEngine:
    """
    Translation Engine for MCP/A2A protocol conversion.

    Provides semantic mapping, field transformations, and protocol translation.
    """

    # Default field mappings MCP -> A2A
    DEFAULT_MCP_TO_A2A_MAPPINGS = [
        FieldMapping("name", "agent_id"),
        FieldMapping("input", "parameters"),
        FieldMapping("arguments", "parameters"),
        FieldMapping("content", "body"),
        FieldMapping("text", "message"),
        FieldMapping("results", "artifacts"),
        FieldMapping("isError", "error"),
        FieldMapping("description", "description"),
        FieldMapping("uri", "uri"),
        FieldMapping("mimeType", "mime_type"),
    ]

    # Default field mappings A2A -> MCP
    DEFAULT_A2A_TO_MCP_MAPPINGS = [
        FieldMapping("agent_id", "name"),
        FieldMapping("parameters", "input"),
        FieldMapping("body", "content"),
        FieldMapping("message", "text"),
        FieldMapping("artifacts", "results"),
        FieldMapping("error", "isError"),
        FieldMapping("description", "description"),
        FieldMapping("uri", "uri"),
        FieldMapping("mime_type", "mimeType"),
        FieldMapping("sessionId", "session_id"),
        FieldMapping("taskId", "task_id"),
    ]

    # Task type mappings
    TASK_TYPE_MAPPINGS = {
        # MCP to A2A
        "tool_execution": "task",
        "tool_call": "task",
        "list_tools": "task",
        "resource_read": "task",
        "resource_list": "task",
        "list_resources": "task",
        "get_prompt": "task",
        # A2A to MCP
        "message": "tool_execution",
        "task": "tool_execution",
    }

    # Status mappings
    STATUS_MAPPINGS = {
        # MCP to A2A
        "success": "completed",
        "error": "failed",
        "pending": "submitted",
        # A2A to MCP
        "submitted": "pending",
        "working": "pending",
        "completed": "success",
        "failed": "error",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize translation engine.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.strict_mode = self.config.get("strict_mode", False)
        self.enable_fallback = self.config.get("enable_fallback", True)
        self.custom_mappings = self.config.get("custom_mappings", {})

        # Initialize transformation cache
        self._transformation_cache: Dict[str, Any] = {}
        self._mapping_cache: Dict[str, List[FieldMapping]] = {
            TranslationDirection.MCP_TO_A2A.value: self.DEFAULT_MCP_TO_A2A_MAPPINGS.copy(),
            TranslationDirection.A2A_TO_MCP.value: self.DEFAULT_A2A_TO_MCP_MAPPINGS.copy(),
        }

        # Load custom mappings if provided
        self._load_custom_mappings()

        logger.info("Translation Engine initialized")

    def translate(self, data: Dict[str, Any], direction: str) -> TranslationResult:
        """
        Translate data between MCP and A2A protocols.

        Args:
            data: Source data to translate
            direction: Translation direction ("mcp_to_a2a" or "a2a_to_mcp")

        Returns:
            TranslationResult: Translation result with target data
        """
        start_time = datetime.now(timezone.utc)

        try:
            # Determine direction and select mappings
            if direction == TranslationDirection.MCP_TO_A2A.value:
                result = self._translate_mcp_to_a2a(data)
            elif direction == TranslationDirection.A2A_TO_MCP.value:
                result = self._translate_a2a_to_mcp(data)
            else:
                raise ValueError(f"Unknown translation direction: {direction}")

            # Add timing metadata
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            result.metadata["translation_time_ms"] = elapsed
            result.metadata["direction"] = direction

            return result

        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return TranslationResult(
                success=False,
                direction=direction,
                status=TranslationStatus.FAILED.value,
                source_data=data,
                target_data={},
                errors=[str(e)],
                metadata={"translation_time_ms": 0}
            )

    def _translate_mcp_to_a2a(self, mcp_data: Dict[str, Any]) -> TranslationResult:
        """Translate MCP data to A2A format."""
        warnings = []
        target_data = {}

        try:
            # Handle JSON-RPC message format
            if "jsonrpc" in mcp_data:
                target_data = self._translate_jsonrpc_mcp(mcp_data)
            else:
                # Direct field translation
                target_data = self._translate_fields(
                    mcp_data,
                    self._mapping_cache[TranslationDirection.MCP_TO_A2A.value]
                )

            # Handle task-specific translation
            if "method" in mcp_data:
                target_data = self._translate_method(mcp_data, target_data, "mcp_to_a2a")

            # Map task type
            if "method" in mcp_data:
                task_type = mcp_data.get("method", "").replace("/", "_")
                target_data["task_type"] = self.TASK_TYPE_MAPPINGS.get(task_type, "task")

            # Translate nested structures
            target_data = self._translate_nested_structures(target_data, "mcp_to_a2a")

            return TranslationResult(
                success=True,
                direction=TranslationDirection.MCP_TO_A2A.value,
                status=TranslationStatus.SUCCESS.value,
                source_data=mcp_data,
                target_data=target_data,
                warnings=warnings
            )

        except Exception as e:
            logger.warning(f"Partial MCP to A2A translation: {e}")
            return TranslationResult(
                success=False,
                direction=TranslationDirection.MCP_TO_A2A.value,
                status=TranslationStatus.PARTIAL.value,
                source_data=mcp_data,
                target_data=target_data,
                warnings=[str(e)]
            )

    def _translate_a2a_to_mcp(self, a2a_data: Dict[str, Any]) -> TranslationResult:
        """Translate A2A data to MCP format."""
        warnings = []
        target_data = {}

        try:
            # Handle JSON-RPC message format
            if "jsonrpc" in a2a_data:
                target_data = self._translate_jsonrpc_a2a(a2a_data)
            else:
                # Direct field translation
                target_data = self._translate_fields(
                    a2a_data,
                    self._mapping_cache[TranslationDirection.A2A_TO_MCP.value]
                )

            # Handle task-specific translation
            if "method" in a2a_data:
                target_data = self._translate_method(a2a_data, target_data, "a2a_to_mcp")

            # Translate nested structures
            target_data = self._translate_nested_structures(target_data, "a2a_to_mcp")

            return TranslationResult(
                success=True,
                direction=TranslationDirection.A2A_TO_MCP.value,
                status=TranslationStatus.SUCCESS.value,
                source_data=a2a_data,
                target_data=target_data,
                warnings=warnings
            )

        except Exception as e:
            logger.warning(f"Partial A2A to MCP translation: {e}")
            return TranslationResult(
                success=False,
                direction=TranslationDirection.A2A_TO_MCP.value,
                status=TranslationStatus.PARTIAL.value,
                source_data=a2a_data,
                target_data=target_data,
                warnings=[str(e)]
            )

    def _translate_jsonrpc_mcp(self, mcp_data: Dict[str, Any]) -> Dict[str, Any]:
        """Translate MCP JSON-RPC message to A2A task format."""
        method = mcp_data.get("method", "")
        params = mcp_data.get("params", {})
        msg_id = mcp_data.get("id")

        # Build A2A task structure conforming to the A2A JSON-RPC spec:
        # Task uses `history` (a list of Message objects), carries a `contextId`,
        # and each Message has `kind: "message"` + a `messageId`.
        task = {
            "id": str(msg_id) if msg_id else self._generate_task_id(),
            "contextId": self._generate_context_id(),
            "kind": "task",
            "status": {
                "state": "submitted"
            },
            "history": [
                {
                    "kind": "message",
                    "messageId": self._generate_msg_id(),
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": f"MCP task: {method}"
                        }
                    ]
                }
            ],
            "metadata": {
                "source_protocol": "mcp",
                "source_method": method,
                "original_id": str(msg_id)
            }
        }

        # Map parameters based on method
        if method == "tools/call":
            task["history"][0]["parts"].append({
                "kind": "data",
                "data": {
                    "tool_name": params.get("name", params.get("tool", "")),
                    "arguments": params.get("arguments", params.get("input", {}))
                }
            })
        elif method == "resources/read":
            task["history"][0]["parts"].append({
                "kind": "data",
                "data": {
                    "uri": params.get("uri", "")
                }
            })

        return {"task": task}

    def _translate_jsonrpc_a2a(self, a2a_data: Dict[str, Any]) -> Dict[str, Any]:
        """Translate A2A JSON-RPC message to MCP format."""
        method = a2a_data.get("method", "")
        params = a2a_data.get("params", {})
        msg_id = a2a_data.get("id")

        mcp_msg = {
            "jsonrpc": "2.0",
            "id": str(msg_id) if msg_id else self._generate_msg_id(),
            "method": self._map_a2a_method_to_mcp(method),
            "params": {}
        }

        # Handle task-specific translation
        if "task" in params:
            task = params["task"]
            mcp_msg["method"] = self._extract_mcp_method_from_task(task)
            mcp_msg["params"] = self._extract_mcp_params_from_task(task)

        return mcp_msg

    def _translate_fields(self, data: Dict[str, Any],
                         mappings: List[FieldMapping]) -> Dict[str, Any]:
        """Apply field mappings to data."""
        result = {}

        for mapping in mappings:
            source_value = self._get_nested_value(data, mapping.source_field)

            if source_value is not None:
                target_value = source_value

                # Apply transformation if specified
                if mapping.transform:
                    target_value = mapping.transform(source_value)

                self._set_nested_value(result, mapping.target_field, target_value)

            elif mapping.default_value is not None:
                self._set_nested_value(result, mapping.target_field, mapping.default_value)

        # Copy unmapped fields
        for key, value in data.items():
            if key not in [m.source_field for m in mappings]:
                result[key] = value

        return result

    def _translate_method(self, data: Dict[str, Any],
                          target: Dict[str, Any],
                          direction: str) -> Dict[str, Any]:
        """Translate method-specific fields."""
        method = data.get("method", "")

        if direction == "mcp_to_a2a":
            # Map MCP method to A2A task format
            if method.startswith("tools/"):
                target["task_type"] = "tool_execution"
            elif method.startswith("resources/"):
                target["task_type"] = "resource_access"
        else:
            # Map A2A task to MCP method
            if "task" in data:
                task = data["task"]
                target["method"] = self._extract_mcp_method(task)

        return target

    def _translate_nested_structures(self, data: Dict[str, Any],
                                     direction: str) -> Dict[str, Any]:
        """Translate nested data structures."""
        result = data.copy()

        # Translate artifacts/content structures
        if "artifacts" in result:
            result["content"] = self._translate_artifacts(result["artifacts"])
            if direction == "a2a_to_mcp":
                del result["artifacts"]

        if "content" in result and direction == "a2a_to_mcp":
            result["results"] = result["content"]
            del result["content"]

        # Translate status structures
        if "status" in result and isinstance(result["status"], dict):
            if "state" in result["status"]:
                state = result["status"]["state"]
                result["status"]["state"] = self.STATUS_MAPPINGS.get(state, state)

        return result

    def _translate_artifacts(self, artifacts: List[Any]) -> List[Dict[str, Any]]:
        """Translate artifact list format."""
        translated = []

        for artifact in artifacts:
            if isinstance(artifact, dict):
                translated.append({
                    "type": artifact.get("type", "text"),
                    "content": artifact.get("content", str(artifact)),
                    "name": artifact.get("name", ""),
                    "description": artifact.get("description", "")
                })
            else:
                translated.append({
                    "type": "text",
                    "content": str(artifact)
                })

        return translated

    def _map_a2a_method_to_mcp(self, a2a_method: str) -> str:
        """Map A2A method to MCP method."""
        method_map = {
            "tasks/send": "tools/call",
            "tasks/get": "tools/list",
            "agent/info": "tools/list",
        }
        return method_map.get(a2a_method, "tools/call")

    def _extract_mcp_method_from_task(self, task: Dict[str, Any]) -> str:
        """Extract MCP method from A2A task."""
        # A2A spec tasks carry messages under `history`; accept legacy `messages` too.
        messages = task.get("history") or task.get("messages") or []
        if messages:
            for part in messages[0].get("parts", []):
                if part.get("kind") == "data":
                    data = part.get("data", {})
                    if "tool_name" in data or "name" in data:
                        return "tools/call"
        return "tools/call"

    def _extract_mcp_params_from_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Extract MCP params from A2A task.

        Emits MCP `tools/call` params shaped per the official MCP schema
        (`{"name": ..., "arguments": ...}`), not the A2A-internal `tool_name`.
        """
        messages = task.get("history") or task.get("messages") or []

        if messages:
            for part in messages[0].get("parts", []):
                if part.get("kind") == "data":
                    data = part.get("data", {})
                    name = data.get("name") or data.get("tool_name")
                    if name is not None:
                        return {"name": name, "arguments": data.get("arguments", {})}
                    return data

        return {}

    def _extract_mcp_method(self, task: Dict[str, Any]) -> str:
        """Extract MCP method from A2A task."""
        return "tools/call"

    def _get_nested_value(self, data: Dict[str, Any], key: str) -> Any:
        """Get value from nested dictionary using dot notation."""
        keys = key.split(".")
        value = data

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return None

        return value

    def _set_nested_value(self, data: Dict[str, Any], key: str, value: Any) -> None:
        """Set value in nested dictionary using dot notation."""
        keys = key.split(".")
        current = data

        for i, k in enumerate(keys[:-1]):
            if k not in current:
                current[k] = {}
            current = current[k]

        current[keys[-1]] = value

    def _generate_task_id(self) -> str:
        """Generate unique task ID."""
        import uuid
        return f"task_{uuid.uuid4().hex[:12]}"

    def _generate_msg_id(self) -> str:
        """Generate unique message ID."""
        import uuid
        return str(uuid.uuid4())

    def _generate_context_id(self) -> str:
        """Generate unique A2A context ID."""
        import uuid
        return f"ctx_{uuid.uuid4().hex[:12]}"

    def _load_custom_mappings(self) -> None:
        """Load custom field mappings from configuration."""
        if "mcp_to_a2a" in self.custom_mappings:
            for mapping in self.custom_mappings["mcp_to_a2a"]:
                if isinstance(mapping, dict):
                    self._mapping_cache[TranslationDirection.MCP_TO_A2A.value].append(
                        FieldMapping(**mapping)
                    )

        if "a2a_to_mcp" in self.custom_mappings:
            for mapping in self.custom_mappings["a2a_to_mcp"]:
                if isinstance(mapping, dict):
                    self._mapping_cache[TranslationDirection.A2A_TO_MCP.value].append(
                        FieldMapping(**mapping)
                    )

    def register_custom_mapping(self, direction: str,
                               source_field: str,
                               target_field: str,
                               transform: Optional[Callable] = None) -> None:
        """
        Register a custom field mapping.

        Args:
            direction: "mcp_to_a2a" or "a2a_to_mcp"
            source_field: Source field name
            target_field: Target field name
            transform: Optional transformation function
        """
        mapping = FieldMapping(
            source_field=source_field,
            target_field=target_field,
            transform=transform
        )

        if direction == TranslationDirection.MCP_TO_A2A.value:
            self._mapping_cache[TranslationDirection.MCP_TO_A2A.value].append(mapping)
        else:
            self._mapping_cache[TranslationDirection.A2A_TO_MCP.value].append(mapping)

        logger.info(f"Registered custom mapping: {source_field} -> {target_field}")

    def get_supported_mappings(self, direction: str) -> List[Dict[str, str]]:
        """
        Get list of supported field mappings.

        Args:
            direction: "mcp_to_a2a" or "a2a_to_mcp"

        Returns:
            List of mapping dictionaries
        """
        mappings = self._mapping_cache.get(direction, [])
        return [
            {"source": m.source_field, "target": m.target_field}
            for m in mappings
        ]

    def validate_translation(self, result: TranslationResult) -> Tuple[bool, List[str]]:
        """
        Validate translation result.

        Args:
            result: TranslationResult to validate

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []

        if not result.source_data:
            errors.append("Source data is empty")

        if result.direction == TranslationDirection.MCP_TO_A2A.value:
            if "method" in result.source_data and not result.target_data.get("task"):
                errors.append("MCP to A2A: Task structure not created")
        else:
            if "task" in result.source_data and not result.target_data.get("method"):
                errors.append("A2A to MCP: Method not extracted")

        is_valid = len(errors) == 0 or result.status == TranslationStatus.PARTIAL.value

        return is_valid, errors