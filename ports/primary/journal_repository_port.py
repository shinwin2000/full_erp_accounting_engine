#!/usr/bin/env python3
"""
Module: journal_repository_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk repository Journal (Book of Original Entry).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


class JournalStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    POSTED = "posted"
    REVERSED = "reversed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class JournalType(Enum):
    GENERAL = "general"
    ADJUSTING = "adjusting"
    CLOSING = "closing"
    REVERSING = "reversing"
    CORRECTION = "correction"
    OPENING = "opening"


class JournalLine:
    """Baris jurnal (detail debit/kredit)."""
    def __init__(
        self,
        account_id: UUID,
        account_code: str,
        debit_amount: Decimal,
        credit_amount: Decimal,
        description: str | None = None,
        cost_center: str | None = None,
        department_id: UUID | None = None,
        project_id: UUID | None = None,
    ):
        self.account_id = account_id
        self.account_code = account_code
        self.debit_amount = debit_amount
        self.credit_amount = credit_amount
        self.description = description
        self.cost_center = cost_center
        self.department_id = department_id
        self.project_id = project_id


class Journal:
    """Aggregate Journal (dengan nilai default yang sesuai)."""
    def __init__(
        self,
        id: UUID,
        voucher_number: str,
        journal_type: JournalType,
        status: JournalStatus,
        journal_date: date,
        period_id: UUID,
        legal_entity_id: UUID,
        description: str,
        lines: list[JournalLine],
        created_by: UUID,
        created_at: datetime,
        updated_by: UUID,
        updated_at: datetime,
        posting_date: date | None = None,
        total_debit: Decimal = Decimal(0),
        total_credit: Decimal = Decimal(0),
        submitted_by: UUID | None = None,
        submitted_at: datetime | None = None,
        approved_by: UUID | None = None,
        approved_at: datetime | None = None,
        posted_by: UUID | None = None,
        posted_at: datetime | None = None,
        reversed_by: UUID | None = None,
        reversed_at: datetime | None = None,
        reversed_journal_id: UUID | None = None,
        original_journal_id: UUID | None = None,
        cancellation_reason: str | None = None,
        attachment_ids: list[UUID] | None = None,
        version: int = 1,
    ):
        self.id = id
        self.voucher_number = voucher_number
        self.journal_type = journal_type
        self.status = status
        self.journal_date = journal_date
        self.posting_date = posting_date
        self.period_id = period_id
        self.legal_entity_id = legal_entity_id
        self.description = description
        self.lines = lines
        self.total_debit = total_debit
        self.total_credit = total_credit
        self.created_by = created_by
        self.created_at = created_at
        self.updated_by = updated_by
        self.updated_at = updated_at
        self.submitted_by = submitted_by
        self.submitted_at = submitted_at
        self.approved_by = approved_by
        self.approved_at = approved_at
        self.posted_by = posted_by
        self.posted_at = posted_at
        self.reversed_by = reversed_by
        self.reversed_at = reversed_at
        self.reversed_journal_id = reversed_journal_id
        self.original_journal_id = original_journal_id
        self.cancellation_reason = cancellation_reason
        self.attachment_ids = attachment_ids or []
        self.version = version


class JournalRepositoryPort(ABC):
    """
    Port interface untuk repository Journal.
    Semua metode harus diimplementasikan oleh adapter (SQLAlchemy, in-memory, dll).
    """

    # ---------- CRUD ----------
    @abstractmethod
    async def save(self, journal: Journal) -> None:
        """Simpan jurnal (insert atau update)."""
        pass

    @abstractmethod
    async def add(self, journal: Journal) -> None:
        """Tambah jurnal baru."""
        pass

    @abstractmethod
    async def update(self, journal: Journal) -> None:
        """Update jurnal yang sudah ada."""
        pass

    @abstractmethod
    async def delete(self, journal_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """Hapus jurnal (soft atau hard)."""
        pass

    # ---------- Query ----------
    @abstractmethod
    async def get_by_id(self, journal_id: UUID) -> Journal | None:
        """Ambil jurnal berdasarkan ID."""
        pass

    @abstractmethod
    async def get_by_voucher_number(self, voucher_number: str) -> Journal | None:
        """Ambil jurnal berdasarkan nomor voucher."""
        pass

    @abstractmethod
    async def exists_by_voucher_number(self, voucher_number: str) -> bool:
        """Cek apakah nomor voucher sudah digunakan."""
        pass

    @abstractmethod
    async def get_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
        """Ambil semua jurnal dengan paginasi."""
        pass

    @abstractmethod
    async def find_by_status(
        self,
        status: JournalStatus,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Journal]:
        """Cari jurnal berdasarkan status."""
        pass

    @abstractmethod
    async def find_by_period(
        self, period_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
        """Cari jurnal berdasarkan periode."""
        pass

    @abstractmethod
    async def find_by_date_range(
        self,
        start_date: date,
        end_date: date,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Journal]:
        """Cari jurnal dalam rentang tanggal."""
        pass

    @abstractmethod
    async def find_by_account(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Journal]:
        """Cari jurnal yang memiliki line dengan account tertentu."""
        pass

    @abstractmethod
    async def get_pending_approval(self, legal_entity_id: UUID) -> list[Journal]:
        """Ambil jurnal yang menunggu approval."""
        pass

    # ---------- Workflow ----------
    @abstractmethod
    async def submit(self, journal_id: UUID, user_id: UUID) -> bool:
        """Submit jurnal untuk approval."""
        pass

    @abstractmethod
    async def approve(self, journal_id: UUID, approver_id: UUID) -> bool:
        """Setujui jurnal."""
        pass

    @abstractmethod
    async def post(self, journal_id: UUID, user_id: UUID) -> bool:
        """Posting jurnal."""
        pass

    @abstractmethod
    async def reverse(
        self, journal_id: UUID, user_id: UUID, reversal_date: date, reason: str
    ) -> Journal | None:
        """Buat jurnal reversal dan tandai original sebagai reversed."""
        pass

    # ---------- Export / Import ----------
    @abstractmethod
    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        """Ekspor jurnal ke CSV."""
        pass

    @abstractmethod
    async def import_from_csv(
        self, csv_content: str, legal_entity_id: UUID, period_id: UUID, user_id: UUID
    ) -> int:
        """Impor jurnal dari CSV. Mengembalikan jumlah yang berhasil diimpor."""
        pass

    # ---------- Statistics & Audit ----------
    @abstractmethod
    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Statistik jurnal."""
        pass

    @abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Ambil audit log (tanpa filter journal_id)."""
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check repository."""
        pass


__all__ = [
    "Journal",
    "JournalLine",
    "JournalRepositoryPort",
    "JournalStatus",
    "JournalType",
]
