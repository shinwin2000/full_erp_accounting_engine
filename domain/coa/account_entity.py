#!/usr/bin/env python3
# ruff: noqa: UP035, UP006
"""
Module: account_entity.py
Layer: Domain / COA (Chart of Accounts)
Responsibility: Entity untuk akun tunggal dalam Chart of Accounts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar, List
from uuid import UUID, uuid4

from domain.coa.account_code_vo import AccountCodeVO
from domain.coa.account_normal_balance_vo import NormalBalance
from domain.coa.account_type_enum import AccountType

logger = logging.getLogger(__name__)


class AccountStatus(Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    LOCKED = "locked"
    CLOSED = "closed"
    ARCHIVED = "archived"

    def is_active(self) -> bool:
        return self == AccountStatus.ACTIVE

    def can_post(self) -> bool:
        return self == AccountStatus.ACTIVE

    def can_modify(self) -> bool:
        return self in (AccountStatus.DRAFT, AccountStatus.ACTIVE, AccountStatus.SUSPENDED)


@dataclass
class AccountEntity:
    """Entitas akun dengan semua method entity dasar."""

    id: UUID
    legal_entity_id: UUID
    code: AccountCodeVO
    name: str
    account_type: AccountType
    normal_balance: NormalBalance
    parent_id: UUID | None = None
    is_control_account: bool = False
    status: AccountStatus = AccountStatus.DRAFT
    description: str = ""
    opening_balance: Decimal = Decimal(0)
    currency_code: str = "IDR"
    level: int = 0
    is_header: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    updated_by: str = "system"
    version: int = 1
    metadata: dict[str, Any] | None = None

    # Tracking
    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if not self.name or len(self.name.strip()) < 2:
            raise ValueError("Account name must be at least 2 characters")
        if self.opening_balance < 0:
            raise ValueError("Opening balance cannot be negative")
        self.opening_balance = self.opening_balance.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "id": str(self.id),
            "name": self.name,
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "account_id": str(self.id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> AccountEntity:
        self._record_audit("CREATE", created_by, {"code": self.code.code, "name": self.name})
        return self

    def update(self, updated_by: str, **kwargs) -> AccountEntity:
        if not self.status.can_modify():
            raise ValueError(f"Cannot update account in status {self.status.value}")
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("id", "created_at", "created_by", "version"):
                data[key] = value
        new_account = self.from_dict(data)
        new_account.updated_at = datetime.now(UTC)
        new_account.updated_by = updated_by
        new_account.version = self.version + 1
        new_account._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_account

    def delete(self, deleted_by: str, reason: str | None = None) -> AccountEntity:
        if self.status not in (AccountStatus.DRAFT, AccountStatus.ARCHIVED):
            raise ValueError(f"Cannot delete account in status {self.status.value}")
        new_account = self._copy()
        new_account.status = AccountStatus.CLOSED
        new_account.updated_at = datetime.now(UTC)
        new_account.updated_by = deleted_by
        new_account.version = self.version + 1
        new_account._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_account

    def restore(self, restored_by: str) -> AccountEntity:
        if self.status != AccountStatus.CLOSED:
            raise ValueError(f"Cannot restore account in status {self.status.value}")
        new_account = self._copy()
        new_account.status = AccountStatus.DRAFT
        new_account.updated_at = datetime.now(UTC)
        new_account.updated_by = restored_by
        new_account.version = self.version + 1
        new_account._record_audit("RESTORE", restored_by, {})
        return new_account

    def activate(self, activated_by: str) -> AccountEntity:
        if self.status != AccountStatus.DRAFT:
            raise ValueError(f"Cannot activate account in status {self.status.value}")
        new_account = self._copy()
        new_account.status = AccountStatus.ACTIVE
        new_account.updated_at = datetime.now(UTC)
        new_account.updated_by = activated_by
        new_account.version = self.version + 1
        new_account._record_audit("ACTIVATE", activated_by, {})
        return new_account

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> AccountEntity:
        if self.status != AccountStatus.ACTIVE:
            raise ValueError(f"Cannot deactivate account in status {self.status.value}")
        new_account = self._copy()
        new_account.status = AccountStatus.SUSPENDED
        new_account.updated_at = datetime.now(UTC)
        new_account.updated_by = deactivated_by
        new_account.version = self.version + 1
        new_account._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_account

    def lock(self, locked_by: str, reason: str) -> AccountEntity:
        if self.status not in (AccountStatus.ACTIVE, AccountStatus.SUSPENDED):
            raise ValueError(f"Cannot lock account in status {self.status.value}")
        new_account = self._copy()
        new_account.status = AccountStatus.LOCKED
        new_account.updated_at = datetime.now(UTC)
        new_account.updated_by = locked_by
        new_account.version = self.version + 1
        new_account._record_audit("LOCK", locked_by, {"reason": reason})
        return new_account

    def unlock(self, unlocked_by: str) -> AccountEntity:
        if self.status != AccountStatus.LOCKED:
            raise ValueError(f"Cannot unlock account in status {self.status.value}")
        new_account = self._copy()
        new_account.status = AccountStatus.ACTIVE
        new_account.updated_at = datetime.now(UTC)
        new_account.updated_by = unlocked_by
        new_account.version = self.version + 1
        new_account._record_audit("UNLOCK", unlocked_by, {})
        return new_account

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "account_id": str(self.id),
            "version": self.version,
        }

    def to_dict(self, include_metadata: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "code": self.code.code,
            "name": self.name,
            "account_type": self.account_type.value,
            "normal_balance": self.normal_balance.value,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "is_control_account": self.is_control_account,
            "status": self.status.value,
            "description": self.description,
            "opening_balance": str(self.opening_balance),
            "currency_code": self.currency_code,
            "level": self.level,
            "is_header": self.is_header,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
        }
        if include_metadata and self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccountEntity:
        code = AccountCodeVO(data["code"])
        return cls(
            id=UUID(data["id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            code=code,
            name=data["name"],
            account_type=AccountType(data["account_type"]),
            normal_balance=NormalBalance(data["normal_balance"]),
            parent_id=UUID(data["parent_id"]) if data.get("parent_id") else None,
            is_control_account=data.get("is_control_account", False),
            status=AccountStatus(data["status"]),
            description=data.get("description", ""),
            opening_balance=Decimal(data.get("opening_balance", "0")),
            currency_code=data.get("currency_code", "IDR"),
            level=data.get("level", 0),
            is_header=data.get("is_header", False),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            updated_by=data.get("updated_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata"),
        )

    def clone(self, new_code: str | None = None) -> AccountEntity:
        new_id = uuid4()
        new_code_str = new_code or f"{self.code.code}_COPY"
        new_code_vo = AccountCodeVO(new_code_str)
        cloned = AccountEntity(
            id=new_id,
            legal_entity_id=self.legal_entity_id,
            code=new_code_vo,
            name=f"{self.name} (COPY)",
            account_type=self.account_type,
            normal_balance=self.normal_balance,
            parent_id=None,
            is_control_account=self.is_control_account,
            status=AccountStatus.DRAFT,
            description=self.description,
            opening_balance=Decimal(0),
            currency_code=self.currency_code,
            level=0,
            is_header=self.is_header,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=self.created_by,
            version=1,
            metadata=self.metadata.copy() if self.metadata else None,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "account_id": str(self.id),
            "code": self.code.code,
            "name": self.name,
            "status": self.status.value,
            "balance": str(self.opening_balance),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AccountEntity:
        new_account = self._copy()
        new_account.updated_at = datetime.now(UTC)
        new_account.updated_by = touched_by
        new_account.version = self.version + 1
        new_account._record_audit("TOUCH", touched_by, {})
        return new_account

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> AccountEntity:
        return AccountEntity(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            code=self.code,
            name=self.name,
            account_type=self.account_type,
            normal_balance=self.normal_balance,
            parent_id=self.parent_id,
            is_control_account=self.is_control_account,
            status=self.status,
            description=self.description,
            opening_balance=self.opening_balance,
            currency_code=self.currency_code,
            level=self.level,
            is_header=self.is_header,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            updated_by=self.updated_by,
            version=self.version,
            metadata=self.metadata.copy() if self.metadata else None,
        )

    # ==================== ALIAS ====================

    @property
    def account_id(self) -> UUID:
        return self.id

    @property
    def account_code(self) -> str:
        return self.code.code

    @property
    def account_name(self) -> str:
        return self.name

    @property
    def parent_account_id(self) -> UUID | None:
        return self.parent_id

    @property
    def is_active(self) -> bool:
        return self.status == AccountStatus.ACTIVE


Account = AccountEntity


class AccountRepository:
    """Repository interface untuk AccountEntity - implementasi in-memory."""

    _storage: ClassVar[dict[UUID, dict[UUID, AccountEntity]]] = {}

    @classmethod
    def _get_storage(cls, legal_entity_id: UUID) -> dict[UUID, AccountEntity]:
        if legal_entity_id not in cls._storage:
            cls._storage[legal_entity_id] = {}
        return cls._storage[legal_entity_id]

    async def get_by_id(self, account_id: UUID, legal_entity_id: UUID) -> AccountEntity | None:
        storage = self._get_storage(legal_entity_id)
        return storage.get(account_id)

    async def get_by_code(
        self, code: str | AccountCodeVO, legal_entity_id: UUID
    ) -> AccountEntity | None:
        code_str = code.code if isinstance(code, AccountCodeVO) else code
        storage = self._get_storage(legal_entity_id)
        for acc in storage.values():
            if acc.code.code == code_str:
                return acc
        return None

    async def get_all(
        self, legal_entity_id: UUID, include_inactive: bool = False
    ) -> list[AccountEntity]:
        storage = self._get_storage(legal_entity_id)
        if include_inactive:
            return list(storage.values())
        return [acc for acc in storage.values() if acc.is_active]

    async def get_children(self, parent_id: UUID, legal_entity_id: UUID) -> list[AccountEntity]:
        storage = self._get_storage(legal_entity_id)
        return [acc for acc in storage.values() if acc.parent_id == parent_id]

    async def get_descendants(self, parent_id: UUID, legal_entity_id: UUID) -> list[AccountEntity]:
        children = await self.get_children(parent_id, legal_entity_id)
        descendants = []
        for child in children:
            descendants.append(child)
            descendants.extend(await self.get_descendants(child.id, legal_entity_id))
        return descendants

    async def get_root_accounts(self, legal_entity_id: UUID) -> list[AccountEntity]:
        storage = self._get_storage(legal_entity_id)
        return [acc for acc in storage.values() if acc.parent_id is None]

    async def save(self, account: AccountEntity, legal_entity_id: UUID) -> None:
        storage = self._get_storage(legal_entity_id)
        storage[account.id] = account

    async def update(self, account: AccountEntity, legal_entity_id: UUID) -> None:
        await self.save(account, legal_entity_id)

    async def delete(self, account_id: UUID, legal_entity_id: UUID) -> None:
        storage = self._get_storage(legal_entity_id)
        if account_id in storage:
            del storage[account_id]

    async def exists_by_code(self, code: str, legal_entity_id: UUID) -> bool:
        return await self.get_by_code(code, legal_entity_id) is not None

    async def exists(self, account_id: UUID, legal_entity_id: UUID) -> bool:
        storage = self._get_storage(legal_entity_id)
        return account_id in storage

    async def count(self, legal_entity_id: UUID) -> int:
        storage = self._get_storage(legal_entity_id)
        return len(storage)

    async def list(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[AccountEntity]:
        accounts = await self.get_all(legal_entity_id, include_inactive=True)
        return accounts[offset : offset + limit]

    async def paginate(
        self, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[List[AccountEntity], int]:
        accounts = await self.get_all(legal_entity_id, include_inactive=True)
        total = len(accounts)
        start = (page - 1) * per_page
        end = start + per_page
        return accounts[start:end], total

    async def search(
        self, legal_entity_id: UUID, query: str, fields: List[str] | None = None
    ) -> List[AccountEntity]:
        if fields is None:
            fields = ["code", "name", "description"]
        accounts = await self.get_all(legal_entity_id, include_inactive=True)
        query_lower = query.lower()
        results = []
        for acc in accounts:
            for field_name in fields:
                value = getattr(acc, field_name, "")
                if value and query_lower in str(value).lower():
                    results.append(acc)
                    break
        return results

    async def lock(
        self, account_id: UUID, legal_entity_id: UUID, locked_by: str, reason: str
    ) -> AccountEntity:
        acc = await self.get_by_id(account_id, legal_entity_id)
        if not acc:
            raise ValueError(f"Account {account_id} not found")
        locked_acc = acc.lock(locked_by, reason)
        await self.save(locked_acc, legal_entity_id)
        return locked_acc

    async def unlock(
        self, account_id: UUID, legal_entity_id: UUID, unlocked_by: str
    ) -> AccountEntity:
        acc = await self.get_by_id(account_id, legal_entity_id)
        if not acc:
            raise ValueError(f"Account {account_id} not found")
        unlocked_acc = acc.unlock(unlocked_by)
        await self.save(unlocked_acc, legal_entity_id)
        return unlocked_acc


__all__ = [
    "Account",
    "AccountEntity",
    "AccountRepository",
    "AccountStatus",
]
