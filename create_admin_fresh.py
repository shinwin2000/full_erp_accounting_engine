#!/usr/bin/env python3
"""
create_admin_fresh.py - Hapus user admin lama dan buat baru dengan hash bcrypt yang benar.
"""

import asyncio
import os
import uuid
import json
import bcrypt
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:palapapls88@localhost/erp_db")
    if not DATABASE_URL:
        print("[X] DATABASE_URL environment variable not set")
        return 1

    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        # 1. Legal Entity
        company_name = "PT Saya"
        legal_id = uuid.uuid4()
        now = datetime.utcnow()

        result = await conn.execute(
            text("SELECT id FROM legal_entity WHERE legal_name = :name"),
            {"name": company_name}
        )
        row = result.fetchone()
        if row:
            legal_id = row[0]
            print(f"[=] Legal Entity '{company_name}' sudah ada (ID: {legal_id})")
        else:
            await conn.execute(
                text("""
                    INSERT INTO legal_entity (
                        id, legal_name, trade_name, entity_type, registration_number, npwp,
                        address, city, postal_code, country, phone, email, website,
                        established_date, fiscal_year_start, fiscal_year_end,
                        base_currency, functional_currency,
                        tax_office, tax_office_code, tax_classification, taxable_date,
                        annual_tax_return_due_date, monthly_tax_due_date,
                        is_vat_collector, vat_collector_number, is_withholding_agent,
                        status, is_active,
                        parent_company_id, consolidation_group_id,
                        logo_url, extra_metadata, created_by,
                        created_at, updated_at, version
                    ) VALUES (
                        :id, :name, :trade_name, :type, :reg_number, :npwp,
                        :address, :city, :postal, :country, :phone, :email, :website,
                        :established_date, :fiscal_year_start, :fiscal_year_end,
                        :base_currency, :functional_currency,
                        :tax_office, :tax_office_code, :tax_classification, :taxable_date,
                        :annual_tax_return_due_date, :monthly_tax_due_date,
                        :is_vat_collector, :vat_collector_number, :is_withholding_agent,
                        :status, :is_active,
                        :parent_company_id, :consolidation_group_id,
                        :logo_url, :extra_metadata, :created_by,
                        :created_at, :updated_at, :version
                    )
                """),
                {
                    "id": legal_id,
                    "name": company_name,
                    "trade_name": None,
                    "type": "PT",
                    "reg_number": None,
                    "npwp": None,
                    "address": None,
                    "city": None,
                    "postal": None,
                    "country": "ID",
                    "phone": None,
                    "email": None,
                    "website": None,
                    "established_date": None,
                    "fiscal_year_start": 1,
                    "fiscal_year_end": 12,
                    "base_currency": "IDR",
                    "functional_currency": "IDR",
                    "tax_office": None,
                    "tax_office_code": None,
                    "tax_classification": None,
                    "taxable_date": None,
                    "annual_tax_return_due_date": None,
                    "monthly_tax_due_date": None,
                    "is_vat_collector": False,
                    "vat_collector_number": None,
                    "is_withholding_agent": False,
                    "status": "active",
                    "is_active": True,
                    "parent_company_id": None,
                    "consolidation_group_id": None,
                    "logo_url": None,
                    "extra_metadata": None,
                    "created_by": None,
                    "created_at": now,
                    "updated_at": now,
                    "version": 1,
                }
            )
            print(f"[+] Legal Entity '{company_name}' dibuat (ID: {legal_id})")

        # 2. Permission
        perm_id = uuid.uuid4()
        result = await conn.execute(
            text("SELECT id FROM iam_permission WHERE resource = '*' AND action = '*'")
        )
        row = result.fetchone()
        if row:
            perm_id = row[0]
            print("[=] Permission '*:*' sudah ada")
        else:
            await conn.execute(
                text("""
                    INSERT INTO iam_permission (id, name, resource, action, description)
                    VALUES (:id, '*:*', '*', '*', 'Full access')
                """),
                {"id": perm_id}
            )
            print("[+] Permission '*:*' dibuat")

        # 3. Role
        role_id = uuid.uuid4()
        result = await conn.execute(
            text("SELECT id FROM iam_role WHERE name = 'Administrator'")
        )
        row = result.fetchone()
        if row:
            role_id = row[0]
            print("[=] Role 'Administrator' sudah ada")
        else:
            await conn.execute(
                text("""
                    INSERT INTO iam_role (id, name, description, is_active, is_system_role)
                    VALUES (:id, 'Administrator', 'Full-access administrator role', true, true)
                """),
                {"id": role_id}
            )
            print("[+] Role 'Administrator' dibuat")

        # Link permission to role
        await conn.execute(
            text("""
                INSERT INTO iam_role_permission (role_id, permission_id)
                VALUES (:role_id, :perm_id)
                ON CONFLICT (role_id, permission_id) DO NOTHING
            """),
            {"role_id": role_id, "perm_id": perm_id}
        )
        print("[+] Permission '*:*' ditautkan ke role 'Administrator'")

        # 4. Hapus user admin lama jika ada
        username = "admin"
        result = await conn.execute(
            text("SELECT id FROM iam_user WHERE username = :username"),
            {"username": username}
        )
        row = result.fetchone()
        if row:
            old_user_id = row[0]
            await conn.execute(
                text("DELETE FROM iam_user_role WHERE user_id = :user_id"),
                {"user_id": old_user_id}
            )
            await conn.execute(
                text("DELETE FROM iam_user WHERE id = :id"),
                {"id": old_user_id}
            )
            print(f"[=] User lama '{username}' dihapus")

        # 5. Buat user admin baru dengan semua kolom required
        password = "Admin123!"
        email = "admin@example.com"
        full_name = "Administrator"
        pwd_bytes = password.encode('utf-8')[:72]
        hashed = bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode('ascii')
        print(f"[+] Hash baru: {hashed}")

        legal_ids_json = json.dumps([str(legal_id)])
        user_id = uuid.uuid4()

        await conn.execute(
            text("""
                INSERT INTO iam_user (
                    id, username, email, phone, phone_encrypted, full_name, password_hash,
                    is_superuser, is_active, status, legal_entity_ids,
                    must_change_password, failed_login_count,
                    created_at, updated_at, created_by, version
                ) VALUES (
                    :id, :username, :email, :phone, :phone_encrypted, :full_name, :hash,
                    :is_superuser, :is_active, :status, CAST(:legal_ids AS jsonb),
                    :must_change_password, :failed_login_count,
                    :created_at, :updated_at, :created_by, :version
                )
            """),
            {
                "id": user_id,
                "username": username,
                "email": email,
                "phone": None,
                "phone_encrypted": None,
                "full_name": full_name,
                "hash": hashed,
                "is_superuser": True,
                "is_active": True,
                "status": "active",
                "legal_ids": legal_ids_json,
                "must_change_password": False,
                "failed_login_count": 0,
                "created_at": now,
                "updated_at": now,
                "created_by": None,
                "version": 1,
            }
        )
        print(f"[+] User '{username}' dibuat")

        # Link role to user
        await conn.execute(
            text("""
                INSERT INTO iam_user_role (user_id, role_id)
                VALUES (:user_id, :role_id)
                ON CONFLICT (user_id, role_id) DO NOTHING
            """),
            {"user_id": user_id, "role_id": role_id}
        )
        print("[+] Role 'Administrator' ditautkan ke user")

        await conn.commit()
        print("\n" + "=" * 60)
        print("  SELESAI — Admin baru dibuat")
        print(f"  Username     : {username}")
        print(f"  Password     : {password}")
        print(f"  Legal Entity : {company_name}")
        print(f"  Legal Entity ID: {legal_id}")
        print("=" * 60)
        return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)