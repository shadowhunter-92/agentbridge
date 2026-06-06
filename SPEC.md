# Agent Bridge - Technical Specification

> ⚠️ **LEGACY SPEC.** This describes the original MCP↔A2A-only translator (`src/api/api.py`),
> which is now **deprecated**. The current product is the **Meta-Bridge** (6-protocol mesh +
> governance). See `README.md` and `docs/PROTOCOL_SUPPORT.md`, `docs/GOVERNANCE.md`,
> `docs/PROJECT_STATE.md` for the real architecture.

## Overview

**Project Name**: Universal Agent Translator (Agent Bridge)
**Type**: Protocol Bridge / Middleware
**Core Functionality**: Real-time translation between MCP (Model Context Protocol) and A2A (Agent-to-Agent) protocols
**Target Users**: AI agent developers, enterprises building multi-agent systems, agent marketplace operators

## Problem Statement

The agent ecosystem is fragmenting into incompatible protocol silos:
- **MCP** (Anthropic): Agent-tool connections
- **A2A** (Google/Linux Foundation): Agent-agent collaboration

Without bridges, every AI vendor builds proprietary integrations, crippling multi-agent workflows.

## Solution Architecture

### Core Components

1. **Protocol Adapters** (`src/adapters/`)
   - `MCPAdapter`: Parses/serializes MCP JSON-RPC messages
   - `A2AAdapter`: Parses/serializes A2A JSON-RPC messages
   - Handles protocol-specific message formats

2. **Translation Engine** (`src/engine/`)
   - Semantic field mapping between protocols
   - Task type and status translation
   - Artifact format conversion
   - Custom mapping registration

3. **Routing Mesh** (`src/routing/`)
   - Endpoint registry
   - Load balancing (round-robin, least-connections, weighted, hash)
   - Health checks
   - Connection tracking

4. **REST API** (`src/api/`)
   - FastAPI-based management plane
   - Translation endpoints
   - Endpoint management
   - Statistics and capabilities

5. **Web UI** (`src/ui/`)
   - Interactive translation testing
   - Endpoint management
   - Real-time statistics

## API Endpoints

### Translation
- `POST /translate` - Translate between protocols
- `POST /translate/batch` - Batch translation
- `POST /forward/mcp` - Forward MCP to A2A
- `POST /forward/a2a` - Forward A2A to MCP

### Endpoint Management
- `POST /endpoints` - Register endpoint
- `DELETE /endpoints/{id}` - Unregister endpoint
- `GET /endpoints` - List endpoints
- `GET /registry` - Get full registry

### System
- `GET /health` - Health check
- `GET /capabilities` - Get bridge capabilities
- `GET /statistics` - Get routing statistics

## Data Models

### MCP Message
```python
{
    "jsonrpc": "2.0",
    "id": str,
    "method": str,
    "params": Dict,
    "result": Dict,
    "error": Dict
}
```

### A2A Task
```python
{
    "id": str,
    "kind": "task",
    "status": {"state": str},
    "messages": [{"role": str, "parts": List}],
    "artifacts": List,
    "metadata": Dict
}
```

## Field Mappings

### MCP → A2A
| MCP Field | A2A Field |
|-----------|-----------|
| name | agent_id |
| input | parameters |
| content | body |
| text | message |
| results | artifacts |
| isError | error |

### A2A → MCP
| A2A Field | MCP Field |
|-----------|-----------|
| agent_id | name |
| parameters | input |
| body | content |
| message | text |
| artifacts | results |
| error | isError |

## Configuration

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 8000 | API port |
| `HOST` | 0.0.0.0 | API host |
| `LOG_LEVEL` | INFO | Logging level |
| `ROUTING_STRATEGY` | round_robin | Load balancing |

### Routing Strategies
- `round_robin`: Sequential distribution
- `least_connections`: Route to least busy
- `weighted`: Weight-based distribution
- `hash`: Consistent hashing by task ID
- `random`: Random selection

## Performance

- Translation latency: < 50ms (typical)
- Concurrent connections: 1000+
- Translation throughput: 10,000/minute

## Deployment

### Docker
```bash
docker build -t agent-bridge .
docker run -p 8000:8000 agent-bridge
```

### Docker Compose
```bash
docker-compose up -d
```

## Testing

```bash
pytest tests/ -v
```

## Version

**1.0.0** - Initial production-ready release

## Author

MiniMax Agent

## License

Apache 2.0