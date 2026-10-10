# ============================================================================
# Script tes otomatis modul IAM - Sovereign ERP
# Cara pakai: pastikan backend sudah jalan (uvicorn app.main:app ...),
# lalu jalankan: .\test_iam_module.ps1
# ============================================================================

$ErrorActionPreference = "Stop"
$BaseUrl = "http://localhost:8000/api/v1"
$results = @()

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Method,
        [string]$Url,
        [hashtable]$Headers = @{},
        [string]$Body = $null,
        [int[]]$ExpectedStatus = @(200, 201, 204)
    )
    try {
        $params = @{
            Uri             = $Url
            Method          = $Method
            Headers         = $Headers
            ContentType     = "application/json"
            ErrorAction     = "Stop"
            UseBasicParsing = $true
        }
        if ($Body) { $params["Body"] = $Body }

        $resp = Invoke-WebRequest @params
        $status = [int]$resp.StatusCode
        if ($ExpectedStatus -contains $status) {
            Write-Host "[PASS] $Name -> $status" -ForegroundColor Green
            $script:results += [pscustomobject]@{ Test = $Name; Status = "PASS"; Code = $status }
            return $resp.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
        } else {
            Write-Host "[FAIL] $Name -> $status (expected $($ExpectedStatus -join ','))" -ForegroundColor Red
            $script:results += [pscustomobject]@{ Test = $Name; Status = "FAIL"; Code = $status }
            return $null
        }
    } catch {
        $code = $null
        if ($_.Exception.Response) {
            $code = [int]$_.Exception.Response.StatusCode
        }
        Write-Host "[FAIL] $Name -> ERROR $code : $($_.Exception.Message)" -ForegroundColor Red
        $script:results += [pscustomobject]@{ Test = $Name; Status = "FAIL"; Code = $code }
        return $null
    }
}

Write-Host "`n=== 1. LOGIN FLOW ===" -ForegroundColor Cyan

$legalEntity = Test-Endpoint -Name "GET /legal-entities/login-options" -Method Get `
    -Url "$BaseUrl/legal-entities/login-options"

if (-not $legalEntity) {
    Write-Host "Tidak bisa dapat legal_entity_id, stop testing." -ForegroundColor Red
    exit 1
}
$legalEntityId = $legalEntity.id

$loginBody = @{ username = "admin"; password = "Admin123!"; legal_entity_id = $legalEntityId } | ConvertTo-Json
$loginResp = Test-Endpoint -Name "POST /iam/login" -Method Post -Url "$BaseUrl/iam/login" -Body $loginBody

if (-not $loginResp) {
    Write-Host "Login gagal, stop testing." -ForegroundColor Red
    exit 1
}

$accessToken = $loginResp.access_token
$refreshToken = $loginResp.refresh_token
$headers = @{ Authorization = "Bearer $accessToken" }

Write-Host "`n=== 2. REFRESH TOKEN ===" -ForegroundColor Cyan
$refreshBody = @{ refresh_token = $refreshToken } | ConvertTo-Json
$refreshResp = Test-Endpoint -Name "POST /iam/refresh" -Method Post -Url "$BaseUrl/iam/refresh" -Body $refreshBody
if ($refreshResp) {
    $accessToken = $refreshResp.access_token
    $headers = @{ Authorization = "Bearer $accessToken" }
}

Write-Host "`n=== 3. USERS ===" -ForegroundColor Cyan
$users = Test-Endpoint -Name "GET /iam/users" -Method Get -Url "$BaseUrl/iam/iam/users?page=1&page_size=50" -Headers $headers
if ($users -and $users.Count -gt 0) {
    $sampleUserId = $users[0].id
} elseif ($users.items -and $users.items.Count -gt 0) {
    $sampleUserId = $users.items[0].id
} else {
    $sampleUserId = $loginResp.user.id
}
Test-Endpoint -Name "GET /iam/users/{id}" -Method Get -Url "$BaseUrl/iam/iam/users/$sampleUserId" -Headers $headers | Out-Null
Test-Endpoint -Name "GET /iam/users/{id}/status" -Method Get -Url "$BaseUrl/iam/iam/users/$sampleUserId/status" -Headers $headers | Out-Null
Test-Endpoint -Name "GET /iam/users/{id}/history" -Method Get -Url "$BaseUrl/iam/iam/users/$sampleUserId/history" -Headers $headers | Out-Null
Test-Endpoint -Name "GET /iam/users/{id}/audit-log" -Method Get -Url "$BaseUrl/iam/iam/users/$sampleUserId/audit-log" -Headers $headers | Out-Null

Write-Host "`n=== 4. ROLES & PERMISSIONS ===" -ForegroundColor Cyan
$roles = Test-Endpoint -Name "GET /iam/roles" -Method Get -Url "$BaseUrl/iam/iam/roles" -Headers $headers
Test-Endpoint -Name "GET /iam/permissions" -Method Get -Url "$BaseUrl/iam/iam/permissions" -Headers $headers | Out-Null
if ($roles -and $roles.Count -gt 0) {
    $sampleRoleId = $roles[0].id
    Test-Endpoint -Name "GET /iam/roles/{id}" -Method Get -Url "$BaseUrl/iam/iam/roles/$sampleRoleId" -Headers $headers | Out-Null
    Test-Endpoint -Name "GET /iam/roles/{id}/permissions" -Method Get -Url "$BaseUrl/iam/iam/roles/$sampleRoleId/permissions" -Headers $headers | Out-Null
}
Test-Endpoint -Name "GET /iam/users/{id}/roles" -Method Get -Url "$BaseUrl/iam/iam/users/$sampleUserId/roles" -Headers $headers | Out-Null

Write-Host "`n=== 5. SESSIONS ===" -ForegroundColor Cyan
Test-Endpoint -Name "GET /iam/sessions" -Method Get -Url "$BaseUrl/iam/iam/sessions" -Headers $headers | Out-Null

Write-Host "`n=== 6. AUDIT / LOGIN ATTEMPTS ===" -ForegroundColor Cyan
Test-Endpoint -Name "GET /iam/login-attempts" -Method Get -Url "$BaseUrl/iam/iam/login-attempts" -Headers $headers | Out-Null

Write-Host "`n=== 7. LOGOUT ===" -ForegroundColor Cyan
Test-Endpoint -Name "POST /iam/logout" -Method Post -Url "$BaseUrl/iam/logout" -Headers $headers -ExpectedStatus @(200, 204) | Out-Null

Write-Host "`n`n============================================================" -ForegroundColor Yellow
Write-Host "RINGKASAN HASIL TES" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow
$results | Format-Table -AutoSize

$passCount = ($results | Where-Object { $_.Status -eq "PASS" }).Count
$failCount = ($results | Where-Object { $_.Status -eq "FAIL" }).Count
Write-Host "`nTotal: $($results.Count) | PASS: $passCount | FAIL: $failCount" -ForegroundColor $(if ($failCount -eq 0) { "Green" } else { "Red" })

if ($failCount -eq 0) {
    Write-Host "`nSEMUA TES LULUS. Modul IAM aman 100%." -ForegroundColor Green
} else {
    Write-Host "`nMASIH ADA YANG GAGAL. Lihat detail [FAIL] di atas." -ForegroundColor Red
}
