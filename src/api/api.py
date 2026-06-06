"""
Agent Bridge API
================
FastAPI REST API for the Universal Agent Translator.

Enterprise-grade with:
- API authentication and rate limiting
- Structured logging and metrics
- Circuit breaker and retry logic
- Redis persistence

Author: MiniMax Agent
"""

import os
import logging
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, WebSocket, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import redis.asyncio as redis

from ..adapters.mcp_adapter import MCPAdapter, MCPTaskRequest
from ..adapters.a2a_adapter import A2AAdapter, A2ATaskRequest
from ..engine.translation_engine import TranslationEngine, TranslationDirection, TranslationResult
from ..routing.routing_mesh import RoutingMesh, Endpoint, EndpointStatus, RoutingResult
from ..middleware.auth import AuthService, APIKey, api_key_header, get_current_api_key, optional_api_key
from ..monitoring.logging_service import (
    initialize_monitoring, get_metrics, get_logging, get_tracing, get_health
)
from ..resilience.resilience import (
    get_circuit_manager, CircuitBreakerConfig, RetryConfig, retry_with_backoff
)
from ..persistence.redis_persistence import create_persistence, TranslationRecord

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global instances
redis_client: Optional[redis.Redis] = None
auth_service: Optional[AuthService] = None
persistence = None


async def optional_auth(api_key: Optional[str] = Depends(api_key_header)) -> Optional[APIKey]:
    """Resolve an optional API key against the global auth service singleton.

    Returns None when no key is provided or auth is not yet initialized, so
    unauthenticated requests still succeed.
    """
    if not api_key or auth_service is None:
        return None
    return auth_service.validate_key(api_key)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - initialize and cleanup."""
    global redis_client, auth_service, persistence

    # Initialize Redis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        redis_client = redis.from_url(redis_url, decode_responses=True)
        await redis_client.ping()
        logger.info("Redis connected successfully")
    except Exception as e:
        logger.warning(f"Redis connection failed, using in-memory fallback: {e}")
        redis_client = None

    # Initialize monitoring
    await initialize_monitoring(redis_client)

    # Initialize auth service
    auth_service = AuthService(redis_client)
    await auth_service.initialize()

    # Initialize persistence
    persistence = await create_persistence(redis_url if redis_client else None)

    # Register health checks
    health_service = get_health()

    async def redis_health_check():
        if redis_client:
            try:
                await redis_client.ping()
                return True
            except:
                return False
        return persistence.is_connected() if hasattr(persistence, 'is_connected') else True

    async def api_health_check():
        return True  # API is healthy if this runs

    await health_service.register_check("redis", redis_health_check, critical=False)
    await health_service.register_check("api", api_health_check, critical=True)

    logger.info("Agent Bridge API initialized")

    yield

    # Cleanup
    if redis_client:
        await redis_client.close()
    logger.info("Agent Bridge API shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Agent Bridge API",
    description="Universal Agent Translator - MCP/A2A Protocol Bridge (Enterprise Edition)",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
mcp_adapter = MCPAdapter()
a2a_adapter = A2AAdapter()
translation_engine = TranslationEngine()
routing_mesh = RoutingMesh()

# Initialize circuit breakers
circuit_manager = get_circuit_manager()
mcp_circuit = circuit_manager.get_or_create("mcp_forward", CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0
))
a2a_circuit = circuit_manager.get_or_create("a2a_forward", CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0
))

# Request/Response Models
class MCPRequest(BaseModel):
    """MCP protocol request."""
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[str] = None


class A2ARequest(BaseModel):
    """A2A protocol request."""
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[str] = None


class TranslateRequest(BaseModel):
    """Translation request."""
    source_protocol: str = Field(..., description="Source protocol (mcp or a2a)")
    target_protocol: str = Field(..., description="Target protocol (mcp or a2a)")
    data: Dict[str, Any] = Field(..., description="Data to translate")


class EndpointRegistration(BaseModel):
    """Endpoint registration request."""
    name: str
    url: str
    protocol: str  # "mcp" or "a2a"
    capabilities: Optional[List[str]] = []
    metadata: Optional[Dict[str, Any]] = {}


class TranslateResponse(BaseModel):
    """Translation response."""
    success: bool
    translation_id: Optional[str] = None
    source_protocol: str
    target_protocol: str
    source_data: Dict[str, Any]
    target_data: Dict[str, Any]
    warnings: Optional[List[str]] = []
    errors: Optional[List[str]] = []
    metadata: Optional[Dict[str, Any]] = {}


class APIKeyCreate(BaseModel):
    """API key creation request."""
    name: str
    tier: str = "free"


class APIKeyResponse(BaseModel):
    """API key response with raw key (only shown once)."""
    key_id: str
    raw_key: str
    name: str
    tier: str
    rate_limit: int
    window_seconds: int
    created_at: str


# Logging helper
async def log_request(request: Request, action: str, details: Dict = None):
    """Log request with tracing."""
    logging_service = get_logging()
    if logging_service:
        await logging_service.info(
            "api",
            f"{action}",
            trace_id=request.state.trace_id if hasattr(request.state, 'trace_id') else None,
            path=str(request.url.path),
            **(details or {})
        )


# Error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    metrics = get_metrics()
    if metrics:
        await metrics.increment("api_errors_total", labels={"exception": type(exc).__name__})

    logging_service = get_logging()
    if logging_service:
        await logging_service.error("api", f"Error: {str(exc)}", path=str(request.url.path))

    logger.error(f"Error processing request: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint with detailed status."""
    health_service = get_health()
    if health_service:
        health_results = await health_service.run_checks()
        return health_results
    return {
        "healthy": True,
        "service": "agent-bridge",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# API Info
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Agent Bridge API",
        "description": "Universal Agent Translator - MCP/A2A Protocol Bridge (Enterprise)",
        "version": "2.0.0",
        "documentation": "/docs",
        "features": [
            "api_authentication",
            "rate_limiting",
            "structured_logging",
            "metrics",
            "tracing",
            "circuit_breaker",
            "redis_persistence"
        ],
        "endpoints": {
            "translate": "/translate",
            "forward_mcp": "/forward/mcp",
            "forward_a2a": "/forward/a2a",
            "endpoints": "/endpoints",
            "registry": "/registry",
            "statistics": "/statistics",
            "metrics": "/metrics",
            "auth_keys": "/auth/keys"
        }
    }


# Auth endpoints
@app.post("/auth/keys", response_model=APIKeyResponse)
async def create_api_key(request: APIKeyCreate):
    """Create a new API key."""
    global auth_service
    if not auth_service:
        auth_service = AuthService(redis_client)

    raw_key, api_key = auth_service.generate_api_key(request.name, request.tier)

    # Store in Redis if available
    if redis_client:
        await auth_service.store_api_key(raw_key, api_key)

    return APIKeyResponse(
        key_id=api_key.key_id,
        raw_key=raw_key,
        name=api_key.name,
        tier=api_key.tier,
        rate_limit=api_key.rate_limit,
        window_seconds=api_key.window_seconds,
        created_at=api_key.created_at
    )


@app.get("/auth/keys")
async def list_api_keys():
    """List all API keys (without raw keys)."""
    global auth_service
    if not auth_service:
        auth_service = AuthService(redis_client)

    return {"keys": auth_service.list_keys()}


@app.delete("/auth/keys/{key_id}")
async def revoke_api_key(key_id: str):
    """Revoke an API key."""
    global auth_service
    if not auth_service:
        auth_service = AuthService(redis_client)

    success = await auth_service.revoke_key(key_id)
    if success:
        return {"success": True, "message": f"API key {key_id} revoked"}
    raise HTTPException(status_code=404, detail="API key not found")


# Translation endpoints
@app.post("/translate", response_model=TranslateResponse)
async def translate(
    request: TranslateRequest,
    api_key: Optional[APIKey] = Depends(optional_auth)
):
    """
    Translate between MCP and A2A protocols.

    Args:
        request: TranslateRequest with source/target protocols and data

    Returns:
        TranslateResponse with translated data
    """
    start_time = datetime.now(timezone.utc)
    translation_id = str(uuid.uuid4())

    try:
        # Determine direction
        if request.source_protocol == "mcp" and request.target_protocol == "a2a":
            direction = TranslationDirection.MCP_TO_A2A.value
        elif request.source_protocol == "a2a" and request.target_protocol == "mcp":
            direction = TranslationDirection.A2A_TO_MCP.value
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported translation: {request.source_protocol} -> {request.target_protocol}"
            )

        # Translate with retry
        retry_config = RetryConfig(max_attempts=3, base_delay=0.5)
        result = await retry_with_backoff(
            translation_engine.translate,
            retry_config,
            request.data,
            direction
        )

        # Store translation record
        if persistence:
            record = TranslationRecord(
                id=translation_id,
                source_protocol=request.source_protocol,
                target_protocol=request.target_protocol,
                source_data=request.data,
                target_data=result.target_data,
                duration_ms=(datetime.now(timezone.utc) - start_time).total_seconds() * 1000,
                status="success" if result.success else "partial",
                metadata={"api_key_id": api_key.key_id if api_key else None}
            )
            await persistence.store_translation(record)

        # Record metrics
        metrics = get_metrics()
        if metrics:
            await metrics.increment("translations_total", labels={
                "source": request.source_protocol,
                "target": request.target_protocol
            })
            await metrics.timing(
                "translation_duration_ms",
                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000,
                labels={"source": request.source_protocol, "target": request.target_protocol}
            )

        return TranslateResponse(
            success=result.success,
            translation_id=translation_id,
            source_protocol=request.source_protocol,
            target_protocol=request.target_protocol,
            source_data=result.source_data,
            target_data=result.target_data,
            warnings=result.warnings,
            errors=result.errors,
            metadata=result.metadata
        )

    except HTTPException:
        # Intentional HTTP errors (e.g. unsupported direction) pass through unchanged.
        raise
    except Exception as e:
        metrics = get_metrics()
        if metrics:
            await metrics.increment("translation_errors_total", labels={
                "source": request.source_protocol,
                "target": request.target_protocol
            })
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/translate/batch")
async def translate_batch(requests: List[TranslateRequest]):
    """Batch translate multiple requests."""
    results = []
    start_time = datetime.now(timezone.utc)

    for req in requests:
        try:
            if req.source_protocol == "mcp" and req.target_protocol == "a2a":
                direction = TranslationDirection.MCP_TO_A2A.value
            else:
                direction = TranslationDirection.A2A_TO_MCP.value

            result = translation_engine.translate(req.data, direction)

            results.append({
                "success": result.success,
                "source_protocol": req.source_protocol,
                "target_protocol": req.target_protocol,
                "target_data": result.target_data,
                "warnings": result.warnings,
                "errors": result.errors
            })

        except Exception as e:
            results.append({
                "success": False,
                "error": str(e)
            })

    # Record metrics
    metrics = get_metrics()
    if metrics:
        await metrics.increment("batch_translations_total", labels={"count": str(len(requests))})
        await metrics.timing("batch_translation_duration_ms", (datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

    return {"results": results, "total": len(results), "successful": sum(1 for r in results if r.get("success"))}


# Forwarding endpoints with circuit breaker
@app.post("/forward/mcp")
async def forward_mcp(mcp_request: MCPRequest, background_tasks: BackgroundTasks):
    """Forward MCP request to target, translating to A2A."""
    try:
        msg_id = mcp_request.id or str(uuid.uuid4())

        mcp_message = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": mcp_request.method,
            "params": mcp_request.params or {}
        }

        # Use circuit breaker for forwarding
        async def forward_operation():
            return translation_engine.translate(mcp_message, TranslationDirection.MCP_TO_A2A.value)

        result = await mcp_circuit.call(forward_operation)

        if result.success:
            routing_result = routing_mesh.route("a2a")

            if routing_result.success:
                return {
                    "success": True,
                    "source": "mcp",
                    "target": "a2a",
                    "translated_data": result.target_data,
                    "routed_to": routing_result.target_url,
                    "endpoint": routing_result.endpoint.id if routing_result.endpoint else None
                }
            else:
                return {
                    "success": True,
                    "source": "mcp",
                    "target": "a2a",
                    "translated_data": result.target_data,
                    "routing_warning": routing_result.error
                }
        else:
            raise HTTPException(status_code=400, detail="Translation failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MCP forward error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/forward/a2a")
async def forward_a2a(a2a_request: A2ARequest, background_tasks: BackgroundTasks):
    """Forward A2A request to target, translating to MCP."""
    try:
        msg_id = a2a_request.id or str(uuid.uuid4())

        a2a_message = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": a2a_request.method,
            "params": a2a_request.params or {}
        }

        # Use circuit breaker for forwarding
        async def forward_operation():
            return translation_engine.translate(a2a_message, TranslationDirection.A2A_TO_MCP.value)

        result = await a2a_circuit.call(forward_operation)

        if result.success:
            routing_result = routing_mesh.route("mcp")

            if routing_result.success:
                return {
                    "success": True,
                    "source": "a2a",
                    "target": "mcp",
                    "translated_data": result.target_data,
                    "routed_to": routing_result.target_url,
                    "endpoint": routing_result.endpoint.id if routing_result.endpoint else None
                }
            else:
                return {
                    "success": True,
                    "source": "a2a",
                    "target": "mcp",
                    "translated_data": result.target_data,
                    "routing_warning": routing_result.error
                }
        else:
            raise HTTPException(status_code=400, detail="Translation failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"A2A forward error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Endpoint management
@app.post("/endpoints")
async def register_endpoint(registration: EndpointRegistration):
    """Register a new endpoint."""
    try:
        endpoint_id = str(uuid.uuid4())

        endpoint = Endpoint(
            id=endpoint_id,
            name=registration.name,
            url=registration.url,
            protocol=registration.protocol,
            capabilities=registration.capabilities,
            metadata=registration.metadata or {}
        )

        success = routing_mesh.register_endpoint(endpoint)

        if success:
            # Record metric
            metrics = get_metrics()
            if metrics:
                await metrics.increment("endpoints_registered_total", labels={"protocol": registration.protocol})

            return {
                "success": True,
                "endpoint": {
                    "id": endpoint_id,
                    "name": registration.name,
                    "url": registration.url,
                    "protocol": registration.protocol
                }
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to register endpoint")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Endpoint registration error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/endpoints/{endpoint_id}")
async def unregister_endpoint(endpoint_id: str):
    """Unregister an endpoint."""
    success = routing_mesh.unregister_endpoint(endpoint_id)

    if success:
        metrics = get_metrics()
        if metrics:
            await metrics.increment("endpoints_unregistered_total")
        return {"success": True, "message": f"Endpoint {endpoint_id} unregistered"}
    else:
        raise HTTPException(status_code=404, detail="Endpoint not found")


@app.get("/endpoints")
async def list_endpoints(protocol: Optional[str] = None):
    """List all endpoints or filter by protocol."""
    if protocol:
        endpoints = routing_mesh.get_endpoints_by_protocol(protocol)
    else:
        endpoints = list(routing_mesh._endpoints.values())

    return {
        "endpoints": [
            {
                "id": e.id,
                "name": e.name,
                "url": e.url,
                "protocol": e.protocol,
                "status": e.status,
                "capabilities": e.capabilities
            }
            for e in endpoints
        ],
        "total": len(endpoints)
    }


# Registry endpoints
@app.get("/registry")
async def get_registry():
    """Get full endpoint registry."""
    return {
        "registry": routing_mesh.get_registry(),
        "statistics": routing_mesh.get_statistics()
    }


# Statistics endpoint
@app.get("/statistics")
async def get_statistics():
    """Get routing mesh statistics and metrics."""
    stats = routing_mesh.get_statistics()

    # Add circuit breaker states
    circuit_states = circuit_manager.get_all_states()

    # Add Redis persistence stats if available
    persistence_stats = {}
    if persistence and hasattr(persistence, 'get_all_stats'):
        persistence_stats = await persistence.get_all_stats()

    return {
        "routing": stats,
        "circuit_breakers": circuit_states,
        "persistence": persistence_stats
    }


# Metrics endpoint
@app.get("/metrics")
async def get_metrics_data():
    """Get current metrics."""
    metrics = get_metrics()
    if metrics:
        return metrics.get_stats()
    return {"message": "Metrics not initialized"}


# Capabilities endpoint
@app.get("/capabilities")
async def get_capabilities():
    """Get bridge capabilities."""
    return {
        "protocols": ["mcp", "a2a"],
        "features": [
            "translation",
            "routing",
            "load_balancing",
            "health_checks",
            "endpoint_registry",
            "api_authentication",
            "rate_limiting",
            "structured_logging",
            "metrics",
            "tracing",
            "circuit_breaker",
            "redis_persistence",
            "batch_translation"
        ],
        "mcp_capabilities": mcp_adapter.get_capabilities(),
        "a2a_capabilities": a2a_adapter.get_capabilities(),
        "supported_mappings": {
            "mcp_to_a2a": translation_engine.get_supported_mappings("mcp_to_a2a"),
            "a2a_to_mcp": translation_engine.get_supported_mappings("a2a_to_mcp")
        }
    }


# Translation history endpoint
@app.get("/history")
async def get_translation_history(user_id: Optional[str] = None, limit: int = 100):
    """Get translation history from Redis."""
    if not persistence:
        return {"translations": [], "total": 0}

    if user_id:
        translations = await persistence.get_user_translations(user_id, limit)
        return {
            "translations": [
                {
                    "id": t.id,
                    "source_protocol": t.source_protocol,
                    "target_protocol": t.target_protocol,
                    "status": t.status,
                    "created_at": t.created_at
                }
                for t in translations
            ],
            "total": len(translations)
        }

    return {"translations": [], "total": 0}


# WebSocket for real-time translations
@app.websocket("/ws/translate")
async def websocket_translate(websocket: WebSocket):
    """WebSocket endpoint for real-time translations."""
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_json()

            source_protocol = data.get("source_protocol")
            target_protocol = data.get("target_protocol")
            message = data.get("data")

            if source_protocol and target_protocol and message:
                if source_protocol == "mcp" and target_protocol == "a2a":
                    direction = TranslationDirection.MCP_TO_A2A.value
                else:
                    direction = TranslationDirection.A2A_TO_MCP.value

                result = translation_engine.translate(message, direction)

                await websocket.send_json({
                    "success": result.success,
                    "source_protocol": source_protocol,
                    "target_protocol": target_protocol,
                    "target_data": result.target_data,
                    "warnings": result.warnings,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)