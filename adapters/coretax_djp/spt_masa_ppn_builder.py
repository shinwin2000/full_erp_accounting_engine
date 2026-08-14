#!/usr/bin/env python3
"""
Module: spt_masa_ppn_builder.py
Layer: Adapters (Coretax DJP)
Responsibility: Membangun SPT Masa PPN (Formulir 1111) berdasarkan data transaksi
               penjualan (faktur keluaran) dan pembelian (faktur masukan).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4
from xml.dom import minidom

from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError, get_coretax_client

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

CORETAX_SPT_PPN_ENDPOINT = "/api/v1/spt/ppn/submit"
CORETAX_SPT_STATUS_ENDPOINT = "/api/v1/spt/status"
CORETAX_SPT_CANCEL_ENDPOINT = "/api/v1/spt/cancel"
CORETAX_SPT_DOWNLOAD_ENDPOINT = "/api/v1/spt/download"
CORETAX_SPT_VALIDATE_ENDPOINT = "/api/v1/spt/validate"
CORETAX_SPT_CHECK_ENDPOINT = "/api/v1/spt/check"

FORM_CODE = "1111"
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
    CALCULATED = "calculated"


SPT_STATUS = {
    "DRAFT": SPTStatus.DRAFT.value,
    "SUBMITTED": SPTStatus.SUBMITTED.value,
    "APPROVED": SPTStatus.APPROVED.value,
    "REJECTED": SPTStatus.REJECTED.value,
    "CANCELLED": SPTStatus.CANCELLED.value,
    "VOID": SPTStatus.VOID.value,
}

SPT_TYPE_NORMAL = SPTType.NORMAL.value
SPT_TYPE_CORRECTION = SPTType.CORRECTION.value

PPN_RATE = Decimal("0.11")
PPN_RATE_PERCENT = 11

JENIS_PPN = {
    "01": "PPN Dalam Negeri",
    "02": "PPN Impor",
    "03": "PPN Ditanggung Pemerintah",
}

STATUS_KB_LB = {
    "KB": "Kurang Bayar",
    "LB": "Lebih Bayar",
    "Nihil": "Nihil",
}

JENIS_KOMPENSASI = {
    "1": "Kompensasi ke Masa Pajak Berikutnya",
    "2": "Restitusi",
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


class SPTCalculationError(SPTError):
    pass


class SPTMasaPPN:
    """Entity untuk SPT Masa PPN (1111)."""

    def __init__(
        self,
        npwp: str,
        tahun: int,
        bulan: int,
        spt_type: SPTType = SPTType.NORMAL,
        correction_number: int = 0,
        total_penyerahan_dpp: Decimal = Decimal(0),
        total_ppn_keluaran: Decimal = Decimal(0),
        total_ppn_masukan: Decimal = Decimal(0),
        total_retur_keluaran: Decimal = Decimal(0),
        total_retur_masukan: Decimal = Decimal(0),
        kompensasi: Decimal = Decimal(0),
        ppn_kurang_bayar: Decimal = Decimal(0),
        ppn_lebih_bayar: Decimal = Decimal(0),
        total_bayar: Decimal = Decimal(0),
        ntpn: str | None = None,
        status_restitusi: str | None = None,
        spt_id: UUID | None = None,
        status: SPTStatus = SPTStatus.DRAFT,
        version: int = 1,
    ):
        self._spt_id = spt_id or uuid4()
        self._npwp = npwp
        self._tahun = tahun
        self._bulan = bulan
        self._spt_type = spt_type
        self._correction_number = correction_number
        self._total_penyerahan_dpp = total_penyerahan_dpp
        self._total_ppn_keluaran = total_ppn_keluaran
        self._total_ppn_masukan = total_ppn_masukan
        self._total_retur_keluaran = total_retur_keluaran
        self._total_retur_masukan = total_retur_masukan
        self._kompensasi = kompensasi
        self._ppn_kurang_bayar = ppn_kurang_bayar
        self._ppn_lebih_bayar = ppn_lebih_bayar
        self._total_bayar = total_bayar
        self._ntpn = ntpn
        self._status_restitusi = status_restitusi
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
        self._detail_pk: list[dict[str, Any]] = []
        self._detail_pm: list[dict[str, Any]] = []
        self._detail_retur: list[dict[str, Any]] = []
        self._pemungut_ppn: dict[str, Any] = {}
        self._events: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._hash: str = ""
        self._calculate_hash()

    # ========================================================================
    # Property Accessors
    # ========================================================================
    @property
    def spt_id(self) -> UUID:
        return self._spt_id

    @property
    def npwp(self) -> str:
        return self._npwp

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
    def total_penyerahan_dpp(self) -> Decimal:
        return self._total_penyerahan_dpp

    @property
    def total_ppn_keluaran(self) -> Decimal:
        return self._total_ppn_keluaran

    @property
    def total_ppn_masukan(self) -> Decimal:
        return self._total_ppn_masukan

    @property
    def total_retur_keluaran(self) -> Decimal:
        return self._total_retur_keluaran

    @property
    def total_retur_masukan(self) -> Decimal:
        return self._total_retur_masukan

    @property
    def kompensasi(self) -> Decimal:
        return self._kompensasi

    @property
    def ppn_kurang_bayar(self) -> Decimal:
        return self._ppn_kurang_bayar

    @property
    def ppn_lebih_bayar(self) -> Decimal:
        return self._ppn_lebih_bayar

    @property
    def total_bayar(self) -> Decimal:
        return self._total_bayar

    @property
    def ntpn(self) -> str | None:
        return self._ntpn

    @property
    def ntpn_masked(self) -> str | None:
        if self._ntpn and len(self._ntpn) > 8:
            return f"{self._ntpn[:8]}...{self._ntpn[-4:]}"
        return self._ntpn

    @property
    def status_restitusi(self) -> str | None:
        return self._status_restitusi

    @property
    def status_kb_lb(self) -> str:
        if self._ppn_kurang_bayar > 0:
            return "KB"
        elif self._ppn_lebih_bayar > 0:
            return "LB"
        return "Nihil"

    @property
    def status_kb_lb_desc(self) -> str:
        return STATUS_KB_LB.get(self.status_kb_lb, "Unknown")

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
    def detail_pk(self) -> list[dict[str, Any]]:
        return self._detail_pk.copy()

    @property
    def detail_pm(self) -> list[dict[str, Any]]:
        return self._detail_pm.copy()

    @property
    def detail_retur(self) -> list[dict[str, Any]]:
        return self._detail_retur.copy()

    @property
    def pk_count(self) -> int:
        return len(self._detail_pk)

    @property
    def pm_count(self) -> int:
        return len(self._detail_pm)

    @property
    def retur_count(self) -> int:
        return len(self._detail_retur)

    @property
    def hash(self) -> str:
        return self._hash

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    def create(self, created_by: UUID) -> SPTMasaPPN:
        self._status = SPTStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "spt_ppn_created",
            {
                "spt_id": str(self._spt_id),
                "npwp": self._npwp,
                "tahun": self._tahun,
                "bulan": self._bulan,
                "created_by": str(created_by),
            },
        )
        return self

    def update(self, data: dict[str, Any], updated_by: UUID) -> SPTMasaPPN:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        if self._status not in [SPTStatus.DRAFT, SPTStatus.PENDING, SPTStatus.REJECTED]:
            raise SPTInvalidStateError(f"Cannot update SPT in status {self._status.value}")
        old_data = self.to_dict()
        if "total_penyerahan_dpp" in data:
            self._total_penyerahan_dpp = Decimal(str(data["total_penyerahan_dpp"]))
        if "total_ppn_keluaran" in data:
            self._total_ppn_keluaran = Decimal(str(data["total_ppn_keluaran"]))
        if "total_ppn_masukan" in data:
            self._total_ppn_masukan = Decimal(str(data["total_ppn_masukan"]))
        if "total_retur_keluaran" in data:
            self._total_retur_keluaran = Decimal(str(data["total_retur_keluaran"]))
        if "total_retur_masukan" in data:
            self._total_retur_masukan = Decimal(str(data["total_retur_masukan"]))
        if "kompensasi" in data:
            self._kompensasi = Decimal(str(data["kompensasi"]))
        if "ntpn" in data:
            self._ntpn = data["ntpn"]
        self._version += 1
        self._updated_at = datetime.now()
        self._calculate_hash()
        self._register_event(
            "spt_ppn_updated",
            {
                "spt_id": str(self._spt_id),
                "old_data": old_data,
                "new_data": self.to_dict(),
                "updated_by": str(updated_by),
            },
        )
        return self

    def delete(self, deleted_by: UUID, permanent: bool = False) -> SPTMasaPPN:
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
            "spt_ppn_deleted",
            {
                "spt_id": str(self._spt_id),
                "permanent": permanent,
                "deleted_by": str(deleted_by),
            },
        )
        return self

    def restore(self, restored_by: UUID) -> SPTMasaPPN:
        if self._status not in [SPTStatus.ARCHIVED, SPTStatus.VOID]:
            raise SPTInvalidStateError(f"Cannot restore SPT in status {self._status.value}")
        self._status = SPTStatus.DRAFT
        self._cancelled_at = None
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_ppn_restored",
            {
                "spt_id": str(self._spt_id),
                "restored_by": str(restored_by),
            },
        )
        return self

    def activate(self, activated_by: UUID) -> SPTMasaPPN:
        if self._status != SPTStatus.DRAFT:
            raise SPTInvalidStateError(f"Cannot activate SPT in status {self._status.value}")
        self._status = SPTStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_ppn_activated",
            {
                "spt_id": str(self._spt_id),
                "activated_by": str(activated_by),
            },
        )
        return self

    def deactivate(self, deactivated_by: UUID) -> SPTMasaPPN:
        if self._status != SPTStatus.PENDING:
            raise SPTInvalidStateError(f"Cannot deactivate SPT in status {self._status.value}")
        self._status = SPTStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_ppn_deactivated",
            {
                "spt_id": str(self._spt_id),
                "deactivated_by": str(deactivated_by),
            },
        )
        return self

    def lock(self, locked_by: UUID, reason: str = "") -> SPTMasaPPN:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} already locked")
        self._locked_at = datetime.now()
        self._locked_by = locked_by
        self._status = SPTStatus.LOCKED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_ppn_locked",
            {
                "spt_id": str(self._spt_id),
                "locked_by": str(locked_by),
                "reason": reason,
            },
        )
        return self

    def unlock(self, unlocked_by: UUID) -> SPTMasaPPN:
        if not self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is not locked")
        self._locked_at = None
        self._locked_by = None
        self._status = SPTStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_ppn_unlocked",
            {
                "spt_id": str(self._spt_id),
                "unlocked_by": str(unlocked_by),
            },
        )
        return self

    def validate(self, validator_id: UUID) -> SPTMasaPPN:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        if self._status not in [SPTStatus.DRAFT, SPTStatus.PENDING, SPTStatus.CALCULATED]:
            raise SPTInvalidStateError(f"Cannot validate SPT in status {self._status.value}")
        errors = []
        if self._total_ppn_keluaran < 0:
            errors.append("PPN Keluaran tidak boleh negatif")
        if self._total_ppn_masukan < 0:
            errors.append("PPN Masukan tidak boleh negatif")
        if self.pk_count == 0 and self._total_ppn_keluaran > 0:
            errors.append("Ada PPN Keluaran tetapi tidak ada faktur keluaran")
        if self.pm_count == 0 and self._total_ppn_masukan > 0:
            errors.append("Ada PPN Masukan tetapi tidak ada faktur masukan yang dikreditkan")
        if self._bulan < 1 or self._bulan > 12:
            errors.append("Bulan pajak tidak valid")
        if self._tahun < 2000 or self._tahun > 2100:
            errors.append("Tahun pajak tidak valid")
        expected_kurang_bayar = (
            (self._total_ppn_keluaran - self._total_retur_keluaran)
            - (self._total_ppn_masukan - self._total_retur_masukan)
            - self._kompensasi
        )
        expected_kurang_bayar = max(expected_kurang_bayar, Decimal(0))
        expected_lebih_bayar = max(-expected_kurang_bayar, Decimal(0))
        if abs(self._ppn_kurang_bayar - expected_kurang_bayar) > Decimal("0.01"):
            errors.append(f"PPN Kurang Bayar tidak sesuai: expected {expected_kurang_bayar}, got {self._ppn_kurang_bayar}")
        if abs(self._ppn_lebih_bayar - expected_lebih_bayar) > Decimal("0.01"):
            errors.append(f"PPN Lebih Bayar tidak sesuai: expected {expected_lebih_bayar}, got {self._ppn_lebih_bayar}")
        if self._ppn_kurang_bayar > 0:
            if not self._ntpn:
                errors.append("Ada kurang bayar tetapi tidak ada NTPN")
            elif not self._validate_ntpn_format(self._ntpn):
                errors.append("Format NTPN tidak valid (harus 16 digit)")
        if errors:
            raise SPTValidationError("Validasi gagal: {}".format("; ".join(errors)))
        self._status = SPTStatus.VALIDATED
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "spt_ppn_validated",
            {
                "spt_id": str(self._spt_id),
                "validator_id": str(validator_id),
            },
        )
        return self

    def approve(self, approver_id: UUID, notes: str = "") -> SPTMasaPPN:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        if self._status != SPTStatus.SUBMITTED:
            raise SPTInvalidStateError(f"Cannot approve SPT in status {self._status.value}")
        self._status = SPTStatus.APPROVED
        self._approved_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_ppn_approved",
            {
                "spt_id": str(self._spt_id),
                "approver_id": str(approver_id),
                "notes": notes,
            },
        )
        return self

    def reject(self, rejector_id: UUID, reason: str) -> SPTMasaPPN:
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
            "spt_ppn_rejected",
            {
                "spt_id": str(self._spt_id),
                "rejector_id": str(rejector_id),
                "reason": reason,
            },
        )
        return self

    def calculate(self, calculator_id: UUID) -> SPTMasaPPN:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        self._ppn_kurang_bayar = max(
            Decimal(0),
            (
                (self._total_ppn_keluaran - self._total_retur_keluaran)
                - (self._total_ppn_masukan - self._total_retur_masukan)
                - self._kompensasi
            ),
        )
        self._ppn_lebih_bayar = max(
            Decimal(0),
            (
                (self._total_ppn_masukan - self._total_retur_masukan)
                + self._kompensasi
                - (self._total_ppn_keluaran - self._total_retur_keluaran)
            ),
        )
        self._total_bayar = self._ppn_kurang_bayar
        self._status = SPTStatus.CALCULATED
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "spt_ppn_calculated",
            {
                "spt_id": str(self._spt_id),
                "ppn_kurang_bayar": float(self._ppn_kurang_bayar),
                "ppn_lebih_bayar": float(self._ppn_lebih_bayar),
                "calculator_id": str(calculator_id),
            },
        )
        return self

    def submit(self, submitted_by: UUID) -> SPTMasaPPN:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        if self._status not in [SPTStatus.PENDING, SPTStatus.VALIDATED, SPTStatus.CALCULATED]:
            raise SPTInvalidStateError(f"Cannot submit SPT in status {self._status.value}")
        self.validate(submitted_by)
        self._generate_xml()
        self._status = SPTStatus.SUBMITTED
        self._submitted_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_ppn_submitted",
            {
                "spt_id": str(self._spt_id),
                "submitted_by": str(submitted_by),
            },
        )
        return self

    def cancel(self, cancelled_by: UUID, reason: str) -> SPTMasaPPN:
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
            "spt_ppn_cancelled",
            {
                "spt_id": str(self._spt_id),
                "cancelled_by": str(cancelled_by),
                "reason": reason,
            },
        )
        return self

    def void(self, voided_by: UUID, reason: str) -> SPTMasaPPN:
        if self.is_locked:
            raise SPTLockedError(f"SPT {self.masa_pajak} is locked")
        self._status = SPTStatus.VOID
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_ppn_voided",
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
            "status_kb_lb": self.status_kb_lb_desc,
            "ppn_kurang_bayar": float(self._ppn_kurang_bayar),
            "ppn_lebih_bayar": float(self._ppn_lebih_bayar),
            "pk_count": self.pk_count,
            "pm_count": self.pm_count,
        }

    def get_history(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def snapshot(self) -> dict[str, Any]:
        return {
            "spt_id": str(self._spt_id),
            "npwp": self._npwp,
            "tahun": self._tahun,
            "bulan": self._bulan,
            "masa_pajak": self.masa_pajak,
            "spt_type": self._spt_type.value,
            "correction_number": self._correction_number,
            "status": self._status.value,
            "version": self._version,
            "total_penyerahan_dpp": float(self._total_penyerahan_dpp),
            "total_ppn_keluaran": float(self._total_ppn_keluaran),
            "total_ppn_masukan": float(self._total_ppn_masukan),
            "total_retur_keluaran": float(self._total_retur_keluaran),
            "total_retur_masukan": float(self._total_retur_masukan),
            "kompensasi": float(self._kompensasi),
            "ppn_kurang_bayar": float(self._ppn_kurang_bayar),
            "ppn_lebih_bayar": float(self._ppn_lebih_bayar),
            "total_bayar": float(self._total_bayar),
            "ntpn": self.ntpn_masked,
            "status_restitusi": self._status_restitusi,
            "status_kb_lb": self.status_kb_lb_desc,
            "spt_number": self._spt_number,
            "tracking_id": self._tracking_id,
            "coretax_id": self._coretax_id,
            "pk_count": self.pk_count,
            "pm_count": self.pm_count,
            "retur_count": self.retur_count,
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
            "npwp": self._npwp,
            "tahun": self._tahun,
            "bulan": self._bulan,
            "spt_type": self._spt_type.value,
            "correction_number": self._correction_number,
            "total_penyerahan_dpp": float(self._total_penyerahan_dpp),
            "total_ppn_keluaran": float(self._total_ppn_keluaran),
            "total_ppn_masukan": float(self._total_ppn_masukan),
            "total_retur_keluaran": float(self._total_retur_keluaran),
            "total_retur_masukan": float(self._total_retur_masukan),
            "kompensasi": float(self._kompensasi),
            "ppn_kurang_bayar": float(self._ppn_kurang_bayar),
            "ppn_lebih_bayar": float(self._ppn_lebih_bayar),
            "total_bayar": float(self._total_bayar),
            "ntpn": self._ntpn,
            "status_restitusi": self._status_restitusi,
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
            "detail_pk": self._detail_pk,
            "detail_pm": self._detail_pm,
            "detail_retur": self._detail_retur,
            "pemungut_ppn": self._pemungut_ppn,
            "hash": self._hash,
            "is_locked": self.is_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SPTMasaPPN:
        spt = cls(
            spt_id=UUID(data["spt_id"]) if data.get("spt_id") else None,
            npwp=data["npwp"],
            tahun=data["tahun"],
            bulan=data["bulan"],
            spt_type=SPTType(data.get("spt_type", "normal")),
            correction_number=data.get("correction_number", 0),
            total_penyerahan_dpp=Decimal(str(data.get("total_penyerahan_dpp", 0))),
            total_ppn_keluaran=Decimal(str(data.get("total_ppn_keluaran", 0))),
            total_ppn_masukan=Decimal(str(data.get("total_ppn_masukan", 0))),
            total_retur_keluaran=Decimal(str(data.get("total_retur_keluaran", 0))),
            total_retur_masukan=Decimal(str(data.get("total_retur_masukan", 0))),
            kompensasi=Decimal(str(data.get("kompensasi", 0))),
            ppn_kurang_bayar=Decimal(str(data.get("ppn_kurang_bayar", 0))),
            ppn_lebih_bayar=Decimal(str(data.get("ppn_lebih_bayar", 0))),
            total_bayar=Decimal(str(data.get("total_bayar", 0))),
            ntpn=data.get("ntpn"),
            status_restitusi=data.get("status_restitusi"),
            status=SPTStatus(data.get("status", "draft")),
            version=data.get("version", 1),
        )
        if data.get("detail_pk"):
            spt._detail_pk = data["detail_pk"]
        if data.get("detail_pm"):
            spt._detail_pm = data["detail_pm"]
        if data.get("detail_retur"):
            spt._detail_retur = data["detail_retur"]
        if data.get("pemungut_ppn"):
            spt._pemungut_ppn = data["pemungut_ppn"]
        return spt

    def audit_trail(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def can_transition(self, new_status: SPTStatus) -> bool:
        transitions = {
            SPTStatus.DRAFT: [SPTStatus.PENDING, SPTStatus.ARCHIVED, SPTStatus.VOID],
            SPTStatus.PENDING: [SPTStatus.CALCULATED, SPTStatus.VALIDATED, SPTStatus.REJECTED, SPTStatus.DRAFT, SPTStatus.CANCELLED],
            SPTStatus.CALCULATED: [SPTStatus.VALIDATED, SPTStatus.REJECTED, SPTStatus.DRAFT],
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

    def transition(self, new_status: SPTStatus, actor_id: UUID, reason: str = "") -> SPTMasaPPN:
        if not self.can_transition(new_status):
            raise SPTInvalidStateError(
                f"Cannot transition from {self._status.value} to {new_status.value}"
            )
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
            "spt_ppn_status_changed",
            {
                "spt_id": str(self._spt_id),
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
            },
        )
        return self

    def register_event(self, event_type: str, event_data: dict[str, Any]) -> SPTMasaPPN:
        return self._register_event(event_type, event_data)

    def _register_event(self, event_type: str, event_data: dict[str, Any]) -> SPTMasaPPN:
        self._events.append(
            {
                "event_id": str(uuid4()),
                "event_type": event_type,
                "aggregate_id": str(self._spt_id),
                "aggregate_type": "SPTMasaPPN",
                "occurred_at": datetime.now().isoformat(),
                "data": event_data,
            }
        )
        return self

    def get_events(self) -> list[dict[str, Any]]:
        return self._events.copy()

    def clear_events(self) -> SPTMasaPPN:
        self._events.clear()
        return self

    def collect_pk_data(self, faktur_list: list[dict[str, Any]]) -> SPTMasaPPN:
        self._detail_pk = []
        self._total_penyerahan_dpp = Decimal(0)
        self._total_ppn_keluaran = Decimal(0)
        self._total_retur_keluaran = Decimal(0)
        for faktur in faktur_list:
            dpp = Decimal(str(faktur.get("dpp", 0)))
            ppn = Decimal(str(faktur.get("ppn", 0)))
            retur = Decimal(str(faktur.get("retur", 0)))
            self._detail_pk.append(
                {
                    "faktur_id": str(faktur.get("faktur_id")),
                    "faktur_number": faktur.get("faktur_number"),
                    "npwp_pembeli": faktur.get("npwp_pembeli"),
                    "nama_pembeli": faktur.get("nama_pembeli"),
                    "dpp": float(dpp),
                    "ppn": float(ppn),
                    "tanggal_faktur": faktur.get("tanggal_faktur", date.today()).isoformat(),
                    "jenis_transaksi": faktur.get("jenis_transaksi", "01"),
                }
            )
            self._total_penyerahan_dpp += dpp
            self._total_ppn_keluaran += ppn
            self._total_retur_keluaran += retur
        return self

    def collect_pm_data(self, faktur_list: list[dict[str, Any]]) -> SPTMasaPPN:
        self._detail_pm = []
        self._total_ppn_masukan = Decimal(0)
        self._total_retur_masukan = Decimal(0)
        for faktur in faktur_list:
            ppn = Decimal(str(faktur.get("ppn", 0)))
            retur = Decimal(str(faktur.get("retur", 0)))
            self._detail_pm.append(
                {
                    "faktur_id": str(faktur.get("faktur_id")),
                    "faktur_number": faktur.get("faktur_number"),
                    "npwp_penjual": faktur.get("npwp_penjual"),
                    "nama_penjual": faktur.get("nama_penjual"),
                    "ppn": float(ppn),
                    "tanggal_faktur": faktur.get("tanggal_faktur", date.today()).isoformat(),
                }
            )
            self._total_ppn_masukan += ppn
            self._total_retur_masukan += retur
        return self

    def set_kompensasi(self, kompensasi: Decimal) -> SPTMasaPPN:
        self._kompensasi = kompensasi
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def set_ntpn(self, ntpn: str) -> SPTMasaPPN:
        if not self._validate_ntpn_format(ntpn):
            raise SPTValidationError(f"Invalid NTPN format: {ntpn}")
        self._ntpn = ntpn
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def set_status_restitusi(self, status_restitusi: str) -> SPTMasaPPN:
        self._status_restitusi = status_restitusi
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def set_coretax_response(self, response: dict[str, Any]) -> SPTMasaPPN:
        self._spt_number = response.get("spt_number")
        self._tracking_id = response.get("tracking_id")
        self._coretax_id = response.get("coretax_id")
        if response.get("status") == "success":
            self._status = SPTStatus.SUBMITTED
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def create_correction(self, correction_number: int, created_by: UUID) -> SPTMasaPPN:
        correction_spt = SPTMasaPPN(
            npwp=self._npwp,
            tahun=self._tahun,
            bulan=self._bulan,
            spt_type=SPTType.CORRECTION,
            correction_number=correction_number,
            status=SPTStatus.DRAFT,
        )
        correction_spt.create(created_by)
        return correction_spt

    def _calculate_hash(self) -> None:
        data = f"{self._spt_id}{self._npwp}{self._tahun}{self._bulan}{self._total_ppn_keluaran}{self._total_ppn_masukan}{self._status.value}"
        self._hash = hashlib.sha256(data.encode()).hexdigest()

    def _generate_xml(self) -> str:
        try:
            root = ET.Element("SPT", {"xmlns": "http://www.djp.go.id/spt/ppn", "versi": FORM_VERSION})
            kepala = ET.SubElement(root, "Kepala")
            ET.SubElement(kepala, "KodeFormulir").text = FORM_CODE
            ET.SubElement(kepala, "JenisSPT").text = self._spt_type.value
            if self._spt_type == SPTType.CORRECTION:
                ET.SubElement(kepala, "NomorPembetulan").text = str(self._correction_number)
            ET.SubElement(kepala, "TahunPajak").text = str(self._tahun)
            ET.SubElement(kepala, "BulanPajak").text = f"{self._bulan:02d}"
            ET.SubElement(kepala, "NPWP").text = self._npwp
            ET.SubElement(kepala, "Tanggal").text = date.today().isoformat()
            detail = ET.SubElement(root, "Detail")
            penyerahan = ET.SubElement(detail, "Penyerahan")
            ET.SubElement(penyerahan, "DPP").text = f"{self._total_penyerahan_dpp:.2f}"
            ET.SubElement(penyerahan, "PPN").text = f"{self._total_ppn_keluaran:.2f}"
            if self._detail_pk:
                lampiran_pk = ET.SubElement(detail, "DaftarFakturKeluaran")
                for pk in self._detail_pk[:100]:
                    pk_elem = ET.SubElement(lampiran_pk, "Faktur")
                    ET.SubElement(pk_elem, "NomorFaktur").text = pk.get("faktur_number", "")
                    ET.SubElement(pk_elem, "NPWP").text = pk.get("npwp_pembeli", "")
                    ET.SubElement(pk_elem, "Nama").text = pk.get("nama_pembeli", "")
                    ET.SubElement(pk_elem, "DPP").text = "{:.2f}".format(pk['dpp'])
                    ET.SubElement(pk_elem, "PPN").text = "{:.2f}".format(pk['ppn'])
                    ET.SubElement(pk_elem, "Tanggal").text = pk.get("tanggal_faktur", "")
            masukan = ET.SubElement(detail, "Masukan")
            ET.SubElement(masukan, "PPNMasukan").text = f"{self._total_ppn_masukan:.2f}"
            if self._pemungut_ppn:
                pemungut = ET.SubElement(masukan, "PemungutPPN")
                ET.SubElement(pemungut, "DPP").text = "{:.2f}".format(self._pemungut_ppn.get('dpp', 0))
                ET.SubElement(pemungut, "PPN").text = "{:.2f}".format(self._pemungut_ppn.get('ppn', 0))
            retur = ET.SubElement(detail, "Retur")
            ET.SubElement(retur, "ReturKeluaran").text = f"{self._total_retur_keluaran:.2f}"
            ET.SubElement(retur, "ReturMasukan").text = f"{self._total_retur_masukan:.2f}"
            ET.SubElement(detail, "Kompensasi").text = f"{self._kompensasi:.2f}"
            if self._ppn_kurang_bayar > 0:
                ET.SubElement(detail, "KurangBayar").text = f"{self._ppn_kurang_bayar:.2f}"
                ET.SubElement(detail, "StatusKurangBayar").text = "1"
            else:
                ET.SubElement(detail, "LebihBayar").text = f"{self._ppn_lebih_bayar:.2f}"
                if self._status_restitusi:
                    ET.SubElement(detail, "StatusLebihBayar").text = self._status_restitusi
            if self._ntpn and self._ppn_kurang_bayar > 0:
                bayar_elem = ET.SubElement(detail, "Pembayaran")
                ET.SubElement(bayar_elem, "NTPN").text = self._ntpn
                ET.SubElement(bayar_elem, "JumlahBayar").text = f"{self._total_bayar:.2f}"
            xml_str = ET.tostring(root, encoding="utf-8")
            dom = minidom.parseString(xml_str)
            self._xml_content = dom.toprettyxml(indent="  ")
            return self._xml_content
        except Exception as e:
            raise SPTXMLGenerationError(f"Failed to create XML SPT: {e}")

    def _validate_ntpn_format(self, ntpn: str) -> bool:
        import re
        return bool(re.match(r"^\d{16}$", ntpn))


# ============================================================================
# REPOSITORY INTERFACE
# ============================================================================
class SPTRepositoryPort:
    async def add(self, spt: SPTMasaPPN) -> None:
        raise NotImplementedError
    async def save(self, spt: SPTMasaPPN) -> None:
        raise NotImplementedError
    async def update(self, spt: SPTMasaPPN) -> None:
        raise NotImplementedError
    async def delete(self, spt_id: UUID) -> None:
        raise NotImplementedError
    async def get_by_id(self, spt_id: UUID) -> SPTMasaPPN | None:
        raise NotImplementedError
    async def get_by_npwp_period(self, npwp: str, tahun: int, bulan: int) -> SPTMasaPPN | None:
        raise NotImplementedError
    async def get_by_tracking_id(self, tracking_id: str) -> SPTMasaPPN | None:
        raise NotImplementedError
    async def get_by_status(self, status: SPTStatus) -> list[SPTMasaPPN]:
        raise NotImplementedError
    async def get_pending_submissions(self) -> list[SPTMasaPPN]:
        raise NotImplementedError
    async def exists(self, npwp: str, tahun: int, bulan: int, correction_number: int = 0) -> bool:
        raise NotImplementedError


class _FallbackSPTRepository(SPTRepositoryPort):
    def __init__(self):
        self._store: dict[UUID, SPTMasaPPN] = {}
        self._by_npwp_period: dict[str, UUID] = {}
        self._by_tracking_id: dict[str, UUID] = {}

    async def add(self, spt: SPTMasaPPN) -> None:
        self._store[spt.spt_id] = spt
        key = f"{spt.npwp}:{spt.tahun}:{spt.bulan}:{spt.correction_number}"
        self._by_npwp_period[key] = spt.spt_id
        if spt.tracking_id:
            self._by_tracking_id[spt.tracking_id] = spt.spt_id

    async def save(self, spt: SPTMasaPPN) -> None:
        self._store[spt.spt_id] = spt

    async def update(self, spt: SPTMasaPPN) -> None:
        self._store[spt.spt_id] = spt

    async def delete(self, spt_id: UUID) -> None:
        if spt_id in self._store:
            del self._store[spt_id]

    async def get_by_id(self, spt_id: UUID) -> SPTMasaPPN | None:
        return self._store.get(spt_id)

    async def get_by_npwp_period(self, npwp: str, tahun: int, bulan: int) -> SPTMasaPPN | None:
        for spt in self._store.values():
            if spt.npwp == npwp and spt.tahun == tahun and spt.bulan == bulan:
                return spt
        return None

    async def get_by_tracking_id(self, tracking_id: str) -> SPTMasaPPN | None:
        spt_id = self._by_tracking_id.get(tracking_id)
        if spt_id:
            return self._store.get(spt_id)
        return None

    async def get_by_status(self, status: SPTStatus) -> list[SPTMasaPPN]:
        return [s for s in self._store.values() if s.status == status]

    async def get_pending_submissions(self) -> list[SPTMasaPPN]:
        return [s for s in self._store.values() if s.status in [SPTStatus.PENDING, SPTStatus.VALIDATED, SPTStatus.CALCULATED, SPTStatus.SUBMITTED]]

    async def exists(self, npwp: str, tahun: int, bulan: int, correction_number: int = 0) -> bool:
        return await self.get_by_npwp_period(npwp, tahun, bulan) is not None


# ============================================================================
# SPT BUILDER
# ============================================================================
class SPTMasaPPNBuilder:
    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._coretax_client = None
        self._repository = _FallbackSPTRepository()
        self._tax_service = None
        self._file_storage = None
        self._cache: dict[str, Any] = {}
        self._init_file_storage()

    def _load_config(self) -> dict[str, Any]:
        if self._config:
            return self._config
        return {
            "coretax_djp": {
                "spt_ppn": {
                    "file_storage_bucket": "coretax-spt-ppn",
                    "auto_submit": False,
                    "validation_strict": True,
                    "cache_ttl_seconds": CACHE_TTL_SECONDS,
                    "max_retry_attempts": MAX_RETRY_ATTEMPTS,
                    "ppn_rate": float(PPN_RATE),
                }
            }
        }

    def _init_file_storage(self):
        try:
            from infrastructure.file_storage.s3_adapter import S3FileStorageAdapter
            bucket = self._load_config().get("coretax_djp", {}).get("spt_ppn", {}).get("file_storage_bucket", "coretax-spt-ppn")
            self._file_storage = S3FileStorageAdapter(bucket_name=bucket)
        except Exception as e:
            logger.warning(f"File storage not available for SPT PPN: {e}")

    async def _get_coretax_client(self):
        if self._coretax_client is None:
            self._coretax_client = await get_coretax_client()
        return self._coretax_client

    async def _get_tax_service(self):
        if self._tax_service is None:
            from application.service_layer.service_tax import TaxService
            self._tax_service = TaxService()
        return self._tax_service

    def _get_cache_key(self, npwp: str, tahun: int, bulan: int) -> str:
        return f"spt_ppn:{npwp}:{tahun}:{bulan:02d}"

    async def _get_cached(self, cache_key: str) -> dict[str, Any] | None:
        return self._cache.get(cache_key)

    async def _set_cached(self, cache_key: str, data: dict[str, Any]) -> None:
        self._cache[cache_key] = data

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    async def create(self, npwp: str, tahun: int, bulan: int, created_by: UUID) -> dict[str, Any]:
        existing = await self._repository.get_by_npwp_period(npwp, tahun, bulan)
        if existing:
            return {"success": False, "error": "SPT already exists for this period"}
        spt = SPTMasaPPN(
            npwp=npwp,
            tahun=tahun,
            bulan=bulan,
            spt_type=SPTType.NORMAL,
        )
        spt.create(created_by)
        await self._repository.add(spt)
        cache_key = self._get_cache_key(npwp, tahun, bulan)
        await self._set_cached(cache_key, spt.to_dict())
        return {
            "success": True,
            "spt_id": str(spt.spt_id),
            "masa_pajak": spt.masa_pajak,
            "status": spt.status.value,
        }

    async def collect_data(self, npwp: str, tahun: int, bulan: int) -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        try:
            pk_data = await tax_service.get_faktur_keluaran_by_period(npwp, tahun, bulan)
            total_penyerahan = sum(pk.get("dpp", Decimal(0)) for pk in pk_data)
            total_ppn_keluaran = sum(pk.get("ppn", Decimal(0)) for pk in pk_data)
            pm_data = await tax_service.get_faktur_masukan_credited_by_period(npwp, tahun, bulan)
            total_ppn_masukan = sum(pm.get("ppn", Decimal(0)) for pm in pm_data)
            retur_data = await tax_service.get_retur_by_period(npwp, tahun, bulan)
            total_retur_keluaran = sum(r.get("ppn_keluaran", Decimal(0)) for r in retur_data if r.get("type") == "keluaran")
            total_retur_masukan = sum(r.get("ppn_masukan", Decimal(0)) for r in retur_data if r.get("type") == "masukan")
            kompensasi = await tax_service.get_kompensasi_sebelumnya(npwp, tahun, bulan)
            ntpn_data = await tax_service.get_ntpn_for_period(npwp, tahun, bulan, tax_type="ppn")
            ppn_kurang_bayar = max(
                Decimal(0),
                ((total_ppn_keluaran - total_retur_keluaran) - (total_ppn_masukan - total_retur_masukan) - kompensasi),
            )
            ppn_lebih_bayar = max(
                Decimal(0),
                ((total_ppn_masukan - total_retur_masukan) + kompensasi - (total_ppn_keluaran - total_retur_keluaran)),
            )
            return {
                "npwp": npwp,
                "tahun": tahun,
                "bulan": bulan,
                "total_penyerahan": total_penyerahan,
                "total_ppn_keluaran": total_ppn_keluaran,
                "total_ppn_masukan": total_ppn_masukan,
                "total_retur_keluaran": total_retur_keluaran,
                "total_retur_masukan": total_retur_masukan,
                "kompensasi": kompensasi,
                "ppn_kurang_bayar": ppn_kurang_bayar,
                "ppn_lebih_bayar": ppn_lebih_bayar,
                "ntpn": ntpn_data.get("ntpn") if ntpn_data else None,
                "pk_count": len(pk_data),
                "pm_count": len(pm_data),
                "detail_pk": pk_data,
                "detail_pm": pm_data,
                "detail_retur": retur_data,
            }
        except Exception as e:
            logger.error(f"Failed to collect data for SPT PPN: {e}")
            return {
                "npwp": npwp,
                "tahun": tahun,
                "bulan": bulan,
                "total_penyerahan": Decimal(0),
                "total_ppn_keluaran": Decimal(0),
                "total_ppn_masukan": Decimal(0),
                "total_retur_keluaran": Decimal(0),
                "total_retur_masukan": Decimal(0),
                "kompensasi": Decimal(0),
                "ppn_kurang_bayar": Decimal(0),
                "ppn_lebih_bayar": Decimal(0),
                "ntpn": None,
                "pk_count": 0,
                "pm_count": 0,
                "detail_pk": [],
                "detail_pm": [],
                "detail_retur": [],
                "error": str(e),
            }

    async def build(self, npwp: str, tahun: int, bulan: int, built_by: UUID) -> dict[str, Any]:
        spt = await self._repository.get_by_npwp_period(npwp, tahun, bulan)
        if not spt:
            result = await self.create(npwp, tahun, bulan, built_by)
            if not result.get("success"):
                return result
            spt = await self._repository.get_by_npwp_period(npwp, tahun, bulan)
        if not spt:
            return {"success": False, "error": "Failed to create or retrieve SPT"}
        data = await self.collect_data(npwp, tahun, bulan)
        if "error" in data:
            return {"success": False, "error": data["error"]}
        spt.collect_pk_data(data["detail_pk"])
        spt.collect_pm_data(data["detail_pm"])
        if data["kompensasi"] > 0:
            spt.set_kompensasi(data["kompensasi"])
        if data["ntpn"]:
            spt.set_ntpn(data["ntpn"])
        spt.calculate(built_by)
        await self._repository.update(spt)
        cache_key = self._get_cache_key(npwp, tahun, bulan)
        await self._set_cached(cache_key, spt.to_dict())
        return {
            "success": True,
            "spt_id": str(spt.spt_id),
            "masa_pajak": spt.masa_pajak,
            "total_ppn_keluaran": float(spt.total_ppn_keluaran),
            "total_ppn_masukan": float(spt.total_ppn_masukan),
            "ppn_kurang_bayar": float(spt.ppn_kurang_bayar),
            "ppn_lebih_bayar": float(spt.ppn_lebih_bayar),
            "pk_count": spt.pk_count,
            "pm_count": spt.pm_count,
            "status": spt.status.value,
        }

    async def validate_spt(self, spt_id: UUID, validator_id: UUID) -> dict[str, Any]:
        spt = await self._repository.get_by_id(spt_id)
        if not spt:
            return {"success": False, "error": "SPT not found"}
        try:
            spt.validate(validator_id)
            await self._repository.update(spt)
            cache_key = self._get_cache_key(spt.npwp, spt.tahun, spt.bulan)
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
            if spt.status not in [SPTStatus.CALCULATED, SPTStatus.VALIDATED]:
                spt.calculate(submitted_by)
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
                "npwp": spt.npwp,
                "tahun": spt.tahun,
                "bulan": spt.bulan,
                "spt_type": spt_type,
                "correction_number": correction_number,
            }
            for attempt in range(MAX_RETRY_ATTEMPTS):
                try:
                    response = await client.post(CORETAX_SPT_PPN_ENDPOINT, payload)
                    spt.set_coretax_response(response)
                    await self._repository.update(spt)
                    if self._file_storage:
                        file_name = f"spt_ppn_{spt.npwp}_{spt.tahun}_{spt.bulan:02d}.xml"
                        await self._file_storage.upload(
                            xml_content.encode("utf-8"),
                            file_name,
                            "application/xml",
                            metadata={
                                "spt_id": str(spt.spt_id),
                                "npwp": spt.npwp,
                                "tahun": spt.tahun,
                                "bulan": spt.bulan,
                            },
                        )
                    cache_key = self._get_cache_key(spt.npwp, spt.tahun, spt.bulan)
                    await self._set_cached(cache_key, spt.to_dict())
                    try:
                        from infrastructure.telemetry.alert_manager_router import trigger_alert
                        await trigger_alert(
                            title="SPT PPN Submitted",
                            message=f"SPT PPN for {spt.npwp} period {spt.masa_pajak} submitted successfully",
                            severity="info",
                            source="SPTMasaPPNBuilder",
                        )
                    except ImportError:
                        pass
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
                    logger.warning(f"Retry {attempt + 1} for SPT PPN submission: {e}")
                except Exception as e:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning(f"Retry {attempt + 1} for SPT PPN submission: {e}")
        except (SPTValidationError, SPTLockedError, SPTInvalidStateError, SPTCalculationError) as e:
            return {"success": False, "error": str(e)}
        except CoretaxAuthError as e:
            spt.transition(SPTStatus.ERROR, submitted_by, str(e))
            await self._repository.update(spt)
            return {"success": False, "error": f"Coretax authentication failed: {e}"}
        except Exception as e:
            logger.exception("Failed to submit SPT PPN")
            spt.transition(SPTStatus.ERROR, submitted_by, str(e))
            await self._repository.update(spt)
            try:
                from infrastructure.telemetry.alert_manager_router import trigger_alert
                await trigger_alert(
                    title="SPT PPN Submission Failed",
                    message=f"Failed to submit SPT PPN: {e}",
                    severity="critical",
                    source="SPTMasaPPNBuilder",
                )
            except ImportError:
                pass
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
            cache_key = self._get_cache_key(spt.npwp, spt.tahun, spt.bulan)
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

    async def create_correction_spt(self, npwp: str, tahun: int, bulan: int, previous_spt_id: UUID, correction_number: int, submitted_by: UUID) -> dict[str, Any]:
        previous_spt = await self._repository.get_by_id(previous_spt_id)
        if not previous_spt:
            return {"success": False, "error": "Previous SPT not found"}
        correction_spt = previous_spt.create_correction(correction_number, submitted_by)
        await self._repository.add(correction_spt)
        return {
            "success": True,
            "spt_id": str(correction_spt.spt_id),
            "masa_pajak": correction_spt.masa_pajak,
            "correction_number": correction_number,
            "status": correction_spt.status.value,
        }

    async def get_by_id(self, spt_id: UUID) -> SPTMasaPPN | None:
        return await self._repository.get_by_id(spt_id)

    async def get_by_npwp_period(self, npwp: str, tahun: int, bulan: int) -> SPTMasaPPN | None:
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

    # ========================================================================
    # Legacy / Test Methods
    # ========================================================================
    def build_sync(self, faktur_list: list, masa: int, tahun: int) -> SPTMasaPpn:
        total_ppn_terutang = Decimal("0")
        for faktur in faktur_list:
            ppn = Decimal("0")
            if hasattr(faktur, "ppn"):
                ppn = Decimal(str(faktur.ppn))
            elif hasattr(faktur, "data") and isinstance(faktur.data, dict):
                ppn = Decimal(str(faktur.data.get("ppn", 0)))
            elif isinstance(faktur, dict):
                ppn = Decimal(str(faktur.get("ppn", 0)))
            total_ppn_terutang += ppn
        return SPTMasaPpn(total_ppn_terutang=total_ppn_terutang, masa=masa, tahun=tahun)


# ============================================================================
# SIMPLE SPT OBJECT (for legacy compatibility)
# ============================================================================
class SPTMasaPpn:
    def __init__(self, total_ppn_terutang: Decimal, masa: int, tahun: int):
        self.total_ppn_terutang = total_ppn_terutang
        self.masa = masa
        self.tahun = tahun
        self.total_ppn_keluaran = total_ppn_terutang
        self.total_ppn_masukan = Decimal(0)
        self.lebih_bayar = Decimal(0)
        self.kode_formulir = FORM_CODE

    def pay(self, amount: Decimal, bank_code: str) -> PaymentReference:
        import random
        ntpn = "".join(str(random.randint(0, 9)) for _ in range(16))
        return PaymentReference(ntpn=ntpn, amount=amount, bank_code=bank_code)

    def submit(self, ntpn: str) -> SubmissionResult:
        receipt_number = f"SPT-{self.tahun}{self.masa:02d}-{ntpn[:8]}"
        return SubmissionResult(is_submitted=True, receipt_number=receipt_number)


class PaymentReference:
    def __init__(self, ntpn: str, amount: Decimal, bank_code: str):
        self.ntpn = ntpn
        self.amount = amount
        self.bank_code = bank_code


class SubmissionResult:
    def __init__(self, is_submitted: bool, receipt_number: str):
        self.is_submitted = is_submitted
        self.receipt_number = receipt_number


# ============================================================================
# ALIAS FOR BACKWARD COMPATIBILITY
# ============================================================================
SPTMasaPpnBuilder = SPTMasaPPNBuilder


# ============================================================================
# SINGLETON
# ============================================================================
_spt_ppn_builder: SPTMasaPPNBuilder | None = None

async def get_spt_ppn_builder(config: dict | None = None) -> SPTMasaPPNBuilder:
    global _spt_ppn_builder
    if _spt_ppn_builder is None:
        _spt_ppn_builder = SPTMasaPPNBuilder(config=config)
    return _spt_ppn_builder

__all__ = [
    "PaymentReference",
    "SPTMasaPPN",
    "SPTMasaPPNBuilder",
    "SPTMasaPpn",
    "SPTMasaPpnBuilder",
    "SPTStatus",
    "SPTType",
    "SubmissionResult",
    "get_spt_ppn_builder",
]
