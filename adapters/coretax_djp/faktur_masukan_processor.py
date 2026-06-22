#!/usr/bin/env python3
"""
Module: faktur_masukan_processor.py
Layer: Adapters (Coretax DJP)
Responsibility: Memproses faktur pajak masukan (PM) yang diterima dari supplier
               atau dari sistem Coretax DJP. Meliputi: download faktur masukan
               dari DJP, parsing XML, validasi, pencocokan dengan transaksi internal,
               dan pengkreditan PPN masukan.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError, get_coretax_client

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

CORETAX_PM_DOWNLOAD_ENDPOINT = "/api/v1/faktur-pajak/masukan/download"
CORETAX_PM_LIST_ENDPOINT = "/api/v1/faktur-pajak/masukan"
CORETAX_PM_CREDIT_ENDPOINT = "/api/v1/faktur-pajak/masukan/kredit"
CORETAX_PM_CANCEL_ENDPOINT = "/api/v1/faktur-pajak/masukan/batal"
CORETAX_PM_DETAIL_ENDPOINT = "/api/v1/faktur-pajak/masukan/detail"
CORETAX_PM_VALIDATE_ENDPOINT = "/api/v1/faktur-pajak/masukan/validate"


class FakturMasukanStatus(Enum):
    DRAFT = "draft"
    PENDING = "pending"
    VALIDATED = "validated"
    MATCHED = "matched"
    CREDITED = "credited"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    CANCELLED = "cancelled"
    VOID = "void"
    REVERSED = "reversed"
    CLOSED = "closed"
    ARCHIVED = "archived"
    LOCKED = "locked"
    ERROR = "error"
    SYNCED = "synced"
    EXPIRED = "expired"


PM_STATUS = {
    "PENDING": FakturMasukanStatus.PENDING.value,
    "VALIDATED": FakturMasukanStatus.VALIDATED.value,
    "CREDITED": FakturMasukanStatus.CREDITED.value,
    "REJECTED": FakturMasukanStatus.REJECTED.value,
    "CANCELLED": FakturMasukanStatus.CANCELLED.value,
    "APPROVED": FakturMasukanStatus.APPROVED.value,
    "POSTED": FakturMasukanStatus.POSTED.value,
    "DRAFT": FakturMasukanStatus.DRAFT.value,
    "MATCHED": FakturMasukanStatus.MATCHED.value,
    "VOID": FakturMasukanStatus.VOID.value,
    "REVERSED": FakturMasukanStatus.REVERSED.value,
    "CLOSED": FakturMasukanStatus.CLOSED.value,
    "ARCHIVED": FakturMasukanStatus.ARCHIVED.value,
    "LOCKED": FakturMasukanStatus.LOCKED.value,
    "ERROR": FakturMasukanStatus.ERROR.value,
    "SYNCED": FakturMasukanStatus.SYNCED.value,
    "EXPIRED": FakturMasukanStatus.EXPIRED.value,
}

JENIS_TRANSAKSI = {
    "01": "Penyerahan BKP",
    "02": "Penyerahan JKP",
    "03": "Penyerahan BKP Tidak Berwujud",
    "04": "Penyerahan JKP Tidak Berwujud",
    "05": "Ekspor BKP",
    "06": "Ekspor JKP",
    "07": "Ekspor BKP Tidak Berwujud",
    "08": "Penyerahan BKP kepada Pemungut",
    "09": "Penyerahan JKP kepada Pemungut",
}

DEFAULT_PPN_RATE = Decimal("0.11")
MAX_RETRY_ATTEMPTS = 3
CACHE_TTL_SECONDS = 3600
EXPIRY_DAYS = 90


# ============================================================================
# EXCEPTIONS
# ============================================================================
class FakturMasukanError(Exception):
    pass


class FakturMasukanNotFoundError(FakturMasukanError):
    pass


class FakturMasukanAlreadyExistsError(FakturMasukanError):
    pass


class FakturMasukanInvalidStateError(FakturMasukanError):
    pass


class FakturMasukanValidationError(FakturMasukanError):
    pass


class FakturMasukanExpiredError(FakturMasukanError):
    pass


class FakturMasukanLockedError(FakturMasukanError):
    pass


# ============================================================================
# DOMAIN ENTITY
# ============================================================================
class FakturMasukan:
    """Entity untuk Faktur Pajak Masukan."""

    def __init__(
        self,
        faktur_number: str,
        npwp_penjual: str,
        nama_penjual: str,
        tanggal_faktur: date,
        dpp: Decimal,
        ppn: Decimal,
        npwp_pembeli: str = "",
        alamat_penjual: str = "",
        ppn_bm: Decimal = Decimal(0),
        keterangan: str = "",
        xml_content: str = "",
        faktur_id: UUID | None = None,
        status: FakturMasukanStatus = FakturMasukanStatus.DRAFT,
        version: int = 1,
    ):
        self._faktur_id = faktur_id or uuid4()
        self._faktur_number = faktur_number
        self._npwp_penjual = npwp_penjual
        self._nama_penjual = nama_penjual
        self._alamat_penjual = alamat_penjual
        self._npwp_pembeli = npwp_pembeli
        self._tanggal_faktur = tanggal_faktur
        self._dpp = dpp
        self._ppn = ppn
        self._ppn_bm = ppn_bm
        self._keterangan = keterangan
        self._xml_content = xml_content
        self._status = status
        self._version = version
        self._created_at = datetime.now()
        self._updated_at = datetime.now()
        self._synced_at: datetime | None = None
        self._credited_at: datetime | None = None
        self._approved_at: datetime | None = None
        self._posted_at: datetime | None = None
        self._cancelled_at: datetime | None = None
        self._closed_at: datetime | None = None
        self._archived_at: datetime | None = None
        self._locked_at: datetime | None = None
        self._locked_by: UUID | None = None
        self._matched_transaction_id: UUID | None = None
        self._period_id: UUID | None = None
        self._credit_amount: Decimal = Decimal(0)
        self._rejection_reason: str = ""
        self._cancellation_reason: str = ""
        self._events: list = []
        self._history: list = []
        self._hash: str = ""
        self._calculate_hash()

    # ========================================================================
    # Property Accessors
    # ========================================================================
    @property
    def faktur_id(self) -> UUID:
        return self._faktur_id

    @property
    def faktur_number(self) -> str:
        return self._faktur_number

    @property
    def npwp_penjual(self) -> str:
        return self._npwp_penjual

    @property
    def nama_penjual(self) -> str:
        return self._nama_penjual

    @property
    def alamat_penjual(self) -> str:
        return self._alamat_penjual

    @property
    def npwp_pembeli(self) -> str:
        return self._npwp_pembeli

    @property
    def tanggal_faktur(self) -> date:
        return self._tanggal_faktur

    @property
    def dpp(self) -> Decimal:
        return self._dpp

    @property
    def ppn(self) -> Decimal:
        return self._ppn

    @property
    def ppn_bm(self) -> Decimal:
        return self._ppn_bm

    @property
    def total_amount(self) -> Decimal:
        return self._dpp + self._ppn + self._ppn_bm

    @property
    def keterangan(self) -> str:
        return self._keterangan

    @property
    def status(self) -> FakturMasukanStatus:
        return self._status

    @property
    def version(self) -> int:
        return self._version

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def synced_at(self) -> datetime | None:
        return self._synced_at

    @property
    def credited_at(self) -> datetime | None:
        return self._credited_at

    @property
    def approved_at(self) -> datetime | None:
        return self._approved_at

    @property
    def posted_at(self) -> datetime | None:
        return self._posted_at

    @property
    def cancelled_at(self) -> datetime | None:
        return self._cancelled_at

    @property
    def closed_at(self) -> datetime | None:
        return self._closed_at

    @property
    def archived_at(self) -> datetime | None:
        return self._archived_at

    @property
    def locked_at(self) -> datetime | None:
        return self._locked_at

    @property
    def locked_by(self) -> UUID | None:
        return self._locked_by

    @property
    def is_locked(self) -> bool:
        return self._locked_at is not None

    @property
    def is_archived(self) -> bool:
        return self._status == FakturMasukanStatus.ARCHIVED

    @property
    def is_closed(self) -> bool:
        return self._status == FakturMasukanStatus.CLOSED

    @property
    def is_active(self) -> bool:
        return self._status not in [
            FakturMasukanStatus.CANCELLED,
            FakturMasukanStatus.VOID,
            FakturMasukanStatus.ARCHIVED,
            FakturMasukanStatus.CLOSED,
            FakturMasukanStatus.EXPIRED,
        ]

    @property
    def matched_transaction_id(self) -> UUID | None:
        return self._matched_transaction_id

    @property
    def period_id(self) -> UUID | None:
        return self._period_id

    @property
    def credit_amount(self) -> Decimal:
        return self._credit_amount

    @property
    def rejection_reason(self) -> str:
        return self._rejection_reason

    @property
    def cancellation_reason(self) -> str:
        return self._cancellation_reason

    @property
    def hash(self) -> str:
        return self._hash

    @property
    def is_expired(self) -> bool:
        expiry_date = self._tanggal_faktur + timedelta(days=EXPIRY_DAYS)
        return date.today() > expiry_date and self._status not in [
            FakturMasukanStatus.CANCELLED,
            FakturMasukanStatus.VOID,
            FakturMasukanStatus.CLOSED,
        ]

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    def create(self, created_by: UUID) -> FakturMasukan:
        self._status = FakturMasukanStatus.DRAFT
        self._updated_at = datetime.now()
        self._register_event(
            "faktur_masukan_created",
            {
                "faktur_id": str(self._faktur_id),
                "faktur_number": self._faktur_number,
                "created_by": str(created_by),
            },
        )
        return self

    def update(self, data: dict[str, Any], updated_by: UUID) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status not in [FakturMasukanStatus.DRAFT, FakturMasukanStatus.PENDING]:
            raise FakturMasukanInvalidStateError(f"Cannot modify faktur in status {self._status.value}")
        old_data = self.to_dict()
        if "dpp" in data:
            self._dpp = Decimal(str(data["dpp"]))
        if "ppn" in data:
            self._ppn = Decimal(str(data["ppn"]))
        if "ppn_bm" in data:
            self._ppn_bm = Decimal(str(data["ppn_bm"]))
        if "keterangan" in data:
            self._keterangan = data["keterangan"]
        if "alamat_penjual" in data:
            self._alamat_penjual = data["alamat_penjual"]
        if "npwp_pembeli" in data:
            self._npwp_pembeli = data["npwp_pembeli"]
        self._version += 1
        self._updated_at = datetime.now()
        self._calculate_hash()
        self._register_event(
            "faktur_masukan_updated",
            {
                "faktur_id": str(self._faktur_id),
                "old_data": old_data,
                "new_data": self.to_dict(),
                "updated_by": str(updated_by),
            },
        )
        return self

    def delete(self, deleted_by: UUID, permanent: bool = False) -> FakturMasukan:
        if permanent:
            self._status = FakturMasukanStatus.VOID
        else:
            self._status = FakturMasukanStatus.ARCHIVED
            self._archived_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_deleted",
            {
                "faktur_id": str(self._faktur_id),
                "permanent": permanent,
                "deleted_by": str(deleted_by),
            },
        )
        return self

    def restore(self, restored_by: UUID) -> FakturMasukan:
        if self._status not in [FakturMasukanStatus.ARCHIVED, FakturMasukanStatus.VOID]:
            raise FakturMasukanInvalidStateError(f"Cannot restore faktur in status {self._status.value}")
        self._status = FakturMasukanStatus.DRAFT
        self._archived_at = None
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_restored",
            {
                "faktur_id": str(self._faktur_id),
                "restored_by": str(restored_by),
            },
        )
        return self

    def activate(self, activated_by: UUID) -> FakturMasukan:
        if self._status != FakturMasukanStatus.DRAFT:
            raise FakturMasukanInvalidStateError(f"Cannot activate faktur in status {self._status.value}")
        self._status = FakturMasukanStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_activated",
            {
                "faktur_id": str(self._faktur_id),
                "activated_by": str(activated_by),
            },
        )
        return self

    def deactivate(self, deactivated_by: UUID) -> FakturMasukan:
        if self._status not in [FakturMasukanStatus.PENDING, FakturMasukanStatus.VALIDATED]:
            raise FakturMasukanInvalidStateError(f"Cannot deactivate faktur in status {self._status.value}")
        self._status = FakturMasukanStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_deactivated",
            {
                "faktur_id": str(self._faktur_id),
                "deactivated_by": str(deactivated_by),
            },
        )
        return self

    def lock(self, locked_by: UUID, reason: str = "") -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} already locked")
        self._locked_at = datetime.now()
        self._locked_by = locked_by
        self._status = FakturMasukanStatus.LOCKED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_locked",
            {
                "faktur_id": str(self._faktur_id),
                "locked_by": str(locked_by),
                "reason": reason,
            },
        )
        return self

    def unlock(self, unlocked_by: UUID) -> FakturMasukan:
        if not self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is not locked")
        self._locked_at = None
        self._locked_by = None
        self._status = FakturMasukanStatus.VALIDATED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_unlocked",
            {
                "faktur_id": str(self._faktur_id),
                "unlocked_by": str(unlocked_by),
            },
        )
        return self

    def validate(self, validator_id: UUID) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status != FakturMasukanStatus.PENDING:
            raise FakturMasukanInvalidStateError(f"Cannot validate faktur in status {self._status.value}")
        if self.is_expired:
            self._status = FakturMasukanStatus.EXPIRED
            raise FakturMasukanExpiredError(f"Faktur {self._faktur_number} has expired")
        expected_ppn = (self._dpp * DEFAULT_PPN_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if abs(self._ppn - expected_ppn) > Decimal("0.01"):
            logger.warning(f"PPN mismatch for {self._faktur_number}: expected {expected_ppn}, got {self._ppn}")
        self._status = FakturMasukanStatus.VALIDATED
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "faktur_masukan_validated",
            {
                "faktur_id": str(self._faktur_id),
                "validator_id": str(validator_id),
            },
        )
        return self

    def approve(self, approver_id: UUID, notes: str = "") -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status not in [FakturMasukanStatus.VALIDATED, FakturMasukanStatus.MATCHED]:
            raise FakturMasukanInvalidStateError(f"Cannot approve faktur in status {self._status.value}")
        if self.is_expired:
            self._status = FakturMasukanStatus.EXPIRED
            raise FakturMasukanExpiredError(f"Faktur {self._faktur_number} has expired")
        self._status = FakturMasukanStatus.APPROVED
        self._approved_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_approved",
            {
                "faktur_id": str(self._faktur_id),
                "approver_id": str(approver_id),
                "notes": notes,
            },
        )
        return self

    def reject(self, rejector_id: UUID, reason: str) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status not in [FakturMasukanStatus.PENDING, FakturMasukanStatus.VALIDATED]:
            raise FakturMasukanInvalidStateError(f"Cannot reject faktur in status {self._status.value}")
        self._status = FakturMasukanStatus.REJECTED
        self._rejection_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_rejected",
            {
                "faktur_id": str(self._faktur_id),
                "rejector_id": str(rejector_id),
                "reason": reason,
            },
        )
        return self

    def cancel(self, cancelled_by: UUID, reason: str) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status == FakturMasukanStatus.CLOSED:
            raise FakturMasukanInvalidStateError("Cannot cancel a closed faktur")
        if self._status == FakturMasukanStatus.CREDITED:
            raise FakturMasukanInvalidStateError("Cannot cancel a faktur that has been credited. Reverse credit first.")
        self._status = FakturMasukanStatus.CANCELLED
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_cancelled",
            {
                "faktur_id": str(self._faktur_id),
                "cancelled_by": str(cancelled_by),
                "reason": reason,
            },
        )
        return self

    def void(self, voided_by: UUID, reason: str) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        self._status = FakturMasukanStatus.VOID
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_voided",
            {
                "faktur_id": str(self._faktur_id),
                "voided_by": str(voided_by),
                "reason": reason,
            },
        )
        return self

    def post(self, posted_by: UUID) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status != FakturMasukanStatus.APPROVED:
            raise FakturMasukanInvalidStateError(f"Cannot post faktur in status {self._status.value}")
        self._status = FakturMasukanStatus.POSTED
        self._posted_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_posted",
            {
                "faktur_id": str(self._faktur_id),
                "posted_by": str(posted_by),
            },
        )
        return self

    def unpost(self, unposted_by: UUID) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status != FakturMasukanStatus.POSTED:
            raise FakturMasukanInvalidStateError(f"Cannot unpost faktur in status {self._status.value}")
        self._status = FakturMasukanStatus.APPROVED
        self._posted_at = None
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_unposted",
            {
                "faktur_id": str(self._faktur_id),
                "unposted_by": str(unposted_by),
            },
        )
        return self

    def reverse(self, reversed_by: UUID, reason: str) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status == FakturMasukanStatus.CREDITED:
            self.reverse_credit(reversed_by, reason)
        self._status = FakturMasukanStatus.REVERSED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_reversed",
            {
                "faktur_id": str(self._faktur_id),
                "reversed_by": str(reversed_by),
                "reason": reason,
            },
        )
        return self

    def close(self, closed_by: UUID) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status not in [FakturMasukanStatus.POSTED, FakturMasukanStatus.CREDITED]:
            raise FakturMasukanInvalidStateError(f"Cannot close faktur in status {self._status.value}")
        self._status = FakturMasukanStatus.CLOSED
        self._closed_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_closed",
            {
                "faktur_id": str(self._faktur_id),
                "closed_by": str(closed_by),
            },
        )
        return self

    def reopen(self, reopened_by: UUID) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status != FakturMasukanStatus.CLOSED:
            raise FakturMasukanInvalidStateError(f"Cannot reopen faktur in status {self._status.value}")
        self._status = FakturMasukanStatus.POSTED
        self._closed_at = None
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_reopened",
            {
                "faktur_id": str(self._faktur_id),
                "reopened_by": str(reopened_by),
            },
        )
        return self

    def archive(self, archived_by: UUID) -> FakturMasukan:
        if self._status != FakturMasukanStatus.CLOSED:
            raise FakturMasukanInvalidStateError(f"Cannot archive faktur in status {self._status.value}")
        self._status = FakturMasukanStatus.ARCHIVED
        self._archived_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_archived",
            {
                "faktur_id": str(self._faktur_id),
                "archived_by": str(archived_by),
            },
        )
        return self

    def unarchive(self, unarchived_by: UUID) -> FakturMasukan:
        if self._status != FakturMasukanStatus.ARCHIVED:
            raise FakturMasukanInvalidStateError(f"Cannot unarchive faktur in status {self._status.value}")
        self._status = FakturMasukanStatus.CLOSED
        self._archived_at = None
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_unarchived",
            {
                "faktur_id": str(self._faktur_id),
                "unarchived_by": str(unarchived_by),
            },
        )
        return self

    def sync(self, synced_by: UUID) -> FakturMasukan:
        self._status = FakturMasukanStatus.SYNCED
        self._synced_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_synced",
            {
                "faktur_id": str(self._faktur_id),
                "synced_by": str(synced_by),
            },
        )
        return self

    def download(self) -> FakturMasukan:
        self._synced_at = datetime.now()
        self._updated_at = datetime.now()
        return self

    def credit(self, period_id: UUID, credited_by: UUID, amount: Decimal | None = None) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status not in [FakturMasukanStatus.APPROVED, FakturMasukanStatus.POSTED]:
            raise FakturMasukanInvalidStateError(f"Cannot credit faktur in status {self._status.value}")
        credit_amount = amount or self._ppn
        if credit_amount > self._ppn:
            raise FakturMasukanValidationError(f"Credit amount {credit_amount} exceeds PPN amount {self._ppn}")
        self._period_id = period_id
        self._credit_amount = credit_amount
        self._credited_at = datetime.now()
        self._status = FakturMasukanStatus.CREDITED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_credited",
            {
                "faktur_id": str(self._faktur_id),
                "period_id": str(period_id),
                "credit_amount": float(credit_amount),
                "credited_by": str(credited_by),
            },
        )
        return self

    def reverse_credit(self, reversed_by: UUID, reason: str) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status != FakturMasukanStatus.CREDITED:
            raise FakturMasukanInvalidStateError(f"Cannot reverse credit for faktur in status {self._status.value}")
        self._period_id = None
        self._credit_amount = Decimal(0)
        self._credited_at = None
        self._status = FakturMasukanStatus.APPROVED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_credit_reversed",
            {
                "faktur_id": str(self._faktur_id),
                "reversed_by": str(reversed_by),
                "reason": reason,
            },
        )
        return self

    def calculate(self) -> dict[str, Decimal]:
        return {
            "dpp": self._dpp,
            "ppn": self._ppn,
            "ppn_bm": self._ppn_bm,
            "total": self.total_amount,
            "ppn_rate_percent": DEFAULT_PPN_RATE * 100,
        }

    def recalculate(self) -> FakturMasukan:
        self._ppn = (self._dpp * DEFAULT_PPN_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        return self

    def match(self, transaction_id: UUID, matched_by: UUID) -> FakturMasukan:
        if self.is_locked:
            raise FakturMasukanLockedError(f"Faktur {self._faktur_number} is locked")
        self._matched_transaction_id = transaction_id
        self._status = FakturMasukanStatus.MATCHED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_masukan_matched",
            {
                "faktur_id": str(self._faktur_id),
                "transaction_id": str(transaction_id),
                "matched_by": str(matched_by),
            },
        )
        return self

    def get_status(self) -> dict[str, Any]:
        return {
            "status": self._status.value,
            "is_locked": self.is_locked,
            "is_active": self.is_active,
            "is_expired": self.is_expired,
            "can_approve": self.can_transition(FakturMasukanStatus.APPROVED),
            "can_cancel": self.can_transition(FakturMasukanStatus.CANCELLED),
            "can_credit": self.can_transition(FakturMasukanStatus.CREDITED),
            "can_post": self.can_transition(FakturMasukanStatus.POSTED),
            "can_reverse": self.can_transition(FakturMasukanStatus.REVERSED),
            "can_close": self.can_transition(FakturMasukanStatus.CLOSED),
        }

    def get_history(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def snapshot(self) -> dict[str, Any]:
        return {
            "faktur_id": str(self._faktur_id),
            "faktur_number": self._faktur_number,
            "status": self._status.value,
            "version": self._version,
            "dpp": float(self._dpp),
            "ppn": float(self._ppn),
            "total": float(self.total_amount),
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "synced_at": self._synced_at.isoformat() if self._synced_at else None,
            "credited_at": self._credited_at.isoformat() if self._credited_at else None,
            "approved_at": self._approved_at.isoformat() if self._approved_at else None,
            "posted_at": self._posted_at.isoformat() if self._posted_at else None,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "closed_at": self._closed_at.isoformat() if self._closed_at else None,
            "archived_at": self._archived_at.isoformat() if self._archived_at else None,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "matched_transaction_id": str(self._matched_transaction_id) if self._matched_transaction_id else None,
            "period_id": str(self._period_id) if self._period_id else None,
            "credit_amount": float(self._credit_amount),
            "hash": self._hash,
        }

    def clone(self, new_faktur_number: str | None = None) -> FakturMasukan:
        new_number = new_faktur_number or f"{self._faktur_number}_COPY"
        return FakturMasukan(
            faktur_number=new_number,
            npwp_penjual=self._npwp_penjual,
            nama_penjual=self._nama_penjual,
            tanggal_faktur=self._tanggal_faktur,
            dpp=self._dpp,
            ppn=self._ppn,
            npwp_pembeli=self._npwp_pembeli,
            alamat_penjual=self._alamat_penjual,
            ppn_bm=self._ppn_bm,
            keterangan=f"COPY of {self._faktur_number}",
            xml_content=self._xml_content,
            status=FakturMasukanStatus.DRAFT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "faktur_id": str(self._faktur_id),
            "faktur_number": self._faktur_number,
            "npwp_penjual": self._npwp_penjual,
            "nama_penjual": self._nama_penjual,
            "alamat_penjual": self._alamat_penjual,
            "npwp_pembeli": self._npwp_pembeli,
            "tanggal_faktur": self._tanggal_faktur.isoformat(),
            "dpp": float(self._dpp),
            "ppn": float(self._ppn),
            "ppn_bm": float(self._ppn_bm),
            "total_amount": float(self.total_amount),
            "keterangan": self._keterangan,
            "status": self._status.value,
            "version": self._version,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "synced_at": self._synced_at.isoformat() if self._synced_at else None,
            "credited_at": self._credited_at.isoformat() if self._credited_at else None,
            "approved_at": self._approved_at.isoformat() if self._approved_at else None,
            "posted_at": self._posted_at.isoformat() if self._posted_at else None,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "closed_at": self._closed_at.isoformat() if self._closed_at else None,
            "archived_at": self._archived_at.isoformat() if self._archived_at else None,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "locked_by": str(self._locked_by) if self._locked_by else None,
            "matched_transaction_id": str(self._matched_transaction_id) if self._matched_transaction_id else None,
            "period_id": str(self._period_id) if self._period_id else None,
            "credit_amount": float(self._credit_amount),
            "rejection_reason": self._rejection_reason,
            "cancellation_reason": self._cancellation_reason,
            "hash": self._hash,
            "is_expired": self.is_expired,
            "is_locked": self.is_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FakturMasukan:
        return cls(
            faktur_id=UUID(data["faktur_id"]) if data.get("faktur_id") else None,
            faktur_number=data["faktur_number"],
            npwp_penjual=data["npwp_penjual"],
            nama_penjual=data["nama_penjual"],
            tanggal_faktur=date.fromisoformat(data["tanggal_faktur"]),
            dpp=Decimal(str(data["dpp"])),
            ppn=Decimal(str(data["ppn"])),
            npwp_pembeli=data.get("npwp_pembeli", ""),
            alamat_penjual=data.get("alamat_penjual", ""),
            ppn_bm=Decimal(str(data.get("ppn_bm", 0))),
            keterangan=data.get("keterangan", ""),
            xml_content=data.get("xml_content", ""),
            status=FakturMasukanStatus(data.get("status", "draft")),
            version=data.get("version", 1),
        )

    def audit_trail(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def can_transition(self, new_status: FakturMasukanStatus) -> bool:
        transitions = {
            FakturMasukanStatus.DRAFT: [FakturMasukanStatus.PENDING, FakturMasukanStatus.ARCHIVED, FakturMasukanStatus.VOID],
            FakturMasukanStatus.PENDING: [FakturMasukanStatus.VALIDATED, FakturMasukanStatus.REJECTED, FakturMasukanStatus.DRAFT, FakturMasukanStatus.CANCELLED],
            FakturMasukanStatus.VALIDATED: [FakturMasukanStatus.MATCHED, FakturMasukanStatus.REJECTED, FakturMasukanStatus.APPROVED, FakturMasukanStatus.DRAFT, FakturMasukanStatus.LOCKED],
            FakturMasukanStatus.MATCHED: [FakturMasukanStatus.APPROVED, FakturMasukanStatus.REJECTED, FakturMasukanStatus.VALIDATED],
            FakturMasukanStatus.APPROVED: [FakturMasukanStatus.POSTED, FakturMasukanStatus.CREDITED, FakturMasukanStatus.REJECTED, FakturMasukanStatus.CANCELLED],
            FakturMasukanStatus.POSTED: [FakturMasukanStatus.CREDITED, FakturMasukanStatus.REVERSED, FakturMasukanStatus.CLOSED, FakturMasukanStatus.CANCELLED],
            FakturMasukanStatus.CREDITED: [FakturMasukanStatus.REVERSED, FakturMasukanStatus.CLOSED, FakturMasukanStatus.CANCELLED],
            FakturMasukanStatus.REJECTED: [FakturMasukanStatus.DRAFT, FakturMasukanStatus.CANCELLED],
            FakturMasukanStatus.CANCELLED: [FakturMasukanStatus.ARCHIVED],
            FakturMasukanStatus.VOID: [],
            FakturMasukanStatus.REVERSED: [FakturMasukanStatus.DRAFT, FakturMasukanStatus.ARCHIVED],
            FakturMasukanStatus.CLOSED: [FakturMasukanStatus.REOPEN, FakturMasukanStatus.ARCHIVED],
            FakturMasukanStatus.ARCHIVED: [FakturMasukanStatus.CLOSED, FakturMasukanStatus.VOID],
            FakturMasukanStatus.LOCKED: [FakturMasukanStatus.VALIDATED],
            FakturMasukanStatus.ERROR: [FakturMasukanStatus.PENDING, FakturMasukanStatus.DRAFT],
            FakturMasukanStatus.SYNCED: [FakturMasukanStatus.VALIDATED, FakturMasukanStatus.ERROR],
            FakturMasukanStatus.EXPIRED: [FakturMasukanStatus.ARCHIVED, FakturMasukanStatus.CANCELLED],
        }
        return new_status in transitions.get(self._status, [])

    def transition(self, new_status: FakturMasukanStatus, actor_id: UUID, reason: str = "") -> FakturMasukan:
        if not self.can_transition(new_status):
            raise FakturMasukanInvalidStateError(f"Status transition invalid: {self._status.value} -> {new_status.value}")
        old_status = self._status
        self._status = new_status
        self._updated_at = datetime.now()
        self._version += 1
        self._history.append(
            {
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self._register_event(
            "faktur_masukan_status_changed",
            {
                "faktur_id": str(self._faktur_id),
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
            },
        )
        return self

    def register_event(self, event_type: str, event_data: dict[str, Any]) -> FakturMasukan:
        return self._register_event(event_type, event_data)

    def _register_event(self, event_type: str, event_data: dict[str, Any]) -> FakturMasukan:
        self._events.append(
            {
                "event_id": str(uuid4()),
                "event_type": event_type,
                "aggregate_id": str(self._faktur_id),
                "aggregate_type": "FakturMasukan",
                "occurred_at": datetime.now().isoformat(),
                "data": event_data,
            }
        )
        return self

    def get_events(self) -> list[dict[str, Any]]:
        return self._events.copy()

    def clear_events(self) -> FakturMasukan:
        self._events.clear()
        return self

    def version(self) -> int:
        return self._version

    def _calculate_hash(self) -> None:
        data = f"{self._faktur_id}{self._faktur_number}{self._npwp_penjual}{self._dpp}{self._ppn}{self._status.value}{self._version}"
        self._hash = hashlib.sha256(data.encode()).hexdigest()

    def _check_expiry(self) -> bool:
        if self.is_expired and self._status not in [FakturMasukanStatus.CANCELLED, FakturMasukanStatus.VOID]:
            self._status = FakturMasukanStatus.EXPIRED
            return True
        return False


# ============================================================================
# REPOSITORY INTERFACE
# ============================================================================
class FakturMasukanRepositoryPort:
    async def add(self, faktur: FakturMasukan) -> None:
        raise NotImplementedError
    async def save(self, faktur: FakturMasukan) -> None:
        raise NotImplementedError
    async def update(self, faktur: FakturMasukan) -> None:
        raise NotImplementedError
    async def delete(self, faktur_id: UUID) -> None:
        raise NotImplementedError
    async def exists(self, faktur_number: str) -> bool:
        raise NotImplementedError
    async def get_by_id(self, faktur_id: UUID) -> FakturMasukan | None:
        raise NotImplementedError
    async def get_by_number(self, faktur_number: str) -> FakturMasukan | None:
        raise NotImplementedError
    async def get_by_npwp(self, npwp: str, limit: int = 100) -> list[FakturMasukan]:
        raise NotImplementedError
    async def get_by_period(self, tahun: int, bulan: int, limit: int = 100) -> list[FakturMasukan]:
        raise NotImplementedError
    async def get_by_status(self, status: FakturMasukanStatus, limit: int = 100) -> list[FakturMasukan]:
        raise NotImplementedError
    async def get_all(self, limit: int = 1000, offset: int = 0) -> list[FakturMasukan]:
        raise NotImplementedError
    async def search(self, criteria: dict[str, Any], limit: int = 100) -> list[FakturMasukan]:
        raise NotImplementedError
    async def count(self, status: FakturMasukanStatus | None = None) -> int:
        raise NotImplementedError
    async def list(self, limit: int = 100, offset: int = 0) -> list[FakturMasukan]:
        raise NotImplementedError
    async def paginate(self, page: int = 1, per_page: int = 20) -> dict[str, Any]:
        raise NotImplementedError
    async def lock(self, faktur_id: UUID, locked_by: UUID) -> None:
        raise NotImplementedError
    async def unlock(self, faktur_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# FALLBACK REPOSITORY
# ============================================================================
class _FallbackTaxRepository:
    def __init__(self):
        self._faktur_store: dict[UUID, FakturMasukan] = {}
        self._faktur_by_number: dict[str, UUID] = {}

    async def get_faktur_masukan_by_number(self, faktur_number: str) -> dict[str, Any] | None:
        faktur_id = self._faktur_by_number.get(faktur_number)
        if faktur_id and faktur_id in self._faktur_store:
            return self._faktur_store[faktur_id].to_dict()
        return None

    async def get_faktur_masukan_by_id(self, faktur_id: UUID) -> dict[str, Any] | None:
        if faktur_id in self._faktur_store:
            return self._faktur_store[faktur_id].to_dict()
        return None

    async def save_faktur_masukan(self, **kwargs) -> UUID:
        faktur = FakturMasukan(
            faktur_number=kwargs["faktur_number"],
            npwp_penjual=kwargs["npwp_penjual"],
            nama_penjual=kwargs["nama_penjual"],
            tanggal_faktur=kwargs["tanggal_faktur"],
            dpp=kwargs["dpp"],
            ppn=kwargs["ppn"],
            npwp_pembeli=kwargs.get("npwp_pembeli", ""),
            alamat_penjual=kwargs.get("alamat_penjual", ""),
            ppn_bm=kwargs.get("ppn_bm", Decimal(0)),
            keterangan=kwargs.get("keterangan", ""),
            xml_content=kwargs.get("xml_content", ""),
            status=FakturMasukanStatus(kwargs.get("status", "draft")),
        )
        self._faktur_store[faktur.faktur_id] = faktur
        self._faktur_by_number[faktur.faktur_number] = faktur.faktur_id
        return faktur.faktur_id

    async def update_faktur_masukan_status(self, faktur_id: UUID, status: str) -> None:
        if faktur_id in self._faktur_store:
            self._faktur_store[faktur_id].transition(FakturMasukanStatus(status), UUID("00000000-0000-0000-0000-000000000000"))

    async def find_matching_purchase_transactions(self, npwp_supplier: str, invoice_date: date, amount: Decimal) -> list[Any]:
        return []

    async def record_ppn_credit(self, faktur_id: UUID, period_id: UUID, amount: Decimal, credited_by: UUID) -> None:
        if faktur_id in self._faktur_store:
            self._faktur_store[faktur_id].credit(period_id, credited_by, amount)

    async def reverse_ppn_credit(self, faktur_id: UUID, cancelled_by: UUID, reason: str) -> None:
        if faktur_id in self._faktur_store:
            self._faktur_store[faktur_id].reverse_credit(cancelled_by, reason)

    async def get_unprocessed_periods(self, npwp_perusahaan: str) -> list[dict[str, Any]]:
        return []


# ============================================================================
# FAKTUR MASUKAN PROCESSOR
# ============================================================================
class FakturMasukanProcessor:
    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._coretax_client = None
        self._tax_service = None
        self._file_storage = None
        self._cache: dict[str, Any] = {}
        self._init_file_storage()

    def _load_config(self) -> dict[str, Any]:
        if self._config:
            return self._config
        return {
            "coretax_djp": {
                "faktur_masukan": {
                    "download_enabled": True,
                    "auto_credit": False,
                    "file_storage_bucket": "coretax-faktur-masukan",
                    "cache_ttl_seconds": 3600,
                    "max_retry_attempts": 3,
                    "expiry_days": 90,
                }
            }
        }

    def _init_file_storage(self):
        try:
            from infrastructure.file_storage.s3_adapter import S3FileStorageAdapter
            bucket = self._load_config().get("coretax_djp", {}).get("faktur_masukan", {}).get("file_storage_bucket", "coretax-faktur-masukan")
            self._file_storage = S3FileStorageAdapter(bucket_name=bucket)
        except Exception as e:
            logger.warning(f"File storage not available for faktur masukan: {e}")

    async def _get_coretax_client(self):
        if self._coretax_client is None:
            self._coretax_client = await get_coretax_client()
        return self._coretax_client

    async def _get_tax_service(self):
        if self._tax_service is None:
            from application.service_layer.service_tax import TaxService
            try:
                from adapters.secondary_impl.sqlalchemy_tax_repository_impl import (
                    SQLAlchemyTaxRepository,
                )
                repo = SQLAlchemyTaxRepository()
            except ImportError:
                logger.warning("SQLAlchemyTaxRepository not available, using fallback")
                repo = _FallbackTaxRepository()
            self._tax_service = TaxService(repo)
        return self._tax_service

    def _parse_faktur_xml(self, xml_content: str) -> dict[str, Any]:
        try:
            root = ET.fromstring(xml_content)
            ns = {"efaktur": "http://www.djp.go.id/efaktur"}
            kepala = root.find(".//KepalaFaktur", ns) or root.find(".//KepalaFaktur")
            if kepala is None:
                raise ValueError("Invalid faktur XML: missing KepalaFaktur")
            nomor_faktur_elem = kepala.find("NomorFaktur")
            faktur_number = nomor_faktur_elem.text if nomor_faktur_elem is not None else ""
            tanggal_faktur_elem = kepala.find("TanggalFaktur")
            tanggal_faktur = datetime.strptime(tanggal_faktur_elem.text, "%Y-%m-%d").date() if tanggal_faktur_elem is not None else date.today()
            penjual = root.find(".//Penjual", ns) or root.find(".//Penjual")
            npwp_penjual = penjual.find("NPWP").text if penjual is not None else ""
            nama_penjual = penjual.find("Nama").text if penjual is not None else ""
            alamat_penjual = penjual.find("Alamat").text if penjual is not None else ""
            pembeli = root.find(".//Pembeli", ns) or root.find(".//Pembeli")
            npwp_pembeli = pembeli.find("NPWP").text if pembeli is not None else ""
            detail = root.find(".//DetailTransaksi", ns) or root.find(".//DetailTransaksi")
            dpp = Decimal(detail.find("DPP").text) if detail is not None else Decimal(0)
            ppn = Decimal(detail.find("PPN").text) if detail is not None else Decimal(0)
            ppn_bm = Decimal(detail.find("PPNBM").text) if detail is not None else Decimal(0)
            keterangan_elem = detail.find("Keterangan") if detail is not None else None
            keterangan = keterangan_elem.text if keterangan_elem is not None else ""
            return {
                "faktur_number": faktur_number,
                "tanggal_faktur": tanggal_faktur,
                "npwp_penjual": npwp_penjual,
                "nama_penjual": nama_penjual,
                "alamat_penjual": alamat_penjual,
                "npwp_pembeli": npwp_pembeli,
                "dpp": dpp,
                "ppn": ppn,
                "ppn_bm": ppn_bm,
                "keterangan": keterangan,
            }
        except ET.ParseError as e:
            logger.error(f"XML parsing error: {e}")
            raise ValueError(f"Invalid XML format: {e}")

    def _get_cache_key(self, faktur_number: str) -> str:
        return f"faktur_masukan:{faktur_number}"

    async def _get_cached(self, faktur_number: str) -> dict[str, Any] | None:
        key = self._get_cache_key(faktur_number)
        return self._cache.get(key)

    async def _set_cached(self, faktur_number: str, data: dict[str, Any]) -> None:
        ttl = self._load_config().get("coretax_djp", {}).get("faktur_masukan", {}).get("cache_ttl_seconds", CACHE_TTL_SECONDS)
        key = self._get_cache_key(faktur_number)
        self._cache[key] = data

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    async def create(self, faktur_data: dict[str, Any], created_by: UUID) -> dict[str, Any]:
        faktur = FakturMasukan(
            faktur_number=faktur_data["faktur_number"],
            npwp_penjual=faktur_data["npwp_penjual"],
            nama_penjual=faktur_data["nama_penjual"],
            tanggal_faktur=faktur_data["tanggal_faktur"],
            dpp=Decimal(str(faktur_data["dpp"])),
            ppn=Decimal(str(faktur_data["ppn"])),
            npwp_pembeli=faktur_data.get("npwp_pembeli", ""),
            alamat_penjual=faktur_data.get("alamat_penjual", ""),
            ppn_bm=Decimal(str(faktur_data.get("ppn_bm", 0))),
            keterangan=faktur_data.get("keterangan", ""),
            xml_content=faktur_data.get("xml_content", ""),
        )
        faktur.create(created_by)
        tax_service = await self._get_tax_service()
        faktur_id = await tax_service.save_faktur_masukan(**faktur.to_dict())
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "faktur_number": faktur.faktur_number,
            "status": faktur.status.value,
        }

    async def update(self, faktur_id: UUID, data: dict[str, Any], updated_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.update(data, updated_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        await self._set_cached(faktur.faktur_number, faktur.to_dict())
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "faktur_number": faktur.faktur_number,
            "status": faktur.status.value,
        }

    async def delete(self, faktur_id: UUID, deleted_by: UUID, permanent: bool = False) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.delete(deleted_by, permanent)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
        }

    async def restore(self, faktur_id: UUID, restored_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.restore(restored_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
        }

    async def activate(self, faktur_id: UUID, activated_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.activate(activated_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
        }

    async def deactivate(self, faktur_id: UUID, deactivated_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.deactivate(deactivated_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
        }

    async def lock(self, faktur_id: UUID, locked_by: UUID, reason: str = "") -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.lock(locked_by, reason)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "locked": True,
        }

    async def unlock(self, faktur_id: UUID, unlocked_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.unlock(unlocked_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "locked": False,
        }

    async def validate_faktur(self, faktur_id: UUID, validator_id: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        try:
            faktur.validate(validator_id)
        except FakturMasukanExpiredError as e:
            await tax_service.update_faktur_masukan_status(faktur_id, FakturMasukanStatus.EXPIRED.value)
            return {"success": False, "error": str(e), "status": "expired"}
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "valid": True,
            "status": faktur.status.value,
        }

    async def approve(self, faktur_id: UUID, approver_id: UUID, notes: str = "") -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.approve(approver_id, notes)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        if self._load_config().get("coretax_djp", {}).get("faktur_masukan", {}).get("auto_credit", False):
            await self.credit_ppn_masukan(faktur_id, None, approver_id)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "approved": True,
        }

    async def reject(self, faktur_id: UUID, rejector_id: UUID, reason: str) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.reject(rejector_id, reason)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "rejection_reason": reason,
        }

    async def cancel(self, faktur_id: UUID, cancelled_by: UUID, reason: str) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.cancel(cancelled_by, reason)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        client = await self._get_coretax_client()
        payload = {
            "faktur_number": faktur.faktur_number,
            "npwp": faktur.npwp_pembeli,
            "reason": reason,
        }
        try:
            await client.post(CORETAX_PM_CANCEL_ENDPOINT, payload)
        except Exception as e:
            logger.warning(f"Failed to cancel credit in Coretax: {e}")
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "cancelled": True,
        }

    async def void(self, faktur_id: UUID, voided_by: UUID, reason: str) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.void(voided_by, reason)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "voided": True,
        }

    async def post(self, faktur_id: UUID, posted_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.post(posted_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "posted": True,
        }

    async def unpost(self, faktur_id: UUID, unposted_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.unpost(unposted_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "posted": False,
        }

    async def reverse(self, faktur_id: UUID, reversed_by: UUID, reason: str) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.reverse(reversed_by, reason)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "reversed": True,
        }

    async def close(self, faktur_id: UUID, closed_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.close(closed_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "closed": True,
        }

    async def reopen(self, faktur_id: UUID, reopened_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.reopen(reopened_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "closed": False,
        }

    async def archive(self, faktur_id: UUID, archived_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.archive(archived_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "archived": True,
        }

    async def unarchive(self, faktur_id: UUID, unarchived_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.unarchive(unarchived_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "status": faktur.status.value,
            "archived": False,
        }

    async def sync(self, faktur_id: UUID, synced_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        client = await self._get_coretax_client()
        endpoint = f"{CORETAX_PM_DETAIL_ENDPOINT}/{faktur.npwp_pembeli}/{faktur.faktur_number}"
        try:
            response = await client.get(endpoint)
            if response.get("status") == "success":
                if "dpp" in response:
                    faktur.update({"dpp": Decimal(str(response["dpp"]))}, synced_by)
                if "ppn" in response:
                    faktur.update({"ppn": Decimal(str(response["ppn"]))}, synced_by)
                faktur.sync(synced_by)
                await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
                return {
                    "success": True,
                    "faktur_id": str(faktur_id),
                    "synced": True,
                    "data_from_coretax": response,
                }
            else:
                return {"success": False, "error": response.get("message", "Sync failed")}
        except Exception as e:
            logger.error(f"Failed to sync faktur {faktur.faktur_number}: {e}")
            return {"success": False, "error": str(e)}

    async def download_faktur_masukan(self, npwp_perusahaan: str, masa_pajak: int, tahun_pajak: int) -> list[dict[str, Any]]:
        client = await self._get_coretax_client()
        endpoint = f"{CORETAX_PM_LIST_ENDPOINT}/{npwp_perusahaan}/{tahun_pajak}/{masa_pajak:02d}"
        results = []
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.get(endpoint)
                faktur_list = response.get("data", [])
                for item in faktur_list:
                    faktur_number = item.get("nomor_faktur")
                    if faktur_number:
                        cached = await self._get_cached(faktur_number)
                        if cached:
                            results.append(cached)
                        else:
                            detail = await self._download_detail_faktur(npwp_perusahaan, faktur_number)
                            if detail:
                                await self._set_cached(faktur_number, detail)
                                results.append(detail)
                return results
            except CoretaxAuthError as e:
                logger.error(f"Coretax auth failed (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return []
            except Exception as e:
                logger.exception(f"Failed to download faktur masukan (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return []
        return []

    async def _download_detail_faktur(self, npwp_perusahaan: str, faktur_number: str) -> dict[str, Any] | None:
        client = await self._get_coretax_client()
        endpoint = f"{CORETAX_PM_DOWNLOAD_ENDPOINT}/{npwp_perusahaan}/{faktur_number}"
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.get(endpoint)
                xml_b64 = response.get("faktur_xml", "")
                if not xml_b64:
                    logger.warning(f"No XML content for faktur {faktur_number}")
                    return None
                xml_content = base64.b64decode(xml_b64).decode("utf-8")
                parsed = self._parse_faktur_xml(xml_content)
                parsed["raw_xml"] = xml_content
                parsed["faktur_number"] = faktur_number
                if self._file_storage:
                    file_name = f"faktur_masukan_{faktur_number}_{datetime.now().strftime('%Y%m%d')}.xml"
                    await self._file_storage.upload(
                        xml_content.encode("utf-8"),
                        file_name,
                        "application/xml",
                        metadata={"faktur_number": faktur_number, "npwp": npwp_perusahaan},
                    )
                    parsed["stored_uri"] = f"fs://{file_name}"
                return parsed
            except Exception as e:
                logger.error(f"Failed to download detail faktur {faktur_number} (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return None
        return None

    async def import_faktur_from_upload(self, xml_content: str, uploaded_by: UUID) -> dict[str, Any]:
        try:
            parsed = self._parse_faktur_xml(xml_content)
            tax_service = await self._get_tax_service()
            existing = await tax_service.get_faktur_masukan_by_number(parsed["faktur_number"])
            if existing:
                return {
                    "success": False,
                    "error": "Faktur already exists",
                    "faktur_number": parsed["faktur_number"],
                }
            faktur = FakturMasukan(
                faktur_number=parsed["faktur_number"],
                npwp_penjual=parsed["npwp_penjual"],
                nama_penjual=parsed["nama_penjual"],
                tanggal_faktur=parsed["tanggal_faktur"],
                dpp=parsed["dpp"],
                ppn=parsed["ppn"],
                npwp_pembeli=parsed.get("npwp_pembeli", ""),
                alamat_penjual=parsed.get("alamat_penjual", ""),
                ppn_bm=parsed.get("ppn_bm", Decimal(0)),
                keterangan=parsed.get("keterangan", ""),
                xml_content=xml_content,
                status=FakturMasukanStatus.PENDING,
            )
            faktur_id = await tax_service.save_faktur_masukan(**faktur.to_dict())
            if self._file_storage:
                file_name = f"faktur_masukan_{parsed['faktur_number']}.xml"
                await self._file_storage.upload(xml_content.encode("utf-8"), file_name, "application/xml")
            return {
                "success": True,
                "faktur_id": str(faktur_id),
                "faktur_number": parsed["faktur_number"],
                "status": faktur.status.value,
            }
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.exception("Import faktur masukan failed")
            return {"success": False, "error": str(e)}

    async def credit_ppn_masukan(self, faktur_id: UUID, period_id: UUID, credited_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        if faktur.status not in [FakturMasukanStatus.APPROVED, FakturMasukanStatus.POSTED]:
            return {
                "success": False,
                "error": f"Faktur status must be APPROVED or POSTED before credit, current: {faktur.status.value}",
            }
        client = await self._get_coretax_client()
        payload = {
            "faktur_number": faktur.faktur_number,
            "npwp": faktur.npwp_pembeli,
            "period_id": str(period_id),
            "amount": float(faktur.ppn),
        }
        try:
            response = await client.post(CORETAX_PM_CREDIT_ENDPOINT, payload)
            if response.get("status") == "success":
                faktur.credit(period_id, credited_by)
                await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
                await tax_service.record_ppn_credit(faktur_id, period_id, faktur.ppn, credited_by)
                return {
                    "success": True,
                    "message": "PPN Masukan credited",
                    "spt_adjustment": response,
                    "faktur_id": str(faktur_id),
                    "status": faktur.status.value,
                }
            else:
                return {"success": False, "error": response.get("message", "Unknown error")}
        except Exception as e:
            logger.error(f"Failed to credit PPN masukan: {e}")
            return {"success": False, "error": str(e)}

    async def reverse_credit(self, faktur_id: UUID, cancelled_by: UUID, reason: str) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        if faktur.status != FakturMasukanStatus.CREDITED:
            return {"success": False, "error": "Faktur not in CREDITED status"}
        client = await self._get_coretax_client()
        payload = {
            "faktur_number": faktur.faktur_number,
            "npwp": faktur.npwp_pembeli,
            "reason": reason,
        }
        try:
            response = await client.post(CORETAX_PM_CANCEL_ENDPOINT, payload)
            if response.get("status") == "success":
                faktur.reverse_credit(cancelled_by, reason)
                await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
                await tax_service.reverse_ppn_credit(faktur_id, cancelled_by, reason)
                return {
                    "success": True,
                    "message": "PPN Masukan credit cancelled",
                    "faktur_id": str(faktur_id),
                    "status": faktur.status.value,
                }
            else:
                return {"success": False, "error": response.get("message", "Unknown error")}
        except Exception as e:
            logger.error(f"Failed to cancel credit: {e}")
            return {"success": False, "error": str(e)}

    async def match_faktur(self, faktur_id: UUID, transaction_id: UUID, matched_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.match(transaction_id, matched_by)
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "matched_transaction_id": str(transaction_id),
            "status": faktur.status.value,
        }

    async def calculate_faktur(self, faktur_id: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        return faktur.calculate()

    async def recalculate_faktur(self, faktur_id: UUID, recalculated_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.recalculate()
        await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "dpp": float(faktur.dpp),
            "ppn": float(faktur.ppn),
            "total": float(faktur.total_amount),
        }

    async def get_status(self, faktur_id: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        return faktur.get_status()

    async def get_history(self, faktur_id: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "history": faktur.get_history(),
        }

    async def snapshot(self, faktur_id: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        return faktur.snapshot()

    async def clone_faktur(self, faktur_id: UUID, new_faktur_number: str, cloned_by: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        new_faktur = faktur.clone(new_faktur_number)
        new_faktur.create(cloned_by)
        new_faktur_id = await tax_service.save_faktur_masukan(**new_faktur.to_dict())
        return {
            "success": True,
            "original_faktur_id": str(faktur_id),
            "new_faktur_id": str(new_faktur_id),
            "new_faktur_number": new_faktur.faktur_number,
        }

    async def to_dict(self, faktur_id: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        return existing

    async def audit_trail(self, faktur_id: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "audit_trail": faktur.audit_trail(),
        }

    async def can_transition(self, faktur_id: UUID, new_status: str) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        can = faktur.can_transition(FakturMasukanStatus(new_status))
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "current_status": faktur.status.value,
            "target_status": new_status,
            "can_transition": can,
        }

    async def transition(self, faktur_id: UUID, new_status: str, actor_id: UUID, reason: str = "") -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        try:
            faktur.transition(FakturMasukanStatus(new_status), actor_id, reason)
            await tax_service.update_faktur_masukan_status(faktur_id, faktur.status.value)
            return {
                "success": True,
                "faktur_id": str(faktur_id),
                "from_status": existing["status"],
                "to_status": new_status,
                "actor_id": str(actor_id),
            }
        except FakturMasukanInvalidStateError as e:
            return {"success": False, "error": str(e)}

    async def register_event(self, faktur_id: UUID, event_type: str, event_data: dict[str, Any]) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.register_event(event_type, event_data)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "events": faktur.get_events(),
        }

    async def get_events(self, faktur_id: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "events": faktur.get_events(),
        }

    async def clear_events(self, faktur_id: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        faktur.clear_events()
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "events_cleared": True,
        }

    async def version(self, faktur_id: UUID) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        existing = await tax_service.get_faktur_masukan_by_id(faktur_id)
        if not existing:
            return {"success": False, "error": "Faktur not found"}
        faktur = FakturMasukan.from_dict(existing)
        return {
            "success": True,
            "faktur_id": str(faktur_id),
            "version": faktur.version(),
        }

    # ========================================================================
    # Batch Operations
    # ========================================================================
    async def sync_faktur_masukan_periodic(self, npwp_perusahaan: str) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        periods = await tax_service.get_unprocessed_periods(npwp_perusahaan)
        results = []
        for period in periods:
            downloaded = await self.download_faktur_masukan(npwp_perusahaan, period["month"], period["year"])
            for faktur_data in downloaded:
                existing = await tax_service.get_faktur_masukan_by_number(faktur_data["faktur_number"])
                if not existing:
                    faktur = FakturMasukan(
                        faktur_number=faktur_data["faktur_number"],
                        npwp_penjual=faktur_data["npwp_penjual"],
                        nama_penjual=faktur_data["nama_penjual"],
                        tanggal_faktur=faktur_data["tanggal_faktur"],
                        dpp=faktur_data["dpp"],
                        ppn=faktur_data["ppn"],
                        npwp_pembeli=faktur_data.get("npwp_pembeli", ""),
                        alamat_penjual=faktur_data.get("alamat_penjual", ""),
                        ppn_bm=faktur_data.get("ppn_bm", Decimal(0)),
                        keterangan=faktur_data.get("keterangan", ""),
                        xml_content=faktur_data.get("raw_xml", ""),
                        status=FakturMasukanStatus.SYNCED,
                    )
                    await tax_service.save_faktur_masukan(**faktur.to_dict())
                    results.append(faktur_data["faktur_number"])
        return {
            "synced_count": len(results),
            "faktur_numbers": results,
            "periods_processed": len(periods),
        }

    # ========================================================================
    # Legacy / Test Methods
    # ========================================================================
    def _check_expiry(self, faktur_data: dict[str, Any]) -> bool:
        tanggal_faktur = faktur_data.get("tanggal_faktur")
        if not tanggal_faktur:
            return False
        today = date.today()
        if isinstance(tanggal_faktur, date):
            expiry_date = tanggal_faktur + timedelta(days=EXPIRY_DAYS)
            return today > expiry_date
        return False

    def approve(self, faktur_data: dict[str, Any]) -> Any:
        if self._check_expiry(faktur_data):
            raise ValueError("Faktur sudah melebihi batas waktu 3 bulan")
        class ApprovalResult:
            def __init__(self):
                self.status = "APPROVED"
                self.pengkreditan_allowed = True
        return ApprovalResult()


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================
_processor: FakturMasukanProcessor | None = None

async def get_faktur_masukan_processor(config: dict | None = None) -> FakturMasukanProcessor:
    global _processor
    if _processor is None:
        _processor = FakturMasukanProcessor(config=config)
    return _processor

__all__ = [
    "PM_STATUS",
    "FakturMasukan",
    "FakturMasukanError",
    "FakturMasukanInvalidStateError",
    "FakturMasukanLockedError",
    "FakturMasukanNotFoundError",
    "FakturMasukanProcessor",
    "FakturMasukanStatus",
    "FakturMasukanValidationError",
    "get_faktur_masukan_processor",
]
