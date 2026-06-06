# Agent Bridge - Enterprise Edition
# Multi-stage build for optimized production image

# Stage 1: Builder
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
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

# Install runtime dependencies only
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

# Create directories for runtime data
RUN mkdir -p /app/logs /app/data /app/certs && \
    chown -R agentbridge:agentbridge /app

# Switch to non-root user
USER agentbridge

# Environment variables
ENV PYTHONDONTWRITECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    LOG_LEVEL=INFO

# Expose ports
EXPOSE 8000

# Health check - verify the API is responsive
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the Meta-Bridge control plane (N-protocol mesh + governance).
# Set AGENTBRIDGE_ADMIN_KEY and AGENTBRIDGE_DB in production.
CMD ["uvicorn", "src.api.control_plane:app", "--host", "0.0.0.0", "--port", "8000"]

# Legacy MCP<->A2A app (deprecated):
# CMD ["python", "-m", "src.api.api"]