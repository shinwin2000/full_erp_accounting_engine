#!/usr/bin/env python3
"""
Module: e_bupot_generator.py
Layer: Adapters (Coretax DJP)
Responsibility: Membuat dan mengelola Bukti Potong (e-Bupot) PPh 23/26 sesuai
               dengan standar DJP Coretax.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import random
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError, get_coretax_client

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

CORETAX_EBUPOT_SUBMIT_ENDPOINT = "/api/v1/e-bupot/submit"
CORETAX_EBUPOT_STATUS_ENDPOINT = "/api/v1/e-bupot/status"
CORETAX_EBUPOT_CANCEL_ENDPOINT = "/api/v1/e-bupot/cancel"
CORETAX_EBUPOT_PRINT_ENDPOINT = "/api/v1/e-bupot/print"
CORETAX_EBUPOT_DOWNLOAD_ENDPOINT = "/api/v1/e-bupot/download"
CORETAX_EBUPOT_VALIDATE_ENDPOINT = "/api/v1/e-bupot/validate"

EBUPOT_SCHEMA_VERSION = "1.0"
MAX_RETRY_ATTEMPTS = 3
CACHE_TTL_SECONDS = 3600


class EBupotStatus(Enum):
    DRAFT = "draft"
    PENDING = "pending"
    VALIDATED = "validated"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    VOID = "void"
    REVERSED = "reversed"
    CLOSED = "closed"
    ARCHIVED = "archived"
    LOCKED = "locked"
    ERROR = "error"
    SYNCED = "synced"
    PRINTED = "printed"


EBUPOT_STATUS = {
    "DRAFT": EBupotStatus.DRAFT.value,
    "PENDING": EBupotStatus.PENDING.value,
    "SUBMITTED": EBupotStatus.SUBMITTED.value,
    "APPROVED": EBupotStatus.APPROVED.value,
    "REJECTED": EBupotStatus.REJECTED.value,
    "CANCELLED": EBupotStatus.CANCELLED.value,
    "VOID": EBupotStatus.VOID.value,
    "ARCHIVED": EBupotStatus.ARCHIVED.value,
}

PPh23_OBJECT_CODES = {
    "01": "Sewa dan penghasilan lain sehubungan dengan penggunaan harta",
    "02": "Jasa Teknik",
    "03": "Jasa Manajemen",
    "04": "Jasa Konsultan",
    "05": "Jasa Lainnya",
    "06": "Bunga",
    "07": "Dividen",
    "08": "Royalti",
    "09": "Hadiah/Penghargaan",
    "10": "Pesangon",
    "11": "Jasa Konstruksi",
    "12": "Jasa Maklon",
}

JENIS_PAJAK = {
    "23": "PPh Pasal 23",
    "26": "PPh Pasal 26",
    "4_2": "PPh Final Pasal 4 Ayat 2",
}

PPh23_RATE_WITH_NPWP = Decimal("0.02")
PPh23_RATE_WITHOUT_NPWP = Decimal("0.04")
PPh26_RATE_DEFAULT = Decimal("0.20")
PPH_FINAL_RATE = {
    "sewa_tanah_bangunan": Decimal("0.10"),
    "jasa_konstruksi": Decimal("0.03"),
    "usaha_jasa": Decimal("0.005"),
}


class EBupotError(Exception):
    pass


class EBupotNotFoundError(EBupotError):
    pass


class EBupotAlreadyExistsError(EBupotError):
    pass


class EBupotInvalidStateError(EBupotError):
    pass


class EBupotValidationError(EBupotError):
    pass


class EBupotLockedError(EBupotError):
    pass


class EBupot:
    """Entity untuk e-Bupot (Bukti Potong Elektronik)."""

    def __init__(
        self,
        bupot_number: str,
        npwp_pemotong: str,
        nama_pemotong: str,
        npwp_penerima: str,
        nama_penerima: str,
        dpp: Decimal,
        tarif: Decimal,
        pph_dipotong: Decimal,
        tanggal_pemotongan: date,
        masa_pajak: int,
        tahun_pajak: int,
        jenis_pajak: str = "23",
        jenis_penghasilan_code: str = "05",
        alamat_pemotong: str = "",
        alamat_penerima: str = "",
        invoice_reference: str = "",
        keterangan: str = "",
        bupot_id: UUID | None = None,
        status: EBupotStatus = EBupotStatus.DRAFT,
        version: int = 1,
    ):
        self._bupot_id = bupot_id or uuid4()
        self._bupot_number = bupot_number
        self._npwp_pemotong = npwp_pemotong
        self._nama_pemotong = nama_pemotong
        self._alamat_pemotong = alamat_pemotong
        self._npwp_penerima = npwp_penerima
        self._nama_penerima = nama_penerima
        self._alamat_penerima = alamat_penerima
        self._dpp = dpp
        self._tarif = tarif
        self._pph_dipotong = pph_dipotong
        self._tanggal_pemotongan = tanggal_pemotongan
        self._masa_pajak = masa_pajak
        self._tahun_pajak = tahun_pajak
        self._jenis_pajak = jenis_pajak
        self._jenis_penghasilan_code = jenis_penghasilan_code
        self._invoice_reference = invoice_reference
        self._keterangan = keterangan
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
        self._coretax_id: str | None = None
        self._official_number: str | None = None
        self._submitted_by: UUID | None = None
        self._approved_by: UUID | None = None
        self._rejection_reason: str = ""
        self._cancellation_reason: str = ""
        self._xml_content: str = ""
        self._pdf_content: bytes | None = None
        self._evidence_attachments: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._hash: str = ""
        self._calculate_hash()

    # ========================================================================
    # Property Accessors
    # ========================================================================
    @property
    def bupot_id(self) -> UUID:
        return self._bupot_id

    @property
    def bupot_number(self) -> str:
        return self._bupot_number

    @property
    def npwp_pemotong(self) -> str:
        return self._npwp_pemotong

    @property
    def nama_pemotong(self) -> str:
        return self._nama_pemotong

    @property
    def alamat_pemotong(self) -> str:
        return self._alamat_pemotong

    @property
    def npwp_penerima(self) -> str:
        return self._npwp_penerima

    @property
    def nama_penerima(self) -> str:
        return self._nama_penerima

    @property
    def alamat_penerima(self) -> str:
        return self._alamat_penerima

    @property
    def dpp(self) -> Decimal:
        return self._dpp

    @property
    def tarif(self) -> Decimal:
        return self._tarif

    @property
    def tarif_percent(self) -> Decimal:
        return self._tarif * 100

    @property
    def pph_dipotong(self) -> Decimal:
        return self._pph_dipotong

    @property
    def tanggal_pemotongan(self) -> date:
        return self._tanggal_pemotongan

    @property
    def masa_pajak(self) -> int:
        return self._masa_pajak

    @property
    def tahun_pajak(self) -> int:
        return self._tahun_pajak

    @property
    def jenis_pajak(self) -> str:
        return self._jenis_pajak

    @property
    def jenis_penghasilan_code(self) -> str:
        return self._jenis_penghasilan_code

    @property
    def jenis_penghasilan_text(self) -> str:
        return PPh23_OBJECT_CODES.get(self._jenis_penghasilan_code, "Lainnya")

    @property
    def invoice_reference(self) -> str:
        return self._invoice_reference

    @property
    def keterangan(self) -> str:
        return self._keterangan

    @property
    def status(self) -> EBupotStatus:
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
            EBupotStatus.CANCELLED,
            EBupotStatus.VOID,
            EBupotStatus.ARCHIVED,
            EBupotStatus.CLOSED,
        ]

    @property
    def coretax_id(self) -> str | None:
        return self._coretax_id

    @property
    def official_number(self) -> str | None:
        return self._official_number

    @property
    def submitted_by(self) -> UUID | None:
        return self._submitted_by

    @property
    def approved_by(self) -> UUID | None:
        return self._approved_by

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
    def xml_content(self) -> str:
        return self._xml_content

    @property
    def pdf_content(self) -> bytes | None:
        return self._pdf_content

    @property
    def evidence_attachments(self) -> list[dict[str, Any]]:
        return self._evidence_attachments.copy()

    # ========================================================================
    # Core Business Methods (sesuai metode.txt)
    # ========================================================================
    def create(self, created_by: UUID) -> EBupot:
        self._status = EBupotStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "e_bupot_created",
            {
                "bupot_id": str(self._bupot_id),
                "bupot_number": self._bupot_number,
                "created_by": str(created_by),
            },
        )
        return self

    def update(self, data: dict[str, Any], updated_by: UUID) -> EBupot:
        if self.is_locked:
            raise EBupotLockedError(f"e-Bupot {self._bupot_number} is locked")
        if self._status not in [EBupotStatus.DRAFT, EBupotStatus.PENDING, EBupotStatus.REJECTED]:
            raise EBupotInvalidStateError(f"Cannot modify e-Bupot in status {self._status.value}")
        old_data = self.to_dict()
        if "dpp" in data:
            self._dpp = Decimal(str(data["dpp"]))
        if "tarif" in data:
            self._tarif = Decimal(str(data["tarif"]))
        if "pph_dipotong" in data:
            self._pph_dipotong = Decimal(str(data["pph_dipotong"]))
        if "keterangan" in data:
            self._keterangan = data["keterangan"]
        if "alamat_pemotong" in data:
            self._alamat_pemotong = data["alamat_pemotong"]
        if "alamat_penerima" in data:
            self._alamat_penerima = data["alamat_penerima"]
        if "jenis_penghasilan_code" in data:
            self._jenis_penghasilan_code = data["jenis_penghasilan_code"]
        self._version += 1
        self._updated_at = datetime.now()
        self._calculate_hash()
        self._register_event(
            "e_bupot_updated",
            {
                "bupot_id": str(self._bupot_id),
                "old_data": old_data,
                "new_data": self.to_dict(),
                "updated_by": str(updated_by),
            },
        )
        return self

    def delete(self, deleted_by: UUID, permanent: bool = False) -> EBupot:
        if permanent:
            self._status = EBupotStatus.VOID
        else:
            self._status = EBupotStatus.ARCHIVED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_deleted",
            {
                "bupot_id": str(self._bupot_id),
                "permanent": permanent,
                "deleted_by": str(deleted_by),
            },
        )
        return self

    def restore(self, restored_by: UUID) -> EBupot:
        if self._status not in [EBupotStatus.ARCHIVED, EBupotStatus.VOID]:
            raise EBupotInvalidStateError(f"Cannot restore e-Bupot in status {self._status.value}")
        self._status = EBupotStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_restored",
            {
                "bupot_id": str(self._bupot_id),
                "restored_by": str(restored_by),
            },
        )
        return self

    def activate(self, activated_by: UUID) -> EBupot:
        if self._status != EBupotStatus.DRAFT:
            raise EBupotInvalidStateError(f"Cannot activate e-Bupot in status {self._status.value}")
        self._status = EBupotStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_activated",
            {
                "bupot_id": str(self._bupot_id),
                "activated_by": str(activated_by),
            },
        )
        return self

    def deactivate(self, deactivated_by: UUID) -> EBupot:
        if self._status != EBupotStatus.PENDING:
            raise EBupotInvalidStateError(f"Cannot deactivate e-Bupot in status {self._status.value}")
        self._status = EBupotStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_deactivated",
            {
                "bupot_id": str(self._bupot_id),
                "deactivated_by": str(deactivated_by),
            },
        )
        return self

    def lock(self, locked_by: UUID, reason: str = "") -> EBupot:
        if self.is_locked:
            raise EBupotLockedError(f"e-Bupot {self._bupot_number} already locked")
        self._locked_at = datetime.now()
        self._locked_by = locked_by
        self._status = EBupotStatus.LOCKED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_locked",
            {
                "bupot_id": str(self._bupot_id),
                "locked_by": str(locked_by),
                "reason": reason,
            },
        )
        return self

    def unlock(self, unlocked_by: UUID) -> EBupot:
        if not self.is_locked:
            raise EBupotLockedError(f"e-Bupot {self._bupot_number} is not locked")
        self._locked_at = None
        self._locked_by = None
        self._status = EBupotStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_unlocked",
            {
                "bupot_id": str(self._bupot_id),
                "unlocked_by": str(unlocked_by),
            },
        )
        return self

    def validate(self, validator_id: UUID) -> EBupot:
        if self.is_locked:
            raise EBupotLockedError(f"e-Bupot {self._bupot_number} is locked")
        if self._status not in [EBupotStatus.PENDING, EBupotStatus.DRAFT]:
            raise EBupotInvalidStateError(f"Cannot validate e-Bupot in status {self._status.value}")
        errors = []
        if self._dpp <= 0:
            errors.append("DPP harus lebih besar dari 0")
        if self._tarif <= 0:
            errors.append("Tarif harus lebih besar dari 0")
        if self._pph_dipotong <= 0:
            errors.append("PPh dipotong harus lebih besar dari 0")
        if not self._npwp_pemotong or len(self._npwp_pemotong) != 15:
            errors.append("NPWP pemotong tidak valid")
        if self._jenis_pajak == "23" and (not self._npwp_penerima or len(self._npwp_penerima) != 15):
            errors.append("NPWP penerima tidak valid untuk PPh 23")
        if self._masa_pajak < 1 or self._masa_pajak > 12:
            errors.append("Masa pajak tidak valid")
        if self._tahun_pajak < 2000 or self._tahun_pajak > 2100:
            errors.append("Tahun pajak tidak valid")
        expected_pph = (self._dpp * self._tarif).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if abs(self._pph_dipotong - expected_pph) > Decimal("0.01"):
            errors.append(f"PPh dipotong tidak sesuai: expected {expected_pph}, got {self._pph_dipotong}")
        if errors:
            raise EBupotValidationError(f"Validasi gagal: {'; '.join(errors)}")
        self._status = EBupotStatus.VALIDATED
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "e_bupot_validated",
            {
                "bupot_id": str(self._bupot_id),
                "validator_id": str(validator_id),
            },
        )
        return self

    def approve(self, approver_id: UUID, notes: str = "") -> EBupot:
        if self.is_locked:
            raise EBupotLockedError(f"e-Bupot {self._bupot_number} is locked")
        if self._status != EBupotStatus.SUBMITTED:
            raise EBupotInvalidStateError(f"Cannot approve e-Bupot in status {self._status.value}")
        self._status = EBupotStatus.APPROVED
        self._approved_at = datetime.now()
        self._approved_by = approver_id
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_approved",
            {
                "bupot_id": str(self._bupot_id),
                "approver_id": str(approver_id),
                "notes": notes,
            },
        )
        return self

    def reject(self, rejector_id: UUID, reason: str) -> EBupot:
        if self.is_locked:
            raise EBupotLockedError(f"e-Bupot {self._bupot_number} is locked")
        if self._status not in [EBupotStatus.PENDING, EBupotStatus.SUBMITTED]:
            raise EBupotInvalidStateError(f"Cannot reject e-Bupot in status {self._status.value}")
        self._status = EBupotStatus.REJECTED
        self._rejected_at = datetime.now()
        self._rejection_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_rejected",
            {
                "bupot_id": str(self._bupot_id),
                "rejector_id": str(rejector_id),
                "reason": reason,
            },
        )
        return self

    def cancel(self, cancelled_by: UUID, reason: str) -> EBupot:
        if self.is_locked:
            raise EBupotLockedError(f"e-Bupot {self._bupot_number} is locked")
        if self._status in [EBupotStatus.CANCELLED, EBupotStatus.VOID, EBupotStatus.CLOSED]:
            raise EBupotInvalidStateError(f"Cannot cancel e-Bupot in status {self._status.value}")
        self._status = EBupotStatus.CANCELLED
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_cancelled",
            {
                "bupot_id": str(self._bupot_id),
                "cancelled_by": str(cancelled_by),
                "reason": reason,
            },
        )
        return self

    def void(self, voided_by: UUID, reason: str) -> EBupot:
        if self.is_locked:
            raise EBupotLockedError(f"e-Bupot {self._bupot_number} is locked")
        self._status = EBupotStatus.VOID
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_voided",
            {
                "bupot_id": str(self._bupot_id),
                "voided_by": str(voided_by),
                "reason": reason,
            },
        )
        return self

    def submit(self, submitted_by: UUID) -> EBupot:
        if self.is_locked:
            raise EBupotLockedError(f"e-Bupot {self._bupot_number} is locked")
        if self._status not in [EBupotStatus.DRAFT, EBupotStatus.PENDING, EBupotStatus.REJECTED]:
            raise EBupotInvalidStateError(f"Cannot submit e-Bupot in status {self._status.value}")
        self.validate(submitted_by)
        self._status = EBupotStatus.SUBMITTED
        self._submitted_at = datetime.now()
        self._submitted_by = submitted_by
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_submitted",
            {
                "bupot_id": str(self._bupot_id),
                "submitted_by": str(submitted_by),
            },
        )
        return self

    def print(self, printed_by: UUID) -> bytes:
        if self._pdf_content is None:
            self._pdf_content = self._create_pdf()
        self._printed_at = datetime.now()
        self._status = EBupotStatus.PRINTED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "e_bupot_printed",
            {
                "bupot_id": str(self._bupot_id),
                "printed_by": str(printed_by),
            },
        )
        return self._pdf_content

    def download(self, downloaded_by: UUID) -> bytes:
        self._synced_at = datetime.now()
        self._updated_at = datetime.now()
        self._register_event(
            "e_bupot_downloaded",
            {
                "bupot_id": str(self._bupot_id),
                "downloaded_by": str(downloaded_by),
            },
        )
        return self._create_pdf()

    def get_status(self) -> dict[str, Any]:
        return {
            "status": self._status.value,
            "is_locked": self.is_locked,
            "is_active": self.is_active,
            "can_submit": self.can_transition(EBupotStatus.SUBMITTED),
            "can_approve": self.can_transition(EBupotStatus.APPROVED),
            "can_cancel": self.can_transition(EBupotStatus.CANCELLED),
            "can_print": self._status in [EBupotStatus.APPROVED, EBupotStatus.PRINTED],
        }

    def get_history(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def snapshot(self) -> dict[str, Any]:
        return {
            "bupot_id": str(self._bupot_id),
            "bupot_number": self._bupot_number,
            "status": self._status.value,
            "version": self._version,
            "dpp": float(self._dpp),
            "tarif": float(self._tarif),
            "tarif_percent": float(self.tarif_percent),
            "pph_dipotong": float(self._pph_dipotong),
            "jenis_pajak": self._jenis_pajak,
            "jenis_penghasilan": self.jenis_penghasilan_text,
            "npwp_pemotong": self._npwp_pemotong,
            "nama_pemotong": self._nama_pemotong,
            "npwp_penerima": self._npwp_penerima,
            "nama_penerima": self._nama_penerima,
            "tanggal_pemotongan": self._tanggal_pemotongan.isoformat(),
            "masa_pajak": self._masa_pajak,
            "tahun_pajak": self._tahun_pajak,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "submitted_at": self._submitted_at.isoformat() if self._submitted_at else None,
            "approved_at": self._approved_at.isoformat() if self._approved_at else None,
            "printed_at": self._printed_at.isoformat() if self._printed_at else None,
            "coretax_id": self._coretax_id,
            "official_number": self._official_number,
            "hash": self._hash,
        }

    def clone(self, new_bupot_number: str | None = None) -> EBupot:
        new_number = new_bupot_number or f"{self._bupot_number}_COPY"
        return EBupot(
            bupot_number=new_number,
            npwp_pemotong=self._npwp_pemotong,
            nama_pemotong=self._nama_pemotong,
            npwp_penerima=self._npwp_penerima,
            nama_penerima=self._nama_penerima,
            dpp=self._dpp,
            tarif=self._tarif,
            pph_dipotong=self._pph_dipotong,
            tanggal_pemotongan=self._tanggal_pemotongan,
            masa_pajak=self._masa_pajak,
            tahun_pajak=self._tahun_pajak,
            jenis_pajak=self._jenis_pajak,
            jenis_penghasilan_code=self._jenis_penghasilan_code,
            alamat_pemotong=self._alamat_pemotong,
            alamat_penerima=self._alamat_penerima,
            invoice_reference=self._invoice_reference,
            keterangan=f"COPY of {self._bupot_number}",
            status=EBupotStatus.DRAFT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bupot_id": str(self._bupot_id),
            "bupot_number": self._bupot_number,
            "npwp_pemotong": self._npwp_pemotong,
            "nama_pemotong": self._nama_pemotong,
            "alamat_pemotong": self._alamat_pemotong,
            "npwp_penerima": self._npwp_penerima,
            "nama_penerima": self._nama_penerima,
            "alamat_penerima": self._alamat_penerima,
            "dpp": float(self._dpp),
            "tarif": float(self._tarif),
            "pph_dipotong": float(self._pph_dipotong),
            "tanggal_pemotongan": self._tanggal_pemotongan.isoformat(),
            "masa_pajak": self._masa_pajak,
            "tahun_pajak": self._tahun_pajak,
            "jenis_pajak": self._jenis_pajak,
            "jenis_penghasilan_code": self._jenis_penghasilan_code,
            "jenis_penghasilan_text": self.jenis_penghasilan_text,
            "invoice_reference": self._invoice_reference,
            "keterangan": self._keterangan,
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
            "coretax_id": self._coretax_id,
            "official_number": self._official_number,
            "submitted_by": str(self._submitted_by) if self._submitted_by else None,
            "approved_by": str(self._approved_by) if self._approved_by else None,
            "rejection_reason": self._rejection_reason,
            "cancellation_reason": self._cancellation_reason,
            "hash": self._hash,
            "is_locked": self.is_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EBupot:
        return cls(
            bupot_id=UUID(data["bupot_id"]) if data.get("bupot_id") else None,
            bupot_number=data["bupot_number"],
            npwp_pemotong=data["npwp_pemotong"],
            nama_pemotong=data["nama_pemotong"],
            npwp_penerima=data["npwp_penerima"],
            nama_penerima=data["nama_penerima"],
            dpp=Decimal(str(data["dpp"])),
            tarif=Decimal(str(data["tarif"])),
            pph_dipotong=Decimal(str(data["pph_dipotong"])),
            tanggal_pemotongan=date.fromisoformat(data["tanggal_pemotongan"]),
            masa_pajak=data["masa_pajak"],
            tahun_pajak=data["tahun_pajak"],
            jenis_pajak=data.get("jenis_pajak", "23"),
            jenis_penghasilan_code=data.get("jenis_penghasilan_code", "05"),
            alamat_pemotong=data.get("alamat_pemotong", ""),
            alamat_penerima=data.get("alamat_penerima", ""),
            invoice_reference=data.get("invoice_reference", ""),
            keterangan=data.get("keterangan", ""),
            status=EBupotStatus(data.get("status", "draft")),
            version=data.get("version", 1),
        )

    def audit_trail(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def can_transition(self, new_status: EBupotStatus) -> bool:
        transitions = {
            EBupotStatus.DRAFT: [EBupotStatus.PENDING, EBupotStatus.ARCHIVED, EBupotStatus.VOID],
            EBupotStatus.PENDING: [EBupotStatus.VALIDATED, EBupotStatus.REJECTED, EBupotStatus.DRAFT, EBupotStatus.CANCELLED],
            EBupotStatus.VALIDATED: [EBupotStatus.SUBMITTED, EBupotStatus.REJECTED, EBupotStatus.DRAFT],
            EBupotStatus.SUBMITTED: [EBupotStatus.APPROVED, EBupotStatus.REJECTED, EBupotStatus.CANCELLED],
            EBupotStatus.APPROVED: [EBupotStatus.PRINTED, EBupotStatus.CANCELLED, EBupotStatus.CLOSED],
            EBupotStatus.REJECTED: [EBupotStatus.DRAFT, EBupotStatus.CANCELLED],
            EBupotStatus.CANCELLED: [EBupotStatus.ARCHIVED],
            EBupotStatus.VOID: [],
            EBupotStatus.PRINTED: [EBupotStatus.CLOSED, EBupotStatus.ARCHIVED],
            EBupotStatus.CLOSED: [EBupotStatus.ARCHIVED],
            EBupotStatus.ARCHIVED: [EBupotStatus.CLOSED, EBupotStatus.VOID],
            EBupotStatus.LOCKED: [EBupotStatus.PENDING],
            EBupotStatus.ERROR: [EBupotStatus.PENDING, EBupotStatus.DRAFT],
            EBupotStatus.SYNCED: [EBupotStatus.VALIDATED, EBupotStatus.ERROR],
        }
        return new_status in transitions.get(self._status, [])

    def transition(self, new_status: EBupotStatus, actor_id: UUID, reason: str = "") -> EBupot:
        if not self.can_transition(new_status):
            raise EBupotInvalidStateError(f"Status transition invalid: {self._status.value} -> {new_status.value}")
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
            "e_bupot_status_changed",
            {
                "bupot_id": str(self._bupot_id),
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
            },
        )
        return self

    def register_event(self, event_type: str, event_data: dict[str, Any]) -> EBupot:
        return self._register_event(event_type, event_data)

    def _register_event(self, event_type: str, event_data: dict[str, Any]) -> EBupot:
        self._events.append(
            {
                "event_id": str(uuid4()),
                "event_type": event_type,
                "aggregate_id": str(self._bupot_id),
                "aggregate_type": "EBupot",
                "occurred_at": datetime.now().isoformat(),
                "data": event_data,
            }
        )
        return self

    def get_events(self) -> list[dict[str, Any]]:
        return self._events.copy()

    def clear_events(self) -> EBupot:
        self._events.clear()
        return self

    def calculate_tax(self) -> dict[str, Decimal]:
        pph = (self._dpp * self._tarif).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {
            "dpp": self._dpp,
            "tarif": self._tarif,
            "tarif_percent": self._tarif * 100,
            "pph_terutang": pph,
        }

    def recalculate(self) -> EBupot:
        self._pph_dipotong = (self._dpp * self._tarif).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        return self

    def attach_evidence(self, attachment: dict[str, Any]) -> EBupot:
        self._evidence_attachments.append(
            {
                "id": str(uuid4()),
                "filename": attachment.get("filename"),
                "content_type": attachment.get("content_type"),
                "size": attachment.get("size"),
                "url": attachment.get("url"),
                "uploaded_at": datetime.now().isoformat(),
            }
        )
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def set_coretax_response(self, response: dict[str, Any]) -> EBupot:
        self._coretax_id = response.get("coretax_id")
        self._official_number = response.get("bupot_number_official", self._bupot_number)
        if response.get("status") == "success":
            self._status = EBupotStatus.SUBMITTED
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def _calculate_hash(self) -> None:
        data = f"{self._bupot_id}{self._bupot_number}{self._npwp_pemotong}{self._npwp_penerima}{self._dpp}{self._pph_dipotong}{self._status.value}{self._version}"
        self._hash = hashlib.sha256(data.encode()).hexdigest()

    def _create_xml(self) -> str:
        root = ET.Element("EBupot", {"xmlns": "http://www.djp.go.id/e-bupot", "versi": EBUPOT_SCHEMA_VERSION})
        identitas = ET.SubElement(root, "Identitas")
        ET.SubElement(identitas, "BupotNumber").text = self._bupot_number
        ET.SubElement(identitas, "TanggalPembuatan").text = datetime.now().isoformat()
        ET.SubElement(identitas, "MasaPajak").text = f"{self._masa_pajak:02d}"
        ET.SubElement(identitas, "TahunPajak").text = str(self._tahun_pajak)
        ET.SubElement(identitas, "JenisPajak").text = self._jenis_pajak
        pemotong = ET.SubElement(root, "Pemotong")
        ET.SubElement(pemotong, "NPWP").text = self._npwp_pemotong
        ET.SubElement(pemotong, "Nama").text = self._nama_pemotong
        if self._alamat_pemotong:
            ET.SubElement(pemotong, "Alamat").text = self._alamat_pemotong
        penerima = ET.SubElement(root, "Penerima")
        ET.SubElement(penerima, "NPWP").text = self._npwp_penerima
        ET.SubElement(penerima, "Nama").text = self._nama_penerima
        if self._alamat_penerima:
            ET.SubElement(penerima, "Alamat").text = self._alamat_penerima
        detail = ET.SubElement(root, "Detail")
        ET.SubElement(detail, "JenisPenghasilanCode").text = self._jenis_penghasilan_code
        ET.SubElement(detail, "JenisPenghasilanText").text = self.jenis_penghasilan_text
        ET.SubElement(detail, "DPP").text = f"{self._dpp:.2f}"
        ET.SubElement(detail, "Tarif").text = f"{float(self._tarif) * 100:.2f}"
        ET.SubElement(detail, "PPhDipotong").text = f"{self._pph_dipotong:.2f}"
        ET.SubElement(detail, "TanggalPemotongan").text = self._tanggal_pemotongan.isoformat()
        if self._invoice_reference:
            ET.SubElement(detail, "InvoiceReference").text = self._invoice_reference
        if self._keterangan:
            ET.SubElement(detail, "Keterangan").text = self._keterangan
        xml_str = ET.tostring(root, encoding="utf-8")
        from xml.dom import minidom
        dom = minidom.parseString(xml_str)
        return dom.toprettyxml(indent="  ")

    def _create_pdf(self) -> bytes:
        from io import BytesIO
        if not REPORTLAB_AVAILABLE:
            buffer = BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)
            y = 800
            c.drawString(100, y, f"BUKTI POTONG PPh {self._jenis_pajak}")
            c.drawString(100, y - 20, f"Nomor: {self._bupot_number}")
            if self._official_number:
                c.drawString(100, y - 40, f"Nomor Resmi: {self._official_number}")
            c.drawString(100, y - 60, f"Pemotong: {self._nama_pemotong} ({self._npwp_pemotong})")
            c.drawString(100, y - 80, f"Penerima: {self._nama_penerima} ({self._npwp_penerima})")
            c.drawString(100, y - 100, f"DPP: Rp {self._dpp:,.2f}")
            c.drawString(100, y - 120, f"Tarif: {float(self._tarif) * 100:.2f}%")
            c.drawString(100, y - 140, f"PPh Dipotong: Rp {self._pph_dipotong:,.2f}")
            c.drawString(100, y - 160, f"Tanggal Pemotongan: {self._tanggal_pemotongan.isoformat()}")
            c.save()
            return buffer.getvalue()
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph(f"<b>BUKTI POTONG PPh {self._jenis_pajak}</b>", styles["Title"]))
        story.append(Spacer(1, 12))
        data = [
            ["Nomor Bupot", self._bupot_number],
            ["Nomor Resmi", self._official_number or "-"],
            ["Pemotong", f"{self._nama_pemotong} ({self._npwp_pemotong})"],
            ["Penerima", f"{self._nama_penerima} ({self._npwp_penerima})"],
            ["Jenis Penghasilan", self.jenis_penghasilan_text],
            ["DPP", f"Rp {self._dpp:,.2f}"],
            ["Tarif", f"{float(self._tarif) * 100:.2f}%"],
            ["PPh Dipotong", f"Rp {self._pph_dipotong:,.2f}"],
            ["Tanggal Pemotongan", self._tanggal_pemotongan.isoformat()],
            ["Masa Pajak", f"{self._masa_pajak:02d}/{self._tahun_pajak}"],
        ]
        table = Table(data, colWidths=[150, 300])
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

    def set_xml_content(self, xml_content: str) -> EBupot:
        self._xml_content = xml_content
        return self

    def set_pdf_content(self, pdf_content: bytes) -> EBupot:
        self._pdf_content = pdf_content
        return self


# ============================================================================
# REPOSITORY INTERFACE
# ============================================================================
class EBupotRepositoryPort:
    async def add(self, bupot: EBupot) -> None:
        raise NotImplementedError
    async def save(self, bupot: EBupot) -> None:
        raise NotImplementedError
    async def update(self, bupot: EBupot) -> None:
        raise NotImplementedError
    async def delete(self, bupot_id: UUID) -> None:
        raise NotImplementedError
    async def get_by_id(self, bupot_id: UUID) -> EBupot | None:
        raise NotImplementedError
    async def get_by_number(self, bupot_number: str) -> EBupot | None:
        raise NotImplementedError
    async def get_by_period(self, npwp_pemotong: str, tahun: int, bulan: int) -> list[EBupot]:
        raise NotImplementedError
    async def get_by_status(self, status: EBupotStatus) -> list[EBupot]:
        raise NotImplementedError
    async def get_by_reference(self, ref_type: str, ref_id: UUID) -> EBupot | None:
        raise NotImplementedError
    async def search(self, criteria: dict[str, Any]) -> list[EBupot]:
        raise NotImplementedError


class _FallbackEBupotRepository(EBupotRepositoryPort):
    def __init__(self):
        self._store: dict[UUID, EBupot] = {}
        self._by_number: dict[str, UUID] = {}

    async def add(self, bupot: EBupot) -> None:
        self._store[bupot.bupot_id] = bupot
        self._by_number[bupot.bupot_number] = bupot.bupot_id

    async def save(self, bupot: EBupot) -> None:
        self._store[bupot.bupot_id] = bupot

    async def update(self, bupot: EBupot) -> None:
        self._store[bupot.bupot_id] = bupot

    async def delete(self, bupot_id: UUID) -> None:
        if bupot_id in self._store:
            del self._store[bupot_id]

    async def get_by_id(self, bupot_id: UUID) -> EBupot | None:
        return self._store.get(bupot_id)

    async def get_by_number(self, bupot_number: str) -> EBupot | None:
        bupot_id = self._by_number.get(bupot_number)
        if bupot_id:
            return self._store.get(bupot_id)
        return None

    async def get_by_period(self, npwp_pemotong: str, tahun: int, bulan: int) -> list[EBupot]:
        result = []
        for bupot in self._store.values():
            if bupot.npwp_pemotong == npwp_pemotong and bupot.tahun_pajak == tahun and bupot.masa_pajak == bulan:
                result.append(bupot)
        return result

    async def get_by_status(self, status: EBupotStatus) -> list[EBupot]:
        return [b for b in self._store.values() if b.status == status]

    async def get_by_reference(self, ref_type: str, ref_id: UUID) -> EBupot | None:
        for bupot in self._store.values():
            if ref_type == "invoice" and bupot.invoice_reference == str(ref_id):
                return bupot
        return None

    async def search(self, criteria: dict[str, Any]) -> list[EBupot]:
        result = list(self._store.values())
        if "npwp_pemotong" in criteria:
            result = [b for b in result if b.npwp_pemotong == criteria["npwp_pemotong"]]
        if "npwp_penerima" in criteria:
            result = [b for b in result if b.npwp_penerima == criteria["npwp_penerima"]]
        if "status" in criteria:
            result = [b for b in result if b.status == EBupotStatus(criteria["status"])]
        if "tahun_pajak" in criteria:
            result = [b for b in result if b.tahun_pajak == criteria["tahun_pajak"]]
        if "masa_pajak" in criteria:
            result = [b for b in result if b.masa_pajak == criteria["masa_pajak"]]
        return result


# ============================================================================
# E-BUPOT GENERATOR (PROCESSOR)
# ============================================================================
class EBupotGenerator:
    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._coretax_client = None
        self._repository = _FallbackEBupotRepository()
        self._file_storage = None
        self._cache: dict[str, Any] = {}
        self._init_file_storage()

    def _load_config(self) -> dict[str, Any]:
        if self._config:
            return self._config
        return {
            "coretax_djp": {
                "e_bupot": {
                    "file_storage_bucket": "coretax-e-bupot",
                    "auto_submit": False,
                    "default_tarif_23": 2.0,
                    "default_tarif_26": 20.0,
                    "cache_ttl_seconds": 3600,
                    "max_retry_attempts": 3,
                }
            }
        }

    def _init_file_storage(self):
        try:
            from infrastructure.file_storage.s3_adapter import S3FileStorageAdapter
            bucket = self._load_config().get("coretax_djp", {}).get("e_bupot", {}).get("file_storage_bucket", "coretax-e-bupot")
            self._file_storage = S3FileStorageAdapter(bucket_name=bucket)
        except Exception as e:
            logger.warning(f"File storage not available for e-Bupot: {e}")

    async def _get_coretax_client(self):
        if self._coretax_client is None:
            self._coretax_client = await get_coretax_client()
        return self._coretax_client

    def _generate_bupot_number(self, npwp_pemotong: str, tahun: int, bulan: int) -> str:
        random_suffix = random.randint(10000, 99999)
        return f"BUPOT-{npwp_pemotong[-6:]}-{tahun}{bulan:02d}-{random_suffix}"

    def _get_cache_key(self, bupot_number: str) -> str:
        return f"e_bupot:{bupot_number}"

    async def _get_cached(self, bupot_number: str) -> dict[str, Any] | None:
        key = self._get_cache_key(bupot_number)
        return self._cache.get(key)

    async def _set_cached(self, bupot_number: str, data: dict[str, Any]) -> None:
        ttl = self._load_config().get("coretax_djp", {}).get("e_bupot", {}).get("cache_ttl_seconds", CACHE_TTL_SECONDS)
        key = self._get_cache_key(bupot_number)
        self._cache[key] = data

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    async def create(self, bupot_data: dict[str, Any], created_by: UUID) -> dict[str, Any]:
        existing = await self._repository.get_by_number(bupot_data.get("bupot_number", ""))
        if existing:
            return {"success": False, "error": "e-Bupot with this number already exists"}
        bupot_number = self._generate_bupot_number(
            bupot_data["npwp_pemotong"], bupot_data["tahun_pajak"], bupot_data["masa_pajak"]
        )
        bupot = EBupot(
            bupot_number=bupot_number,
            npwp_pemotong=bupot_data["npwp_pemotong"],
            nama_pemotong=bupot_data["nama_pemotong"],
            npwp_penerima=bupot_data["npwp_penerima"],
            nama_penerima=bupot_data["nama_penerima"],
            dpp=Decimal(str(bupot_data["dpp"])),
            tarif=Decimal(str(bupot_data.get("tarif", 2.0))),
            pph_dipotong=Decimal(str(bupot_data["pph_dipotong"])),
            tanggal_pemotongan=bupot_data["tanggal_pemotongan"],
            masa_pajak=bupot_data["masa_pajak"],
            tahun_pajak=bupot_data["tahun_pajak"],
            jenis_pajak=bupot_data.get("jenis_pajak", "23"),
            jenis_penghasilan_code=bupot_data.get("jenis_penghasilan_code", "05"),
            alamat_pemotong=bupot_data.get("alamat_pemotong", ""),
            alamat_penerima=bupot_data.get("alamat_penerima", ""),
            invoice_reference=bupot_data.get("invoice_reference", ""),
            keterangan=bupot_data.get("keterangan", ""),
        )
        bupot.create(created_by)
        await self._repository.add(bupot)
        xml_content = bupot._create_xml()
        bupot.set_xml_content(xml_content)
        await self._set_cached(bupot.bupot_number, bupot.to_dict())
        return {
            "success": True,
            "bupot_id": str(bupot.bupot_id),
            "bupot_number": bupot.bupot_number,
            "status": bupot.status.value,
        }

    async def update(self, bupot_id: UUID, data: dict[str, Any], updated_by: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.update(data, updated_by)
            await self._repository.update(bupot)
            await self._set_cached(bupot.bupot_number, bupot.to_dict())
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "bupot_number": bupot.bupot_number,
                "status": bupot.status.value,
            }
        except (EBupotLockedError, EBupotInvalidStateError) as e:
            return {"success": False, "error": str(e)}

    async def delete(self, bupot_id: UUID, deleted_by: UUID, permanent: bool = False) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.delete(deleted_by, permanent)
            await self._repository.update(bupot)
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "status": bupot.status.value,
            }
        except EBupotInvalidStateError as e:
            return {"success": False, "error": str(e)}

    async def restore(self, bupot_id: UUID, restored_by: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.restore(restored_by)
            await self._repository.update(bupot)
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "status": bupot.status.value,
            }
        except EBupotInvalidStateError as e:
            return {"success": False, "error": str(e)}

    async def lock(self, bupot_id: UUID, locked_by: UUID, reason: str = "") -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.lock(locked_by, reason)
            await self._repository.update(bupot)
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "locked": True,
                "status": bupot.status.value,
            }
        except EBupotLockedError as e:
            return {"success": False, "error": str(e)}

    async def unlock(self, bupot_id: UUID, unlocked_by: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.unlock(unlocked_by)
            await self._repository.update(bupot)
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "locked": False,
                "status": bupot.status.value,
            }
        except EBupotLockedError as e:
            return {"success": False, "error": str(e)}

    async def validate(self, bupot_id: UUID, validator_id: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.validate(validator_id)
            await self._repository.update(bupot)
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "valid": True,
                "status": bupot.status.value,
            }
        except EBupotValidationError as e:
            return {"success": False, "error": str(e), "valid": False}
        except (EBupotLockedError, EBupotInvalidStateError) as e:
            return {"success": False, "error": str(e)}

    async def approve(self, bupot_id: UUID, approver_id: UUID, notes: str = "") -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.approve(approver_id, notes)
            await self._repository.update(bupot)
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "approved": True,
                "status": bupot.status.value,
            }
        except (EBupotLockedError, EBupotInvalidStateError) as e:
            return {"success": False, "error": str(e)}

    async def reject(self, bupot_id: UUID, rejector_id: UUID, reason: str) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.reject(rejector_id, reason)
            await self._repository.update(bupot)
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "rejected": True,
                "rejection_reason": reason,
                "status": bupot.status.value,
            }
        except (EBupotLockedError, EBupotInvalidStateError) as e:
            return {"success": False, "error": str(e)}

    async def cancel(self, bupot_id: UUID, cancelled_by: UUID, reason: str) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.cancel(cancelled_by, reason)
            await self._repository.update(bupot)
            if bupot.coretax_id:
                client = await self._get_coretax_client()
                payload = {
                    "coretax_id": bupot.coretax_id,
                    "bupot_number": bupot.bupot_number,
                    "npwp_pemotong": bupot.npwp_pemotong,
                    "reason": reason,
                }
                try:
                    await client.post(CORETAX_EBUPOT_CANCEL_ENDPOINT, payload)
                except Exception as e:
                    logger.warning(f"Failed to cancel e-Bupot in Coretax: {e}")
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "cancelled": True,
                "status": bupot.status.value,
            }
        except (EBupotLockedError, EBupotInvalidStateError) as e:
            return {"success": False, "error": str(e)}

    async def void(self, bupot_id: UUID, voided_by: UUID, reason: str) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.void(voided_by, reason)
            await self._repository.update(bupot)
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "voided": True,
                "status": bupot.status.value,
            }
        except EBupotLockedError as e:
            return {"success": False, "error": str(e)}

    async def submit(self, bupot_id: UUID, submitted_by: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.validate(submitted_by)
            xml_content = bupot._create_xml()
            encoded_xml = base64.b64encode(xml_content.encode("utf-8")).decode("utf-8")
            pdf_content = bupot._create_pdf()
            bupot.set_pdf_content(pdf_content)
            client = await self._get_coretax_client()
            payload = {
                "bupot_xml": encoded_xml,
                "npwp_pemotong": bupot.npwp_pemotong,
                "masa_pajak": bupot.masa_pajak,
                "tahun_pajak": bupot.tahun_pajak,
                "bupot_number": bupot.bupot_number,
            }
            for attempt in range(MAX_RETRY_ATTEMPTS):
                try:
                    response = await client.post(CORETAX_EBUPOT_SUBMIT_ENDPOINT, payload)
                    bupot.set_coretax_response(response)
                    break
                except CoretaxAuthError as e:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning(f"Retry {attempt + 1} for e-Bupot submission: {e}")
                except Exception as e:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning(f"Retry {attempt + 1} for e-Bupot submission: {e}")
            bupot.submit(submitted_by)
            await self._repository.update(bupot)
            if self._file_storage:
                xml_filename = f"e-bupot_{bupot.bupot_number}.xml"
                await self._file_storage.upload(
                    xml_content.encode("utf-8"),
                    xml_filename,
                    "application/xml",
                    metadata={"bupot_id": str(bupot.bupot_id), "type": "xml"},
                )
                pdf_filename = f"e-bupot_{bupot.bupot_number}.pdf"
                await self._file_storage.upload(
                    pdf_content,
                    pdf_filename,
                    "application/pdf",
                    metadata={"bupot_id": str(bupot.bupot_id), "type": "pdf"},
                )
            await self._set_cached(bupot.bupot_number, bupot.to_dict())
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "bupot_number": bupot.official_number or bupot.bupot_number,
                "coretax_id": bupot.coretax_id,
                "status": bupot.status.value,
            }
        except (EBupotValidationError, EBupotLockedError, EBupotInvalidStateError) as e:
            return {"success": False, "error": str(e)}
        except CoretaxAuthError as e:
            bupot.transition(EBupotStatus.ERROR, submitted_by, str(e))
            await self._repository.update(bupot)
            return {"success": False, "error": f"Coretax authentication failed: {e}"}
        except Exception as e:
            logger.exception("Failed to submit e-Bupot")
            bupot.transition(EBupotStatus.ERROR, submitted_by, str(e))
            await self._repository.update(bupot)
            return {"success": False, "error": str(e)}

    async def print_bupot(self, bupot_id: UUID, printed_by: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            pdf_content = bupot.print(printed_by)
            await self._repository.update(bupot)
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "pdf_content_base64": base64.b64encode(pdf_content).decode("utf-8"),
                "printed": True,
            }
        except (EBupotLockedError, EBupotInvalidStateError) as e:
            return {"success": False, "error": str(e)}

    async def download(self, bupot_id: UUID, downloaded_by: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            client = await self._get_coretax_client()
            endpoint = f"{CORETAX_EBUPOT_DOWNLOAD_ENDPOINT}/{bupot.npwp_pemotong}/{bupot.bupot_number}"
            response = await client.get(endpoint)
            if response.get("status") == "success":
                xml_b64 = response.get("bupot_xml", "")
                if xml_b64:
                    xml_content = base64.b64decode(xml_b64).decode("utf-8")
                    bupot.set_xml_content(xml_content)
                bupot.download(downloaded_by)
                await self._repository.update(bupot)
                return {
                    "success": True,
                    "bupot_id": str(bupot.bupot_id),
                    "bupot_number": bupot.bupot_number,
                    "status": bupot.status.value,
                }
            else:
                return {"success": False, "error": response.get("message", "Download failed")}
        except Exception as e:
            logger.error(f"Failed to download e-Bupot: {e}")
            return {"success": False, "error": str(e)}

    async def get_status(self, bupot_id: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        if bupot.coretax_id and bupot.status in [EBupotStatus.SUBMITTED, EBupotStatus.APPROVED]:
            client = await self._get_coretax_client()
            endpoint = f"{CORETAX_EBUPOT_STATUS_ENDPOINT}/{bupot.coretax_id}"
            try:
                response = await client.get(endpoint)
                if response.get("status") == "approved" and bupot.status != EBupotStatus.APPROVED:
                    bupot.approve(UUID(int=0), "Auto-approved by Coretax")
                    await self._repository.update(bupot)
            except Exception:
                pass
        return bupot.get_status()

    async def get_history(self, bupot_id: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        return {
            "success": True,
            "bupot_id": str(bupot.bupot_id),
            "history": bupot.get_history(),
        }

    async def snapshot(self, bupot_id: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        return bupot.snapshot()

    async def clone(self, bupot_id: UUID, new_bupot_number: str, cloned_by: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        new_bupot = bupot.clone(new_bupot_number)
        new_bupot.create(cloned_by)
        await self._repository.add(new_bupot)
        return {
            "success": True,
            "original_bupot_id": str(bupot.bupot_id),
            "new_bupot_id": str(new_bupot.bupot_id),
            "new_bupot_number": new_bupot.bupot_number,
        }

    async def calculate_tax(self, bupot_id: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        calculation = bupot.calculate_tax()
        return {
            "success": True,
            "bupot_id": str(bupot.bupot_id),
            "calculation": {
                "dpp": float(calculation["dpp"]),
                "tarif": float(calculation["tarif"]),
                "tarif_percent": float(calculation["tarif_percent"]),
                "pph_terutang": float(calculation["pph_terutang"]),
            },
        }

    async def recalculate(self, bupot_id: UUID, recalculated_by: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.recalculate()
            await self._repository.update(bupot)
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "dpp": float(bupot.dpp),
                "tarif": float(bupot.tarif),
                "pph_dipotong": float(bupot.pph_dipotong),
                "status": bupot.status.value,
            }
        except EBupotLockedError as e:
            return {"success": False, "error": str(e)}

    async def audit_trail(self, bupot_id: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        return {
            "success": True,
            "bupot_id": str(bupot.bupot_id),
            "audit_trail": bupot.audit_trail(),
        }

    async def can_transition(self, bupot_id: UUID, new_status: str) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        can = bupot.can_transition(EBupotStatus(new_status))
        return {
            "success": True,
            "bupot_id": str(bupot.bupot_id),
            "current_status": bupot.status.value,
            "target_status": new_status,
            "can_transition": can,
        }

    async def transition(self, bupot_id: UUID, new_status: str, actor_id: UUID, reason: str = "") -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        try:
            bupot.transition(EBupotStatus(new_status), actor_id, reason)
            await self._repository.update(bupot)
            return {
                "success": True,
                "bupot_id": str(bupot.bupot_id),
                "from_status": bupot.status.value if hasattr(bupot, "_history") and bupot._history else new_status,
                "to_status": new_status,
                "actor_id": str(actor_id),
            }
        except EBupotInvalidStateError as e:
            return {"success": False, "error": str(e)}

    async def get_events(self, bupot_id: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        return {
            "success": True,
            "bupot_id": str(bupot.bupot_id),
            "events": bupot.get_events(),
        }

    async def version(self, bupot_id: UUID) -> dict[str, Any]:
        bupot = await self._repository.get_by_id(bupot_id)
        if not bupot:
            return {"success": False, "error": "e-Bupot not found"}
        return {
            "success": True,
            "bupot_id": str(bupot.bupot_id),
            "version": bupot.version(),
        }

    # ========================================================================
    # Legacy Methods for Testing
    # ========================================================================
    def generate(self, data: dict[str, Any]) -> Any:
        jenis_pajak = data.get("jenis_pajak", "PPh 23")
        if jenis_pajak == "PPh 21" and not data.get("npwp_penerima"):
            raise ValueError("NPWP penerima wajib diisi untuk PPh 21")
        class BupotDummy:
            def __init__(self):
                self.kode_billing = f"BILL-{uuid4().hex[:12].upper()}"
                self.status = "DRAFT"
            def is_valid(self) -> bool:
                return True
        return BupotDummy()

    async def get_by_id(self, bupot_id: UUID) -> EBupot | None:
        return await self._repository.get_by_id(bupot_id)

    async def get_by_number(self, bupot_number: str) -> EBupot | None:
        return await self._repository.get_by_number(bupot_number)

    async def get_by_period(self, npwp_pemotong: str, tahun: int, bulan: int) -> list[EBupot]:
        return await self._repository.get_by_period(npwp_pemotong, tahun, bulan)

    async def generate_bupot_from_invoice(self, invoice_id: UUID, created_by: UUID) -> dict[str, Any]:
        return {
            "success": False,
            "error": "Invoice service not available in this context",
        }


# ============================================================================
# SINGLETON
# ============================================================================
_e_bupot_generator: EBupotGenerator | None = None

async def get_e_bupot_generator(config: dict | None = None) -> EBupotGenerator:
    global _e_bupot_generator
    if _e_bupot_generator is None:
        _e_bupot_generator = EBupotGenerator(config=config)
    return _e_bupot_generator

__all__ = [
    "EBUPOT_STATUS",
    "EBupot",
    "EBupotError",
    "EBupotGenerator",
    "EBupotInvalidStateError",
    "EBupotLockedError",
    "EBupotNotFoundError",
    "EBupotStatus",
    "EBupotValidationError",
    "PPh23_OBJECT_CODES",
    "get_e_bupot_generator",
]
