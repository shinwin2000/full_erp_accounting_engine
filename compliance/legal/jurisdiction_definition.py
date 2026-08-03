#!/usr/bin/env python3
"""
Module: jurisdiction_definition.py
Layer: Compliance / Legal

Responsibility:
    Mendefinisikan yurisdiksi hukum, termasuk sistem hukum, regulator utama,
    standar akuntansi, mata uang, bahasa pelaporan, dan aturan spesifik untuk
    setiap negara/region. Mendukung pencarian yurisdiksi berdasarkan kode,
    nama, atau kriteria, serta menyediakan validasi terhadap aturan lintas
    batas (cross-border).

Dependencies:
    - datetime, typing, enum, hashlib, json, logging

Audit:
    Setiap perubahan definisi yurisdiksi dicatat (jika dimodifikasi runtime).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class LegalSystem(Enum):
    CIVIL_LAW = "civil_law"
    COMMON_LAW = "common_law"
    ISLAMIC_LAW = "islamic_law"
    CUSTOMARY_LAW = "customary_law"
    MIXED = "mixed"


class Currency(Enum):
    IDR = "IDR"
    USD = "USD"
    SGD = "SGD"
    MYR = "MYR"
    GBP = "GBP"
    EUR = "EUR"
    JPY = "JPY"
    CNY = "CNY"
    AUD = "AUD"


class Language(Enum):
    INDONESIAN = "id"
    ENGLISH = "en"
    CHINESE = "zh"
    ARABIC = "ar"
    HINDI = "hi"


# ============================================================================
# Data Classes
# ============================================================================
class Jurisdiction:
    def __init__(
        self,
        code: str,
        name: str,
        legal_system: LegalSystem,
        regulatory_bodies: list[str],
        tax_authority: str,
        accounting_standards: list[str],
        currency: Currency,
        reporting_language: Language,
        fiscal_year_start_month: int = 1,  # 1=Januari
        is_treaty_member: bool = False,
        parent_jurisdiction: str | None = None,  # for hierarchical (e.g., EU -> member states)
    ):
        self.code = code
        self.name = name
        self.legal_system = legal_system
        self.regulatory_bodies = regulatory_bodies
        self.tax_authority = tax_authority
        self.accounting_standards = accounting_standards
        self.currency = currency
        self.reporting_language = reporting_language
        self.fiscal_year_start_month = fiscal_year_start_month
        self.is_treaty_member = is_treaty_member
        self.parent_jurisdiction = parent_jurisdiction
        self.created_at = datetime.utcnow().isoformat()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "code": self.code,
            "name": self.name,
            "legal_system": self.legal_system.value,
            "currency": self.currency.value,
            "accounting_standards": self.accounting_standards,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "legal_system": self.legal_system.value,
            "regulatory_bodies": self.regulatory_bodies,
            "tax_authority": self.tax_authority,
            "accounting_standards": self.accounting_standards,
            "currency": self.currency.value,
            "reporting_language": self.reporting_language.value,
            "fiscal_year_start_month": self.fiscal_year_start_month,
            "is_treaty_member": self.is_treaty_member,
            "parent_jurisdiction": self.parent_jurisdiction,
            "hash": self._hash,
        }


# ============================================================================
# JurisdictionDefinition Core
# ============================================================================
class JurisdictionDefinition:
    """
    Mendefinisikan dan mengelola yurisdiksi hukum untuk kepatuhan global.
    """

    def __init__(self):
        self._jurisdictions: dict[str, Jurisdiction] = {}
        self._init_jurisdictions()

    def _init_jurisdictions(self) -> None:
        """Inisialisasi data yurisdiksi default (bisa diperluas dari file eksternal)."""
        jurisdictions = [
            Jurisdiction(
                code="ID",
                name="Indonesia",
                legal_system=LegalSystem.CIVIL_LAW,
                regulatory_bodies=["OJK", "DJP", "BI", "KPPU"],
                tax_authority="DJP (Direktorat Jenderal Pajak)",
                accounting_standards=["PSAK", "SAK ETAP", "SAK UMKM"],
                currency=Currency.IDR,
                reporting_language=Language.INDONESIAN,
                fiscal_year_start_month=1,
                is_treaty_member=True,
            ),
            Jurisdiction(
                code="SG",
                name="Singapore",
                legal_system=LegalSystem.COMMON_LAW,
                regulatory_bodies=["MAS", "IRAS", "ACRA"],
                tax_authority="IRAS (Inland Revenue Authority of Singapore)",
                accounting_standards=["SFRS", "SFRS for Small Entities"],
                currency=Currency.SGD,
                reporting_language=Language.ENGLISH,
                fiscal_year_start_month=4,  # typical SG fiscal year April-March
                is_treaty_member=True,
            ),
            Jurisdiction(
                code="US",
                name="United States",
                legal_system=LegalSystem.COMMON_LAW,
                regulatory_bodies=["SEC", "FASB", "IRS", "PCAOB"],
                tax_authority="IRS (Internal Revenue Service)",
                accounting_standards=["US GAAP"],
                currency=Currency.USD,
                reporting_language=Language.ENGLISH,
                fiscal_year_start_month=1,
                is_treaty_member=False,  # Not all treaties; but many
            ),
            Jurisdiction(
                code="UK",
                name="United Kingdom",
                legal_system=LegalSystem.COMMON_LAW,
                regulatory_bodies=["FRC", "HMRC", "PRA"],
                tax_authority="HMRC (HM Revenue & Customs)",
                accounting_standards=["UK GAAP", "IFRS (adopted)"],
                currency=Currency.GBP,
                reporting_language=Language.ENGLISH,
                fiscal_year_start_month=4,
                is_treaty_member=True,
            ),
            Jurisdiction(
                code="MY",
                name="Malaysia",
                legal_system=LegalSystem.MIXED,  # Common law + Islamic
                regulatory_bodies=["SC", "IRB", "BNM"],
                tax_authority="IRB (Inland Revenue Board)",
                accounting_standards=["MFRS", "MPERS"],
                currency=Currency.MYR,
                reporting_language=Language.ENGLISH,
                fiscal_year_start_month=1,
                is_treaty_member=True,
            ),
            Jurisdiction(
                code="AU",
                name="Australia",
                legal_system=LegalSystem.COMMON_LAW,
                regulatory_bodies=["ASIC", "ATO", "APRA"],
                tax_authority="ATO (Australian Taxation Office)",
                accounting_standards=["AASB (IFRS aligned)"],
                currency=Currency.AUD,
                reporting_language=Language.ENGLISH,
                fiscal_year_start_month=7,
                is_treaty_member=True,
            ),
            Jurisdiction(
                code="JP",
                name="Japan",
                legal_system=LegalSystem.CIVIL_LAW,
                regulatory_bodies=["FSA", "NTA", "JICPA"],
                tax_authority="NTA (National Tax Agency)",
                accounting_standards=["J-GAAP", "IFRS (voluntary)"],
                currency=Currency.JPY,
                reporting_language=Language.ENGLISH,  # or Japanese; simplified
                fiscal_year_start_month=4,
                is_treaty_member=True,
            ),
            Jurisdiction(
                code="CN",
                name="China",
                legal_system=LegalSystem.CIVIL_LAW,
                regulatory_bodies=["CSRC", "SAT", "MOF"],
                tax_authority="SAT (State Administration of Taxation)",
                accounting_standards=["CAS", "IFRS converged"],
                currency=Currency.CNY,
                reporting_language=Language.CHINESE,
                fiscal_year_start_month=1,
                is_treaty_member=True,
            ),
        ]
        for j in jurisdictions:
            self._jurisdictions[j.code] = j

    def add_jurisdiction(self, jurisdiction: Jurisdiction) -> None:
        self._jurisdictions[jurisdiction.code] = jurisdiction

    def get_jurisdiction(self, code: str) -> Jurisdiction | None:
        return self._jurisdictions.get(code.upper())

    def get_by_name(self, name: str) -> Jurisdiction | None:
        name_lower = name.lower()
        for j in self._jurisdictions.values():
            if j.name.lower() == name_lower:
                return j
        return None

    def get_all(self) -> list[Jurisdiction]:
        return list(self._jurisdictions.values())

    def get_supported_codes(self) -> list[str]:
        return list(self._jurisdictions.keys())

    def is_supported(self, code: str) -> bool:
        return code.upper() in self._jurisdictions

    def validate_cross_border(
        self, from_code: str, to_code: str, data_type: str = "personal_data"
    ) -> tuple[bool, list[str]]:
        """
        Validasi apakah transfer data atau transaksi lintas yurisdiksi diperbolehkan.
        """
        warnings = []
        from_jur = self.get_jurisdiction(from_code)
        to_jur = self.get_jurisdiction(to_code)
        if not from_jur or not to_jur:
            return False, ["One or both jurisdictions not recognized"]

        # Rule: Data pribadi ke luar negeri memerlukan kepatuhan khusus
        if data_type == "personal_data" and from_code == "ID" and to_code not in ["SG", "US"]:
            warnings.append(
                f"Transfer of personal data from {from_code} to {to_code} may require special approval (UU PDP)"
            )

        # Rule: Financial transaction ke negara non-treaty
        if data_type == "financial_transaction" and not to_jur.is_treaty_member:
            warnings.append("Tax treaty may not apply, withholding tax at higher rate")

        # Jika tidak ada larangan eksplisit, dianggap diizinkan dengan catatan
        return True, warnings

    def export_to_json(self, file_path: str) -> None:
        data = {
            "total": len(self._jurisdictions),
            "jurisdictions": [j.to_dict() for j in self._jurisdictions.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    jur_def = JurisdictionDefinition()
    indo = jur_def.get_jurisdiction("ID")
    print(f"Indonesia: {indo.name}, currency: {indo.currency.value}")
    allowed, warns = jur_def.validate_cross_border("ID", "US", "personal_data")
    print(f"Cross-border allowed: {allowed}, warnings: {warns}")
    jur_def.export_to_json("jurisdictions.json")
