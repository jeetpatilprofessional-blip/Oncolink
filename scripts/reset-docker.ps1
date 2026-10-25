# ==============================================================================
# ONCOLINK Docker Volume Reset Script (PowerShell)
# ==============================================================================
[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Red
Write-Host "  ONCOLINK: Reset Local Docker Volumes" -ForegroundColor Red
Write-Host "==========================================================" -ForegroundColor Red
Write-Host "WARNING: This will destroy all local MongoDB replica set data, GridFS images, and keyfiles." -ForegroundColor Yellow

if (-not $Force) {
    $confirm = Read-Host "Are you sure you want to proceed? (y/N)"
    if ($confirm -ne 'y' -and $confirm -ne 'Y') {
        Write-Host "Reset aborted." -ForegroundColor Gray
        exit 0
    }
}

$rootPath = Split-Path -Parent $PSScriptRoot
Push-Location $rootPath

try {
    Write-Host "`nStopping containers and removing volumes..." -ForegroundColor Yellow
    docker compose down -v --remove-orphans

    # Force remove named volumes if still present
    $volumes = @("oncolink_mongo_data", "oncolink_mongo_keyfile")
    foreach ($vol in $volumes) {
        try {
            docker volume rm $vol 2>$null
        } catch {
            # Ignore if already removed
        }
    }

    Write-Host "`n[OK] Local Docker volumes have been reset to a clean slate." -ForegroundColor Green
    Write-Host "Run .\scripts\setup.ps1 or 'docker compose up -d' to restart with fresh storage." -ForegroundColor Cyan
} finally {
    Pop-Location
}
