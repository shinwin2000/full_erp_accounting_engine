# service_coa.py - Complete rewrite with fixes (adding missing imports)

#!/usr/bin/env python3

"""
Module: service_coa.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer untuk Chart of Accounts (COA).
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

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
    AccountCreated,
    AccountDeactivated,
    AccountReactivated,
    AccountUpdated,
)
from domain.coa.invariants_validator import COAInvariantsValidator
from ports.primary.account_repository_port import AccountRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


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


# ============================================================================
# Main Service
# ============================================================================


class COAService:
    """
    Service untuk Chart of Accounts (COA).
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

    async def create_account(
        self, request: CreateAccountRequest, user_id: UUID, correlation_id: str | None = None
    ) -> AccountResponse:
        """Create a new account."""
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
            event = AccountCreated(
                aggregate_id=account.id,
                legal_entity_id=account.legal_entity_id,
                account_code=account.account_code.value,
                account_name=account.name,
                account_type=account.account_type.value,
                parent_account_id=account.parent_account_id,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return self._to_response(account)

    async def update_account(
        self,
        account_id: UUID,
        request: UpdateAccountRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> AccountResponse:
        """Update existing account."""
        aggregate = await self._account_repo.get_by_id(account_id)
        if not aggregate:
            raise AccountNotFoundError(f"Account {account_id} not found")

        account = aggregate.account
        changes_made = False

        if request.name is not None and request.name != account.name:
            aggregate.rename_account(request.name, user_id)
            changes_made = True

        if request.description is not None and request.description != account.description:
            aggregate.update_description(request.description, user_id)
            changes_made = True

        if request.parent_account_id is not None:
            new_parent_id = request.parent_account_id
            if new_parent_id != account.parent_account_id:
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
            aggregate.update_opening_balance(request.opening_balance, user_id)
            changes_made = True

        if not changes_made:
            return self._to_response(account)

        await self._account_repo.save(aggregate)
        await self._uow.commit()

        await self._invalidate_cache()
        self._stats["accounts_updated"] += 1

        if self._event_publisher:
            event = AccountUpdated(
                aggregate_id=account.id,
                legal_entity_id=account.legal_entity_id,
                account_code=account.account_code.value,
                changes=request.to_dict(),
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return self._to_response(aggregate.account)

    async def deactivate_account(
        self,
        account_id: UUID,
        user_id: UUID,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> AccountResponse:
        """Deactivate (soft delete) an account."""
        aggregate = await self._account_repo.get_by_id(account_id)
        if not aggregate:
            raise AccountNotFoundError(f"Account {account_id} not found")

        account = aggregate.account

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
            event = AccountDeactivated(
                aggregate_id=account.id,
                legal_entity_id=account.legal_entity_id,
                account_code=account.account_code.value,
                reason=reason,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return self._to_response(aggregate.account)

    async def reactivate_account(
        self, account_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> AccountResponse:
        """Reactivate a deactivated account."""
        aggregate = await self._account_repo.get_by_id(account_id)
        if not aggregate:
            raise AccountNotFoundError(f"Account {account_id} not found")

        aggregate.reactivate(user_id)

        await self._account_repo.save(aggregate)
        await self._uow.commit()

        await self._invalidate_cache()

        if self._event_publisher:
            event = AccountReactivated(
                aggregate_id=account.id,
                legal_entity_id=account.legal_entity_id,
                account_code=account.account_code.value,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return self._to_response(aggregate.account)

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

    async def list_accounts(
        self,
        legal_entity_id: UUID,
        account_type: str | None = None,
        status: str | None = None,
        parent_id: UUID | None = None,
        include_children: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AccountResponse]:
        accounts = await self._account_repo.list(
            legal_entity_id=legal_entity_id,
            account_type=account_type,
            status=status,
            parent_id=parent_id,
            limit=limit,
            offset=offset,
        )

        result = []
        for acc in accounts:
            result.append(self._to_response(acc))
            if include_children and acc.id:
                children = await self._account_repo.find_children(acc.id)
                for child in children:
                    result.append(self._to_response(child))

        return result

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

    async def bulk_import_accounts(
        self,
        legal_entity_id: UUID,
        csv_content: str,
        user_id: UUID,
        correlation_id: str | None = None,
        dry_run: bool = False,
    ) -> BulkImportResultDTO:
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

            return BulkImportResultDTO(
                total_rows=success_count + failure_count,
                success_count=success_count,
                failure_count=failure_count,
                failures=failures[:100],
                created_accounts=created_accounts,
            )

        except Exception as e:
            raise InvalidBulkImportDataError(f"Failed to parse CSV: {e}")

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
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


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
    "AccountNotFoundError",
    "COAService",
    "COAServiceError",
    "InvalidAccountTypeHierarchyError",
    "InvalidBulkImportDataError",
    "InvalidParentAccountError",
    "create_coa_service",
]
