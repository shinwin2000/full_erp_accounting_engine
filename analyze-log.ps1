<#
.SYNOPSIS
    Analisa log server ERP (uvicorn/fastapi) dari file log.

.USAGE
    .\analyze-log.ps1 -Path "server.log"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

if (-not (Test-Path $Path)) {
    Write-Host "File tidak ditemukan: $Path" -ForegroundColor Red
    exit 1
}

$lines = Get-Content $Path

Write-Host "`n================ RINGKASAN LOG ================" -ForegroundColor Cyan
Write-Host "Total baris log : $($lines.Count)"

# --- 1. ERRORS ---
Write-Host "`n---- ERROR ----" -ForegroundColor Red
$errors = $lines | Select-String -Pattern "ERROR"
if ($errors) {
    $errors | ForEach-Object { Write-Host $_.Line -ForegroundColor Red }
} else {
    Write-Host "Tidak ada ERROR ditemukan." -ForegroundColor Green
}

# --- 2. WARNINGS ---
Write-Host "`n---- WARNING ----" -ForegroundColor Yellow
$warnings = $lines | Select-String -Pattern "WARNING"
if ($warnings) {
    $warnings | ForEach-Object { Write-Host $_.Line -ForegroundColor Yellow }
} else {
    Write-Host "Tidak ada WARNING ditemukan." -ForegroundColor Green
}

# --- 3. HTTP STATUS CODE SUMMARY ---
Write-Host "`n---- RINGKASAN HTTP STATUS ----" -ForegroundColor Cyan
$httpLines = $lines | Select-String -Pattern '"\w+ .*? HTTP/1\.1"\s+(\d{3})'
$statusCounts = @{}
foreach ($m in $httpLines) {
    if ($m.Line -match '"\w+ .*? HTTP/1\.1"\s+(\d{3})') {
        $code = $matches[1]
        if ($statusCounts.ContainsKey($code)) {
            $statusCounts[$code]++
        } else {
            $statusCounts[$code] = 1
        }
    }
}
$statusCounts.GetEnumerator() | Sort-Object Name | ForEach-Object {
    $color = if ($_.Name -ge 500) { "Red" } elseif ($_.Name -ge 400) { "Yellow" } else { "Green" }
    Write-Host ("Status {0}: {1} request" -f $_.Name, $_.Value) -ForegroundColor $color
}

# --- 4. FAILED REQUESTS DETAIL (4xx / 5xx) ---
Write-Host "`n---- REQUEST GAGAL (4xx/5xx) ----" -ForegroundColor Red
$failed = $lines | Select-String -Pattern 'HTTP/1\.1"\s+(4\d{2}|5\d{2})'
if ($failed) {
    $failed | ForEach-Object { Write-Host $_.Line -ForegroundColor Red }
} else {
    Write-Host "Tidak ada request gagal." -ForegroundColor Green
}

# --- 5. TRACEBACK BLOCKS ---
Write-Host "`n---- TRACEBACK PYTHON ----" -ForegroundColor Magenta
$inTraceback = $false
foreach ($line in $lines) {
    if ($line -match "Traceback \(most recent call last\):") {
        $inTraceback = $true
        Write-Host $line -ForegroundColor Magenta
        continue
    }
    if ($inTraceback) {
        Write-Host $line -ForegroundColor DarkMagenta
        if ($line -match "^\S") { $inTraceback = $false }  # baris tanpa indent = akhir traceback
    }
}

Write-Host "`n================ SELESAI ================`n" -ForegroundColor Cyan
