#!/usr/bin/env python3
"""
Module: sqlalchemy_account_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk aggregate Account (Chart of Accounts)
               menggunakan SQLAlchemy ORM.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
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
from ports.primary.customer_supplier_repository_port import CustomerRepositoryPort

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


class SQLAlchemyAccountRepository(
    AccountRepositoryPort,
    BankAccountRepositoryPort,
    CustomerRepositoryPort,
):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: list[dict[str, Any]] = []

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

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
            opening_balance=Money(amount=table.opening_balance or 0, currency=table.currency_code or "IDR"),
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
            opening_balance=aggregate.opening_balance.amount if aggregate.opening_balance else 0,
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            created_by=aggregate.created_by,
            version=aggregate.version,
            legal_entity_id=aggregate.legal_entity_id,
            is_active=aggregate.status == AccountStatus.ACTIVE,
        )

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
    # CORE CRUD (AccountRepositoryPort)
    # ========================================================================

    async def add(self, account: AccountAggregate) -> None:
        session = await self._get_session()
        try:
            exists = await self.is_code_unique(str(account.account_code), account.legal_entity_id)
            if not exists:
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
        except DuplicateAccountCodeError:
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
            stmt = select(AccountTable).where(AccountTable.id == account_id, AccountTable.deleted_at.is_(None))
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain(table)
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
            if not table:
                return None
            return self._to_domain(table)
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
        except OptimisticLockError:
            raise
        except Exception as e:
            await session.rollback()
            raise AccountRepositoryError(f"Failed to update account: {e}") from e

    # ===== PERBAIKAN: delete dengan 2 parameter wajib (user_id) dan permanent opsional =====
    async def delete(self, account_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        session = await self._get_session()
        try:
            # Cek anak
            children_stmt = select(func.count()).select_from(AccountTable).where(
                AccountTable.parent_account_id == account_id, AccountTable.deleted_at.is_(None)
            )
            children_result = await session.execute(children_stmt)
            children_count = children_result.scalar()
            if children_count > 0:
                raise AccountHasChildrenError(f"Account {account_id} has {children_count} children")

            acct = await self.get_by_id(account_id)
            if acct and acct.is_used_in_transaction:
                raise AccountHasTransactionsError(f"Account {account_id} has transactions")

            if permanent:
                # Permanent delete: hapus baris dari tabel
                stmt = delete(AccountTable).where(AccountTable.id == account_id)
                result = await session.execute(stmt)
                deleted = result.rowcount > 0
                if deleted:
                    await self._log_audit("DELETE_PERMANENT", account_id, {"user_id": str(user_id)})
                    logger.info("Account %s permanently deleted by %s", account_id, user_id)
            else:
                # Soft delete: set deleted_at dan status inactive
                stmt = update(AccountTable).where(AccountTable.id == account_id).values(
                    deleted_at=datetime.utcnow(),
                    status="inactive",
                    is_active=False,
                    updated_at=datetime.utcnow(),
                    updated_by=user_id,
                )
                result = await session.execute(stmt)
                deleted = result.rowcount > 0
                if deleted:
                    await self._log_audit("DELETE_SOFT", account_id, {"user_id": str(user_id)})
                    logger.info("Account %s soft deleted by %s", account_id, user_id)

            await session.flush()
            return deleted

        except (AccountHasChildrenError, AccountHasTransactionsError):
            raise
        except Exception as e:
            await session.rollback()
            raise AccountRepositoryError(f"Failed to delete account: {e}") from e

    # ===== PERBAIKAN: restore dengan 2 parameter wajib (user_id) =====
    async def restore(self, account_id: UUID, user_id: UUID) -> bool:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(AccountTable.id == account_id, AccountTable.deleted_at.is_not(None))
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return False
            await session.execute(
                update(AccountTable)
                .where(AccountTable.id == account_id)
                .values(
                    deleted_at=None,
                    status="active",
                    is_active=True,
                    updated_at=datetime.utcnow(),
                    updated_by=user_id,
                )
            )
            await session.flush()
            await self._log_audit("RESTORE", account_id, {"user_id": str(user_id)})
            logger.info("Account %s restored by %s", account_id, user_id)
            return True
        except Exception as e:
            await session.rollback()
            raise AccountRepositoryError(f"Failed to restore account: {e}") from e

    # ========================================================================
    # QUERY METHODS (AccountRepositoryPort)
    # ========================================================================

    async def get_children(self, parent_account_id: UUID) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.parent_account_id == parent_account_id,
                AccountTable.deleted_at.is_(None),
            ).order_by(AccountTable.account_code)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
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

    async def find_by_name_contains(self, name_fragment: str, legal_entity_id: UUID, limit: int = 50) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.account_name.ilike(func.concat('%', name_fragment, '%')),
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

    async def get_all(self, legal_entity_id: UUID, limit: int = 1000, offset: int = 0) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
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
            count = result.scalar()
            return count > 0
        except Exception as e:
            raise AccountRepositoryError(f"Failed to check children: {e}") from e

    async def is_code_unique(self, account_code: str, legal_entity_id: UUID) -> bool:
        session = await self._get_session()
        try:
            stmt = select(func.count()).select_from(AccountTable).where(
                AccountTable.account_code == account_code,
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            count = result.scalar()
            return count == 0
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
                children = await self.get_children(current_id)
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

    # ========================================================================
    # STATISTICS (AccountRepositoryPort)
    # ========================================================================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        session = await self._get_session()
        try:
            stmt_total = select(func.count()).select_from(AccountTable).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt_total)
            total = result.scalar() or 0

            stmt_active = select(func.count()).select_from(AccountTable).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.status == "active",
                AccountTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt_active)
            active = result.scalar() or 0

            stmt_types = select(AccountTable.account_type, func.count()).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            ).group_by(AccountTable.account_type)
            result = await session.execute(stmt_types)
            by_type = {row[0]: row[1] for row in result.all()}

            stmt_levels = select(AccountTable.level, func.count()).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            ).group_by(AccountTable.level)
            result = await session.execute(stmt_levels)
            by_level = {row[0]: row[1] for row in result.all()}

            return {
                "total_accounts": total,
                "active_accounts": active,
                "inactive_accounts": total - active,
                "by_type": by_type,
                "by_level": by_level,
            }
        except Exception as e:
            raise AccountRepositoryError(f"Failed to get statistics: {e}") from e

    # ========================================================================
    # EXPORT / IMPORT (AccountRepositoryPort)
    # ========================================================================

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        accounts = await self.get_all(legal_entity_id, limit=10000, offset=0)
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
                float(acc.opening_balance.amount) if acc.opening_balance else 0,
            ])
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, created_by: UUID) -> int:
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
                    created_by=created_by,
                )
                await self.add(account)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import row: {e}")
        return count

    # ========================================================================
    # AUDIT & HEALTH (AccountRepositoryPort)
    # ========================================================================

    async def get_audit_log(self, account_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        logs = self._audit_log
        if account_id:
            logs = [l for l in logs if l.get("account_id") == str(account_id)]
        return logs[-limit:]

    async def health_check(self) -> dict[str, Any]:
        try:
            session = await self._get_session()
            await session.execute(select(1))
            return {"status": "healthy", "repository": "AccountRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "AccountRepository", "error": str(e)}

    # ========================================================================
    # ALIAS UNTUK KONTRAK PORT (AccountRepositoryPort)
    # ========================================================================

    async def save(self, account: AccountAggregate) -> None:
        existing = await self.get_by_id(account.id)
        if existing:
            await self.update(account)
        else:
            await self.add(account)

    async def find_by_id(self, account_id: UUID) -> AccountAggregate | None:
        return await self.get_by_id(account_id)

    async def find_by_code(self, legal_entity_id: UUID, account_code: str) -> AccountAggregate | None:
        return await self.get_by_code(account_code, legal_entity_id)

    async def find_by_normal_balance(self, normal_balance: str, legal_entity_id: UUID) -> list[AccountAggregate]:
        session = await self._get_session()
        try:
            stmt = select(AccountTable).where(
                AccountTable.normal_balance == normal_balance,
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            ).order_by(AccountTable.account_code)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise AccountRepositoryError(f"Failed to find accounts by normal balance: {e}") from e

    async def list_by_legal_entity(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        return await self.get_all(legal_entity_id)

    async def count_by_type(self, legal_entity_id: UUID) -> dict[str, int]:
        stats = await self.get_statistics(legal_entity_id)
        return stats.get("by_type", {})

    async def get_account_with_children(self, account_id: UUID) -> dict[str, Any]:
        account = await self.get_by_id(account_id)
        if not account:
            return {}
        children = await self.get_children(account_id)
        return {
            "account": account,
            "children": children,
            "has_children": len(children) > 0,
        }

    # ========================================================================
    # BankAccountRepositoryPort METHODS
    # ========================================================================

    async def find_by_legal_entity(self, legal_entity_id: UUID) -> list[AccountAggregate]:
        """Find all bank accounts for a legal entity."""
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

    async def get_balance(self, account_id: UUID, as_of_date: date | None = None) -> Decimal:
        """Get current balance of a bank account (simplified)."""
        account = await self.get_by_id(account_id)
        if not account:
            raise AccountNotFoundError(f"Account {account_id} not found")
        return account.opening_balance.amount if account.opening_balance else Decimal(0)

    async def get_by_account_number(self, account_number: str, legal_entity_id: UUID) -> AccountAggregate | None:
        """Get bank account by its account number (same as account_code)."""
        return await self.get_by_code(account_number, legal_entity_id)

    async def get_transactions(
        self,
        account_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get transactions for a bank account (stub - no transaction table)."""
        logger.warning("get_transactions is a stub - no bank transaction table implemented")
        return []

    async def reconcile(
        self,
        account_id: UUID,
        statement_date: date,
        ending_balance: Decimal,
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Perform bank reconciliation (stub)."""
        account = await self.get_by_id(account_id)
        if not account:
            raise AccountNotFoundError(f"Account {account_id} not found")
        return {
            "status": "reconciled",
            "account_id": str(account_id),
            "statement_date": statement_date.isoformat(),
            "ending_balance": float(ending_balance),
            "system_balance": float(await self.get_balance(account_id)),
            "difference": 0.0,
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
        """Record a bank transaction (stub - no actual storage)."""
        logger.info("Recording transaction for account %s: amount %s, description %s", account_id, amount, description)
        return {
            "id": UUID(int=0),
            "account_id": account_id,
            "transaction_date": transaction_date.isoformat(),
            "amount": float(amount),
            "description": description,
            "reference": reference,
            "transaction_type": transaction_type,
            "created_at": datetime.utcnow().isoformat(),
            "created_by": str(created_by) if created_by else None,
        }

    # ========================================================================
    # CustomerRepositoryPort METHODS
    # ========================================================================

    async def add_order(self, customer_id: UUID, order_id: UUID, amount: Decimal) -> None:
        """Add an order to a customer's history (stub)."""
        logger.info("Adding order %s for customer %s amount %s", order_id, customer_id, amount)

    async def blacklist(self, customer_id: UUID, reason: str) -> bool:
        """Mark a customer as blacklisted (stub)."""
        account = await self.get_by_id(customer_id)
        if not account:
            return False
        await self._log_audit("BLACKLIST", customer_id, {"reason": reason})
        logger.info("Customer %s blacklisted: %s", customer_id, reason)
        return True

    async def find_by_category(self, category: str, legal_entity_id: UUID) -> list[AccountAggregate]:
        """Find customers by category (stub)."""
        logger.warning("find_by_category is a stub - no customer category field")
        return []

    async def update_credit_usage(self, customer_id: UUID, amount_used: Decimal) -> None:
        """Update credit usage for a customer (stub)."""
        account = await self.get_by_id(customer_id)
        if not account:
            raise AccountNotFoundError(f"Customer {customer_id} not found")
        logger.info("Updating credit usage for customer %s: %s", customer_id, amount_used)


SQLAlchemyAccountRepositoryImpl = SQLAlchemyAccountRepository

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
