.PHONY: help install test test-live lint format clean build publish docker-up docker-down demo

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies for development
	python -m pip install --upgrade pip
	pip install -e ".[dev]"

test: ## Run the full test suite (fast, no live agents)
	pytest tests/ -q --tb=short

test-live: ## Run live protocol tests (needs real SDKs installed)
	pytest tests/test_protocols_conformance.py tests/test_nprotocol_live.py tests/test_inline_proxy.py -v --tb=short

test-governance: ## Run governance and concurrency tests
	pytest tests/test_governance.py tests/test_governance_v2.py tests/test_enterprise_governance.py tests/test_concurrency.py -v --tb=short

lint: ## Run linting with ruff
	ruff check src/ tests/

format: ## Auto-format code with ruff
	ruff format src/ tests/

clean: ## Remove build artifacts
	rm -rf build/ dist/ *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

build: ## Build PyPI package
	python -m build

publish: build ## Build and publish to PyPI (requires TWINE_USERNAME and TWINE_PASSWORD env vars)
	twine upload dist/*

docker-up: ## Start AgentBridge with Docker Compose
	docker-compose up --build -d

docker-down: ## Stop Docker Compose services
	docker-compose down

docker-logs: ## Tail Docker logs
	docker-compose logs -f

demo: ## Run the 60-second demo story
	python examples/demo_story.py

quickstart: ## Run the quickstart (zero governance)
	python examples/quickstart.py

serve: ## Start the control plane API locally
	uvicorn src.api.control_plane:app --host 0.0.0.0 --port 8000 --reload

serve-mcp: ## Start the drop-in MCP server
	python -m src.serve.mcp_gateway

benchmark: ## Run the performance benchmark
	python tools/benchmark.py

coverage: ## Run tests with coverage report
	pytest tests/ -q --cov=src --cov-report=term --cov-report=html

docker-dev: ## Build and run the development Docker image (with hot reload)
	docker build -f Dockerfile.dev -t agentbridge:dev .
	docker run -p 8000:8000 -v $(PWD)/src:/app/src agentbridge:dev

k8s-deploy: ## Deploy to Kubernetes
	kubectl apply -f k8s/deployment.yaml

k8s-delete: ## Remove from Kubernetes
	kubectl delete -f k8s/deployment.yaml

k8s-logs: ## Tail Kubernetes logs
	kubectl logs -f deployment/agentbridge

k8s-portforward: ## Port-forward to local access
	kubectl port-forward svc/agentbridge 8000:8000

docs: ## Remind user to open docs files
	@echo "Open docs/FAQ.md, docs/DEPLOYMENT.md, etc. in your browser or markdown viewer"
