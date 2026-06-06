"""
Agent Bridge Tests
==================

Author: MiniMax Agent
"""

import pytest
import json
from src.adapters.mcp_adapter import MCPAdapter, MCPMessage, MCPTaskRequest
from src.adapters.a2a_adapter import A2AAdapter, A2ATaskRequest
from src.engine.translation_engine import TranslationEngine, TranslationDirection
from src.routing.routing_mesh import RoutingMesh, Endpoint, RoutingStrategy


class TestMCPAdapter:
    """Test MCP Adapter functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = MCPAdapter()

    def test_parse_message(self):
        """Test MCP message parsing."""
        raw_message = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {
                "name": "test_tool",
                "arguments": {"arg1": "value1"}
            }
        }

        message = self.adapter.parse_message(raw_message)

        assert message.id == "1"
        assert message.method == "tools/call"
        assert message.params["name"] == "test_tool"

    def test_serialize_message(self):
        """Test MCP message serialization."""
        message = MCPMessage(
            id="2",
            method="tools/list",
            result={"tools": []}
        )

        serialized = self.adapter.serialize_message(message)

        assert serialized["jsonrpc"] == "2.0"
        assert serialized["id"] == "2"
        assert serialized["method"] == "tools/list"

    def test_extract_task(self):
        """Test task extraction from MCP message."""
        message = MCPMessage(
            id="3",
            method="tools/call",
            params={"name": "execute_code", "arguments": {"code": "print(1)"}}
        )

        task = self.adapter.extract_task(message)

        assert task.task_id == "3"
        assert task.task_type == "tool_execution"
        assert task.tools == ["execute_code"]

    def test_validate_message(self):
        """Test message validation."""
        valid_message = MCPMessage(id="1", method="tools/call")
        assert self.adapter.validate_message(valid_message)

        invalid_message = MCPMessage(id="", method="")
        assert not self.adapter.validate_message(invalid_message)


class TestA2AAdapter:
    """Test A2A Adapter functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = A2AAdapter(config={"agent_info": {"name": "Test Agent"}})

    def test_parse_message(self):
        """Test A2A message parsing."""
        raw_message = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tasks/send",
            "params": {
                "task": {
                    "id": "task-1",
                    "kind": "task"
                }
            }
        }

        parsed = self.adapter.parse_message(raw_message)

        assert parsed["method"] == "tasks/send"
        assert parsed["type"] == "task"

    def test_create_task(self):
        """Test A2A task creation."""
        task_request = A2ATaskRequest(
            task_id="task-123",
            task_type="execution",
            description="Execute Python code",
            parameters={"code": "print('hello')"}
        )

        task = self.adapter.create_task(task_request)

        assert task["method"] == "tasks/send"
        assert task["params"]["task"]["id"] == "task-123"

    def test_get_agent_info_response(self):
        """Test agent info response."""
        info = self.adapter.get_agent_info_response()

        assert "name" in info
        assert "capabilities" in info
        assert "skills" in info


class TestTranslationEngine:
    """Test Translation Engine functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = TranslationEngine()

    def test_mcp_to_a2a_translation(self):
        """Test MCP to A2A translation."""
        mcp_data = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {
                "name": "test_tool",
                "arguments": {"arg": "value"}
            }
        }

        result = self.engine.translate(mcp_data, TranslationDirection.MCP_TO_A2A.value)

        assert result.success
        assert result.direction == TranslationDirection.MCP_TO_A2A.value
        assert "task" in result.target_data

    def test_a2a_to_mcp_translation(self):
        """Test A2A to MCP translation."""
        a2a_data = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tasks/send",
            "params": {
                "task": {
                    "id": "task-1",
                    "kind": "task",
                    "status": {"state": "submitted"},
                    "messages": [{
                        "role": "agent",
                        "parts": [{"kind": "text", "text": "test"}]
                    }]
                }
            }
        }

        result = self.engine.translate(a2a_data, TranslationDirection.A2A_TO_MCP.value)

        assert result.success
        assert result.direction == TranslationDirection.A2A_TO_MCP.value

    def test_custom_mapping(self):
        """Test custom field mapping registration."""
        self.engine.register_custom_mapping(
            "mcp_to_a2a",
            "custom_field",
            "mapped_field"
        )

        mappings = self.engine.get_supported_mappings("mcp_to_a2a")
        assert any(m["source"] == "custom_field" for m in mappings)


class TestRoutingMesh:
    """Test Routing Mesh functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mesh = RoutingMesh()

    def test_register_endpoint(self):
        """Test endpoint registration."""
        endpoint = Endpoint(
            id="ep-1",
            name="Test MCP Agent",
            url="http://localhost:5001",
            protocol="mcp"
        )

        success = self.mesh.register_endpoint(endpoint)

        assert success
        assert self.mesh.get_endpoint("ep-1") is not None

    def test_unregister_endpoint(self):
        """Test endpoint unregistration."""
        endpoint = Endpoint(
            id="ep-2",
            name="Test A2A Agent",
            url="http://localhost:5002",
            protocol="a2a"
        )

        self.mesh.register_endpoint(endpoint)
        success = self.mesh.unregister_endpoint("ep-2")

        assert success
        assert self.mesh.get_endpoint("ep-2") is None

    def test_route_to_endpoint(self):
        """Test routing to active endpoint."""
        endpoint = Endpoint(
            id="ep-3",
            name="Test Agent",
            url="http://localhost:5003",
            protocol="mcp"
        )

        self.mesh.register_endpoint(endpoint)
        result = self.mesh.route("mcp")

        assert result.success
        assert result.endpoint is not None
        assert result.target_url == "http://localhost:5003"

    def test_route_no_endpoints(self):
        """Test routing with no available endpoints."""
        result = self.mesh.route("a2a")

        assert not result.success
        assert result.error is not None

    def test_get_statistics(self):
        """Test statistics retrieval."""
        endpoint = Endpoint(
            id="ep-4",
            name="Stat Test",
            url="http://localhost:5004",
            protocol="mcp"
        )

        self.mesh.register_endpoint(endpoint)
        stats = self.mesh.get_statistics()

        assert "total_endpoints" in stats
        assert "active_endpoints" in stats
        assert stats["total_endpoints"] >= 1


class TestIntegration:
    """Integration tests for full workflow."""

    def test_full_translation_flow(self):
        """Test complete MCP -> A2A -> MCP flow."""
        mcp_adapter = MCPAdapter()
        a2a_adapter = A2AAdapter()
        engine = TranslationEngine()

        # MCP to A2A
        mcp_message = {
            "jsonrpc": "2.0",
            "id": "int-1",
            "method": "tools/call",
            "params": {
                "name": "execute_code",
                "arguments": {"code": "print('test')"}
            }
        }

        # Translate to A2A
        result1 = engine.translate(mcp_message, TranslationDirection.MCP_TO_A2A.value)
        assert result1.success

        # Translate back to MCP
        result2 = engine.translate(result1.target_data, TranslationDirection.A2A_TO_MCP.value)
        assert result2.success

    def test_routing_with_translation(self):
        """Test routing combined with translation."""
        mesh = RoutingMesh()
        mcp_adapter = MCPAdapter()
        engine = TranslationEngine()

        # Register endpoints
        mesh.register_endpoint(Endpoint(
            id="mcp-1",
            name="MCP Agent",
            url="http://mcp-agent:5001",
            protocol="mcp"
        ))

        mesh.register_endpoint(Endpoint(
            id="a2a-1",
            name="A2A Agent",
            url="http://a2a-agent:5002",
            protocol="a2a"
        ))

        # Route MCP -> A2A
        mcp_msg = mcp_adapter.parse_message({
            "jsonrpc": "2.0",
            "id": "r1",
            "method": "tools/call",
            "params": {"name": "test"}
        })

        translated = engine.translate(
            mcp_adapter.serialize_message(mcp_msg),
            TranslationDirection.MCP_TO_A2A.value
        )

        # Route to A2A endpoint
        routing_result = mesh.route("a2a")
        assert routing_result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])