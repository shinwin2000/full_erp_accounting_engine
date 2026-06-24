#!/usr/bin/env python3
"""
Module: fix.py
Responsibility: Maintenance script untuk pemulihan state Alembic secara lokal.
                - Mengonversi asyncpg driver ke sync driver (psycopg2).
                - Memetakan DNS host 'postgres' (Docker context) ke 'localhost'.
                - Mengosongkan tabel `alembic_version` dan menyuntikkan head revision sekuensial.
"""

import os
import sys
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Target head revision sekuensial terakhir yang valid dan eksis di folder lokal Anda
TARGET_REVISION = "0045"


def main():
    load_dotenv()

    # 1. Ambil URL Database dari alembic.ini atau Environment Variable
    alembic_cfg = Config("alembic.ini")
    db_url = alembic_cfg.get_main_option("sqlalchemy.url") or os.getenv(
        "DATABASE_URL"
    )

    if not db_url:
        print("❌ ERROR: DATABASE_URL tidak ditemukan di alembic.ini maupun .env")
        sys.exit(1)

    print(f"🔗 Original DB URL : {db_url}")

    # 2. Transmutilasi Driver: asyncpg -> psycopg2 (Synchronous Engine)
    if "asyncpg" in db_url:
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    # 3. Resolusi DNS: Ubah konteks network Docker ('postgres') ke lokal host machine
    if "@postgres:" in db_url:
        db_url = db_url.replace("@postgres:", "@localhost:")
    elif "@postgres/" in db_url:
        db_url = db_url.replace("@postgres/", "@localhost/")
    elif "//postgres:" in db_url:
        db_url = db_url.replace("//postgres:", "//localhost:")

    print(f"🔄 Resolved DB URL : {db_url}")

    # 4. Inisialisasi Engine & Eksekusi Skrip Pemulihan State
    try:
        engine = create_engine(db_url, echo=False)

        with engine.connect() as conn:
            # Mulai transaksi eksplisit
            with conn.begin():
                print("\n🧹 Mengosongkan tabel alembic_version...")
                conn.execute(text("TRUNCATE TABLE alembic_version;"))
                print("✅ Tabel alembic_version berhasil dikosongkan.")

                print(
                    f"📥 Menyuntikkan Target Revision '{TARGET_REVISION}' ke database..."
                )
                conn.execute(
                    text(
                        "INSERT INTO alembic_version (version_num) VALUES (:version);"
                    ),
                    {"version": TARGET_REVISION},
                )
                print(f"✅ State database berhasil dipaksa ke: {TARGET_REVISION}")

        print("\n🎉 SUCCESS: Sinkronisasi state Alembic selesai secara bersih!")
        print("Anda sekarang dapat menjalankan 'alembic current' untuk verifikasi.")

    except Exception as e:
        print(f"\n❌ CRITICAL: Gagal mengeksekusi script maintenance.")
        print(f"Detail Eror: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()