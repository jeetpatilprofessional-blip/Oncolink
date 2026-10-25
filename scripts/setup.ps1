# ==============================================================================
# ONCOLINK First-Time Setup Script (PowerShell)
# ==============================================================================
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  ONCOLINK: First-Time Environment Setup" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Verify Prerequisites
Write-Host "`n[1/5] Checking prerequisites..." -ForegroundColor Yellow

# Check Docker
try {
    $dockerVer = docker --version
    Write-Host "  [OK] Docker found: $dockerVer" -ForegroundColor Green
} catch {
    Write-Error "Docker is not installed or not in PATH."
}

# Check Docker Daemon
try {
    docker info 2>&1 | Out-Null
    Write-Host "  [OK] Docker daemon is running" -ForegroundColor Green
} catch {
    Write-Error "Docker Desktop is not running. Please launch Docker Desktop first."
}

# Check Node.js
try {
    $nodeVer = node -v
    Write-Host "  [OK] Node.js found: $nodeVer" -ForegroundColor Green
} catch {
    Write-Error "Node.js is not installed."
}

# Check Git
try {
    $gitVer = git --version
    Write-Host "  [OK] Git found: $gitVer" -ForegroundColor Green
} catch {
    Write-Error "Git is not installed."
}

# 2. Environment Configuration
Write-Host "`n[2/5] Checking environment configuration (.env)..." -ForegroundColor Yellow
$rootPath = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $rootPath ".env"
$envExamplePath = Join-Path $rootPath ".env.example"

if (-not (Test-Path $envPath)) {
    if (Test-Path $envExamplePath) {
        Copy-Item -Path $envExamplePath -Destination $envPath
        Write-Host "  [CREATED] .env created from .env.example with local development defaults." -ForegroundColor Green
    } else {
        Write-Error ".env.example was not found."
    }
} else {
    Write-Host "  [EXISTS] .env already present." -ForegroundColor Green
}

# 3. Frontend Dependencies
Write-Host "`n[3/5] Installing frontend local dependencies..." -ForegroundColor Yellow
$frontendPath = Join-Path $rootPath "frontend"
Push-Location $frontendPath
try {
    npm install
    Write-Host "  [OK] Frontend dependencies installed successfully." -ForegroundColor Green
} finally {
    Pop-Location
}

# 4. Build and Start Docker Stack
Write-Host "`n[4/5] Building and starting Docker services..." -ForegroundColor Yellow
Push-Location $rootPath
try {
    docker compose build
    docker compose up -d
    Write-Host "  [OK] Containers started in background." -ForegroundColor Green
} finally {
    Pop-Location
}

# 5. Wait for Health Checks
Write-Host "`n[5/5] Waiting for services to reach healthy status..." -ForegroundColor Yellow
$maxAttempts = 30
$attempt = 0
$healthy = $false

while ($attempt -lt $maxAttempts -and -not $healthy) {
    Start-Sleep -Seconds 3
    $attempt++
    try {
        $res = Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($res.status -eq "healthy") {
            $healthy = $true
            break
        }
    } catch {
        Write-Host "  Waiting for backend... (attempt $attempt/$maxAttempts)" -ForegroundColor Gray
    }
}

if ($healthy) {
    Write-Host "`n==========================================================" -ForegroundColor Green
    Write-Host "  ONCOLINK Foundation is LIVE and HEALTHY!" -ForegroundColor Green
    Write-Host "  - Frontend: http://localhost:5173" -ForegroundColor Cyan
    Write-Host "  - Backend Health: http://localhost:8000/health" -ForegroundColor Cyan
    Write-Host "  - MinIO Console: http://localhost:9001" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Green
} else {
    Write-Warning "Backend did not become healthy within the timeout window. Check 'docker compose logs'."
}
