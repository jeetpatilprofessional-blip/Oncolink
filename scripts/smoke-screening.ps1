# ONCOLINK Screener End-to-End Intake & Screening Smoke Test Script
# Runs against the real running backend at http://127.0.0.1:8000
# 1. Logs in as the demo screener (credentials from .env)
# 2. Creates a new adult patient profile via POST /patients
# 3. Records in-person informed consent via POST /consent
# 4. Creates a case draft via POST /cases
# 5. Saves structured health history via POST /cases/{id}/history
# 6. Generates synthetic test images (never real photos) and uploads via POST /cases/{id}/images
#    (Requires: 1 lesion_closeup, 2 context views)
# 7. Submits the screening case via POST /cases/{id}/submit
# 8. Prints each response and cleans up all created records at the end

$ErrorActionPreference = "Stop"
$baseUrl = "http://127.0.0.1:8000"

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "ONCOLINK SMOKE TEST: SCREENER INTAKE & SUBMISSION" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 0. Load credentials from environment or .env
$envFile = Join-Path $PSScriptRoot "..\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $idx = $line.IndexOf("=")
            if ($idx -gt 0) {
                $k = $line.Substring(0, $idx).Trim()
                $v = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
                if (-not [System.Environment]::GetEnvironmentVariable($k)) {
                    [System.Environment]::SetEnvironmentVariable($k, $v)
                }
            }
        }
    }
}

$screenerEmail = [System.Environment]::GetEnvironmentVariable("DEMO_SCREENER_EMAIL")
$screenerPassword = [System.Environment]::GetEnvironmentVariable("DEMO_SCREENER_PASSWORD")

if (-not $screenerEmail -or -not $screenerPassword) {
    Write-Error "Missing DEMO_SCREENER_EMAIL or DEMO_SCREENER_PASSWORD in environment."
}

Write-Host "Target URL:     $baseUrl"
Write-Host "Screener Email: $screenerEmail"
Write-Host "--------------------------------------------------------"

# 1. Log in as demo screener
Write-Host "`n[Step 1] Logging in as demo screener (POST /auth/login)..." -ForegroundColor Yellow
$loginPayload = @{
    email    = $screenerEmail
    password = $screenerPassword
} | ConvertTo-Json

$loginRes = Invoke-RestMethod -Uri "$baseUrl/auth/login" -Method Post -Body $loginPayload -ContentType "application/json"
$token = $loginRes.access_token
Write-Host "  [OK] Screener logged in successfully!" -ForegroundColor Green
Write-Host "  Token: $($token.Substring(0, 24))..."

$headers = @{
    Authorization = "Bearer $token"
}

# 2. Create person profile (POST /patients)
$rand = Get-Random -Minimum 1000 -Maximum 9999
Write-Host "`n[Step 2] Creating participant profile (POST /patients)..." -ForegroundColor Yellow
$patientPayload = @{
    date_of_birth = "1988-05-12"
    language      = "en"
    contact       = "Smoke-Camp-$rand"
} | ConvertTo-Json

$patientRes = Invoke-RestMethod -Uri "$baseUrl/patients" -Method Post -Headers $headers -Body $patientPayload -ContentType "application/json"
$patientId = $patientRes.id
Write-Host "  [OK] Participant created! ID: $patientId" -ForegroundColor Green
Write-Host ($patientRes | ConvertTo-Json -Depth 3)

# 3. Record in-person consent (POST /consent)
Write-Host "`n[Step 3] Fetching active consent and recording in-person consent (POST /consent)..." -ForegroundColor Yellow
$consentCurrent = Invoke-RestMethod -Uri "$baseUrl/consent/current" -Method Get
$consentPayload = @{
    patient_id       = $patientId
    consent_version  = $consentCurrent.version
    language         = "en"
    consent_accepted = $true
} | ConvertTo-Json

$consentRes = Invoke-RestMethod -Uri "$baseUrl/consent" -Method Post -Headers $headers -Body $consentPayload -ContentType "application/json"
Write-Host "  [OK] Informed consent recorded!" -ForegroundColor Green
Write-Host ($consentRes | ConvertTo-Json -Depth 3)

# 4. Create case draft (POST /cases)
Write-Host "`n[Step 4] Creating case draft (POST /cases)..." -ForegroundColor Yellow
$casePayload = @{
    patient_id = $patientId
} | ConvertTo-Json

$caseRes = Invoke-RestMethod -Uri "$baseUrl/cases" -Method Post -Headers $headers -Body $casePayload -ContentType "application/json"
$caseId = $caseRes.id
Write-Host "  [OK] Case draft created! Case ID: $caseId, Ref: $($caseRes.reference)" -ForegroundColor Green
Write-Host ($caseRes | ConvertTo-Json -Depth 3)

# 5. Save questionnaire history (POST /cases/{id}/history)
Write-Host "`n[Step 5] Saving structured questionnaire history (POST /cases/$caseId/history)..." -ForegroundColor Yellow
$historyPayload = @{
    heavy_bleeding               = $false
    difficulty_breathing          = $false
    rapid_swelling               = $false
    lesion_duration_weeks        = 3
    lesion_pain                  = $true
    lesion_non_healing_two_weeks = $true
    lesion_bleeding              = $false
    lesion_white_or_red_patch    = $true
    lesion_lump                  = $false
    difficulty_swallowing        = $false
    difficulty_opening_mouth     = $false
    difficulty_speaking          = $false
    unexplained_weight_loss      = $false
    family_history_cancer        = $false
    tobacco_smoked_frequency     = "never"
    tobacco_smoked_years         = 0
    tobacco_smokeless_frequency  = "never"
    tobacco_smokeless_years      = 0
    areca_nut_frequency          = "never"
    areca_nut_years              = 0
    betel_quid_frequency         = "never"
    betel_quid_years             = 0
    alcohol_frequency            = "never"
} | ConvertTo-Json

$historyRes = Invoke-RestMethod -Uri "$baseUrl/cases/$caseId/history" -Method Post -Headers $headers -Body $historyPayload -ContentType "application/json"
Write-Host "  [OK] History saved successfully!" -ForegroundColor Green
Write-Host ($historyRes | ConvertTo-Json -Depth 3)

# 6. Generate synthetic test image (never real photos) and upload
Write-Host "`n[Step 6] Generating synthetic checkered test images and uploading..." -ForegroundColor Yellow
Add-Type -AssemblyName System.Drawing
$tempDir = [System.IO.Path]::GetTempPath()
$imgFile = Join-Path $tempDir "smoke_test_image.jpg"

$bmp = New-Object System.Drawing.Bitmap 640, 640
$g = [System.Drawing.Graphics]::FromImage($bmp)
$brushDark = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(60, 60, 60))
$brushLight = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(190, 190, 190))

for ($y = 0; $y -lt 640; $y += 16) {
    for ($x = 0; $x -lt 640; $x += 16) {
        $brush = if ((($x / 16) + ($y / 16)) % 2 -eq 0) { $brushLight } else { $brushDark }
        $g.FillRectangle($brush, $x, $y, 16, 16)
    }
}
$g.Dispose()
$bmp.Save($imgFile, [System.Drawing.Imaging.ImageFormat]::Jpeg)
$bmp.Dispose()
Write-Host "  [OK] Generated 640x640 synthetic test JPEG: $imgFile" -ForegroundColor Green

# Upload 1: lesion_closeup on tongue_top
Write-Host "  Uploading Image 1: lesion_closeup on tongue_top..."
$upload1Raw = & curl.exe -s -X POST "$baseUrl/cases/$caseId/images" `
    -H "Authorization: Bearer $token" `
    -F "site=tongue_top" `
    -F "view_type=lesion_closeup" `
    -F "file=@$imgFile;type=image/jpeg"
Write-Host "  Response 1: $upload1Raw"

# Upload 2: context on left_cheek
Write-Host "  Uploading Image 2: context on left_cheek..."
$upload2Raw = & curl.exe -s -X POST "$baseUrl/cases/$caseId/images" `
    -H "Authorization: Bearer $token" `
    -F "site=left_cheek" `
    -F "view_type=context" `
    -F "file=@$imgFile;type=image/jpeg"
Write-Host "  Response 2: $upload2Raw"

# Upload 3: context on right_cheek
Write-Host "  Uploading Image 3: context on right_cheek..."
$upload3Raw = & curl.exe -s -X POST "$baseUrl/cases/$caseId/images" `
    -H "Authorization: Bearer $token" `
    -F "site=right_cheek" `
    -F "view_type=context" `
    -F "file=@$imgFile;type=image/jpeg"
Write-Host "  Response 3: $upload3Raw"

# Clean up local temp image
if (Test-Path $imgFile) {
    Remove-Item $imgFile -Force
}

# 7. Submit screening case (POST /cases/{id}/submit)
Write-Host "`n[Step 7] Submitting case for quality gate and triage (POST /cases/$caseId/submit)..." -ForegroundColor Yellow
$submitRes = Invoke-RestMethod -Uri "$baseUrl/cases/$caseId/submit" -Method Post -Headers $headers -ContentType "application/json"
Write-Host "  [OK] Case submitted successfully!" -ForegroundColor Green
Write-Host ($submitRes | ConvertTo-Json -Depth 3)

# 8. Clean up all created test records
Write-Host "`n[Step 8] Cleaning up created smoke test records via backend CLI..." -ForegroundColor Yellow
docker compose -f (Join-Path $PSScriptRoot "..\docker-compose.yml") exec -T backend python -m app.cli clean-smoke-case $caseId
Write-Host "  [OK] Smoke test records purged." -ForegroundColor Green

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "SMOKE SCREENING TEST COMPLETED SUCCESSFULLY (100% PASSED)" -ForegroundColor Green
Write-Host "========================================================`n"
