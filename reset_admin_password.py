#!/usr/bin/env python3
"""
reset_admin_password.py
========================
Skrip utilitas untuk reset password user `admin` (atau user apa pun)
langsung dari command line, tanpa perlu login lewat API.

KAPAN DIPAKAI:
    Saat login dengan admin/admin123 balas "Invalid username or password"
    — biasanya karena database di-reset, atau password hash tidak match
    setelah perubahan PasswordHasher.

CARA PAKAI:
    cd E:\\full_erp_accounting_engine
    python reset_admin_password.py admin admin123

ARGUMEN:
    arg1 = username (default: admin)
    arg2 = password baru (default: admin123)

CATATAN TEKNIS PENTING (FIX v2):
    Skrip ini WAJIB memanggil `load_all_models()` SEBELUM mengimpor
    `IAMUserTable`, karena mapper `IAMUserTable` punya relationship ke
    `LegalEntityTable` (di file ORM terpisah) — kalau `LegalEntityTable`
    belum ter-import, SQLAlchemy akan error:
        "When initializing mapper IAMUserTable, expression 'LegalEntityTable'
         failed to locate a name"
    Backend FastAPI sendiri melakukan ini di `lifespan()`
    (`load_all_models()` sebelum servis dijalankan), jadi skrip standalone
    ini meniru pola yang sama.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Tambahkan project root ke sys.path supaya bisa import module lokal
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> int:
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    new_password = sys.argv[2] if len(sys.argv) > 2 else "admin123"

    # ==================================================================
    # LANGKAH 1 (WAJIB): Muat SEMUA ORM models supaya SQLAlchemy bisa
    # me-resolve relationship antar table (mis. IAMUserTable -> LegalEntityTable).
    # Harus dipanggil SEBELUM `from infrastructure.persistence_orm.iam_user_table import IAMUserTable`
    # supaya semua nama class (LegalEntityTable, dll) sudah terdaftar di
    # registry SQLAlchemy.
    # ==================================================================
    print("[1/4] Memuat semua ORM models (load_all_models)...")
    from infrastructure.persistence_orm import load_all_models
    load_all_models()
    print("[1/4] OK — semua ORM models termuat")

    # Baru sekarang aman untuk import tabel individual
    from infrastructure.database.session_factory_sqlalchemy import (
        get_async_session_factory,
    )
    from sqlalchemy import select
    from infrastructure.persistence_orm.iam_user_table import IAMUserTable

    # ==================================================================
    # LANGKAH 2: Tentukan PasswordHasher yang dipakai backend.
    # Coba beberapa lokasi umum, fallback ke bcrypt langsung.
    # ==================================================================
    print("[2/4] Menyiapkan PasswordHasher...")
    password_hasher = None
    for import_path in (
        "infrastructure.security.password_hasher",
        "infrastructure.security.password_hasher_bcrypt",
        "infrastructure.security.password_service",
    ):
        try:
            module = __import__(import_path, fromlist=["PasswordHasher"])
            hasher_cls = getattr(module, "PasswordHasher", None)
            if hasher_cls is not None:
                password_hasher = hasher_cls()
                print(f"[2/4] PasswordHasher dimuat dari {import_path}")
                break
        except (ImportError, AttributeError):
            continue

    if password_hasher is None:
        try:
            import bcrypt
        except ImportError:
            print("[FATAL] Tidak bisa menemukan PasswordHasher DAN bcrypt tidak terpasang.")
            print("        Pastikan backend ERP ini pakai bcrypt/passlib untuk hash password.")
            return 1

        class _BCryptAdapter:
            @staticmethod
            def hash(plain: str) -> str:
                return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        password_hasher = _BCryptAdapter()
        print("[2/4] PasswordHasher fallback: bcrypt langsung")

    new_hash = password_hasher.hash(new_password)

    # ==================================================================
    # LANGKAH 3: Cari user & update password hash + status.
    # ==================================================================
    print(f"[3/4] Mencari user '{username}' di database...")
    factory = await get_async_session_factory()
    async with factory() as session:
        stmt = select(IAMUserTable).where(IAMUserTable.username == username)
        result = await session.execute(stmt)
        user_row = result.scalar_one_or_none()

        if user_row is None:
            print(f"[ERROR] User '{username}' TIDAK DITEMUKAN di database.")
            print("        Kemungkinan database sudah di-reset. Buat user baru dulu")
            print("        lewat endpoint POST /api/v1/iam/iam/users (butuh login admin")
            print("        yang sudah ada) — atau minta bantuan tim backend.")
            return 2

        # Set password hash baru
        user_row.password_hash = new_hash
        # Pastikan status juga aktif dan tidak terkunci
        if hasattr(user_row, "status"):
            user_row.status = "active"
        if hasattr(user_row, "is_active"):
            user_row.is_active = True
        if hasattr(user_row, "locked_until"):
            user_row.locked_until = None
        if hasattr(user_row, "failed_login_attempts"):
            user_row.failed_login_attempts = 0

        await session.commit()
        print(f"[3/4] OK — password untuk user '{username}' berhasil direset.")

    # ==================================================================
    # LANGKAH 4: Selesai.
    # ==================================================================
    print("[4/4] SELESAI.")
    print(f"      Login dengan: username='{username}', password='{new_password}'")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
    