#!/usr/bin/env python3
"""
create_first_admin.py
=======================
Membuat user admin pertama secara langsung ke database.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("[!] python-dotenv tidak terpasang, melanjutkan tanpa memuat .env otomatis.")

try:
    import bcrypt as raw_bcrypt
except ImportError:
    print("[X] Modul 'bcrypt' tidak ditemukan. Install dulu: pip install bcrypt")
    sys.exit(1)

try:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
except ImportError:
    print("[X] Modul 'sqlalchemy' tidak ditemukan. Pastikan venv backend aktif & requirements terpasang.")
    sys.exit(1)


def hash_password_safely(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    if len(pwd_bytes) > 72:
        pwd_bytes = pwd_bytes[:72]
    salt = raw_bcrypt.gensalt()
    hashed_bytes = raw_bcrypt.hashpw(pwd_bytes, salt)
    return hashed_bytes.decode("ascii")


async def main(args: argparse.Namespace) -> int:
    try:
        from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import SqlAlchemyUnitOfWork
        from infrastructure.persistence_orm.iam_user_table import (
            IAMPermissionTable,
            IAMRoleTable,
            IAMUserTable,
        )
        from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable
    except ImportError as exc:
        print(f"[X] Gagal import modul backend: {exc}")
        print("    Pastikan script ini dijalankan dari root folder backend")
        return 1

    company_name = args.company or input("Nama Perusahaan (Legal Entity)   : ").strip()
    entity_type = args.entity_type or (input("Tipe Entitas [PT]                : ").strip() or "PT")
    npwp = args.npwp or input("NPWP (boleh kosong)              : ").strip() or None

    username = args.username or input("Username admin                  : ").strip()
    email = args.email or input("Email admin                     : ").strip()
    full_name = args.full_name or input("Nama lengkap admin              : ").strip() or username

    password = args.password
    if not password:
        password = getpass.getpass("Password admin                  : ")
        password_confirm = getpass.getpass("Ulangi password                  : ")
        if password != password_confirm:
            print("[X] Password tidak sama. Dibatalkan.")
            return 1

    if not (company_name and username and email and password):
        print("[X] Nama perusahaan, username, email, dan password wajib diisi.")
        return 1

    if len(password) < 8:
        print("[X] Password minimal 8 karakter.")
        return 1

    pwd_bytes = password.encode("utf-8")
    if len(pwd_bytes) > 72:
        print(f"\n[!] PERINGATAN: Password Anda memiliki {len(pwd_bytes)} byte.")
        print("    Algoritma enkripsi 'bcrypt' maksimal HANYA bisa memproses 72 byte.")
        print("    Script ini akan secara otomatis memotongnya menjadi 72 byte pertama saja.")
        print("    Saat login nanti, pastikan Anda juga HANYA mengetikkan 72 byte tersebut.\n")

    # --- Perbaikan: Buat engine dan async_sessionmaker langsung ---
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        # Default jika tidak ada
        DATABASE_URL = "postgresql+asyncpg://postgresql:palapapls88@localhost/erp_db"
        print(f"[!] DATABASE_URL tidak diset, menggunakan default: {DATABASE_URL}")
    engine = create_async_engine(DATABASE_URL)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)
    uow = SqlAlchemyUnitOfWork(session_factory=async_session_maker)

    try:
        # Mulai transaksi secara eksplisit
        await uow.begin()

        # 1. Legal Entity
        legal_entity = await uow.session.execute(
            select(LegalEntityTable).where(LegalEntityTable.legal_name == company_name)
        )
        legal_entity = legal_entity.scalar_one_or_none()
        if legal_entity:
            print(f"[=] Legal Entity '{company_name}' sudah ada, dipakai ulang.")
        else:
            legal_entity = LegalEntityTable(
                id=uuid.uuid4(),
                legal_name=company_name,
                entity_type=entity_type,
                npwp=npwp,
                country="ID",
                base_currency="IDR",
                functional_currency="IDR",
                fiscal_year_start=1,
                fiscal_year_end=12,
                status="active",
                is_active=True,
            )
            uow.session.add(legal_entity)
            await uow.session.flush()
            print(f"[+] Legal Entity dibuat: {company_name} ({legal_entity.id})")

        # 2. Permission
        permission = await uow.session.execute(
            select(IAMPermissionTable).where(
                IAMPermissionTable.resource == "*", IAMPermissionTable.action == "*"
            )
        )
        permission = permission.scalar_one_or_none()
        if permission:
            print("[=] Permission wildcard '*:*' sudah ada, dipakai ulang.")
        else:
            permission = IAMPermissionTable(
                id=uuid.uuid4(),
                name="*:*",
                resource="*",
                action="*",
                description="Full access",
            )
            uow.session.add(permission)
            await uow.session.flush()
            print("[+] Permission wildcard '*:*' dibuat.")

        # 3. Role
        role = await uow.session.execute(
            select(IAMRoleTable).where(IAMRoleTable.name == "Administrator")
        )
        role = role.scalar_one_or_none()
        if role:
            print("[=] Role 'Administrator' sudah ada, dipakai ulang.")
        else:
            role = IAMRoleTable(
                id=uuid.uuid4(),
                name="Administrator",
                description="Full-access administrator role",
                is_active=True,
                is_system_role=True,
            )
            uow.session.add(role)
            await uow.session.flush()
            print("[+] Role 'Administrator' dibuat.")

        await uow.session.refresh(role, attribute_names=["permissions"])
        if permission not in role.permissions:
            role.permissions.append(permission)
            print("[+] Permission '*:*' ditautkan ke role 'Administrator'.")

        # 4. User admin
        user = await uow.session.execute(
            select(IAMUserTable).where(IAMUserTable.username == username)
        )
        user = user.scalar_one_or_none()

        password_hash = hash_password_safely(password)

        if user:
            entity_ids = set(user.legal_entity_ids or [])
            entity_ids.add(str(legal_entity.id))

            user.password_hash = password_hash
            user.email = email
            user.full_name = full_name
            user.is_superuser = True
            user.is_active = True
            user.status = "active"
            user.must_change_password = False
            user.legal_entity_ids = list(entity_ids)
            print(f"[=] User '{username}' sudah ada — password & akses diperbarui.")
        else:
            user = IAMUserTable(
                id=uuid.uuid4(),
                username=username,
                email=email,
                full_name=full_name,
                password_hash=password_hash,
                must_change_password=False,
                is_superuser=True,
                is_active=True,
                status="active",
                legal_entity_ids=[str(legal_entity.id)],
            )
            uow.session.add(user)
            await uow.session.flush()
            print(f"[+] User admin dibuat: {username} ({user.id})")

        await uow.session.refresh(user, attribute_names=["roles"])
        if role not in user.roles:
            user.roles.append(role)
            print("[+] Role 'Administrator' ditautkan ke user.")

        # Commit transaksi secara eksplisit
        await uow.commit()
        print("\n" + "=" * 60)
        print("  SELESAI — Anda sekarang bisa login di frontend dengan:")
        print(f"  Username     : {username}")
        print("  Password     : (Sesuai yang Anda input. Jika kepanjangan, 72 karakter pertama)")
        print(f"  Legal Entity : {company_name}")
        print("=" * 60)
        return 0

    except Exception as e:
        # Rollback jika terjadi error
        await uow.rollback()
        print(f"[X] Terjadi error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Buat user admin pertama Sovereign ERP.")
    parser.add_argument("--company", default=os.environ.get("COMPANY_NAME", ""))
    parser.add_argument("--entity-type", default=os.environ.get("COMPANY_ENTITY_TYPE", ""))
    parser.add_argument("--npwp", default=os.environ.get("COMPANY_NPWP", ""))
    parser.add_argument("--username", default=os.environ.get("ADMIN_USERNAME", ""))
    parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL", ""))
    parser.add_argument("--full-name", default=os.environ.get("ADMIN_FULL_NAME", ""))
    parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD", ""))
    return parser.parse_args()


if __name__ == "__main__":
    parsed_args = parse_args()
    exit_code = asyncio.run(main(parsed_args))
    sys.exit(exit_code)
