#!/usr/bin/env python3
"""
Module: coretax_format_validator.py
Layer: 4 - Kernel / Guards
Responsibility: Validasi format data sebelum dikirim ke Coretax DJP.
               Memastikan bahwa data yang dikirim ke sistem Coretax DJP
               (faktur pajak, SPT, pembayaran) memenuhi format dan skema
               yang dipersyaratkan, termasuk validasi NPWP, kode faktur,
               NTPN, dan struktur data JSON/XML.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.guards.guard_exceptions import (
    CoretaxFormatError,
    GuardSeverity,
)

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class CoretaxValidationSeverity(Enum):
    INFO = 0       # Ditambahkan untuk validasi sukses
    LOW = 20
    MEDIUM = 40
    HIGH = 60
    CRITICAL = 80


class CoretaxDocumentType(Enum):
    FAKTUR_PAJAK = "faktur_pajak"
    SPT_MASA_PPN = "spt_masa_ppn"
    SPT_MASA_PPH_21 = "spt_masa_pph_21"
    SPT_MASA_PPH_23 = "spt_masa_pph_23"
    SPT_TAHUNAN = "spt_tahunan"
    BUKTI_POTONG = "bukti_potong"
    NTPN = "ntpn"


# ============================================================================
# CONSTANT PATTERNS
# ============================================================================

NPWP_PATTERN = re.compile(r"^(\d{2}\.\d{3}\.\d{3}\.\d{1}-\d{3}\.\d{3})$|^(\d{15})$")
NTPN_PATTERN = re.compile(r"^[A-Z0-9]{16}$")
FAKTUR_PAJAK_PATTERN = re.compile(r"^010-\d{2}-\d{8}-\d{10}$|^\d{16,20}$")
KODE_FAKTUR_VALID = ["010", "011", "020", "030", "040", "050", "060", "070", "080", "090"]
FAKTUR_TYPE = {
    "010": "Faktur Pajak Keluaran (PKP Penjual)",
    "011": "Faktur Pajak Keluaran (PKP Pembeli - KMS)",
    "020": "Faktur Pajak Masukan (PKP Pembeli)",
    "030": "Faktur Pajak Digunggung",
    "040": "Faktur Pajak Penyerahan ke Pemungut PPN",
    "050": "Faktur Pajak Penyerahan dengan Besaran Tertentu",
    "060": "Faktur Pajak Penyerahan yang PPN-nya Tidak Dipungut",
    "070": "Faktur Pajak Penyerahan yang PPN-nya Dibebaskan",
    "080": "Faktur Pajak Penyerahan yang PPnBM-nya Tidak Dipungut",
    "090": "Faktur Pajak Penyerahan yang PPnBM-nya Dibebaskan",
}

MASA_PAJAK_PATTERN = re.compile(r"^(0[1-9]|1[0-2])/\d{4}$")
TAHUN_PAJAK_PATTERN = re.compile(r"^\d{4}$")
BUKTI_POTONG_VALID_TYPES = ["21", "22", "23", "26", "4(2)", "15"]
SPT_VALID_TYPES = ["PPN", "PPH_21", "PPH_22", "PPH_23", "PPH_4_2", "PPH_25", "PPH_26", "PPH_BADAN"]


# ============================================================================
# VALUE OBJECTS
# ============================================================================


@dataclass
class CoretaxValidationResult:
    validation_id: UUID
    document_type: CoretaxDocumentType
    field_name: str
    field_value: str
    is_valid: bool
    severity: CoretaxValidationSeverity
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    validated_by: str = "system"
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.validation_id}|{self.document_type.value}|{self.field_name}|"
            f"{self.is_valid}|{self.severity.value}|{self.message[:100]}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_id": str(self.validation_id),
            "document_type": self.document_type.value,
            "field_name": self.field_name,
            "field_value": self.field_value[:50],
            "is_valid": self.is_valid,
            "severity": self.severity.name,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


# ============================================================================
# CORETAX FORMAT VALIDATOR (STATIC)
# ============================================================================


class CoretaxFormatValidator:
    @staticmethod
    def validate_npwp(npwp: str) -> tuple[bool, str | None]:
        if not npwp:
            return False, "NPWP tidak boleh kosong"
        npwp_clean = npwp.strip()
        if NPWP_PATTERN.match(npwp_clean):
            return True, None
        else:
            return (
                False,
                f"Format NPWP tidak valid: {npwp_clean}. Harus 15 digit atau dengan format 00.000.000.0-000.000",
            )

    @staticmethod
    def validate_ntpn(ntpn: str) -> tuple[bool, str | None]:
        if not ntpn:
            return False, "NTPN tidak boleh kosong"
        if NTPN_PATTERN.match(ntpn.upper()):
            return True, None
        else:
            return False, f"Format NTPN tidak valid: {ntpn}. Harus 16 karakter alfanumerik."

    @staticmethod
    def validate_faktur_pajak(faktur: str, kode: str | None = None) -> tuple[bool, str | None]:
        if not faktur:
            return False, "Nomor faktur pajak tidak boleh kosong"
        if not FAKTUR_PAJAK_PATTERN.match(faktur):
            return False, f"Format nomor faktur pajak tidak valid: {faktur}"
        # Gabungkan nested if dengan and (SIM102)
        if kode and kode not in KODE_FAKTUR_VALID:
            return (
                False,
                f"Kode faktur pajak '{kode}' tidak valid. Kode yang valid: {KODE_FAKTUR_VALID}",
            )
        return True, None

    @staticmethod
    def validate_masa_pajak(masa_pajak: str) -> tuple[bool, str | None]:
        if not masa_pajak:
            return False, "Masa pajak tidak boleh kosong"
        if MASA_PAJAK_PATTERN.match(masa_pajak):
            return True, None
        else:
            return (
                False,
                f"Format masa pajak tidak valid: {masa_pajak}. Harus MM/YYYY (contoh: 01/2024)",
            )

    @staticmethod
    def validate_tahun_pajak(tahun: str) -> tuple[bool, str | None]:
        if not tahun:
            return False, "Tahun pajak tidak boleh kosong"
        if TAHUN_PAJAK_PATTERN.match(tahun):
            year = int(tahun)
            current_year = datetime.now(UTC).year
            if year < 2000 or year > current_year + 1:
                return False, f"Tahun pajak {tahun} di luar rentang (2000-{current_year + 1})"
            return True, None
        else:
            return False, f"Format tahun pajak tidak valid: {tahun}. Harus YYYY"

    @staticmethod
    def validate_nilai_ppn(ppn: Decimal, dpp: Decimal) -> tuple[bool, str | None]:
        # Konversi jika menerima float (untuk kompatibilitas)
        if isinstance(ppn, float):
            ppn = Decimal(str(ppn))
        if isinstance(dpp, float):
            dpp = Decimal(str(dpp))

        if ppn <= 0 or dpp <= 0:
            return False, "Nilai PPN dan DPP harus positif"
        expected_ppn_11 = dpp * Decimal("0.11")
        expected_ppn_12 = dpp * Decimal("0.12")
        if abs(ppn - expected_ppn_11) > Decimal("0.01") and abs(ppn - expected_ppn_12) > Decimal("0.01"):
            return (
                False,
                f"Nilai PPN {ppn} tidak sesuai dengan DPP {dpp} (11% = {expected_ppn_11:.2f}, 12% = {expected_ppn_12:.2f})",
            )
        return True, None

    @staticmethod
    def validate_kode_efaktur(kode: str) -> tuple[bool, str | None]:
        if kode not in KODE_FAKTUR_VALID:
            return False, f"Kode faktur '{kode}' tidak dikenal. Kode valid: {KODE_FAKTUR_VALID}"
        return True, None

    @staticmethod
    def validate_bukti_potong_type(bukti_type: str) -> tuple[bool, str | None]:
        if bukti_type not in BUKTI_POTONG_VALID_TYPES:
            return (
                False,
                f"Jenis bukti potong '{bukti_type}' tidak valid. Harus salah satu: {BUKTI_POTONG_VALID_TYPES}",
            )
        return True, None

    @staticmethod
    def validate_tarif_pph(tarif: Decimal, bukti_type: str) -> tuple[bool, str | None]:
        if isinstance(tarif, float):
            tarif = Decimal(str(tarif))
        expected_ranges = {
            "21": (Decimal("0.0"), Decimal("0.35")),
            "22": (Decimal("0.0"), Decimal("0.10")),
            "23": (Decimal("0.0"), Decimal("0.15")),
            "26": (Decimal("0.2"), Decimal("0.2")),
            "4(2)": (Decimal("0.0"), Decimal("0.10")),
            "15": (Decimal("0.0"), Decimal("0.30")),
        }
        low, high = expected_ranges.get(bukti_type, (Decimal("0"), Decimal("1")))
        if tarif < low or tarif > high:
            return (
                False,
                f"Tarif PPh {tarif * 100:.0f}% tidak wajar untuk jenis bukti potong {bukti_type}",
            )
        return True, None

    @staticmethod
    def validate_spt_type(spt_type: str) -> tuple[bool, str | None]:
        if spt_type not in SPT_VALID_TYPES:
            return (
                False,
                f"Jenis SPT '{spt_type}' tidak dikenal. Harus salah satu: {SPT_VALID_TYPES}",
            )
        return True, None


# ============================================================================
# BASE CORETAX FORMAT GUARD (ABSTRACT)
# ============================================================================

class BaseCoretaxFormatGuard(ABC):
    """Base contract untuk Coretax Format Guard."""

    @abstractmethod
    async def validate_efaktur_data(
        self,
        npwp_penjual: str,
        npwp_pembeli: str,
        kode_faktur: str,
        nomor_faktur: str,
        dpp: Decimal,          # diubah dari float
        ppn: Decimal,           # diubah dari float
        masa_pajak: str,
        tahun_pajak: str,
        user_id: str | None = None,
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        """Validate e-Faktur data."""
        pass

    @abstractmethod
    async def validate_ebupot_data(
        self,
        npwp_pemotong: str,
        npwp_penerima: str,
        bukti_type: str,
        tarif: Decimal,               # diubah dari float
        dasar_pemotongan: Decimal,    # diubah dari float
        pph_terutang: Decimal,        # diubah dari float
        masa_pajak: str,
        user_id: str | None = None,
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        """Validate e-Bupot data."""
        pass

    @abstractmethod
    async def validate_spt_submission(
        self,
        spt_type: str,
        npwp: str,
        masa_pajak: str,
        tahun_pajak: str,
        total_ppn: Decimal | None = None,   # diubah dari float
        total_pph: Decimal | None = None,   # diubah dari float
        user_id: str | None = None,
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        """Validate SPT submission data."""
        pass

    @abstractmethod
    async def enforce_efaktur(
        self, raise_on_violation: bool = True, **kwargs
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        """Enforce e-Faktur validation."""
        pass

    @abstractmethod
    async def enforce_ebupot(
        self, raise_on_violation: bool = True, **kwargs
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        """Enforce e-Bupot validation."""
        pass

    @abstractmethod
    async def enforce_spt(
        self, raise_on_violation: bool = True, **kwargs
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        """Enforce SPT validation."""
        pass

    @abstractmethod
    def get_validation_history(
        self,
        limit: int = 100,
        document_type: CoretaxDocumentType | None = None,
        only_invalid: bool = False,
    ) -> list[CoretaxValidationResult]:
        """Get validation history."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about validations."""
        pass

    # ==================== CHECKER METHODS ====================

    @abstractmethod
    def check(self, context: dict) -> list[str]:
        """Sync check method untuk compliance checker."""
        pass

    @abstractmethod
    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        pass

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseCoretaxFormatGuard:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseCoretaxFormatGuard:
        """Clone instance."""
        pass

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        pass

    @abstractmethod
    def version(self) -> int:
        """Dapatkan versi."""
        pass

    @abstractmethod
    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        pass

    @abstractmethod
    def touch(self, touched_by: str) -> BaseCoretaxFormatGuard:
        """Touch instance (increment version)."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset state."""
        pass


# ============================================================================
# CORETAX FORMAT GUARD (CONCRETE)
# ============================================================================


class CoretaxFormatGuard(BaseCoretaxFormatGuard):
    _instance: CoretaxFormatGuard | None = None
    _lock = threading.Lock()
    _initialized: bool  # Tambahkan deklarasi tipe

    def __new__(cls) -> CoretaxFormatGuard:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._validation_history: list[CoretaxValidationResult] = []
        self._max_history = 10000
        self._history_lock = threading.RLock()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================

    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors: list[str] = []
        document_type = context.get("document_type")
        data = context.get("data")

        if not document_type:
            errors.append("document_type is required")
        elif document_type not in ["efaktur", "ebupot", "spt"]:
            errors.append("document_type must be one of: efaktur, ebupot, spt")

        if data is None:
            errors.append("data is required")
        elif not isinstance(data, dict):
            errors.append("data must be a dict")
        else:
            if document_type == "efaktur":
                required = ["npwp_penjual", "npwp_pembeli", "kode_faktur", "nomor_faktur", "dpp", "ppn", "masa_pajak", "tahun_pajak"]
                for field in required:
                    if field not in data:
                        errors.append(f"efaktur data missing field: {field}")
            elif document_type == "ebupot":
                required = ["npwp_pemotong", "npwp_penerima", "bukti_type", "tarif", "dasar_pemotongan", "pph_terutang", "masa_pajak"]
                for field in required:
                    if field not in data:
                        errors.append(f"ebupot data missing field: {field}")
            elif document_type == "spt":
                required = ["spt_type", "npwp", "masa_pajak", "tahun_pajak"]
                for field in required:
                    if field not in data:
                        errors.append(f"spt data missing field: {field}")

        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        return {
            "validation_history_count": len(self._validation_history),
            "max_history": self._max_history,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoretaxFormatGuard:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> CoretaxFormatGuard:
        """Clone instance."""
        new_instance = CoretaxFormatGuard()
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._history_lock:
            return {
                "version": self._version,
                "history_count": len(self._validation_history),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CoretaxFormatGuard:
        """Touch instance (increment version)."""
        self._version += 1
        self._audit_trail.append({
            "action": "TOUCH",
            "performed_by": touched_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
        })
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append({
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
            "details": details,
        })

    # ==================== ORIGINAL BUSINESS METHODS ====================

    async def validate_efaktur_data(
        self,
        npwp_penjual: str,
        npwp_pembeli: str,
        kode_faktur: str,
        nomor_faktur: str,
        dpp: Decimal,
        ppn: Decimal,
        masa_pajak: str,
        tahun_pajak: str,
        user_id: str | None = None,
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        results: list[CoretaxValidationResult] = []

        def add_result(
            field: str, value: str, is_valid: bool, severity: CoretaxValidationSeverity, msg: str
        ) -> None:
            result = CoretaxValidationResult(
                validation_id=uuid4(),
                document_type=CoretaxDocumentType.FAKTUR_PAJAK,
                field_name=field,
                field_value=value,
                is_valid=is_valid,
                severity=severity,
                message=msg,
                validated_by=user_id or get_current_user() or "system",
                cryptographic_hash="",
            )
            result = CoretaxValidationResult(
                validation_id=result.validation_id,
                document_type=result.document_type,
                field_name=result.field_name,
                field_value=result.field_value,
                is_valid=result.is_valid,
                severity=result.severity,
                message=result.message,
                details=result.details,
                timestamp=result.timestamp,
                validated_by=result.validated_by,
                cryptographic_hash=result.compute_hash(),
            )
            results.append(result)

        # NPWP Penjual
        is_valid, msg = CoretaxFormatValidator.validate_npwp(npwp_penjual)
        add_result(
            "npwp_penjual",
            npwp_penjual,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # NPWP Pembeli
        is_valid, msg = CoretaxFormatValidator.validate_npwp(npwp_pembeli)
        add_result(
            "npwp_pembeli",
            npwp_pembeli,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # Kode faktur
        is_valid, msg = CoretaxFormatValidator.validate_kode_efaktur(kode_faktur)
        add_result(
            "kode_faktur",
            kode_faktur,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # Nomor faktur
        is_valid, msg = CoretaxFormatValidator.validate_faktur_pajak(nomor_faktur, kode_faktur)
        add_result(
            "nomor_faktur",
            nomor_faktur,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # Nilai PPN vs DPP
        is_valid, msg = CoretaxFormatValidator.validate_nilai_ppn(ppn, dpp)
        add_result(
            "ppn",
            str(ppn),
            is_valid,
            CoretaxValidationSeverity.HIGH if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # Masa pajak
        is_valid, msg = CoretaxFormatValidator.validate_masa_pajak(masa_pajak)
        add_result(
            "masa_pajak",
            masa_pajak,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # Tahun pajak
        is_valid, msg = CoretaxFormatValidator.validate_tahun_pajak(tahun_pajak)
        add_result(
            "tahun_pajak",
            tahun_pajak,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )

        with self._history_lock:
            self._validation_history.extend(results)
            if len(self._validation_history) > self._max_history:
                self._validation_history = self._validation_history[-self._max_history :]

        is_valid = all(r.is_valid for r in results)
        return is_valid, results

    async def validate_ebupot_data(
        self,
        npwp_pemotong: str,
        npwp_penerima: str,
        bukti_type: str,
        tarif: Decimal,
        dasar_pemotongan: Decimal,
        pph_terutang: Decimal,
        masa_pajak: str,
        user_id: str | None = None,
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        results: list[CoretaxValidationResult] = []

        def add_result(
            field: str, value: str, is_valid: bool, severity: CoretaxValidationSeverity, msg: str
        ) -> None:
            result = CoretaxValidationResult(
                validation_id=uuid4(),
                document_type=CoretaxDocumentType.BUKTI_POTONG,
                field_name=field,
                field_value=value,
                is_valid=is_valid,
                severity=severity,
                message=msg,
                validated_by=user_id or get_current_user() or "system",
                cryptographic_hash="",
            )
            result = CoretaxValidationResult(
                validation_id=result.validation_id,
                document_type=result.document_type,
                field_name=result.field_name,
                field_value=result.field_value,
                is_valid=result.is_valid,
                severity=result.severity,
                message=result.message,
                details=result.details,
                timestamp=result.timestamp,
                validated_by=result.validated_by,
                cryptographic_hash=result.compute_hash(),
            )
            results.append(result)

        # NPWP Pemotong
        is_valid, msg = CoretaxFormatValidator.validate_npwp(npwp_pemotong)
        add_result(
            "npwp_pemotong",
            npwp_pemotong,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # NPWP Penerima
        is_valid, msg = CoretaxFormatValidator.validate_npwp(npwp_penerima)
        add_result(
            "npwp_penerima",
            npwp_penerima,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # Jenis bukti potong
        is_valid, msg = CoretaxFormatValidator.validate_bukti_potong_type(bukti_type)
        add_result(
            "bukti_type",
            bukti_type,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # Tarif
        is_valid, msg = CoretaxFormatValidator.validate_tarif_pph(tarif, bukti_type)
        add_result(
            "tarif",
            str(tarif),
            is_valid,
            CoretaxValidationSeverity.HIGH if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # Perhitungan PPh
        calculated_pph = dasar_pemotongan * tarif
        if abs(calculated_pph - pph_terutang) > Decimal("0.01"):
            msg = f"Perhitungan PPh tidak sesuai: dasar {dasar_pemotongan} * tarif {tarif} = {calculated_pph}, tetapi PPh terutang {pph_terutang}"
            add_result(
                "pph_terutang", str(pph_terutang), False, CoretaxValidationSeverity.HIGH, msg
            )
        else:
            add_result(
                "pph_terutang", str(pph_terutang), True, CoretaxValidationSeverity.INFO, "OK"
            )
        # Masa pajak
        is_valid, msg = CoretaxFormatValidator.validate_masa_pajak(masa_pajak)
        add_result(
            "masa_pajak",
            masa_pajak,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )

        with self._history_lock:
            self._validation_history.extend(results)
            if len(self._validation_history) > self._max_history:
                self._validation_history = self._validation_history[-self._max_history :]

        is_valid = all(r.is_valid for r in results)
        return is_valid, results

    async def validate_spt_submission(
        self,
        spt_type: str,
        npwp: str,
        masa_pajak: str,
        tahun_pajak: str,
        total_ppn: Decimal | None = None,
        total_pph: Decimal | None = None,
        user_id: str | None = None,
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        results: list[CoretaxValidationResult] = []

        def add_result(
            field: str, value: str, is_valid: bool, severity: CoretaxValidationSeverity, msg: str
        ) -> None:
            result = CoretaxValidationResult(
                validation_id=uuid4(),
                document_type=CoretaxDocumentType.SPT_MASA_PPN,
                field_name=field,
                field_value=value,
                is_valid=is_valid,
                severity=severity,
                message=msg,
                validated_by=user_id or get_current_user() or "system",
                cryptographic_hash="",
            )
            result = CoretaxValidationResult(
                validation_id=result.validation_id,
                document_type=result.document_type,
                field_name=result.field_name,
                field_value=result.field_value,
                is_valid=result.is_valid,
                severity=result.severity,
                message=result.message,
                details=result.details,
                timestamp=result.timestamp,
                validated_by=result.validated_by,
                cryptographic_hash=result.compute_hash(),
            )
            results.append(result)

        # Jenis SPT
        is_valid, msg = CoretaxFormatValidator.validate_spt_type(spt_type)
        add_result(
            "spt_type",
            spt_type,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # NPWP
        is_valid, msg = CoretaxFormatValidator.validate_npwp(npwp)
        add_result(
            "npwp",
            npwp,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # Masa pajak
        is_valid, msg = CoretaxFormatValidator.validate_masa_pajak(masa_pajak)
        add_result(
            "masa_pajak",
            masa_pajak,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        # Tahun pajak
        is_valid, msg = CoretaxFormatValidator.validate_tahun_pajak(tahun_pajak)
        add_result(
            "tahun_pajak",
            tahun_pajak,
            is_valid,
            CoretaxValidationSeverity.CRITICAL if not is_valid else CoretaxValidationSeverity.INFO,
            msg or "OK",
        )
        if total_ppn is not None and total_ppn < 0:
            add_result(
                "total_ppn",
                str(total_ppn),
                False,
                CoretaxValidationSeverity.HIGH,
                "Total PPN tidak boleh negatif",
            )
        elif total_ppn is not None:
            add_result("total_ppn", str(total_ppn), True, CoretaxValidationSeverity.INFO, "OK")
        if total_pph is not None and total_pph < 0:
            add_result(
                "total_pph",
                str(total_pph),
                False,
                CoretaxValidationSeverity.HIGH,
                "Total PPh tidak boleh negatif",
            )
        elif total_pph is not None:
            add_result("total_pph", str(total_pph), True, CoretaxValidationSeverity.INFO, "OK")

        with self._history_lock:
            self._validation_history.extend(results)
            if len(self._validation_history) > self._max_history:
                self._validation_history = self._validation_history[-self._max_history :]

        is_valid = all(r.is_valid for r in results)
        return is_valid, results

    async def enforce_efaktur(
        self, raise_on_violation: bool = True, **kwargs
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        is_valid, results = await self.validate_efaktur_data(**kwargs)
        if raise_on_violation:
            critical = [
                r
                for r in results
                if r.severity == CoretaxValidationSeverity.CRITICAL and not r.is_valid
            ]
            if critical:
                raise CoretaxFormatError(
                    message=f"Coretax format validation failed: {critical[0].message}",
                    field=critical[0].field_name,
                    value=critical[0].field_value,
                    severity=GuardSeverity.CRITICAL,
                    details={"validation_results": [r.to_dict() for r in critical]},
                )
        return is_valid, results

    async def enforce_ebupot(
        self, raise_on_violation: bool = True, **kwargs
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        is_valid, results = await self.validate_ebupot_data(**kwargs)
        if raise_on_violation:
            critical = [
                r
                for r in results
                if r.severity == CoretaxValidationSeverity.CRITICAL and not r.is_valid
            ]
            if critical:
                raise CoretaxFormatError(
                    message=f"Coretax e-Bupot validation failed: {critical[0].message}",
                    field=critical[0].field_name,
                    value=critical[0].field_value,
                    severity=GuardSeverity.CRITICAL,
                    details={"validation_results": [r.to_dict() for r in critical]},
                )
        return is_valid, results

    async def enforce_spt(
        self, raise_on_violation: bool = True, **kwargs
    ) -> tuple[bool, list[CoretaxValidationResult]]:
        is_valid, results = await self.validate_spt_submission(**kwargs)
        if raise_on_violation:
            critical = [
                r
                for r in results
                if r.severity == CoretaxValidationSeverity.CRITICAL and not r.is_valid
            ]
            if critical:
                raise CoretaxFormatError(
                    message=f"Coretax SPT validation failed: {critical[0].message}",
                    field=critical[0].field_name,
                    value=critical[0].field_value,
                    severity=GuardSeverity.CRITICAL,
                    details={"validation_results": [r.to_dict() for r in critical]},
                )
        return is_valid, results

    def get_validation_history(
        self,
        limit: int = 100,
        document_type: CoretaxDocumentType | None = None,
        only_invalid: bool = False,
    ) -> list[CoretaxValidationResult]:
        with self._history_lock:
            results = self._validation_history[-limit:]
        if document_type:
            results = [r for r in results if r.document_type == document_type]
        if only_invalid:
            results = [r for r in results if not r.is_valid]
        return results

    def get_statistics(self) -> dict[str, Any]:
        with self._history_lock:
            total = len(self._validation_history)
            if total == 0:
                return {"total_validations": 0, "version": self._version}
            invalid = len([r for r in self._validation_history if not r.is_valid])
            by_severity: dict[str, int] = {}
            by_document: dict[str, int] = {}
            for r in self._validation_history:
                if not r.is_valid:
                    by_severity[r.severity.name] = by_severity.get(r.severity.name, 0) + 1
                by_document[r.document_type.value] = by_document.get(r.document_type.value, 0) + 1
            return {
                "total_validations": total,
                "invalid_count": invalid,
                "validity_rate": (total - invalid) / total if total > 0 else 1.0,
                "by_severity": by_severity,
                "by_document_type": by_document,
                "latest_validation": self._validation_history[-1].timestamp.isoformat()
                if self._validation_history
                else None,
                "version": self._version,
            }

    def reset(self) -> None:
        with self._history_lock:
            self._validation_history = []
            self._version += 1
            self._audit_trail = []


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_coretax_format_guard_instance: CoretaxFormatGuard | None = None


def get_coretax_format_guard() -> CoretaxFormatGuard:
    global _coretax_format_guard_instance
    if _coretax_format_guard_instance is None:
        _coretax_format_guard_instance = CoretaxFormatGuard()
    return _coretax_format_guard_instance


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CoretaxDocumentType",
    "CoretaxFormatGuard",
    "CoretaxFormatValidator",
    "CoretaxValidationResult",
    "CoretaxValidationSeverity",
    "get_coretax_format_guard",
]
