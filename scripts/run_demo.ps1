# Quick demo script for Windows
# Run: .\scripts\run_demo.ps1

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  AgentBridge Quick Demo" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

if (-not (Test-Path ".venv")) {
    Write-Host "Virtual environment not found. Running setup first..."
    .\scripts\install.ps1
} else {
    .venv\Scripts\Activate.ps1
}

Write-Host ""
Write-Host "Running demo story..."
python examples\demo_story.py

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Demo complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start the control plane: make serve"
Write-Host "Dashboard: http://localhost:8000/dashboard"
Write-Host "API Docs:  http://localhost:8000/docs"
Write-Host ""
