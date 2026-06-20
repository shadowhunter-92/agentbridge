#!/bin/bash
# Quick demo script for Linux/macOS
# Run: ./scripts/run_demo.sh

set -e

echo "=========================================="
echo "  AgentBridge Quick Demo"
echo "=========================================="

if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Running setup first..."
    ./scripts/install.sh
    source .venv/bin/activate
else
    source .venv/bin/activate
fi

echo ""
echo "Running demo story..."
python examples/demo_story.py

echo ""
echo "=========================================="
echo "  Demo complete!"
echo "=========================================="
echo ""
echo "To start the control plane: make serve"
echo "Dashboard: http://localhost:8000/dashboard"
echo "API Docs:  http://localhost:8000/docs"
echo ""
