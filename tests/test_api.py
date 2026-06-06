"""
API Integration Tests
====================

Test the FastAPI endpoints with enterprise features.

Author: MiniMax Agent
"""

import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock

# Mock the external dependencies before importing the app
import sys
sys.modules['redis'] = MagicMock()
sys.modules['redis.asyncio'] = MagicMock()

from src.api.api import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check(self, client):
        """Test basic health check."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "healthy" in data or "status" in data


class TestRootEndpoint:
    """Test root endpoint."""

    def test_root(self, client):
        """Test root endpoint returns API info."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "version" in data
        assert "features" in data


class TestCapabilitiesEndpoint:
    """Test capabilities endpoint."""

    def test_capabilities(self, client):
        """Test getting bridge capabilities."""
        response = client.get("/capabilities")

        assert response.status_code == 200
        data = response.json()
        assert "protocols" in data
        assert "features" in data
        assert "mcp_capabilities" in data
        assert "a2a_capabilities" in data


class TestTranslateEndpoint:
    """Test translation endpoint."""

    def test_translate_mcp_to_a2a(self, client):
        """Test MCP to A2A translation."""
        payload = {
            "source_protocol": "mcp",
            "target_protocol": "a2a",
            "data": {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {
                    "name": "test_tool",
                    "arguments": {"arg": "value"}
                }
            }
        }

        response = client.post("/translate", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["source_protocol"] == "mcp"
        assert data["target_protocol"] == "a2a"
        assert "target_data" in data

    def test_translate_a2a_to_mcp(self, client):
        """Test A2A to MCP translation."""
        payload = {
            "source_protocol": "a2a",
            "target_protocol": "mcp",
            "data": {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tasks/send",
                "params": {
                    "task": {
                        "id": "task-1",
                        "kind": "task",
                        "status": {"state": "submitted"}
                    }
                }
            }
        }

        response = client.post("/translate", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["source_protocol"] == "a2a"
        assert data["target_protocol"] == "mcp"

    def test_translate_unsupported_direction(self, client):
        """Test unsupported translation direction."""
        payload = {
            "source_protocol": "mcp",
            "target_protocol": "http",
            "data": {}
        }

        response = client.post("/translate", json=payload)

        assert response.status_code == 400


class TestBatchTranslateEndpoint:
    """Test batch translation endpoint."""

    def test_batch_translate(self, client):
        """Test batch translation."""
        payload = [
            {
                "source_protocol": "mcp",
                "target_protocol": "a2a",
                "data": {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "tools/call"
                }
            },
            {
                "source_protocol": "a2a",
                "target_protocol": "mcp",
                "data": {
                    "jsonrpc": "2.0",
                    "id": "2",
                    "method": "tasks/send"
                }
            }
        ]

        response = client.post("/translate/batch", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert data["total"] == 2


class TestEndpointsEndpoint:
    """Test endpoint management endpoints."""

    def test_register_endpoint(self, client):
        """Test registering an endpoint."""
        payload = {
            "name": "Test MCP Agent",
            "url": "http://localhost:5001",
            "protocol": "mcp",
            "capabilities": ["tools", "resources"],
            "metadata": {"version": "1.0"}
        }

        response = client.post("/endpoints", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "endpoint" in data

    def test_list_endpoints(self, client):
        """Test listing endpoints."""
        response = client.get("/endpoints")

        assert response.status_code == 200
        data = response.json()
        assert "endpoints" in data
        assert "total" in data

    def test_list_endpoints_filter_by_protocol(self, client):
        """Test listing endpoints filtered by protocol."""
        response = client.get("/endpoints?protocol=mcp")

        assert response.status_code == 200
        data = response.json()
        assert "endpoints" in data


class TestForwardEndpoints:
    """Test forwarding endpoints."""

    def test_forward_mcp(self, client):
        """Test forwarding MCP request."""
        payload = {
            "method": "tools/call",
            "params": {
                "name": "test_tool",
                "arguments": {}
            },
            "id": "test-123"
        }

        response = client.post("/forward/mcp", json=payload)

        # May fail due to no endpoints registered, but should not be 500
        assert response.status_code in [200, 400, 404]

    def test_forward_a2a(self, client):
        """Test forwarding A2A request."""
        payload = {
            "method": "tasks/send",
            "params": {
                "task": {
                    "id": "task-1",
                    "kind": "task"
                }
            },
            "id": "test-456"
        }

        response = client.post("/forward/a2a", json=payload)

        # May fail due to no endpoints registered, but should not be 500
        assert response.status_code in [200, 400, 404]


class TestRegistryEndpoint:
    """Test registry endpoint."""

    def test_get_registry(self, client):
        """Test getting registry."""
        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()
        assert "registry" in data
        assert "statistics" in data


class TestStatisticsEndpoint:
    """Test statistics endpoint."""

    def test_get_statistics(self, client):
        """Test getting statistics."""
        response = client.get("/statistics")

        assert response.status_code == 200
        data = response.json()
        assert "routing" in data or "circuit_breakers" in data


class TestMetricsEndpoint:
    """Test metrics endpoint."""

    def test_get_metrics(self, client):
        """Test getting metrics."""
        response = client.get("/metrics")

        assert response.status_code == 200
        data = response.json()
        # Should return metrics data structure
        assert isinstance(data, dict)


class TestWebSocketEndpoint:
    """Test WebSocket endpoint."""

    def test_websocket_connection(self, client):
        """Test WebSocket connection."""
        with client.websocket_connect("/ws/translate") as websocket:
            # Send a translation request
            websocket.send_json({
                "source_protocol": "mcp",
                "target_protocol": "a2a",
                "data": {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "tools/call"
                }
            })

            # Should receive response
            response = websocket.receive_json()
            assert "success" in response


class TestAPIKeyEndpoints:
    """Test API key management endpoints."""

    def test_create_api_key(self, client):
        """Test creating an API key."""
        payload = {
            "name": "Test API Key",
            "tier": "free"
        }

        response = client.post("/auth/keys", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "key_id" in data
        assert "raw_key" in data
        assert data["name"] == "Test API Key"

    def test_list_api_keys(self, client):
        """Test listing API keys."""
        response = client.get("/auth/keys")

        assert response.status_code == 200
        data = response.json()
        assert "keys" in data

    def test_revoke_api_key(self, client):
        """Test revoking an API key."""
        # First create a key
        create_response = client.post("/auth/keys", json={
            "name": "Key to Revoke",
            "tier": "free"
        })
        key_id = create_response.json()["key_id"]

        # Then revoke it
        response = client.delete(f"/auth/keys/{key_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestHistoryEndpoint:
    """Test translation history endpoint."""

    def test_get_history_no_user(self, client):
        """Test getting history without user ID."""
        response = client.get("/history")

        assert response.status_code == 200
        data = response.json()
        assert "translations" in data


class TestErrorHandling:
    """Test error handling."""

    def test_invalid_json(self, client):
        """Test handling of invalid JSON."""
        response = client.post(
            "/translate",
            content="not valid json",
            headers={"Content-Type": "application/json"}
        )

        # Should return 422 (validation error) or 500
        assert response.status_code in [400, 422, 500]

    def test_missing_required_fields(self, client):
        """Test handling of missing required fields."""
        payload = {
            "source_protocol": "mcp"
            # Missing target_protocol and data
        }

        response = client.post("/translate", json=payload)

        assert response.status_code == 422  # Validation error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])