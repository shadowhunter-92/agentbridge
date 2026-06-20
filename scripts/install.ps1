# AgentBridge One-Line Setup (PowerShell)
$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  AgentBridge One-Line Setup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Error "Error: Python is not installed. Please install Python 3.11 or higher."
    exit 1
}

$pyVersion = & $python.Source -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
Write-Host "Python version: $pyVersion"

# Create virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    & $python.Source -m venv .venv
}

# Activate
.venv\Scripts\Activate.ps1

# Upgrade pip
pip install --upgrade pip

# Install AgentBridge with dev dependencies
Write-Host "Installing AgentBridge..."
pip install -e ".[dev]"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Quick commands:"
Write-Host "  make test        # Run all tests"
Write-Host "  make serve       # Start the control plane"
Write-Host "  make demo        # Run the 60-second demo"
Write-Host "  make docker-up   # Deploy with Docker"
Write-Host ""
Write-Host "Open your browser to: http://localhost:8000/dashboard"
Write-Host ""
