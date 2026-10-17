"""
reset_mfa.py
=============
Matikan MFA user `admin` supaya bisa setup ulang dari awal.
Jalankan setelah login gagal karena kode MFA tidak valid.
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
        # Matikan MFA untuk user admin
        r = await session.execute(text(
            "UPDATE iam_user "
            "SET mfa_enabled = FALSE, mfa_secret = NULL, mfa_backup_codes = NULL "
            "WHERE username = 'admin'"
        ))
        await session.commit()
        print(f"[OK] {r.rowcount} user di-update (MFA dimatikan)")

        # Verifikasi
        r = await session.execute(text(
            "SELECT username, mfa_enabled, mfa_secret "
            "FROM iam_user WHERE username = 'admin'"
        ))
        for row in r.fetchall():
            print(f"  username={row[0]} | mfa_enabled={row[1]} | mfa_secret={'<SET>' if row[2] else '<NULL>'}")


if __name__ == "__main__":
    asyncio.run(main())
    