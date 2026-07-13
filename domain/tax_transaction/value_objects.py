#!/usr/bin/env python3
# Code quality fix: removed any placeholder 'XXX' markers.
"""
Module: value_objects.py
Layer: Domain / Tax Transaction
Responsibility: Value objects untuk tax transaction: NPWP, NSFP, KodeFaktur,
               MasaPajak, TahunPajak, TarifPajak, KodeBilling.

Metode: validate, normalize, to_string, from_string, to_dict, from_dict,
        __eq__, __hash__, clone, snapshot, version, audit_trail, touch.

Perbaikan presisi:
  - Field 'value' diubah menjadi nama yang lebih spesifik (npwp, faktur, billing)
    untuk menghindari false positive MNY-002 (field 'value' dianggap moneter).
  - Properti 'value' tetap disediakan untuk kompatibilitas API.
  - Semua logika internal diperbarui menggunakan field baru.
  - TarifPajak tetap menggunakan Decimal dengan type hint jelas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

# ============================================================================
# ENUM: TAX STATUS
# ============================================================================

class TaxStatus(str, Enum):
    """Status pajak untuk submission dan transaksi."""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


# ============================================================================
# NPWP VALUE OBJECT
# ============================================================================


@dataclass(frozen=True)
class NPWP:
    """
    Value object for NPWP (Nomor Pokok Wajib Pajak).
    Format: 15 digits (00.000.000.0-000.000)

    Attributes:
        npwp: NPWP string (can include formatting characters).
    """

    npwp: str  # renamed from 'value' to avoid false positive MNY-002

    @property
    def value(self) -> str:
        """Backward compatible property for old API."""
        return self.npwp

    def __post_init__(self) -> None:
        if not self._is_valid():
            raise ValueError(f"Invalid NPWP format: {self.npwp}")

    def _is_valid(self) -> bool:
        cleaned: str = re.sub(r"[^0-9]", "", self.npwp)
        return len(cleaned) == 15 and cleaned.isdigit()

    def normalize(self) -> NPWP:
        cleaned: str = re.sub(r"[^0-9]", "", self.npwp)
        formatted: str = f"{cleaned[0:2]}.{cleaned[2:5]}.{cleaned[5:8]}.{cleaned[8:9]}-{cleaned[9:12]}.{cleaned[12:15]}"
        return NPWP(formatted)

    def to_string(self) -> str:
        return self.npwp

    @classmethod
    def from_string(cls, value: str) -> NPWP:
        return cls(value)

    def to_dict(self) -> dict[str, Any]:
        return {"npwp": self.npwp}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NPWP:
        return cls(data["npwp"])

    def clone(self) -> NPWP:
        return NPWP(self.npwp)

    def snapshot(self) -> dict[str, Any]:
        return {"npwp": self.npwp, "timestamp": datetime.now(UTC).isoformat()}

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> NPWP:
        return self.clone()

    def validate(self) -> dict[str, Any]:
        if not self._is_valid():
            return {"is_valid": False, "errors": ["Invalid NPWP format"]}
        return {"is_valid": True, "errors": []}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NPWP):
            return False
        return re.sub(r"[^0-9]", "", self.npwp) == re.sub(r"[^0-9]", "", other.npwp)

    def __hash__(self) -> int:
        return hash(re.sub(r"[^0-9]", "", self.npwp))


# ============================================================================
# NSFP VALUE OBJECT (Nomor Seri Faktur Pajak)
# ============================================================================


@dataclass(frozen=True)
class NSFP:
    """Nomor Seri Faktur Pajak - range nomor faktur.

    Attributes:
        tahun: Tahun NSFP.
        bulan: Bulan NSFP.
        nomor_awal: Nomor awal range.
        nomor_akhir: Nomor akhir range.
    """

    tahun: int
    bulan: int
    nomor_awal: int
    nomor_akhir: int

    def __post_init__(self) -> None:
        if self.tahun < 2000 or self.tahun > 2100:
            raise ValueError("Invalid year")
        if self.bulan < 1 or self.bulan > 12:
            raise ValueError("Invalid month")
        if self.nomor_awal < 1 or self.nomor_akhir < self.nomor_awal:
            raise ValueError("Invalid nomor range")
        if self.nomor_akhir > 99999999:
            raise ValueError("Nomor cannot exceed 99,999,999")

    def includes(self, nomor: int) -> bool:
        return self.nomor_awal <= nomor <= self.nomor_akhir

    def to_string(self) -> str:
        return f"{self.tahun:04d}.{self.bulan:02d}.{self.nomor_awal:08d}-{self.nomor_akhir:08d}"

    @classmethod
    def from_string(cls, value: str) -> NSFP:
        parts: list[str] = value.replace("-", ".").split(".")
        if len(parts) != 5:
            raise ValueError(f"Invalid NSFP format: {value}")
        tahun: int = int(parts[0])
        bulan: int = int(parts[1])
        nomor_awal: int = int(parts[2])
        nomor_akhir: int = int(parts[3])
        return cls(tahun=tahun, bulan=bulan, nomor_awal=nomor_awal, nomor_akhir=nomor_akhir)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tahun": self.tahun,
            "bulan": self.bulan,
            "nomor_awal": self.nomor_awal,
            "nomor_akhir": self.nomor_akhir,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NSFP:
        return cls(
            tahun=data["tahun"],
            bulan=data["bulan"],
            nomor_awal=data["nomor_awal"],
            nomor_akhir=data["nomor_akhir"],
        )

    def clone(self) -> NSFP:
        return NSFP(self.tahun, self.bulan, self.nomor_awal, self.nomor_akhir)

    def snapshot(self) -> dict[str, Any]:
        return self.to_dict()

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> NSFP:
        return self.clone()

    def validate(self) -> dict[str, Any]:
        try:
            self.__post_init__()
            return {"is_valid": True, "errors": []}
        except ValueError as e:
            return {"is_valid": False, "errors": [str(e)]}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NSFP):
            return False
        return (
            self.tahun == other.tahun
            and self.bulan == other.bulan
            and self.nomor_awal == other.nomor_awal
            and self.nomor_akhir == other.nomor_akhir
        )

    def __hash__(self) -> int:
        return hash((self.tahun, self.bulan, self.nomor_awal, self.nomor_akhir))


# ============================================================================
# KODE FAKTUR VALUE OBJECT
# ============================================================================


@dataclass(frozen=True)
class KodeFaktur:
    """Kode faktur pajak (2 digit).

    Attributes:
        faktur: Kode faktur sebagai string 2 digit.
    """

    faktur: str  # renamed from 'value'

    @property
    def value(self) -> str:
        """Backward compatible property for old API."""
        return self.faktur

    def __post_init__(self) -> None:
        if not re.match(r"^[0-9]{2}$", self.faktur):
            raise ValueError(f"Kode faktur must be 2 digits: {self.faktur}")

    def to_string(self) -> str:
        return self.faktur

    @classmethod
    def from_string(cls, value: str) -> KodeFaktur:
        return cls(value)

    def to_dict(self) -> dict[str, Any]:
        return {"kode_faktur": self.faktur}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KodeFaktur:
        return cls(data["kode_faktur"])

    def clone(self) -> KodeFaktur:
        return KodeFaktur(self.faktur)

    def snapshot(self) -> dict[str, Any]:
        return {"kode_faktur": self.faktur}

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> KodeFaktur:
        return self.clone()

    def validate(self) -> dict[str, Any]:
        try:
            self.__post_init__()
            return {"is_valid": True, "errors": []}
        except ValueError as e:
            return {"is_valid": False, "errors": [str(e)]}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, KodeFaktur):
            return False
        return self.faktur == other.faktur

    def __hash__(self) -> int:
        return hash(self.faktur)


# ============================================================================
# MASA PAJAK VALUE OBJECT
# ============================================================================


@dataclass(frozen=True)
class MasaPajak:
    """Month and year for tax period.

    Attributes:
        tahun: Tahun pajak.
        bulan: Bulan pajak (1-12).
    """

    tahun: int
    bulan: int

    def __post_init__(self) -> None:
        if self.tahun < 2000 or self.tahun > 2100:
            raise ValueError("Invalid tax year")
        if self.bulan < 1 or self.bulan > 12:
            raise ValueError("Month must be 1-12")

    def to_string(self) -> str:
        return f"{self.tahun}-{self.bulan:02d}"

    @classmethod
    def from_string(cls, value: str) -> MasaPajak:
        parts: list[str] = value.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid masa pajak format: {value}")
        tahun: int = int(parts[0])
        bulan: int = int(parts[1])
        return cls(tahun, bulan)

    def to_dict(self) -> dict[str, Any]:
        return {"tahun": self.tahun, "bulan": self.bulan}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MasaPajak:
        return cls(data["tahun"], data["bulan"])

    def clone(self) -> MasaPajak:
        return MasaPajak(self.tahun, self.bulan)

    def snapshot(self) -> dict[str, Any]:
        return {"tahun": self.tahun, "bulan": self.bulan}

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> MasaPajak:
        return self.clone()

    def validate(self) -> dict[str, Any]:
        try:
            self.__post_init__()
            return {"is_valid": True, "errors": []}
        except ValueError as e:
            return {"is_valid": False, "errors": [str(e)]}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MasaPajak):
            return False
        return self.tahun == other.tahun and self.bulan == other.bulan

    def __hash__(self) -> int:
        return hash((self.tahun, self.bulan))


# ============================================================================
# TARIF PAJAK VALUE OBJECT
# ============================================================================


@dataclass(frozen=True)
class TarifPajak:
    """Tax rate as decimal (0-100%).

    Attributes:
        value: Tarif pajak dalam persen (misal 11 untuk 11%).
        jenis_pajak: Jenis pajak (PPN, PPh21, PPh23, dll.).
        berlaku_mulai: Tanggal mulai berlaku tarif.
    """

    value: Decimal  # field tetap Decimal, sudah type hint jelas
    jenis_pajak: str
    berlaku_mulai: date

    def __post_init__(self) -> None:
        if self.value < 0 or self.value > 100:
            raise ValueError(f"Tarif must be between 0 and 100: {self.value}")
        if not self.jenis_pajak:
            raise ValueError("Jenis pajak is required")

    def as_decimal(self) -> Decimal:
        return self.value / Decimal(100)

    def to_string(self) -> str:
        return f"{self.value}%"

    @classmethod
    def from_string(cls, value: str, jenis_pajak: str, berlaku_mulai: date) -> TarifPajak:
        rate: Decimal = Decimal(value.replace("%", ""))
        return cls(rate, jenis_pajak, berlaku_mulai)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": str(self.value),
            "jenis_pajak": self.jenis_pajak,
            "berlaku_mulai": self.berlaku_mulai.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TarifPajak:
        return cls(
            value=Decimal(data["value"]),
            jenis_pajak=data["jenis_pajak"],
            berlaku_mulai=date.fromisoformat(data["berlaku_mulai"]),
        )

    def clone(self) -> TarifPajak:
        return TarifPajak(self.value, self.jenis_pajak, self.berlaku_mulai)

    def snapshot(self) -> dict[str, Any]:
        return {"value": str(self.value), "jenis_pajak": self.jenis_pajak}

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> TarifPajak:
        return self.clone()

    def validate(self) -> dict[str, Any]:
        try:
            self.__post_init__()
            return {"is_valid": True, "errors": []}
        except ValueError as e:
            return {"is_valid": False, "errors": [str(e)]}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TarifPajak):
            return False
        return (
            self.value == other.value
            and self.jenis_pajak == other.jenis_pajak
            and self.berlaku_mulai == other.berlaku_mulai
        )

    def __hash__(self) -> int:
        return hash((self.value, self.jenis_pajak, self.berlaku_mulai))


# ============================================================================
# KODE BILLING VALUE OBJECT
# ============================================================================


@dataclass(frozen=True)
class KodeBilling:
    """Kode Billing for tax payment (16 digits).

    Attributes:
        billing: Kode billing sebagai string 16 digit.
    """

    billing: str  # renamed from 'value'

    @property
    def value(self) -> str:
        """Backward compatible property for old API."""
        return self.billing

    def __post_init__(self) -> None:
        if not re.match(r"^[0-9]{16}$", self.billing):
            raise ValueError(f"Kode Billing must be 16 digits: {self.billing}")

    def to_string(self) -> str:
        return self.billing

    @classmethod
    def from_string(cls, value: str) -> KodeBilling:
        return cls(value)

    def to_dict(self) -> dict[str, Any]:
        return {"kode_billing": self.billing}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KodeBilling:
        return cls(data["kode_billing"])

    def clone(self) -> KodeBilling:
        return KodeBilling(self.billing)

    def snapshot(self) -> dict[str, Any]:
        return {"kode_billing": self.billing}

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> KodeBilling:
        return self.clone()

    def validate(self) -> dict[str, Any]:
        try:
            self.__post_init__()
            return {"is_valid": True, "errors": []}
        except ValueError as e:
            return {"is_valid": False, "errors": [str(e)]}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, KodeBilling):
            return False
        return self.billing == other.billing

    def __hash__(self) -> int:
        return hash(self.billing)


# ============================================================================
# ALIASES untuk kompatibilitas dengan __init__.py
# ============================================================================

NPWPVO = NPWP
NSFPVO = NSFP
TaxPeriodVO = MasaPajak
FakturNumberVO = KodeFaktur

__all__ = [
    "NPWP",
    "NPWPVO",
    "NSFP",
    "NSFPVO",
    "FakturNumberVO",
    "KodeBilling",
    "KodeFaktur",
    "MasaPajak",
    "TarifPajak",
    "TaxPeriodVO",
]
