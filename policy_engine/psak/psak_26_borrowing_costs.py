#!/usr/bin/env python3
"""
Module: psak_26_borrowing_costs.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 26: Biaya Pinjaman (setara dengan IAS 23).
    Mengatur perlakuan akuntansi untuk biaya pinjaman (bunga dan biaya terkait
    lainnya) yang dapat diatribusikan secara langsung dengan perolehan,
    konstruksi, atau produksi aset kualifikasian (qualifying asset).
    Biaya pinjaman tersebut harus dikapitalisasi sebagai bagian dari biaya
    aset, bukan dibebankan pada periode berjalan. Aset kualifikasian memerlukan
    waktu yang cukup lama (substantial period) untuk siap digunakan atau dijual.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap biaya pinjaman yang dikapitalisasi dan perhitungannya dicatat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class PSAK26QualifyingAssetType(Enum):
    INVENTORY = "persediaan"
    PROPERTY_PLANT_EQUIPMENT = "aset_tetap"
    INTANGIBLE_ASSET = "aset_tak_berwujud"
    INVESTMENT_PROPERTY = "properti_investasi"
    OTHER = "lainnya"


class PSAK26BorrowingCostType(Enum):
    INTEREST = "bunga"
    FINANCE_CHARGES = "biaya_keuangan"
    EXCHANGE_DIFFERENCE = (
        "selisih_kurs"  # Bagian yang terkait dengan pinjaman dalam mata uang asing
    )


class PSAK26CapitalizationMethod(Enum):
    SPECIFIC_BORROWINGS = "pinjaman_spesifik"
    GENERAL_BORROWINGS = "pinjaman_umum"
    WEIGHTED_AVERAGE = "rata_rata_tertimbang"


class PSAK26ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK26Error(Exception):
    pass


class NoQualifyingAssetError(PSAK26Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK26Borrowing:
    """Pinjaman individual."""

    borrowing_id: UUID
    principal: Decimal
    annual_interest_rate: Decimal  # dalam persen (misal 10 untuk 10%)
    start_date: datetime
    end_date: datetime | None = None
    is_specific_to_asset: bool = False  # Jika pinjaman khusus untuk aset tertentu
    specific_asset_id: UUID | None = None
    borrowing_type: PSAK26BorrowingCostType = PSAK26BorrowingCostType.INTEREST

    def interest_for_period(self, start: datetime, end: datetime) -> Decimal:
        """Menghitung bunga untuk periode tertentu (prorata)."""
        if self.end_date and self.end_date < start:
            return Decimal(0)
        period_start = max(start, self.start_date)
        period_end = min(end, self.end_date) if self.end_date else end
        if period_end <= period_start:
            return Decimal(0)
        days = (period_end - period_start).days
        years = Decimal(days) / Decimal(365)
        return (self.principal * (self.annual_interest_rate / 100) * years).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    def to_dict(self) -> dict:
        return {
            "borrowing_id": str(self.borrowing_id),
            "principal": str(self.principal),
            "annual_interest_rate": str(self.annual_interest_rate),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "is_specific": self.is_specific_to_asset,
        }


@dataclass
class PSAK26QualifyingAsset:
    """Aset kualifikasian."""

    asset_id: UUID
    asset_name: str
    asset_type: PSAK26QualifyingAssetType
    construction_start_date: datetime
    construction_end_date: datetime | None = None
    total_expenditures: Decimal = Decimal(0)
    capitalized_borrowing_costs: Decimal = Decimal(0)
    specific_borrowings: list[UUID] = field(default_factory=list)  # borrowing ids
    is_active: bool = True

    def eligible_period(self, reference_date: datetime) -> bool:
        """Apakah aset masih dalam periode kapitalisasi."""
        if not self.is_active:
            return False
        if self.construction_end_date and reference_date > self.construction_end_date:
            return False
        return reference_date >= self.construction_start_date

    def to_dict(self) -> dict:
        return {
            "asset_id": str(self.asset_id),
            "asset_name": self.asset_name,
            "asset_type": self.asset_type.value,
            "construction_start": self.construction_start_date.isoformat(),
            "construction_end": self.construction_end_date.isoformat()
            if self.construction_end_date
            else None,
            "total_expenditures": str(self.total_expenditures),
            "capitalized_costs": str(self.capitalized_borrowing_costs),
            "is_active": self.is_active,
        }


@dataclass
class PSAK26CapitalizationCalculation:
    """Hasil perhitungan kapitalisasi biaya pinjaman untuk suatu periode."""

    calculation_id: UUID
    period_start: datetime
    period_end: datetime
    eligible_assets: list[PSAK26QualifyingAsset] = field(default_factory=list)
    total_capitalizable_cost: Decimal = Decimal(0)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "calculation_id": str(self.calculation_id),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "total_capitalizable_cost": str(self.total_capitalizable_cost),
            "details": self.details,
        }


@dataclass
class PSAK26ValidationResult:
    is_compliant: bool
    compliance_level: PSAK26ComplianceLevel
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hash_sha256: str = ""

    def __post_init__(self):
        self.hash_sha256 = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "is_compliant": self.is_compliant,
            "level": self.compliance_level.value,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False
        if self.compliance_level != PSAK26ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK26ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK26ComplianceLevel.FULL:
            self.compliance_level = PSAK26ComplianceLevel.SUBSTANTIAL

    def to_dict(self) -> dict:
        return {
            "is_compliant": self.is_compliant,
            "compliance_level": self.compliance_level.value,
            "errors": self.errors,
            "warnings": self.warnings,
            "hash": self.hash_sha256,
        }


# ============================================================================
# Domain Services
# ============================================================================
class PSAK26BorrowingCostService:
    """Service untuk kapitalisasi biaya pinjaman."""

    @staticmethod
    def is_qualifying_asset(
        asset_type: PSAK26QualifyingAssetType, construction_period_years: float
    ) -> bool:
        """Memeriksa apakah aset termasuk aset kualifikasian (memerlukan waktu substansial)."""
        # Biasanya lebih dari 12 bulan dianggap substansial
        return construction_period_years >= 1

    @staticmethod
    def calculate_capitalization_rate(
        borrowings: list[PSAK26Borrowing], period_start: datetime, period_end: datetime
    ) -> Decimal:
        """Menghitung tingkat kapitalisasi rata-rata tertimbang untuk pinjaman umum."""
        total_interest = Decimal(0)
        total_principal = Decimal(0)
        for b in borrowings:
            if b.is_specific_to_asset:
                continue
            interest = b.interest_for_period(period_start, period_end)
            total_interest += interest
            # Untuk principal, gunakan rata-rata tertimbang selama periode
            total_principal += b.principal
        if total_principal == 0:
            return Decimal(0)
        return (total_interest / total_principal * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @staticmethod
    def capitalize_for_asset(
        asset: PSAK26QualifyingAsset,
        specific_borrowings: list[PSAK26Borrowing],
        general_borrowings: list[PSAK26Borrowing],
        period_start: datetime,
        period_end: datetime,
        capitalization_rate: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Menghitung biaya pinjaman yang dapat dikapitalisasi untuk satu aset."""
        total = Decimal(0)
        # 1. Specific borrowings
        for b in specific_borrowings:
            if b.borrowing_id in asset.specific_borrowings:
                total += b.interest_for_period(period_start, period_end)
        # 2. General borrowings: dikapitalisasi sebesar expenditure dikalikan capitalization rate
        expenditure = asset.total_expenditures
        if expenditure > 0:
            from_general = (expenditure * (capitalization_rate / 100)).quantize(
                Decimal("0"), rounding=ROUND_HALF_EVEN
            )
            # Tidak boleh melebihi total biaya pinjaman umum yang sebenarnya
            total_actual_general = sum(
                b.interest_for_period(period_start, period_end) for b in general_borrowings
            )
            total += min(from_general, total_actual_general)
        # Batasi total tidak melebihi akumulasi expenditure (tidak praktis)
        return total, expenditure

    @staticmethod
    def calculate_weighted_average_expenditure(
        expenditures: list[tuple[datetime, Decimal]],
    ) -> Decimal:
        """Menghitung rata-rata tertimbang pengeluaran selama periode."""
        if not expenditures:
            return Decimal(0)
        # Asumsikan periode referensi dari awal hingga akhir
        total_weighted = Decimal(0)
        total_days = 0
        if len(expenditures) >= 2:
            start = expenditures[0][0]
            end = expenditures[-1][0]
            total_days = (end - start).days
            if total_days <= 0:
                total_days = 1
        else:
            total_days = 365
        for i in range(1, len(expenditures)):
            prev_date, prev_amt = expenditures[i - 1]
            cur_date, _ = expenditures[i]
            days = (cur_date - prev_date).days
            total_weighted += prev_amt * Decimal(days)
        # Tambahkan pengeluaran terakhir sampai akhir periode (asumsikan sisa)
        # Untuk penyederhanaan, return expenditure terakhir
        return expenditures[-1][1] if expenditures else Decimal(0)


# ============================================================================
# Rules
# ============================================================================
class PSAK26Rules:
    """Aturan PSAK 26."""

    @staticmethod
    def validate_qualifying_asset(asset: PSAK26QualifyingAsset) -> PSAK26ValidationResult:
        result = PSAK26ValidationResult(
            is_compliant=True, compliance_level=PSAK26ComplianceLevel.FULL
        )
        if not PSAK26BorrowingCostService.is_qualifying_asset(asset.asset_type, 1):
            result.add_warning(
                f"Aset {asset.asset_name} mungkin bukan aset kualifikasian karena periode konstruksi tidak substansial"
            )
        if asset.total_expenditures < 0:
            result.add_error("Total pengeluaran tidak boleh negatif")
        return result

    @staticmethod
    def validate_capitalization(
        calculation: PSAK26CapitalizationCalculation,
    ) -> PSAK26ValidationResult:
        result = PSAK26ValidationResult(
            is_compliant=True, compliance_level=PSAK26ComplianceLevel.FULL
        )
        if calculation.total_capitalizable_cost < 0:
            result.add_error("Biaya kapitalisasi tidak boleh negatif")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK26Validator:
    def __init__(self):
        self._rules = PSAK26Rules()
        self._service = PSAK26BorrowingCostService()

    def create_borrowing(
        self,
        principal: Decimal,
        annual_interest_rate: Decimal,
        start_date: datetime,
        end_date: datetime | None = None,
        is_specific_to_asset: bool = False,
        specific_asset_id: UUID | None = None,
    ) -> PSAK26Borrowing:
        return PSAK26Borrowing(
            borrowing_id=uuid4(),
            principal=principal,
            annual_interest_rate=annual_interest_rate,
            start_date=start_date,
            end_date=end_date,
            is_specific_to_asset=is_specific_to_asset,
            specific_asset_id=specific_asset_id,
        )

    def create_qualifying_asset(
        self,
        asset_name: str,
        asset_type: PSAK26QualifyingAssetType,
        construction_start_date: datetime,
        construction_end_date: datetime | None = None,
        total_expenditures: Decimal = Decimal(0),
    ) -> PSAK26QualifyingAsset:
        return PSAK26QualifyingAsset(
            asset_id=uuid4(),
            asset_name=asset_name,
            asset_type=asset_type,
            construction_start_date=construction_start_date,
            construction_end_date=construction_end_date,
            total_expenditures=total_expenditures,
        )

    def add_expenditure(
        self, asset: PSAK26QualifyingAsset, amount: Decimal, date: datetime
    ) -> PSAK26QualifyingAsset:
        return PSAK26QualifyingAsset(
            asset_id=asset.asset_id,
            asset_name=asset.asset_name,
            asset_type=asset.asset_type,
            construction_start_date=asset.construction_start_date,
            construction_end_date=asset.construction_end_date,
            total_expenditures=asset.total_expenditures + amount,
            capitalized_borrowing_costs=asset.capitalized_borrowing_costs,
            specific_borrowings=asset.specific_borrowings,
            is_active=asset.is_active,
        )

    def link_specific_borrowing(
        self, asset: PSAK26QualifyingAsset, borrowing_id: UUID
    ) -> PSAK26QualifyingAsset:
        new_list = [*asset.specific_borrowings, borrowing_id]
        return PSAK26QualifyingAsset(
            asset_id=asset.asset_id,
            asset_name=asset.asset_name,
            asset_type=asset.asset_type,
            construction_start_date=asset.construction_start_date,
            construction_end_date=asset.construction_end_date,
            total_expenditures=asset.total_expenditures,
            capitalized_borrowing_costs=asset.capitalized_borrowing_costs,
            specific_borrowings=new_list,
            is_active=asset.is_active,
        )

    def complete_construction(
        self, asset: PSAK26QualifyingAsset, completion_date: datetime
    ) -> PSAK26QualifyingAsset:
        return PSAK26QualifyingAsset(
            asset_id=asset.asset_id,
            asset_name=asset.asset_name,
            asset_type=asset.asset_type,
            construction_start_date=asset.construction_start_date,
            construction_end_date=completion_date,
            total_expenditures=asset.total_expenditures,
            capitalized_borrowing_costs=asset.capitalized_borrowing_costs,
            specific_borrowings=asset.specific_borrowings,
            is_active=False,
        )

    def calculate_capitalization(
        self,
        assets: list[PSAK26QualifyingAsset],
        borrowings: list[PSAK26Borrowing],
        period_start: datetime,
        period_end: datetime,
    ) -> PSAK26CapitalizationCalculation:
        eligible_assets = [a for a in assets if a.eligible_period(period_end)]
        if not eligible_assets:
            return PSAK26CapitalizationCalculation(
                calculation_id=uuid4(),
                period_start=period_start,
                period_end=period_end,
            )

        general_borrowings = [b for b in borrowings if not b.is_specific_to_asset]
        specific_borrowings = [b for b in borrowings if b.is_specific_to_asset]
        cap_rate = self._service.calculate_capitalization_rate(
            general_borrowings, period_start, period_end
        )

        total_capitalizable = Decimal(0)
        details = {}
        for asset in eligible_assets:
            cap_cost, exp = self._service.capitalize_for_asset(
                asset, specific_borrowings, general_borrowings, period_start, period_end, cap_rate
            )
            total_capitalizable += cap_cost
            details[asset.asset_name] = {
                "expenditure": str(exp),
                "capitalizable_cost": str(cap_cost),
            }

        return PSAK26CapitalizationCalculation(
            calculation_id=uuid4(),
            period_start=period_start,
            period_end=period_end,
            eligible_assets=eligible_assets,
            total_capitalizable_cost=total_capitalizable,
            details=details,
        )

    def validate_assets(self, assets: list[PSAK26QualifyingAsset]) -> PSAK26ValidationResult:
        result = PSAK26ValidationResult(
            is_compliant=True, compliance_level=PSAK26ComplianceLevel.FULL
        )
        for a in assets:
            result = self._merge_results(result, self._rules.validate_qualifying_asset(a))
        return result

    def _merge_results(
        self, main: PSAK26ValidationResult, other: PSAK26ValidationResult
    ) -> PSAK26ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK26ComplianceLevel.FULL,
            PSAK26ComplianceLevel.SUBSTANTIAL,
            PSAK26ComplianceLevel.PARTIAL,
            PSAK26ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "qualifying_asset": "Aset yang memerlukan waktu substansial (biasanya >12 bulan) untuk siap digunakan atau dijual",
            "borrowing_costs": "Termasuk bunga, biaya keuangan, dan selisih kurs yang terkait dengan pinjaman",
            "capitalization": "Biaya pinjaman yang dapat diatribusikan secara langsung harus dikapitalisasi",
            "specific_borrowings": "Untuk pinjaman khusus, gunakan tingkat bunga aktual",
            "general_borrowings": "Untuk pinjaman umum, gunakan tingkat kapitalisasi rata-rata tertimbang",
            "suspension": "Kapitalisasi ditangguhkan jika aktivitas konstruksi terhenti untuk periode yang panjang",
            "cease": "Kapitalisasi berhenti ketika aset siap digunakan",
            "disclosures": [
                "Kebijakan akuntansi biaya pinjaman",
                "Jumlah biaya pinjaman yang dikapitalisasi selama periode",
                "Tingkat kapitalisasi yang digunakan",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak26_validator_instance: PSAK26Validator | None = None


def get_psak26_validator() -> PSAK26Validator:
    global _psak26_validator_instance
    if _psak26_validator_instance is None:
        _psak26_validator_instance = PSAK26Validator()
    return _psak26_validator_instance


# ============================================================================
# Aliases for backward compatibility (FIX: resolves import errors)
# ============================================================================
# Alias untuk class utama
BorrowingCostCapitalization = PSAK26CapitalizationCalculation
BorrowingCosts = PSAK26Borrowing

# Alias untuk enum types
BorrowingCostType = PSAK26BorrowingCostType
QualifyingAssetType = PSAK26QualifyingAssetType

# Ekspos semua nama yang mungkin dibutuhkan
__all__ = [
    "BorrowingCostCapitalization",
    "BorrowingCostType",
    "BorrowingCosts",
    "PSAK26Borrowing",
    "PSAK26BorrowingCostService",
    "PSAK26BorrowingCostType",
    "PSAK26CapitalizationCalculation",
    "PSAK26CapitalizationMethod",
    "PSAK26ComplianceLevel",
    "PSAK26QualifyingAsset",
    "PSAK26QualifyingAssetType",
    "PSAK26Rules",
    "PSAK26ValidationResult",
    "PSAK26Validator",
    "QualifyingAssetType",
    "get_psak26_validator",
]

# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak26_validator()

    # Create borrowings
    specific_loan = validator.create_borrowing(
        principal=Decimal("1000000000"),
        annual_interest_rate=Decimal("8"),
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        end_date=datetime(2026, 12, 31, tzinfo=UTC),
        is_specific_to_asset=True,
    )
    general_loan1 = validator.create_borrowing(
        principal=Decimal("500000000"),
        annual_interest_rate=Decimal("10"),
        start_date=datetime(2025, 1, 1, tzinfo=UTC),
    )
    general_loan2 = validator.create_borrowing(
        principal=Decimal("300000000"),
        annual_interest_rate=Decimal("9"),
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
    )
    borrowings = [specific_loan, general_loan1, general_loan2]

    # Create qualifying asset
    asset = validator.create_qualifying_asset(
        asset_name="Gedung Pabrik",
        asset_type=PSAK26QualifyingAssetType.PROPERTY_PLANT_EQUIPMENT,
        construction_start_date=datetime(2026, 1, 1, tzinfo=UTC),
        construction_end_date=datetime(2026, 12, 31, tzinfo=UTC),
    )
    # Add expenditures
    asset = validator.add_expenditure(asset, Decimal("200000000"), datetime(2026, 2, 1, tzinfo=UTC))
    asset = validator.add_expenditure(asset, Decimal("300000000"), datetime(2026, 5, 1, tzinfo=UTC))
    asset = validator.add_expenditure(asset, Decimal("400000000"), datetime(2026, 8, 1, tzinfo=UTC))
    asset = validator.add_expenditure(
        asset, Decimal("100000000"), datetime(2026, 11, 1, tzinfo=UTC)
    )
    # Link specific borrowing
    asset = validator.link_specific_borrowing(asset, specific_loan.borrowing_id)

    # Calculate capitalization for period
    calc = validator.calculate_capitalization(
        assets=[asset],
        borrowings=borrowings,
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 12, 31, tzinfo=UTC),
    )
    print("Capitalization Calculation:")
    print(json.dumps(calc.to_dict(), indent=2, default=str))

    # Validate assets
    result = validator.validate_assets([asset])
    print("\nValidation Result:")
    print(json.dumps(result.to_dict(), indent=2))

    # Complete construction (stop capitalization)
    asset_completed = validator.complete_construction(asset, datetime(2026, 12, 31, tzinfo=UTC))
    print("\nAsset after completion (inactive):", asset_completed.is_active)
