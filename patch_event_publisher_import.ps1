# patch_event_publisher_import.ps1
# Jalankan dari root E:\full_erp_accounting_engine

$path = ".\bootstrap\dependency_container\service_registry.py"
$content = Get-Content -Path $path -Raw

$old = 'from infrastructure.event_publisher.event_publisher import EventPublisher'
$new = 'from adapters.secondary_impl.kafka_event_publisher_impl import KafkaEventPublisher as EventPublisher'

$occurrences = ([regex]::Matches($content, [regex]::Escape($old))).Count

if ($occurrences -eq 0) {
    Write-Host "SKIP (tidak ditemukan): $old" -ForegroundColor Yellow
} elseif ($occurrences -gt 1) {
    Write-Host "WARNING: baris ini muncul $occurrences kali - patch dibatalkan, cek manual" -ForegroundColor Red
} else {
    $content = $content.Replace($old, $new)
    Set-Content -Path $path -Value $content -Encoding utf8 -NoNewline
    Write-Host "OK: import EventPublisher dipatch ke KafkaEventPublisher" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Verifikasi ==="
Select-String -Path $path -Pattern "KafkaEventPublisher as EventPublisher"
