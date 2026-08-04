<#
.SYNOPSIS
    Analisis log full_erp_accounting_engine (uvicorn/fastapi) untuk menemukan
    pola error: status code, DependencyNotFoundError, 403 mass-fail, dan
    endpoint yang salah path.

.USAGE
    .\Analyze-ErpLog.ps1 -LogPath "C:\path\to\server.log"

    Kalau log-nya belum berupa file, redirect dulu:
    uvicorn app.main:app --factory ... > server.log 2>&1
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$LogPath
)

if (-not (Test-Path $LogPath)) {
    Write-Error "File log tidak ditemukan: $LogPath"
    return
}

$lines = Get-Content -Path $LogPath -Encoding UTF8

Write-Host "`n================ 1. RINGKASAN STATUS CODE ================" -ForegroundColor Cyan
$statusPattern = [regex]'"(GET|POST|PUT|PATCH|DELETE)\s(\S+)\sHTTP/\d\.\d"\s(\d{3})'
$requests = foreach ($line in $lines) {
    $m = $statusPattern.Match($line)
    if ($m.Success) {
        [PSCustomObject]@{
            Method = $m.Groups[1].Value
            Path   = $m.Groups[2].Value
            Status = [int]$m.Groups[3].Value
        }
    }
}

$total = $requests.Count
Write-Host "Total request terparsing: $total"
$requests | Group-Object Status | Sort-Object Count -Descending |
    ForEach-Object {
        $pct = [math]::Round(($_.Count / [math]::Max($total,1)) * 100, 1)
        [PSCustomObject]@{ StatusCode = $_.Name; Jumlah = $_.Count; Persen = "$pct%" }
    } | Format-Table -AutoSize

Write-Host "`n================ 2. TOP 25 (ENDPOINT + STATUS) BERMASALAH ================" -ForegroundColor Cyan
$requests | Where-Object { $_.Status -in 401,403,404,422,500,502,503 } |
    Group-Object Path, Status |
    Sort-Object Count -Descending |
    Select-Object -First 25 |
    ForEach-Object {
        [PSCustomObject]@{ EndpointStatus = $_.Name; Jumlah = $_.Count }
    } | Format-Table -AutoSize

Write-Host "`n================ 3. DEPENDENCY YANG GAGAL RESOLVE (IoC) ================" -ForegroundColor Cyan
$depFails = $lines | Select-String -Pattern 'Dependency tidak terdaftar:\s*(\w+)'
if ($depFails) {
    $depFails | ForEach-Object { $_.Matches[0].Groups[1].Value } |
        Group-Object | Sort-Object Count -Descending |
        ForEach-Object { [PSCustomObject]@{ DependencyPort = $_.Name; JumlahKemunculan = $_.Count } } |
        Format-Table -AutoSize
} else {
    Write-Host "Tidak ada DependencyNotFoundError ditemukan." -ForegroundColor Green
}

Write-Host "`n================ 4. TRACEBACK / EXCEPTION TYPE UNIK ================" -ForegroundColor Cyan
$excPattern = [regex]'([A-Za-z_][A-Za-z0-9_.]*Error(?:or|)):\s'
$excTypes = foreach ($line in $lines) {
    $m = $excPattern.Match($line)
    if ($m.Success -and $line -notmatch 'Validation error http') {
        $m.Groups[1].Value
    }
}
$excTypes | Group-Object | Sort-Object Count -Descending |
    ForEach-Object { [PSCustomObject]@{ ExceptionType = $_.Name; Jumlah = $_.Count } } |
    Format-Table -AutoSize

Write-Host "`n================ 4b. DIAGNOSA UnicodeEncodeError ================" -ForegroundColor Cyan
$unicodeErrIdx = @()
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'UnicodeEncodeError') { $unicodeErrIdx += $i }
}
if ($unicodeErrIdx.Count -gt 0) {
    Write-Host "Ditemukan $($unicodeErrIdx.Count) baris UnicodeEncodeError." -ForegroundColor Red
    Write-Host "Contoh baris pertama (dengan 3 baris konteks sebelumnya):"
    $start = [math]::Max(0, $unicodeErrIdx[0] - 3)
    $lines[$start..$unicodeErrIdx[0]] | ForEach-Object { Write-Host "  $_" }
    Write-Host "`n>> Kemungkinan besar: emoji (checkmark/rocket) di log message tidak bisa di-encode" -ForegroundColor Yellow
    Write-Host ">> ke codepage default Windows saat stdout di-redirect ke file (biasanya cp1252)." -ForegroundColor Yellow
    Write-Host ">> Fix: set `$env:PYTHONUTF8='1'; `$env:PYTHONIOENCODING='utf-8' sebelum start uvicorn." -ForegroundColor Yellow
} else {
    Write-Host "Tidak ada UnicodeEncodeError." -ForegroundColor Green
}

Write-Host "`n================ 5. WARNING FALLBACK / DEGRADED SERVICE ================" -ForegroundColor Cyan
$lines | Select-String -Pattern 'not available, using None|in-memory fallback|ephemeral key' |
    ForEach-Object { $_.Line.Trim() } | Select-Object -Unique

Write-Host "`n================ 6. RASIO 403 PER MODUL (indikasi masalah authorization) ================" -ForegroundColor Cyan
$requests | Where-Object { $_.Status -eq 403 } |
    ForEach-Object {
        if ($_.Path -match '/api/v1/([^/]+)/') { $Matches[1] } else { 'unknown' }
    } | Group-Object | Sort-Object Count -Descending |
    ForEach-Object { [PSCustomObject]@{ Modul = $_.Name; Jumlah403 = $_.Count } } |
    Format-Table -AutoSize

Write-Host "`n================ 7. UUID PATH PLACEHOLDER YANG TIDAK DISUBSTITUSI ================" -ForegroundColor Cyan
$placeholderHits = $lines | Select-String -Pattern "found `[a-z]` at \d+.*expected an optional prefix of ``urn:uuid:``"
Write-Host "Jumlah request dengan path param literal '{xxx_id}' (bukan UUID asli): $($placeholderHits.Count)"

Write-Host "`nSelesai. Gunakan output di atas untuk memprioritaskan perbaikan:" -ForegroundColor Yellow
Write-Host " - Prioritas 1: DependencyNotFoundError (section 3)"
Write-Host " - Prioritas 2: 403 mendominasi di semua modul (section 6) -> cek authority_matrix"
Write-Host " - Prioritas 3: exception type di section 4 yang bukan 'Validation error'"
