"""
Diagnostik: cek apakah password_hash di seed_admin.py benar-benar
hash bcrypt dari "Admin123!", dan cek juga status/is_active user admin
langsung dari database.

Jalankan dengan interpreter yang sama dipakai project (python 3.11 + venv aktif):
    python check_admin_login.py
"""
import asyncio

import bcrypt

# --- 1. Cek independen: apakah hash ini benar-benar untuk "Admin123!" ---
STORED_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKx0f7WcUmHx5cW"

candidates = [
    "Admin123!",
    "admin123!",
    "Admin123",
    "password",
    "secret",
    "admin",
]

print("=== TES 1: Cocokkan hash dengan beberapa kandidat password ===")
for pw in candidates:
    try:
        ok = bcrypt.checkpw(pw.encode("utf-8"), STORED_HASH.encode("utf-8"))
        print(f"  '{pw}' -> {'COCOK' if ok else 'tidak cocok'}")
    except Exception as e:
        print(f"  '{pw}' -> ERROR saat verifikasi: {e}")

print("\n=== TES 2: Generate hash baru untuk 'Admin123!' (untuk perbandingan) ===")
new_hash = bcrypt.hashpw(b"Admin123!", bcrypt.gensalt(rounds=12)).decode()
print(f"  Hash baru untuk 'Admin123!': {new_hash}")
print(f"  Hash lama di seed_admin.py: {STORED_HASH}")
print("  (Hash beda itu WAJAR karena salt bcrypt selalu random tiap generate -")
print("   yang penting TES 1 di atas, apakah checkpw() balikin COCOK atau tidak)")


# --- 2. Cek langsung ke database: status, is_active, hash yang benar2 tersimpan ---
async def check_db():
    print("\n=== TES 3: Cek row admin langsung dari database ===")
    try:
        from sqlalchemy import text

        from infrastructure.persistence_orm.database import async_session_maker
    except ImportError as e:
        print(f"  Tidak bisa import modul project: {e}")
        print("  Jalankan script ini dari root folder project dengan venv yang benar.")
        return

    async with async_session_maker() as session:
        result = await session.execute(
            text(
                "SELECT id, username, status, is_active, is_superuser, "
                "failed_login_count, must_change_password, password_hash "
                "FROM iam_user WHERE username = 'admin'"
            )
        )
        row = result.fetchone()
        if not row:
            print("  User 'admin' TIDAK ditemukan di database ini.")
            return
        print(f"  id                  : {row.id}")
        print(f"  username            : {row.username}")
        print(f"  status              : {row.status}")
        print(f"  is_active           : {row.is_active}")
        print(f"  is_superuser        : {row.is_superuser}")
        print(f"  failed_login_count  : {row.failed_login_count}")
        print(f"  must_change_password: {row.must_change_password}")
        print(f"  password_hash (db)  : {row.password_hash}")
        print(f"  password_hash (file): {STORED_HASH}")
        print(f"  SAMA dengan yang di seed_admin.py? "
              f"{'YA' if row.password_hash == STORED_HASH else 'TIDAK - berbeda!'}")

        # tes ulang checkpw pakai hash yang BENAR-BENAR ada di DB
        print("\n=== TES 4: Cocokkan kandidat password dengan hash YANG ADA DI DB ===")
        for pw in candidates:
            try:
                ok = bcrypt.checkpw(pw.encode("utf-8"), row.password_hash.encode("utf-8"))
                print(f"  '{pw}' -> {'COCOK' if ok else 'tidak cocok'}")
            except Exception as e:
                print(f"  '{pw}' -> ERROR saat verifikasi: {e}")


if __name__ == "__main__":
    asyncio.run(check_db())
