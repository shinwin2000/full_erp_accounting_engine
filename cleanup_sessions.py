"""
cleanup_sessions.py
====================
Skrip utilitas untuk menghapus sesi login yang sudah kadaluarsa
atau sudah di-revoke dari tabel `iam_session`.

JALANKAN:
    cd E:\\full_erp_accounting_engine
    python cleanup_sessions.py
"""
import asyncio

from infrastructure.persistence_orm import load_all_models

load_all_models()


async def main() -> None:
    from infrastructure.database.session_factory_sqlalchemy import (
        get_async_session_factory,
    )
    from sqlalchemy import text

    factory = await get_async_session_factory()
    async with factory() as session:
        # Hitung dulu berapa yang akan dihapus
        r = await session.execute(text(
            "SELECT COUNT(*) FROM iam_session "
            "WHERE expires_at < NOW() OR is_revoked = TRUE"
        ))
        total = r.scalar()
        print(f"Sesi yang akan dihapus: {total}")

        if not total:
            print("Tidak ada yang perlu dihapus.")
            return

        # Hapus
        r = await session.execute(text(
            "DELETE FROM iam_session "
            "WHERE expires_at < NOW() OR is_revoked = TRUE"
        ))
        await session.commit()
        print(f"[OK] Dihapus: {r.rowcount} baris")

        # Cek sisa
        r = await session.execute(text("SELECT COUNT(*) FROM iam_session"))
        sisa = r.scalar()
        print(f"Sisa sesi aktif: {sisa}")


if __name__ == "__main__":
    asyncio.run(main())
    