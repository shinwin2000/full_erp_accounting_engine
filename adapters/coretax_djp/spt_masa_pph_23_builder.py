#!/usr/bin/env python3
"""
Module: spt_masa_pph_23_builder.py
Layer: Adapters (Coretax DJP)
Responsibility: Membangun SPT Masa PPh Pasal 23/26 (Formulir 1721-VI) berdasarkan
               data pemotongan pajak atas jasa, sewa, bunga, royalti, hadiah,
               dan transaksi lain yang dikenakan PPh 23/26.
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

CORETAX_SPT_PPH23_ENDPOINT = "/api/v1/spt/pph23/submit"
CORETAX_SPT_STATUS_ENDPOINT = "/api/v1/spt/status"
CORETAX_SPT_CANCEL_ENDPOINT = "/api/v1/spt/cancel"
CORETAX_EBUPOT_SUBMIT_ENDPOINT = "/api/v1/e-bupot/submit"
CORETAX_EBUPOT_BATCH_ENDPOINT = "/api/v1/e-bupot/batch"

FORM_CODE_23 = "1721-VI"
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
    "SUBMITTED": SPTStatus.SUBMITTED.value,
    "APPROVED": SPTStatus.APPROVED.value,
    "REJECTED": SPTStatus.REJECTED.value,
    "CANCELLED": SPTStatus.CANCELLED.value,
    "VOID": SPTStatus.VOID.value,
}

SPT_TYPE_NORMAL = SPTType.NORMAL.value
SPT_TYPE_CORRECTION = SPTType.CORRECTION.value

PPh23_OBJECTS = {
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
PPh23_RATE_KONSTRUKSI = Decimal("0.03")
PPh26_RATE_DEFAULT = Decimal("0.20")
PPh26_RATE_WITHOUT_DGT = Decimal("0.20")
PPh26_RATE_WITH_DGT = Decimal("0.10")
PPH_FINAL_RATE = {
    "sewa_tanah_bangunan": Decimal("0.10"),
    "jasa_konstruksi": Decimal("0.03"),
    "usaha_jasa": Decimal("0.005"),
}


class SPT23Error(Exception):
    pass


class SPT23NotFoundError(SPT23Error):
    pass


class SPT23AlreadyExistsError(SPT23Error):
    pass


class SPT23InvalidStateError(SPT23Error):
    pass


class SPT23ValidationError(SPT23Error):
    pass


class SPT23LockedError(SPT23Error):
    pass


class SPT23XMLGenerationError(SPT23Error):
    pass


class SPTMasaPPH23:
    """Entity untuk SPT Masa PPh Pasal 23/26."""

    def __init__(
        self,
        npwp_pemotong: str,
        tahun: int,
        bulan: int,
        jenis_pajak: str = "23",
        spt_type: SPTType = SPTType.NORMAL,
        correction_number: int = 0,
        total_dpp: Decimal = Decimal(0),
        total_pph_dipotong: Decimal = Decimal(0),
        total_bayar: Decimal = Decimal(0),
        kompensasi: Decimal = Decimal(0),
        ntpn: str | None = None,
        spt_id: UUID | None = None,
        status: SPTStatus = SPTStatus.DRAFT,
        version: int = 1,
    ):
        self._spt_id = spt_id or uuid4()
        self._npwp_pemotong = npwp_pemotong
        self._tahun = tahun
        self._bulan = bulan
        self._jenis_pajak = jenis_pajak
        self._spt_type = spt_type
        self._correction_number = correction_number
        self._total_dpp = total_dpp
        self._total_pph_dipotong = total_pph_dipotong
        self._total_bayar = total_bayar
        self._kompensasi = kompensasi
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
        self._detail_bupot: list[dict[str, Any]] = []
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
    def jenis_pajak(self) -> str:
        return self._jenis_pajak

    @property
    def jenis_pajak_desc(self) -> str:
        return JENIS_PAJAK.get(self._jenis_pajak, "Unknown")

    @property
    def spt_type(self) -> SPTType:
        return self._spt_type

    @property
    def correction_number(self) -> int:
        return self._correction_number

    @property
    def total_dpp(self) -> Decimal:
        return self._total_dpp

    @property
    def total_pph_dipotong(self) -> Decimal:
        return self._total_pph_dipotong

    @property
    def total_bayar(self) -> Decimal:
        return self._total_bayar

    @property
    def kompensasi(self) -> Decimal:
        return self._kompensasi

    @property
    def kurang_bayar(self) -> Decimal:
        return max(Decimal(0), self._total_pph_dipotong - self._total_bayar - self._kompensasi)

    @property
    def lebih_bayar(self) -> Decimal:
        return max(Decimal(0), self._total_bayar + self._kompensasi - self._total_pph_dipotong)

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
    def detail_bupot(self) -> list[dict[str, Any]]:
        return self._detail_bupot.copy()

    @property
    def bupot_count(self) -> int:
        return len(self._detail_bupot)

    @property
    def hash(self) -> str:
        return self._hash

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    def create(self, created_by: UUID) -> SPTMasaPPH23:
        self._status = SPTStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "spt_pph23_created",
            {
                "spt_id": str(self._spt_id),
                "npwp": self._npwp_pemotong,
                "tahun": self._tahun,
                "bulan": self._bulan,
                "jenis_pajak": self._jenis_pajak,
                "created_by": str(created_by),
            },
        )
        return self

    def update(self, data: dict[str, Any], updated_by: UUID) -> SPTMasaPPH23:
        if self.is_locked:
            raise SPT23LockedError(f"SPT {self.masa_pajak} is locked")
        if self._status not in [SPTStatus.DRAFT, SPTStatus.PENDING, SPTStatus.REJECTED]:
            raise SPT23InvalidStateError(f"Cannot update SPT in status {self._status.value}")
        old_data = self.to_dict()
        if "total_dpp" in data:
            self._total_dpp = Decimal(str(data["total_dpp"]))
        if "total_pph_dipotong" in data:
            self._total_pph_dipotong = Decimal(str(data["total_pph_dipotong"]))
        if "total_bayar" in data:
            self._total_bayar = Decimal(str(data["total_bayar"]))
        if "kompensasi" in data:
            self._kompensasi = Decimal(str(data["kompensasi"]))
        if "ntpn" in data:
            self._ntpn = data["ntpn"]
        self._version += 1
        self._updated_at = datetime.now()
        self._calculate_hash()
        self._register_event(
            "spt_pph23_updated",
            {
                "spt_id": str(self._spt_id),
                "old_data": old_data,
                "new_data": self.to_dict(),
                "updated_by": str(updated_by),
            },
        )
        return self

    def delete(self, deleted_by: UUID, permanent: bool = False) -> SPTMasaPPH23:
        if self.is_locked:
            raise SPT23LockedError(f"SPT {self.masa_pajak} is locked")
        if permanent:
            self._status = SPTStatus.VOID
            self._cancelled_at = datetime.now()
        else:
            self._status = SPTStatus.ARCHIVED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph23_deleted",
            {
                "spt_id": str(self._spt_id),
                "permanent": permanent,
                "deleted_by": str(deleted_by),
            },
        )
        return self

    def restore(self, restored_by: UUID) -> SPTMasaPPH23:
        if self._status not in [SPTStatus.ARCHIVED, SPTStatus.VOID]:
            raise SPT23InvalidStateError(f"Cannot restore SPT in status {self._status.value}")
        self._status = SPTStatus.DRAFT
        self._cancelled_at = None
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph23_restored",
            {
                "spt_id": str(self._spt_id),
                "restored_by": str(restored_by),
            },
        )
        return self

    def activate(self, activated_by: UUID) -> SPTMasaPPH23:
        if self._status != SPTStatus.DRAFT:
            raise SPT23InvalidStateError(f"Cannot activate SPT in status {self._status.value}")
        self._status = SPTStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph23_activated",
            {
                "spt_id": str(self._spt_id),
                "activated_by": str(activated_by),
            },
        )
        return self

    def deactivate(self, deactivated_by: UUID) -> SPTMasaPPH23:
        if self._status != SPTStatus.PENDING:
            raise SPT23InvalidStateError(f"Cannot deactivate SPT in status {self._status.value}")
        self._status = SPTStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph23_deactivated",
            {
                "spt_id": str(self._spt_id),
                "deactivated_by": str(deactivated_by),
            },
        )
        return self

    def lock(self, locked_by: UUID, reason: str = "") -> SPTMasaPPH23:
        if self.is_locked:
            raise SPT23LockedError(f"SPT {self.masa_pajak} already locked")
        self._locked_at = datetime.now()
        self._locked_by = locked_by
        self._status = SPTStatus.LOCKED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph23_locked",
            {
                "spt_id": str(self._spt_id),
                "locked_by": str(locked_by),
                "reason": reason,
            },
        )
        return self

    def unlock(self, unlocked_by: UUID) -> SPTMasaPPH23:
        if not self.is_locked:
            raise SPT23LockedError(f"SPT {self.masa_pajak} is not locked")
        self._locked_at = None
        self._locked_by = None
        self._status = SPTStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph23_unlocked",
            {
                "spt_id": str(self._spt_id),
                "unlocked_by": str(unlocked_by),
            },
        )
        return self

    def validate(self, validator_id: UUID) -> SPTMasaPPH23:
        if self.is_locked:
            raise SPT23LockedError(f"SPT {self.masa_pajak} is locked")
        if self._status not in [SPTStatus.DRAFT, SPTStatus.PENDING]:
            raise SPT23InvalidStateError(f"Cannot validate SPT in status {self._status.value}")
        errors = []
        if self._total_dpp < 0:
            errors.append("Total DPP tidak boleh negatif")
        if self._total_pph_dipotong < 0:
            errors.append("Total PPh dipotong tidak boleh negatif")
        if self.bupot_count == 0 and self._total_pph_dipotong > 0:
            errors.append("Ada PPh dipotong tetapi tidak ada bukti potong")
        if self.kurang_bayar > 0 and not self._ntpn:
            errors.append("Ada kurang bayar tetapi tidak ada NTPN")
        if self._bulan < 1 or self._bulan > 12:
            errors.append("Bulan pajak tidak valid")
        if self._tahun < 2000 or self._tahun > 2100:
            errors.append("Tahun pajak tidak valid")
        if self._jenis_pajak not in ["23", "26", "4_2"]:
            errors.append("Jenis pajak tidak valid")
        total_dpp_from_bupot = sum(Decimal(str(b.get("dpp", 0))) for b in self._detail_bupot)
        total_pph_from_bupot = sum(Decimal(str(b.get("pph_dipotong", 0))) for b in self._detail_bupot)
        if abs(total_dpp_from_bupot - self._total_dpp) > Decimal("0.01"):
            errors.append(f"Total DPP tidak konsisten: {total_dpp_from_bupot} vs {self._total_dpp}")
        if abs(total_pph_from_bupot - self._total_pph_dipotong) > Decimal("0.01"):
            errors.append(f"Total PPh tidak konsisten: {total_pph_from_bupot} vs {self._total_pph_dipotong}")
        # Gabungkan nested if menjadi satu (SIM102)
        if self.kurang_bayar > 0 and self._ntpn and not self._validate_ntpn_format(self._ntpn):
            errors.append("Format NTPN tidak valid (harus 16 digit)")
        if errors:
            raise SPT23ValidationError("Validasi gagal: {}".format("; ".join(errors)))
        self._status = SPTStatus.VALIDATED
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "spt_pph23_validated",
            {
                "spt_id": str(self._spt_id),
                "validator_id": str(validator_id),
            },
        )
        return self

    def approve(self, approver_id: UUID, notes: str = "") -> SPTMasaPPH23:
        if self.is_locked:
            raise SPT23LockedError(f"SPT {self.masa_pajak} is locked")
        if self._status != SPTStatus.SUBMITTED:
            raise SPT23InvalidStateError(f"Cannot approve SPT in status {self._status.value}")
        self._status = SPTStatus.APPROVED
        self._approved_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph23_approved",
            {
                "spt_id": str(self._spt_id),
                "approver_id": str(approver_id),
                "notes": notes,
            },
        )
        return self

    def reject(self, rejector_id: UUID, reason: str) -> SPTMasaPPH23:
        if self.is_locked:
            raise SPT23LockedError(f"SPT {self.masa_pajak} is locked")
        if self._status not in [SPTStatus.PENDING, SPTStatus.SUBMITTED, SPTStatus.VALIDATED]:
            raise SPT23InvalidStateError(f"Cannot reject SPT in status {self._status.value}")
        self._status = SPTStatus.REJECTED
        self._rejected_at = datetime.now()
        self._rejection_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph23_rejected",
            {
                "spt_id": str(self._spt_id),
                "rejector_id": str(rejector_id),
                "reason": reason,
            },
        )
        return self

    def submit(self, submitted_by: UUID) -> SPTMasaPPH23:
        if self.is_locked:
            raise SPT23LockedError(f"SPT {self.masa_pajak} is locked")
        if self._status not in [SPTStatus.PENDING, SPTStatus.VALIDATED]:
            raise SPT23InvalidStateError(f"Cannot submit SPT in status {self._status.value}")
        self.validate(submitted_by)
        self._generate_xml()
        self._status = SPTStatus.SUBMITTED
        self._submitted_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph23_submitted",
            {
                "spt_id": str(self._spt_id),
                "submitted_by": str(submitted_by),
            },
        )
        return self

    def cancel(self, cancelled_by: UUID, reason: str) -> SPTMasaPPH23:
        if self.is_locked:
            raise SPT23LockedError(f"SPT {self.masa_pajak} is locked")
        if self._status in [SPTStatus.CANCELLED, SPTStatus.VOID, SPTStatus.CLOSED]:
            raise SPT23InvalidStateError(f"Cannot cancel SPT in status {self._status.value}")
        self._status = SPTStatus.CANCELLED
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph23_cancelled",
            {
                "spt_id": str(self._spt_id),
                "cancelled_by": str(cancelled_by),
                "reason": reason,
            },
        )
        return self

    def void(self, voided_by: UUID, reason: str) -> SPTMasaPPH23:
        if self.is_locked:
            raise SPT23LockedError(f"SPT {self.masa_pajak} is locked")
        self._status = SPTStatus.VOID
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_pph23_voided",
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
            "jenis_pajak": self.jenis_pajak_desc,
            "kurang_bayar": float(self.kurang_bayar),
            "lebih_bayar": float(self.lebih_bayar),
            "bupot_count": self.bupot_count,
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
            "jenis_pajak": self._jenis_pajak,
            "jenis_pajak_desc": self.jenis_pajak_desc,
            "spt_type": self._spt_type.value,
            "correction_number": self._correction_number,
            "status": self._status.value,
            "version": self._version,
            "total_dpp": float(self._total_dpp),
            "total_pph_dipotong": float(self._total_pph_dipotong),
            "total_bayar": float(self._total_bayar),
            "kompensasi": float(self._kompensasi),
            "kurang_bayar": float(self.kurang_bayar),
            "lebih_bayar": float(self.lebih_bayar),
            "ntpn": self.ntpn_masked,
            "spt_number": self._spt_number,
            "tracking_id": self._tracking_id,
            "coretax_id": self._coretax_id,
            "bupot_count": self.bupot_count,
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
            "jenis_pajak": self._jenis_pajak,
            "spt_type": self._spt_type.value,
            "correction_number": self._correction_number,
            "total_dpp": float(self._total_dpp),
            "total_pph_dipotong": float(self._total_pph_dipotong),
            "total_bayar": float(self._total_bayar),
            "kompensasi": float(self._kompensasi),
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
            "detail_bupot": self._detail_bupot,
            "hash": self._hash,
            "is_locked": self.is_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SPTMasaPPH23:
        return cls(
            spt_id=UUID(data["spt_id"]) if data.get("spt_id") else None,
            npwp_pemotong=data["npwp_pemotong"],
            tahun=data["tahun"],
            bulan=data["bulan"],
            jenis_pajak=data.get("jenis_pajak", "23"),
            spt_type=SPTType(data.get("spt_type", "normal")),
            correction_number=data.get("correction_number", 0),
            total_dpp=Decimal(str(data.get("total_dpp", 0))),
            total_pph_dipotong=Decimal(str(data.get("total_pph_dipotong", 0))),
            total_bayar=Decimal(str(data.get("total_bayar", 0))),
            kompensasi=Decimal(str(data.get("kompensasi", 0))),
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

    def transition(self, new_status: SPTStatus, actor_id: UUID, reason: str = "") -> SPTMasaPPH23:
        if not self.can_transition(new_status):
            raise SPT23InvalidStateError(f"Cannot transition from {self._status.value} to {new_status.value}")
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
            "spt_pph23_status_changed",
            {
                "spt_id": str(self._spt_id),
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
            },
        )
        return self

    def register_event(self, event_type: str, event_data: dict[str, Any]) -> SPTMasaPPH23:
        return self._register_event(event_type, event_data)

    def _register_event(self, event_type: str, event_data: dict[str, Any]) -> SPTMasaPPH23:
        self._events.append(
            {
                "event_id": str(uuid4()),
                "event_type": event_type,
                "aggregate_id": str(self._spt_id),
                "aggregate_type": "SPTMasaPPH23",
                "occurred_at": datetime.now().isoformat(),
                "data": event_data,
            }
        )
        return self

    def get_events(self) -> list[dict[str, Any]]:
        return self._events.copy()

    def clear_events(self) -> SPTMasaPPH23:
        self._events.clear()
        return self

    def calculate_pph23_rate(self, object_type: str, has_npwp: bool, is_construction: bool = False) -> Decimal:
        if is_construction:
            return PPh23_RATE_KONSTRUKSI
        if has_npwp:
            return PPh23_RATE_WITH_NPWP
        else:
            return PPh23_RATE_WITHOUT_NPWP

    def calculate_pph26_rate(self, has_dgt_form: bool = False, treaty_rate: Decimal | None = None) -> Decimal:
        if treaty_rate:
            return treaty_rate
        if has_dgt_form:
            return PPh26_RATE_WITH_DGT
        return PPh26_RATE_DEFAULT

    def collect_bupot_data(self, bupot_list: list[dict[str, Any]]) -> SPTMasaPPH23:
        self._detail_bupot = []
        self._total_dpp = Decimal(0)
        self._total_pph_dipotong = Decimal(0)
        for bupot in bupot_list:
            dpp = Decimal(str(bupot.get("dpp", 0)))
            pph = Decimal(str(bupot.get("pph_dipotong", 0)))
            self._detail_bupot.append(
                {
                    "bupot_id": str(bupot.get("bupot_id")),
                    "bupot_number": bupot.get("bupot_number"),
                    "npwp_penerima": bupot.get("npwp_penerima"),
                    "nama_penerima": bupot.get("nama_penerima"),
                    "jenis_penghasilan_code": bupot.get("object_type", "05"),
                    "jenis_penghasilan_text": PPh23_OBJECTS.get(bupot.get("object_type", "05"), "Lainnya"),
                    "dpp": float(dpp),
                    "tarif": float(bupot.get("rate", 0)),
                    "pph_dipotong": float(pph),
                    "tanggal_pemotongan": bupot.get("withholding_date", date.today()).isoformat(),
                    "invoice_reference": bupot.get("invoice_number"),
                }
            )
            self._total_dpp += dpp
            self._total_pph_dipotong += pph
        self._total_bayar = self._total_pph_dipotong
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        return self

    def set_coretax_response(self, response: dict[str, Any]) -> SPTMasaPPH23:
        self._spt_number = response.get("spt_number")
        self._tracking_id = response.get("tracking_id")
        self._coretax_id = response.get("coretax_id")
        if response.get("status") == "success":
            self._status = SPTStatus.SUBMITTED
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def set_ntpn(self, ntpn: str) -> SPTMasaPPH23:
        if not self._validate_ntpn_format(ntpn):
            raise SPT23ValidationError(f"Invalid NTPN format: {ntpn}")
        self._ntpn = ntpn
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def set_kompensasi(self, kompensasi: Decimal) -> SPTMasaPPH23:
        self._kompensasi = kompensasi
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def _calculate_hash(self) -> None:
        data = f"{self._spt_id}{self._npwp_pemotong}{self._tahun}{self._bulan}{self._total_pph_dipotong}{self._status.value}{self._version}"
        self._hash = hashlib.sha256(data.encode()).hexdigest()

    def _generate_xml(self) -> str:
        try:
            root = ET.Element("SPT", {"xmlns": "http://www.djp.go.id/spt/pph23", "versi": FORM_VERSION})
            kepala = ET.SubElement(root, "Kepala")
            ET.SubElement(kepala, "KodeFormulir").text = FORM_CODE_23
            ET.SubElement(kepala, "JenisSPT").text = self._spt_type.value
            ET.SubElement(kepala, "JenisPajak").text = self._jenis_pajak
            if self._spt_type == SPTType.CORRECTION:
                ET.SubElement(kepala, "NomorPembetulan").text = str(self._correction_number)
            ET.SubElement(kepala, "TahunPajak").text = str(self._tahun)
            ET.SubElement(kepala, "BulanPajak").text = f"{self._bulan:02d}"
            ET.SubElement(kepala, "NPWP").text = self._npwp_pemotong
            ET.SubElement(kepala, "Tanggal").text = date.today().isoformat()
            detail = ET.SubElement(root, "Detail")
            if self._detail_bupot:
                lampiran = ET.SubElement(detail, "DaftarPemotongan")
                for bupot in self._detail_bupot:
                    pemotongan = ET.SubElement(lampiran, "Pemotongan")
                    ET.SubElement(pemotongan, "BupotNumber").text = bupot.get("bupot_number", "")
                    ET.SubElement(pemotongan, "NPWP").text = bupot.get("npwp_penerima", "")
                    ET.SubElement(pemotongan, "Nama").text = bupot.get("nama_penerima", "")
                    ET.SubElement(pemotongan, "JenisPenghasilanCode").text = bupot.get("jenis_penghasilan_code", "05")
                    ET.SubElement(pemotongan, "JenisPenghasilanText").text = bupot.get("jenis_penghasilan_text", "Lainnya")
                    ET.SubElement(pemotongan, "DPP").text = "{:.2f}".format(bupot['dpp'])
                    ET.SubElement(pemotongan, "Tarif").text = "{:.2f}".format(bupot['tarif'])
                    ET.SubElement(pemotongan, "PPhDipotong").text = "{:.2f}".format(bupot['pph_dipotong'])
                    if bupot.get("tanggal_pemotongan"):
                        ET.SubElement(pemotongan, "TanggalPemotongan").text = bupot["tanggal_pemotongan"]
            total_elem = ET.SubElement(detail, "Ringkasan")
            ET.SubElement(total_elem, "TotalDPP").text = f"{self._total_dpp:.2f}"
            ET.SubElement(total_elem, "TotalPPh").text = f"{self._total_pph_dipotong:.2f}"
            if self._kompensasi > 0:
                ET.SubElement(total_elem, "Kompensasi").text = f"{self._kompensasi:.2f}"
            if self.kurang_bayar > 0:
                ET.SubElement(total_elem, "KurangBayar").text = f"{self.kurang_bayar:.2f}"
            if self.lebih_bayar > 0:
                ET.SubElement(total_elem, "LebihBayar").text = f"{self.lebih_bayar:.2f}"
            if self._ntpn:
                bayar_elem = ET.SubElement(detail, "Pembayaran")
                ET.SubElement(bayar_elem, "NTPN").text = self._ntpn
                ET.SubElement(bayar_elem, "JumlahBayar").text = f"{self._total_bayar:.2f}"
            xml_str = ET.tostring(root, encoding="utf-8")
            dom = minidom.parseString(xml_str)
            self._xml_content = dom.toprettyxml(indent="  ")
            return self._xml_content
        except Exception as e:
            raise SPT23XMLGenerationError(f"Failed to create XML SPT: {e}")

    def _validate_ntpn_format(self, ntpn: str) -> bool:
        import re
        return bool(re.match(r"^\d{16}$", ntpn))


# ============================================================================
# REPOSITORY INTERFACE
# ============================================================================
class SPT23RepositoryPort:
    async def add(self, spt: SPTMasaPPH23) -> None:
        raise NotImplementedError
    async def save(self, spt: SPTMasaPPH23) -> None:
        raise NotImplementedError
    async def update(self, spt: SPTMasaPPH23) -> None:
        raise NotImplementedError
    async def delete(self, spt_id: UUID) -> None:
        raise NotImplementedError
    async def get_by_id(self, spt_id: UUID) -> SPTMasaPPH23 | None:
        raise NotImplementedError
    async def get_by_npwp_period(self, npwp: str, tahun: int, bulan: int, jenis_pajak: str = "23") -> SPTMasaPPH23 | None:
        raise NotImplementedError
    async def get_by_tracking_id(self, tracking_id: str) -> SPTMasaPPH23 | None:
        raise NotImplementedError
    async def get_by_status(self, status: SPTStatus) -> list[SPTMasaPPH23]:
        raise NotImplementedError
    async def get_pending_submissions(self) -> list[SPTMasaPPH23]:
        raise NotImplementedError
    async def exists(self, npwp: str, tahun: int, bulan: int, jenis_pajak: str = "23", correction_number: int = 0) -> bool:
        raise NotImplementedError


class _FallbackSPT23Repository(SPT23RepositoryPort):
    def __init__(self):
        self._store: dict[UUID, SPTMasaPPH23] = {}
        self._by_npwp_period: dict[str, UUID] = {}
        self._by_tracking_id: dict[str, UUID] = {}

    async def add(self, spt: SPTMasaPPH23) -> None:
        self._store[spt.spt_id] = spt
        key = f"{spt.npwp_pemotong}:{spt.tahun}:{spt.bulan}:{spt.jenis_pajak}:{spt.correction_number}"
        self._by_npwp_period[key] = spt.spt_id
        if spt.tracking_id:
            self._by_tracking_id[spt.tracking_id] = spt.spt_id

    async def save(self, spt: SPTMasaPPH23) -> None:
        self._store[spt.spt_id] = spt

    async def update(self, spt: SPTMasaPPH23) -> None:
        self._store[spt.spt_id] = spt

    async def delete(self, spt_id: UUID) -> None:
        if spt_id in self._store:
            del self._store[spt_id]

    async def get_by_id(self, spt_id: UUID) -> SPTMasaPPH23 | None:
        return self._store.get(spt_id)

    async def get_by_npwp_period(self, npwp: str, tahun: int, bulan: int, jenis_pajak: str = "23") -> SPTMasaPPH23 | None:
        for spt in self._store.values():
            if spt.npwp_pemotong == npwp and spt.tahun == tahun and spt.bulan == bulan and spt.jenis_pajak == jenis_pajak:
                return spt
        return None

    async def get_by_tracking_id(self, tracking_id: str) -> SPTMasaPPH23 | None:
        spt_id = self._by_tracking_id.get(tracking_id)
        if spt_id:
            return self._store.get(spt_id)
        return None

    async def get_by_status(self, status: SPTStatus) -> list[SPTMasaPPH23]:
        return [s for s in self._store.values() if s.status == status]

    async def get_pending_submissions(self) -> list[SPTMasaPPH23]:
        return [s for s in self._store.values() if s.status in [SPTStatus.PENDING, SPTStatus.VALIDATED, SPTStatus.SUBMITTED]]

    async def exists(self, npwp: str, tahun: int, bulan: int, jenis_pajak: str = "23", correction_number: int = 0) -> bool:
        return await self.get_by_npwp_period(npwp, tahun, bulan, jenis_pajak) is not None


# ============================================================================
# SPT BUILDER
# ============================================================================
class SPTMasaPPH23Builder:
    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._coretax_client = None
        self._repository = _FallbackSPT23Repository()
        self._ap_service = None
        self._tax_service = None
        self._file_storage = None
        self._cache: dict[str, Any] = {}
        self._init_file_storage()

    def _load_config(self) -> dict[str, Any]:
        if self._config:
            return self._config
        return {
            "coretax_djp": {
                "spt_pph23": {
                    "file_storage_bucket": "coretax-spt-pph23",
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
            bucket = self._load_config().get("coretax_djp", {}).get("spt_pph23", {}).get("file_storage_bucket", "coretax-spt-pph23")
            self._file_storage = S3FileStorageAdapter(bucket_name=bucket)
        except Exception as e:
            logger.warning(f"File storage not available for SPT PPh23: {e}")

    async def _get_coretax_client(self):
        if self._coretax_client is None:
            self._coretax_client = await get_coretax_client()
        return self._coretax_client

    async def _get_ap_service(self):
        if self._ap_service is None:
            from application.service_layer.service_ap import APService
            self._ap_service = APService()
        return self._ap_service

    async def _get_tax_service(self):
        if self._tax_service is None:
            from application.service_layer.service_tax import TaxService
            self._tax_service = TaxService()
        return self._tax_service

    def _get_cache_key(self, npwp: str, tahun: int, bulan: int, jenis_pajak: str = "23") -> str:
        return f"spt_pph23:{npwp}:{tahun}:{bulan:02d}:{jenis_pajak}"

    async def _get_cached(self, cache_key: str) -> dict[str, Any] | None:
        return self._cache.get(cache_key)

    async def _set_cached(self, cache_key: str, data: dict[str, Any]) -> None:
        self._cache[cache_key] = data

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    async def create(self, npwp_pemotong: str, tahun: int, bulan: int, jenis_pajak: str = "23", created_by: UUID | None = None) -> dict[str, Any]:
        existing = await self._repository.get_by_npwp_period(npwp_pemotong, tahun, bulan, jenis_pajak)
        if existing:
            return {"success": False, "error": "SPT already exists for this period"}
        spt = SPTMasaPPH23(
            npwp_pemotong=npwp_pemotong,
            tahun=tahun,
            bulan=bulan,
            jenis_pajak=jenis_pajak,
            spt_type=SPTType.NORMAL,
        )
        if created_by:
            spt.create(created_by)
        await self._repository.add(spt)
        cache_key = self._get_cache_key(npwp_pemotong, tahun, bulan, jenis_pajak)
        await self._set_cached(cache_key, spt.to_dict())
        return {
            "success": True,
            "spt_id": str(spt.spt_id),
            "masa_pajak": spt.masa_pajak,
            "jenis_pajak": spt.jenis_pajak_desc,
            "status": spt.status.value,
        }

    async def collect_data(self, npwp_pemotong: str, tahun: int, bulan: int, jenis_pajak: str = "23") -> dict[str, Any]:
        tax_service = await self._get_tax_service()
        try:
            bupots = await tax_service.get_bupot_list(npwp_pemotong=npwp_pemotong, tahun=tahun, bulan=bulan, tax_type=jenis_pajak)
            total_dpp = Decimal(0)
            total_pph_dipotong = Decimal(0)
            detail_per_bupot = []
            for bupot in bupots:
                dpp = Decimal(str(bupot.get("dpp", 0)))
                pph = Decimal(str(bupot.get("pph_amount", 0)))
                total_dpp += dpp
                total_pph_dipotong += pph
                detail_per_bupot.append(
                    {
                        "bupot_id": bupot.get("id"),
                        "bupot_number": bupot.get("bupot_number"),
                        "npwp_penerima": bupot.get("npwp_penerima"),
                        "nama_penerima": bupot.get("nama_penerima"),
                        "object_type": bupot.get("object_type", "05"),
                        "dpp": dpp,
                        "rate": bupot.get("rate", 0),
                        "pph_amount": pph,
                        "withholding_date": bupot.get("withholding_date", date.today()),
                        "invoice_number": bupot.get("invoice_number"),
                    }
                )
            kompensasi = await tax_service.get_kompensasi_pph23(npwp_pemotong, tahun, bulan, jenis_pajak)
            ntpn_data = await tax_service.get_ntpn_for_period(npwp_pemotong, tahun, bulan, tax_type=jenis_pajak)
            return {
                "npwp_pemotong": npwp_pemotong,
                "tahun": tahun,
                "bulan": bulan,
                "jenis_pajak": jenis_pajak,
                "total_dpp": total_dpp,
                "total_pph_dipotong": total_pph_dipotong,
                "total_bayar": total_pph_dipotong,
                "kompensasi": kompensasi,
                "ntpn": ntpn_data.get("ntpn") if ntpn_data else None,
                "detail_bupot": detail_per_bupot,
                "bupot_count": len(bupots),
            }
        except Exception as e:
            logger.error(f"Failed to collect data for SPT PPh23: {e}")
            return {
                "npwp_pemotong": npwp_pemotong,
                "tahun": tahun,
                "bulan": bulan,
                "jenis_pajak": jenis_pajak,
                "total_dpp": Decimal(0),
                "total_pph_dipotong": Decimal(0),
                "total_bayar": Decimal(0),
                "kompensasi": Decimal(0),
                "ntpn": None,
                "detail_bupot": [],
                "bupot_count": 0,
                "error": str(e),
            }

    async def build(self, npwp_pemotong: str, tahun: int, bulan: int, jenis_pajak: str = "23", built_by: UUID | None = None) -> dict[str, Any]:
        spt = await self._repository.get_by_npwp_period(npwp_pemotong, tahun, bulan, jenis_pajak)
        if not spt:
            result = await self.create(npwp_pemotong, tahun, bulan, jenis_pajak, built_by)
            if not result.get("success"):
                return result
            spt = await self._repository.get_by_npwp_period(npwp_pemotong, tahun, bulan, jenis_pajak)
        if not spt:
            return {"success": False, "error": "Failed to create or retrieve SPT"}
        data = await self.collect_data(npwp_pemotong, tahun, bulan, jenis_pajak)
        if "error" in data:
            return {"success": False, "error": data["error"]}
        spt.collect_bupot_data(data["detail_bupot"])
        if data["kompensasi"] > 0:
            spt.set_kompensasi(data["kompensasi"])
        if data["ntpn"]:
            spt.set_ntpn(data["ntpn"])
        await self._repository.update(spt)
        cache_key = self._get_cache_key(npwp_pemotong, tahun, bulan, jenis_pajak)
        await self._set_cached(cache_key, spt.to_dict())
        return {
            "success": True,
            "spt_id": str(spt.spt_id),
            "masa_pajak": spt.masa_pajak,
            "jenis_pajak": spt.jenis_pajak_desc,
            "total_dpp": float(spt.total_dpp),
            "total_pph_dipotong": float(spt.total_pph_dipotong),
            "bupot_count": spt.bupot_count,
            "status": spt.status.value,
        }

    async def validate_spt(self, spt_id: UUID, validator_id: UUID) -> dict[str, Any]:
        spt = await self._repository.get_by_id(spt_id)
        if not spt:
            return {"success": False, "error": "SPT not found"}
        try:
            spt.validate(validator_id)
            await self._repository.update(spt)
            cache_key = self._get_cache_key(spt.npwp_pemotong, spt.tahun, spt.bulan, spt.jenis_pajak)
            await self._set_cached(cache_key, spt.to_dict())
            return {
                "success": True,
                "spt_id": str(spt.spt_id),
                "valid": True,
                "status": spt.status.value,
            }
        except SPT23ValidationError as e:
            return {"success": False, "error": str(e), "valid": False}
        except (SPT23LockedError, SPT23InvalidStateError) as e:
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
                "tax_type": spt.jenis_pajak,
            }
            for attempt in range(MAX_RETRY_ATTEMPTS):
                try:
                    response = await client.post(CORETAX_SPT_PPH23_ENDPOINT, payload)
                    spt.set_coretax_response(response)
                    await self._repository.update(spt)
                    if self._file_storage:
                        file_name = f"spt_pph23_{spt.npwp_pemotong}_{spt.tahun}_{spt.bulan:02d}_{spt.jenis_pajak}.xml"
                        await self._file_storage.upload(
                            xml_content.encode("utf-8"),
                            file_name,
                            "application/xml",
                            metadata={
                                "spt_id": str(spt.spt_id),
                                "npwp": spt.npwp_pemotong,
                                "tahun": spt.tahun,
                                "bulan": spt.bulan,
                                "jenis_pajak": spt.jenis_pajak,
                            },
                        )
                    try:
                        from infrastructure.telemetry.alert_manager_router import trigger_alert
                        await trigger_alert(
                            title="SPT PPh23 Submitted",
                            message=f"SPT PPh23 {spt.jenis_pajak_desc} for {spt.npwp_pemotong} period {spt.masa_pajak} submitted successfully",
                            severity="info",
                            source="SPTMasaPPH23Builder",
                        )
                    except ImportError:
                        pass
                    cache_key = self._get_cache_key(spt.npwp_pemotong, spt.tahun, spt.bulan, spt.jenis_pajak)
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
                    logger.warning(f"Retry {attempt + 1} for SPT PPh23 submission: {e}")
                except Exception as e:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning(f"Retry {attempt + 1} for SPT PPh23 submission: {e}")
        except (SPT23ValidationError, SPT23LockedError, SPT23InvalidStateError) as e:
            return {"success": False, "error": str(e)}
        except CoretaxAuthError as e:
            spt.transition(SPTStatus.ERROR, submitted_by, str(e))
            await self._repository.update(spt)
            return {"success": False, "error": f"Coretax authentication failed: {e}"}
        except Exception as e:
            logger.exception("Failed to submit SPT PPh23")
            spt.transition(SPTStatus.ERROR, submitted_by, str(e))
            await self._repository.update(spt)
            try:
                from infrastructure.telemetry.alert_manager_router import trigger_alert
                await trigger_alert(
                    title="SPT PPh23 Submission Failed",
                    message=f"Failed to submit SPT PPh23: {e}",
                    severity="critical",
                    source="SPTMasaPPH23Builder",
                )
            except ImportError:
                pass
            return {"success": False, "error": str(e)}

    async def submit_bupot(self, bupot_data: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_coretax_client()
        payload = {
            "npwp_pemotong": bupot_data["npwp_pemotong"],
            "npwp_penerima": bupot_data["npwp_penerima"],
            "nama_penerima": bupot_data["nama_penerima"],
            "jenis_penghasilan": bupot_data["object_type"],
            "dpp": float(bupot_data["dpp"]),
            "tarif": float(bupot_data["rate"]),
            "pph_dipotong": float(bupot_data["pph_amount"]),
            "tanggal_pemotongan": bupot_data["withholding_date"].isoformat(),
            "masa_pajak": bupot_data["bulan"],
            "tahun_pajak": bupot_data["tahun"],
            "invoice_reference": bupot_data.get("invoice_number"),
        }
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.post(CORETAX_EBUPOT_SUBMIT_ENDPOINT, payload)
                return {
                    "success": True,
                    "bupot_id": response.get("bupot_id"),
                    "bupot_number": response.get("bupot_number"),
                    "status": response.get("status"),
                }
            except Exception as e:
                logger.error(f"Failed to submit e-Bupot (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {"success": False, "error": str(e)}
        return {"success": False, "error": "Max retries exceeded"}

    async def submit_bupot_batch(self, bupot_list: list[dict[str, Any]]) -> dict[str, Any]:
        client = await self._get_coretax_client()
        payload = {
            "bupot_list": [
                {
                    "npwp_pemotong": b["npwp_pemotong"],
                    "npwp_penerima": b["npwp_penerima"],
                    "nama_penerima": b["nama_penerima"],
                    "jenis_penghasilan": b["object_type"],
                    "dpp": float(b["dpp"]),
                    "tarif": float(b["rate"]),
                    "pph_dipotong": float(b["pph_amount"]),
                    "tanggal_pemotongan": b["withholding_date"].isoformat(),
                    "masa_pajak": b["bulan"],
                    "tahun_pajak": b["tahun"],
                }
                for b in bupot_list
            ]
        }
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                response = await client.post(CORETAX_EBUPOT_BATCH_ENDPOINT, payload)
                return {
                    "success": True,
                    "submitted_count": response.get("submitted_count", 0),
                    "failed_count": response.get("failed_count", 0),
                    "results": response.get("results", []),
                }
            except Exception as e:
                logger.error(f"Failed to submit e-Bupot batch (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    return {"success": False, "error": str(e)}
        return {"success": False, "error": "Max retries exceeded"}

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
            cache_key = self._get_cache_key(spt.npwp_pemotong, spt.tahun, spt.bulan, spt.jenis_pajak)
            if cache_key in self._cache:
                del self._cache[cache_key]
            return {
                "success": True,
                "spt_id": str(spt.spt_id),
                "cancelled": True,
                "status": spt.status.value,
            }
        except (SPT23LockedError, SPT23InvalidStateError) as e:
            return {"success": False, "error": str(e)}

    async def get_by_id(self, spt_id: UUID) -> SPTMasaPPH23 | None:
        return await self._repository.get_by_id(spt_id)

    async def get_by_npwp_period(self, npwp: str, tahun: int, bulan: int, jenis_pajak: str = "23") -> SPTMasaPPH23 | None:
        return await self._repository.get_by_npwp_period(npwp, tahun, bulan, jenis_pajak)

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
SPTMasaPph23Builder = SPTMasaPPH23Builder


# ============================================================================
# SINGLETON
# ============================================================================
_spt_pph23_builder: SPTMasaPPH23Builder | None = None

async def get_spt_pph23_builder(config: dict | None = None) -> SPTMasaPPH23Builder:
    global _spt_pph23_builder
    if _spt_pph23_builder is None:
        _spt_pph23_builder = SPTMasaPPH23Builder(config=config)
    return _spt_pph23_builder

__all__ = [
    "PPh23_OBJECTS",
    "PPh23_RATE_WITHOUT_NPWP",
    "PPh23_RATE_WITH_NPWP",
    "PPh26_RATE_DEFAULT",
    "SPTMasaPPH23",
    "SPTMasaPPH23Builder",
    "SPTMasaPph23Builder",
    "SPTStatus",
    "SPTType",
    "get_spt_pph23_builder",
]
