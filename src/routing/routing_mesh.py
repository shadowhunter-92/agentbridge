"""
Routing Mesh
============
Endpoint registry and load balancing for protocol bridge.

Handles agent discovery, routing, and load balancing.

Author: MiniMax Agent
"""

import json
import logging
import asyncio
import hashlib
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from collections import defaultdict
import uuid

logger = logging.getLogger(__name__)


class EndpointStatus(str, Enum):
    """Endpoint status values."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    OVERLOADED = "overloaded"
    DRAINING = "draining"


class RoutingStrategy(str, Enum):
    """Routing strategy types."""
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    WEIGHTED = "weighted"
    RANDOM = "random"
    HASH = "hash"


@dataclass
class Endpoint:
    """Agent endpoint representation."""
    id: str
    name: str
    url: str
    protocol: str  # "mcp" or "a2a"
    status: str = EndpointStatus.ACTIVE.value
    weight: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    health_check_url: Optional[str] = None
    last_health_check: Optional[str] = None
    consecutive_failures: int = 0
    connections: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Route:
    """Route information."""
    endpoint_id: str
    path: str
    method: Optional[str] = None
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingResult:
    """Result of routing operation."""
    success: bool
    endpoint: Optional[Endpoint]
    target_url: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class RoutingMesh:
    """
    Routing Mesh for agent endpoints.

    Manages endpoint registry, health checks, and load balancing.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize routing mesh.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.strategy = RoutingStrategy(
            self.config.get("strategy", "round_robin")
        )
        self.health_check_interval = self.config.get("health_check_interval", 60)
        self.max_consecutive_failures = self.config.get("max_consecutive_failures", 3)

        # Endpoint storage
        self._endpoints: Dict[str, Endpoint] = {}
        self._endpoints_by_protocol: Dict[str, List[str]] = {
            "mcp": [],
            "a2a": []
        }

        # Routing tables
        self._routes: Dict[str, List[Route]] = defaultdict(list)
        self._route_counters: Dict[str, int] = defaultdict(int)

        # Connection tracking
        self._active_connections: Dict[str, int] = defaultdict(int)
        self._connection_history: Dict[str, List[datetime]] = defaultdict(list)

        logger.info(f"Routing Mesh initialized with strategy: {self.strategy.value}")

    def register_endpoint(self, endpoint: Endpoint) -> bool:
        """
        Register a new endpoint.

        Args:
            endpoint: Endpoint to register

        Returns:
            bool: True if successful
        """
        try:
            # Validate endpoint
            if not endpoint.id or not endpoint.url:
                logger.error("Invalid endpoint: missing id or url")
                return False

            # Add to storage
            self._endpoints[endpoint.id] = endpoint
            self._endpoints_by_protocol[endpoint.protocol].append(endpoint.id)

            logger.info(f"Registered endpoint: {endpoint.id} ({endpoint.protocol}) at {endpoint.url}")
            return True

        except Exception as e:
            logger.error(f"Failed to register endpoint: {e}")
            return False

    def unregister_endpoint(self, endpoint_id: str) -> bool:
        """
        Unregister an endpoint.

        Args:
            endpoint_id: Endpoint ID to remove

        Returns:
            bool: True if successful
        """
        if endpoint_id not in self._endpoints:
            return False

        endpoint = self._endpoints[endpoint_id]
        self._endpoints_by_protocol[endpoint.protocol].remove(endpoint_id)
        del self._endpoints[endpoint_id]

        logger.info(f"Unregistered endpoint: {endpoint_id}")
        return True

    def get_endpoint(self, endpoint_id: str) -> Optional[Endpoint]:
        """
        Get endpoint by ID.

        Args:
            endpoint_id: Endpoint ID

        Returns:
            Optional[Endpoint]: Endpoint if found
        """
        return self._endpoints.get(endpoint_id)

    def get_endpoints_by_protocol(self, protocol: str) -> List[Endpoint]:
        """
        Get all endpoints for a protocol.

        Args:
            protocol: Protocol ("mcp" or "a2a")

        Returns:
            List of endpoints
        """
        endpoint_ids = self._endpoints_by_protocol.get(protocol, [])
        return [self._endpoints[eid] for eid in endpoint_ids if eid in self._endpoints]

    def route(self, protocol: str, task_id: Optional[str] = None,
              context: Optional[Dict[str, Any]] = None) -> RoutingResult:
        """
        Route to an endpoint based on strategy.

        Args:
            protocol: Protocol ("mcp" or "a2a")
            task_id: Optional task ID for hash-based routing
            context: Optional routing context

        Returns:
            RoutingResult: Routing result with target endpoint
        """
        try:
            endpoints = self.get_endpoints_by_protocol(protocol)

            if not endpoints:
                return RoutingResult(
                    success=False,
                    endpoint=None,
                    target_url="",
                    error=f"No endpoints available for protocol: {protocol}"
                )

            # Filter active endpoints
            active_endpoints = [e for e in endpoints if e.status == EndpointStatus.ACTIVE.value]

            if not active_endpoints:
                return RoutingResult(
                    success=False,
                    endpoint=None,
                    target_url="",
                    error=f"No active endpoints for protocol: {protocol}"
                )

            # Select endpoint based on strategy
            selected = self._select_endpoint(active_endpoints, task_id, context)

            if selected:
                # Track connection
                self._track_connection(selected.id)

                return RoutingResult(
                    success=True,
                    endpoint=selected,
                    target_url=selected.url,
                    metadata={
                        "strategy": self.strategy.value,
                        "total_endpoints": len(endpoints),
                        "active_endpoints": len(active_endpoints)
                    }
                )
            else:
                return RoutingResult(
                    success=False,
                    endpoint=None,
                    target_url="",
                    error="Failed to select endpoint"
                )

        except Exception as e:
            logger.error(f"Routing failed: {e}")
            return RoutingResult(
                success=False,
                endpoint=None,
                target_url="",
                error=str(e)
            )

    def _select_endpoint(self, endpoints: List[Endpoint],
                         task_id: Optional[str] = None,
                         context: Optional[Dict[str, Any]] = None) -> Optional[Endpoint]:
        """Select endpoint based on routing strategy."""
        if self.strategy == RoutingStrategy.ROUND_ROBIN:
            return self._round_robin_select(endpoints)
        elif self.strategy == RoutingStrategy.LEAST_CONNECTIONS:
            return self._least_connections_select(endpoints)
        elif self.strategy == RoutingStrategy.WEIGHTED:
            return self._weighted_select(endpoints)
        elif self.strategy == RoutingStrategy.HASH:
            return self._hash_select(endpoints, task_id)
        else:
            return self._random_select(endpoints)

    def _round_robin_select(self, endpoints: List[Endpoint]) -> Endpoint:
        """Round-robin selection."""
        key = hash(tuple(sorted([e.id for e in endpoints])))
        counter = self._route_counters[key]
        selected = endpoints[counter % len(endpoints)]
        self._route_counters[key] = counter + 1
        return selected

    def _least_connections_select(self, endpoints: List[Endpoint]) -> Endpoint:
        """Select endpoint with least connections."""
        return min(endpoints, key=lambda e: self._active_connections.get(e.id, 0))

    def _weighted_select(self, endpoints: List[Endpoint]) -> Endpoint:
        """Weighted selection based on endpoint weights."""
        total_weight = sum(e.weight for e in endpoints)
        import random
        rand = random.randint(0, total_weight - 1)

        cumulative = 0
        for endpoint in endpoints:
            cumulative += endpoint.weight
            if rand < cumulative:
                return endpoint

        return endpoints[0]

    def _hash_select(self, endpoints: List[Endpoint],
                     task_id: Optional[str] = None) -> Endpoint:
        """Hash-based selection for consistent routing."""
        if not task_id:
            return self._random_select(endpoints)

        hash_value = int(hashlib.md5(task_id.encode()).hexdigest(), 16)
        index = hash_value % len(endpoints)
        return endpoints[index]

    def _random_select(self, endpoints: List[Endpoint]) -> Endpoint:
        """Random selection."""
        import random
        return random.choice(endpoints)

    def _track_connection(self, endpoint_id: str) -> None:
        """Track active connection to endpoint."""
        self._active_connections[endpoint_id] += 1
        self._connection_history[endpoint_id].append(datetime.now(timezone.utc))

    def release_connection(self, endpoint_id: str) -> None:
        """Release connection from endpoint."""
        if self._active_connections.get(endpoint_id, 0) > 0:
            self._active_connections[endpoint_id] -= 1

    def update_endpoint_status(self, endpoint_id: str, status: str) -> bool:
        """
        Update endpoint status.

        Args:
            endpoint_id: Endpoint ID
            status: New status

        Returns:
            bool: True if successful
        """
        if endpoint_id not in self._endpoints:
            return False

        endpoint = self._endpoints[endpoint_id]
        endpoint.status = status
        endpoint.updated_at = datetime.now(timezone.utc).isoformat()

        logger.info(f"Updated endpoint {endpoint_id} status to {status}")
        return True

    def record_failure(self, endpoint_id: str) -> None:
        """
        Record endpoint failure.

        Args:
            endpoint_id: Endpoint ID
        """
        if endpoint_id not in self._endpoints:
            return

        endpoint = self._endpoints[endpoint_id]
        endpoint.consecutive_failures += 1

        if endpoint.consecutive_failures >= self.max_consecutive_failures:
            endpoint.status = EndpointStatus.INACTIVE.value
            logger.warning(f"Endpoint {endpoint_id} marked inactive after {endpoint.consecutive_failures} failures")

    def record_success(self, endpoint_id: str) -> None:
        """
        Record successful connection to endpoint.

        Args:
            endpoint_id: Endpoint ID
        """
        if endpoint_id not in self._endpoints:
            return

        endpoint = self._endpoints[endpoint_id]
        endpoint.consecutive_failures = 0
        endpoint.last_health_check = datetime.now(timezone.utc).isoformat()

    def health_check(self, endpoint_id: str) -> bool:
        """
        Perform health check on endpoint.

        Args:
            endpoint_id: Endpoint ID

        Returns:
            bool: True if healthy
        """
        if endpoint_id not in self._endpoints:
            return False

        endpoint = self._endpoints[endpoint_id]

        # In production, would perform actual HTTP health check
        # For now, assume healthy if consecutive_failures < threshold
        is_healthy = endpoint.consecutive_failures < self.max_consecutive_failures

        if is_healthy and endpoint.status != EndpointStatus.ACTIVE.value:
            endpoint.status = EndpointStatus.ACTIVE.value

        endpoint.last_health_check = datetime.now(timezone.utc).isoformat()

        return is_healthy

    def add_route(self, protocol: str, route: Route) -> None:
        """
        Add routing rule.

        Args:
            protocol: Protocol
            route: Route to add
        """
        self._routes[protocol].append(route)
        logger.info(f"Added route for {protocol}: {route.path}")

    def find_route(self, protocol: str, path: str) -> Optional[Route]:
        """
        Find matching route.

        Args:
            protocol: Protocol
            path: Request path

        Returns:
            Optional[Route]: Matching route if found
        """
        routes = self._routes.get(protocol, [])

        for route in sorted(routes, key=lambda r: r.priority, reverse=True):
            if path.startswith(route.path):
                return route

        return None

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get routing mesh statistics.

        Returns:
            Dict containing statistics
        """
        total_endpoints = len(self._endpoints)
        active_endpoints = sum(
            1 for e in self._endpoints.values()
            if e.status == EndpointStatus.ACTIVE.value
        )

        return {
            "total_endpoints": total_endpoints,
            "active_endpoints": active_endpoints,
            "inactive_endpoints": total_endpoints - active_endpoints,
            "by_protocol": {
                protocol: len(ids)
                for protocol, ids in self._endpoints_by_protocol.items()
            },
            "total_connections": sum(self._active_connections.values()),
            "strategy": self.strategy.value,
            "endpoints": [
                {
                    "id": e.id,
                    "name": e.name,
                    "protocol": e.protocol,
                    "status": e.status,
                    "connections": self._active_connections.get(e.id, 0)
                }
                for e in self._endpoints.values()
            ]
        }

    def clear_endpoints(self) -> None:
        """Clear all endpoints (for testing)."""
        self._endpoints.clear()
        self._endpoints_by_protocol = {"mcp": [], "a2a": []}
        self._active_connections.clear()
        self._route_counters.clear()
        logger.info("Cleared all endpoints")

    def get_registry(self) -> List[Dict[str, Any]]:
        """
        Get full endpoint registry.

        Returns:
            List of endpoint dictionaries
        """
        return [
            {
                "id": e.id,
                "name": e.name,
                "url": e.url,
                "protocol": e.protocol,
                "status": e.status,
                "capabilities": e.capabilities,
                "metadata": e.metadata
            }
            for e in self._endpoints.values()
        ]