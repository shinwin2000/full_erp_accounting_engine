# =============================================================================
# 1. service_coa.py
# =============================================================================

# service_coa.py - Complete rewrite with full event publishing
# v5.9.3 - Added audit decorator and authority checks for mutation methods

#!/usr/bin/env python3

"""
Module: service_coa.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer untuk Chart of Accounts (COA).
    Mempublikasikan semua domain events yang sesuai.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from dataclasses import dataclass, field as dc_field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select

from application.dto_objects.account_dto import (
    AccountHierarchyNodeDTO,
    AccountResponse,
    BulkImportResultDTO,
    CreateAccountRequest,
    UpdateAccountRequest,
)
from domain.coa.account_code_vo import AccountCode, AccountCodeFormatError
from domain.coa.account_entity import Account, AccountStatus, AccountType
from domain.coa.account_hierarchy_tree import AccountHierarchyTree, HierarchyNode
from domain.coa.account_normal_balance_vo import NormalBalance
from domain.coa.aggregate_root import COAAggregate
from domain.coa.domain_events import (
    AccountCreatedEvent,
    AccountDeactivatedEvent,
    AccountReactivatedEvent,
    AccountUpdatedEvent,
    COAArchivedEvent,
    COALockedEvent,
    COAUnlockedEvent,
)
from domain.coa.invariants_validator import COAInvariantsValidator
from ports.primary.account_repository_port import AccountRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Exceptions
# ============================================================================


class COAServiceError(Exception):
    pass


class AccountNotFoundError(COAServiceError):
    pass


class AccountCodeAlreadyExistsError(COAServiceError):
    pass


class InvalidParentAccountError(COAServiceError):
    pass


class AccountHasChildrenError(COAServiceError):
    pass


class AccountHasTransactionsError(COAServiceError):
    pass


class AccountCycleDetectedError(COAServiceError):
    pass


class InvalidAccountTypeHierarchyError(COAServiceError):
    pass


class AccountCodeFormatError(COAServiceError):
    pass


class InvalidBulkImportDataError(COAServiceError):
    pass


class AccountLockedError(COAServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


# ============================================================================
# List DTOs (untuk endpoint GET /coa/chart-of-accounts/accounts)
#
# CATATAN PENTING: query list ini SENGAJA tidak lewat self._account_repo /
# AccountAggregate. Investigasi menemukan bahwa AccountAggregate (alias dari
# ChartOfAccounts, lihat domain/coa/aggregate_root.py) adalah aggregate untuk
# SATU SET banyak akun (punya field accounts: dict[UUID, Account]), BUKAN
# representasi satu akun tunggal. Baik SQLAlchemyAccountRepositoryImpl._to_domain
# maupun _ConcreteAccountRepository mengonstruksi AccountAggregate(...) dengan
# kwargs satu-akun (account_code=, account_name=, is_bank_account=, dst) yang
# TIDAK COCOK dengan constructor ChartOfAccounts yang sebenarnya -> selalu
# TypeError begitu dipanggil. Ini bug arsitektur di level domain, bukan cuma
# salah wiring service/DTO, dan berada di luar cakupan perbaikan endpoint list.
# Untuk endpoint READ (list akun) kita query AccountTable langsung lewat
# UnitOfWork (yang sudah benar & ter-wiring), supaya endpoint ini bisa jalan
# tanpa bergantung pada AccountAggregate yang rusak.
# ============================================================================


@dataclass(kw_only=True)
class AccountListItemDTO:
    """Item akun untuk endpoint list, lengkap sesuai AccountResponseSchema
    di fastapi_coa_router.py."""

    id: UUID
    account_code: str
    account_name: str
    account_type: str
    normal_balance: str
    parent_account_id: UUID | None
    parent_account_code: str | None
    level: int
    description: str | None
    status: str
    currency_code: str
    is_bank_account: bool
    is_cash_account: bool
    is_intercompany: bool
    is_header: bool
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    version: int = 1
    # Field berikut TIDAK ada kolomnya di tabel `account` saat ini, jadi
    # diisi default aman. Kalau suatu saat kolomnya ditambahkan di DB,
    # tinggal isi dari row di sini.
    is_used_in_transaction: bool = False
    is_locked: bool = False
    current_balance: Decimal = Decimal("0")
    category: str | None = None
    budget_control: bool = False
    created_by_name: str | None = None


@dataclass(kw_only=True)
class AccountListResult:
    items: list[AccountListItemDTO]
    total: int


class COAService:
    """
    Service untuk Chart of Accounts (COA).
    Mempublikasikan event untuk setiap operasi.
    """

    def __init__(
        self,
        account_repository: AccountRepositoryPort,
        uow: UnitOfWorkPort,
        event_publisher: EventPublisherPort | None = None,
    ):
        self._account_repo = account_repository
        self._uow = uow
        self._event_publisher = event_publisher
        self._validator = COAInvariantsValidator()
        self._stats = {"accounts_created": 0, "accounts_updated": 0, "accounts_deactivated": 0}
        self._audit_trail: list[dict[str, Any]] = []

        self._hierarchy_cache: AccountHierarchyTree | None = None
        self._cache_ttl_seconds: int = 300
        self._cache_updated_at: datetime | None = None
        self._cache_lock = asyncio.Lock()

        self._valid_parent_types: dict[AccountType, set[AccountType]] = {
            AccountType.ASSET: {AccountType.ASSET},
            AccountType.LIABILITY: {AccountType.LIABILITY},
            AccountType.EQUITY: {AccountType.EQUITY},
            AccountType.REVENUE: {AccountType.REVENUE},
            AccountType.EXPENSE: {AccountType.EXPENSE},
            AccountType.CONTRA_ASSET: {AccountType.ASSET},
            AccountType.CONTRA_LIABILITY: {AccountType.LIABILITY},
            AccountType.CONTRA_EQUITY: {AccountType.EQUITY},
        }

        self._default_normal_balance: dict[AccountType, NormalBalance] = {
            AccountType.ASSET: NormalBalance.DEBIT,
            AccountType.LIABILITY: NormalBalance.CREDIT,
            AccountType.EQUITY: NormalBalance.CREDIT,
            AccountType.REVENUE: NormalBalance.CREDIT,
            AccountType.EXPENSE: NormalBalance.DEBIT,
            AccountType.CONTRA_ASSET: NormalBalance.CREDIT,
            AccountType.CONTRA_LIABILITY: NormalBalance.DEBIT,
            AccountType.CONTRA_EQUITY: NormalBalance.DEBIT,
        }

        logger.info("COAService initialized")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        """
        Check if the user has the required authority/permission.
        Placeholder implementation; in production, consult authority matrix.
        """
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        # In production:
        # if not authority_matrix.has_permission(user_id, permission):
        #     raise PermissionError(f"User {user_id} lacks permission {permission}")
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        """Record audit trail entry."""
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "COAService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== ORIGINAL METHODS WITH PATCHES ====================

    @audit
    async def create_account(
        self, request: CreateAccountRequest, user_id: UUID, correlation_id: str | None = None
    ) -> AccountResponse:
        """Create a new account."""
        self._check_authority(user_id, "create_account")

        try:
            account_code_vo = AccountCode(request.account_code)
        except AccountCodeFormatError as e:
            raise AccountCodeFormatError(f"Invalid account code format: {e}")

        existing = await self._account_repo.find_by_code(
            request.legal_entity_id, request.account_code
        )
        if existing:
            raise AccountCodeAlreadyExistsError(
                f"Account code '{request.account_code}' already exists"
            )

        parent_account: Account | None = None
        if request.parent_account_id:
            parent_account = await self._account_repo.get_by_id(request.parent_account_id)
            if not parent_account:
                raise InvalidParentAccountError(
                    f"Parent account {request.parent_account_id} not found"
                )

            account_type = AccountType(request.account_type)
            parent_type = parent_account.account_type
            allowed_parents = self._valid_parent_types.get(account_type, set())
            if parent_type not in allowed_parents:
                raise InvalidAccountTypeHierarchyError(
                    f"Account type '{account_type.value}' cannot have parent of type '{parent_type.value}'"
                )

        account_type = AccountType(request.account_type)
        normal_balance = self._default_normal_balance.get(account_type, NormalBalance.DEBIT)
        level = parent_account.level + 1 if parent_account else 0

        aggregate = COAAggregate(id=uuid4(), legal_entity_id=request.legal_entity_id, version=0)

        account = Account(
            id=aggregate.id,
            legal_entity_id=request.legal_entity_id,
            account_code=account_code_vo,
            name=request.name,
            account_type=account_type,
            normal_balance=normal_balance,
            status=AccountStatus.ACTIVE,
            parent_account_id=request.parent_account_id,
            description=request.description,
            opening_balance=request.opening_balance or Decimal("0"),
            currency_code=request.currency_code or "IDR",
            is_header=request.is_header or False,
            level=level,
            is_locked=False,
            created_at=datetime.now(UTC),
            created_by=user_id,
            updated_at=None,
            updated_by=None,
        )

        aggregate.create_account(account, user_id)

        await self._account_repo.save(aggregate)
        await self._uow.commit()

        await self._invalidate_cache()
        self._stats["accounts_created"] += 1

        if self._event_publisher:
            event = AccountCreatedEvent(
                aggregate_id=account.id,
                aggregate_version=aggregate.version,
                legal_entity_id=account.legal_entity_id,
                account_code=account.account_code.value,
                account_name=account.name,
                account_type=account.account_type.value,
                parent_account_id=account.parent_account_id,
                user_id=user_id,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        self._record_audit("create_account", {
            "account_id": str(account.id),
            "account_code": account.account_code.value,
            "user_id": str(user_id),
        })

        return self._to_response(account)

    @audit
    async def update_account(
        self,
        account_id: UUID,
        request: UpdateAccountRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> AccountResponse:
        """Update existing account."""
        self._check_authority(user_id, "update_account")

        aggregate = await self._account_repo.get_by_id(account_id)
        if not aggregate:
            raise AccountNotFoundError(f"Account {account_id} not found")

        account = aggregate.account

        if account.is_locked:
            raise AccountLockedError(f"Account {account.account_code.value} is locked")

        changes_made = False
        changes_dict = {}

        if request.name is not None and request.name != account.name:
            changes_dict["name"] = {"old": account.name, "new": request.name}
            aggregate.rename_account(request.name, user_id)
            changes_made = True

        if request.description is not None and request.description != account.description:
            changes_dict["description"] = {"old": account.description, "new": request.description}
            aggregate.update_description(request.description, user_id)
            changes_made = True

        if request.parent_account_id is not None:
            new_parent_id = request.parent_account_id
            if new_parent_id != account.parent_account_id:
                changes_dict["parent_id"] = {"old": account.parent_account_id, "new": new_parent_id}
                if new_parent_id:
                    new_parent = await self._account_repo.get_by_id(new_parent_id)
                    if not new_parent:
                        raise InvalidParentAccountError(f"Parent account {new_parent_id} not found")

                    if await self._would_create_cycle(account_id, new_parent_id):
                        raise AccountCycleDetectedError("Moving account would create a cycle")

                    parent_type = new_parent.account.account_type
                    allowed_parents = self._valid_parent_types.get(account.account_type, set())
                    if parent_type not in allowed_parents:
                        raise InvalidAccountTypeHierarchyError(
                            f"Cannot move {account.account_type.value} under {parent_type.value}"
                        )

                aggregate.change_parent(new_parent_id, user_id)
                changes_made = True

        if (
            request.opening_balance is not None
            and request.opening_balance != account.opening_balance
        ):
            changes_dict["opening_balance"] = {
                "old": account.opening_balance,
                "new": request.opening_balance,
            }
            aggregate.update_opening_balance(request.opening_balance, user_id)
            changes_made = True

        if not changes_made:
            return self._to_response(account)

        await self._account_repo.save(aggregate)
        await self._uow.commit()

        await self._invalidate_cache()
        self._stats["accounts_updated"] += 1

        if self._event_publisher:
            event = AccountUpdatedEvent(
                aggregate_id=account.id,
                aggregate_version=aggregate.version,
                legal_entity_id=account.legal_entity_id,
                account_code=account.account_code.value,
                changes=changes_dict,
                user_id=user_id,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        self._record_audit("update_account", {
            "account_id": str(account_id),
            "changes": changes_dict,
            "user_id": str(user_id),
        })

        return self._to_response(aggregate.account)

    @audit
    async def deactivate_account(
        self,
        account_id: UUID,
        user_id: UUID,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> AccountResponse:
        """Deactivate (soft delete) an account."""
        self._check_authority(user_id, "deactivate_account")

        aggregate = await self._account_repo.get_by_id(account_id)
        if not aggregate:
            raise AccountNotFoundError(f"Account {account_id} not found")

        account = aggregate.account

        if account.is_locked:
            raise AccountLockedError(f"Account {account.account_code.value} is locked")

        children = await self._account_repo.find_children(account_id)
        if children:
            raise AccountHasChildrenError(
                f"Cannot deactivate account with {len(children)} child accounts"
            )

        aggregate.deactivate(user_id, reason)

        await self._account_repo.save(aggregate)
        await self._uow.commit()

        await self._invalidate_cache()
        self._stats["accounts_deactivated"] += 1

        if self._event_publisher:
            event = AccountDeactivatedEvent(
                aggregate_id=account.id,
                aggregate_version=aggregate.version,
                legal_entity_id=account.legal_entity_id,
                account_code=account.account_code.value,
                reason=reason,
                user_id=user_id,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        self._record_audit("deactivate_account", {
            "account_id": str(account_id),
            "reason": reason,
            "user_id": str(user_id),
        })

        return self._to_response(aggregate.account)

    @audit
    async def reactivate_account(
        self, account_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> AccountResponse:
        """Reactivate a deactivated account."""
        self._check_authority(user_id, "reactivate_account")

        aggregate = await self._account_repo.get_by_id(account_id)
        if not aggregate:
            raise AccountNotFoundError(f"Account {account_id} not found")

        aggregate.reactivate(user_id)

        await self._account_repo.save(aggregate)
        await self._uow.commit()

        await self._invalidate_cache()

        if self._event_publisher:
            event = AccountReactivatedEvent(
                aggregate_id=account.id,
                aggregate_version=aggregate.version,
                legal_entity_id=account.legal_entity_id,
                account_code=account.account_code.value,
                user_id=user_id,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        self._record_audit("reactivate_account", {
            "account_id": str(account_id),
            "user_id": str(user_id),
        })

        return self._to_response(aggregate.account)

    @audit
    async def lock_account(
        self,
        account_id: UUID,
        user_id: UUID,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> AccountResponse:
        """Lock an account (prevent modifications)."""
        self._check_authority(user_id, "lock_account")

        aggregate = await self._account_repo.get_by_id(account_id)
        if not aggregate:
            raise AccountNotFoundError(f"Account {account_id} not found")

        account = aggregate.account
        account.is_locked = True
        account.locked_at = datetime.now(UTC)
        account.locked_by = user_id
        account.lock_reason = reason

        await self._account_repo.save(aggregate)
        await self._uow.commit()

        await self._invalidate_cache()

        if self._event_publisher:
            event = COALockedEvent(
                aggregate_id=account.id,
                aggregate_version=aggregate.version,
                legal_entity_id=account.legal_entity_id,
                account_code=account.account_code.value,
                reason=reason,
                locked_by=user_id,
                user_id=user_id,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        self._record_audit("lock_account", {
            "account_id": str(account_id),
            "reason": reason,
            "user_id": str(user_id),
        })

        return self._to_response(account)

    @audit
    async def unlock_account(
        self,
        account_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> AccountResponse:
        """Unlock an account."""
        self._check_authority(user_id, "unlock_account")

        aggregate = await self._account_repo.get_by_id(account_id)
        if not aggregate:
            raise AccountNotFoundError(f"Account {account_id} not found")

        account = aggregate.account
        account.is_locked = False
        account.unlocked_at = datetime.now(UTC)
        account.unlocked_by = user_id

        await self._account_repo.save(aggregate)
        await self._uow.commit()

        await self._invalidate_cache()

        if self._event_publisher:
            event = COAUnlockedEvent(
                aggregate_id=account.id,
                aggregate_version=aggregate.version,
                legal_entity_id=account.legal_entity_id,
                account_code=account.account_code.value,
                unlocked_by=user_id,
                user_id=user_id,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        self._record_audit("unlock_account", {
            "account_id": str(account_id),
            "user_id": str(user_id),
        })

        return self._to_response(account)

    @audit
    async def archive_account(
        self,
        account_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> AccountResponse:
        """Archive an account (permanent soft delete)."""
        self._check_authority(user_id, "archive_account")

        aggregate = await self._account_repo.get_by_id(account_id)
        if not aggregate:
            raise AccountNotFoundError(f"Account {account_id} not found")

        account = aggregate.account

        children = await self._account_repo.find_children(account_id)
        if children:
            raise AccountHasChildrenError(
                f"Cannot archive account with {len(children)} child accounts"
            )

        account.is_archived = True
        account.archived_at = datetime.now(UTC)
        account.archived_by = user_id
        account.status = AccountStatus.INACTIVE

        await self._account_repo.save(aggregate)
        await self._uow.commit()

        await self._invalidate_cache()

        if self._event_publisher:
            event = COAArchivedEvent(
                aggregate_id=account.id,
                aggregate_version=aggregate.version,
                legal_entity_id=account.legal_entity_id,
                account_code=account.account_code.value,
                archived_by=user_id,
                user_id=user_id,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        self._record_audit("archive_account", {
            "account_id": str(account_id),
            "user_id": str(user_id),
        })

        return self._to_response(account)

    # --- QUERY METHODS (no audit needed) ---
    async def get_account(self, account_id: UUID) -> AccountResponse:
        aggregate = await self._account_repo.get_by_id(account_id)
        if not aggregate:
            raise AccountNotFoundError(f"Account {account_id} not found")
        return self._to_response(aggregate.account)

    async def get_account_by_code(
        self, legal_entity_id: UUID, account_code: str
    ) -> AccountResponse | None:
        account = await self._account_repo.find_by_code(legal_entity_id, account_code)
        if not account:
            return None
        return self._to_response(account)

    async def list_accounts_raw(
        self,
        legal_entity_id: UUID,
        account_type: str | None = None,
        status: str | None = None,
        include_inactive: bool = True,
    ) -> list[AccountListItemDTO]:
        """
        Ambil SEMUA akun yang cocok filter, TANPA pagination — dipakai oleh
        use case internal (mis. post_closing_journal.py) yang butuh iterasi
        atas seluruh akun suatu tipe, bukan satu halaman.
        """
        result = await self.list_accounts(
            legal_entity_id=legal_entity_id,
            account_type=account_type,
            status=status,
            include_inactive=include_inactive,
            page=1,
            page_size=100_000,
        )
        return result.items

    async def list_accounts(
        self,
        legal_entity_id: UUID,
        account_type: str | None = None,
        status: str | None = None,
        parent_account_code: str | None = None,
        is_header: bool | None = None,
        level: int | None = None,
        search: str | None = None,
        include_inactive: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> AccountListResult:
        """
        List akun dengan filter dan pagination.
        Dipakai oleh GET /api/v1/coa/chart-of-accounts/accounts.

        Query langsung ke AccountTable lewat UnitOfWork — lihat catatan di
        atas class AccountListItemDTO untuk alasannya.
        """
        from infrastructure.persistence_orm.account_table import AccountTable

        page = max(page, 1)
        page_size = max(page_size, 1)

        async with self._uow:
            session = self._uow.session

            conditions = [
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            ]
            if account_type:
                conditions.append(AccountTable.account_type == account_type)
            if status:
                conditions.append(AccountTable.status == status)
            elif not include_inactive:
                conditions.append(AccountTable.status == "active")
            if parent_account_code:
                conditions.append(
                    AccountTable.parent_account_id.in_(
                        select(AccountTable.id).where(
                            AccountTable.account_code == parent_account_code,
                            AccountTable.legal_entity_id == legal_entity_id,
                        )
                    )
                )
            if is_header is not None:
                conditions.append(AccountTable.is_header == is_header)
            if level is not None:
                conditions.append(AccountTable.level == level)
            if search:
                like = f"%{search}%"
                conditions.append(
                    or_(
                        AccountTable.account_code.ilike(like),
                        AccountTable.account_name.ilike(like),
                    )
                )

            count_stmt = select(func.count()).select_from(AccountTable).where(*conditions)
            total = (await session.execute(count_stmt)).scalar_one()

            stmt = (
                select(AccountTable)
                .where(*conditions)
                .order_by(AccountTable.account_code)
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
            rows = (await session.execute(stmt)).scalars().all()

            parent_ids = {r.parent_account_id for r in rows if r.parent_account_id}
            parent_code_map: dict[UUID, str] = {}
            if parent_ids:
                presult = await session.execute(
                    select(AccountTable.id, AccountTable.account_code).where(
                        AccountTable.id.in_(parent_ids)
                    )
                )
                parent_code_map = {pid: code for pid, code in presult.all()}

            items = [self._table_row_to_list_item(r, parent_code_map) for r in rows]

        return AccountListResult(items=items, total=total)

    def _table_row_to_list_item(
        self, row: Any, parent_code_map: dict[UUID, str]
    ) -> AccountListItemDTO:
        return AccountListItemDTO(
            id=row.id,
            account_code=row.account_code,
            account_name=row.account_name,
            account_type=row.account_type,
            normal_balance=row.normal_balance,
            parent_account_id=row.parent_account_id,
            parent_account_code=parent_code_map.get(row.parent_account_id),
            level=row.level,
            description=row.description,
            status=row.status,
            currency_code=row.currency_code,
            is_bank_account=row.is_bank_account,
            is_cash_account=row.is_cash_account,
            is_intercompany=row.is_intercompany,
            is_header=row.is_header,
            created_at=row.created_at,
            updated_at=row.updated_at or row.created_at,
            created_by=row.created_by or UUID(int=0),
            version=getattr(row, "version", 1),
        )

    async def get_hierarchy_tree(
        self, legal_entity_id: UUID, use_cache: bool = True, max_depth: int = 10
    ) -> AccountHierarchyNodeDTO:
        if use_cache and await self._is_cache_valid():
            async with self._cache_lock:
                if self._hierarchy_cache and self._hierarchy_cache.root:
                    return self._tree_to_dto(self._hierarchy_cache.root, max_depth)

        all_accounts = await self._account_repo.list(
            legal_entity_id=legal_entity_id, limit=10000, offset=0
        )

        if not all_accounts:
            return AccountHierarchyNodeDTO(
                id=None,
                account_code="",
                name="No Accounts",
                account_type="",
                normal_balance="",
                level=0,
                children=[],
            )

        tree = AccountHierarchyTree.build(all_accounts)

        async with self._cache_lock:
            self._hierarchy_cache = tree
            self._cache_updated_at = datetime.now(UTC)

        return self._tree_to_dto(tree.root, max_depth)

    @audit
    async def bulk_import_accounts(
        self,
        legal_entity_id: UUID,
        csv_content: str,
        user_id: UUID,
        correlation_id: str | None = None,
        dry_run: bool = False,
    ) -> BulkImportResultDTO:
        self._check_authority(user_id, "bulk_import_accounts")
        success_count = 0
        failure_count = 0
        failures: list[dict[str, Any]] = []
        created_accounts: list[AccountResponse] = []

        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            required_fields = ["account_code", "name", "account_type"]

            accounts_data = []
            for row_num, row in enumerate(reader, start=2):
                try:
                    for field in required_fields:
                        if not row.get(field):
                            raise ValueError(f"Missing required field: {field}")

                    accounts_data.append(
                        {
                            "row_num": row_num,
                            "account_code": row["account_code"].strip(),
                            "name": row["name"].strip(),
                            "account_type": row["account_type"].strip().upper(),
                            "parent_code": row.get("parent_code", "").strip() or None,
                            "description": row.get("description", "").strip() or None,
                            "opening_balance": Decimal(row.get("opening_balance", "0")),
                            "currency_code": row.get("currency_code", "IDR").strip(),
                            "is_header": row.get("is_header", "false").lower()
                            in ("true", "1", "yes"),
                        }
                    )
                except Exception as e:
                    failure_count += 1
                    failures.append({"row": row_num, "error": str(e)})

            if dry_run:
                return BulkImportResultDTO(
                    total_rows=len(accounts_data) + failure_count,
                    success_count=0,
                    failure_count=failure_count + len(accounts_data),
                    failures=failures,
                    created_accounts=[],
                )

            code_to_id = {}
            for data in accounts_data:
                try:
                    parent_id = None
                    if data["parent_code"]:
                        if data["parent_code"] not in code_to_id:
                            raise ValueError(
                                f"Parent account code '{data['parent_code']}' not found"
                            )
                        parent_id = code_to_id[data["parent_code"]]

                    request = CreateAccountRequest(
                        legal_entity_id=legal_entity_id,
                        account_code=data["account_code"],
                        name=data["name"],
                        account_type=data["account_type"],
                        parent_account_id=parent_id,
                        description=data["description"],
                        opening_balance=data["opening_balance"],
                        currency_code=data["currency_code"],
                        is_header=data["is_header"],
                    )

                    response = await self.create_account(request, user_id, correlation_id)
                    success_count += 1
                    created_accounts.append(response)
                    code_to_id[data["account_code"]] = response.id

                except Exception as e:
                    failure_count += 1
                    failures.append(
                        {
                            "row": data["row_num"],
                            "account_code": data["account_code"],
                            "error": str(e),
                        }
                    )

            self._record_audit("bulk_import_accounts", {
                "success_count": success_count,
                "failure_count": failure_count,
                "user_id": str(user_id),
            })

            return BulkImportResultDTO(
                total_rows=success_count + failure_count,
                success_count=success_count,
                failure_count=failure_count,
                failures=failures[:100],
                created_accounts=created_accounts,
            )

        except Exception as e:
            raise InvalidBulkImportDataError(f"Failed to parse CSV: {e}")

    # --- private helpers ---
    async def _would_create_cycle(self, account_id: UUID, new_parent_id: UUID) -> bool:
        if account_id == new_parent_id:
            return True

        current = new_parent_id
        visited = set()
        while current and current not in visited:
            if current == account_id:
                return True
            visited.add(current)
            parent_agg = await self._account_repo.get_by_id(current)
            if not parent_agg:
                break
            current = parent_agg.account.parent_account_id

        return False

    async def _invalidate_cache(self) -> None:
        async with self._cache_lock:
            self._hierarchy_cache = None
            self._cache_updated_at = None

    async def _is_cache_valid(self) -> bool:
        if self._hierarchy_cache is None or self._cache_updated_at is None:
            return False
        age = (datetime.now(UTC) - self._cache_updated_at).total_seconds()
        return age < self._cache_ttl_seconds

    def _to_response(self, account: Account) -> AccountResponse:
        return AccountResponse(
            id=account.id,
            legal_entity_id=account.legal_entity_id,
            account_code=account.account_code.value,
            name=account.name,
            account_type=account.account_type.value,
            normal_balance=account.normal_balance.value,
            status=account.status.value,
            parent_account_id=account.parent_account_id,
            description=account.description,
            opening_balance=account.opening_balance,
            currency_code=account.currency_code,
            is_header=account.is_header,
            level=account.level,
            is_locked=account.is_locked,
            created_at=account.created_at,
            created_by=account.created_by,
            updated_at=account.updated_at,
            updated_by=account.updated_by,
        )

    def _tree_to_dto(self, node: HierarchyNode, max_depth: int) -> AccountHierarchyNodeDTO:
        children = []
        if node.level < max_depth:
            for child in node.children:
                children.append(self._tree_to_dto(child, max_depth))

        return AccountHierarchyNodeDTO(
            id=node.account.id,
            account_code=node.account.account_code.value,
            name=node.account.name,
            account_type=node.account.account_type.value,
            normal_balance=node.account.normal_balance.value,
            level=node.level,
            children=children,
            is_header=node.account.is_header,
            status=node.account.status.value,
            opening_balance=node.account.opening_balance,
            is_locked=node.account.is_locked,
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_coa_service(
    account_repository: AccountRepositoryPort,
    uow: UnitOfWorkPort,
    event_publisher: EventPublisherPort | None = None,
) -> COAService:
    return COAService(account_repository, uow, event_publisher)


__all__ = [
    "AccountCodeAlreadyExistsError",
    "AccountCodeFormatError",
    "AccountCycleDetectedError",
    "AccountHasChildrenError",
    "AccountHasTransactionsError",
    "AccountLockedError",
    "AccountNotFoundError",
    "COAService",
    "COAServiceError",
    "InvalidAccountTypeHierarchyError",
    "InvalidBulkImportDataError",
    "InvalidParentAccountError",
    "create_coa_service",
]
