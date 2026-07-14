#!/usr/bin/env python3
"""
Module: tax_transaction_repository_port.py
Layer: Ports (Primary)
Responsibility: 
    - Mendefinisikan antarmuka (port) untuk repository transaksi pajak.
    - Menyediakan implementasi in-memory untuk keperluan testing/fallback.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ==================== ENUMS & DOMAIN MODELS ====================

class TaxType(Enum):
    PPN_OUT = "ppn_out"
    PPN_IN = "ppn_in"
    PPH_21 = "pph_21"
    PPH_22 = "pph_22"
    PPH_23 = "pph_23"
    PPH_24 = "pph_24"
    PPH_25 = "pph_25"
    PPH_26 = "pph_26"
    PPH_4_2 = "pph_4_2"
    PPH_BADAN = "pph_badan"
    PPH_OP = "pph_op"


class TaxTransactionStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PAID = "paid"
    REPORTED = "reported"
    ADJUSTED = "adjusted"
    VOID = "void"


class SPTType(Enum):
    PPN_MASA = "ppn_masa"
    PPH_21_MASA = "pph_21_masa"
    PPH_22_MASA = "pph_22_masa"
    PPH_23_MASA = "pph_23_masa"
    PPH_25_MASA = "pph_25_masa"
    PPH_4_2_MASA = "pph_4_2_masa"
    PPH_BADAN_TAHUNAN = "pph_badan_tahunan"
    PPH_OP_TAHUNAN = "pph_op_tahunan"


@dataclass
class TaxTransaction:
    id: UUID
    legal_entity_id: UUID
    tax_type: TaxType
    transaction_date: date
    tax_period_month: int
    tax_period_year: int
    amount: Decimal
    tax_amount: Decimal
    rate: Decimal
    status: TaxTransactionStatus
    reference_type: str | None = None
    reference_id: UUID | None = None
    description: str | None = None
    is_credit: bool = False
    payment_date: date | None = None
    payment_amount: Decimal = Decimal(0)
    ntpn: str | None = None
    reported_in_spt_id: UUID | None = None
    adjusted_from_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    version: int = 1
    deleted_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "tax_type": self.tax_type.value,
            "transaction_date": self.transaction_date.isoformat(),
            "tax_period_month": self.tax_period_month,
            "tax_period_year": self.tax_period_year,
            "amount": str(self.amount),
            "tax_amount": str(self.tax_amount),
            "rate": str(self.rate),
            "status": self.status.value,
            "reference_type": self.reference_type,
            "reference_id": str(self.reference_id) if self.reference_id else None,
            "description": self.description,
            "is_credit": self.is_credit,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "payment_amount": str(self.payment_amount),
            "ntpn": self.ntpn,
            "reported_in_spt_id": str(self.reported_in_spt_id) if self.reported_in_spt_id else None,
            "adjusted_from_id": str(self.adjusted_from_id) if self.adjusted_from_id else None,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


@dataclass
class SPTSubmission:
    id: UUID
    legal_entity_id: UUID
    spt_type: SPTType
    period_month: int
    period_year: int
    status: str
    total_tax_due: Decimal
    total_tax_paid: Decimal
    total_tax_credit: Decimal
    submission_date: date | None = None
    approval_code: str | None = None
    rejection_reason: str | None = None
    xml_content: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))


# ==================== PORT (INTERFACE) ====================

class TaxTransactionRepositoryPort(ABC):
    """Port untuk repository transaksi pajak."""

    @abstractmethod
    async def add(self, tax_transaction: TaxTransaction) -> None:
        pass

    @abstractmethod
    async def get_by_id(self, tax_transaction_id: UUID) -> TaxTransaction | None:
        pass

    @abstractmethod
    async def update(self, tax_transaction: TaxTransaction) -> None:
        pass

    @abstractmethod
    async def delete(
        self, tax_transaction_id: UUID, user_id: UUID, permanent: bool = False
    ) -> bool:
        pass

    @abstractmethod
    async def find_by_period(
        self, legal_entity_id: UUID, tax_type: TaxType, year: int, month: int
    ) -> list[TaxTransaction]:
        pass

    @abstractmethod
    async def find_by_period_range(
        self,
        legal_entity_id: UUID,
        tax_type: TaxType,
        start_year: int,
        start_month: int,
        end_year: int,
        end_month: int,
    ) -> list[TaxTransaction]:
        pass

    @abstractmethod
    async def get_total_tax_liability(
        self, legal_entity_id: UUID, tax_type: TaxType, start_date: date, end_date: date
    ) -> Decimal:
        pass

    @abstractmethod
    async def get_total_tax_credit(
        self, legal_entity_id: UUID, tax_type: TaxType, start_date: date, end_date: date
    ) -> Decimal:
        pass

    @abstractmethod
    async def find_by_reference(
        self, reference_type: str, reference_id: UUID
    ) -> list[TaxTransaction]:
        pass

    @abstractmethod
    async def create_spt_submission(
        self,
        legal_entity_id: UUID,
        spt_type: SPTType,
        period_month: int,
        period_year: int,
        total_tax_due: Decimal,
        total_tax_paid: Decimal,
        total_tax_credit: Decimal,
        created_by: UUID,
    ) -> UUID:
        pass

    @abstractmethod
    async def submit_spt(
        self, spt_id: UUID, submission_date: date, xml_content: str, user_id: UUID
    ) -> bool:
        pass

    @abstractmethod
    async def approve_spt(self, spt_id: UUID, approval_code: str, user_id: UUID) -> bool:
        pass

    @abstractmethod
    async def reject_spt(self, spt_id: UUID, reason: str, user_id: UUID) -> bool:
        pass

    @abstractmethod
    async def get_spt_by_period(
        self, legal_entity_id: UUID, spt_type: SPTType, period_month: int, period_year: int
    ) -> SPTSubmission | None:
        pass

    @abstractmethod
    async def mark_transactions_reported(
        self, tax_transaction_ids: list[UUID], spt_id: UUID, user_id: UUID
    ) -> int:
        pass

    @abstractmethod
    async def record_payment(
        self,
        tax_transaction_id: UUID,
        payment_date: date,
        amount: Decimal,
        ntpn: str,
        user_id: UUID,
    ) -> bool:
        pass

    @abstractmethod
    async def create_adjustment(
        self, original_tx_id: UUID, new_tax_amount: Decimal, description: str, user_id: UUID
    ) -> TaxTransaction | None:
        pass

    @abstractmethod
    async def export_to_csv(
        self,
        legal_entity_id: UUID,
        tax_type: TaxType | None = None,
        start_year: int | None = None,
        start_month: int | None = None,
        end_year: int | None = None,
        end_month: int | None = None,
    ) -> str:
        pass

    @abstractmethod
    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, user_id: UUID) -> int:
        pass

    @abstractmethod
    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        pass


# ==================== IMPLEMENTASI IN-MEMORY (FALLBACK/TESTING) ====================

class InMemoryTaxTransactionRepository(TaxTransactionRepositoryPort):
    """
    Implementasi in-memory untuk TaxTransactionRepositoryPort.
    Kelas ini TIDAK akan didaftarkan oleh container karena mengandung kata "InMemory".
    """

    def __init__(self):
        self._storage: dict[UUID, TaxTransaction] = {}
        self._period_index: dict[
            tuple[UUID, int, int, TaxType], list[UUID]
        ] = {}
        self._reference_index: dict[tuple[str, UUID], list[UUID]] = {}
        self._spt_submissions: dict[UUID, SPTSubmission] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    # ==================== HELPERS ====================

    async def _log_audit(self, action: str, tx_id: UUID, user_id: UUID, details: dict[str, Any]):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "tax_transaction_id": str(tx_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"TAX TRANSACTION AUDIT: {action} on {tx_id}")

    async def _update_indices(self, tx: TaxTransaction, is_insert: bool = True):
        period_key = (tx.legal_entity_id, tx.tax_period_year, tx.tax_period_month, tx.tax_type)
        if period_key not in self._period_index:
            self._period_index[period_key] = []
        if tx.id not in self._period_index[period_key]:
            self._period_index[period_key].append(tx.id)

        if tx.reference_type and tx.reference_id:
            ref_key = (tx.reference_type, tx.reference_id)
            if ref_key not in self._reference_index:
                self._reference_index[ref_key] = []
            if tx.id not in self._reference_index[ref_key]:
                self._reference_index[ref_key].append(tx.id)

    async def _remove_from_indices(self, tx: TaxTransaction):
        period_key = (tx.legal_entity_id, tx.tax_period_year, tx.tax_period_month, tx.tax_type)
        if period_key in self._period_index and tx.id in self._period_index[period_key]:
            self._period_index[period_key].remove(tx.id)
        if tx.reference_type and tx.reference_id:
            ref_key = (tx.reference_type, tx.reference_id)
            if ref_key in self._reference_index and tx.id in self._reference_index[ref_key]:
                self._reference_index[ref_key].remove(tx.id)

    # ==================== CRUD ====================

    async def add(self, tax_transaction: TaxTransaction) -> None:
        if tax_transaction.id in self._storage:
            raise ValueError(f"TaxTransaction {tax_transaction.id} already exists")
        tax_transaction.created_at = datetime.now(UTC)
        tax_transaction.updated_at = tax_transaction.created_at
        tax_transaction.version = 1
        async with self._lock:
            self._storage[tax_transaction.id] = tax_transaction
            await self._update_indices(tax_transaction, is_insert=True)
        await self._log_audit(
            "ADD",
            tax_transaction.id,
            tax_transaction.created_by,
            {
                "tax_type": tax_transaction.tax_type.value,
                "amount": str(tax_transaction.tax_amount),
                "period": f"{tax_transaction.tax_period_year}-{tax_transaction.tax_period_month}",
            },
        )

    async def get_by_id(self, tax_transaction_id: UUID) -> TaxTransaction | None:
        tx = self._storage.get(tax_transaction_id)
        if tx and tx.deleted_at is not None:
            return None
        return tx

    async def update(self, tax_transaction: TaxTransaction) -> None:
        if tax_transaction.id not in self._storage:
            raise ValueError(f"TaxTransaction {tax_transaction.id} not found")
        old = self._storage[tax_transaction.id]
        if old.deleted_at is not None:
            raise ValueError("Cannot update deleted transaction")
        if (old.legal_entity_id, old.tax_period_year, old.tax_period_month, old.tax_type) != (
            tax_transaction.legal_entity_id,
            tax_transaction.tax_period_year,
            tax_transaction.tax_period_month,
            tax_transaction.tax_type,
        ):
            await self._remove_from_indices(old)
            await self._update_indices(tax_transaction, is_insert=True)
        tax_transaction.updated_at = datetime.now(UTC)
        tax_transaction.version = old.version + 1
        tax_transaction.created_at = old.created_at
        tax_transaction.created_by = old.created_by
        async with self._lock:
            self._storage[tax_transaction.id] = tax_transaction
        await self._log_audit("UPDATE", tax_transaction.id, tax_transaction.updated_by, {})

    async def delete(
        self, tax_transaction_id: UUID, user_id: UUID, permanent: bool = False
    ) -> bool:
        tx = self._storage.get(tax_transaction_id)
        if not tx:
            return False
        if permanent:
            await self._remove_from_indices(tx)
            del self._storage[tax_transaction_id]
            await self._log_audit("DELETE_PERMANENT", tax_transaction_id, user_id, {})
        else:
            tx.deleted_at = datetime.now(UTC)
            tx.status = TaxTransactionStatus.VOID
            tx.updated_by = user_id
            tx.updated_at = tx.deleted_at
            tx.version += 1
            await self.update(tx)
            await self._log_audit("DELETE_SOFT", tax_transaction_id, user_id, {})
        return True

    # ==================== QUERY ====================

    async def find_by_period(
        self, legal_entity_id: UUID, tax_type: TaxType, year: int, month: int
    ) -> list[TaxTransaction]:
        period_key = (legal_entity_id, year, month, tax_type)
        ids = self._period_index.get(period_key, [])
        result = []
        for tid in ids:
            tx = self._storage.get(tid)
            if tx and tx.deleted_at is None:
                result.append(tx)
        return result

    async def find_by_period_range(
        self,
        legal_entity_id: UUID,
        tax_type: TaxType,
        start_year: int,
        start_month: int,
        end_year: int,
        end_month: int,
    ) -> list[TaxTransaction]:
        result = []
        year, month = start_year, start_month
        while (year < end_year) or (year == end_year and month <= end_month):
            period_key = (legal_entity_id, year, month, tax_type)
            ids = self._period_index.get(period_key, [])
            for tid in ids:
                tx = self._storage.get(tid)
                if tx and tx.deleted_at is None:
                    result.append(tx)
            month += 1
            if month > 12:
                month = 1
                year += 1
        return result

    async def get_total_tax_liability(
        self, legal_entity_id: UUID, tax_type: TaxType, start_date: date, end_date: date
    ) -> Decimal:
        total = Decimal(0)
        for tx in self._storage.values():
            if (
                tx.legal_entity_id == legal_entity_id
                and tx.tax_type == tax_type
                and not tx.is_credit
            ):
                if start_date <= tx.transaction_date <= end_date:
                    if tx.status in (
                        TaxTransactionStatus.SUBMITTED,
                        TaxTransactionStatus.PAID,
                        TaxTransactionStatus.REPORTED,
                    ):
                        total += tx.tax_amount
        return total

    async def get_total_tax_credit(
        self, legal_entity_id: UUID, tax_type: TaxType, start_date: date, end_date: date
    ) -> Decimal:
        total = Decimal(0)
        for tx in self._storage.values():
            if tx.legal_entity_id == legal_entity_id and tx.tax_type == tax_type and tx.is_credit:
                if start_date <= tx.transaction_date <= end_date:
                    if tx.status in (
                        TaxTransactionStatus.SUBMITTED,
                        TaxTransactionStatus.PAID,
                        TaxTransactionStatus.REPORTED,
                    ):
                        total += tx.tax_amount
        return total

    async def find_by_reference(
        self, reference_type: str, reference_id: UUID
    ) -> list[TaxTransaction]:
        ref_key = (reference_type, reference_id)
        ids = self._reference_index.get(ref_key, [])
        result = []
        for tid in ids:
            tx = self._storage.get(tid)
            if tx and tx.deleted_at is None:
                result.append(tx)
        return result

    # ==================== SPT MANAGEMENT ====================

    async def create_spt_submission(
        self,
        legal_entity_id: UUID,
        spt_type: SPTType,
        period_month: int,
        period_year: int,
        total_tax_due: Decimal,
        total_tax_paid: Decimal,
        total_tax_credit: Decimal,
        created_by: UUID,
    ) -> UUID:
        spt_id = uuid4()
        spt = SPTSubmission(
            id=spt_id,
            legal_entity_id=legal_entity_id,
            spt_type=spt_type,
            period_month=period_month,
            period_year=period_year,
            status="DRAFT",
            total_tax_due=total_tax_due,
            total_tax_paid=total_tax_paid,
            total_tax_credit=total_tax_credit,
            created_at=datetime.now(UTC),
            created_by=created_by,
            updated_at=datetime.now(UTC),
            updated_by=created_by,
        )
        self._spt_submissions[spt_id] = spt
        await self._log_audit(
            "CREATE_SPT",
            spt_id,
            created_by,
            {"spt_type": spt_type.value, "period": f"{period_year}-{period_month}"},
        )
        return spt_id

    async def submit_spt(
        self, spt_id: UUID, submission_date: date, xml_content: str, user_id: UUID
    ) -> bool:
        spt = self._spt_submissions.get(spt_id)
        if not spt or spt.status != "DRAFT":
            return False
        spt.status = "SUBMITTED"
        spt.submission_date = submission_date
        spt.xml_content = xml_content
        spt.updated_at = datetime.now(UTC)
        spt.updated_by = user_id
        await self._log_audit(
            "SUBMIT_SPT", spt_id, user_id, {"submission_date": submission_date.isoformat()}
        )
        return True

    async def approve_spt(self, spt_id: UUID, approval_code: str, user_id: UUID) -> bool:
        spt = self._spt_submissions.get(spt_id)
        if not spt or spt.status != "SUBMITTED":
            return False
        spt.status = "APPROVED"
        spt.approval_code = approval_code
        spt.updated_at = datetime.now(UTC)
        spt.updated_by = user_id
        await self._log_audit("APPROVE_SPT", spt_id, user_id, {"approval_code": approval_code})
        return True

    async def reject_spt(self, spt_id: UUID, reason: str, user_id: UUID) -> bool:
        spt = self._spt_submissions.get(spt_id)
        if not spt or spt.status != "SUBMITTED":
            return False
        spt.status = "REJECTED"
        spt.rejection_reason = reason
        spt.updated_at = datetime.now(UTC)
        spt.updated_by = user_id
        await self._log_audit("REJECT_SPT", spt_id, user_id, {"reason": reason})
        return True

    async def get_spt_by_period(
        self, legal_entity_id: UUID, spt_type: SPTType, period_month: int, period_year: int
    ) -> SPTSubmission | None:
        for spt in self._spt_submissions.values():
            if (
                spt.legal_entity_id == legal_entity_id
                and spt.spt_type == spt_type
                and spt.period_month == period_month
                and spt.period_year == period_year
            ):
                return spt
        return None

    async def mark_transactions_reported(
        self, tax_transaction_ids: list[UUID], spt_id: UUID, user_id: UUID
    ) -> int:
        count = 0
        for tid in tax_transaction_ids:
            tx = await self.get_by_id(tid)
            if tx and tx.status not in (TaxTransactionStatus.REPORTED, TaxTransactionStatus.VOID):
                tx.status = TaxTransactionStatus.REPORTED
                tx.reported_in_spt_id = spt_id
                tx.updated_by = user_id
                tx.updated_at = datetime.now(UTC)
                tx.version += 1
                await self.update(tx)
                count += 1
        await self._log_audit(
            "MARK_REPORTED", UUID(int=0), user_id, {"count": count, "spt_id": str(spt_id)}
        )
        return count

    # ==================== PAYMENT ====================

    async def record_payment(
        self,
        tax_transaction_id: UUID,
        payment_date: date,
        amount: Decimal,
        ntpn: str,
        user_id: UUID,
    ) -> bool:
        tx = await self.get_by_id(tax_transaction_id)
        if not tx or tx.status == TaxTransactionStatus.PAID:
            return False
        tx.payment_date = payment_date
        tx.payment_amount = amount
        tx.ntpn = ntpn
        tx.status = TaxTransactionStatus.PAID
        tx.updated_by = user_id
        tx.updated_at = datetime.now(UTC)
        tx.version += 1
        await self.update(tx)
        await self._log_audit(
            "PAYMENT", tax_transaction_id, user_id, {"ntpn": ntpn, "amount": str(amount)}
        )
        return True

    # ==================== ADJUSTMENT ====================

    async def create_adjustment(
        self, original_tx_id: UUID, new_tax_amount: Decimal, description: str, user_id: UUID
    ) -> TaxTransaction | None:
        original = await self.get_by_id(original_tx_id)
        if not original:
            return None
        adjustment = TaxTransaction(
            id=uuid4(),
            legal_entity_id=original.legal_entity_id,
            tax_type=original.tax_type,
            transaction_date=date.today(),
            tax_period_month=original.tax_period_month,
            tax_period_year=original.tax_period_year,
            amount=original.amount,
            tax_amount=new_tax_amount,
            rate=original.rate,
            status=TaxTransactionStatus.ADJUSTED,
            reference_type="ADJUSTMENT",
            reference_id=original.id,
            description=description,
            is_credit=original.is_credit,
            adjusted_from_id=original.id,
            created_by=user_id,
            updated_by=user_id,
        )
        await self.add(adjustment)
        original.status = TaxTransactionStatus.ADJUSTED
        original.updated_by = user_id
        original.updated_at = datetime.now(UTC)
        original.version += 1
        await self.update(original)
        return adjustment

    # ==================== IMPORT / EXPORT ====================

    async def export_to_csv(
        self,
        legal_entity_id: UUID,
        tax_type: TaxType | None = None,
        start_year: int | None = None,
        start_month: int | None = None,
        end_year: int | None = None,
        end_month: int | None = None,
    ) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "tax_type", "transaction_date", "period", "amount",
            "tax_amount", "rate", "status", "is_credit",
            "payment_date", "ntpn", "reference_type", "reference_id"
        ])

        for tx in self._storage.values():
            if tx.legal_entity_id != legal_entity_id or tx.deleted_at is not None:
                continue
            if tax_type and tx.tax_type != tax_type:
                continue
            if start_year and end_year:
                if (tx.tax_period_year < start_year) or (tx.tax_period_year > end_year):
                    continue
                if tx.tax_period_year == start_year and start_month and tx.tax_period_month < start_month:
                    continue
                if tx.tax_period_year == end_year and end_month and tx.tax_period_month > end_month:
                    continue
            writer.writerow([
                str(tx.id),
                tx.tax_type.value,
                tx.transaction_date.isoformat(),
                f"{tx.tax_period_year}-{tx.tax_period_month:02d}",
                str(tx.amount),
                str(tx.tax_amount),
                str(tx.rate),
                tx.status.value,
                "1" if tx.is_credit else "0",
                tx.payment_date.isoformat() if tx.payment_date else "",
                tx.ntpn or "",
                tx.reference_type or "",
                str(tx.reference_id) if tx.reference_id else "",
            ])
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, user_id: UUID) -> int:
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                period = row["period"].split("-")
                year = int(period[0])
                month = int(period[1])
                tx = TaxTransaction(
                    id=uuid4(),
                    legal_entity_id=legal_entity_id,
                    tax_type=TaxType(row["tax_type"]),
                    transaction_date=date.fromisoformat(row["transaction_date"]),
                    tax_period_month=month,
                    tax_period_year=year,
                    amount=Decimal(row["amount"]),
                    tax_amount=Decimal(row["tax_amount"]),
                    rate=Decimal(row["rate"]),
                    status=TaxTransactionStatus(row["status"]),
                    is_credit=row["is_credit"] == "1",
                    payment_date=date.fromisoformat(row["payment_date"]) if row["payment_date"] else None,
                    ntpn=row["ntpn"] or None,
                    reference_type=row["reference_type"] or None,
                    reference_id=UUID(row["reference_id"]) if row["reference_id"] else None,
                    created_by=user_id,
                    updated_by=user_id,
                )
                await self.add(tx)
                count += 1
            except Exception as e:
                logger.warning(f"Import tax transaction failed: {e}")
        return count

    # ==================== STATISTICS & AUDIT ====================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        transactions = [t for t in self._storage.values() if t.legal_entity_id == legal_entity_id and t.deleted_at is None]
        total = len(transactions)
        total_liability = sum(t.tax_amount for t in transactions if not t.is_credit)
        total_credit = sum(t.tax_amount for t in transactions if t.is_credit)
        net_payable = total_liability - total_credit
        paid = sum(t.payment_amount for t in transactions if t.status == TaxTransactionStatus.PAID)
        by_type = {tt.value: 0 for tt in TaxType}
        for t in transactions:
            by_type[t.tax_type.value] = by_type.get(t.tax_type.value, 0) + 1
        return {
            "total_transactions": total,
            "total_liability": str(total_liability),
            "total_credit": str(total_credit),
            "net_payable": str(net_payable),
            "total_paid": str(paid),
            "outstanding": str(net_payable - paid),
            "by_tax_type": by_type,
            "spt_submissions": len(self._spt_submissions),
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_transactions": len(self._storage),
            "total_spt": len(self._spt_submissions),
            "audit_log_size": len(self._audit_log),
        }


__all__ = [
    "InMemoryTaxTransactionRepository",
    "SPTSubmission",
    "SPTType",
    "TaxTransaction",
    "TaxTransactionRepositoryPort",
    "TaxTransactionStatus",
    "TaxType",
]
