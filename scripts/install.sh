#!/bin/bash
set -e

echo "=========================================="
echo "  AgentBridge One-Line Setup"
echo "=========================================="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed. Please install Python 3.11 or higher."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Python version: $PYTHON_VERSION"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install AgentBridge with dev dependencies
echo "Installing AgentBridge..."
pip install -e ".[dev]"

echo ""
echo "=========================================="
echo "  Setup complete!"
echo "=========================================="
echo ""
echo "Quick commands:"
echo "  make test        # Run all tests"
echo "  make serve       # Start the control plane"
echo "  make demo        # Run the 60-second demo"
echo "  make docker-up   # Deploy with Docker"
echo ""
echo "Open your browser to: http://localhost:8000/dashboard"
echo ""
