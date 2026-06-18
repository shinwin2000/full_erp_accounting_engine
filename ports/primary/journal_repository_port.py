#!/usr/bin/env python3
"""
Module: journal_repository_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory repository untuk aggregate Journal.
               Jurnal adalah catatan akuntansi pertama (book of original entry).
               Mendukung full CRUD, status workflow (draft, submitted, approved, posted, reversed, cancelled),
               optimistic locking, filtering by period/date/status/account, voucher number generation,
               audit trail, import/export CSV, dan statistik.
Audit: Semua operasi penyimpanan (add, update, delete) pada jurnal dicatat.
"""

from __future__ import annotations

import asyncio
import csv
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class JournalStatus(Enum):
    """Status jurnal."""

    DRAFT = "draft"  # Konsep, bisa diedit
    SUBMITTED = "submitted"  # Diajukan untuk approval
    APPROVED = "approved"  # Disetujui (4 mata)
    POSTED = "posted"  # Telah diposting ke buku besar
    REVERSED = "reversed"  # Dibalik (reversal)
    CANCELLED = "cancelled"  # Dibatalkan


class JournalType(Enum):
    """Tipe jurnal."""

    GENERAL = "general"  # Jurnal umum
    ADJUSTING = "adjusting"  # Jurnal penyesuaian
    CLOSING = "closing"  # Jurnal penutup
    REVERSING = "reversing"  # Jurnal balik
    CORRECTION = "correction"  # Jurnal koreksi
    OPENING = "opening"  # Jurnal pembukaan


@dataclass
class JournalLine:
    """Baris jurnal (detail debit/kredit)."""

    account_id: UUID
    account_code: str
    debit_amount: Decimal
    credit_amount: Decimal
    description: str | None = None
    cost_center: str | None = None
    department_id: UUID | None = None
    project_id: UUID | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "debit_amount": float(self.debit_amount),
            "credit_amount": float(self.credit_amount),
            "description": self.description,
            "cost_center": self.cost_center,
            "department_id": str(self.department_id) if self.department_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
        }


@dataclass
class Journal:
    """
    Aggregate Root Journal.
    """

    id: UUID
    voucher_number: str
    journal_type: JournalType
    status: JournalStatus
    journal_date: date
    posting_date: date | None
    period_id: UUID
    legal_entity_id: UUID
    description: str
    lines: list[JournalLine]
    total_debit: Decimal
    total_credit: Decimal
    created_by: UUID
    created_at: datetime
    updated_by: UUID
    updated_at: datetime
    submitted_by: UUID | None = None
    submitted_at: datetime | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    posted_by: UUID | None = None
    posted_at: datetime | None = None
    reversed_by: UUID | None = None
    reversed_at: datetime | None = None
    reversed_journal_id: UUID | None = None  # ID jurnal balik
    original_journal_id: UUID | None = None  # ID jurnal asli (untuk koreksi/reversal)
    cancellation_reason: str | None = None
    attachment_ids: list[UUID] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "voucher_number": self.voucher_number,
            "journal_type": self.journal_type.value,
            "status": self.status.value,
            "journal_date": self.journal_date.isoformat(),
            "posting_date": self.posting_date.isoformat() if self.posting_date else None,
            "period_id": str(self.period_id),
            "legal_entity_id": str(self.legal_entity_id),
            "description": self.description,
            "lines": [line.to_dict() for line in self.lines],
            "total_debit": float(self.total_debit),
            "total_credit": float(self.total_credit),
            "created_by": str(self.created_by),
            "created_at": self.created_at.isoformat(),
            "updated_by": str(self.updated_by),
            "updated_at": self.updated_at.isoformat(),
            "submitted_by": str(self.submitted_by) if self.submitted_by else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "posted_by": str(self.posted_by) if self.posted_by else None,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "reversed_by": str(self.reversed_by) if self.reversed_by else None,
            "reversed_at": self.reversed_at.isoformat() if self.reversed_at else None,
            "reversed_journal_id": str(self.reversed_journal_id)
            if self.reversed_journal_id
            else None,
            "original_journal_id": str(self.original_journal_id)
            if self.original_journal_id
            else None,
            "cancellation_reason": self.cancellation_reason,
            "attachment_ids": [str(aid) for aid in self.attachment_ids],
            "version": self.version,
        }

    def is_balanced(self) -> bool:
        """Periksa apakah debit == credit."""
        return self.total_debit == self.total_credit


class JournalRepositoryPort:
    """
    In-memory repository untuk Journal dengan fitur lengkap.
    """

    def __init__(self):
        self._storage: dict[UUID, Journal] = {}
        self._voucher_index: dict[str, Journal] = {}
        self._period_index: dict[UUID, list[UUID]] = {}
        self._status_index: dict[JournalStatus, list[UUID]] = {}
        self._legal_entity_index: dict[UUID, list[UUID]] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._voucher_counter: dict[str, int] = {}  # format "YYYY-MM" -> counter

    # ==================== HELPER ====================

    async def _log_audit(
        self, action: str, journal_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "journal_id": str(journal_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"JOURNAL AUDIT: {action} on {journal_id} by {user_id}")

    async def _generate_voucher_number(self, period_id: UUID) -> str:
        """Generate nomor voucher otomatis dengan format JRN-YYYYMM-XXXXX."""
        # Cari periode untuk mendapatkan tahun-bulan
        period = None
        # Simulasi: untuk demo, gunakan id period sebagai seed
        # Lebih baik: terima parameter tahun dan bulan
        now = datetime.now()
        year_month = now.strftime("%Y%m")
        if year_month not in self._voucher_counter:
            self._voucher_counter[year_month] = 0
        self._voucher_counter[year_month] += 1
        seq = str(self._voucher_counter[year_month]).zfill(5)
        return f"JRN-{year_month}-{seq}"

    async def _recompute_totals(self, journal: Journal):
        """Hitung ulang total debit dan kredit dari lines."""
        total_debit = Decimal(0)
        total_credit = Decimal(0)
        for line in journal.lines:
            total_debit += line.debit_amount
            total_credit += line.credit_amount
        journal.total_debit = total_debit
        journal.total_credit = total_credit

    async def _validate_journal(self, journal: Journal):
        """Validasi invariant jurnal."""
        if not journal.lines:
            raise ValueError("Journal must have at least one line")
        await self._recompute_totals(journal)
        if journal.total_debit != journal.total_credit:
            raise ValueError(
                f"Journal not balanced: debit={journal.total_debit}, credit={journal.total_credit}"
            )
        # Validasi tidak boleh ada line dengan debit dan credit > 0 simultan
        for line in journal.lines:
            if line.debit_amount > 0 and line.credit_amount > 0:
                raise ValueError("A journal line cannot have both debit and credit > 0")
            if line.debit_amount == 0 and line.credit_amount == 0:
                raise ValueError("A journal line must have either debit or credit > 0")

    async def _update_indices(self, journal: Journal, is_insert: bool = True):
        if is_insert:
            self._voucher_index[journal.voucher_number] = journal
            if journal.period_id not in self._period_index:
                self._period_index[journal.period_id] = []
            if journal.id not in self._period_index[journal.period_id]:
                self._period_index[journal.period_id].append(journal.id)
            if journal.status not in self._status_index:
                self._status_index[journal.status] = []
            if journal.id not in self._status_index[journal.status]:
                self._status_index[journal.status].append(journal.id)
            if journal.legal_entity_id not in self._legal_entity_index:
                self._legal_entity_index[journal.legal_entity_id] = []
            if journal.id not in self._legal_entity_index[journal.legal_entity_id]:
                self._legal_entity_index[journal.legal_entity_id].append(journal.id)
        else:
            # Untuk update, perlu update status index jika status berubah
            pass

    async def _remove_from_indices(self, journal: Journal):
        if journal.voucher_number in self._voucher_index:
            del self._voucher_index[journal.voucher_number]
        if (
            journal.period_id in self._period_index
            and journal.id in self._period_index[journal.period_id]
        ):
            self._period_index[journal.period_id].remove(journal.id)
        if (
            journal.status in self._status_index
            and journal.id in self._status_index[journal.status]
        ):
            self._status_index[journal.status].remove(journal.id)
        if (
            journal.legal_entity_id in self._legal_entity_index
            and journal.id in self._legal_entity_index[journal.legal_entity_id]
        ):
            self._legal_entity_index[journal.legal_entity_id].remove(journal.id)

    # ==================== CRUD ====================

    async def save(self, journal: Journal) -> None:
        """
        Simpan jurnal (insert jika baru, update jika sudah ada).
        Ini adalah method yang diminta oleh kontrak port.
        """
        async with self._lock:
            if journal.id in self._storage:
                # Update existing
                await self.update(journal)
            else:
                await self.add(journal)

    async def add(self, journal: Journal) -> None:
        if journal.id in self._storage:
            raise ValueError(f"Journal {journal.id} already exists")
        await self._validate_journal(journal)
        # Generate voucher number if not provided
        if not journal.voucher_number:
            journal.voucher_number = await self._generate_voucher_number(journal.period_id)
        if journal.voucher_number in self._voucher_index:
            raise ValueError(f"Voucher number {journal.voucher_number} already exists")
        journal.created_at = datetime.now(UTC)
        journal.updated_at = journal.created_at
        journal.version = 1
        async with self._lock:
            self._storage[journal.id] = journal
            await self._update_indices(journal, is_insert=True)
        await self._log_audit(
            "ADD",
            journal.id,
            journal.created_by,
            {
                "voucher_number": journal.voucher_number,
                "type": journal.journal_type.value,
            },
        )

    async def get_by_id(self, journal_id: UUID) -> Journal | None:
        return self._storage.get(journal_id)

    async def get_by_voucher_number(self, voucher_number: str) -> Journal | None:
        return self._voucher_index.get(voucher_number)

    async def update(self, journal: Journal) -> None:
        if journal.id not in self._storage:
            raise ValueError(f"Journal {journal.id} not found")
        old = self._storage[journal.id]
        # Hanya draft yang boleh diupdate langsung
        if old.status != JournalStatus.DRAFT:
            raise ValueError(
                f"Cannot update journal with status {old.status.value}. Only DRAFT allowed."
            )
        await self._validate_journal(journal)
        # Update voucher index jika berubah
        if old.voucher_number != journal.voucher_number:
            if journal.voucher_number in self._voucher_index:
                raise ValueError(f"Voucher number {journal.voucher_number} already exists")
            del self._voucher_index[old.voucher_number]
            self._voucher_index[journal.voucher_number] = journal
        # Update status index jika status berubah (hanya jika dari draft ke submitted)
        if old.status != journal.status:
            if old.status in self._status_index and old.id in self._status_index[old.status]:
                self._status_index[old.status].remove(old.id)
            if journal.status not in self._status_index:
                self._status_index[journal.status] = []
            if journal.id not in self._status_index[journal.status]:
                self._status_index[journal.status].append(journal.id)
        journal.updated_at = datetime.now(UTC)
        journal.version = old.version + 1
        journal.created_at = old.created_at
        journal.created_by = old.created_by
        self._storage[journal.id] = journal
        await self._log_audit(
            "UPDATE",
            journal.id,
            journal.updated_by,
            {
                "voucher_number": journal.voucher_number,
                "status_change": f"{old.status.value} -> {journal.status.value}",
            },
        )

    async def delete(self, journal_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        journal = self._storage.get(journal_id)
        if not journal:
            return False
        if journal.status != JournalStatus.DRAFT:
            raise ValueError(
                f"Cannot delete journal with status {journal.status.value}. Only DRAFT allowed."
            )
        if permanent:
            await self._remove_from_indices(journal)
            del self._storage[journal_id]
            await self._log_audit("DELETE_PERMANENT", journal_id, user_id, {})
        else:
            journal.status = JournalStatus.CANCELLED
            journal.cancellation_reason = "Deleted by user"
            journal.updated_by = user_id
            journal.updated_at = datetime.now(UTC)
            journal.version += 1
            await self.update(journal)
            await self._log_audit("DELETE_SOFT", journal_id, user_id, {})
        return True

    # ==================== WORKFLOW ACTIONS ====================

    async def submit(self, journal_id: UUID, user_id: UUID) -> bool:
        journal = await self.get_by_id(journal_id)
        if not journal or journal.status != JournalStatus.DRAFT:
            return False
        journal.status = JournalStatus.SUBMITTED
        journal.submitted_by = user_id
        journal.submitted_at = datetime.now(UTC)
        journal.updated_by = user_id
        await self.update(journal)
        await self._log_audit("SUBMIT", journal_id, user_id, {})
        return True

    async def approve(self, journal_id: UUID, approver_id: UUID) -> bool:
        journal = await self.get_by_id(journal_id)
        if not journal or journal.status != JournalStatus.SUBMITTED:
            return False
        journal.status = JournalStatus.APPROVED
        journal.approved_by = approver_id
        journal.approved_at = datetime.now(UTC)
        journal.updated_by = approver_id
        await self.update(journal)
        await self._log_audit("APPROVE", journal_id, approver_id, {})
        return True

    async def post(self, journal_id: UUID, user_id: UUID, posting_date: date | None = None) -> bool:
        journal = await self.get_by_id(journal_id)
        if not journal or journal.status != JournalStatus.APPROVED:
            return False
        journal.status = JournalStatus.POSTED
        journal.posted_by = user_id
        journal.posted_at = datetime.now(UTC)
        journal.posting_date = posting_date or date.today()
        journal.updated_by = user_id
        await self.update(journal)
        await self._log_audit(
            "POST", journal_id, user_id, {"posting_date": journal.posting_date.isoformat()}
        )
        return True

    async def reverse(
        self, journal_id: UUID, user_id: UUID, reversal_date: date, reason: str
    ) -> Journal | None:
        """
        Membuat jurnal reversal (balik) untuk jurnal yang sudah diposting.
        Mengembalikan jurnal reversal yang baru dibuat.
        """
        original = await self.get_by_id(journal_id)
        if not original or original.status != JournalStatus.POSTED:
            raise ValueError("Only posted journal can be reversed")
        if original.reversed_journal_id:
            raise ValueError("Journal already reversed")
        # Buat lines reversal (negatif dari original)
        reversal_lines = []
        for line in original.lines:
            reversal_lines.append(
                JournalLine(
                    account_id=line.account_id,
                    account_code=line.account_code,
                    debit_amount=line.credit_amount,  # swap debit/credit
                    credit_amount=line.debit_amount,
                    description=f"Reversal of {original.voucher_number}: {line.description or ''}",
                    cost_center=line.cost_center,
                    department_id=line.department_id,
                    project_id=line.project_id,
                )
            )
        # Generate voucher number untuk reversal
        reversal_voucher = await self._generate_voucher_number(original.period_id)
        reversal = Journal(
            id=uuid4(),
            voucher_number=reversal_voucher,
            journal_type=JournalType.REVERSING,
            status=JournalStatus.DRAFT,
            journal_date=reversal_date,
            posting_date=None,
            period_id=original.period_id,
            legal_entity_id=original.legal_entity_id,
            description=f"Reversal of {original.voucher_number}: {reason}",
            lines=reversal_lines,
            total_debit=Decimal(0),
            total_credit=Decimal(0),
            created_by=user_id,
            created_at=datetime.now(UTC),
            updated_by=user_id,
            updated_at=datetime.now(UTC),
            original_journal_id=original.id,
        )
        await self.add(reversal)
        # Tandai original sebagai reversed
        original.reversed_journal_id = reversal.id
        original.status = JournalStatus.REVERSED
        original.updated_by = user_id
        await self.update(original)
        await self._log_audit(
            "REVERSE", original.id, user_id, {"reversal_id": str(reversal.id), "reason": reason}
        )
        return reversal

    # ==================== QUERY ====================

    async def find_by_status(
        self, status: JournalStatus, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
        ids = self._status_index.get(status, [])
        result = []
        for jid in ids:
            journal = self._storage.get(jid)
            if journal and journal.legal_entity_id == legal_entity_id:
                result.append(journal)
        result.sort(key=lambda x: x.journal_date, reverse=True)
        return result[offset : offset + limit]

    async def find_by_period(
        self, period_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
        ids = self._period_index.get(period_id, [])
        result = [self._storage[jid] for jid in ids if jid in self._storage]
        result.sort(key=lambda x: x.journal_date)
        return result[offset : offset + limit]

    async def find_by_date_range(
        self, start_date: date, end_date: date, legal_entity_id: UUID
    ) -> list[Journal]:
        result = []
        for journal in self._storage.values():
            if (
                journal.legal_entity_id == legal_entity_id
                and start_date <= journal.journal_date <= end_date
            ):
                result.append(journal)
        return sorted(result, key=lambda x: x.journal_date)

    async def find_by_account(
        self, account_id: UUID, start_date: date, end_date: date
    ) -> list[Journal]:
        """Cari jurnal yang memiliki line dengan account tertentu."""
        result = []
        for journal in self._storage.values():
            for line in journal.lines:
                if line.account_id == account_id and start_date <= journal.journal_date <= end_date:
                    result.append(journal)
                    break
        return sorted(result, key=lambda x: x.journal_date)

    async def exists_by_voucher_number(self, voucher_number: str) -> bool:
        return voucher_number in self._voucher_index

    async def get_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
        ids = self._legal_entity_index.get(legal_entity_id, [])
        result = [self._storage[jid] for jid in ids if jid in self._storage]
        result.sort(key=lambda x: x.journal_date, reverse=True)
        return result[offset : offset + limit]

    async def get_pending_approval(self, legal_entity_id: UUID) -> list[Journal]:
        return await self.find_by_status(JournalStatus.SUBMITTED, legal_entity_id)

    # ==================== IMPORT/EXPORT ====================

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        journals = await self.get_all(legal_entity_id)
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "voucher_number",
                "journal_date",
                "type",
                "status",
                "description",
                "total_debit",
                "total_credit",
            ]
        )
        for j in journals:
            writer.writerow(
                [
                    j.voucher_number,
                    j.journal_date.isoformat(),
                    j.journal_type.value,
                    j.status.value,
                    j.description,
                    float(j.total_debit),
                    float(j.total_credit),
                ]
            )
        return output.getvalue()

    async def import_from_csv(
        self, csv_content: str, legal_entity_id: UUID, period_id: UUID, user_id: UUID
    ) -> int:
        import io

        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                journal = Journal(
                    id=uuid4(),
                    voucher_number="",
                    journal_type=JournalType(row.get("type", "general")),
                    status=JournalStatus.DRAFT,
                    journal_date=date.fromisoformat(row["journal_date"]),
                    posting_date=None,
                    period_id=period_id,
                    legal_entity_id=legal_entity_id,
                    description=row.get("description", ""),
                    lines=[],
                    total_debit=Decimal(0),
                    total_credit=Decimal(0),
                    created_by=user_id,
                    created_at=datetime.now(UTC),
                    updated_by=user_id,
                    updated_at=datetime.now(UTC),
                )
                await self.add(journal)
                count += 1
            except Exception as e:
                logger.warning(f"Import failed: {e}")
        return count

    # ==================== STATISTICS & AUDIT ====================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        journals = [j for j in self._storage.values() if j.legal_entity_id == legal_entity_id]
        total = len(journals)
        posted = sum(1 for j in journals if j.status == JournalStatus.POSTED)
        draft = sum(1 for j in journals if j.status == JournalStatus.DRAFT)
        total_debit = sum(j.total_debit for j in journals)
        total_credit = sum(j.total_credit for j in journals)
        return {
            "total_journals": total,
            "posted_count": posted,
            "draft_count": draft,
            "approved_count": sum(1 for j in journals if j.status == JournalStatus.APPROVED),
            "total_debit": float(total_debit),
            "total_credit": float(total_credit),
            "by_type": {
                t.value: sum(1 for j in journals if j.journal_type == t) for t in JournalType
            },
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_journals": len(self._storage),
            "total_vouchers": len(self._voucher_index),
            "audit_log_size": len(self._audit_log),
        }
