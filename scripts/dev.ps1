# One-click start for InspectAgent Cloud (Windows PowerShell)
#   .\scripts\dev.ps1        (or double-click 启动.bat in project root)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host ""
Write-Host "  InspectAgent Cloud - one-click start" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path ".env")) {
    Write-Host "  ERROR: .env not found. Copy .env.example to .env and fill the keys." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

$py = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "  [1/3] creating virtualenv (python 3.11) ..."
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv venv --python 3.11
    } else {
        python -m venv .venv
    }
    Write-Host "  [2/3] installing dependencies (first run may take a few minutes) ..."
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv pip install -r requirements.txt --python .\.venv\Scripts\python.exe
    } else {
        & $py -m pip install --upgrade pip -q
        & $py -m pip install -r requirements.txt -q
    }
} else {
    Write-Host "  [1/3] virtualenv found, skip install"
    Write-Host "  [2/3] dependencies assumed ready"
}

$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1).IPAddress
if (-not $ip) { $ip = "127.0.0.1" }

Write-Host ""
Write-Host "  [3/3] starting server ..." -ForegroundColor Yellow
Write-Host ""
Write-Host ("  Web console : http://" + $ip + ":8000/") -ForegroundColor Green
Write-Host ("  API docs    : http://" + $ip + ":8000/docs") -ForegroundColor Green
Write-Host ("  Health      : http://" + $ip + ":8000/health   (mock MUST be false)") -ForegroundColor Green
Write-Host ""
Write-Host "  Keep this window open. Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

& $py -m uvicorn app.main:app --host 0.0.0.0 --port 8000
