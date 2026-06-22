#!/usr/bin/env python3
"""
Module: spt_masa_pph_21_builder.py
Layer: Adapters (Coretax DJP)
Responsibility: Membangun SPT Masa PPh Pasal 21 (Formulir 1721) berdasarkan data
               payroll dan pemotongan PPh 21 setiap bulan.
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

from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError, get_coretax_client

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

CORETAX_SPT_PPH21_ENDPOINT = "/api/v1/spt/pph21/submit"
CORETAX_SPT_STATUS_ENDPOINT = "/api/v1/spt/status"
CORETAX_SPT_CANCEL_ENDPOINT = "/api/v1/spt/cancel"
CORETAX_SPT_DOWNLOAD_ENDPOINT = "/api/v1/spt/download"
CORETAX_SPT_VALIDATE_ENDPOINT = "/api/v1/spt/validate"

FORM_CODE = "1721"
FORM_VERSION = "1.0"
MAX_RETRY_ATTEMPTS = 3
CACHE_TTL_SECONDS = 86400


class SPTType(Enum):
    NORMAL = "normal"
    CORRECTION = "pembetulan"
    VOID = "batal"


class SPTStatus(Enum):
    DRAFT = "draft"
    PENDING = "pending"
    VALIDATED = "validated"
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


SPT_STATUS = {
    "DRAFT": SPTStatus.DRAFT.value,
    "PENDING": SPTStatus.PENDING.value,
    "SUBMITTED": SPTStatus.SUBMITTED.value,
    "APPROVED": SPTStatus.APPROVED.value,
    "REJECTED": SPTStatus.REJECTED.value,
    "CANCELLED": SPTStatus.CANCELLED.value,
    "VOID": SPTStatus.VOID.value,
    "ARCHIVED": SPTStatus.ARCHIVED.value,
}

SPT_TYPE_NORMAL = SPTType.NORMAL.value
SPT_TYPE_CORRECTION = SPTType.CORRECTION.value

TAX_BRACKETS = [
    (0, 60000000, Decimal("0.05")),
    (60000000, 250000000, Decimal("0.15")),
    (250000000, 500000000, Decimal("0.25")),
    (500000000, 5000000000, Decimal("0.30")),
    (5000000000, float("inf"), Decimal("0.35")),
]

PTKP_AMOUNT = {
    "TK/0": 54000000,
    "TK/1": 58500000,
    "TK/2": 63000000,
    "TK/3": 67500000,
    "K/0": 58500000,
    "K/1": 63000000,
    "K/2": 67500000,
    "K/3": 72000000,
}

MAX_BIaya_JABATAN_BULANAN = 500000
BIaya_JABATAN_PERSEN = Decimal("0.05")
MAX_IURAN_PENSIUN_BULANAN = 200000

JENIS_PENGHASILAN = {
    "01": "Gaji/Pensiun",
    "02": "Honorarium",
    "03": "Bonus",
    "04": "THR",
    "05": "Jasa Produksi",
    "06": "Pesangon",
    "07": "Uang Penggantian",
    "08": "Tunjangan",
}


class SPTError(Exception):
    pass


class SPTNotFoundError(SPTError):
    pass


class SPTAlreadyExistsError(SPTError):
    pass


class SPTInvalidStateError(SPTError):
    pass


class SPTValidationError(SPTError):
    pass


class SPTLockedError(SPTError):
    pass


class SPTXMLGenerationError(SPTError):
    pass


class SPTMasaPPH21:
    """Entity untuk SPT Masa PPh Pasal 21."""

    def __init__(
        self,
        npwp_pemotong: str,
        tahun: int,
        bulan: int,
        spt_type: SPTType = SPTType.NORMAL,
        correction_number: int = 0,
        total_bruto: Decimal = Decimal(0),
        total_pph_terutang: Decimal = Decimal(0),
        total_bayar: Decimal = Decimal(0),
        ntpn: str | None = None,
        spt_id: UUID | None = None,
        status: SPTStatus = SPTStatus.DRAFT,
        version: int = 1,
    ):
        self._spt_id = spt_id or uuid4()
        self._npwp_pemotong = npwp_pemotong
        self._tahun = tahun
        self._bulan = bulan
        self._spt_type = spt_type
        self._correction_number = correction_number
        self._total_bruto = total_bruto
        self._total_pph_terutang = total_pph_terutang
        self._total_bayar = total_bayar
        self._ntpn = ntpn
        self._status = status
        self._version = version
        self._created_at = datetime.now()
        self._updated_at = datetime.now()
        self._submitted_at: datetime | None = None
        self._approved_at: datetime | None = None
        self._rejected_at: datetime | None = None
        self._cancelled_at: datetime | None = None
        self._synced_at: datetime | None = None
        self._locked_at: datetime | None = None
        self._locked_by: UUID | None = None
        self._spt_number: str | None = None
        self._tracking_id: str | None = None
        self._coretax_id: str | None = None
        self._xml_content: str = ""
        self._rejection_reason: str = ""
        self._cancellation_reason: str = ""
        self._detail_karyawan: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._hash: str = ""
        self._calculate_hash()

    @property
    def spt_id(self) -> UUID:
        return self._spt_id

    @property
    def npwp_pemotong(self) -> str:
        return self._npwp_pemotong

    @property
    def tahun(self) -> int:
        return self._tahun

    @property
    def bulan(self) -> int:
        return self._bulan

    @property
    def masa_pajak(self) -> str:
        return f"{self._tahun}-{self._bulan:02d}"

    @property
    def spt_type(self) -> SPTType:
        return self._spt_type

    @property
    def correction_number(self) -> int:
        return self._correction_number

    @property
    def total_bruto(self) -> Decimal:
        return self._total_bruto

    @property
    def total_pph_terutang(self) -> Decimal:
        return self._total_pph_terutang

    @property
    def total_bayar(self) -> Decimal:
        return self._total_bayar

    @property
    def kurang_bayar(self) -> Decimal:
        return max(Decimal(0), self._total_pph_terutang - self._total_bayar)

    @property
    def lebih_bayar(self) -> Decimal:
        return max(Decimal(0), self._total_bayar - self._total_pph_terutang)

    @property
    def ntpn(self) -> str | None:
        return self._ntpn

    @property
    def ntpn_masked(self) -> str | None:
        if self._ntpn and len(self._ntpn) > 8:
            return f"{self._ntpn[:8]}...{self._ntpn[-4:]}"
        return self._ntpn

    @property
    def status(self) -> SPTStatus:
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
            SPTStatus.CANCELLED,
            SPTStatus.VOID,
            SPTStatus.ARCHIVED,
            SPTStatus.CLOSED,
        ]

    @property
    def spt_number(self) -> str | None:
        return self._spt_number

    @property
    def tracking_id(self) -> str | None:
        return self._tracking_id

    @property
    def coretax_id(self) -> str | None:
        return self._coretax_id

    @property
    def xml_content(self) -> str:
        return self._xml_content

    @property
    def rejection_reason(self) -> str:
        return self._rejection_reason

    @property
    def cancellation_reason(self) -> str:
        return self._cancellation_reason

    @property
    def detail_karyawan(self) -> list[dict[str, Any]]:
        return self._detail_karyawan.copy()

    @property
    def employee_count(self) -> int:
        return len(self._detail_karyawan)

    @property
    def hash(self) -> str:
        return self._hash

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    def create(self, created_by: UUID) -> SPTMasaPPH21:
        self._status = SPTStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "spt_pph21_created",
            {
                "spt_id": str(self._spt_id),
                "npwp": self._npwp_pemotong,
                "tahun": self._tahun,
                "bulan": self._bulan,
                "created_by": str(created_by),
            },
        )
        return self

    def update(self, data: dict[str, Any], updated_by: UUID) -> SPTMasaPPH21:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        if self._status not in [SPTStatus.DRAFT, SPTStatus.PENDING, SPTStatus.REJECTED]:
            raise SPTInvalidStateError(f"Cannot modify SPT in status {self._status.value}")
        old_data = self.to_dict()
        if "total_bruto" in data:
            self._total_bruto = Decimal(str(data["total_bruto"]))
        if "total_pph_terutang" in data:
            self._total_pph_terutang = Decimal(str(data["total_pph_terutang"]))
        if "total_bayar" in data:
            self._total_bayar = Decimal(str(data["total_bayar"]))
        if "ntpn" in data:
            self._ntpn = data["ntpn"]
        if "detail_karyawan" in data:
            self._detail_karyawan = data["detail_karyawan"]
        self._version += 1
        self._updated_at = datetime.now()
        self._calculate_hash()
        self._register_event(
            "spt_pph21_updated",
            {
                "spt_id": str(self._spt_id),
                "old_data": old_data,
                "new_data": self.to_dict(),
                "updated_by": str(updated_by),
            },
        )
        return self

    def delete(self, deleted_by: UUID, permanent: bool = False) -> SPTMasaPPH21:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        if permanent:
            self._status = SPTStatus.VOID
            self._cancelled_at = datetime.now()
        else:
            self._status = SPTStatus.ARCHIVED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph21_deleted",
            {
                "spt_id": str(self._spt_id),
                "permanent": permanent,
                "deleted_by": str(deleted_by),
            },
        )
        return self

    def restore(self, restored_by: UUID) -> SPTMasaPPH21:
        if self._status not in [SPTStatus.ARCHIVED, SPTStatus.VOID]:
            raise SPTInvalidStateError(f"Cannot restore SPT in status {self._status.value}")
        self._status = SPTStatus.DRAFT
        self._cancelled_at = None
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph21_restored",
            {
                "spt_id": str(self._spt_id),
                "restored_by": str(restored_by),
            },
        )
        return self

    def activate(self, activated_by: UUID) -> SPTMasaPPH21:
        if self._status != SPTStatus.DRAFT:
            raise SPTInvalidStateError(f"Cannot activate SPT in status {self._status.value}")
        self._status = SPTStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph21_activated",
            {
                "spt_id": str(self._spt_id),
                "activated_by": str(activated_by),
            },
        )
        return self

    def deactivate(self, deactivated_by: UUID) -> SPTMasaPPH21:
        if self._status != SPTStatus.PENDING:
            raise SPTInvalidStateError(f"Cannot deactivate SPT in status {self._status.value}")
        self._status = SPTStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph21_deactivated",
            {
                "spt_id": str(self._spt_id),
                "deactivated_by": str(deactivated_by),
            },
        )
        return self

    def lock(self, locked_by: UUID, reason: str = "") -> SPTMasaPPH21:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} already locked")
        self._locked_at = datetime.now()
        self._locked_by = locked_by
        self._status = SPTStatus.LOCKED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph21_locked",
            {
                "spt_id": str(self._spt_id),
                "locked_by": str(locked_by),
                "reason": reason,
            },
        )
        return self

    def unlock(self, unlocked_by: UUID) -> SPTMasaPPH21:
        if not self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is not locked")
        self._locked_at = None
        self._locked_by = None
        self._status = SPTStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph21_unlocked",
            {
                "spt_id": str(self._spt_id),
                "unlocked_by": str(unlocked_by),
            },
        )
        return self

    def validate(self, validator_id: UUID) -> SPTMasaPPH21:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        if self._status not in [SPTStatus.DRAFT, SPTStatus.PENDING]:
            raise SPTInvalidStateError(f"Cannot validate SPT in status {self._status.value}")
        errors = []
        if self._total_bruto < 0:
            errors.append("Total bruto tidak boleh negatif")
        if self._total_pph_terutang < 0:
            errors.append("PPh terutang tidak boleh negatif")
        if self._total_bayar < 0:
            errors.append("Total bayar tidak boleh negatif")
        if self.employee_count == 0 and self._total_pph_terutang > 0:
            errors.append("Ada PPh terutang tetapi tidak ada karyawan")
        if self.kurang_bayar > 0 and not self._ntpn:
            errors.append("Ada kurang bayar tetapi tidak ada NTPN")
        if self._bulan < 1 or self._bulan > 12:
            errors.append("Bulan pajak tidak valid")
        if self._tahun < 2000 or self._tahun > 2100:
            errors.append("Tahun pajak tidak valid")
        if self.kurang_bayar > 0 and self._ntpn:
            if not self._validate_ntpn_format(self._ntpn):
                errors.append("Format NTPN tidak valid (harus 16 digit)")
        if errors:
            raise SPTValidationError(f"Validasi gagal: {'; '.join(errors)}")
        self._status = SPTStatus.VALIDATED
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "spt_pph21_validated",
            {
                "spt_id": str(self._spt_id),
                "validator_id": str(validator_id),
            },
        )
        return self

    def approve(self, approver_id: UUID, notes: str = "") -> SPTMasaPPH21:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        if self._status != SPTStatus.SUBMITTED:
            raise SPTInvalidStateError(f"Cannot approve SPT in status {self._status.value}")
        self._status = SPTStatus.APPROVED
        self._approved_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph21_approved",
            {
                "spt_id": str(self._spt_id),
                "approver_id": str(approver_id),
                "notes": notes,
            },
        )
        return self

    def reject(self, rejector_id: UUID, reason: str) -> SPTMasaPPH21:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        if self._status not in [SPTStatus.PENDING, SPTStatus.SUBMITTED, SPTStatus.VALIDATED]:
            raise SPTInvalidStateError(f"Cannot reject SPT in status {self._status.value}")
        self._status = SPTStatus.REJECTED
        self._rejected_at = datetime.now()
        self._rejection_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph21_rejected",
            {
                "spt_id": str(self._spt_id),
                "rejector_id": str(rejector_id),
                "reason": reason,
            },
        )
        return self

    def submit(self, submitted_by: UUID) -> SPTMasaPPH21:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        if self._status not in [SPTStatus.PENDING, SPTStatus.VALIDATED]:
            raise SPTInvalidStateError(f"Cannot submit SPT in status {self._status.value}")
        self.validate(submitted_by)
        self._generate_xml()
        self._status = SPTStatus.SUBMITTED
        self._submitted_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph21_submitted",
            {
                "spt_id": str(self._spt_id),
                "submitted_by": str(submitted_by),
            },
        )
        return self

    def cancel(self, cancelled_by: UUID, reason: str) -> SPTMasaPPH21:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        if self._status in [SPTStatus.CANCELLED, SPTStatus.VOID, SPTStatus.CLOSED]:
            raise SPTInvalidStateError(f"Cannot cancel SPT in status {self._status.value}")
        self._status = SPTStatus.CANCELLED
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph21_cancelled",
            {
                "spt_id": str(self._spt_id),
                "cancelled_by": str(cancelled_by),
                "reason": reason,
            },
        )
        return self

    def void(self, voided_by: UUID, reason: str) -> SPTMasaPPH21:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        self._status = SPTStatus.VOID
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph21_voided",
            {
                "spt_id": str(self._spt_id),
                "voided_by": str(voided_by),
                "reason": reason,
            },
        )
        return self

    def get_status(self) -> dict[str, Any]:
        return {
            "status": self._status.value,
            "is_locked": self.is_locked,
            "is_active": self.is_active,
            "can_submit": self.can_transition(SPTStatus.SUBMITTED),
            "can_cancel": self.can_transition(SPTStatus.CANCELLED),
            "spt_number": self._spt_number,
            "tracking_id": self._tracking_id,
            "masa_pajak": self.masa_pajak,
            "kurang_bayar": float(self.kurang_bayar),
            "lebih_bayar": float(self.lebih_bayar),
        }

    def get_history(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def snapshot(self) -> dict[str, Any]:
        return {
            "spt_id": str(self._spt_id),
            "npwp_pemotong": self._npwp_pemotong,
            "tahun": self._tahun,
            "bulan": self._bulan,
            "masa_pajak": self.masa_pajak,
            "spt_type": self._spt_type.value,
            "correction_number": self._correction_number,
            "status": self._status.value,
            "version": self._version,
            "total_bruto": float(self._total_bruto),
            "total_pph_terutang": float(self._total_pph_terutang),
            "total_bayar": float(self._total_bayar),
            "kurang_bayar": float(self.kurang_bayar),
            "lebih_bayar": float(self.lebih_bayar),
            "ntpn": self.ntpn_masked,
            "spt_number": self._spt_number,
            "tracking_id": self._tracking_id,
            "coretax_id": self._coretax_id,
            "employee_count": self.employee_count,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "submitted_at": self._submitted_at.isoformat() if self._submitted_at else None,
            "approved_at": self._approved_at.isoformat() if self._approved_at else None,
            "rejected_at": self._rejected_at.isoformat() if self._rejected_at else None,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "hash": self._hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "spt_id": str(self._spt_id),
            "npwp_pemotong": self._npwp_pemotong,
            "tahun": self._tahun,
            "bulan": self._bulan,
            "spt_type": self._spt_type.value,
            "correction_number": self._correction_number,
            "total_bruto": float(self._total_bruto),
            "total_pph_terutang": float(self._total_pph_terutang),
            "total_bayar": float(self._total_bayar),
            "ntpn": self._ntpn,
            "status": self._status.value,
            "version": self._version,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "submitted_at": self._submitted_at.isoformat() if self._submitted_at else None,
            "approved_at": self._approved_at.isoformat() if self._approved_at else None,
            "rejected_at": self._rejected_at.isoformat() if self._rejected_at else None,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "synced_at": self._synced_at.isoformat() if self._synced_at else None,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "locked_by": str(self._locked_by) if self._locked_by else None,
            "spt_number": self._spt_number,
            "tracking_id": self._tracking_id,
            "coretax_id": self._coretax_id,
            "rejection_reason": self._rejection_reason,
            "cancellation_reason": self._cancellation_reason,
            "detail_karyawan": self._detail_karyawan,
            "hash": self._hash,
            "is_locked": self.is_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SPTMasaPPH21:
        return cls(
            spt_id=UUID(data["spt_id"]) if data.get("spt_id") else None,
            npwp_pemotong=data["npwp_pemotong"],
            tahun=data["tahun"],
            bulan=data["bulan"],
            spt_type=SPTType(data.get("spt_type", "normal")),
            correction_number=data.get("correction_number", 0),
            total_bruto=Decimal(str(data.get("total_bruto", 0))),
            total_pph_terutang=Decimal(str(data.get("total_pph_terutang", 0))),
            total_bayar=Decimal(str(data.get("total_bayar", 0))),
            ntpn=data.get("ntpn"),
            status=SPTStatus(data.get("status", "draft")),
            version=data.get("version", 1),
        )

    def audit_trail(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def can_transition(self, new_status: SPTStatus) -> bool:
        transitions = {
            SPTStatus.DRAFT: [SPTStatus.PENDING, SPTStatus.ARCHIVED, SPTStatus.VOID],
            SPTStatus.PENDING: [SPTStatus.VALIDATED, SPTStatus.REJECTED, SPTStatus.DRAFT, SPTStatus.CANCELLED],
            SPTStatus.VALIDATED: [SPTStatus.SUBMITTED, SPTStatus.REJECTED, SPTStatus.DRAFT],
            SPTStatus.SUBMITTED: [SPTStatus.APPROVED, SPTStatus.REJECTED, SPTStatus.CANCELLED],
            SPTStatus.APPROVED: [SPTStatus.POSTED, SPTStatus.CANCELLED, SPTStatus.CLOSED],
            SPTStatus.REJECTED: [SPTStatus.DRAFT, SPTStatus.CANCELLED],
            SPTStatus.POSTED: [SPTStatus.CLOSED, SPTStatus.CANCELLED],
            SPTStatus.CANCELLED: [SPTStatus.ARCHIVED],
            SPTStatus.VOID: [],
            SPTStatus.CLOSED: [SPTStatus.ARCHIVED],
            SPTStatus.ARCHIVED: [SPTStatus.CLOSED, SPTStatus.VOID],
            SPTStatus.LOCKED: [SPTStatus.PENDING],
            SPTStatus.ERROR: [SPTStatus.PENDING, SPTStatus.DRAFT],
            SPTStatus.SYNCED: [SPTStatus.VALIDATED, SPTStatus.ERROR],
        }
        return new_status in transitions.get(self._status, [])

    def transition(self, new_status: SPTStatus, actor_id: UUID, reason: str = "") -> SPTMasaPPH21:
        if not self.can_transition(new_status):
            raise SPTInvalidStateError(f"Status transition invalid: {self._status.value} -> {new_status.value}")
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
            "spt_pph21_status_changed",
            {
                "spt_id": str(self._spt_id),
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
            },
        )
        return self

    def register_event(self, event_type: str, event_data: dict[str, Any]) -> SPTMasaPPH21:
        return self._register_event(event_type, event_data)

    def _register_event(self, event_type: str, event_data: dict[str, Any]) -> SPTMasaPPH21:
        self._events.append(
            {
                "event_id": str(uuid4()),
                "event_type": event_type,
                "aggregate_id": str(self._spt_id),
                "aggregate_type": "SPTMasaPPH21",
                "occurred_at": datetime.now().isoformat(),
                "data": event_data,
            }
        )
        return self

    def get_events(self) -> list[dict[str, Any]]:
        return self._events.copy()

    def clear_events(self) -> SPTMasaPPH21:
        self._events.clear()
        return self

    def version(self) -> int:
        return self._version

    def calculate_tax(self, penghasilan_netto: Decimal) -> Decimal:
        pph = Decimal(0)
        sisa = penghasilan_netto
        for lower, upper, rate in TAX_BRACKETS:
            if upper == float("inf"):
                bracket_amount = sisa
            else:
                bracket_amount = min(sisa, Decimal(str(upper)) - Decimal(str(lower)))
            if bracket_amount <= 0:
                continue
            pph += bracket_amount * rate
            sisa -= bracket_amount
            if sisa <= 0:
                break
        return pph.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_ptkp(self, ptkp_status: str) -> Decimal:
        amount = PTKP_AMOUNT.get(ptkp_status, 54000000)
        return Decimal(str(amount))

    def collect_employee_data(self, employees: list[dict[str, Any]]) -> SPTMasaPPH21:
        self._detail_karyawan = []
        self._total_bruto = Decimal(0)
        self._total_pph_terutang = Decimal(0)
        for emp in employees:
            gross = Decimal(str(emp.get("gross", 0)))
            pph21 = Decimal(str(emp.get("pph21", 0)))
            self._detail_karyawan.append(
                {
                    "npwp": emp.get("npwp"),
                    "nama": emp.get("name"),
                    "ptkp_status": emp.get("ptkp_status", "TK/0"),
                    "bruto": float(gross),
                    "pph21": float(pph21),
                }
            )
            self._total_bruto += gross
            self._total_pph_terutang += pph21
        self._total_bayar = self._total_pph_terutang
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        return self

    def set_coretax_response(self, response: dict[str, Any]) -> SPTMasaPPH21:
        self._spt_number = response.get("spt_number")
        self._tracking_id = response.get("tracking_id")
        self._coretax_id = response.get("coretax_id")
        if response.get("status") == "success":
            self._status = SPTStatus.SUBMITTED
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def set_ntpn(self, ntpn: str, validated: bool = False) -> SPTMasaPPH21:
        if not self._validate_ntpn_format(ntpn):
            raise SPTValidationError(f"Invalid NTPN format: {ntpn}")
        self._ntpn = ntpn
        if validated:
            self._status = SPTStatus.VALIDATED
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def _calculate_hash(self) -> None:
        data = f"{self._spt_id}{self._npwp_pemotong}{self._tahun}{self._bulan}{self._total_pph_terutang}{self._status.value}{self._version}"
        self._hash = hashlib.sha256(data.encode()).hexdigest()

    def _generate_xml(self) -> str:
        try:
            root = ET.Element("SPT", {"xmlns": "http://www.djp.go.id/spt/pph21", "versi": FORM_VERSION})
            kepala = ET.SubElement(root, "Kepala")
            ET.SubElement(kepala, "KodeFormulir").text = FORM_CODE
            ET.SubElement(kepala, "JenisSPT").text = self._spt_type.value
            if self._spt_type == SPTType.CORRECTION:
                ET.SubElement(kepala, "NomorPembetulan").text = str(self._correction_number)
            ET.SubElement(kepala, "TahunPajak").text = str(self._tahun)
            ET.SubElement(kepala, "BulanPajak").text = f"{self._bulan:02d}"
            ET.SubElement(kepala, "NPWP").text = self._npwp_pemotong
            ET.SubElement(kepala, "Tanggal").text = date.today().isoformat()
            detail = ET.SubElement(root, "Detail")
            bruto_elem = ET.SubElement(detail, "PenghasilanBruto")
            ET.SubElement(bruto_elem, "Jumlah").text = f"{self._total_bruto:.2f}"
            pph_elem = ET.SubElement(detail, "PPhTerutang")
            ET.SubElement(pph_elem, "Jumlah").text = f"{self._total_pph_terutang:.2f}"
            bayar_elem = ET.SubElement(detail, "Pembayaran")
            ET.SubElement(bayar_elem, "JumlahBayar").text = f"{self._total_bayar:.2f}"
            if self._ntpn:
                ET.SubElement(bayar_elem, "NTPN").text = self._ntpn
            if self.kurang_bayar > 0:
                ET.SubElement(detail, "KurangBayar").text = f"{self.kurang_bayar:.2f}"
            if self.lebih_bayar > 0:
                ET.SubElement(detail, "LebihBayar").text = f"{self.lebih_bayar:.2f}"
            if self._detail_karyawan:
                lampiran = ET.SubElement(detail, "DaftarPemotongan")
                for emp in self._detail_karyawan:
                    karyawan = ET.SubElement(lampiran, "Karyawan")
                    if emp.get("npwp"):
                        ET.SubElement(karyawan, "NPWP").text = emp["npwp"]
                    ET.SubElement(karyawan, "Nama").text = emp["nama"]
                    ET.SubElement(karyawan, "StatusPTKP").text = emp.get("ptkp_status", "TK/0")
                    ET.SubElement(karyawan, "Bruto").text = f"{emp['bruto']:.2f}"
                    ET.SubElement(karyawan, "PPh21").text = f"{emp['pph21']:.2f}"
            xml_str = ET.tostring(root, encoding="utf-8")
            dom = minidom.parseString(xml_str)
            self._xml_content = dom.toprettyxml(indent="  ")
            return self._xml_content
        except Exception as e:
            raise SPTXMLGenerationError(f"Failed to generate XML SPT: {e}")

    def _validate_ntpn_format(self, ntpn: str) -> bool:
        import re
        return bool(re.match(r"^\d{16}$", ntpn))


# ============================================================================
# REPOSITORY INTERFACE
# ============================================================================
class SPTRepositoryPort:
    async def add(self, spt: SPTMasaPPH21) -> None:
        raise NotImplementedError
    async def save(self, spt: SPTMasaPPH21) -> None:
        raise NotImplementedError
    async def update(self, spt: SPTMasaPPH21) -> None:
        raise NotImplementedError
    async def delete(self, spt_id: UUID) -> None:
        raise NotImplementedError
    async def get_by_id(self, spt_id: UUID) -> SPTMasaPPH21 | None:
        raise NotImplementedError
    async def get_by_npwp_period(self, npwp: str, tahun: int, bulan: int) -> SPTMasaPPH21 | None:
        raise NotImplementedError
    async def get_by_tracking_id(self, tracking_id: str) -> SPTMasaPPH21 | None:
        raise NotImplementedError
    async def get_by_status(self, status: SPTStatus) -> list[SPTMasaPPH21]:
        raise NotImplementedError
    async def get_pending_submissions(self) -> list[SPTMasaPPH21]:
        raise NotImplementedError
    async def exists(self, npwp: str, tahun: int, bulan: int, correction_number: int = 0) -> bool:
        raise NotImplementedError


class _FallbackSPTRepository(SPTRepositoryPort):
    def __init__(self):
        self._store: dict[UUID, SPTMasaPPH21] = {}
        self._by_npwp_period: dict[str, UUID] = {}
        self._by_tracking_id: dict[str, UUID] = {}

    async def add(self, spt: SPTMasaPPH21) -> None:
        self._store[spt.spt_id] = spt
        key = f"{spt.npwp_pemotong}:{spt.tahun}:{spt.bulan}:{spt.correction_number}"
        self._by_npwp_period[key] = spt.spt_id

    async def save(self, spt: SPTMasaPPH21) -> None:
        self._store[spt.spt_id] = spt

    async def update(self, spt: SPTMasaPPH21) -> None:
        self._store[spt.spt_id] = spt

    async def delete(self, spt_id: UUID) -> None:
        if spt_id in self._store:
            del self._store[spt_id]

    async def get_by_id(self, spt_id: UUID) -> SPTMasaPPH21 | None:
        return self._store.get(spt_id)

    async def get_by_npwp_period(self, npwp: str, tahun: int, bulan: int) -> SPTMasaPPH21 | None:
        for spt in self._store.values():
            if spt.npwp_pemotong == npwp and spt.tahun == tahun and spt.bulan == bulan:
                return spt
        return None

    async def get_by_tracking_id(self, tracking_id: str) -> SPTMasaPPH21 | None:
        for spt in self._store.values():
            if spt.tracking_id == tracking_id:
                return spt
        return None

    async def get_by_status(self, status: SPTStatus) -> list[SPTMasaPPH21]:
        return [s for s in self._store.values() if s.status == status]

    async def get_pending_submissions(self) -> list[SPTMasaPPH21]:
        return [s for s in self._store.values() if s.status in [SPTStatus.PENDING, SPTStatus.VALIDATED, SPTStatus.SUBMITTED]]

    async def exists(self, npwp: str, tahun: int, bulan: int, correction_number: int = 0) -> bool:
        return await self.get_by_npwp_period(npwp, tahun, bulan) is not None


# ============================================================================
# SPT BUILDER
# ============================================================================
class SPTMasaPPH21Builder:
    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._coretax_client = None
        self._repository = _FallbackSPTRepository()
        self._payroll_service = None
        self._tax_service = None
        self._file_storage = None
        self._cache: dict[str, Any] = {}
        self._init_file_storage()

    def _load_config(self) -> dict[str, Any]:
        if self._config:
            return self._config
        return {
            "coretax_djp": {
                "spt_pph21": {
                    "file_storage_bucket": "coretax-spt-pph21",
                    "auto_submit": False,
                    "validation_strict": True,
                    "cache_ttl_seconds": CACHE_TTL_SECONDS,
                    "max_retry_attempts": MAX_RETRY_ATTEMPTS,
                }
            }
        }

    def _init_file_storage(self):
        try:
            from infrastructure.file_storage.s3_adapter import S3FileStorageAdapter
            bucket = self._load_config().get("coretax_djp", {}).get("spt_pph21", {}).get("file_storage_bucket", "coretax-spt-pph21")
            self._file_storage = S3FileStorageAdapter(bucket_name=bucket)
        except Exception as e:
            logger.warning(f"File storage not available for SPT PPh21: {e}")

    async def _get_coretax_client(self):
        if self._coretax_client is None:
            self._coretax_client = await get_coretax_client()
        return self._coretax_client

    async def _get_payroll_service(self):
        if self._payroll_service is None:
            from application.service_layer.service_payroll import PayrollService
            self._payroll_service = PayrollService()
        return self._payroll_service

    async def _get_tax_service(self):
        if self._tax_service is None:
            from application.service_layer.service_tax import TaxService
            self._tax_service = TaxService()
        return self._tax_service

    def _get_cache_key(self, npwp: str, tahun: int, bulan: int) -> str:
        return f"spt_pph21:{npwp}:{tahun}:{bulan:02d}"

    async def _get_cached(self, cache_key: str) -> dict[str, Any] | None:
        ttl = self._load_config().get("coretax_djp", {}).get("spt_pph21", {}).get("cache_ttl_seconds", CACHE_TTL_SECONDS)
        return self._cache.get(cache_key)

    async def _set_cached(self, cache_key: str, data: dict[str, Any]) -> None:
        ttl = self._load_config().get("coretax_djp", {}).get("spt_pph21", {}).get("cache_ttl_seconds", CACHE_TTL_SECONDS)
        self._cache[cache_key] = data

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    async def create(self, npwp_pemotong: str, tahun: int, bulan: int, created_by: UUID) -> dict[str, Any]:
        existing = await self._repository.get_by_npwp_period(npwp_pemotong, tahun, bulan)
        if existing:
            return {"success": False, "error": "SPT already exists for this period"}
        spt = SPTMasaPPH21(
            npwp_pemotong=npwp_pemotong,
            tahun=tahun,
            bulan=bulan,
            spt_type=SPTType.NORMAL,
        )
        spt.create(created_by)
        await self._repository.add(spt)
        cache_key = self._get_cache_key(npwp_pemotong, tahun, bulan)
        await self._set_cached(cache_key, spt.to_dict())
        return {
            "success": True,
            "spt_id": str(spt.spt_id),
            "masa_pajak": spt.masa_pajak,
            "status": spt.status.value,
        }

    async def collect_data(self, npwp_pemotong: str, tahun: int, bulan: int) -> dict[str, Any]:
        payroll_service = await self._get_payroll_service()
        try:
            employees = await payroll_service.get_employees_with_pph21(npwp_pemotong, tahun, bulan)
            total_bruto = Decimal(0)
            total_pph_terutang = Decimal(0)
            detail_per_employee = []
            for emp in employees:
                gross = await payroll_service.get_gross_income(emp["employee_id"], tahun, bulan)
                pph21 = await payroll_service.calculate_pph21(emp["employee_id"], tahun, bulan)
                total_bruto += gross
                total_pph_terutang += pph21
                detail_per_employee.append(
                    {
                        "npwp": emp.get("npwp"),
                        "nama": emp.get("name"),
                        "ptkp_status": emp.get("ptkp_status", "TK/0"),
                        "bruto": float(gross),
                        "pph21": float(pph21),
                    }
                )
            tax_service = await self._get_tax_service()
            ntpn_data = await tax_service.get_ntpn_for_period(npwp_pemotong, tahun, bulan, tax_type="21")
            return {
                "npwp_pemotong": npwp_pemotong,
                "tahun": tahun,
                "bulan": bulan,
                "total_bruto": total_bruto,
                "total_pph_terutang": total_pph_terutang,
                "total_bayar": total_pph_terutang,
                "ntpn": ntpn_data.get("ntpn") if ntpn_data else None,
                "detail_karyawan": detail_per_employee,
                "employee_count": len(employees),
            }
        except Exception as e:
            logger.error(f"Failed to collect data for SPT: {e}")
            return {
                "npwp_pemotong": npwp_pemotong,
                "tahun": tahun,
                "bulan": bulan,
                "total_bruto": Decimal(0),
                "total_pph_terutang": Decimal(0),
                "total_bayar": Decimal(0),
                "ntpn": None,
                "detail_karyawan": [],
                "employee_count": 0,
                "error": str(e),
            }

    async def build(self, npwp_pemotong: str, tahun: int, bulan: int, built_by: UUID) -> dict[str, Any]:
        spt = await self._repository.get_by_npwp_period(npwp_pemotong, tahun, bulan)
        if not spt:
            return await self.create(npwp_pemotong, tahun, bulan, built_by)
        data = await self.collect_data(npwp_pemotong, tahun, bulan)
        if "error" in data:
            return {"success": False, "error": data["error"]}
        spt.collect_employee_data(data["detail_karyawan"])
        if data["ntpn"]:
            spt.set_ntpn(data["ntpn"])
        await self._repository.update(spt)
        cache_key = self._get_cache_key(npwp_pemotong, tahun, bulan)
        await self._set_cached(cache_key, spt.to_dict())
        return {
            "success": True,
            "spt_id": str(spt.spt_id),
            "masa_pajak": spt.masa_pajak,
            "total_bruto": float(spt.total_bruto),
            "total_pph_terutang": float(spt.total_pph_terutang),
            "employee_count": spt.employee_count,
            "status": spt.status.value,
        }

    async def validate_spt(self, spt_id: UUID, validator_id: UUID) -> dict[str, Any]:
        spt = await self._repository.get_by_id(spt_id)
        if not spt:
            return {"success": False, "error": "SPT not found"}
        try:
            spt.validate(validator_id)
            await self._repository.update(spt)
            cache_key = self._get_cache_key(spt.npwp_pemotong, spt.tahun, spt.bulan)
            await self._set_cached(cache_key, spt.to_dict())
            return {
                "success": True,
                "spt_id": str(spt.spt_id),
                "valid": True,
                "status": spt.status.value,
            }
        except SPTValidationError as e:
            return {"success": False, "error": str(e), "valid": False}
        except (SPTLockedError, SPTInvalidStateError) as e:
            return {"success": False, "error": str(e)}

    async def submit_spt(self, spt_id: UUID, submitted_by: UUID, spt_type: str = SPTType.NORMAL.value, correction_number: int = 0) -> dict[str, Any]:
        spt = await self._repository.get_by_id(spt_id)
        if not spt:
            return {"success": False, "error": "SPT not found"}
        try:
            spt.validate(submitted_by)
            xml_content = spt._generate_xml()
            encoded_xml = base64.b64encode(xml_content.encode("utf-8")).decode("utf-8")
            if spt_type != spt.spt_type.value:
                spt._spt_type = SPTType(spt_type)
                spt._correction_number = correction_number
            spt.submit(submitted_by)
            await self._repository.update(spt)
            client = await self._get_coretax_client()
            payload = {
                "spt_xml": encoded_xml,
                "npwp": spt.npwp_pemotong,
                "tahun": spt.tahun,
                "bulan": spt.bulan,
                "spt_type": spt_type,
                "correction_number": correction_number,
            }
            for attempt in range(MAX_RETRY_ATTEMPTS):
                try:
                    response = await client.post(CORETAX_SPT_PPH21_ENDPOINT, payload)
                    spt.set_coretax_response(response)
                    await self._repository.update(spt)
                    if self._file_storage:
                        file_name = f"spt_pph21_{spt.npwp_pemotong}_{spt.tahun}_{spt.bulan:02d}.xml"
                        await self._file_storage.upload(
                            xml_content.encode("utf-8"),
                            file_name,
                            "application/xml",
                            metadata={
                                "spt_id": str(spt.spt_id),
                                "npwp": spt.npwp_pemotong,
                                "tahun": spt.tahun,
                                "bulan": spt.bulan,
                            },
                        )
                    cache_key = self._get_cache_key(spt.npwp_pemotong, spt.tahun, spt.bulan)
                    await self._set_cached(cache_key, spt.to_dict())
                    return {
                        "success": True,
                        "spt_id": str(spt.spt_id),
                        "spt_number": spt.spt_number,
                        "tracking_id": spt.tracking_id,
                        "coretax_id": spt.coretax_id,
                        "status": spt.status.value,
                        "message": response.get("message"),
                    }
                except CoretaxAuthError as e:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning(f"Retry {attempt + 1} for SPT submission: {e}")
                except Exception as e:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning(f"Retry {attempt + 1} for SPT submission: {e}")
        except (SPTValidationError, SPTLockedError, SPTInvalidStateError) as e:
            return {"success": False, "error": str(e)}
        except CoretaxAuthError as e:
            spt.transition(SPTStatus.ERROR, submitted_by, str(e))
            await self._repository.update(spt)
            return {"success": False, "error": f"Coretax authentication failed: {e}"}
        except Exception as e:
            logger.exception("Failed to submit SPT PPh21")
            spt.transition(SPTStatus.ERROR, submitted_by, str(e))
            await self._repository.update(spt)
            return {"success": False, "error": str(e)}

    async def check_spt_status(self, spt_id: UUID) -> dict[str, Any]:
        spt = await self._repository.get_by_id(spt_id)
        if not spt:
            return {"success": False, "error": "SPT not found"}
        if not spt.tracking_id:
            return {
                "success": True,
                "spt_id": str(spt.spt_id),
                "status": spt.status.value,
                "message": "Not yet submitted to Coretax",
            }
        client = await self._get_coretax_client()
        endpoint = f"{CORETAX_SPT_STATUS_ENDPOINT}/{spt.tracking_id}"
        try:
            response = await client.get(endpoint)
            new_status = response.get("status")
            if new_status == "approved" and spt.status != SPTStatus.APPROVED:
                spt.approve(UUID(int=0))
            elif new_status == "rejected" and spt.status != SPTStatus.REJECTED:
                spt.reject(UUID(int=0), response.get("rejection_reason", ""))
            await self._repository.update(spt)
            return {
                "success": True,
                "spt_id": str(spt.spt_id),
                "status": spt.status.value,
                "coretax_status": new_status,
                "approval_date": response.get("approval_date"),
                "rejection_reason": response.get("rejection_reason"),
            }
        except Exception as e:
            logger.error(f"Failed to check SPT status: {e}")
            return {"success": False, "error": str(e)}

    async def cancel_spt(self, spt_id: UUID, cancelled_by: UUID, reason: str) -> dict[str, Any]:
        spt = await self._repository.get_by_id(spt_id)
        if not spt:
            return {"success": False, "error": "SPT not found"}
        try:
            spt.cancel(cancelled_by, reason)
            await self._repository.update(spt)
            if spt.tracking_id:
                client = await self._get_coretax_client()
                payload = {"tracking_id": spt.tracking_id, "reason": reason}
                try:
                    await client.post(CORETAX_SPT_CANCEL_ENDPOINT, payload)
                except Exception as e:
                    logger.warning(f"Failed to cancel SPT in Coretax: {e}")
            cache_key = self._get_cache_key(spt.npwp_pemotong, spt.tahun, spt.bulan)
            if cache_key in self._cache:
                del self._cache[cache_key]
            return {
                "success": True,
                "spt_id": str(spt.spt_id),
                "cancelled": True,
                "status": spt.status.value,
            }
        except (SPTLockedError, SPTInvalidStateError) as e:
            return {"success": False, "error": str(e)}

    async def get_by_id(self, spt_id: UUID) -> SPTMasaPPH21 | None:
        return await self._repository.get_by_id(spt_id)

    async def get_by_npwp_period(self, npwp: str, tahun: int, bulan: int) -> SPTMasaPPH21 | None:
        return await self._repository.get_by_npwp_period(npwp, tahun, bulan)

    async def get_status(self, spt_id: UUID) -> dict[str, Any]:
        spt = await self._repository.get_by_id(spt_id)
        if not spt:
            return {"success": False, "error": "SPT not found"}
        return spt.get_status()

    async def get_history(self, spt_id: UUID) -> dict[str, Any]:
        spt = await self._repository.get_by_id(spt_id)
        if not spt:
            return {"success": False, "error": "SPT not found"}
        return {
            "success": True,
            "spt_id": str(spt.spt_id),
            "history": spt.get_history(),
        }

    async def snapshot(self, spt_id: UUID) -> dict[str, Any]:
        spt = await self._repository.get_by_id(spt_id)
        if not spt:
            return {"success": False, "error": "SPT not found"}
        return spt.snapshot()


# ============================================================================
# ALIAS FOR BACKWARD COMPATIBILITY
# ============================================================================
SPTMasaPph21Builder = SPTMasaPPH21Builder


# ============================================================================
# SINGLETON
# ============================================================================
_spt_pph21_builder: SPTMasaPPH21Builder | None = None

async def get_spt_pph21_builder(config: dict | None = None) -> SPTMasaPPH21Builder:
    global _spt_pph21_builder
    if _spt_pph21_builder is None:
        _spt_pph21_builder = SPTMasaPPH21Builder(config=config)
    return _spt_pph21_builder

__all__ = [
    "PTKP_AMOUNT",
    "TAX_BRACKETS",
    "SPTMasaPPH21",
    "SPTMasaPPH21Builder",
    "SPTMasaPph21Builder",
    "SPTStatus",
    "SPTType",
    "get_spt_pph21_builder",
]
