@echo off
REM build_exe.bat
REM ================
REM Build SovereignERP jadi .exe standalone (Windows).
REM Jalankan dari folder erp_frontend (venv harus sudah aktif).

echo [1/3] Install PyInstaller...
pip install pyinstaller --quiet

echo [2/3] Bersihkan build lama...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

echo [3/3] Build aplikasi...
pyinstaller SovereignERP.spec --noconfirm

echo.
echo ============================================================
echo Selesai. Hasil build ada di: dist\SovereignERP\SovereignERP.exe
echo Copy seluruh folder dist\SovereignERP untuk didistribusikan.
echo ============================================================
pause
