"""
Cek apakah user admin punya row di tabel role/permission assignment,
untuk membedakan: bug di logic JWT issuer (tidak query role sama sekali)
vs data belum lengkap (memang belum ada role yang di-assign).

Usage: python check_roles.py
"""
import asyncio


async def main():
    from sqlalchemy import text
    from infrastructure.persistence_orm.database import async_session_maker

    admin_id = "d319d343-742e-44ff-b142-37386a1cdd57"

    async with async_session_maker() as session:
        print("=== 1. Cari tabel yang berhubungan dengan role/permission ===")
        result = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' "
                "AND (table_name ILIKE '%role%' OR table_name ILIKE '%permission%') "
                "ORDER BY table_name"
            )
        )
        tables = [r[0] for r in result.fetchall()]
        for t in tables:
            print(f"  - {t}")

        print(f"\n=== 2. Cek row iam_user untuk admin (role_ids, is_superuser) ===")
        result2 = await session.execute(
            text("SELECT role_ids, is_superuser FROM iam_user WHERE id = :id"),
            {"id": admin_id},
        )
        row = result2.fetchone()
        print(f"  role_ids     : {row.role_ids}")
        print(f"  is_superuser : {row.is_superuser}")

        print("\n=== 3. Coba cek tabel junction/assignment (kalau ada) ===")
        for t in tables:
            if t == "iam_user":
                continue
            try:
                # coba tebak kolom user_id yang umum
                r = await session.execute(
                    text(f"SELECT * FROM {t} LIMIT 5")
                )
                rows = r.fetchall()
                print(f"  Tabel '{t}': {len(rows)} row (sample max 5)")
                for rr in rows:
                    print(f"      {dict(rr._mapping)}")
            except Exception as e:
                print(f"  Tabel '{t}': gagal query - {e}")


if __name__ == "__main__":
    asyncio.run(main())
