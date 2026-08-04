"""
Cek legal_entity_ids yang benar-benar tersimpan untuk user admin,
dan cek juga apakah row di tabel legal_entity untuk id tersebut memang ada.

Jalankan: python check_legal_entity.py
"""
import asyncio


async def main():
    from sqlalchemy import text
    from infrastructure.persistence_orm.database import async_session_maker

    async with async_session_maker() as session:
        print("=== 1. legal_entity_ids milik user admin ===")
        result = await session.execute(
            text("SELECT id, username, legal_entity_ids FROM iam_user WHERE username = 'admin'")
        )
        row = result.fetchone()
        if not row:
            print("  User admin tidak ditemukan.")
            return
        print(f"  user_id          : {row.id}")
        print(f"  legal_entity_ids : {row.legal_entity_ids}")

        print("\n=== 2. Isi tabel legal_entity (semua row) ===")
        try:
            result2 = await session.execute(
                text("SELECT id, name, npwp, status FROM legal_entity LIMIT 20")
            )
            rows2 = result2.fetchall()
            if not rows2:
                print("  Tabel legal_entity KOSONG - tidak ada satupun legal entity terdaftar!")
            for r in rows2:
                print(f"  id={r.id}  name={r.name}  npwp={r.npwp}  status={r.status}")
        except Exception as e:
            print(f"  Gagal query tabel legal_entity: {e}")
            print("  (mungkin nama tabelnya beda, cek dengan \\dt di psql)")


if __name__ == "__main__":
    asyncio.run(main())
