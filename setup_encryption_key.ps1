# setup_encryption_key.ps1
# Jalankan dari root E:\full_erp_accounting_engine

# ============================================================
# 1. Generate AES-256 key (32 bytes) secara kriptografis aman, base64-encode
# ============================================================
$key = python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

if (-not $key) {
    Write-Host "GAGAL generate key - pastikan python bisa dipanggil" -ForegroundColor Red
    exit 1
}

Write-Host "Key baru berhasil digenerate (32 bytes, base64)." -ForegroundColor Green

# ============================================================
# 2. Cek apakah ENCRYPTION_KEY sudah ada di .env - jangan overwrite kalau sudah ada
# ============================================================
$envPath = ".\.env"
$envContent = Get-Content -Path $envPath -Raw

if ($envContent -match "(?m)^ENCRYPTION_KEY=") {
    Write-Host "SKIP: ENCRYPTION_KEY sudah ada di .env - tidak ditimpa." -ForegroundColor Yellow
    Write-Host "Kalau memang mau rotate key, hapus dulu baris ENCRYPTION_KEY lama secara manual" -ForegroundColor Yellow
    Write-Host "(ganti key berarti data lama yang sudah terenkripsi dengan key lama TIDAK BISA didekripsi lagi)." -ForegroundColor Yellow
} else {
    Add-Content -Path $envPath -Value "`nENCRYPTION_KEY=$key"
    Write-Host "OK: ENCRYPTION_KEY ditambahkan ke .env" -ForegroundColor Green
}

# ============================================================
# 3. Cek apakah folder secrets/ ke-track git (private key JWT berisiko ke-commit)
# ============================================================
Write-Host ""
Write-Host "=== Cek status git untuk folder secrets/ ==="
$isGitRepo = Test-Path ".\.git"
if ($isGitRepo) {
    $tracked = git ls-files secrets/ 2>$null
    if ($tracked) {
        Write-Host "PERINGATAN: file-file berikut di folder secrets/ SUDAH ke-track git:" -ForegroundColor Red
        $tracked | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        Write-Host "Ini butuh dibersihkan manual (git rm --cached, lalu rotate semua key/cert di dalamnya)." -ForegroundColor Red
    } else {
        Write-Host "OK: tidak ada file di secrets/ yang ke-track git saat ini." -ForegroundColor Green
    }
} else {
    Write-Host "Bukan git repo (tidak ada folder .git) - lewati cek ini." -ForegroundColor Yellow
}

# ============================================================
# 4. Tambahkan secrets/ ke .gitignore kalau belum ada
# ============================================================
$gitignorePath = ".\.gitignore"
$gitignoreContent = if (Test-Path $gitignorePath) { Get-Content -Path $gitignorePath -Raw } else { "" }

if ($gitignoreContent -notmatch "(?m)^secrets/?\s*$") {
    Add-Content -Path $gitignorePath -Value "`nsecrets/"
    Write-Host ""
    Write-Host "OK: 'secrets/' ditambahkan ke .gitignore" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "SKIP: 'secrets/' sudah ada di .gitignore" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Verifikasi akhir ==="
Select-String -Path $envPath -Pattern "^ENCRYPTION_KEY="
Select-String -Path $gitignorePath -Pattern "secrets"
