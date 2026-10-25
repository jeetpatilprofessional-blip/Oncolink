# ONCOLINK Patient Registration Smoke Test Script
# Tests real running backend API at http://127.0.0.1:8000
# 1. Registers a new patient with date_of_birth and informed consent
# 2. Logs in with the new credentials
# 3. Fetches GET /auth/me and prints the resulting identity and patient profile link

$ErrorActionPreference = "Stop"

$baseUrl = "http://127.0.0.1:8000"
$randomId = Get-Random -Minimum 10000 -Maximum 99999
$email = "smoke.patient.$randomId@oncolink.local"
$password = "SmokePatient#2026!"
$dob = "1992-06-20"

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "ONCOLINK SMOKE TEST: PATIENT REGISTRATION & AUTH" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "Target Backend URL: $baseUrl"
Write-Host "Generated Email:    $email"
Write-Host "Date of Birth:      $dob (Adult: Age 34)"
Write-Host "--------------------------------------------------------"

# 1. Fetch current active consent version
Write-Host "`n[Step 1] Fetching active consent version from /consent/current..." -ForegroundColor Yellow
$consentResponse = Invoke-RestMethod -Uri "$baseUrl/consent/current" -Method Get
$consentVersion = $consentResponse.version
Write-Host "  [OK] Current active consent version: $consentVersion" -ForegroundColor Green

# 2. Register new patient with date_of_birth
Write-Host "`n[Step 2] Calling POST /auth/register..." -ForegroundColor Yellow
$registerPayload = @{
    email            = $email
    password         = $password
    date_of_birth    = $dob
    consent_version  = $consentVersion
    consent_accepted = $true
} | ConvertTo-Json

$registerResult = Invoke-RestMethod -Uri "$baseUrl/auth/register" -Method Post -Body $registerPayload -ContentType "application/json"
Write-Host "  [OK] Registration successful!" -ForegroundColor Green
Write-Host "  User ID:      $($registerResult.user_id)"
Write-Host "  Token Type:   $($registerResult.token_type)"
Write-Host "  Access Token: $($registerResult.access_token.Substring(0, 24))..."

# 3. Log in with newly registered credentials
Write-Host "`n[Step 3] Calling POST /auth/login..." -ForegroundColor Yellow
$loginPayload = @{
    email    = $email
    password = $password
} | ConvertTo-Json

$loginResult = Invoke-RestMethod -Uri "$baseUrl/auth/login" -Method Post -Body $loginPayload -ContentType "application/json"
$accessToken = $loginResult.access_token
Write-Host "  [OK] Login successful! Access token obtained." -ForegroundColor Green

# 4. Call GET /auth/me to verify user identity & patient profile link
Write-Host "`n[Step 4] Calling GET /auth/me with Bearer token..." -ForegroundColor Yellow
$headers = @{
    Authorization = "Bearer $accessToken"
}

$meResult = Invoke-RestMethod -Uri "$baseUrl/auth/me" -Method Get -Headers $headers
Write-Host "  [OK] Current user profile retrieved successfully!" -ForegroundColor Green

Write-Host "`n--------------------------------------------------------" -ForegroundColor Cyan
Write-Host "VERIFIED PATIENT PROFILE (GET /auth/me):" -ForegroundColor Cyan
Write-Host "--------------------------------------------------------"
$meResult | Format-List | Out-String | Write-Host
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "SMOKE TEST COMPLETED SUCCESSFULLY (100% PASSED)" -ForegroundColor Green
Write-Host "========================================================`n"
