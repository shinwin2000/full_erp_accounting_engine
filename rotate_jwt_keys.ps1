# rotate_jwt_keys.ps1
# Jalankan dari root E:\full_erp_accounting_engine
# PENTING: baca dulu isinya sebelum run. Script ini akan mengganti key JWT
# aktif - semua token yang sudah diterbitkan sebelumnya jadi invalid
# (semua user perlu login ulang setelah ini).

Write-Host "=== Rotasi JWT Key ===" -ForegroundColor Cyan
Write-Host "Semua token JWT yang sudah diterbitkan sebelumnya akan invalid setelah ini." -ForegroundColor Yellow
$confirm = Read-Host "Ketik 'YA' untuk lanjut"
if ($confirm -ne "YA") {
    Write-Host "Dibatalkan." -ForegroundColor Red
    exit 0
}

# 1. Backup key lama (buat referensi, jangan disimpan permanen di lokasi ini)
$backupDir = ".\secrets\_compromised_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Copy-Item .\secrets\jwt_private.pem "$backupDir\jwt_private.pem.compromised"
Copy-Item .\secrets\jwt_public.pem "$backupDir\jwt_public.pem.compromised"
Write-Host "Key lama di-backup ke $backupDir (untuk referensi forensik, JANGAN dipakai lagi)" -ForegroundColor Yellow

# 2. Generate key pair baru (2048-bit RSA, sesuai algorithm RS256 yang dipakai)
openssl genrsa -out .\secrets\jwt_private.pem 2048
openssl rsa -in .\secrets\jwt_private.pem -pubout -out .\secrets\jwt_public.pem
Write-Host "Key pair baru berhasil digenerate: secrets/jwt_private.pem, secrets/jwt_public.pem" -ForegroundColor Green

# 3. Hapus dari git tracking (untuk commit berikutnya)
git rm --cached secrets/jwt_private.pem secrets/jwt_public.pem 2>$null
Write-Host "File key dihapus dari git tracking (working directory tetap ada)" -ForegroundColor Green

# 4. Cek status
Write-Host ""
Write-Host "=== git status setelah rotasi ==="
git status

Write-Host ""
Write-Host "=== LANGKAH SELANJUTNYA (manual) ===" -ForegroundColor Cyan
Write-Host "1. Review 'git status' di atas - pastikan hanya perubahan yang diharapkan"
Write-Host "2. Commit perubahan ini:"
Write-Host "   git add .gitignore"
Write-Host "   git commit -m 'Remove secrets from git tracking, rotate JWT keys'"
Write-Host "   git push"
Write-Host ""
Write-Host "3. PENTING - riwayat commit LAMA (c6f1b8f dkk) masih menyimpan key yang bocor"
Write-Host "   meski file sudah dihapus dari tracking. Untuk membersihkan riwayat git"
Write-Host "   sepenuhnya, perlu 'git filter-repo' atau BFG Repo-Cleaner - ini MENULIS ULANG"
Write-Host "   history dan perlu force-push + koordinasi kalau ada kolaborator lain."
Write-Host "   Beri tahu saya kalau mau lanjut ke langkah ini."
Write-Host ""
Write-Host "4. Restart server ERP untuk memakai key baru:"
Write-Host "   uvicorn app.main:app --factory --host 0.0.0.0 --port 8000 --workers 1"
Write-Host ""
Write-Host "5. Hapus folder backup '_compromised_backup_*' setelah kamu yakin migrasi aman"
Write-Host "   (jangan biarkan key lama nongkrong di disk lebih lama dari perlu)."
