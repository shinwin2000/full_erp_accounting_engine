#!/usr/bin/env python3
"""
Module: spt_tahunan_badan_builder.py
Layer: Adapters (Coretax DJP)
Responsibility: Membangun SPT Tahunan PPh Badan (Formulir 1771) berdasarkan data
               laporan keuangan yang sudah diaudit dan rekonsiliasi fiskal.
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

CORETAX_SPT_TAHUNAN_ENDPOINT = "/api/v1/spt/tahunan/badan/submit"
CORETAX_SPT_STATUS_ENDPOINT = "/api/v1/spt/status"
CORETAX_SPT_CANCEL_ENDPOINT = "/api/v1/spt/cancel"
CORETAX_SPT_DOWNLOAD_ENDPOINT = "/api/v1/spt/download"
CORETAX_SPT_VALIDATE_ENDPOINT = "/api/v1/spt/validate"
CORETAX_SPT_CALCULATE_ENDPOINT = "/api/v1/spt/calculate"

FORM_CODE = "1771"
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

CORPORATE_TAX_RATE = Decimal("0.22")
PUBLIC_COMPANY_RATE = Decimal("0.19")
SME_RATE_1 = Decimal("0.125")
SME_RATE_2 = Decimal("0.25")
SME_REVENUE_LIMIT_1 = 4800000000
SME_REVENUE_LIMIT_2 = 50000000000

JENIS_TARIF = {
    "1": "Pasal 17 ayat (1) huruf b - Tarif Umum",
    "2": "Pasal 17 ayat (2b) - Perusahaan Publik",
    "3": "Pasal 31E - Fasilitas UMKM",
}


class KoreksiFiskalType(Enum):
    POSITIF = "positif"
    NEGATIF = "negatif"


JENIS_KOREKSI = {
    "01": "Beda Tetap (Permanen)",
    "02": "Beda Waktu (Temporer)",
    "03": "Koreksi Administratif",
    "04": "Koreksi Teknis",
}

SUMBER_KOREKSI = {
    "01": "Penyusutan",
    "02": "Amortisasi",
    "03": "Biaya Bunga",
    "04": "Biaya Pajak",
    "05": "Biaya Representasi",
    "06": "Biaya Sumbangan",
    "07": "Biaya Pribadi",
    "08": "Penghasilan Belum Dikenakan Pajak",
    "09": "Kerugian Piutang",
    "10": "Penghasilan Lainnya",
}

MAX_LOSS_COMPENSATION_YEARS = 5


class SPTBadanError(Exception):
    pass


class SPTBadanNotFoundError(SPTBadanError):
    pass


class SPTBadanAlreadyExistsError(SPTBadanError):
    pass


class SPTBadanInvalidStateError(SPTBadanError):
    pass


class SPTBadanValidationError(SPTBadanError):
    pass


class SPTBadanLockedError(SPTBadanError):
    pass


class SPTBadanXMLGenerationError(SPTBadanError):
    pass


class SPTBadanCalculationError(SPTBadanError):
    pass


class KoreksiFiskal:
    """Entity untuk koreksi fiskal."""

    def __init__(
        self,
        jenis_koreksi: str,
        jenis_kode: str,
        jumlah: Decimal,
        keterangan: str = "",
        sumber: str = "",
        tahun_pajak: int | None = None,
    ):
        self.id = uuid4()
        self.jenis_koreksi = jenis_koreksi
        self.jenis_kode = jenis_kode
        self.jumlah = jumlah
        self.keterangan = keterangan
        self.sumber = sumber
        self.tahun_pajak = tahun_pajak
        self.created_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "jenis_koreksi": self.jenis_koreksi,
            "jenis_kode": self.jenis_kode,
            "jenis_desc": JENIS_KOREKSI.get(self.jenis_kode, "Lainnya"),
            "jumlah": float(self.jumlah),
            "keterangan": self.keterangan,
            "sumber": self.sumber,
            "sumber_desc": SUMBER_KOREKSI.get(self.sumber, ""),
            "tahun_pajak": self.tahun_pajak,
        }


class PemegangSaham:
    """Entity untuk pemegang saham."""

    def __init__(
        self,
        npwp: str,
        nama: str,
        persentase: Decimal,
        jumlah_modal: Decimal,
        alamat: str = "",
        kewarganegaraan: str = "WNI",
    ):
        self.id = uuid4()
        self.npwp = npwp
        self.nama = nama
        self.persentase = persentase
        self.jumlah_modal = jumlah_modal
        self.alamat = alamat
        self.kewarganegaraan = kewarganegaraan

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "npwp": self.npwp,
            "nama": self.nama,
            "persentase": float(self.persentase),
            "jumlah_modal": float(self.jumlah_modal),
            "alamat": self.alamat,
            "kewarganegaraan": self.kewarganegaraan,
        }


class SPTTahunanBadan:
    """Entity untuk SPT Tahunan PPh Badan (1771)."""

    def __init__(
        self,
        npwp_badan: str,
        tahun_pajak: int,
        spt_type: SPTType = SPTType.NORMAL,
        correction_number: int = 0,
        penghasilan_neto_komersial: Decimal = Decimal(0),
        penghasilan_neto_fiskal: Decimal = Decimal(0),
        kompensasi_kerugian: Decimal = Decimal(0),
        penghasilan_kena_pajak: Decimal = Decimal(0),
        pph_terutang: Decimal = Decimal(0),
        total_kredit_pajak: Decimal = Decimal(0),
        kurang_bayar: Decimal = Decimal(0),
        lebih_bayar: Decimal = Decimal(0),
        total_bayar: Decimal = Decimal(0),
        tarif: Decimal = CORPORATE_TAX_RATE,
        ntpn: str | None = None,
        spt_id: UUID | None = None,
        status: SPTStatus = SPTStatus.DRAFT,
        version: int = 1,
    ):
        self._spt_id = spt_id or uuid4()
        self._npwp_badan = npwp_badan
        self._tahun_pajak = tahun_pajak
        self._spt_type = spt_type
        self._correction_number = correction_number
        self._penghasilan_neto_komersial = penghasilan_neto_komersial
        self._penghasilan_neto_fiskal = penghasilan_neto_fiskal
        self._kompensasi_kerugian = kompensasi_kerugian
        self._penghasilan_kena_pajak = penghasilan_kena_pajak
        self._pph_terutang = pph_terutang
        self._total_kredit_pajak = total_kredit_pajak
        self._kurang_bayar = kurang_bayar
        self._lebih_bayar = lebih_bayar
        self._total_bayar = total_bayar
        self._tarif = tarif
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
        self._koreksi_positif: list[KoreksiFiskal] = []
        self._koreksi_negatif: list[KoreksiFiskal] = []
        self._pemegang_saham: list[PemegangSaham] = []
        self._penyusutan_fiskal: list[dict[str, Any]] = []
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
    def npwp_badan(self) -> str:
        return self._npwp_badan

    @property
    def tahun_pajak(self) -> int:
        return self._tahun_pajak

    @property
    def spt_type(self) -> SPTType:
        return self._spt_type

    @property
    def correction_number(self) -> int:
        return self._correction_number

    @property
    def penghasilan_neto_komersial(self) -> Decimal:
        return self._penghasilan_neto_komersial

    @property
    def penghasilan_neto_fiskal(self) -> Decimal:
        return self._penghasilan_neto_fiskal

    @property
    def kompensasi_kerugian(self) -> Decimal:
        return self._kompensasi_kerugian

    @property
    def penghasilan_kena_pajak(self) -> Decimal:
        return self._penghasilan_kena_pajak

    @property
    def pph_terutang(self) -> Decimal:
        return self._pph_terutang

    @property
    def total_kredit_pajak(self) -> Decimal:
        return self._total_kredit_pajak

    @property
    def kurang_bayar(self) -> Decimal:
        return self._kurang_bayar

    @property
    def lebih_bayar(self) -> Decimal:
        return self._lebih_bayar

    @property
    def total_bayar(self) -> Decimal:
        return self._total_bayar

    @property
    def tarif(self) -> Decimal:
        return self._tarif

    @property
    def tarif_percent(self) -> Decimal:
        return self._tarif * 100

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
    def koreksi_positif(self) -> list[KoreksiFiskal]:
        return self._koreksi_positif.copy()

    @property
    def koreksi_negatif(self) -> list[KoreksiFiskal]:
        return self._koreksi_negatif.copy()

    @property
    def total_koreksi_positif(self) -> Decimal:
        return sum(k.jumlah for k in self._koreksi_positif)

    @property
    def total_koreksi_negatif(self) -> Decimal:
        return sum(k.jumlah for k in self._koreksi_negatif)

    @property
    def pemegang_saham(self) -> list[PemegangSaham]:
        return self._pemegang_saham.copy()

    @property
    def penyusutan_fiskal(self) -> list[dict[str, Any]]:
        return self._penyusutan_fiskal.copy()

    @property
    def hash(self) -> str:
        return self._hash

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    def create(self, created_by: UUID) -> SPTTahunanBadan:
        self._status = SPTStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "spt_tahunan_badan_created",
            {
                "spt_id": str(self._spt_id),
                "npwp": self._npwp_badan,
                "tahun_pajak": self._tahun_pajak,
                "created_by": str(created_by),
            },
        )
        return self

    def update(self, data: dict[str, Any], updated_by: UUID) -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        if self._status not in [SPTStatus.DRAFT, SPTStatus.PENDING, SPTStatus.REJECTED]:
            raise SPTBadanInvalidStateError(f"Cannot update SPT in status {self._status.value}")
        old_data = self.to_dict()
        if "penghasilan_neto_komersial" in data:
            self._penghasilan_neto_komersial = Decimal(str(data["penghasilan_neto_komersial"]))
        if "penghasilan_neto_fiskal" in data:
            self._penghasilan_neto_fiskal = Decimal(str(data["penghasilan_neto_fiskal"]))
        if "kompensasi_kerugian" in data:
            self._kompensasi_kerugian = Decimal(str(data["kompensasi_kerugian"]))
        if "total_kredit_pajak" in data:
            self._total_kredit_pajak = Decimal(str(data["total_kredit_pajak"]))
        if "ntpn" in data:
            self._ntpn = data["ntpn"]
        self._version += 1
        self._updated_at = datetime.now()
        self._calculate_hash()
        self._register_event(
            "spt_tahunan_badan_updated",
            {
                "spt_id": str(self._spt_id),
                "old_data": old_data,
                "new_data": self.to_dict(),
                "updated_by": str(updated_by),
            },
        )
        return self

    def delete(self, deleted_by: UUID, permanent: bool = False) -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        if permanent:
            self._status = SPTStatus.VOID
            self._cancelled_at = datetime.now()
        else:
            self._status = SPTStatus.ARCHIVED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_tahunan_badan_deleted",
            {
                "spt_id": str(self._spt_id),
                "permanent": permanent,
                "deleted_by": str(deleted_by),
            },
        )
        return self

    def restore(self, restored_by: UUID) -> SPTTahunanBadan:
        if self._status not in [SPTStatus.ARCHIVED, SPTStatus.VOID]:
            raise SPTBadanInvalidStateError(f"Cannot restore SPT in status {self._status.value}")
        self._status = SPTStatus.DRAFT
        self._cancelled_at = None
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_tahunan_badan_restored",
            {
                "spt_id": str(self._spt_id),
                "restored_by": str(restored_by),
            },
        )
        return self

    def activate(self, activated_by: UUID) -> SPTTahunanBadan:
        if self._status != SPTStatus.DRAFT:
            raise SPTBadanInvalidStateError(f"Cannot activate SPT in status {self._status.value}")
        self._status = SPTStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_tahunan_badan_activated",
            {
                "spt_id": str(self._spt_id),
                "activated_by": str(activated_by),
            },
        )
        return self

    def deactivate(self, deactivated_by: UUID) -> SPTTahunanBadan:
        if self._status != SPTStatus.PENDING:
            raise SPTBadanInvalidStateError(f"Cannot deactivate SPT in status {self._status.value}")
        self._status = SPTStatus.DRAFT
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_tahunan_badan_deactivated",
            {
                "spt_id": str(self._spt_id),
                "deactivated_by": str(deactivated_by),
            },
        )
        return self

    def lock(self, locked_by: UUID, reason: str = "") -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} already locked")
        self._locked_at = datetime.now()
        self._locked_by = locked_by
        self._status = SPTStatus.LOCKED
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_tahunan_badan_locked",
            {
                "spt_id": str(self._spt_id),
                "locked_by": str(locked_by),
                "reason": reason,
            },
        )
        return self

    def unlock(self, unlocked_by: UUID) -> SPTTahunanBadan:
        if not self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is not locked")
        self._locked_at = None
        self._locked_by = None
        self._status = SPTStatus.PENDING
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_tahunan_badan_unlocked",
            {
                "spt_id": str(self._spt_id),
                "unlocked_by": str(unlocked_by),
            },
        )
        return self

    def validate(self, validator_id: UUID) -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        if self._status not in [SPTStatus.DRAFT, SPTStatus.PENDING, SPTStatus.CALCULATED]:
            raise SPTBadanInvalidStateError(f"Cannot validate SPT in status {self._status.value}")
        errors = []
        if self._penghasilan_kena_pajak < 0:
            errors.append("Penghasilan Kena Pajak tidak boleh negatif")
        if self._pph_terutang < 0:
            errors.append("PPh terutang tidak boleh negatif")
        if self._kurang_bayar > 0 and not self._ntpn:
            errors.append("Ada kurang bayar tetapi tidak ada NTPN")
        if not self._pemegang_saham:
            errors.append("Daftar pemegang saham tidak boleh kosong")
        if self._tahun_pajak < 2000 or self._tahun_pajak > 2100:
            errors.append("Tahun pajak tidak valid")
        expected_penghasilan_kena_pajak = max(self._penghasilan_neto_fiskal - self._kompensasi_kerugian, Decimal(0))
        if abs(self._penghasilan_kena_pajak - expected_penghasilan_kena_pajak) > Decimal("0.01"):
            errors.append(
                f"PKP tidak konsisten: expected {expected_penghasilan_kena_pajak}, got {self._penghasilan_kena_pajak}"
            )
        expected_pph = (self._penghasilan_kena_pajak * self._tarif).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if abs(self._pph_terutang - expected_pph) > Decimal("0.01"):
            errors.append(
                f"PPh terutang tidak sesuai: expected {expected_pph}, got {self._pph_terutang}"
            )
        expected_kurang_bayar = max(self._pph_terutang - self._total_kredit_pajak, Decimal(0))
        if abs(self._kurang_bayar - expected_kurang_bayar) > Decimal("0.01"):
            errors.append(
                f"Kurang bayar tidak konsisten: expected {expected_kurang_bayar}, got {self._kurang_bayar}"
            )
        if self._kurang_bayar > 0 and self._ntpn:
            if not self._validate_ntpn_format(self._ntpn):
                errors.append("Format NTPN tidak valid (harus 16 digit)")
        if errors:
            raise SPTBadanValidationError("Validasi gagal: {}".format("; ".join(errors)))
        self._status = SPTStatus.VALIDATED
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "spt_tahunan_badan_validated",
            {
                "spt_id": str(self._spt_id),
                "validator_id": str(validator_id),
            },
        )
        return self

    def approve(self, approver_id: UUID, notes: str = "") -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        if self._status != SPTStatus.SUBMITTED:
            raise SPTBadanInvalidStateError(f"Cannot approve SPT in status {self._status.value}")
        self._status = SPTStatus.APPROVED
        self._approved_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_tahunan_badan_approved",
            {
                "spt_id": str(self._spt_id),
                "approver_id": str(approver_id),
                "notes": notes,
            },
        )
        return self

    def reject(self, rejector_id: UUID, reason: str) -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        if self._status not in [SPTStatus.PENDING, SPTStatus.SUBMITTED, SPTStatus.VALIDATED]:
            raise SPTBadanInvalidStateError(f"Cannot reject SPT in status {self._status.value}")
        self._status = SPTStatus.REJECTED
        self._rejected_at = datetime.now()
        self._rejection_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_tahunan_badan_rejected",
            {
                "spt_id": str(self._spt_id),
                "rejector_id": str(rejector_id),
                "reason": reason,
            },
        )
        return self

    def calculate(self, calculator_id: UUID) -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        self._penghasilan_kena_pajak = max(self._penghasilan_neto_fiskal - self._kompensasi_kerugian, Decimal(0))
        self._pph_terutang = (self._penghasilan_kena_pajak * self._tarif).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self._kurang_bayar = max(self._pph_terutang - self._total_kredit_pajak, Decimal(0))
        self._lebih_bayar = max(self._total_kredit_pajak - self._pph_terutang, Decimal(0))
        self._total_bayar = self._kurang_bayar
        self._status = SPTStatus.CALCULATED
        self._updated_at = datetime.now()
        self._version += 1
        self._calculate_hash()
        self._register_event(
            "spt_tahunan_badan_calculated",
            {
                "spt_id": str(self._spt_id),
                "penghasilan_kena_pajak": float(self._penghasilan_kena_pajak),
                "pph_terutang": float(self._pph_terutang),
                "kurang_bayar": float(self._kurang_bayar),
                "lebih_bayar": float(self._lebih_bayar),
                "calculator_id": str(calculator_id),
            },
        )
        return self

    def submit(self, submitted_by: UUID) -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        if self._status not in [SPTStatus.PENDING, SPTStatus.VALIDATED, SPTStatus.CALCULATED]:
            raise SPTBadanInvalidStateError(f"Cannot submit SPT in status {self._status.value}")
        self.validate(submitted_by)
        self._generate_xml()
        self._status = SPTStatus.SUBMITTED
        self._submitted_at = datetime.now()
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_tahunan_badan_submitted",
            {
                "spt_id": str(self._spt_id),
                "submitted_by": str(submitted_by),
            },
        )
        return self

    def cancel(self, cancelled_by: UUID, reason: str) -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        if self._status in [SPTStatus.CANCELLED, SPTStatus.VOID, SPTStatus.CLOSED]:
            raise SPTBadanInvalidStateError(f"Cannot cancel SPT in status {self._status.value}")
        self._status = SPTStatus.CANCELLED
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_tahunan_badan_cancelled",
            {
                "spt_id": str(self._spt_id),
                "cancelled_by": str(cancelled_by),
                "reason": reason,
            },
        )
        return self

    def void(self, voided_by: UUID, reason: str) -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        self._status = SPTStatus.VOID
        self._cancelled_at = datetime.now()
        self._cancellation_reason = reason
        self._updated_at = datetime.now()
        self._version += 1
        self._register_event(
            "spt_tahunan_badan_voided",
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
            "tahun_pajak": self._tahun_pajak,
            "penghasilan_kena_pajak": float(self._penghasilan_kena_pajak),
            "pph_terutang": float(self._pph_terutang),
            "kurang_bayar": float(self._kurang_bayar),
            "lebih_bayar": float(self._lebih_bayar),
            "pemegang_saham_count": len(self._pemegang_saham),
        }

    def get_history(self) -> list[dict[str, Any]]:
        return self._history.copy()

    def snapshot(self) -> dict[str, Any]:
        return {
            "spt_id": str(self._spt_id),
            "npwp_badan": self._npwp_badan,
            "tahun_pajak": self._tahun_pajak,
            "spt_type": self._spt_type.value,
            "correction_number": self._correction_number,
            "status": self._status.value,
            "version": self._version,
            "penghasilan_neto_komersial": float(self._penghasilan_neto_komersial),
            "penghasilan_neto_fiskal": float(self._penghasilan_neto_fiskal),
            "kompensasi_kerugian": float(self._kompensasi_kerugian),
            "penghasilan_kena_pajak": float(self._penghasilan_kena_pajak),
            "pph_terutang": float(self._pph_terutang),
            "total_kredit_pajak": float(self._total_kredit_pajak),
            "kurang_bayar": float(self._kurang_bayar),
            "lebih_bayar": float(self._lebih_bayar),
            "tarif": float(self._tarif),
            "tarif_percent": float(self.tarif_percent),
            "ntpn": self.ntpn_masked,
            "spt_number": self._spt_number,
            "tracking_id": self._tracking_id,
            "coretax_id": self._coretax_id,
            "total_koreksi_positif": float(self.total_koreksi_positif),
            "total_koreksi_negatif": float(self.total_koreksi_negatif),
            "koreksi_positif": [k.to_dict() for k in self._koreksi_positif],
            "koreksi_negatif": [k.to_dict() for k in self._koreksi_negatif],
            "pemegang_saham": [s.to_dict() for s in self._pemegang_saham],
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
            "npwp_badan": self._npwp_badan,
            "tahun_pajak": self._tahun_pajak,
            "spt_type": self._spt_type.value,
            "correction_number": self._correction_number,
            "penghasilan_neto_komersial": float(self._penghasilan_neto_komersial),
            "penghasilan_neto_fiskal": float(self._penghasilan_neto_fiskal),
            "kompensasi_kerugian": float(self._kompensasi_kerugian),
            "penghasilan_kena_pajak": float(self._penghasilan_kena_pajak),
            "pph_terutang": float(self._pph_terutang),
            "total_kredit_pajak": float(self._total_kredit_pajak),
            "kurang_bayar": float(self._kurang_bayar),
            "lebih_bayar": float(self._lebih_bayar),
            "total_bayar": float(self._total_bayar),
            "tarif": float(self._tarif),
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
            "koreksi_positif": [k.to_dict() for k in self._koreksi_positif],
            "koreksi_negatif": [k.to_dict() for k in self._koreksi_negatif],
            "pemegang_saham": [s.to_dict() for s in self._pemegang_saham],
            "penyusutan_fiskal": self._penyusutan_fiskal,
            "hash": self._hash,
            "is_locked": self.is_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SPTTahunanBadan:
        spt = cls(
            spt_id=UUID(data["spt_id"]) if data.get("spt_id") else None,
            npwp_badan=data["npwp_badan"],
            tahun_pajak=data["tahun_pajak"],
            spt_type=SPTType(data.get("spt_type", "normal")),
            correction_number=data.get("correction_number", 0),
            penghasilan_neto_komersial=Decimal(str(data.get("penghasilan_neto_komersial", 0))),
            penghasilan_neto_fiskal=Decimal(str(data.get("penghasilan_neto_fiskal", 0))),
            kompensasi_kerugian=Decimal(str(data.get("kompensasi_kerugian", 0))),
            penghasilan_kena_pajak=Decimal(str(data.get("penghasilan_kena_pajak", 0))),
            pph_terutang=Decimal(str(data.get("pph_terutang", 0))),
            total_kredit_pajak=Decimal(str(data.get("total_kredit_pajak", 0))),
            kurang_bayar=Decimal(str(data.get("kurang_bayar", 0))),
            lebih_bayar=Decimal(str(data.get("lebih_bayar", 0))),
            tarif=Decimal(str(data.get("tarif", CORPORATE_TAX_RATE))),
            ntpn=data.get("ntpn"),
            status=SPTStatus(data.get("status", "draft")),
            version=data.get("version", 1),
        )
        for k in data.get("koreksi_positif", []):
            spt._koreksi_positif.append(
                KoreksiFiskal(
                    jenis_koreksi="positif",
                    jenis_kode=k.get("jenis_kode", "01"),
                    jumlah=Decimal(str(k.get("jumlah", 0))),
                    keterangan=k.get("keterangan", ""),
                    sumber=k.get("sumber", ""),
                    tahun_pajak=k.get("tahun_pajak"),
                )
            )
        for k in data.get("koreksi_negatif", []):
            spt._koreksi_negatif.append(
                KoreksiFiskal(
                    jenis_koreksi="negatif",
                    jenis_kode=k.get("jenis_kode", "01"),
                    jumlah=Decimal(str(k.get("jumlah", 0))),
                    keterangan=k.get("keterangan", ""),
                    sumber=k.get("sumber", ""),
                    tahun_pajak=k.get("tahun_pajak"),
                )
            )
        for s in data.get("pemegang_saham", []):
            spt._pemegang_saham.append(
                PemegangSaham(
                    npwp=s.get("npwp", ""),
                    nama=s.get("nama", ""),
                    persentase=Decimal(str(s.get("persentase", 0))),
                    jumlah_modal=Decimal(str(s.get("jumlah_modal", 0))),
                    alamat=s.get("alamat", ""),
                    kewarganegaraan=s.get("kewarganegaraan", "WNI"),
                )
            )
        if data.get("penyusutan_fiskal"):
            spt._penyusutan_fiskal = data["penyusutan_fiskal"]
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

    def transition(self, new_status: SPTStatus, actor_id: UUID, reason: str = "") -> SPTTahunanBadan:
        if not self.can_transition(new_status):
            raise SPTBadanInvalidStateError(
                f"Status transition invalid: {self._status.value} -> {new_status.value}"
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
            "spt_tahunan_badan_status_changed",
            {
                "spt_id": str(self._spt_id),
                "from_status": old_status.value,
                "to_status": new_status.value,
                "actor_id": str(actor_id),
                "reason": reason,
            },
        )
        return self

    def register_event(self, event_type: str, event_data: dict[str, Any]) -> SPTTahunanBadan:
        return self._register_event(event_type, event_data)

    def _register_event(self, event_type: str, event_data: dict[str, Any]) -> SPTTahunanBadan:
        self._events.append(
            {
                "event_id": str(uuid4()),
                "event_type": event_type,
                "aggregate_id": str(self._spt_id),
                "aggregate_type": "SPTTahunanBadan",
                "occurred_at": datetime.now().isoformat(),
                "data": event_data,
            }
        )
        return self

    def get_events(self) -> list[dict[str, Any]]:
        return self._events.copy()

    def clear_events(self) -> SPTTahunanBadan:
        self._events.clear()
        return self

    def add_koreksi_positif(self, jenis_kode: str, jumlah: Decimal, keterangan: str = "", sumber: str = "") -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        koreksi = KoreksiFiskal(
            jenis_koreksi="positif",
            jenis_kode=jenis_kode,
            jumlah=jumlah,
            keterangan=keterangan,
            sumber=sumber,
            tahun_pajak=self._tahun_pajak,
        )
        self._koreksi_positif.append(koreksi)
        self._penghasilan_neto_fiskal = self._penghasilan_neto_komersial + self.total_koreksi_positif - self.total_koreksi_negatif
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def add_koreksi_negatif(self, jenis_kode: str, jumlah: Decimal, keterangan: str = "", sumber: str = "") -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        koreksi = KoreksiFiskal(
            jenis_koreksi="negatif",
            jenis_kode=jenis_kode,
            jumlah=jumlah,
            keterangan=keterangan,
            sumber=sumber,
            tahun_pajak=self._tahun_pajak,
        )
        self._koreksi_negatif.append(koreksi)
        self._penghasilan_neto_fiskal = self._penghasilan_neto_komersial + self.total_koreksi_positif - self.total_koreksi_negatif
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def add_pemegang_saham(self, npwp: str, nama: str, persentase: Decimal, jumlah_modal: Decimal, alamat: str = "", kewarganegaraan: str = "WNI") -> SPTTahunanBadan:
        if self.is_locked:
            raise SPTBadanLockedError(f"SPT {self._tahun_pajak} is locked")
        pemegang = PemegangSaham(
            npwp=npwp,
            nama=nama,
            persentase=persentase,
            jumlah_modal=jumlah_modal,
            alamat=alamat,
            kewarganegaraan=kewarganegaraan,
        )
        self._pemegang_saham.append(pemegang)
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def set_tarif(self, tarif: Decimal, jenis_tarif: str = "1") -> SPTTahunanBadan:
        self._tarif = tarif
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def set_kompensasi_kerugian(self, kompensasi: Decimal) -> SPTTahunanBadan:
        self._kompensasi_kerugian = kompensasi
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def set_ntpn(self, ntpn: str) -> SPTTahunanBadan:
        if not self._validate_ntpn_format(ntpn):
            raise SPTBadanValidationError(f"Invalid NTPN format: {ntpn}")
        self._ntpn = ntpn
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def set_coretax_response(self, response: dict[str, Any]) -> SPTTahunanBadan:
        self._spt_number = response.get("spt_number")
        self._tracking_id = response.get("tracking_id")
        self._coretax_id = response.get("coretax_id")
        if response.get("status") == "success":
            self._status = SPTStatus.SUBMITTED
        self._updated_at = datetime.now()
        self._version += 1
        return self

    def create_correction(self, correction_number: int, created_by: UUID) -> SPTTahunanBadan:
        correction_spt = SPTTahunanBadan(
            npwp_badan=self._npwp_badan,
            tahun_pajak=self._tahun_pajak,
            spt_type=SPTType.CORRECTION,
            correction_number=correction_number,
            status=SPTStatus.DRAFT,
        )
        correction_spt.create(created_by)
        return correction_spt

    def _calculate_hash(self) -> None:
        data = f"{self._spt_id}{self._npwp_badan}{self._tahun_pajak}{self._pph_terutang}{self._status.value}{self._version}"
        self._hash = hashlib.sha256(data.encode()).hexdigest()

    def _generate_xml(self) -> str:
        try:
            root = ET.Element("SPT", {"xmlns": "http://www.djp.go.id/spt/pph_badan", "versi": FORM_VERSION})
            kepala = ET.SubElement(root, "Kepala")
            ET.SubElement(kepala, "KodeFormulir").text = FORM_CODE
            ET.SubElement(kepala, "JenisSPT").text = self._spt_type.value
            if self._spt_type == SPTType.CORRECTION:
                ET.SubElement(kepala, "NomorPembetulan").text = str(self._correction_number)
            ET.SubElement(kepala, "TahunPajak").text = str(self._tahun_pajak)
            ET.SubElement(kepala, "NPWP").text = self._npwp_badan
            ET.SubElement(kepala, "Tanggal").text = date.today().isoformat()
            bagian_a = ET.SubElement(root, "PenghasilanNeto")
            ET.SubElement(bagian_a, "Komersial").text = f"{self._penghasilan_neto_komersial:.2f}"
            ET.SubElement(bagian_a, "Fiskal").text = f"{self._penghasilan_neto_fiskal:.2f}"
            ET.SubElement(bagian_a, "KompensasiKerugian").text = f"{self._kompensasi_kerugian:.2f}"
            ET.SubElement(bagian_a, "PenghasilanKenaPajak").text = f"{self._penghasilan_kena_pajak:.2f}"
            if self._koreksi_positif or self._koreksi_negatif:
                koreksi_elem = ET.SubElement(root, "KoreksiFiskal")
                for k in self._koreksi_positif:
                    item = ET.SubElement(koreksi_elem, "KoreksiPositif")
                    ET.SubElement(item, "Uraian").text = k.keterangan or JENIS_KOREKSI.get(k.jenis_kode, "Lainnya")
                    ET.SubElement(item, "Jumlah").text = f"{k.jumlah:.2f}"
                for k in self._koreksi_negatif:
                    item = ET.SubElement(koreksi_elem, "KoreksiNegatif")
                    ET.SubElement(item, "Uraian").text = k.keterangan or JENIS_KOREKSI.get(k.jenis_kode, "Lainnya")
                    ET.SubElement(item, "Jumlah").text = f"{k.jumlah:.2f}"
            bagian_b = ET.SubElement(root, "PPhTerutang")
            ET.SubElement(bagian_b, "Tarif").text = f"{float(self._tarif) * 100:.2f}"
            ET.SubElement(bagian_b, "Jumlah").text = f"{self._pph_terutang:.2f}"
            kredit_elem = ET.SubElement(root, "KreditPajak")
            ET.SubElement(kredit_elem, "Total").text = f"{self._total_kredit_pajak:.2f}"
            bayar_elem = ET.SubElement(root, "Pembayaran")
            if self._kurang_bayar > 0:
                ET.SubElement(bayar_elem, "KurangBayar").text = f"{self._kurang_bayar:.2f}"
                if self._ntpn:
                    ET.SubElement(bayar_elem, "NTPN").text = self._ntpn
            else:
                ET.SubElement(bayar_elem, "LebihBayar").text = f"{self._lebih_bayar:.2f}"
            if self._pemegang_saham:
                saham_elem = ET.SubElement(root, "DaftarPemegangSaham")
                for sh in self._pemegang_saham:
                    sh_elem = ET.SubElement(saham_elem, "PemegangSaham")
                    ET.SubElement(sh_elem, "NPWP").text = sh.npwp
                    ET.SubElement(sh_elem, "Nama").text = sh.nama
                    ET.SubElement(sh_elem, "Persentase").text = f"{sh.persentase:.2f}"
                    ET.SubElement(sh_elem, "JumlahModal").text = f"{sh.jumlah_modal:.2f}"
                    if sh.alamat:
                        ET.SubElement(sh_elem, "Alamat").text = sh.alamat
                    ET.SubElement(sh_elem, "Kewarganegaraan").text = sh.kewarganegaraan
            xml_str = ET.tostring(root, encoding="utf-8")
            dom = minidom.parseString(xml_str)
            self._xml_content = dom.toprettyxml(indent="  ")
            return self._xml_content
        except Exception as e:
            raise SPTBadanXMLGenerationError(f"Failed to create XML SPT: {e}")

    def _validate_ntpn_format(self, ntpn: str) -> bool:
        import re
        return bool(re.match(r"^\d{16}$", ntpn))


# ============================================================================
# REPOSITORY INTERFACE
# ============================================================================
class SPTBadanRepositoryPort:
    async def add(self, spt: SPTTahunanBadan) -> None:
        raise NotImplementedError
    async def save(self, spt: SPTTahunanBadan) -> None:
        raise NotImplementedError
    async def update(self, spt: SPTTahunanBadan) -> None:
        raise NotImplementedError
    async def delete(self, spt_id: UUID) -> None:
        raise NotImplementedError
    async def get_by_id(self, spt_id: UUID) -> SPTTahunanBadan | None:
        raise NotImplementedError
    async def get_by_npwp_tahun(self, npwp: str, tahun: int) -> SPTTahunanBadan | None:
        raise NotImplementedError
    async def get_by_tracking_id(self, tracking_id: str) -> SPTTahunanBadan | None:
        raise NotImplementedError
    async def get_by_status(self, status: SPTStatus) -> list[SPTTahunanBadan]:
        raise NotImplementedError
    async def get_pending_submissions(self) -> list[SPTTahunanBadan]:
        raise NotImplementedError
    async def exists(self, npwp: str, tahun: int, correction_number: int = 0) -> bool:
        raise NotImplementedError


class _FallbackSPTBadanRepository(SPTBadanRepositoryPort):
    def __init__(self):
        self._store: dict[UUID, SPTTahunanBadan] = {}
        self._by_npwp_tahun: dict[str, UUID] = {}
        self._by_tracking_id: dict[str, UUID] = {}

    async def add(self, spt: SPTTahunanBadan) -> None:
        self._store[spt.spt_id] = spt
        key = f"{spt.npwp_badan}:{spt.tahun_pajak}:{spt.correction_number}"
        self._by_npwp_tahun[key] = spt.spt_id
        if spt.tracking_id:
            self._by_tracking_id[spt.tracking_id] = spt.spt_id

    async def save(self, spt: SPTTahunanBadan) -> None:
        self._store[spt.spt_id] = spt

    async def update(self, spt: SPTTahunanBadan) -> None:
        self._store[spt.spt_id] = spt

    async def delete(self, spt_id: UUID) -> None:
        if spt_id in self._store:
            del self._store[spt_id]

    async def get_by_id(self, spt_id: UUID) -> SPTTahunanBadan | None:
        return self._store.get(spt_id)

    async def get_by_npwp_tahun(self, npwp: str, tahun: int) -> SPTTahunanBadan | None:
        for spt in self._store.values():
            if spt.npwp_badan == npwp and spt.tahun_pajak == tahun:
                return spt
        return None

    async def get_by_tracking_id(self, tracking_id: str) -> SPTTahunanBadan | None:
        spt_id = self._by_tracking_id.get(tracking_id)
        if spt_id:
            return self._store.get(spt_id)
        return None

    async def get_by_status(self, status: SPTStatus) -> list[SPTTahunanBadan]:
        return [s for s in self._store.values() if s.status == status]

    async def get_pending_submissions(self) -> list[SPTTahunanBadan]:
        return [
            s
            for s in self._store.values()
            if s.status
            in [SPTStatus.PENDING, SPTStatus.VALIDATED, SPTStatus.CALCULATED, SPTStatus.SUBMITTED]
        ]

    async def exists(self, npwp: str, tahun: int, correction_number: int = 0) -> bool:
        return await self.get_by_npwp_tahun(npwp, tahun) is not None


# ============================================================================
# SPT BUILDER
# ============================================================================
class SPTTahunanBadanBuilder:
    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._coretax_client = None
        self._repository = _FallbackSPTBadanRepository()
        self._ledger_service = None
        self._tax_service = None
        self._file_storage = None
        self._cache: dict[str, Any] = {}
        self._init_file_storage()

    def _load_config(self) -> dict[str, Any]:
        if self._config:
            return self._config
        return {
            "coretax_djp": {
                "spt_tahunan": {
                    "file_storage_bucket": "coretax-spt-tahunan",
                    "auto_submit": False,
                    "validation_strict": True,
                    "default_tax_rate": float(CORPORATE_TAX_RATE),
                    "cache_ttl_seconds": CACHE_TTL_SECONDS,
                    "max_retry_attempts": MAX_RETRY_ATTEMPTS,
                }
            }
        }

    def _init_file_storage(self):
        try:
            from infrastructure.file_storage.s3_adapter import S3FileStorageAdapter
            bucket = self._load_config().get("coretax_djp", {}).get("spt_tahunan", {}).get("file_storage_bucket", "coretax-spt-tahunan")
            self._file_storage = S3FileStorageAdapter(bucket_name=bucket)
        except Exception as e:
            logger.warning(f"File storage not available for SPT Tahunan: {e}")

    async def _get_coretax_client(self):
        if self._coretax_client is None:
            self._coretax_client = await get_coretax_client()
        return self._coretax_client

    async def _get_ledger_service(self):
        if self._ledger_service is None:
            from application.service_layer.service_ledger import LedgerService
            self._ledger_service = LedgerService()
        return self._ledger_service

    async def _get_tax_service(self):
        if self._tax_service is None:
            from application.service_layer.service_tax import TaxService
            self._tax_service = TaxService()
        return self._tax_service

    def _get_cache_key(self, npwp: str, tahun: int) -> str:
        return f"spt_tahunan_badan:{npwp}:{tahun}"

    async def _get_cached(self, cache_key: str) -> dict[str, Any] | None:
        ttl = self._load_config().get("coretax_djp", {}).get("spt_tahunan", {}).get("cache_ttl_seconds", CACHE_TTL_SECONDS)
        return self._cache.get(cache_key)

    async def _set_cached(self, cache_key: str, data: dict[str, Any]) -> None:
        ttl = self._load_config().get("coretax_djp", {}).get("spt_tahunan", {}).get("cache_ttl_seconds", CACHE_TTL_SECONDS)
        self._cache[cache_key] = data

    # ========================================================================
    # Core Business Methods
    # ========================================================================
    async def create(self, npwp_badan: str, tahun_pajak: int, created_by: UUID) -> dict[str, Any]:
        existing = await self._repository.get_by_npwp_tahun(npwp_badan, tahun_pajak)
        if existing:
            return {"success": False, "error": "SPT already exists for this tax year"}
        spt = SPTTahunanBadan(
            npwp_badan=npwp_badan,
            tahun_pajak=tahun_pajak,
            spt_type=SPTType.NORMAL,
        )
        spt.create(created_by)
        await self._repository.add(spt)
        cache_key = self._get_cache_key(npwp_badan, tahun_pajak)
        await self._set_cached(cache_key, spt.to_dict())
        return {
            "success": True,
            "spt_id": str(spt.spt_id),
            "tahun_pajak": spt.tahun_pajak,
            "status": spt.status.value,
        }

    async def collect_data(self, npwp_badan: str, tahun_pajak: int) -> dict[str, Any]:
        ledger_service = await self._get_ledger_service()
        tax_service = await self._get_tax_service()
        try:
            commercial_financials = await ledger_service.get_commercial_financials(npwp_badan, tahun_pajak)
            penghasilan_neto_komersial = commercial_financials.get("net_income_before_tax", Decimal(0))
            fiscal_reconciliation = await tax_service.get_fiscal_reconciliation(npwp_badan, tahun_pajak)
            total_koreksi_positif = fiscal_reconciliation.get("total_positive_correction", Decimal(0))
            total_koreksi_negatif = fiscal_reconciliation.get("total_negative_correction", Decimal(0))
            detail_koreksi_positif = fiscal_reconciliation.get("details", [])
            detail_koreksi_negatif = fiscal_reconciliation.get("details_negative", [])
            penghasilan_neto_fiskal = penghasilan_neto_komersial + total_koreksi_positif - total_koreksi_negatif
            kompensasi_kerugian = await tax_service.get_loss_compensation(npwp_badan, tahun_pajak)
            penghasilan_kena_pajak = max(penghasilan_neto_fiskal - kompensasi_kerugian, Decimal(0))
            is_public = await tax_service.check_public_company(npwp_badan)
            revenue = commercial_financials.get("total_revenue", Decimal(0))
            if is_public:
                tarif = PUBLIC_COMPANY_RATE
            elif revenue <= SME_REVENUE_LIMIT_1:
                tarif = SME_RATE_1
            elif revenue <= SME_REVENUE_LIMIT_2:
                tarif = CORPORATE_TAX_RATE
            else:
                tarif = CORPORATE_TAX_RATE
            tax_credits = await tax_service.get_tax_credits(npwp_badan, tahun_pajak)
            total_kredit_pajak = sum(credit.get("amount", Decimal(0)) for credit in tax_credits)
            pph_terutang = (penghasilan_kena_pajak * tarif).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            kurang_bayar = max(pph_terutang - total_kredit_pajak, Decimal(0))
            lebih_bayar = max(total_kredit_pajak - pph_terutang, Decimal(0))
            ntpn_data = await tax_service.get_ntpn_for_period(npwp_badan, tahun_pajak, None, tax_type="badan")
            shareholders = await tax_service.get_shareholders(npwp_badan, tahun_pajak)
            depreciation_schedule = await tax_service.get_fiscal_depreciation(npwp_badan, tahun_pajak)
            return {
                "npwp_badan": npwp_badan,
                "tahun_pajak": tahun_pajak,
                "penghasilan_neto_komersial": penghasilan_neto_komersial,
                "penghasilan_neto_fiskal": penghasilan_neto_fiskal,
                "koreksi_positif": detail_koreksi_positif,
                "koreksi_negatif": detail_koreksi_negatif,
                "total_koreksi_positif": total_koreksi_positif,
                "total_koreksi_negatif": total_koreksi_negatif,
                "kompensasi_kerugian": kompensasi_kerugian,
                "penghasilan_kena_pajak": penghasilan_kena_pajak,
                "tarif": tarif,
                "pph_terutang": pph_terutang,
                "kredit_pajak": tax_credits,
                "total_kredit_pajak": total_kredit_pajak,
                "kurang_bayar": kurang_bayar,
                "lebih_bayar": lebih_bayar,
                "ntpn": ntpn_data.get("ntpn") if ntpn_data else None,
                "shareholders": shareholders,
                "depreciation_schedule": depreciation_schedule,
                "commercial_financials": commercial_financials,
            }
        except Exception as e:
            logger.error(f"Failed to collect data for SPT Tahunan Badan: {e}")
            return {
                "npwp_badan": npwp_badan,
                "tahun_pajak": tahun_pajak,
                "penghasilan_neto_komersial": Decimal(0),
                "penghasilan_neto_fiskal": Decimal(0),
                "koreksi_positif": [],
                "koreksi_negatif": [],
                "total_koreksi_positif": Decimal(0),
                "total_koreksi_negatif": Decimal(0),
                "kompensasi_kerugian": Decimal(0),
                "penghasilan_kena_pajak": Decimal(0),
                "tarif": CORPORATE_TAX_RATE,
                "pph_terutang": Decimal(0),
                "kredit_pajak": [],
                "total_kredit_pajak": Decimal(0),
                "kurang_bayar": Decimal(0),
                "lebih_bayar": Decimal(0),
                "ntpn": None,
                "shareholders": [],
                "depreciation_schedule": [],
                "commercial_financials": {},
                "error": str(e),
            }

    async def build(self, npwp_badan: str, tahun_pajak: int, built_by: UUID) -> dict[str, Any]:
        spt = await self._repository.get_by_npwp_tahun(npwp_badan, tahun_pajak)
        if not spt:
            result = await self.create(npwp_badan, tahun_pajak, built_by)
            if not result.get("success"):
                return result
            spt = await self._repository.get_by_npwp_tahun(npwp_badan, tahun_pajak)
        if not spt:
            return {"success": False, "error": "Failed to create or retrieve SPT"}
        data = await self.collect_data(npwp_badan, tahun_pajak)
        if "error" in data:
            return {"success": False, "error": data["error"]}
        spt._penghasilan_neto_komersial = data["penghasilan_neto_komersial"]
        spt._penghasilan_neto_fiskal = data["penghasilan_neto_fiskal"]
        spt._kompensasi_kerugian = data["kompensasi_kerugian"]
        spt._penghasilan_kena_pajak = data["penghasilan_kena_pajak"]
        spt._pph_terutang = data["pph_terutang"]
        spt._total_kredit_pajak = data["total_kredit_pajak"]
        spt._kurang_bayar = data["kurang_bayar"]
        spt._lebih_bayar = data["lebih_bayar"]
        spt._tarif = data["tarif"]
        if data["ntpn"]:
            spt.set_ntpn(data["ntpn"])
        for k in data.get("koreksi_positif", []):
            spt.add_koreksi_positif(
                jenis_kode=k.get("jenis_kode", "01"),
                jumlah=Decimal(str(k.get("amount", 0))),
                keterangan=k.get("description", ""),
                sumber=k.get("source", ""),
            )
        for k in data.get("koreksi_negatif", []):
            spt.add_koreksi_negatif(
                jenis_kode=k.get("jenis_kode", "01"),
                jumlah=Decimal(str(k.get("amount", 0))),
                keterangan=k.get("description", ""),
                sumber=k.get("source", ""),
            )
        for sh in data.get("shareholders", []):
            spt.add_pemegang_saham(
                npwp=sh.get("npwp", ""),
                nama=sh.get("name", ""),
                persentase=Decimal(str(sh.get("percentage", 0))),
                jumlah_modal=Decimal(str(sh.get("capital_contribution", 0))),
                alamat=sh.get("address", ""),
                kewarganegaraan=sh.get("citizenship", "WNI"),
            )
        spt.calculate(built_by)
        await self._repository.update(spt)
        cache_key = self._get_cache_key(npwp_badan, tahun_pajak)
        await self._set_cached(cache_key, spt.to_dict())
        return {
            "success": True,
            "spt_id": str(spt.spt_id),
            "tahun_pajak": spt.tahun_pajak,
            "penghasilan_kena_pajak": float(spt.penghasilan_kena_pajak),
            "pph_terutang": float(spt.pph_terutang),
            "kurang_bayar": float(spt.kurang_bayar),
            "lebih_bayar": float(spt.lebih_bayar),
            "status": spt.status.value,
        }

    async def validate_spt(self, spt_id: UUID, validator_id: UUID) -> dict[str, Any]:
        spt = await self._repository.get_by_id(spt_id)
        if not spt:
            return {"success": False, "error": "SPT not found"}
        try:
            spt.validate(validator_id)
            await self._repository.update(spt)
            cache_key = self._get_cache_key(spt.npwp_badan, spt.tahun_pajak)
            await self._set_cached(cache_key, spt.to_dict())
            return {
                "success": True,
                "spt_id": str(spt.spt_id),
                "valid": True,
                "status": spt.status.value,
            }
        except SPTBadanValidationError as e:
            return {"success": False, "error": str(e), "valid": False}
        except (SPTBadanLockedError, SPTBadanInvalidStateError) as e:
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
                "npwp": spt.npwp_badan,
                "tahun": spt.tahun_pajak,
                "spt_type": spt_type,
                "correction_number": correction_number,
                "tax_type": "badan",
            }
            for attempt in range(MAX_RETRY_ATTEMPTS):
                try:
                    response = await client.post(CORETAX_SPT_TAHUNAN_ENDPOINT, payload)
                    spt.set_coretax_response(response)
                    await self._repository.update(spt)
                    if self._file_storage:
                        file_name = f"spt_tahunan_{spt.npwp_badan}_{spt.tahun_pajak}.xml"
                        await self._file_storage.upload(
                            xml_content.encode("utf-8"),
                            file_name,
                            "application/xml",
                            metadata={
                                "spt_id": str(spt.spt_id),
                                "npwp": spt.npwp_badan,
                                "tahun": spt.tahun_pajak,
                            },
                        )
                    cache_key = self._get_cache_key(spt.npwp_badan, spt.tahun_pajak)
                    await self._set_cached(cache_key, spt.to_dict())
                    try:
                        from infrastructure.telemetry.alert_manager_router import trigger_alert
                        await trigger_alert(
                            title="SPT Tahunan Badan Submitted",
                            message=f"SPT Tahunan for {spt.npwp_badan} year {spt.tahun_pajak} submitted successfully",
                            severity="info",
                            source="SPTTahunanBadanBuilder",
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
                    logger.warning(f"Retry {attempt + 1} for SPT Tahunan submission: {e}")
                except Exception as e:
                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        raise
                    logger.warning(f"Retry {attempt + 1} for SPT Tahunan submission: {e}")
        except (SPTBadanValidationError, SPTBadanLockedError, SPTBadanInvalidStateError, SPTBadanCalculationError) as e:
            return {"success": False, "error": str(e)}
        except CoretaxAuthError as e:
            spt.transition(SPTStatus.ERROR, submitted_by, str(e))
            await self._repository.update(spt)
            return {"success": False, "error": f"Coretax authentication failed: {e}"}
        except Exception as e:
            logger.exception("Failed to submit SPT Tahunan Badan")
            spt.transition(SPTStatus.ERROR, submitted_by, str(e))
            await self._repository.update(spt)
            try:
                from infrastructure.telemetry.alert_manager_router import trigger_alert
                await trigger_alert(
                    title="SPT Tahunan Badan Submission Failed",
                    message=f"Failed to submit SPT Tahunan: {e}",
                    severity="critical",
                    source="SPTTahunanBadanBuilder",
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
            cache_key = self._get_cache_key(spt.npwp_badan, spt.tahun_pajak)
            if cache_key in self._cache:
                del self._cache[cache_key]
            return {
                "success": True,
                "spt_id": str(spt.spt_id),
                "cancelled": True,
                "status": spt.status.value,
            }
        except (SPTBadanLockedError, SPTBadanInvalidStateError) as e:
            return {"success": False, "error": str(e)}

    async def create_correction_spt(self, npwp_badan: str, tahun_pajak: int, previous_spt_id: UUID, correction_number: int, submitted_by: UUID) -> dict[str, Any]:
        previous_spt = await self._repository.get_by_id(previous_spt_id)
        if not previous_spt:
            return {"success": False, "error": "Previous SPT not found"}
        correction_spt = previous_spt.create_correction(correction_number, submitted_by)
        await self._repository.add(correction_spt)
        return {
            "success": True,
            "spt_id": str(correction_spt.spt_id),
            "tahun_pajak": correction_spt.tahun_pajak,
            "correction_number": correction_number,
            "status": correction_spt.status.value,
        }

    async def get_by_id(self, spt_id: UUID) -> SPTTahunanBadan | None:
        return await self._repository.get_by_id(spt_id)

    async def get_by_npwp_tahun(self, npwp: str, tahun: int) -> SPTTahunanBadan | None:
        return await self._repository.get_by_npwp_tahun(npwp, tahun)

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
    def build_sync(self, data_keuangan: dict[str, Any], tahun_buku: int) -> SPTTahunanBadanDummy:
        return SPTTahunanBadanDummy(
            tahun_buku=tahun_buku,
            penghasilan_bruto=data_keuangan.get("penghasilan_bruto", Decimal(0)),
            beban=data_keuangan.get("beban", Decimal(0)),
        )


# ============================================================================
# SPT OBJECT FOR TESTING
# ============================================================================
class SPTTahunanBadanDummy:
    def __init__(self, tahun_buku: int, penghasilan_bruto: Decimal, beban: Decimal):
        self.tahun_buku = tahun_buku
        self.penghasilan_bruto = penghasilan_bruto
        self.beban = beban
        self._attachments = ["laporan_keuangan", "daftar_susunan_pemegang_saham"]

    def has_attachment(self, name: str) -> bool:
        return name in self._attachments


# ============================================================================
# SINGLETON
# ============================================================================
_spt_tahunan_builder: SPTTahunanBadanBuilder | None = None

async def get_spt_tahunan_builder(config: dict | None = None) -> SPTTahunanBadanBuilder:
    global _spt_tahunan_builder
    if _spt_tahunan_builder is None:
        _spt_tahunan_builder = SPTTahunanBadanBuilder(config=config)
    return _spt_tahunan_builder

__all__ = [
    "CORPORATE_TAX_RATE",
    "JENIS_KOREKSI",
    "PUBLIC_COMPANY_RATE",
    "SUMBER_KOREKSI",
    "KoreksiFiskal",
    "KoreksiFiskalType",
    "PemegangSaham",
    "SPTStatus",
    "SPTTahunanBadan",
    "SPTTahunanBadanBuilder",
    "SPTTahunanBadanDummy",
    "SPTType",
    "get_spt_tahunan_builder",
]
