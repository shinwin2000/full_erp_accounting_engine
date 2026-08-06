#!/usr/bin/env python3
"""
Module: budget_repository_port.py
Layer: Ports / Primary
Responsibility:
    - Mendefinisikan antarmuka (port) untuk repository budget.
    - Mendefinisikan entitas BudgetEntity dengan tipe moneter Decimal.
    - Menyediakan Protocol untuk structural typing.

Changelog:
    - v2.0.0: Pisahkan implementasi InMemory ke adapters/; gunakan Decimal untuk moneter.
    - v1.0.0: Port awal dengan float (sekarang ditinggalkan).
"""

from __future__ import annotations

import abc
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

# ==================== DOMAIN ENTITY (PORT-LEVEL) ====================


class BudgetLineEntity:
    """
    Representasi entitas Budget Line di level port.
    Semua nilai moneter menggunakan Decimal untuk presisi akuntansi.
    """

    def __init__(
        self,
        id: UUID,
        account_id: UUID,
        account_code: str,
        amount: Decimal,
        note: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ):
        self.id = id
        self.account_id = account_id
        self.account_code = account_code
        self.amount = amount
        self.note = note
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "amount": str(self.amount),
            "note": self.note,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BudgetLineEntity":
        return cls(
            id=UUID(data["id"]),
            account_id=UUID(data["account_id"]),
            account_code=data["account_code"],
            amount=Decimal(data["amount"]),
            note=data.get("note"),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else None,
        )


class BudgetEntity:
    """
    Representasi entitas Budget di level port.
    Semua nilai moneter menggunakan Decimal untuk presisi akuntansi.
    """

    def __init__(
        self,
        id: UUID,
        legal_entity_id: UUID,
        budget_code: str,
        budget_name: str,
        budget_type: str,
        fiscal_year: int,
        period: str,
        version: str,
        status: str,
        effective_date: datetime.date,
        expiry_date: datetime.date | None,
        currency: str,
        total_amount: Decimal,
        notes: str | None = None,
        tags: list[str] | None = None,
        is_locked: bool = False,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        created_by: UUID | None = None,
        updated_by: UUID | None = None,
        approved_at: datetime | None = None,
        approved_by: UUID | None = None,
        submitted_at: datetime | None = None,
        submitted_by: UUID | None = None,
        rejected_at: datetime | None = None,
        rejected_by: UUID | None = None,
        rejection_reason: str | None = None,
        version_number: int = 1,
        lines: list[BudgetLineEntity] | None = None,
    ):
        self.id = id
        self.legal_entity_id = legal_entity_id
        self.budget_code = budget_code
        self.budget_name = budget_name
        self.budget_type = budget_type
        self.fiscal_year = fiscal_year
        self.period = period
        self.version = version
        self.status = status
        self.effective_date = effective_date
        self.expiry_date = expiry_date
        self.currency = currency
        self.total_amount = total_amount
        self.notes = notes
        self.tags = tags or []
        self.is_locked = is_locked
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        self.created_by = created_by
        self.updated_by = updated_by
        self.approved_at = approved_at
        self.approved_by = approved_by
        self.submitted_at = submitted_at
        self.submitted_by = submitted_by
        self.rejected_at = rejected_at
        self.rejected_by = rejected_by
        self.rejection_reason = rejection_reason
        self.version_number = version_number
        self.lines = lines or []

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "budget_code": self.budget_code,
            "budget_name": self.budget_name,
            "budget_type": self.budget_type,
            "fiscal_year": self.fiscal_year,
            "period": self.period,
            "version": self.version,
            "status": self.status,
            "effective_date": self.effective_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "currency": self.currency,
            "total_amount": str(self.total_amount),
            "notes": self.notes,
            "tags": self.tags.copy() if self.tags else [],
            "is_locked": self.is_locked,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "submitted_by": str(self.submitted_by) if self.submitted_by else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejected_by": str(self.rejected_by) if self.rejected_by else None,
            "rejection_reason": self.rejection_reason,
            "version_number": self.version_number,
            "lines": [line.to_dict() for line in self.lines],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BudgetEntity":
        lines = [BudgetLineEntity.from_dict(line_data) for line_data in data.get("lines", [])]
        return cls(
            id=UUID(data["id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            budget_code=data["budget_code"],
            budget_name=data["budget_name"],
            budget_type=data["budget_type"],
            fiscal_year=data["fiscal_year"],
            period=data["period"],
            version=data["version"],
            status=data["status"],
            effective_date=datetime.date.fromisoformat(data["effective_date"]),
            expiry_date=datetime.date.fromisoformat(data["expiry_date"]) if data.get("expiry_date") else None,
            currency=data["currency"],
            total_amount=Decimal(data["total_amount"]),
            notes=data.get("notes"),
            tags=data.get("tags", []),
            is_locked=data.get("is_locked", False),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else None,
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            updated_by=UUID(data["updated_by"]) if data.get("updated_by") else None,
            approved_at=datetime.fromisoformat(data["approved_at"]) if data.get("approved_at") else None,
            approved_by=UUID(data["approved_by"]) if data.get("approved_by") else None,
            submitted_at=datetime.fromisoformat(data["submitted_at"]) if data.get("submitted_at") else None,
            submitted_by=UUID(data["submitted_by"]) if data.get("submitted_by") else None,
            rejected_at=datetime.fromisoformat(data["rejected_at"]) if data.get("rejected_at") else None,
            rejected_by=UUID(data["rejected_by"]) if data.get("rejected_by") else None,
            rejection_reason=data.get("rejection_reason"),
            version_number=data.get("version_number", 1),
            lines=lines,
        )


# ==================== PORT (INTERFACE) ====================


class BudgetRepositoryPort(abc.ABC):
    """Port untuk penyimpanan data budget."""

    @abc.abstractmethod
    async def save(self, budget: BudgetEntity) -> None:
        """Simpan budget baru."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update(self, budget: BudgetEntity) -> None:
        """Perbarui budget yang sudah ada."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_id(self, budget_id: UUID) -> BudgetEntity | None:
        """Ambil budget berdasarkan ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_code_and_year(
        self, legal_entity_id: UUID, budget_code: str, fiscal_year: int
    ) -> BudgetEntity | None:
        """Ambil budget berdasarkan kode dan tahun fiskal."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_name_and_year(
        self, legal_entity_id: UUID, budget_name: str, fiscal_year: int
    ) -> BudgetEntity | None:
        """Ambil budget berdasarkan nama dan tahun fiskal."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, fiscal_year: int | None = None, status: str | None = None
    ) -> list[BudgetEntity]:
        """Daftar budget untuk entitas legal."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_budget_code(self, legal_entity_id: UUID) -> str | None:
        """Dapatkan kode budget terakhir yang digunakan."""
        raise NotImplementedError

    @abc.abstractmethod
    async def delete(self, budget_id: UUID) -> bool:
        """Hapus budget (soft delete)."""
        raise NotImplementedError


class BudgetRepositoryPortProtocol(Protocol):
    """Protokol untuk structural typing (duck typing)."""

    async def save(self, budget: BudgetEntity) -> None: ...
    async def update(self, budget: BudgetEntity) -> None: ...
    async def get_by_id(self, budget_id: UUID) -> BudgetEntity | None: ...
    async def get_by_code_and_year(
        self, legal_entity_id: UUID, budget_code: str, fiscal_year: int
    ) -> BudgetEntity | None: ...
    async def get_by_name_and_year(
        self, legal_entity_id: UUID, budget_name: str, fiscal_year: int
    ) -> BudgetEntity | None: ...
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, fiscal_year: int | None = None, status: str | None = None
    ) -> list[BudgetEntity]: ...
    async def get_last_budget_code(self, legal_entity_id: UUID) -> str | None: ...
    async def delete(self, budget_id: UUID) -> bool: ...


# ==================== EKSPOR ====================

__all__ = [
    "BudgetEntity",
    "BudgetLineEntity",
    "BudgetRepositoryPort",
    "BudgetRepositoryPortProtocol",
]