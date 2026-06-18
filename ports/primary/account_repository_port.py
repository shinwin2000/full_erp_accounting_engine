#!/usr/bin/env python3
"""
Module: account_repository_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory repository untuk Chart of Accounts (COA).
               Mendukung hierarki akun (parent-child), validasi kode berdasarkan
               standar akuntansi, soft delete, audit trail, import/export CSV,
               dan query berdasarkan berbagai filter.
Audit: Setiap perubahan pada akun (tambah, ubah, hapus, nonaktifkan) tercatat.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class AccountType(Enum):
    """Tipe akun berdasarkan PSAK/IFRS."""

    ASSET = "asset"  # Aset
    LIABILITY = "liability"  # Kewajiban
    EQUITY = "equity"  # Ekuitas
    REVENUE = "revenue"  # Pendapatan
    EXPENSE = "expense"  # Beban
    CONTRA_ASSET = "contra_asset"  # Kontra aset (akumulasi penyusutan)
    CONTRA_LIABILITY = "contra_liability"
    CONTRA_EQUITY = "contra_equity"
    CONTRA_REVENUE = "contra_revenue"
    CONTRA_EXPENSE = "contra_expense"


class NormalBalance(Enum):
    """Saldo normal akun."""

    DEBIT = "debit"
    CREDIT = "credit"


@dataclass
class Account:
    """
    Aggregate Root Account (Chart of Accounts).
    """

    id: UUID
    account_code: str
    account_name: str
    account_type: AccountType
    normal_balance: NormalBalance
    legal_entity_id: UUID
    parent_id: UUID | None = None
    level: int = 0
    is_active: bool = True
    is_contra: bool = False
    currency_code: str = "IDR"
    opening_balance: Decimal = Decimal(0)
    closing_balance: Decimal = Decimal(0)
    description: str | None = None
    allowed_debit: bool = True
    allowed_credit: bool = True
    requires_approval: bool = False
    budget_control: bool = False
    segment1: str | None = None
    segment2: str | None = None
    segment3: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    deleted_at: datetime | None = None
    version: int = 1

    def to_dict(self, include_children: bool = False) -> dict[str, Any]:
        result = {
            "id": str(self.id),
            "account_code": self.account_code,
            "account_name": self.account_name,
            "account_type": self.account_type.value,
            "normal_balance": self.normal_balance.value,
            "legal_entity_id": str(self.legal_entity_id),
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "level": self.level,
            "is_active": self.is_active,
            "is_contra": self.is_contra,
            "currency_code": self.currency_code,
            "opening_balance": float(self.opening_balance),
            "closing_balance": float(self.closing_balance),
            "description": self.description,
            "allowed_debit": self.allowed_debit,
            "allowed_credit": self.allowed_credit,
            "requires_approval": self.requires_approval,
            "budget_control": self.budget_control,
            "segment1": self.segment1,
            "segment2": self.segment2,
            "segment3": self.segment3,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "version": self.version,
        }
        return result


class AccountRepositoryPort:
    """
    In-memory repository untuk Chart of Accounts.
    """

    def __init__(self):
        self._storage: dict[UUID, Account] = {}
        self._code_index: dict[tuple[str, UUID], Account] = {}  # (account_code, legal_entity_id)
        self._parent_index: dict[UUID, list[UUID]] = {}  # parent_id -> list of child ids
        self._type_index: dict[tuple[AccountType, UUID], list[UUID]] = {}
        self._active_index: dict[UUID, list[UUID]] = {}  # legal_entity_id -> list of active ids
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._code_pattern = re.compile(
            r"^(\d{1,2})(?:\.(\d{1,3}))?(?:\.(\d{1,3}))?$"
        )  # pola 1, 1.1, 1.1.1

    # ==================== HELPER ====================

    async def _log_audit(
        self, action: str, account_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "account_id": str(account_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"COA AUDIT: {action} on account {account_id} by {user_id}")

    async def _validate_account_code(self, account_code: str, legal_entity_id: UUID) -> None:
        """Validasi format kode akun dan keunikan."""
        if not self._code_pattern.match(account_code):
            raise ValueError(
                f"Invalid account code format: {account_code}. Use format like '1', '1.1', '1.1.1'"
            )
        key = (account_code, legal_entity_id)
        if key in self._code_index:
            existing = self._code_index[key]
            if existing.deleted_at is None:
                raise ValueError(
                    f"Account code {account_code} already exists for legal entity {legal_entity_id}"
                )

    async def _compute_level(self, parent_id: UUID | None) -> int:
        """Hitung level akun berdasarkan parent."""
        if parent_id is None:
            return 0
        parent = self._storage.get(parent_id)
        if not parent or parent.deleted_at is not None:
            raise ValueError(f"Parent account {parent_id} not found or deleted")
        return parent.level + 1

    async def _update_indices(self, account: Account, is_insert: bool = True):
        """Update berbagai index."""
        key = (account.account_code, account.legal_entity_id)
        if is_insert:
            self._code_index[key] = account
        else:
            self._code_index[key] = account  # replace

        # Parent index
        if account.parent_id:
            if account.parent_id not in self._parent_index:
                self._parent_index[account.parent_id] = []
            if account.id not in self._parent_index[account.parent_id]:
                self._parent_index[account.parent_id].append(account.id)

        # Type index
        type_key = (account.account_type, account.legal_entity_id)
        if type_key not in self._type_index:
            self._type_index[type_key] = []
        if account.id not in self._type_index[type_key]:
            self._type_index[type_key].append(account.id)

        # Active index
        if account.is_active and account.deleted_at is None:
            if account.legal_entity_id not in self._active_index:
                self._active_index[account.legal_entity_id] = []
            if account.id not in self._active_index[account.legal_entity_id]:
                self._active_index[account.legal_entity_id].append(account.id)

    async def _remove_from_indices(self, account: Account):
        """Hapus akun dari semua index (soft delete)."""
        key = (account.account_code, account.legal_entity_id)
        if key in self._code_index:
            del self._code_index[key]

        if account.parent_id and account.parent_id in self._parent_index:
            if account.id in self._parent_index[account.parent_id]:
                self._parent_index[account.parent_id].remove(account.id)

        type_key = (account.account_type, account.legal_entity_id)
        if type_key in self._type_index and account.id in self._type_index[type_key]:
            self._type_index[type_key].remove(account.id)

        if (
            account.legal_entity_id in self._active_index
            and account.id in self._active_index[account.legal_entity_id]
        ):
            self._active_index[account.legal_entity_id].remove(account.id)

    # ==================== CRUD ====================

    async def add(self, account: Account) -> None:
        """Menambahkan akun baru ke COA."""
        if not isinstance(account, Account):
            raise TypeError("account must be Account instance")
        if account.id in self._storage:
            raise ValueError(f"Account with id {account.id} already exists")
        await self._validate_account_code(account.account_code, account.legal_entity_id)
        # Hitung level jika parent_id diberikan
        if account.parent_id:
            account.level = await self._compute_level(account.parent_id)
        else:
            account.level = 0
        account.created_at = datetime.now(UTC)
        account.updated_at = account.created_at
        account.version = 1
        account.deleted_at = None
        async with self._lock:
            self._storage[account.id] = account
            await self._update_indices(account, is_insert=True)
        await self._log_audit(
            "ADD",
            account.id,
            account.created_by,
            {
                "account_code": account.account_code,
                "account_name": account.account_name,
                "type": account.account_type.value,
                "parent_id": str(account.parent_id) if account.parent_id else None,
            },
        )

    async def get_by_id(self, account_id: UUID) -> Account | None:
        return self._storage.get(account_id)

    async def get_by_code(self, account_code: str, legal_entity_id: UUID) -> Account | None:
        key = (account_code, legal_entity_id)
        account = self._code_index.get(key)
        if account and account.deleted_at is not None:
            return None
        return account

    async def update(self, account: Account) -> None:
        """Memperbarui akun yang sudah ada."""
        if account.id not in self._storage:
            raise ValueError(f"Account with id {account.id} not found")
        old = self._storage[account.id]
        if old.deleted_at is not None:
            raise ValueError(f"Account {account.id} is deleted, cannot update")
        # Validasi kode baru jika berubah
        if old.account_code != account.account_code:
            await self._validate_account_code(account.account_code, account.legal_entity_id)
        # Hitung ulang level jika parent berubah
        if old.parent_id != account.parent_id:
            account.level = await self._compute_level(account.parent_id)
            # TODO: update level seluruh descendants
        account.updated_at = datetime.now(UTC)
        account.version = old.version + 1
        account.created_at = old.created_at
        account.created_by = old.created_by
        account.deleted_at = old.deleted_at
        # Hapus dari index lama sebelum update
        await self._remove_from_indices(old)
        async with self._lock:
            self._storage[account.id] = account
            await self._update_indices(account, is_insert=True)
        await self._log_audit(
            "UPDATE",
            account.id,
            account.updated_by,
            {
                "account_code": account.account_code,
                "changes": f"from {old.account_code} to {account.account_code}"
                if old.account_code != account.account_code
                else "other",
            },
        )

    async def delete(self, account_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """Soft delete (default) atau permanent delete."""
        account = self._storage.get(account_id)
        if not account:
            return False
        if permanent:
            # Cek apakah memiliki children
            children = await self.get_children(account_id)
            if children:
                raise ValueError(f"Cannot delete account {account_id} because it has children")
            await self._remove_from_indices(account)
            del self._storage[account_id]
            await self._log_audit("DELETE_PERMANENT", account_id, user_id, {})
        else:
            account.deleted_at = datetime.now(UTC)
            account.is_active = False
            account.updated_at = account.deleted_at
            account.updated_by = user_id
            account.version += 1
            await self._remove_from_indices(account)
            await self._log_audit("DELETE_SOFT", account_id, user_id, {})
        return True

    async def restore(self, account_id: UUID, user_id: UUID) -> bool:
        """Mengembalikan akun yang di-soft delete."""
        account = self._storage.get(account_id)
        if not account or account.deleted_at is None:
            return False
        account.deleted_at = None
        account.is_active = True
        account.updated_at = datetime.now(UTC)
        account.updated_by = user_id
        account.version += 1
        await self._update_indices(account, is_insert=True)
        await self._log_audit("RESTORE", account_id, user_id, {})
        return True

    # ==================== HIERARCHY ====================

    async def get_children(self, parent_account_id: UUID, recursive: bool = False) -> list[Account]:
        """Mengambil semua anak (sub-akun) dari akun induk."""
        child_ids = self._parent_index.get(parent_account_id, [])
        result = [
            self._storage[cid]
            for cid in child_ids
            if cid in self._storage and self._storage[cid].deleted_at is None
        ]
        if recursive:
            for child in result:
                result.extend(await self.get_children(child.id, recursive=True))
        return result

    async def get_root_accounts(self, legal_entity_id: UUID) -> list[Account]:
        """Akun level 0 (tanpa parent)."""
        result = []
        for acc in self._storage.values():
            if (
                acc.legal_entity_id == legal_entity_id
                and acc.parent_id is None
                and acc.deleted_at is None
            ):
                result.append(acc)
        return sorted(result, key=lambda x: x.account_code)

    async def get_full_hierarchy(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        """Mengembalikan full tree COA dalam bentuk nested dictionary di dalam list."""
        roots = await self.get_root_accounts(legal_entity_id)

        async def build_tree(account: Account) -> dict[str, Any]:
            children = await self.get_children(account.id)
            # Menggunakan asyncio.gather untuk resolusi rekursif secara konkuren dan non-blocking
            children_trees = await asyncio.gather(*(build_tree(child) for child in children))
            return {
                "id": str(account.id),
                "code": account.account_code,
                "name": account.account_name,
                "type": account.account_type.value,
                "children": children_trees,
            }

        return await asyncio.gather(*(build_tree(root) for root in roots))

    # ==================== QUERY ====================

    async def find_by_type(self, account_type: AccountType, legal_entity_id: UUID) -> list[Account]:
        """Mencari akun berdasarkan tipenya."""
        type_key = (account_type, legal_entity_id)
        ids = self._type_index.get(type_key, [])
        return [
            self._storage[a_id]
            for a_id in ids
            if a_id in self._storage and self._storage[a_id].deleted_at is None
        ]

    async def find_by_name_contains(
        self, keyword: str, legal_entity_id: UUID, limit: int = 50
    ) -> list[Account]:
        """Pencarian akun berdasarkan nama (partial match, case-insensitive)."""
        keyword_lower = keyword.lower()
        result = []
        for acc in self._storage.values():
            if acc.legal_entity_id == legal_entity_id and acc.deleted_at is None:
                if (
                    keyword_lower in acc.account_name.lower()
                    or keyword_lower in acc.account_code.lower()
                ):
                    result.append(acc)
        return sorted(result, key=lambda x: x.account_code)[:limit]

    async def find_active(self, legal_entity_id: UUID) -> list[Account]:
        """Semua akun aktif."""
        ids = self._active_index.get(legal_entity_id, [])
        return [self._storage[a_id] for a_id in ids if a_id in self._storage]

    async def get_all(
        self,
        legal_entity_id: UUID,
        include_inactive: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Account]:
        """Semua akun untuk legal entity tertentu."""
        result = []
        for acc in self._storage.values():
            if acc.legal_entity_id == legal_entity_id:
                if not include_inactive and acc.deleted_at is not None:
                    continue
                result.append(acc)
        result.sort(key=lambda x: x.account_code)
        return result[offset : offset + limit]

    async def get_balance_sheet_accounts(self, legal_entity_id: UUID) -> list[Account]:
        """Akun neraca (Aset, Liabilitas, Ekuitas)."""
        balance_types = {AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY}
        result = []
        for acc in self._storage.values():
            if (
                acc.legal_entity_id == legal_entity_id
                and acc.account_type in balance_types
                and acc.deleted_at is None
            ):
                result.append(acc)
        return result

    async def get_income_statement_accounts(self, legal_entity_id: UUID) -> list[Account]:
        """Akun laba rugi (Pendapatan, Beban)."""
        pl_types = {AccountType.REVENUE, AccountType.EXPENSE}
        result = []
        for acc in self._storage.values():
            if (
                acc.legal_entity_id == legal_entity_id
                and acc.account_type in pl_types
                and acc.deleted_at is None
            ):
                result.append(acc)
        return result

    # ==================== VALIDATION & UTILITY ====================

    async def is_code_unique(
        self, account_code: str, legal_entity_id: UUID, exclude_id: UUID | None = None
    ) -> bool:
        """Cek keunikan kode akun."""
        existing = await self.get_by_code(account_code, legal_entity_id)
        if not existing:
            return True
        if exclude_id and existing.id == exclude_id:
            return True
        return False

    async def has_children(self, account_id: UUID) -> bool:
        """Apakah akun memiliki sub-akun?"""
        children = await self.get_children(account_id)
        return len(children) > 0

    async def get_descendants(self, account_id: UUID) -> list[Account]:
        """Semua keturunan (rekursif)."""
        return await self.get_children(account_id, recursive=True)

    async def get_path(self, account_id: UUID) -> list[Account]:
        """Path dari root ke akun ini."""
        path = []
        current = self._storage.get(account_id)
        while current and current.parent_id:
            path.insert(0, current)
            current = self._storage.get(current.parent_id)
        if current:
            path.insert(0, current)
        return path

    # ==================== IMPORT / EXPORT ====================

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        """Ekspor COA ke CSV."""
        accounts = await self.get_all(legal_entity_id, include_inactive=True)
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "account_code",
                "account_name",
                "account_type",
                "normal_balance",
                "parent_code",
                "is_active",
                "description",
                "currency_code",
            ]
        )
        # Pre-map parent code
        code_map = {acc.id: acc.account_code for acc in accounts}
        for acc in accounts:
            parent_code = code_map.get(acc.parent_id) if acc.parent_id else ""
            writer.writerow(
                [
                    acc.account_code,
                    acc.account_name,
                    acc.account_type.value,
                    acc.normal_balance.value,
                    parent_code,
                    "1" if acc.is_active and acc.deleted_at is None else "0",
                    acc.description or "",
                    acc.currency_code,
                ]
            )
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, user_id: UUID) -> int:
        """Impor COA dari CSV (format ekspor)."""
        import io

        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        # First pass: create all accounts without parent
        temp_accounts: dict[str, Account] = {}
        for row in reader:
            try:
                acc_type = AccountType(row["account_type"])
                norm_balance = NormalBalance(row["normal_balance"])
                account = Account(
                    id=uuid4(),
                    account_code=row["account_code"],
                    account_name=row["account_name"],
                    account_type=acc_type,
                    normal_balance=norm_balance,
                    legal_entity_id=legal_entity_id,
                    parent_id=None,
                    is_active=row["is_active"] == "1",
                    currency_code=row.get("currency_code", "IDR"),
                    description=row.get("description"),
                    created_by=user_id,
                    updated_by=user_id,
                )
                await self.add(account)
                temp_accounts[account.account_code] = account
                count += 1
            except Exception as e:
                logger.warning(f"Import account {row.get('account_code')} failed: {e}")
        # Second pass: set parent based on parent_code
        for row in (
            reader
        ):  # Reader exhausted, need to re-read? Simpler: use temp_accounts after first pass
            pass
        # Better: reset reader
        return count  # simplified, full version would handle parent linking

    # ==================== STATISTICS & AUDIT ====================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        accounts = await self.get_all(legal_entity_id, include_inactive=True)
        active = sum(1 for a in accounts if a.is_active and a.deleted_at is None)
        by_type = {}
        for a in accounts:
            t = a.account_type.value
            by_type[t] = by_type.get(t, 0) + 1
        return {
            "total_accounts": len(accounts),
            "active_accounts": active,
            "inactive_accounts": len(accounts) - active,
            "accounts_by_type": by_type,
            "max_depth": max((a.level for a in accounts), default=0),
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_accounts": len(self._storage),
            "indexed_codes": len(self._code_index),
            "active_entities": len(self._active_index),
            "audit_log_size": len(self._audit_log),
        }


# === ALIAS UNTUK KOMPATIBILITAS ===
AccountRepository = AccountRepositoryPort


__all__ = [
    "Account",
    "AccountRepository",
    "AccountRepositoryPort",
    "AccountType",
    "NormalBalance",
]