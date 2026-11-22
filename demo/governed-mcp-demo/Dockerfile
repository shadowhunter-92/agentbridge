# Synthetic local evaluator image; not a production or reproducible-release claim.
FROM python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements-runtime.lock ./
COPY demo/governed-mcp-demo/requirements-mcp.lock ./requirements-mcp.lock
RUN python -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --only-binary=:all: --require-hashes \
      -r requirements-runtime.lock -r requirements-mcp.lock && \
    /venv/bin/pip check
ENV PATH="/venv/bin:$PATH"
COPY src ./src
COPY examples/governed_mcp_demo.py examples/governed_mcp_tool.py ./examples/
COPY tools/inspect_governed_mcp_evidence.py ./tools/
RUN addgroup -S -g 10001 agentbridge && adduser -S -D -H -u 10001 -G agentbridge agentbridge && \
    mkdir /evidence && chown 10001:10001 /evidence
USER 10001:10001
ENTRYPOINT ["python", "-B", "-m", "examples.governed_mcp_demo"]
