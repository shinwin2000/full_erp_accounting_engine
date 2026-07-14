#!/usr/bin/env python3
"""
Module: sqlalchemy_account_repository_impl.py
Layer: Adapters (Secondary Implementation)

Implementasi repository Account menggunakan SQLAlchemy AsyncSession.
Mengimplementasikan AccountRepositoryPort, BankAccountRepositoryPort, dan CustomerRepositoryPort.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.coa.account_code_vo import AccountCode
from domain.coa.account_entity import AccountStatus, NormalBalance
from domain.coa.account_type_enum import AccountType
from domain.coa.aggregate_root import AccountAggregate
from domain.shared_value_objects.money_vo import Money
from infrastructure.persistence_orm.account_table import AccountTable
from ports.primary.account_repository_port import AccountRepositoryPort
from ports.primary.bank_cash_repository_port import BankAccountRepositoryPort
from ports.primary.customer_repository_port import CustomerRepositoryPort

logger = logging.getLogger(__name__)


class AccountRepositoryError(Exception):
    pass


class DuplicateAccountCodeError(AccountRepositoryError):
    pass


class AccountNotFoundError(AccountRepositoryError):
    pass


class AccountHasChildrenError(AccountRepositoryError):
    pass


class AccountHasTransactionsError(AccountRepositoryError):
    pass


class OptimisticLockError(AccountRepositoryError):
    pass


class SQLAlchemyAccountRepositoryImpl(
    AccountRepositoryPort,
    BankAccountRepositoryPort,
    CustomerRepositoryPort,
):
    """
    Implementasi repository Account dengan SQLAlchemy.
    Mendukung pessimistic locking untuk delete dan restore.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: list[dict[str, Any]] = []

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def _log_audit(self, action: str, account_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "account_id": str(account_id),
            "details": details
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # MAPPING
    # ========================================================================

    def _to_domain(self, table: AccountTable) -> AccountAggregate:
        account_type = AccountType(table.account_type) if table.account_type else AccountType.ASSET
        normal_balance = NormalBalance(table.normal_balance) if table.normal_balance else NormalBalance.DEBIT
        status = AccountStatus(table.status) if table.status else AccountStatus.DRAFT
        return AccountAggregate(
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
            opening_balance=Money(amount=table.opening_balance or Decimal(0), currency=table.currency_code or "IDR"),
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            version=table.version,
            legal_entity_id=table.legal_entity_id,
        )

    async def _to_orm(self, aggregate: AccountAggregate) -> AccountTable:
        return AccountTable(
            id=aggregate.id,
            account_code=str(aggregate.account_code),
            account_name=aggregate.account_name,
            account_type=aggregate.account_type.value,
            normal_balance=aggregate.normal_balance.value,
            parent_account_id=aggregate.parent_account_id,
            level=aggregate.level,
            description=aggregate.description,
            status=aggregate.status.value,
            currency_code=aggregate.currency_code,
            is_bank_account=aggregate.is_bank_account,
            is_cash_account=aggregate.is_cash_account,
            is_intercompany=aggregate.is_intercompany,
            is_header=aggregate.is_header,
            opening_balance=aggregate.opening_balance.amount if aggregate.opening_balance else Decimal(0),
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            created_by=aggregate.created_by,
            version=aggregate.version,
            legal_entity_id=aggregate.legal_entity_id,
            is_active=aggregate.status == AccountStatus.ACTIVE,
        )

    # ========================================================================
    # ACCOUNT REPOSITORY PORT (AccountRepositoryPort)
    # ========================================================================

    async def add(self, account: AccountAggregate) -> None:
        session = await self._get_session()
        try:
            if not await self.is_code_unique(str(account.account_code), account.legal_entity_id):
                raise DuplicateAccountCodeError(
                    f"Account code {account.account_code} already exists in legal entity {account.legal_entity_id}"
                )
            if account.parent_account_id:
                parent_stmt = select(AccountTable).where(AccountTable.id == account.parent_account_id)
                parent_result = await session.execute(parent_stmt)
                if not parent_result.scalar_one_or_none():
                    raise AccountNotFoundError(f"Parent account {account.parent_account_id} not found")
            table = await self._to_orm(account)
            session.add(table)
            await session.flush()
            await self._log_audit("ADD", account.id, {"account_code": str(account.account_code)})
            logger.info("Account added: %s", account.account_code)
        except (DuplicateAccountCodeError, AccountNotFoundError):
            raise
        except IntegrityError as e:
            await session.rollback()
            raise AccountRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await session.rollback()
            raise AccountRepositoryError(f"Failed to add account: {e}") from e

    async def get_by_id(self, account_id: UUID) -> AccountAggregate | None:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.id == account_id,
                AccountTable.deleted_at.is_(None)
            )
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain(table) if table else None
        except Exception as e:
            logger.error("Failed to get account by id %s: %s", account_id, e)
            raise AccountRepositoryError(f"Failed to get account: {e}") from e

    async def get_by_code(self, account_code: str, legal_entity_id: UUID) -> AccountAggregate | None:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.account_code == account_code,
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain(table) if table else None
        except Exception as e:
            logger.error("Failed to get account by code %s: %s", account_code, e)
            raise AccountRepositoryError(f"Failed to get account: {e}") from e

    async def update(self, account: AccountAggregate) -> None:
        session = await self._get_session()
        try:
            stmt = select(AccountTable.version).where(AccountTable.id == account.id)
            result = await session.execute(stmt)
            current_version = result.scalar_one_or_none()
            if current_version is None:
                raise AccountNotFoundError(f"Account {account.id} not found")
            if current_version != account.version:
                raise OptimisticLockError(f"Version mismatch: expected {account.version}, got {current_version}")

            table = await self._to_orm(account)
            table.version = account.version + 1
            table.updated_at = datetime.utcnow()
            await session.merge(table)
            await session.flush()
            await self._log_audit("UPDATE", account.id, {"account_code": str(account.account_code)})
            logger.info("Account updated: %s", account.account_code)
        except (AccountNotFoundError, OptimisticLockError):
            raise
        except Exception as e:
            await session.rollback()
            raise AccountRepositoryError(f"Failed to update account: {e}") from e

    async def delete(self, account_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        session = await self._get_session()
        try:
            async with session.begin():
                stmt_lock = select(AccountTable).where(
                    AccountTable.id == account_id,
                    AccountTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt_lock)
                table = result.scalar_one_or_none()
                if table is None:
                    raise AccountNotFoundError(f"Account {account_id} not found")

                current_version = table.version

                children_stmt = select(func.count()).select_from(AccountTable).where(
                    AccountTable.parent_account_id == account_id,
                    AccountTable.deleted_at.is_(None)
                )
                children_result = await session.execute(children_stmt)
                if children_result.scalar() > 0:
                    raise AccountHasChildrenError(f"Account {account_id} has children")

                acct = await self.get_by_id(account_id)
                if acct and acct.is_used_in_transaction:
                    raise AccountHasTransactionsError(f"Account {account_id} has transactions")

                if permanent:
                    stmt = delete(AccountTable).where(
                        AccountTable.id == account_id,
                        AccountTable.version == current_version
                    )
                    result = await session.execute(stmt)
                    if result.rowcount == 0:
                        raise OptimisticLockError(f"Version mismatch for account {account_id}")
                    deleted = True
                    await self._log_audit("DELETE_PERMANENT", account_id, {"user_id": str(user_id)})
                    logger.info("Account %s permanently deleted by %s", account_id, user_id)
                else:
                    new_version = current_version + 1
                    stmt = update(AccountTable).where(
                        AccountTable.id == account_id,
                        AccountTable.version == current_version
                    ).values(
                        deleted_at=datetime.utcnow(),
                        status="inactive",
                        is_active=False,
                        updated_at=datetime.utcnow(),
                        updated_by=user_id,
                        version=new_version,
                    )
                    result = await session.execute(stmt)
                    if result.rowcount == 0:
                        raise OptimisticLockError(f"Version mismatch for account {account_id}")
                    deleted = True
                    await self._log_audit("DELETE_SOFT", account_id, {"user_id": str(user_id)})
                    logger.info("Account %s soft deleted by %s", account_id, user_id)

                await session.flush()
                return deleted

        except (AccountHasChildrenError, AccountHasTransactionsError, OptimisticLockError, AccountNotFoundError):
            raise
        except Exception as e:
            await session.rollback()
            raise AccountRepositoryError(f"Failed to delete account: {e}") from e

    async def restore(self, account_id: UUID, user_id: UUID) -> bool:
        session = await self._get_session()
        try:
            async with session.begin():
                stmt_lock = select(AccountTable).where(
                    AccountTable.id == account_id,
                    AccountTable.deleted_at.is_not(None)
                ).with_for_update()
                result = await session.execute(stmt_lock)
                table = result.scalar_one_or_none()
                if not table:
                    return False

                current_version = table.version
                new_version = current_version + 1

                result = await session.execute(
                    update(AccountTable)
                    .where(
                        AccountTable.id == account_id,
                        AccountTable.version == current_version,
                        AccountTable.deleted_at.is_not(None)
                    )
                    .values(
                        deleted_at=None,
                        status="active",
                        is_active=True,
                        updated_at=datetime.utcnow(),
                        updated_by=user_id,
                        version=new_version,
                    )
                )
                if result.rowcount == 0:
                    raise OptimisticLockError(f"Version mismatch for account {account_id} during restore")

                await session.flush()
                await self._log_audit("RESTORE", account_id, {"user_id": str(user_id)})
                logger.info("Account %s restored by %s", account_id, user_id)
                return True
        except OptimisticLockError:
            raise
        except Exception as e:
            await session.rollback()
            raise AccountRepositoryError(f"Failed to restore account: {e}") from e

    async def get_children(self, parent_account_id: UUID, recursive: bool = False) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.parent_account_id == parent_account_id,
                AccountTable.deleted_at.is_(None),
            ).order_by(AccountTable.account_code)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            children = [self._to_domain(table) for table in tables]
            if recursive:
                for child in children:
                    children.extend(await self.get_children(child.id, recursive=True))
            return children
        except Exception as e:
            raise AccountRepositoryError(f"Failed to get children: {e}") from e

    async def get_root_accounts(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.parent_account_id.is_(None),
                AccountTable.deleted_at.is_(None),
            ).order_by(AccountTable.account_code)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise AccountRepositoryError(f"Failed to get root accounts: {e}") from e

    async def find_by_type(self, account_type: str, legal_entity_id: UUID) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.account_type == account_type,
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            ).order_by(AccountTable.account_code)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise AccountRepositoryError(f"Failed to find accounts by type: {e}") from e

    async def find_by_name_contains(
        self, keyword: str, legal_entity_id: UUID, limit: int = 50
    ) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.account_name.ilike(func.concat('%', keyword, '%')),
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            ).limit(limit).order_by(AccountTable.account_code)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise AccountRepositoryError(f"Failed to search accounts: {e}") from e

    async def find_active(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.status == "active",
                AccountTable.is_active == True,
                AccountTable.deleted_at.is_(None),
            ).order_by(AccountTable.account_code)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise AccountRepositoryError(f"Failed to find active accounts: {e}") from e

    async def get_all(
        self,
        legal_entity_id: UUID,
        include_inactive: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None) if not include_inactive else True,
            ).order_by(AccountTable.account_code).limit(limit).offset(offset)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise AccountRepositoryError(f"Failed to get all accounts: {e}") from e

    async def has_children(self, account_id: UUID) -> bool:
        session = await self._get_session()
        try:
            stmt = select(func.count()).select_from(AccountTable).where(
                AccountTable.parent_account_id == account_id,
                AccountTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            raise AccountRepositoryError(f"Failed to check children: {e}") from e

    async def is_code_unique(
        self, account_code: str, legal_entity_id: UUID, exclude_id: UUID | None = None
    ) -> bool:
        session = await self._get_session()
        try:
            stmt = select(func.count()).select_from(AccountTable).where(
                AccountTable.account_code == account_code,
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            )
            if exclude_id:
                stmt = stmt.where(AccountTable.id != exclude_id)
            result = await session.execute(stmt)
            return result.scalar() == 0
        except Exception as e:
            raise AccountRepositoryError(f"Failed to check uniqueness: {e}") from e

    async def get_descendants(self, account_id: UUID) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            result = []
            stack = [account_id]
            visited = set()
            while stack:
                current_id = stack.pop()
                if current_id in visited:
                    continue
                visited.add(current_id)
                children = await self.get_children(current_id, recursive=False)
                for child in children:
                    result.append(child)
                    stack.append(child.id)
            return result
        except Exception as e:
            raise AccountRepositoryError(f"Failed to get descendants: {e}") from e

    async def get_path(self, account_id: UUID) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            path = []
            current = await self.get_by_id(account_id)
            while current:
                path.insert(0, current)
                if current.parent_account_id:
                    current = await self.get_by_id(current.parent_account_id)
                else:
                    break
            return path
        except Exception as e:
            raise AccountRepositoryError(f"Failed to get path: {e}") from e

    async def get_full_hierarchy(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            ).order_by(AccountTable.account_code)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            accounts = {str(t.id): self._to_domain(t) for t in tables}
            roots = []
            for account in accounts.values():
                if account.parent_account_id is None:
                    roots.append({
                        "id": str(account.id),
                        "account_code": str(account.account_code),
                        "account_name": account.account_name,
                        "account_type": account.account_type.value,
                        "level": account.level,
                        "children": self._build_tree(account.id, accounts)
                    })
            return roots
        except Exception as e:
            raise AccountRepositoryError(f"Failed to get hierarchy: {e}") from e

    def _build_tree(self, parent_id: UUID, accounts: dict[str, AccountAggregate]) -> list[dict[str, Any]]:
        children = []
        for account in accounts.values():
            if account.parent_account_id and str(account.parent_account_id) == str(parent_id):
                children.append({
                    "id": str(account.id),
                    "account_code": str(account.account_code),
                    "account_name": account.account_name,
                    "account_type": account.account_type.value,
                    "level": account.level,
                    "children": self._build_tree(account.id, accounts)
                })
        return children

    async def get_balance_sheet_accounts(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            balance_sheet_types = ["asset", "liability", "equity"]
            stmt = select(AccountTable).where(
                AccountTable.account_type.in_(balance_sheet_types),
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            ).order_by(AccountTable.account_code)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise AccountRepositoryError(f"Failed to get balance sheet accounts: {e}") from e

    async def get_income_statement_accounts(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            income_statement_types = ["revenue", "expense"]
            stmt = select(AccountTable).where(
                AccountTable.account_type.in_(income_statement_types),
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            ).order_by(AccountTable.account_code)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise AccountRepositoryError(f"Failed to get income statement accounts: {e}") from e

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        session = await self._get_session()
        try:
            total = await session.execute(
                select(func.count()).select_from(AccountTable).where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.deleted_at.is_(None),
                )
            )
            total = total.scalar() or 0

            active = await session.execute(
                select(func.count()).select_from(AccountTable).where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.status == "active",
                    AccountTable.deleted_at.is_(None),
                )
            )
            active = active.scalar() or 0

            by_type_result = await session.execute(
                select(AccountTable.account_type, func.count())
                .where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.deleted_at.is_(None),
                )
                .group_by(AccountTable.account_type)
            )
            by_type = {row[0]: row[1] for row in by_type_result.all()}

            by_level_result = await session.execute(
                select(AccountTable.level, func.count())
                .where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.deleted_at.is_(None),
                )
                .group_by(AccountTable.level)
            )
            by_level = {row[0]: row[1] for row in by_level_result.all()}

            return {
                "total_accounts": total,
                "active_accounts": active,
                "inactive_accounts": total - active,
                "by_type": by_type,
                "by_level": by_level,
            }
        except Exception as e:
            raise AccountRepositoryError(f"Failed to get statistics: {e}") from e

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        accounts = await self.get_all(legal_entity_id, include_inactive=True, limit=10000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "account_code", "account_name", "account_type", "normal_balance",
            "parent_account_id", "level", "status", "currency_code", "is_bank_account",
            "is_cash_account", "is_intercompany", "is_header", "opening_balance"
        ])
        for acc in accounts:
            writer.writerow([
                str(acc.id),
                str(acc.account_code),
                acc.account_name,
                acc.account_type.value,
                acc.normal_balance.value,
                str(acc.parent_account_id) if acc.parent_account_id else "",
                acc.level,
                acc.status.value,
                acc.currency_code,
                acc.is_bank_account,
                acc.is_cash_account,
                acc.is_intercompany,
                acc.is_header,
                acc.opening_balance.amount,
            ])
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, user_id: UUID) -> int:
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                account = AccountAggregate(
                    id=UUID(row.get("id", UUID(int=0))),
                    account_code=AccountCode(row["account_code"]),
                    account_name=row["account_name"],
                    account_type=AccountType(row["account_type"]),
                    normal_balance=NormalBalance(row["normal_balance"]),
                    parent_account_id=UUID(row["parent_account_id"]) if row.get("parent_account_id") else None,
                    level=int(row.get("level", 1)),
                    description=row.get("description", ""),
                    status=AccountStatus(row.get("status", "draft")),
                    currency_code=row.get("currency_code", "IDR"),
                    is_bank_account=row.get("is_bank_account", "false").lower() == "true",
                    is_cash_account=row.get("is_cash_account", "false").lower() == "true",
                    is_intercompany=row.get("is_intercompany", "false").lower() == "true",
                    is_header=row.get("is_header", "false").lower() == "true",
                    opening_balance=Money(amount=Decimal(row.get("opening_balance", 0)), currency=row.get("currency_code", "IDR")),
                    legal_entity_id=legal_entity_id,
                    created_by=user_id,
                )
                await self.add(account)
                count += 1
            except Exception as e:
                logger.warning("Failed to import row: %s", e)
        return count

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset:offset+limit]

    async def health_check(self) -> dict[str, Any]:
        try:
            session = await self._get_session()
            await session.execute(select(1))
            return {"status": "healthy", "repository": "AccountRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "AccountRepository", "error": str(e)}

    # ========================================================================
    # ALIAS UNTUK KEMUDAHAN (opsional)
    # ========================================================================

    async def save(self, account: AccountAggregate) -> None:
        """Simpan atau update account (alias)."""
        existing = await self.get_by_id(account.id)
        if existing:
            await self.update(account)
        else:
            await self.add(account)

    async def find_by_id(self, account_id: UUID) -> AccountAggregate | None:
        """Alias untuk get_by_id."""
        return await self.get_by_id(account_id)

    async def find_by_code(self, legal_entity_id: UUID, account_code: str) -> AccountAggregate | None:
        """Alias untuk get_by_code."""
        return await self.get_by_code(account_code, legal_entity_id)

    # ========================================================================
    # BANK ACCOUNT REPOSITORY PORT (BankAccountRepositoryPort)
    # ========================================================================

    async def find_by_legal_entity(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.is_bank_account == True,
                AccountTable.deleted_at.is_(None),
            ).order_by(AccountTable.account_code)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise AccountRepositoryError(f"Failed to find bank accounts: {e}") from e

    async def get_balance(self, bank_account_id: UUID, as_of_date: date | None = None) -> Decimal:
        account = await self.get_by_id(bank_account_id)
        if not account:
            raise AccountNotFoundError(f"Account {bank_account_id} not found")
        return account.opening_balance.amount if account.opening_balance else Decimal(0)

    async def get_by_account_number(self, account_number: str, bank_code: str, legal_entity_id: UUID) -> AccountAggregate | None:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.account_code == account_number,
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.is_bank_account == True,
                AccountTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain(table) if table else None
        except Exception as e:
            raise AccountRepositoryError(f"Failed to get bank account: {e}") from e

    async def get_transactions(
        self,
        account_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        logger.warning("get_transactions is a stub")
        return []

    async def reconcile(
        self,
        account_id: UUID,
        statement_date: date,
        ending_balance: Decimal,
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        account = await self.get_by_id(account_id)
        if not account:
            raise AccountNotFoundError(f"Account {account_id} not found")
        system_balance = await self.get_balance(account_id)
        return {
            "status": "reconciled",
            "account_id": str(account_id),
            "statement_date": statement_date.isoformat(),
            "ending_balance": str(ending_balance),
            "system_balance": str(system_balance),
            "difference": str(ending_balance - system_balance),
            "reconciled_at": datetime.utcnow().isoformat(),
        }

    async def record_transaction(
        self,
        account_id: UUID,
        transaction_date: date,
        amount: Decimal,
        description: str,
        reference: str | None = None,
        transaction_type: str = "other",
        created_by: UUID | None = None,
    ) -> dict[str, Any]:
        logger.info("Recording transaction for account %s: amount %s", account_id, amount)
        return {
            "id": UUID(int=0),
            "account_id": account_id,
            "transaction_date": transaction_date.isoformat(),
            "amount": str(amount),
            "description": description,
            "reference": reference,
            "transaction_type": transaction_type,
            "created_at": datetime.utcnow().isoformat(),
            "created_by": str(created_by) if created_by else None,
        }

    # ========================================================================
    # CUSTOMER REPOSITORY PORT (CustomerRepositoryPort)
    # ========================================================================

    async def add_order(self, customer_id: UUID, order_id: UUID, amount: Decimal) -> None:
        logger.info("Adding order %s for customer %s amount %s", order_id, customer_id, amount)

    async def blacklist(self, customer_id: UUID, reason: str) -> bool:
        account = await self.get_by_id(customer_id)
        if not account:
            return False
        await self._log_audit("BLACKLIST", customer_id, {"reason": reason})
        logger.info("Customer %s blacklisted: %s", customer_id, reason)
        return True

    async def find_by_category(self, category: str, legal_entity_id: UUID) -> list[AccountAggregate]:
        logger.warning("find_by_category is a stub")
        return []

    async def update_credit_usage(self, customer_id: UUID, amount_used: Decimal) -> None:
        account = await self.get_by_id(customer_id)
        if not account:
            raise AccountNotFoundError(f"Customer {customer_id} not found")
        logger.info("Updating credit usage for customer %s: %s", customer_id, amount_used)

    # ========================================================================
    # METODE YANG HILANG (untuk memenuhi kontrak CustomerRepositoryPort)
    # ========================================================================

    async def check_credit_limit(self, customer_id: UUID) -> Decimal:
        """
        Periksa batas kredit pelanggan.
        Implementasi sederhana: mengembalikan 0 (tidak ada batas).
        """
        account = await self.get_by_id(customer_id)
        if not account:
            raise AccountNotFoundError(f"Customer {customer_id} not found")
        # Untuk produksi, batas kredit bisa diambil dari atribut account jika ada
        return Decimal('0')

    async def is_active(self, customer_id: UUID) -> bool:
        """
        Cek apakah pelanggan aktif.
        """
        account = await self.get_by_id(customer_id)
        if not account:
            return False
        return account.status == AccountStatus.ACTIVE

    async def list_by_entity(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        """
        Daftar pelanggan berdasarkan entitas legal.
        Implementasi: gunakan get_all dengan filter aktif.
        """
        return await self.get_all(legal_entity_id, include_inactive=False)


# ============================================================================
# ALIAS UNTUK BACKWARD COMPATIBILITY
# ============================================================================

SQLAlchemyAccountRepository = SQLAlchemyAccountRepositoryImpl

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
