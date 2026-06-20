# AgentBridge — Meta-Bridge Control Plane
# Production-ready, multi-stage Docker build

# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Production
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user for security
RUN groupadd --gid 1000 agentbridge && \
    useradd --uid 1000 --gid agentbridge --shell /bin/bash --create-home agentbridge

# Copy application code
COPY --chown=agentbridge:agentbridge src/ ./src/
COPY --chown=agentbridge:agentbridge main.py ./

# Create directories for runtime data
RUN mkdir -p /app/data && \
    chown -R agentbridge:agentbridge /app

# Switch to non-root user
USER agentbridge

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0

# Expose ports
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the Meta-Bridge control plane
CMD ["uvicorn", "src.api.control_plane:app", "--host", "0.0.0.0", "--port", "8000"]
