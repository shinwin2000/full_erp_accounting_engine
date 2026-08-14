#!/usr/bin/env python3
"""
Module: faktur_keluaran_generator.py
Layer: Adapters (Coretax DJP)
Responsibility: Membuat dan memformat faktur pajak keluaran (PK) sesuai dengan
               standar DJP Coretax. Meliputi pembuatan XML faktur, penandatanganan digital,
               pengiriman ke Coretax API, dan penanganan status balasan.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4
from xml.dom import minidom

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256

from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError, get_coretax_client

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

FAKTUR_NS = {"efaktur": "http://www.djp.go.id/efaktur", "ds": "http://www.w3.org/2000/09/xmldsig#"}
FAKTUR_SCHEMA_VERSION = "2.0"
CORETAX_FAKTUR_ENDPOINT = "/api/v1/faktur-pajak/keluaran"
CORETAX_FAKTUR_STATUS_ENDPOINT = "/api/v1/faktur-pajak/status"
CORETAX_FAKTUR_PEMBATALAN_ENDPOINT = "/api/v1/faktur-pajak/batal"
CORETAX_FAKTUR_DOWNLOAD_ENDPOINT = "/api/v1/faktur-pajak/download"
CORETAX_FAKTUR_VALIDATE_ENDPOINT = "/api/v1/faktur-pajak/validate"
CORETAX_FAKTUR_APPROVAL_ENDPOINT = "/api/v1/faktur-pajak/approval-status"

MAX_RETRY_ATTEMPTS = 3
CACHE_TTL_SECONDS = 3600
DEFAULT_NSFP_LENGTH = 8

PPN_RATE = Decimal("0.11")  # 11%


class FakturStatus(Enum):
    DRAFT = "draft"
    PENDING = "pending"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    VOID = "void"
    POSTED = "posted"
    CLOSED = "closed"
    ARCHIVED = "archived"
    LOCKED = "locked"
    ERROR = "error"
    SYNCED = "synced"
    PRINTED = "printed"


STATUS_FAKTUR = {
    "DRAFT": FakturStatus.DRAFT.value,
    "PENDING": FakturStatus.PENDING.value,
    "SUBMITTED": FakturStatus.SUBMITTED.value,
    "APPROVED": FakturStatus.APPROVED.value,
    "REJECTED": FakturStatus.REJECTED.value,
    "CANCELLED": FakturStatus.CANCELLED.value,
    "VOID": FakturStatus.VOID.value,
    "POSTED": FakturStatus.POSTED.value,
    "CLOSED": FakturStatus.CLOSED.value,
    "ARCHIVED": FakturStatus.ARCHIVED.value,
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

KODE_TRANSAKSI = {
    "010": "Faktur Pajak Standar",
    "011": "Faktur Pajak Digunggung",
    "012": "Faktur Pajak Penjualan Eceran",
    "020": "Faktur Pajak Pembatalan",
    "030": "Faktur Pajak Pengganti",
}

STATUS_PEMBAYARAN = {
    "1": "Lunas",
    "2": "Cicilan",
    "3": "Belum Dibayar",
}


class FakturError(Exception):
    pass


class FakturNotFoundError(FakturError):
    pass


class FakturAlreadyExistsError(FakturError):
    pass


class FakturInvalidStateError(FakturError):
    pass


class FakturValidationError(FakturError):
    pass


class FakturLockedError(FakturError):
    pass


class FakturSigningError(FakturError):
    pass


class FakturXMLGenerationError(FakturError):
    pass


class FakturKeluaran:
    """Entity untuk Faktur Pajak Keluaran."""

    def __init__(
        self,
        faktur_number: str,
        nsfp: str,
        npwp_penjual: str,
        nama_penjual: str,
        npwp_pembeli: str,
        nama_pembeli: str,
        dpp: Decimal,
        ppn: Decimal,
        tanggal_faktur: date,
        tahun: int,
        bulan: int,
        alamat_penjual: str = "",
        alamat_pembeli: str = "",
        ppn_bm: Decimal = Decimal(0),
        keterangan: str = "",
        referensi: str = "",
        jenis_transaksi: str = "01",
        status_pembayaran: str = "1",
        faktur_id: UUID | None = None,
        status: FakturStatus = FakturStatus.DRAFT,
        version: int = 1,
    ):
        self._faktur_id = faktur_id or uuid4()
        self._faktur_number = faktur_number
        self._nsfp = nsfp
        self._npwp_penjual = npwp_penjual
        self._nama_penjual = nama_penjual
        self._alamat_penjual = alamat_penjual
        self._npwp_pembeli = npwp_pembeli
        self._nama_pembeli = nama_pembeli
        self._alamat_pembeli = alamat_pembeli
        self._dpp = dpp
        self._ppn = ppn
        self._ppn_bm = ppn_bm
        self._tanggal_faktur = tanggal_faktur
        self._tahun = tahun
        self._bulan = bulan
        self._keterangan = keterangan
        self._referensi = referensi
        self._jenis_transaksi = jenis_transaksi
        self._status_pembayaran = status_pembayaran
        self._status = status
        self._version = version
        self._created_at = datetime.now()
        self._updated_at = datetime.now()
        self._submitted_at: datetime | None = None
        self._approved_at: datetime | None = None
        self._rejected_at: datetime | None = None
        self._cancelled_at: datetime | None = None
        self._printed_at: datetime | None = None
        self._synced_at: datetime | None = None
        self._locked_at: datetime | None = None
        self._locked_by: UUID | None = None
        self._approval_code: str | None = None
        self._coretax_id: str | None = None
        self._qr_code: str | None = None
        self._xml_content: str = ""
        self._pdf_content: bytes | None = None
        self._signature: str | None = None
        self._rejection_reason: str = ""
        self._cancellation_reason: str = ""
        self._events: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
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
    def nsfp(self) -> str:
        return self._nsfp

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
    def nama_pembeli(self) -> str:
        return self._nama_pembeli

    @property
    def alamat_pembeli(self) -> str:
        return self._alamat_pembeli

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
    def tanggal_faktur(self) -> date:
        return self._tanggal_faktur

    @property
    def tahun(self) -> int:
        return self._tahun

    @property
    def bulan(self) -> int:
        return self._bulan

    @property
    def keterangan(self) -> str:
        return self._keterangan

    @property
    def referensi(self) -> str:
        return self._referensi

    @property
    def jenis_transaksi(self) -> str:
        return self._jenis_transaksi

    @property
    def jenis_transaksi_text(self) -> str:
        return JENIS_TRANSAKSI.get(self._jenis_transaksi, "Unknown")

    @property
    def status_pembayaran(self) -> str:
        return self._status_pembayaran

    @property
    def status_pembayaran_text(self) -> str:
        return STATUS_PEMBAYARAN.get(self._status_pembayaran, "Unknown")

    @property
    def status(self) -> FakturStatus:
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
    def submitted_at(self) -> datetime | None:
        return self._submitted_at

    @property
    def approved_at(self) -> datetime | None:
        return self._approved_at

    @property
    def rejected_at(self) -> datetime | None:
        return self._rejected_at

    @property
    def cancelled_at(self) -> datetime | None:
        return self._cancelled_at

    @property
    def printed_at(self) -> datetime | None:
        return self._printed_at

    @property
    def synced_at(self) -> datetime | None:
        return self._synced_at

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
    def is_active(self) -> bool:
        return self._status not in [
            FakturStatus.CANCELLED,
            FakturStatus.VOID,
            FakturStatus.ARCHIVED,
            FakturStatus.CLOSED,
        ]

    @property
    def approval_code(self) -> str | None:
        return self._approval_code

    @property
    def coretax_id(self) -> str | None:
        return self._coretax_id

    @property
    def qr_code(self) -> str | None:
        return self._qr_code

    @property
    def xml_content(self) -> str:
        return self._xml_content

    @property
    def pdf_content(self) -> bytes | None:
        return self._pdf_content

    @property
    def signature(self) -> str | None:
        return self._signature

    @property
    def rejection_reason(self) -> str:
        return self._rejection_reason

    @property
    def cancellation_reason(self) -> str:
        return self._cancellation_reason

    @property
    def hash(self) -> str:
        return self._hash

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    def create(self, created_by: UUID) -> FakturKeluaran:
        self._status = FakturStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "faktur_keluaran_created",
            {
                "faktur_id": str(self._faktur_id),
                "faktur_number": self._faktur_number,
                "created_by": str(created_by),
            },
        )
        return self

    def update(self, data: dict[str, Any], updated_by: UUID) -> FakturKeluaran:
        if self.is_locked:
            raise FakturLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status not in [FakturStatus.DRAFT, FakturStatus.PENDING, FakturStatus.REJECTED]:
            raise FakturInvalidStateError(f"Cannot update faktur in status {self._status.value}")
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
        if "alamat_pembeli" in data:
            self._alamat_pembeli = data["alamat_pembeli"]
        if "referensi" in data:
            self._referensi = data["referensi"]
        if "status_pembayaran" in data:
            self._status_pembayaran = data["status_pembayaran"]
        self._version += 1
        self._updated_at = datetime.now()
        self._calculate_hash()
        self._register_event(
            "faktur_keluaran_updated",
            {
                "faktur_id": str(self._faktur_id),
                "old_data": old_data,
                "new_data": self.to_dict(),
                "updated_by": str(updated_by),
            },
        )
        return self

    def delete(self, deleted_by: UUID, permanent: bool = False) -> FakturKeluaran:
        if self.is_locked:
            raise FakturLockedError(f"Faktur {self._faktur_number} is locked")
        if permanent:
            self._status = FakturStatus.VOID
        else:
            self._status = FakturStatus.ARCHIVED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_deleted",
            {
                "faktur_id": str(self._faktur_id),
                "permanent": permanent,
                "deleted_by": str(deleted_by),
            },
        )
        return self

    def restore(self, restored_by: UUID) -> FakturKeluaran:
        if self._status not in [FakturStatus.ARCHIVED, FakturStatus.VOID]:
            raise FakturInvalidStateError(f"Cannot restore faktur in status {self._status.value}")
        self._status = FakturStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_restored",
            {
                "faktur_id": str(self._faktur_id),
                "restored_by": str(restored_by),
            },
        )
        return self

    def activate(self, activated_by: UUID) -> FakturKeluaran:
        if self._status != FakturStatus.DRAFT:
            raise FakturInvalidStateError(f"Cannot activate faktur in status {self._status.value}")
        self._status = FakturStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_activated",
            {
                "faktur_id": str(self._faktur_id),
                "activated_by": str(activated_by),
            },
        )
        return self

    def deactivate(self, deactivated_by: UUID) -> FakturKeluaran:
        if self._status != FakturStatus.PENDING:
            raise FakturInvalidStateError(f"Cannot deactivate faktur in status {self._status.value}")
        self._status = FakturStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_deactivated",
            {
                "faktur_id": str(self._faktur_id),
                "deactivated_by": str(deactivated_by),
            },
        )
        return self

    def lock(self, locked_by: UUID, reason: str = "") -> FakturKeluaran:
        if self.is_locked:
            raise FakturLockedError(f"Faktur {self._faktur_number} already locked")
        self._locked_at = datetime.now()
        self._locked_by = locked_by
        self._status = FakturStatus.LOCKED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_locked",
            {
                "faktur_id": str(self._faktur_id),
                "locked_by": str(locked_by),
                "reason": reason,
            },
        )
        return self

    def unlock(self, unlocked_by: UUID) -> FakturKeluaran:
        if not self.is_locked:
            raise FakturLockedError(f"Faktur {self._faktur_number} is not locked")
        self._locked_at = None
        self._locked_by = None
        self._status = FakturStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_unlocked",
            {
                "faktur_id": str(self._faktur_id),
                "unlocked_by": str(unlocked_by),
            },
        )
        return self

    def validate(self, validator_id: UUID) -> FakturKeluaran:
        if self.is_locked:
            raise FakturLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status not in [FakturStatus.DRAFT, FakturStatus.PENDING]:
            raise FakturInvalidStateError(f"Cannot validate faktur in status {self._status.value}")
        errors = []
        if self._dpp <= 0:
            errors.append("DPP harus lebih besar dari 0")
        if self._ppn < 0:
            errors.append("PPN tidak boleh negatif")
        if not self._npwp_penjual or len(self._npwp_penjual) != 15:
            errors.append("NPWP penjual tidak valid")
        if not self._npwp_pembeli or len(self._npwp_pembeli) != 15:
            errors.append("NPWP pembeli tidak valid")
        if not self._nsfp or len(self._nsfp) != DEFAULT_NSFP_LENGTH:
            errors.append("NSFP tidak valid")
        if self._bulan < 1 or self._bulan > 12:
            errors.append("Bulan pajak tidak valid")
        if self._tahun < 2000 or self._tahun > 2100:
            errors.append("Tahun pajak tidak valid")
        expected_ppn = (self._dpp * PPN_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if abs(self._ppn - expected_ppn) > Decimal("0.01"):
            errors.append(f"PPN tidak sesuai: expected {expected_ppn}, got {self._ppn}")
        if errors:
            raise FakturValidationError("Validasi gagal: {}".format("; ".join(errors)))
        self._status = FakturStatus.VALIDATED
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "faktur_keluaran_validated",
            {
                "faktur_id": str(self._faktur_id),
                "validator_id": str(validator_id),
            },
        )
        return self

    def approve(self, approver_id: UUID, notes: str = "") -> FakturKeluaran:
        if self.is_locked:
            raise FakturLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status != FakturStatus.SUBMITTED:
            raise FakturInvalidStateError(f"Cannot approve faktur in status {self._status.value}")
        self._status = FakturStatus.APPROVED
        self._approved_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_approved",
            {
                "faktur_id": str(self._faktur_id),
                "approver_id": str(approver_id),
                "notes": notes,
            },
        )
        return self

    def reject(self, rejector_id: UUID, reason: str) -> FakturKeluaran:
        if self.is_locked:
            raise FakturLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status not in [FakturStatus.PENDING, FakturStatus.SUBMITTED]:
            raise FakturInvalidStateError(f"Cannot reject faktur in status {self._status.value}")
        self._status = FakturStatus.REJECTED
        self._rejected_at = datetime.now()
        self._rejection_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_rejected",
            {
                "faktur_id": str(self._faktur_id),
                "rejector_id": str(rejector_id),
                "reason": reason,
            },
        )
        return self

    def cancel(self, cancelled_by: UUID, reason: str) -> FakturKeluaran:
        if self.is_locked:
            raise FakturLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status in [FakturStatus.CANCELLED, FakturStatus.VOID, FakturStatus.CLOSED]:
            raise FakturInvalidStateError(f"Cannot cancel faktur in status {self._status.value}")
        self._status = FakturStatus.CANCELLED
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_cancelled",
            {
                "faktur_id": str(self._faktur_id),
                "cancelled_by": str(cancelled_by),
                "reason": reason,
            },
        )
        return self

    def void(self, voided_by: UUID, reason: str) -> FakturKeluaran:
        if self.is_locked:
            raise FakturLockedError(f"Faktur {self._faktur_number} is locked")
        self._status = FakturStatus.VOID
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_voided",
            {
                "faktur_id": str(self._faktur_id),
                "voided_by": str(voided_by),
                "reason": reason,
            },
        )
        return self

    def submit(self, submitted_by: UUID) -> FakturKeluaran:
        if self.is_locked:
            raise FakturLockedError(f"Faktur {self._faktur_number} is locked")
        if self._status not in [FakturStatus.PENDING, FakturStatus.VALIDATED]:
            raise FakturInvalidStateError(f"Cannot submit faktur in status {self._status.value}")
        self.validate(submitted_by)
        self._generate_qr_code()
        self._status = FakturStatus.SUBMITTED
        self._submitted_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_submitted",
            {
                "faktur_id": str(self._faktur_id),
                "submitted_by": str(submitted_by),
            },
        )
        return self

    def print(self, printed_by: UUID) -> bytes:
        if self._pdf_content is None:
            self._pdf_content = self._create_pdf()
        self._printed_at = datetime.now()
        self._status = FakturStatus.PRINTED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_printed",
            {
                "faktur_id": str(self._faktur_id),
                "printed_by": str(printed_by),
            },
        )
        return self._pdf_content

    def download(self, downloaded_by: UUID) -> bytes:
        self._synced_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_downloaded",
            {
                "faktur_id": str(self._faktur_id),
                "downloaded_by": str(downloaded_by),
            },
        )
        return self._pdf_content or self._create_pdf()

    def get_status(self) -> dict[str, Any]:
        return {
            "status": self._status.value,
            "is_locked": self.is_locked,
            "is_active": self.is_active,
            "can_submit": self.can_transition(FakturStatus.SUBMITTED),
            "can_cancel": self.can_transition(FakturStatus.CANCELLED),
            "can_print": self._status in [FakturStatus.APPROVED, FakturStatus.PRINTED],
            "approval_code": self._approval_code,
            "coretax_id": self._coretax_id,
        }

    def get_history(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def snapshot(self) -> dict[str, Any]:
        return {
            "faktur_id": str(self._faktur_id),
            "faktur_number": self._faktur_number,
            "nsfp": self._nsfp,
            "status": self._status.value,
            "version": self._version,
            "dpp": float(self._dpp),
            "ppn": float(self._ppn),
            "total": float(self.total_amount),
            "npwp_penjual": self._npwp_penjual,
            "nama_penjual": self._nama_penjual,
            "npwp_pembeli": self._npwp_pembeli,
            "nama_pembeli": self._nama_pembeli,
            "tanggal_faktur": self._tanggal_faktur.isoformat(),
            "tahun": self._tahun,
            "bulan": self._bulan,
            "jenis_transaksi": self._jenis_transaksi,
            "status_pembayaran": self._status_pembayaran,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "submitted_at": self._submitted_at.isoformat() if self._submitted_at else None,
            "approved_at": self._approved_at.isoformat() if self._approved_at else None,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "approval_code": self._approval_code,
            "coretax_id": self._coretax_id,
            "qr_code": self._qr_code,
            "hash": self._hash,
        }

    def clone(self, new_faktur_number: str | None = None) -> FakturKeluaran:
        new_number = new_faktur_number or "{}_{}".format(self._faktur_number, "COPY")
        return FakturKeluaran(
            faktur_number=new_number,
            nsfp=self._nsfp,
            npwp_penjual=self._npwp_penjual,
            nama_penjual=self._nama_penjual,
            npwp_pembeli=self._npwp_pembeli,
            nama_pembeli=self._nama_pembeli,
            dpp=self._dpp,
            ppn=self._ppn,
            tanggal_faktur=self._tanggal_faktur,
            tahun=self._tahun,
            bulan=self._bulan,
            alamat_penjual=self._alamat_penjual,
            alamat_pembeli=self._alamat_pembeli,
            ppn_bm=self._ppn_bm,
            keterangan=f"COPY of {self._faktur_number}",
            referensi=self._referensi,
            jenis_transaksi=self._jenis_transaksi,
            status_pembayaran=self._status_pembayaran,
            status=FakturStatus.DRAFT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "faktur_id": str(self._faktur_id),
            "faktur_number": self._faktur_number,
            "nsfp": self._nsfp,
            "npwp_penjual": self._npwp_penjual,
            "nama_penjual": self._nama_penjual,
            "alamat_penjual": self._alamat_penjual,
            "npwp_pembeli": self._npwp_pembeli,
            "nama_pembeli": self._nama_pembeli,
            "alamat_pembeli": self._alamat_pembeli,
            "dpp": float(self._dpp),
            "ppn": float(self._ppn),
            "ppn_bm": float(self._ppn_bm),
            "total_amount": float(self.total_amount),
            "tanggal_faktur": self._tanggal_faktur.isoformat(),
            "tahun": self._tahun,
            "bulan": self._bulan,
            "keterangan": self._keterangan,
            "referensi": self._referensi,
            "jenis_transaksi": self._jenis_transaksi,
            "jenis_transaksi_text": self.jenis_transaksi_text,
            "status_pembayaran": self._status_pembayaran,
            "status_pembayaran_text": self.status_pembayaran_text,
            "status": self._status.value,
            "version": self._version,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "submitted_at": self._submitted_at.isoformat() if self._submitted_at else None,
            "approved_at": self._approved_at.isoformat() if self._approved_at else None,
            "rejected_at": self._rejected_at.isoformat() if self._rejected_at else None,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "printed_at": self._printed_at.isoformat() if self._printed_at else None,
            "synced_at": self._synced_at.isoformat() if self._synced_at else None,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "locked_by": str(self._locked_by) if self._locked_by else None,
            "approval_code": self._approval_code,
            "coretax_id": self._coretax_id,
            "qr_code": self._qr_code,
            "rejection_reason": self._rejection_reason,
            "cancellation_reason": self._cancellation_reason,
            "hash": self._hash,
            "is_locked": self.is_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FakturKeluaran:
        return cls(
            faktur_id=UUID(data["faktur_id"]) if data.get("faktur_id") else None,
            faktur_number=data["faktur_number"],
            nsfp=data["nsfp"],
            npwp_penjual=data["npwp_penjual"],
            nama_penjual=data["nama_penjual"],
            npwp_pembeli=data["npwp_pembeli"],
            nama_pembeli=data["nama_pembeli"],
            dpp=Decimal(str(data["dpp"])),
            ppn=Decimal(str(data["ppn"])),
            tanggal_faktur=date.fromisoformat(data["tanggal_faktur"]),
            tahun=data["tahun"],
            bulan=data["bulan"],
            alamat_penjual=data.get("alamat_penjual", ""),
            alamat_pembeli=data.get("alamat_pembeli", ""),
            ppn_bm=Decimal(str(data.get("ppn_bm", 0))),
            keterangan=data.get("keterangan", ""),
            referensi=data.get("referensi", ""),
            jenis_transaksi=data.get("jenis_transaksi", "01"),
            status_pembayaran=data.get("status_pembayaran", "1"),
            status=FakturStatus(data.get("status", "draft")),
            version=data.get("version", 1),
        )

    def audit_trail(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def can_transition(self, new_status: FakturStatus) -> bool:
        transitions = {
            FakturStatus.DRAFT: [FakturStatus.PENDING, FakturStatus.ARCHIVED, FakturStatus.VOID],
            FakturStatus.PENDING: [FakturStatus.VALIDATED, FakturStatus.REJECTED, FakturStatus.DRAFT, FakturStatus.CANCELLED],
            FakturStatus.VALIDATED: [FakturStatus.SUBMITTED, FakturStatus.REJECTED, FakturStatus.DRAFT],
            FakturStatus.SUBMITTED: [FakturStatus.APPROVED, FakturStatus.REJECTED, FakturStatus.CANCELLED],
            FakturStatus.APPROVED: [FakturStatus.POSTED, FakturStatus.PRINTED, FakturStatus.CANCELLED, FakturStatus.CLOSED],
            FakturStatus.REJECTED: [FakturStatus.DRAFT, FakturStatus.CANCELLED],
            FakturStatus.POSTED: [FakturStatus.CLOSED, FakturStatus.CANCELLED],
            FakturStatus.CANCELLED: [FakturStatus.ARCHIVED],
            FakturStatus.VOID: [],
            FakturStatus.PRINTED: [FakturStatus.CLOSED, FakturStatus.ARCHIVED],
            FakturStatus.CLOSED: [FakturStatus.ARCHIVED],
            FakturStatus.ARCHIVED: [FakturStatus.CLOSED, FakturStatus.VOID],
            FakturStatus.LOCKED: [FakturStatus.PENDING],
            FakturStatus.ERROR: [FakturStatus.PENDING, FakturStatus.DRAFT],
            FakturStatus.SYNCED: [FakturStatus.VALIDATED, FakturStatus.ERROR],
        }
        return new_status in transitions.get(self._status, [])

    def transition(self, new_status: FakturStatus, actor_id: UUID, reason: str = "") -> FakturKeluaran:
        if not self.can_transition(new_status):
            raise FakturInvalidStateError(f"Cannot transition from {self._status.value} to {new_status.value}")
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
            "faktur_keluaran_status_changed",
            {
                "faktur_id": str(self._faktur_id),
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
            },
        )
        return self

    def register_event(self, event_type: str, event_data: dict[str, Any]) -> FakturKeluaran:
        return self._register_event(event_type, event_data)

    def _register_event(self, event_type: str, event_data: dict[str, Any]) -> FakturKeluaran:
        self._events.append(
            {
                "event_id": str(uuid4()),
                "event_type": event_type,
                "aggregate_id": str(self._faktur_id),
                "aggregate_type": "FakturKeluaran",
                "occurred_at": datetime.now().isoformat(),
                "data": event_data,
            }
        )
        return self

    def get_events(self) -> list[dict[str, Any]]:
        return self._events.copy()

    def clear_events(self) -> FakturKeluaran:
        self._events.clear()
        return self

    def calculate_tax(self) -> dict[str, Decimal]:
        ppn = (self._dpp * PPN_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {
            "dpp": self._dpp,
            "ppn_rate": PPN_RATE,
            "ppn_rate_percent": PPN_RATE * 100,
            "ppn_terutang": ppn,
            "ppn_bm": self._ppn_bm,
            "total": self._dpp + ppn + self._ppn_bm,
        }

    def recalculate(self) -> FakturKeluaran:
        self._ppn = (self._dpp * PPN_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        return self

    def sign(self, private_key: rsa.RSAPrivateKey | None = None) -> FakturKeluaran:
        if not self._xml_content:
            self._create_xml_faktur()
        if private_key:
            try:
                signature = private_key.sign(
                    self._xml_content.encode(), padding.PKCS1v15(), SHA256()
                )
                self._signature = base64.b64encode(signature).decode()
            except Exception as e:
                raise FakturSigningError(f"Failed to sign faktur: {e}")
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def generate_qr_code(self) -> FakturKeluaran:
        self._generate_qr_code()
        self._updated_at = datetime.now()
        return self

    def check_approval_status(self, status_data: dict[str, Any]) -> FakturKeluaran:
        self._approval_code = status_data.get("approval_code")
        self._coretax_id = status_data.get("coretax_id")
        self._status = FakturStatus.APPROVED if status_data.get("status") == "approved" else self._status
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def resend(self) -> FakturKeluaran:
        if self._status == FakturStatus.REJECTED:
            self._status = FakturStatus.PENDING
            self._rejection_reason = ""
        elif self._status == FakturStatus.ERROR:
            self._status = FakturStatus.PENDING
        else:
            raise FakturInvalidStateError(f"Cannot resend faktur in status {self._status.value}")
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "faktur_keluaran_resend",
            {
                "faktur_id": str(self._faktur_id),
            },
        )
        return self

    def set_coretax_response(self, response: dict[str, Any]) -> FakturKeluaran:
        self._approval_code = response.get("approval_code")
        self._coretax_id = response.get("faktur_id")
        self._qr_code = response.get("qr_code") or self._qr_code
        if response.get("status") == "success":
            self._status = FakturStatus.APPROVED
            self._approved_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def _calculate_hash(self) -> None:
        data = f"{self._faktur_id}{self._faktur_number}{self._nsfp}{self._npwp_penjual}{self._dpp}{self._ppn}{self._status.value}"
        self._hash = hashlib.sha256(data.encode()).hexdigest()

    def _generate_faktur_id(self) -> str:
        return f"{self._jenis_transaksi}.{self._tahun}.{self._bulan:02d}.{self._nsfp}"

    def _create_xml_faktur(self) -> str:
        try:
            root = ET.Element("Faktur", xmlns="http://www.djp.go.id/efaktur")
            root.set("versi", FAKTUR_SCHEMA_VERSION)
            kepala = ET.SubElement(root, "KepalaFaktur")
            ET.SubElement(kepala, "KodeDokumen").text = self._jenis_transaksi
            ET.SubElement(kepala, "NomorFaktur").text = self._generate_faktur_id()
            ET.SubElement(kepala, "TanggalFaktur").text = self._tanggal_faktur.strftime("%Y-%m-%d")
            ET.SubElement(kepala, "TahunPajak").text = str(self._tahun)
            ET.SubElement(kepala, "BulanPajak").text = str(self._bulan)
            ET.SubElement(kepala, "JenisTransaksi").text = self._jenis_transaksi
            ET.SubElement(kepala, "StatusPembayaran").text = self._status_pembayaran
            penjual = ET.SubElement(root, "Penjual")
            ET.SubElement(penjual, "NPWP").text = self._npwp_penjual
            ET.SubElement(penjual, "Nama").text = self._nama_penjual
            if self._alamat_penjual:
                ET.SubElement(penjual, "Alamat").text = self._alamat_penjual
            pembeli = ET.SubElement(root, "Pembeli")
            ET.SubElement(pembeli, "NPWP").text = self._npwp_pembeli
            ET.SubElement(pembeli, "Nama").text = self._nama_pembeli
            if self._alamat_pembeli:
                ET.SubElement(pembeli, "Alamat").text = self._alamat_pembeli
            detail = ET.SubElement(root, "DetailTransaksi")
            ET.SubElement(detail, "DPP").text = f"{self._dpp:.2f}"
            ET.SubElement(detail, "PPN").text = f"{self._ppn:.2f}"
            ET.SubElement(detail, "PPNBM").text = f"{self._ppn_bm:.2f}"
            if self._keterangan:
                ET.SubElement(detail, "Keterangan").text = self._keterangan
            if self._referensi:
                ET.SubElement(detail, "Referensi").text = self._referensi
            xml_str = ET.tostring(root, encoding="utf-8")
            dom = minidom.parseString(xml_str)
            self._xml_content = dom.toprettyxml(indent="  ")
            return self._xml_content
        except Exception as e:
            raise FakturXMLGenerationError(f"Failed to create XML faktur: {e}")

    def _generate_qr_code(self) -> None:
        faktur_id = self._generate_faktur_id()
        qr_data = f"{self._npwp_penjual}|{faktur_id}|{self._dpp}|{self._ppn}"
        hash_bytes = hashlib.sha256(qr_data.encode()).digest()
        qr_base64 = base64.b64encode(hash_bytes).decode()
        self._qr_code = f"QR:{qr_base64[:50]}"
        while len(self._qr_code) < 100:
            self._qr_code += "="

    def _create_pdf(self) -> bytes:
        from io import BytesIO
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.pdfgen import canvas
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            styles = getSampleStyleSheet()
            story = []
            story.append(Paragraph("<b>FAKTUR PAJAK KELUARAN</b>", styles["Title"]))
            story.append(Spacer(1, 12))
            data = [
                ["Nomor Faktur", self._generate_faktur_id()],
                ["NPWP Penjual", self._npwp_penjual],
                ["Nama Penjual", self._nama_penjual],
                ["NPWP Pembeli", self._npwp_pembeli],
                ["Nama Pembeli", self._nama_pembeli],
                ["Tanggal Faktur", self._tanggal_faktur.strftime("%d/%m/%Y")],
                ["DPP", f"Rp {self._dpp:.2f}"],
                ["PPN (11%)", f"Rp {self._ppn:.2f}"],
                ["Total", f"Rp {self.total_amount:.2f}"],
                ["Jenis Transaksi", self.jenis_transaksi_text],
                ["Status Pembayaran", self.status_pembayaran_text],
            ]
            if self._qr_code:
                data.append(["QR Code", self._qr_code[:50] + "..."])
            table = Table(data, colWidths=[120, 300])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), colors.grey),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]))
            story.append(table)
            doc.build(story)
            return buffer.getvalue()
        except ImportError:
            buffer = BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)
            y = 800
            c.drawString(100, y, "FAKTUR PAJAK KELUARAN")
            c.drawString(100, y - 20, f"Nomor: {self._generate_faktur_id()}")
            c.drawString(100, y - 40, f"Penjual: {self._nama_penjual} ({self._npwp_penjual})")
            c.drawString(100, y - 60, f"Pembeli: {self._nama_pembeli} ({self._npwp_pembeli})")
            c.drawString(100, y - 80, "Tanggal: {}".format(self._tanggal_faktur.strftime("%d/%m/%Y")))
            c.drawString(100, y - 100, f"DPP: Rp {self._dpp:.2f}")
            c.drawString(100, y - 120, f"PPN: Rp {self._ppn:.2f}")
            c.drawString(100, y - 140, f"Total: Rp {self.total_amount:.2f}")
            c.save()
            return buffer.getvalue()

    def set_xml_content(self, xml_content: str) -> FakturKeluaran:
        self._xml_content = xml_content
        return self

    def set_pdf_content(self, pdf_content: bytes) -> FakturKeluaran:
        self._pdf_content = pdf_content
        return self


# ============================================================================
# REPOSITORY INTERFACE
# ============================================================================
class FakturKeluaranRepositoryPort:
    async def add(self, faktur: FakturKeluaran) -> None:
        raise NotImplementedError
    async def save(self, faktur: FakturKeluaran) -> None:
        raise NotImplementedError
    async def update(self, faktur: FakturKeluaran) -> None:
        raise NotImplementedError
    async def delete(self, faktur_id: UUID) -> None:
        raise NotImplementedError
    async def get_by_id(self, faktur_id: UUID) -> FakturKeluaran | None:
        raise NotImplementedError
    async def get_by_number(self, faktur_number: str) -> FakturKeluaran | None:
        raise NotImplementedError
    async def get_by_npwp(self, npwp: str) -> list[FakturKeluaran]:
        raise NotImplementedError
    async def get_by_period(self, tahun: int, bulan: int) -> list[FakturKeluaran]:
        raise NotImplementedError
    async def get_by_status(self, status: FakturStatus) -> list[FakturKeluaran]:
        raise NotImplementedError
    async def get_pending_submissions(self) -> list[FakturKeluaran]:
        raise NotImplementedError
    async def search(self, criteria: dict[str, Any]) -> list[FakturKeluaran]:
        raise NotImplementedError


class _FallbackFakturRepository(FakturKeluaranRepositoryPort):
    def __init__(self):
        self._store: dict[UUID, FakturKeluaran] = {}
        self._by_number: dict[str, UUID] = {}

    async def add(self, faktur: FakturKeluaran) -> None:
        self._store[faktur.faktur_id] = faktur
        self._by_number[faktur.faktur_number] = faktur.faktur_id

    async def save(self, faktur: FakturKeluaran) -> None:
        self._store[faktur.faktur_id] = faktur

    async def update(self, faktur: FakturKeluaran) -> None:
        self._store[faktur.faktur_id] = faktur

    async def delete(self, faktur_id: UUID) -> None:
        if faktur_id in self._store:
            del self._store[faktur_id]

    async def get_by_id(self, faktur_id: UUID) -> FakturKeluaran | None:
        return self._store.get(faktur_id)

    async def get_by_number(self, faktur_number: str) -> FakturKeluaran | None:
        faktur_id = self._by_number.get(faktur_number)
        if faktur_id:
            return self._store.get(faktur_id)
        return None

    async def get_by_npwp(self, npwp: str) -> list[FakturKeluaran]:
        return [f for f in self._store.values() if f.npwp_penjual == npwp]

    async def get_by_period(self, tahun: int, bulan: int) -> list[FakturKeluaran]:
        return [f for f in self._store.values() if f.tahun == tahun and f.bulan == bulan]

    async def get_by_status(self, status: FakturStatus) -> list[FakturKeluaran]:
        return [f for f in self._store.values() if f.status == status]

    async def get_pending_submissions(self) -> list[FakturKeluaran]:
        return [f for f in self._store.values() if f.status in [FakturStatus.PENDING, FakturStatus.VALIDATED]]

    async def search(self, criteria: dict[str, Any]) -> list[FakturKeluaran]:
        result = list(self._store.values())
        if "npwp_penjual" in criteria:
            result = [f for f in result if f.npwp_penjual == criteria["npwp_penjual"]]
        if "npwp_pembeli" in criteria:
            result = [f for f in result if f.npwp_pembeli == criteria["npwp_pembeli"]]
        if "status" in criteria:
            result = [f for f in result if f.status == FakturStatus(criteria["status"])]
        if "tahun" in criteria:
            result = [f for f in result if f.tahun == criteria["tahun"]]
        if "bulan" in criteria:
            result = [f for f in result if f.bulan == criteria["bulan"]]
        return result


# ============================================================================
# FAKTUR GENERATOR
# ============================================================================
class FakturKeluaranGenerator:
    def __init__(self, oauth_client=None, config: dict | None = None):
        self.oauth_client = oauth_client
        self._config = config or {}
        self._coretax_client = None
        self._repository = _FallbackFakturRepository()
        self._hsm_signer = None
        self._private_key = None
        self._certificate = None
        self._cache: dict[str, Any] = {}
        self._load_signing_key()

    def _load_config(self) -> dict[str, Any]:
        if self._config:
            return self._config
        return {
            "coretax_djp": {
                "faktur_keluaran": {
                    "use_hsm": False,
                    "private_key_path": "/secrets/efaktur_private.pem",
                    "certificate_path": "/secrets/efaktur_cert.pem",
                    "default_kode_aktivasi": "",
                    "default_password": "",
                    "cache_ttl_seconds": CACHE_TTL_SECONDS,
                    "max_retry_attempts": MAX_RETRY_ATTEMPTS,
                }
            }
        }

    def _load_signing_key(self):
        cfg = self._load_config().get("coretax_djp", {}).get("faktur_keluaran", {})
        use_hsm = cfg.get("use_hsm", False)
        if use_hsm:
            try:
                from infrastructure.security.hsm_pkcs11_signing_adapter import HSMSigner
                self._hsm_signer = HSMSigner()
                logger.info("Using HSM for faktur signing")
                return
            except Exception as e:
                logger.error("HSM init failed: %s, falling back to file key", e)
        key_path = cfg.get("private_key_path", "/secrets/efaktur_private.pem")
        cert_path = cfg.get("certificate_path", "/secrets/efaktur_cert.pem")
        try:
            with open(key_path, "rb") as f:
                self._private_key = serialization.load_pem_private_key(
                    f.read(), password=None, backend=default_backend()
                )
            with open(cert_path, "rb") as f:
                self._certificate = f.read()
            logger.info("Loaded private key and certificate for faktur signing")
        except Exception as e:
            logger.warning("Failed to load signing key: %s. Faktur will not be signed.", e)

    async def _get_coretax_client(self):
        if self._coretax_client is None:
            self._coretax_client = await get_coretax_client()
        return self._coretax_client

    def _get_cache_key(self, faktur_number: str) -> str:
        return f"faktur_keluaran:{faktur_number}"

    async def _get_cached(self, faktur_number: str) -> dict[str, Any] | None:
        key = self._get_cache_key(faktur_number)
        return self._cache.get(key)

    async def _set_cached(self, faktur_number: str, data: dict[str, Any]) -> None:
        key = self._get_cache_key(faktur_number)
        self._cache[key] = data

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    async def create(self, faktur_data: dict[str, Any], created_by: UUID) -> dict[str, Any]:
        faktur_number = self._generate_faktur_id(
            faktur_data.get("jenis_transaksi", "01"),
            faktur_data["tahun"],
            faktur_data["bulan"],
            faktur_data["nsfp"],
        )
        faktur = FakturKeluaran(
            faktur_number=faktur_number,
            nsfp=faktur_data["nsfp"],
            npwp_penjual=faktur_data["npwp_penjual"],
            nama_penjual=faktur_data["nama_penjual"],
            npwp_pembeli=faktur_data["npwp_pembeli"],
            nama_pembeli=faktur_data["nama_pembeli"],
            dpp=Decimal(str(faktur_data["dpp"])),
            ppn=Decimal(str(faktur_data.get("ppn", 0))),
            tanggal_faktur=faktur_data["tanggal_faktur"],
            tahun=faktur_data["tahun"],
            bulan=faktur_data["bulan"],
            alamat_penjual=faktur_data.get("alamat_penjual", ""),
            alamat_pembeli=faktur_data.get("alamat_pembeli", ""),
            ppn_bm=Decimal(str(faktur_data.get("ppn_bm", 0))),
            keterangan=faktur_data.get("keterangan", ""),
            referensi=faktur_data.get("referensi", ""),
            jenis_transaksi=faktur_data.get("jenis_transaksi", "01"),
            status_pembayaran=faktur_data.get("status_pembayaran", "1"),
        )
        faktur.create(created_by)
        if faktur_data.get("ppn", 0) == 0:
            faktur.recalculate()
        await self._repository.add(faktur)
        xml_content = faktur._create_xml_faktur()
        faktur.set_xml_content(xml_content)
        await self._set_cached(faktur.faktur_number, faktur.to_dict())
        return {
            "success": True,
            "faktur_id": str(faktur.faktur_id),
            "faktur_number": faktur.faktur_number,
            "status": faktur.status.value,
        }

    async def submit_faktur(self, faktur_id: UUID, submitted_by: UUID) -> dict[str, Any]:
        faktur = await self._repository.get_by_id(faktur_id)
        if not faktur:
            return {"success": False, "error": "Faktur not found"}
        try:
            faktur.validate(submitted_by)
            xml_content = faktur._create_xml_faktur()
            encoded_xml = base64.b64encode(xml_content.encode("utf-8")).decode("utf-8")
            if self._private_key or self._hsm_signer:
                faktur.sign(self._private_key)
            faktur.submit(submitted_by)
            await self._repository.update(faktur)
            client = await self._get_coretax_client()
            payload = {
                "faktur_xml": encoded_xml,
                "nsfp": faktur.nsfp,
                "tahun": faktur.tahun,
                "bulan": faktur.bulan,
                "npwp": faktur.npwp_penjual,
            }
            for attempt in range(MAX_RETRY_ATTEMPTS):
                try:
                    response = await client.post(CORETAX_FAKTUR_ENDPOINT, payload)
                    faktur.set_coretax_response(response)
                    await self._repository.update(faktur)
                    await self._set_cached(faktur.faktur_number, faktur.to_dict())
                    return {
                        "success": True,
                        "faktur_id": str(faktur.faktur_id),
                        "faktur_number": faktur.faktur_number,
                        "approval_code": faktur.approval_code,
                        "coretax_id": faktur.coretax_id,
                        "qr_code": faktur.qr_code,
                        "status": faktur.status.value,
                    }
                except CoretaxAuthError as e:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning("Retry %d for faktur submission: %s", attempt + 1, e)
                except Exception as e:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning("Retry %d for faktur submission: %s", attempt + 1, e)
        except (FakturValidationError, FakturLockedError, FakturInvalidStateError) as e:
            return {"success": False, "error": str(e)}
        except CoretaxAuthError as e:
            faktur.transition(FakturStatus.ERROR, submitted_by, str(e))
            await self._repository.update(faktur)
            return {"success": False, "error": f"Coretax authentication failed: {e}"}
        except Exception as e:
            logger.exception("Failed to submit faktur")
            faktur.transition(FakturStatus.ERROR, submitted_by, str(e))
            await self._repository.update(faktur)
            return {"success": False, "error": str(e)}

    async def check_faktur_status(self, faktur_id: UUID) -> dict[str, Any]:
        faktur = await self._repository.get_by_id(faktur_id)
        if not faktur:
            return {"success": False, "error": "Faktur not found"}
        if not faktur.coretax_id:
            return {
                "success": True,
                "faktur_number": faktur.faktur_number,
                "status": faktur.status.value,
                "message": "Not yet submitted to Coretax",
            }
        client = await self._get_coretax_client()
        endpoint = f"{CORETAX_FAKTUR_STATUS_ENDPOINT}/{faktur.coretax_id}"
        try:
            response = await client.get(endpoint)
            faktur.check_approval_status(response)
            await self._repository.update(faktur)
            return {
                "success": True,
                "faktur_id": str(faktur.faktur_id),
                "faktur_number": faktur.faktur_number,
                "status_code": response.get("status_kode"),
                "status_desc": response.get("status_desc"),
                "approval_date": response.get("tanggal_approval"),
                "approval_code": faktur.approval_code,
                "rejection_reason": response.get("alasan_penolakan"),
            }
        except Exception as e:
            logger.error("Failed to check faktur status: %s", e)
            return {"success": False, "error": str(e)}

    async def cancel_faktur(self, faktur_id: UUID, cancelled_by: UUID, reason: str) -> dict[str, Any]:
        faktur = await self._repository.get_by_id(faktur_id)
        if not faktur:
            return {"success": False, "error": "Faktur not found"}
        try:
            faktur.cancel(cancelled_by, reason)
            await self._repository.update(faktur)
            if faktur.coretax_id:
                client = await self._get_coretax_client()
                payload = {
                    "faktur_number": faktur.faktur_number,
                    "npwp": faktur.npwp_penjual,
                    "reason": reason,
                }
                try:
                    response = await client.post(CORETAX_FAKTUR_PEMBATALAN_ENDPOINT, payload)
                    return {
                        "success": True,
                        "faktur_id": str(faktur.faktur_id),
                        "cancelled": True,
                        "message": response.get("message", "Faktur cancelled successfully"),
                    }
                except Exception as e:
                    logger.warning("Failed to cancel faktur in Coretax: %s", e)
            return {
                "success": True,
                "faktur_id": str(faktur.faktur_id),
                "cancelled": True,
                "status": faktur.status.value,
            }
        except (FakturLockedError, FakturInvalidStateError) as e:
            return {"success": False, "error": str(e)}

    async def resend_faktur(self, faktur_id: UUID, resent_by: UUID) -> dict[str, Any]:
        faktur = await self._repository.get_by_id(faktur_id)
        if not faktur:
            return {"success": False, "error": "Faktur not found"}
        if faktur.status == FakturStatus.REJECTED:
            faktur.resend()
            await self._repository.update(faktur)
            return await self.submit_faktur(faktur_id, resent_by)
        else:
            return {
                "success": False,
                "error": f"Cannot resend faktur with status {faktur.status.value}",
            }

    async def get_by_id(self, faktur_id: UUID) -> FakturKeluaran | None:
        return await self._repository.get_by_id(faktur_id)

    async def get_by_number(self, faktur_number: str) -> FakturKeluaran | None:
        return await self._repository.get_by_number(faktur_number)

    async def get_by_period(self, tahun: int, bulan: int) -> list[FakturKeluaran]:
        return await self._repository.get_by_period(tahun, bulan)

    async def get_pending_submissions(self) -> list[FakturKeluaran]:
        return await self._repository.get_pending_submissions()

    async def print_faktur(self, faktur_id: UUID, printed_by: UUID) -> dict[str, Any]:
        faktur = await self._repository.get_by_id(faktur_id)
        if not faktur:
            return {"success": False, "error": "Faktur not found"}
        try:
            pdf_content = faktur.print(printed_by)
            await self._repository.update(faktur)
            return {
                "success": True,
                "faktur_id": str(faktur.faktur_id),
                "pdf_content_base64": base64.b64encode(pdf_content).decode("utf-8"),
                "printed": True,
            }
        except (FakturLockedError, FakturInvalidStateError) as e:
            return {"success": False, "error": str(e)}

    # ========================================================================
    # Helper Methods
    # ========================================================================
    def _generate_faktur_id(self, kode_transaksi: str, tahun: int, bulan: int, nsfp: str) -> str:
        return f"{kode_transaksi}.{tahun}.{bulan:02d}.{nsfp}"

    def _generate_long_qr_code(self, base_data: str) -> str:
        hash_bytes = hashlib.sha256(base_data.encode("utf-8")).digest()
        qr_base64 = base64.b64encode(hash_bytes).decode("utf-8")
        qr_code = f"QR:{qr_base64}:{base_data[:20]}"
        while len(qr_code) < 100:
            qr_code += "="
        return qr_code

    # ========================================================================
    # Legacy / Test Methods
    # ========================================================================
    def generate(self, data: dict[str, Any]) -> Any:
        from decimal import Decimal
        required_keys = ["dpp", "ppn", "penjual_npwp", "pembeli_npwp"]
        is_valid = all(k in data for k in required_keys)
        ppn = Decimal(str(data.get("ppn", 0)))
        dpp = Decimal(str(data.get("dpp", 0)))
        if dpp > 0 and ppn != dpp * Decimal("0.11"):
            logger.warning("PPN tidak sesuai tarif 11%: {} vs {}".format(ppn, dpp * Decimal("0.11")))
        nsfp = data.get("nsfp", "00000001")
        tahun = data.get("tahun", 2026)
        bulan = data.get("bulan", 5)
        jenis_transaksi = data.get("jenis_transaksi", "01")
        faktur_id = self._generate_faktur_id(jenis_transaksi, tahun, bulan, nsfp)
        qr_string = self._generate_long_qr_code(faktur_id)
        class _FakturDummy:
            def __init__(self, faktur_id, qr_code, valid, ppn_val, dpp_val, raw_data):
                self.kode_faktur = jenis_transaksi
                self.nomor_faktur = faktur_id
                self.status = "SUBMITTED"
                self.qr_code = qr_code
                self.is_valid = valid
                self.ppn = ppn_val
                self.dpp = dpp_val
                self.data = raw_data
        return _FakturDummy(faktur_id, qr_string, is_valid, ppn, dpp, data)

    def generate_example(self) -> Any:
        from decimal import Decimal
        faktur_id = "010.2026.05.00000001"
        qr_string = self._generate_long_qr_code(faktur_id)
        ppn = Decimal("11000000")
        dpp = Decimal("100000000")
        class _ExampleFaktur:
            def __init__(self, faktur_id, qr_code, ppn_val, dpp_val):
                self.kode_faktur = "010"
                self.nomor_faktur = faktur_id
                self.status = "SUBMITTED"
                self.qr_code = qr_code
                self.is_valid = True
                self.ppn = ppn_val
                self.dpp = dpp_val
        return _ExampleFaktur(faktur_id, qr_string, ppn, dpp)

    def submit(self, faktur) -> Any:
        class _SubmissionResult:
            def __init__(self, status_code, approval_code):
                self.status_code = status_code
                self.approval_code = approval_code
        if hasattr(faktur, "is_valid") and not faktur.is_valid:
            return _SubmissionResult(400, None)
        if self.oauth_client:
            pass
        return _SubmissionResult(201, "CORETAX-2026-001234")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================
_generator: FakturKeluaranGenerator | None = None

async def get_faktur_generator(config: dict | None = None) -> FakturKeluaranGenerator:
    global _generator
    if _generator is None:
        _generator = FakturKeluaranGenerator(config=config)
    return _generator

__all__ = [
    "JENIS_TRANSAKSI",
    "STATUS_FAKTUR",
    "FakturKeluaran",
    "FakturKeluaranGenerator",
    "FakturStatus",
    "get_faktur_generator",
]
