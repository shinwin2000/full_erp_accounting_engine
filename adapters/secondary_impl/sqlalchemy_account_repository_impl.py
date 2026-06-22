#!/usr/bin/env python3
"""
Module: sqlalchemy_account_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk aggregate Account (Chart of Accounts)
               menggunakan SQLAlchemy ORM. Menyediakan operasi CRUD untuk akun,
               hierarki akun (parent-child), validasi unik per entitas hukum,
               dan soft delete. Mendukung optimistic locking untuk update.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- sqlalchemy import select, update, delete, func, and_, or_
- ports.primary.account_repository_port (AccountRepositoryPort)
- domain.coa.aggregate_root (AccountAggregate)
- infrastructure.persistence_orm.account_table (AccountTable)
- domain.shared_value_objects.money_vo (Money)
Audit: Setiap perubahan pada COA dicatat di event store (diluar repository).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.coa.account_code_vo import AccountCode
from domain.coa.account_entity import AccountStatus, NormalBalance
from domain.coa.account_type_enum import AccountType

# Domain
from domain.coa.aggregate_root import AccountAggregate

# Infrastructure ORM
from infrastructure.persistence_orm.account_table import AccountTable

# Ports
from ports.primary.account_repository_port import AccountRepositoryPort

# Money - pastikan import benar
from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPTIONS
# ============================================================================


class AccountRepositoryError(Exception):
    """Base exception untuk repository account."""
    pass


class DuplicateAccountCodeError(AccountRepositoryError):
    """Kode akun sudah ada dalam entitas hukum yang sama."""
    pass


class AccountNotFoundError(AccountRepositoryError):
    """Akun tidak ditemukan."""
    pass


class AccountHasChildrenError(AccountRepositoryError):
    """Akun memiliki sub-akun, tidak bisa dihapus."""
    pass


class AccountHasTransactionsError(AccountRepositoryError):
    """Akun sudah memiliki transaksi, tidak bisa dinonaktifkan."""
    pass


class OptimisticLockError(AccountRepositoryError):
    """Version mismatch saat update."""
    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyAccountRepository(AccountRepositoryPort):
    """
    Implementasi repository Account dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========================================================================
    # HELPER MAPPING METHODS
    # ========================================================================

    def _to_domain(self, table: AccountTable) -> AccountAggregate:
        """
        Mapping dari ORM model ke domain aggregate.
        """
        # Convert string enum values to domain enums
        account_type = AccountType(table.account_type) if table.account_type else AccountType.ASSET
        normal_balance = (
            NormalBalance(table.normal_balance) if table.normal_balance else NormalBalance.DEBIT
        )
        status = AccountStatus(table.status) if table.status else AccountStatus.DRAFT

        aggregate = AccountAggregate(
            id=table.id,
            account_code=AccountCode(table.account_code),
            account_name=table.account_name,
            account_type=account_type,
            normal_balance=normal_balance,
            parent_account_id=table.parent_account_id,
            level=table.level,
            description=table.description,
            status=status,
            currency_code=table.currency_code,
            is_bank_account=table.is_bank_account,
            is_cash_account=table.is_cash_account,
            is_intercompany=table.is_intercompany,
            is_header=table.is_header,
            opening_balance=Money(
                amount=table.opening_balance or 0, currency=table.currency_code or "IDR"
            ),
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            version=table.version,
            legal_entity_id=table.legal_entity_id,
        )

        return aggregate

    async def _to_orm(self, aggregate: AccountAggregate) -> AccountTable:
        """Mapping dari domain ke ORM model."""
        account_type_str = aggregate.account_type.value
        normal_balance_str = aggregate.normal_balance.value
        status_str = aggregate.status.value

        table = AccountTable(
            id=aggregate.id,
            account_code=str(aggregate.account_code),
            account_name=aggregate.account_name,
            account_type=account_type_str,
            normal_balance=normal_balance_str,
            parent_account_id=aggregate.parent_account_id,
            level=aggregate.level,
            description=aggregate.description,
            status=status_str,
            currency_code=aggregate.currency_code,
            is_bank_account=aggregate.is_bank_account,
            is_cash_account=aggregate.is_cash_account,
            is_intercompany=aggregate.is_intercompany,
            is_header=aggregate.is_header,
            opening_balance=aggregate.opening_balance.amount if aggregate.opening_balance else 0,
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            created_by=aggregate.created_by,
            version=aggregate.version,
            legal_entity_id=aggregate.legal_entity_id,
            is_active=aggregate.status == AccountStatus.ACTIVE,
        )
        return table

    # ========================================================================
    # REPOSITORY METHODS (dari port)
    # ========================================================================

    async def add(self, account: AccountAggregate) -> None:
        """
        Menambahkan akun baru ke Chart of Accounts.
        """
        session = await self._get_session()
        try:
            # Cek duplikasi account_code dalam legal entity yang sama
            stmt = (
                select(func.count())
                .select_from(AccountTable)
                .where(
                    AccountTable.account_code == str(account.account_code),
                    AccountTable.legal_entity_id == account.legal_entity_id,
                    AccountTable.deleted_at.is_(None),
                )
            )
            result = await session.execute(stmt)
            count = result.scalar()

            if count > 0:
                raise DuplicateAccountCodeError(
                    f"Account code {account.account_code} already exists in legal entity {account.legal_entity_id}"
                )

            # Cek parent account exists jika ada
            if account.parent_account_id:
                parent_stmt = select(AccountTable).where(
                    AccountTable.id == account.parent_account_id
                )
                parent_result = await session.execute(parent_stmt)
                if not parent_result.scalar_one_or_none():
                    raise AccountNotFoundError(
                        f"Parent account {account.parent_account_id} not found"
                    )

            # Mapping dan simpan
            table = await self._to_orm(account)
            session.add(table)
            await session.flush()

            logger.info("Account added: %s (id=%s)", account.account_code, account.id)

        except DuplicateAccountCodeError:
            raise
        except IntegrityError as e:
            await session.rollback()
            raise AccountRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await session.rollback()
            logger.error("Failed to add account: %s", e)
            raise AccountRepositoryError(f"Failed to add account: {e}") from e

    async def get_by_id(self, account_id: UUID) -> AccountAggregate | None:
        """
        Mengambil akun berdasarkan ID.
        """
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.id == account_id, AccountTable.deleted_at.is_(None)
            )
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()

            if not table:
                return None

            return self._to_domain(table)

        except Exception as e:
            logger.error("Failed to get account by id %s: %s", account_id, e)
            raise AccountRepositoryError(f"Failed to get account: {e}") from e

    async def get_by_code(
        self, account_code: str, legal_entity_id: UUID
    ) -> AccountAggregate | None:
        """
        Mengambil akun berdasarkan kode unik dalam entitas hukum.
        """
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.account_code == account_code,
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()

            if not table:
                return None

            return self._to_domain(table)

        except Exception as e:
            logger.error("Failed to get account by code %s: %s", account_code, e)
            raise AccountRepositoryError(f"Failed to get account: {e}") from e

    async def update(self, account: AccountAggregate) -> None:
        """
        Memperbarui informasi akun.
        """
        session = await self._get_session()
        try:
            # Get current version from database
            stmt = select(AccountTable.version).where(AccountTable.id == account.id)
            result = await session.execute(stmt)
            current_version = result.scalar_one_or_none()

            if current_version is None:
                raise AccountNotFoundError(f"Account {account.id} not found")

            # Check version match
            if current_version != account.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {account.version}, got {current_version}"
                )

            # Update account
            table = await self._to_orm(account)
            table.version = account.version + 1
            table.updated_at = datetime.utcnow()

            await session.merge(table)
            await session.flush()

            logger.info(
                "Account updated: %s (version %d -> %d)",
                account.account_code,
                account.version,
                account.version + 1,
            )

        except OptimisticLockError:
            raise
        except Exception as e:
            await session.rollback()
            logger.error("Failed to update account %s: %s", account.id, e)
            raise AccountRepositoryError(f"Failed to update account: {e}") from e

    async def delete(self, account_id: UUID) -> bool:
        """
        Soft delete akun (set deleted_at dan status inactive).
        """
        session = await self._get_session()
        try:
            # Check if account has children
            children_stmt = (
                select(func.count())
                .select_from(AccountTable)
                .where(
                    AccountTable.parent_account_id == account_id, AccountTable.deleted_at.is_(None)
                )
            )
            children_result = await session.execute(children_stmt)
            children_count = children_result.scalar()

            if children_count > 0:
                raise AccountHasChildrenError(
                    f"Account {account_id} has {children_count} children"
                )

            # Check if account has transactions
            acct = await self.get_by_id(account_id)
            if acct and acct.is_used_in_transaction:
                raise AccountHasTransactionsError(
                    f"Account {account_id} has transactions"
                )

            stmt = (
                update(AccountTable)
                .where(AccountTable.id == account_id)
                .values(deleted_at=datetime.utcnow(), status="inactive", is_active=False)
            )
            result = await session.execute(stmt)
            await session.flush()

            deleted = result.rowcount > 0
            if deleted:
                logger.info("Account %s soft deleted", account_id)
            return deleted

        except (AccountHasChildrenError, AccountHasTransactionsError):
            raise
        except Exception as e:
            await session.rollback()
            logger.error("Failed to delete account %s: %s", account_id, e)
            raise AccountRepositoryError(f"Failed to delete account: {e}") from e

    async def get_children(self, parent_account_id: UUID) -> list[AccountAggregate]:
        """
        Mengambil semua sub-akun dari akun induk.
        """
        session = await self._get_session()
        try:
            stmt = (
                select(AccountTable)
                .where(
                    AccountTable.parent_account_id == parent_account_id,
                    AccountTable.deleted_at.is_(None),
                )
                .order_by(AccountTable.account_code)
            )

            result = await session.execute(stmt)
            tables = result.scalars().all()

            return [self._to_domain(table) for table in tables]

        except Exception as e:
            logger.error("Failed to get children for %s: %s", parent_account_id, e)
            raise AccountRepositoryError(f"Failed to get children: {e}") from e

    async def get_root_accounts(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        """
        Mengambil semua akun level atas (parent_account_id is null).
        """
        session = await self._get_session()
        try:
            stmt = (
                select(AccountTable)
                .where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.parent_account_id.is_(None),
                    AccountTable.deleted_at.is_(None),
                )
                .order_by(AccountTable.account_code)
            )

            result = await session.execute(stmt)
            tables = result.scalars().all()

            return [self._to_domain(table) for table in tables]

        except Exception as e:
            logger.error("Failed to get root accounts for %s: %s", legal_entity_id, e)
            raise AccountRepositoryError(f"Failed to get root accounts: {e}") from e

    async def find_by_type(
        self, account_type: str, legal_entity_id: UUID
    ) -> list[AccountAggregate]:
        """
        Mencari akun berdasarkan tipenya.
        """
        session = await self._get_session()
        try:
            stmt = (
                select(AccountTable)
                .where(
                    AccountTable.account_type == account_type,
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.deleted_at.is_(None),
                )
                .order_by(AccountTable.account_code)
            )

            result = await session.execute(stmt)
            tables = result.scalars().all()

            return [self._to_domain(table) for table in tables]

        except Exception as e:
            logger.error("Failed to find accounts by type %s: %s", account_type, e)
            raise AccountRepositoryError(f"Failed to find accounts: {e}") from e

    async def find_by_name_contains(
        self, name_fragment: str, legal_entity_id: UUID, limit: int = 50
    ) -> list[AccountAggregate]:
        """
        Pencarian akun berdasarkan nama (partial match).
        """
        session = await self._get_session()
        try:
            stmt = (
                select(AccountTable)
                .where(
                    AccountTable.account_name.ilike(func.concat('%', name_fragment, '%')),
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.deleted_at.is_(None),
                )
                .limit(limit)
                .order_by(AccountTable.account_code)
            )

            result = await session.execute(stmt)
            tables = result.scalars().all()

            return [self._to_domain(table) for table in tables]

        except Exception as e:
            logger.error("Failed to search accounts: %s", e)
            raise AccountRepositoryError(f"Failed to search accounts: {e}") from e

    async def get_hierarchy_tree(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        """
        Mendapatkan hierarki akun dalam bentuk tree (nested dict).
        """
        session = await self._get_session()
        try:
            stmt = (
                select(AccountTable)
                .where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.deleted_at.is_(None),
                )
                .order_by(AccountTable.account_code)
            )

            result = await session.execute(stmt)
            tables = result.scalars().all()

            accounts_map = {str(t.id): self._to_domain(t) for t in tables}

            roots = []
            for account in accounts_map.values():
                if account.parent_account_id is None:
                    roots.append(
                        {
                            "id": str(account.id),
                            "account_code": str(account.account_code),
                            "account_name": account.account_name,
                            "account_type": account.account_type.value,
                            "level": account.level,
                            "children": [],
                        }
                    )
                else:
                    parent = accounts_map.get(str(account.parent_account_id))
                    if parent:
                        # Recursive building (simplified, just for stub)
                        pass

            return roots

        except Exception as e:
            logger.error("Failed to get hierarchy tree: %s", e)
            raise AccountRepositoryError(f"Failed to get hierarchy: {e}") from e

    # ========================================================================
    # METODE TAMBAHAN UNTUK MEMENUHI KONTRAK PORT (stub/delegasi)
    # ========================================================================

    async def save(self, account: AccountAggregate) -> None:
        """Simpan (add atau update) akun."""
        existing = await self.get_by_id(account.id)
        if existing:
            await self.update(account)
        else:
            await self.add(account)

    async def list_by_legal_entity(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        """Dapatkan semua akun aktif untuk entitas hukum."""
        session = await self._get_session()
        stmt = select(AccountTable).where(
            AccountTable.legal_entity_id == legal_entity_id,
            AccountTable.deleted_at.is_(None),
            AccountTable.is_active == True,
        ).order_by(AccountTable.account_code)
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    async def find_by_code(self, legal_entity_id: UUID, account_code: str) -> AccountAggregate | None:
        """Cari akun berdasarkan kode (alias get_by_code)."""
        return await self.get_by_code(account_code, legal_entity_id)

    async def get_active_accounts(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        """Dapatkan akun dengan status ACTIVE."""
        session = await self._get_session()
        stmt = select(AccountTable).where(
            AccountTable.legal_entity_id == legal_entity_id,
            AccountTable.status == "active",
            AccountTable.deleted_at.is_(None),
        ).order_by(AccountTable.account_code)
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    # Tambahan method yang mungkin diperlukan port (stub)
    async def find_by_normal_balance(self, normal_balance: str, legal_entity_id: UUID) -> list[AccountAggregate]:
        """Stub: cari berdasarkan normal balance."""
        logger.warning("find_by_normal_balance not fully implemented")
        return []

    async def get_all_by_legal_entity(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        """Alias untuk list_by_legal_entity."""
        return await self.list_by_legal_entity(legal_entity_id)

    async def count_by_type(self, legal_entity_id: UUID) -> dict[str, int]:
        """Stub: hitung akun per tipe."""
        logger.warning("count_by_type not fully implemented")
        return {}

    async def get_account_with_children(self, account_id: UUID) -> dict[str, Any]:
        """Stub: dapatkan akun dengan children."""
        logger.warning("get_account_with_children not fully implemented")
        return {}

    async def save(self, account: AccountAggregate) -> None:
        existing = await self.get_by_id(account.id)
        if existing:
            await self.update(account)
        else:
            await self.add(account)

    async def find_by_id(self, account_id: UUID) -> AccountAggregate | None:
        return await self.get_by_id(account_id)
    
# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS DENGAN ADAPTER REGISTRY
# ============================================================================

SQLAlchemyAccountRepositoryImpl = SQLAlchemyAccountRepository

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AccountHasChildrenError",
    "AccountHasTransactionsError",
    "AccountNotFoundError",
    "AccountRepositoryError",
    "DuplicateAccountCodeError",
    "OptimisticLockError",
    "SQLAlchemyAccountRepository",
    "SQLAlchemyAccountRepositoryImpl",
]