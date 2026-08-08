# patch_resolve_async.ps1
# Jalankan dari root E:\full_erp_accounting_engine

$path = ".\bootstrap\dependency_container\service_registry.py"
$content = Get-Content -Path $path -Raw

$replacements = @(
    @{
        Old = 'event_publisher = container.resolve(EventPublisherPort)'
        New = 'event_publisher = await container.resolve_async(EventPublisherPort)'
    },
    @{
        Old = 'token_issuer = container.resolve(TokenIssuerPort)'
        New = 'token_issuer = await container.resolve_async(TokenIssuerPort)'
    },
    @{
        Old = 'cache = container.resolve(CachePort)'
        New = 'cache = await container.resolve_async(CachePort)'
    }
)

$changedCount = 0
foreach ($r in $replacements) {
    $occurrences = ([regex]::Matches($content, [regex]::Escape($r.Old))).Count
    if ($occurrences -eq 0) {
        Write-Host "SKIP (tidak ditemukan): $($r.Old)" -ForegroundColor Yellow
        continue
    }
    if ($occurrences -gt 1) {
        Write-Host "WARNING: '$($r.Old)' muncul $occurrences kali - patch dibatalkan untuk baris ini, cek manual" -ForegroundColor Red
        continue
    }
    $content = $content.Replace($r.Old, $r.New)
    $changedCount++
    Write-Host "OK: $($r.Old)" -ForegroundColor Green
    Write-Host "  -> $($r.New)" -ForegroundColor Green
}

if ($changedCount -gt 0) {
    Set-Content -Path $path -Value $content -Encoding utf8 -NoNewline
    Write-Host ""
    Write-Host "$changedCount baris berhasil dipatch di $path" -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "Tidak ada perubahan yang diterapkan." -ForegroundColor Red
}

# Verifikasi hasil patch
Write-Host ""
Write-Host "=== Verifikasi ==="
Select-String -Path $path -Pattern "resolve_async\(EventPublisherPort\)|resolve_async\(TokenIssuerPort\)|resolve_async\(CachePort\)"
