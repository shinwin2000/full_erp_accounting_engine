#!/usr/bin/env python3
# Code quality fix: removed any placeholder 'XXX' markers.

"""
Module: npwp_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for NPWP (Nomor Pokok Wajib Pajak) - Indonesian Taxpayer
    Identification Number.

    FIX (audit 2026-09-14): dua masalah serius ditemukan di versi
    sebelumnya, keduanya menyebabkan NPWP ASLI/VALID milik user ditolak
    sistem (log produksi menunjukkan 422 berulang untuk NPWP yang sudah
    benar):

    1. Format 16-digit TIDAK didukung sama sekali (LENGTH dipaksa 15).
       Padahal sejak 1 Juli 2024, DJP resmi memberlakukan NPWP 16 digit
       (PMK 112/PMK.03/2022 jo. PER-06/PJ/2024) - NPWP badan/instansi
       16-digit = angka "0" + NPWP lama 15 digit; NPWP orang pribadi
       WNI 16-digit = NIK. NPWP 15 digit masih berlaku sebagai
       peninggalan/legacy, tapi 16 digit sekarang adalah format standar.
       -> LENGTH sekarang menerima 15 ATAU 16 digit.

    2. Check-digit modulo-11 sebelumnya di sini di-KLAIM mengacu ke
       "PER-04/PJ/2020" dengan tabel bobot tertentu, dan enforcement-nya
       BERSIFAT WAJIB (menolak NPWP yang tidak lolos). Setelah ditelusuri
       ulang, referensi itu tidak ditemukan sumber resminya, dan sumber
       yang ada (mis. pustaka open-source Business::ID::NPWP)
       menyebutnya "apparently" pakai algoritma Luhn/modulo-10 - artinya
       DJP TIDAK PERNAH mempublikasikan algoritma check-digit resmi, dan
       tidak ada satupun implementasi pihak ketiga yang bisa dipastikan
       benar. Memblokir input berdasarkan algoritma yang tidak terverifikasi
       ini justru menolak NPWP asli yang sah (sudah terjadi di produksi).
       -> Check digit TIDAK lagi memblokir; method verifikasinya
          dipertahankan hanya sebagai INFORMASI (best-effort, non-fatal),
          bukan syarat lolos/tidak.

    Struktur NPWP 15-digit lama (badan usaha):
    - 2 digit : kode KPP (kantor pajak)
    - 2 digit : kode golongan usaha
    - 1 digit : kode internal (biasa 0)
    - 6 digit : nomor urut
    - 1 digit : check digit (algoritma tidak terverifikasi resmi - lihat di atas)

    NPWP 16-digit badan/instansi = "0" + 15 digit di atas.
    NPWP 16-digit orang pribadi WNI = NIK (16 digit, struktur Dukcapil,
    tidak mengikuti pola KPP di atas sama sekali).

    Features:
    - Validasi format (15 atau 16 digit numerik).
    - Automatic formatting untuk NPWP 15-digit: 00.000.000.0-000.000
    - Extraction of tax office, entity type, and branch info (untuk
      bagian 15-digit legacy/badan; NIK 16-digit tidak diekstrak).
    - Immutable, hashable, comparable.
    - Audit logging on creation.

Dependencies:
    - Python standard library (re, logging)

Audit:
    Each NPWP creation is logged with the formatted version for audit trail.
    No external calls; all validation is deterministic.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import ClassVar

logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================


class NPWPValidationError(ValueError):
    """Raised when NPWP string fails validation."""

    pass


# ============================================================================
# Value Object: NPWP
# ============================================================================


@dataclass(frozen=True, slots=True)
class NPWP:
    """
    Indonesian Taxpayer Identification Number.

    Format (raw): 15 digit (legacy) ATAU 16 digit (standar sejak 1 Juli
    2024 - lihat catatan modul di atas).
    Format (display, khusus 15-digit / bagian legacy dari 16-digit
    badan): 00.000.000.0-000.000

    Validation rules:
    1. Tepat 15 ATAU 16 digit numerik.
    2. Untuk NPWP 15-digit, atau 16-digit yang diawali "0" (format badan/
       instansi = "0" + 15 digit lama): dua digit pertama dari bagian
       15-digit-nya divalidasi terhadap daftar kode KPP.
    3. NPWP 16-digit yang TIDAK diawali "0" diperlakukan sebagai NIK
       (format orang pribadi WNI) - tidak divalidasi lebih lanjut selain
       panjang & harus numerik, karena strukturnya milik Dukcapil bukan
       DJP.
    4. Check digit TIDAK memblokir (lihat catatan modul: algoritmanya
       tidak pernah dipastikan resmi oleh DJP). `check_digit_plausible()`
       tersedia untuk info tambahan saja, bukan syarat valid/tidak.

    Examples:
        >>> npwp = NPWP("123456789012345")
        >>> npwp.formatted()
        '12.345.678.9-012.345'
        >>> npwp.tax_office_code()
        '12'
        >>> NPWP("0123456789012345").compact()  # format badan 16-digit
        '0123456789012345'
    """

    # Class constants
    LENGTH_LEGACY: ClassVar[int] = 15
    LENGTH_CURRENT: ClassVar[int] = 16
    VALID_PREFIXES: ClassVar[set[str]] = {
        "01",
        "02",
        "03",
        "04",
        "05",
        "07",
        "09",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
        "19",
        "20",
        "21",
        "22",
        "23",
        "24",
        "25",
        "26",
        "27",
        "28",
        "29",
        "30",
        "31",
        "32",
        "33",
        "34",
        "35",
        "36",
        "37",
        "38",
        "39",
        "40",
        "41",
        "42",
        "43",
        "44",
        "45",
        "46",
        "47",
        "48",
        "49",
        "50",
        "51",
        "52",
        "53",
        "54",
        "55",
        "56",
        "57",
        "58",
        "59",
        "60",
        "61",
        "62",
        "63",
        "64",
        "65",
        "66",
        "67",
        "68",
        "69",
        "70",
        "71",
        "72",
        "73",
        "74",
        "75",
        "76",
        "77",
        "78",
        "79",
        "80",
        "81",
        "82",
        "83",
        "84",
        "85",
        "86",
        "87",
        "88",
        "89",
        "90",
        "91",
        "92",
        "93",
        "94",
        "95",
        "96",
        "97",
        "98",
        "99",
    }

    _value: str  # normalized 15-digit string

    def __init__(self, value: str | int, strict_prefix: bool = True) -> None:
        """
        Initialize NPWP.

        Args:
            value: Raw NPWP as string or integer (with or without separators).
            strict_prefix: If True, validate tax office code prefix.

        Raises:
            NPWPValidationError: If validation fails.
        """
        object.__setattr__(self, "_value", self._normalize_and_validate(value, strict_prefix))
        logger.debug(f"NPWP created: {self.formatted()} (strict_prefix={strict_prefix})")

    # ------------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------------

    @classmethod
    def _normalize_and_validate(cls, raw: str | int, strict_prefix: bool) -> str:
        raw_str = str(raw).strip()
        # Remove all non-digit characters (dots, spaces, dashes)
        cleaned = re.sub(r"[^\d]", "", raw_str)

        if len(cleaned) not in (cls.LENGTH_LEGACY, cls.LENGTH_CURRENT):
            raise NPWPValidationError(
                f"NPWP must be {cls.LENGTH_LEGACY} digits (format lama) atau "
                f"{cls.LENGTH_CURRENT} digits (format standar sejak Juli 2024). "
                f"Got {len(cleaned)} digits from '{raw_str}'"
            )

        if not cleaned.isdigit():
            raise NPWPValidationError(f"NPWP must contain only digits. Got '{cleaned}'")

        # Untuk 16-digit: kalau diawali "0", ini format badan/instansi
        # ("0" + 15 digit lama) - bagian 15-digitnya masih bisa dicek
        # terhadap kode KPP. Kalau TIDAK diawali "0", ini NIK (16 digit
        # orang pribadi WNI) - strukturnya milik Dukcapil, bukan pola KPP
        # DJP, jadi tidak diperiksa lebih lanjut.
        legacy_body: str | None = None
        if len(cleaned) == cls.LENGTH_LEGACY:
            legacy_body = cleaned
        elif len(cleaned) == cls.LENGTH_CURRENT and cleaned[0] == "0":
            legacy_body = cleaned[1:]

        if strict_prefix and legacy_body is not None:
            prefix = legacy_body[:2]
            if prefix not in cls.VALID_PREFIXES:
                raise NPWPValidationError(
                    f"Invalid NPWP prefix '{prefix}'. Must be one of KPP codes (01-05,07,09-99)."
                )

        # Check digit SENGAJA tidak memblokir - lihat catatan di docstring
        # modul: algoritmanya tidak pernah dipastikan resmi oleh DJP, dan
        # memblokir berdasarkan itu terbukti menolak NPWP asli yang sah.
        # `check_digit_plausible()` tetap tersedia untuk info non-fatal.

        return cleaned

    @classmethod
    def check_digit_plausible(cls, digits: str) -> bool | None:
        """
        Cek check-digit modulo-11 secara INFORMASIONAL SAJA - TIDAK dipakai
        untuk menolak NPWP (lihat catatan di docstring modul: algoritma ini
        tidak pernah dipastikan sebagai standar resmi DJP, sumber yang ada
        malah menyebut kemungkinan Luhn/modulo-10, bukan modulo-11).

        Kembalikan None kalau tidak berlaku dihitung (mis. NIK 16-digit
        yang tidak berformat "0" + 15 digit lama).
        """
        legacy_body: str | None = None
        if len(digits) == cls.LENGTH_LEGACY:
            legacy_body = digits
        elif len(digits) == cls.LENGTH_CURRENT and digits[0] == "0":
            legacy_body = digits[1:]
        if legacy_body is None:
            return None

        weights = [2, 3, 4, 5, 6, 7, 8, 9, 10, 2, 3, 4, 5, 6]
        total = sum(int(legacy_body[i]) * weights[i] for i in range(14))

        remainder = total % 11
        expected_check = 0 if remainder == 1 else 11 - remainder
        actual_check = int(legacy_body[14])
        return actual_check == expected_check

    # ------------------------------------------------------------------------
    # Public Properties & Methods
    # ------------------------------------------------------------------------

    @property
    def value(self) -> str:
        """Return raw 15-digit NPWP string."""
        return self._value

    def __str__(self) -> str:
        return self.formatted()

    def __repr__(self) -> str:
        return f"NPWP('{self._value}')"

    def _legacy_body(self) -> str | None:
        """15-digit legacy body dipakai untuk semua accessor di bawah.
        None kalau NPWP ini NIK 16-digit (tidak punya struktur KPP)."""
        if len(self._value) == self.LENGTH_LEGACY:
            return self._value
        if len(self._value) == self.LENGTH_CURRENT and self._value[0] == "0":
            return self._value[1:]
        return None

    def is_nik_based(self) -> bool:
        """True kalau ini NPWP 16-digit berbasis NIK (orang pribadi WNI),
        bukan format badan/instansi ("0" + 15 digit lama)."""
        return self._legacy_body() is None

    def formatted(self) -> str:
        """
        Return NPWP dalam format tampilan standar: 00.000.000.0-000.000
        (format lama, 15 digit). Untuk NPWP 16-digit badan ("0" + 15
        digit lama), bagian 15-digitnya yang diformat, dengan awalan "0"
        ditampilkan terpisah. Untuk NIK 16-digit, dikembalikan apa adanya
        (NIK tidak punya format titik/strip DJP).
        Example: "12.345.678.9-012.345"
        """
        body = self._legacy_body()
        if body is None:
            return self._value
        formatted_body = f"{body[:2]}.{body[2:5]}.{body[5:8]}.{body[8]}-{body[9:12]}.{body[12:]}"
        if len(self._value) == self.LENGTH_CURRENT:
            return f"0{formatted_body}"
        return formatted_body

    def compact(self) -> str:
        """Return without any separators (raw digits)."""
        return self._value

    def tax_office_code(self) -> str | None:
        """Return first two digits (KPP code). None kalau NIK-based."""
        body = self._legacy_body()
        return body[:2] if body else None

    def entity_code(self) -> str | None:
        """Return digits 3-5 (entity type / business group). None kalau NIK-based."""
        body = self._legacy_body()
        return body[2:5] if body else None

    def internal_code(self) -> str | None:
        """Return digit 9 (usually 0 for head office, 1 for branch, etc.).
        None kalau NIK-based."""
        body = self._legacy_body()
        return body[8] if body else None

    def serial_number(self) -> str | None:
        """Return digits 10-14 (serial part). None kalau NIK-based."""
        body = self._legacy_body()
        return body[9:14] if body else None

    def is_head_office(self) -> bool:
        """Return True if internal_code == '0' (head office). False kalau NIK-based."""
        return self.internal_code() == "0"

    def to_json(self) -> dict[str, str]:
        """Serialise to JSON."""
        return {
            "value": self._value,
            "formatted": self.formatted(),
            "tax_office_code": self.tax_office_code() or "",
            "entity_code": self.entity_code() or "",
            "is_head_office": str(self.is_head_office()),  # Convert bool to str
            "is_nik_based": str(self.is_nik_based()),
        }

    @classmethod
    def from_json(cls, data: dict[str, str]) -> NPWP:
        """Reconstruct NPWP from JSON."""
        return cls(data["value"])

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NPWP):
            return False
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __lt__(self, other: NPWP) -> bool:
        return int(self._value) < int(other._value)

    # ------------------------------------------------------------------------
    # Alternative Constructors
    # ------------------------------------------------------------------------

    @classmethod
    def from_formatted(cls, formatted: str) -> NPWP:
        """
        Create NPWP from formatted string (with dots/dashes).

        Example: "12.345.678.9-012.345" -> NPWP("123456789012345")
        """
        cleaned = re.sub(r"[^\d]", "", formatted)
        return cls(cleaned)

    @classmethod
    def for_testing(cls, base: str = "123456789012345") -> NPWP:
        """
        Generate a valid NPWP for testing purposes only.

        The provided base must be 15 digits with correct check digit,
        otherwise a valid one is generated.

        Args:
            base: A 15-digit candidate.

        Returns:
            A guaranteed valid NPWP.
        """
        if len(base) == 15 and base.isdigit():
            try:
                return cls(base)
            except NPWPValidationError:
                # Fix check digit
                base_digits = list(base[:14])
                total = 0
                weights = [2, 3, 4, 5, 6, 7, 8, 9, 10, 2, 3, 4, 5, 6]
                for i in range(14):
                    total += int(base_digits[i]) * weights[i]
                remainder = total % 11
                new_check = 0 if remainder == 1 else 11 - remainder
                return cls(base[:14] + str(new_check))
        # Fallback to a valid test NPWP
        return cls._generate_valid_test_npwp()

    @classmethod
    def _generate_valid_test_npwp(cls) -> NPWP:
        """Generate a completely valid test NPWP."""
        import random

        random.seed(42)
        prefix = random.choice(list(cls.VALID_PREFIXES))
        rest = [str(random.randint(0, 9)) for _ in range(12)]
        candidate = prefix + "".join(rest)
        total = 0
        weights = [2, 3, 4, 5, 6, 7, 8, 9, 10, 2, 3, 4, 5, 6]
        for i in range(14):
            total += int(candidate[i]) * weights[i]
        remainder = total % 11
        check = 0 if remainder == 1 else 11 - remainder
        return cls(candidate + str(check))


# ============================================================================
# Aliases for backward compatibility
# ============================================================================
NPWPVO = NPWP


# ============================================================================
# Helper Functions
# ============================================================================


def validate_npwp_string(raw: str) -> bool:
    """Quick validation without creating object."""
    try:
        NPWP(raw)
        return True
    except NPWPValidationError:
        return False


def normalize_npwp(raw: str | int) -> str:
    """Remove all non-digit characters."""
    return re.sub(r"[^\d]", "", str(raw))


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "NPWP",
    "NPWPVO",
    "NPWPValidationError",
    "normalize_npwp",
    "validate_npwp_string",
]
