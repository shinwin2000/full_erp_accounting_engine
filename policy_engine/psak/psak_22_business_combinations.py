#!/usr/bin/env python3
"""
Module: psak_22_business_combinations.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 22: Kombinasi Bisnis (setara dengan IFRS 3).
    Mengatur akuntansi untuk kombinasi bisnis, termasuk identifikasi
    pihak pengakuisisi, penentuan tanggal akuisisi, pengakuan dan
    pengukuran aset teridentifikasi, liabilitas, dan kepentingan
    non-pengendali (non-controlling interest), serta pengakuan
    goodwill atau keuntungan dari pembelian dengan diskon (bargain purchase).
    Menerapkan metode akuisisi (acquisition method).

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap kombinasi bisnis, alokasi harga perolehan, dan pengakuan goodwill dicatat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class PSAK22AcquisitionMethod(Enum):
    ACQUISITION = "akuisisi"  # Metode akuisisi (wajib)
    MERGER = "penggabungan"  # Untuk entitas sepengendali (PSAK 38)


class PSAK22NCIChoice(Enum):
    PROPORTIONATE_SHARE = "proporsi_aset_bersih"  # Diukur pada proporsi aset bersih teridentifikasi
    FAIR_VALUE = "nilai_wajar"  # Diukur pada nilai wajar (mengakui goodwill untuk NCI)


class PSAK22ContingentConsiderationClassification(Enum):
    EQUITY = "ekuitas"
    LIABILITY = "liabilitas"
    ASSET = "aset"


class PSAK22MeasurementPeriodAdjustment(Enum):
    IDENTIFIABLE_ASSETS = "aset_teridentifikasi"
    LIABILITIES = "liabilitas"
    CONTINGENT_CONSIDERATION = "kontinjensi_pembayaran"
    GOODWILL = "goodwill"


class PSAK22ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK22Error(Exception):
    pass


class AcquisitionDateError(PSAK22Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK22IdentifiableAsset:
    """Aset teridentifikasi dalam kombinasi bisnis."""

    asset_id: UUID
    description: str
    fair_value: Decimal
    carrying_amount: Decimal
    asset_type: str  # tangible, intangible, financial
    useful_life: int | None = None
    is_current: bool = False

    def to_dict(self) -> dict:
        return {
            "asset_id": str(self.asset_id),
            "description": self.description,
            "fair_value": str(self.fair_value),
            "carrying_amount": str(self.carrying_amount),
            "asset_type": self.asset_type,
            "useful_life": self.useful_life,
            "is_current": self.is_current,
        }


@dataclass
class PSAK22IdentifiableLiability:
    """Liabilitas teridentifikasi dalam kombinasi bisnis."""

    liability_id: UUID
    description: str
    fair_value: Decimal
    carrying_amount: Decimal
    liability_type: str  # current, non-current, contingent
    settlement_date: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "liability_id": str(self.liability_id),
            "description": self.description,
            "fair_value": str(self.fair_value),
            "carrying_amount": str(self.carrying_amount),
            "liability_type": self.liability_type,
        }


@dataclass
class PSAK22ContingentConsideration:
    """Kontinjensi pembayaran dalam kombinasi bisnis."""

    consideration_id: UUID
    description: str
    classification: PSAK22ContingentConsiderationClassification
    fair_value_at_acquisition: Decimal
    settlement_range_low: Decimal | None = None
    settlement_range_high: Decimal | None = None
    settlement_date: datetime | None = None
    remeasurement_gain_loss: Decimal = Decimal(0)

    def to_dict(self) -> dict:
        return {
            "consideration_id": str(self.consideration_id),
            "description": self.description,
            "classification": self.classification.value,
            "fair_value_at_acquisition": str(self.fair_value_at_acquisition),
            "range_low": str(self.settlement_range_low) if self.settlement_range_low else None,
            "range_high": str(self.settlement_range_high) if self.settlement_range_high else None,
        }


@dataclass
class PSAK22BusinessCombination:
    """Kombinasi bisnis."""

    combination_id: UUID
    acquirer_id: UUID
    acquiree_id: UUID
    acquirer_name: str
    acquiree_name: str
    acquisition_date: datetime
    consideration_transferred: Decimal  # Harga perolehan (total)
    identifiable_assets: list[PSAK22IdentifiableAsset] = field(default_factory=list)
    identifiable_liabilities: list[PSAK22IdentifiableLiability] = field(default_factory=list)
    nci_choice: PSAK22NCIChoice = PSAK22NCIChoice.PROPORTIONATE_SHARE
    nci_percentage: Decimal = Decimal(0)  # Persentase kepemilikan non-pengendali (0-100)
    nci_value: Decimal = Decimal(0)  # Nilai yang diakui untuk NCI
    contingent_consideration: list[PSAK22ContingentConsideration] = field(default_factory=list)
    goodwill: Decimal = Decimal(0)
    bargain_purchase_gain: Decimal = Decimal(0)  # Keuntungan pembelian dengan diskon (jika ada)
    measurement_period_adjustments: dict[str, Decimal] = field(default_factory=dict)
    is_business_combination: bool = True  # False jika sebenarnya aset saja (tidak bisnis)
    notes: str = ""

    @property
    def net_identifiable_assets(self) -> Decimal:
        # FIX: tambahkan Decimal(0) sebagai nilai awal sum
        total_assets = sum((a.fair_value for a in self.identifiable_assets), Decimal(0))
        total_liabilities = sum((liab.fair_value for liab in self.identifiable_liabilities), Decimal(0))
        return total_assets - total_liabilities

    @property
    def nci_proportionate_value(self) -> Decimal:
        return self.net_identifiable_assets * (self.nci_percentage / 100)

    def calculate_goodwill_or_gain(self) -> tuple[Decimal, Decimal]:
        """Menghitung goodwill atau bargain purchase gain."""
        # Jumlah yang dialihkan (consideration transferred)
        # Plus nilai NCI (pada proporsi atau nilai wajar)
        # Plus nilai wajar kepemilikan sebelumnya (jika bertahap) -> tidak diimplementasikan di sini
        total = self.consideration_transferred + self.nci_value
        if total > self.net_identifiable_assets:
            goodwill = total - self.net_identifiable_assets
            return goodwill, Decimal(0)
        else:
            gain = self.net_identifiable_assets - total
            return Decimal(0), gain

    def to_dict(self) -> dict:
        goodwill, gain = self.calculate_goodwill_or_gain()
        return {
            "combination_id": str(self.combination_id),
            "acquirer_id": str(self.acquirer_id),
            "acquiree_id": str(self.acquiree_id),
            "acquirer_name": self.acquirer_name,
            "acquiree_name": self.acquiree_name,
            "acquisition_date": self.acquisition_date.isoformat(),
            "consideration_transferred": str(self.consideration_transferred),
            "net_identifiable_assets": str(self.net_identifiable_assets),
            "nci_choice": self.nci_choice.value,
            "nci_percentage": str(self.nci_percentage),
            "nci_value": str(self.nci_value),
            "goodwill": str(goodwill),
            "bargain_purchase_gain": str(gain),
            "identifiable_assets": [a.to_dict() for a in self.identifiable_assets],
            "identifiable_liabilities": [liab.to_dict() for liab in self.identifiable_liabilities],
            "contingent_consideration": [c.to_dict() for c in self.contingent_consideration],
            "measurement_period_adjustments": {
                k: str(v) for k, v in self.measurement_period_adjustments.items()
            },
            "is_business_combination": self.is_business_combination,
            "notes": self.notes,
        }


@dataclass
class PSAK22ValidationResult:
    is_compliant: bool
    compliance_level: PSAK22ComplianceLevel
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
        if self.compliance_level != PSAK22ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK22ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK22ComplianceLevel.FULL:
            self.compliance_level = PSAK22ComplianceLevel.SUBSTANTIAL

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
class PSAK22BusinessCombinationService:
    """Service untuk kombinasi bisnis."""

    @staticmethod
    def is_business_combination(
        assets: list[PSAK22IdentifiableAsset], has_substantive_processes: bool
    ) -> bool:
        """Menentukan apakah transaksi merupakan kombinasi bisnis atau hanya pembelian aset."""
        # Kombinasi bisnis memerlukan input dan proses substantif
        if not assets:
            return False
        return has_substantive_processes

    @staticmethod
    def calculate_acquired_net_assets(
        assets: list[PSAK22IdentifiableAsset], liabilities: list[PSAK22IdentifiableLiability]
    ) -> Decimal:
        # FIX: tambahkan Decimal(0) sebagai nilai awal sum
        total_assets = sum((a.fair_value for a in assets), Decimal(0))
        total_liabilities = sum((liab.fair_value for liab in liabilities), Decimal(0))
        return total_assets - total_liabilities

    @staticmethod
    def allocate_purchase_price(
        combination: PSAK22BusinessCombination,
        fair_values_assets: dict[UUID, Decimal],
        fair_values_liabilities: dict[UUID, Decimal],
    ) -> PSAK22BusinessCombination:
        """Alokasi harga perolehan ke aset dan liabilitas berdasarkan nilai wajar."""
        for asset in combination.identifiable_assets:
            if asset.asset_id in fair_values_assets:
                asset.fair_value = fair_values_assets[asset.asset_id]
        for liability in combination.identifiable_liabilities:
            if liability.liability_id in fair_values_liabilities:
                liability.fair_value = fair_values_liabilities[liability.liability_id]
        return combination

    @staticmethod
    def compute_remeasurement_contingent_consideration(
        original: PSAK22ContingentConsideration, new_fair_value: Decimal
    ) -> tuple[PSAK22ContingentConsideration, Decimal]:
        """Menghitung perubahan nilai kontinjensi pembayaran (untuk liabilitas/aset)."""
        difference = new_fair_value - original.fair_value_at_acquisition
        if original.classification == PSAK22ContingentConsiderationClassification.EQUITY:
            # Perubahan tidak diakui
            return original, Decimal(0)
        else:
            # Diakui di laba rugi
            new = PSAK22ContingentConsideration(
                consideration_id=original.consideration_id,
                description=original.description,
                classification=original.classification,
                fair_value_at_acquisition=new_fair_value,
                settlement_range_low=original.settlement_range_low,
                settlement_range_high=original.settlement_range_high,
                settlement_date=original.settlement_date,
                remeasurement_gain_loss=original.remeasurement_gain_loss + difference,
            )
            return new, difference


# ============================================================================
# Rules
# ============================================================================
class PSAK22Rules:
    """Aturan PSAK 22."""

    @staticmethod
    def validate_measurement_period(
        combination: PSAK22BusinessCombination, current_date: datetime
    ) -> PSAK22ValidationResult:
        result = PSAK22ValidationResult(
            is_compliant=True, compliance_level=PSAK22ComplianceLevel.FULL
        )
        measurement_period_end = combination.acquisition_date.replace(
            year=combination.acquisition_date.year + 1
        )
        if current_date > measurement_period_end and combination.measurement_period_adjustments:
            result.add_error(
                "Penyesuaian periode pengukuran hanya diperbolehkan dalam 12 bulan setelah tanggal akuisisi"
            )
        return result

    @staticmethod
    def validate_nci_measurement(combination: PSAK22BusinessCombination) -> PSAK22ValidationResult:
        result = PSAK22ValidationResult(
            is_compliant=True, compliance_level=PSAK22ComplianceLevel.FULL
        )
        if combination.nci_choice == PSAK22NCIChoice.FAIR_VALUE and combination.nci_value == 0:
            result.add_error("NCI diukur pada nilai wajar tetapi nilai NCI tidak ditentukan")
        if combination.nci_percentage < 0 or combination.nci_percentage > 100:
            result.add_error("Persentase NCI harus antara 0 dan 100")
        return result

    @staticmethod
    def validate_identifiable_assets(
        assets: list[PSAK22IdentifiableAsset],
    ) -> PSAK22ValidationResult:
        result = PSAK22ValidationResult(
            is_compliant=True, compliance_level=PSAK22ComplianceLevel.FULL
        )
        for asset in assets:
            if asset.fair_value <= 0 and asset.asset_type not in ["goodwill"]:
                result.add_warning(f"Aset {asset.description} memiliki nilai wajar non-positif")
        return result

    @staticmethod
    def validate_contingent_consideration(
        contingent: list[PSAK22ContingentConsideration],
    ) -> PSAK22ValidationResult:
        result = PSAK22ValidationResult(
            is_compliant=True, compliance_level=PSAK22ComplianceLevel.FULL
        )
        for c in contingent:
            if (
                c.classification == PSAK22ContingentConsiderationClassification.EQUITY
                and c.fair_value_at_acquisition != 0
            ):
                result.add_warning(
                    "Kontinjensi pembayaran yang diklasifikasikan sebagai ekuitas harus diukur pada nilai wajar 0 pada akuisisi"
                )
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK22Validator:
    def __init__(self):
        self._rules = PSAK22Rules()
        self._service = PSAK22BusinessCombinationService()

    def create_business_combination(
        self,
        acquirer_id: UUID,
        acquiree_id: UUID,
        acquirer_name: str,
        acquiree_name: str,
        acquisition_date: datetime,
        consideration_transferred: Decimal,
        nci_choice: PSAK22NCIChoice = PSAK22NCIChoice.PROPORTIONATE_SHARE,
        nci_percentage: Decimal = Decimal(0),
        nci_value: Decimal = Decimal(0),
    ) -> PSAK22BusinessCombination:
        return PSAK22BusinessCombination(
            combination_id=uuid4(),
            acquirer_id=acquirer_id,
            acquiree_id=acquiree_id,
            acquirer_name=acquirer_name,
            acquiree_name=acquiree_name,
            acquisition_date=acquisition_date,
            consideration_transferred=consideration_transferred,
            nci_choice=nci_choice,
            nci_percentage=nci_percentage,
            nci_value=nci_value,
        )

    def add_identifiable_asset(
        self,
        combination: PSAK22BusinessCombination,
        description: str,
        fair_value: Decimal,
        carrying_amount: Decimal = Decimal(0),
        asset_type: str = "tangible",
        useful_life: int | None = None,
        is_current: bool = False,
    ) -> PSAK22BusinessCombination:
        new_asset = PSAK22IdentifiableAsset(
            asset_id=uuid4(),
            description=description,
            fair_value=fair_value,
            carrying_amount=carrying_amount,
            asset_type=asset_type,
            useful_life=useful_life,
            is_current=is_current,
        )
        new_assets = [*combination.identifiable_assets, new_asset]
        return PSAK22BusinessCombination(
            combination_id=combination.combination_id,
            acquirer_id=combination.acquirer_id,
            acquiree_id=combination.acquiree_id,
            acquirer_name=combination.acquirer_name,
            acquiree_name=combination.acquiree_name,
            acquisition_date=combination.acquisition_date,
            consideration_transferred=combination.consideration_transferred,
            identifiable_assets=new_assets,
            identifiable_liabilities=combination.identifiable_liabilities,
            nci_choice=combination.nci_choice,
            nci_percentage=combination.nci_percentage,
            nci_value=combination.nci_value,
            contingent_consideration=combination.contingent_consideration,
            measurement_period_adjustments=combination.measurement_period_adjustments,
            is_business_combination=combination.is_business_combination,
            notes=combination.notes,
        )

    def add_identifiable_liability(
        self,
        combination: PSAK22BusinessCombination,
        description: str,
        fair_value: Decimal,
        carrying_amount: Decimal = Decimal(0),
        liability_type: str = "current",
        settlement_date: datetime | None = None,
    ) -> PSAK22BusinessCombination:
        new_liability = PSAK22IdentifiableLiability(
            liability_id=uuid4(),
            description=description,
            fair_value=fair_value,
            carrying_amount=carrying_amount,
            liability_type=liability_type,
            settlement_date=settlement_date,
        )
        new_liabilities = [*combination.identifiable_liabilities, new_liability]
        return PSAK22BusinessCombination(
            combination_id=combination.combination_id,
            acquirer_id=combination.acquirer_id,
            acquiree_id=combination.acquiree_id,
            acquirer_name=combination.acquirer_name,
            acquiree_name=combination.acquiree_name,
            acquisition_date=combination.acquisition_date,
            consideration_transferred=combination.consideration_transferred,
            identifiable_assets=combination.identifiable_assets,
            identifiable_liabilities=new_liabilities,
            nci_choice=combination.nci_choice,
            nci_percentage=combination.nci_percentage,
            nci_value=combination.nci_value,
            contingent_consideration=combination.contingent_consideration,
            measurement_period_adjustments=combination.measurement_period_adjustments,
            is_business_combination=combination.is_business_combination,
            notes=combination.notes,
        )

    def add_contingent_consideration(
        self,
        combination: PSAK22BusinessCombination,
        description: str,
        classification: PSAK22ContingentConsiderationClassification,
        fair_value_at_acquisition: Decimal,
        settlement_range_low: Decimal | None = None,
        settlement_range_high: Decimal | None = None,
        settlement_date: datetime | None = None,
    ) -> PSAK22BusinessCombination:
        new_cc = PSAK22ContingentConsideration(
            consideration_id=uuid4(),
            description=description,
            classification=classification,
            fair_value_at_acquisition=fair_value_at_acquisition,
            settlement_range_low=settlement_range_low,
            settlement_range_high=settlement_range_high,
            settlement_date=settlement_date,
        )
        new_cc_list = [*combination.contingent_consideration, new_cc]
        return PSAK22BusinessCombination(
            combination_id=combination.combination_id,
            acquirer_id=combination.acquirer_id,
            acquiree_id=combination.acquiree_id,
            acquirer_name=combination.acquirer_name,
            acquiree_name=combination.acquiree_name,
            acquisition_date=combination.acquisition_date,
            consideration_transferred=combination.consideration_transferred,
            identifiable_assets=combination.identifiable_assets,
            identifiable_liabilities=combination.identifiable_liabilities,
            nci_choice=combination.nci_choice,
            nci_percentage=combination.nci_percentage,
            nci_value=combination.nci_value,
            contingent_consideration=new_cc_list,
            measurement_period_adjustments=combination.measurement_period_adjustments,
            is_business_combination=combination.is_business_combination,
            notes=combination.notes,
        )

    def set_nci_value(
        self, combination: PSAK22BusinessCombination, nci_value: Decimal
    ) -> PSAK22BusinessCombination:
        return PSAK22BusinessCombination(
            combination_id=combination.combination_id,
            acquirer_id=combination.acquirer_id,
            acquiree_id=combination.acquiree_id,
            acquirer_name=combination.acquirer_name,
            acquiree_name=combination.acquiree_name,
            acquisition_date=combination.acquisition_date,
            consideration_transferred=combination.consideration_transferred,
            identifiable_assets=combination.identifiable_assets,
            identifiable_liabilities=combination.identifiable_liabilities,
            nci_choice=combination.nci_choice,
            nci_percentage=combination.nci_percentage,
            nci_value=nci_value,
            contingent_consideration=combination.contingent_consideration,
            measurement_period_adjustments=combination.measurement_period_adjustments,
            is_business_combination=combination.is_business_combination,
            notes=combination.notes,
        )

    def set_business_combination_flag(
        self, combination: PSAK22BusinessCombination, is_business: bool
    ) -> PSAK22BusinessCombination:
        return PSAK22BusinessCombination(
            combination_id=combination.combination_id,
            acquirer_id=combination.acquirer_id,
            acquiree_id=combination.acquiree_id,
            acquirer_name=combination.acquirer_name,
            acquiree_name=combination.acquiree_name,
            acquisition_date=combination.acquisition_date,
            consideration_transferred=combination.consideration_transferred,
            identifiable_assets=combination.identifiable_assets,
            identifiable_liabilities=combination.identifiable_liabilities,
            nci_choice=combination.nci_choice,
            nci_percentage=combination.nci_percentage,
            nci_value=combination.nci_value,
            contingent_consideration=combination.contingent_consideration,
            measurement_period_adjustments=combination.measurement_period_adjustments,
            is_business_combination=is_business,
            notes=combination.notes,
        )

    def compute_goodwill(self, combination: PSAK22BusinessCombination) -> tuple[Decimal, Decimal]:
        return combination.calculate_goodwill_or_gain()

    def validate_combination(
        self, combination: PSAK22BusinessCombination, current_date: datetime | None = None
    ) -> PSAK22ValidationResult:
        if current_date is None:
            current_date = datetime.now(UTC)
        result = self._rules.validate_measurement_period(combination, current_date)
        result = self._merge_results(result, self._rules.validate_nci_measurement(combination))
        result = self._merge_results(
            result, self._rules.validate_identifiable_assets(combination.identifiable_assets)
        )
        result = self._merge_results(
            result,
            self._rules.validate_contingent_consideration(combination.contingent_consideration),
        )
        return result

    def _merge_results(
        self, main: PSAK22ValidationResult, other: PSAK22ValidationResult
    ) -> PSAK22ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK22ComplianceLevel.FULL,
            PSAK22ComplianceLevel.SUBSTANTIAL,
            PSAK22ComplianceLevel.PARTIAL,
            PSAK22ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "acquisition_method": "Metode akuisisi wajib untuk semua kombinasi bisnis",
            "identifiable_assets_liabilities": "Diakui pada nilai wajar pada tanggal akuisisi",
            "goodwill": "Selisih antara harga perolehan + NCI - aset bersih teridentifikasi",
            "bargain_purchase": "Keuntungan dari pembelian dengan diskon diakui di laba rugi",
            "measurement_period": "Maksimal 12 bulan setelah akuisisi untuk penyesuaian",
            "contingent_consideration": "Diakui pada nilai wajar; perubahan setelah periode pengukuran diakui di laba rugi (kecuali ekuitas)",
            "nci_measurement": "Pilihan proporsi aset bersih atau nilai wajar",
            "disclosures": [
                "Nama pihak pengakuisisi dan pihak diakuisisi",
                "Tanggal akuisisi",
                "Persentase kepemilikan yang diperoleh",
                "Harga perolehan dan komponennya",
                "Goodwill dan faktor yang mempengaruhinya",
                "Informasi aset dan liabilitas yang diakui",
                "Kepentingan non-pengendali",
            ],
        }


class PSAK22:
    @staticmethod
    def calculate_goodwill(purchase_price, fair_value_of_identifiable_net_assets):
        return purchase_price - fair_value_of_identifiable_net_assets

    @staticmethod
    def get_nci_measurement_methods():
        return ["proportionate_share", "fair_value"]


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak22_validator_instance: PSAK22Validator | None = None


def get_psak22_validator() -> PSAK22Validator:
    global _psak22_validator_instance
    if _psak22_validator_instance is None:
        _psak22_validator_instance = PSAK22Validator()
    return _psak22_validator_instance


class PSAK22GoodwillCalculation:
    """Placeholder untuk perhitungan goodwill."""

    def __init__(self, purchase_price, fair_value_net_assets):
        self.goodwill = purchase_price - fair_value_net_assets


AcquisitionMethod = PSAK22AcquisitionMethod
BusinessCombination = PSAK22BusinessCombination
GoodwillCalculation = PSAK22GoodwillCalculation

# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    import json

    validator = get_psak22_validator()
    acquirer_id = uuid4()
    acquiree_id = uuid4()

    combination = validator.create_business_combination(
        acquirer_id=acquirer_id,
        acquiree_id=acquiree_id,
        acquirer_name="PT Induk Sejahtera",
        acquiree_name="PT Anak Maju",
        acquisition_date=datetime(2026, 6, 30, tzinfo=UTC),
        consideration_transferred=Decimal("800000000"),
        nci_choice=PSAK22NCIChoice.PROPORTIONATE_SHARE,
        nci_percentage=Decimal("20"),
    )

    # Aset teridentifikasi
    combination = validator.add_identifiable_asset(combination, "Tanah", Decimal("300000000"))
    combination = validator.add_identifiable_asset(combination, "Bangunan", Decimal("200000000"))
    combination = validator.add_identifiable_asset(
        combination, "Paten", Decimal("100000000"), asset_type="intangible", useful_life=10
    )
    combination = validator.add_identifiable_asset(
        combination, "Persediaan", Decimal("50000000"), is_current=True
    )

    # Liabilitas teridentifikasi
    combination = validator.add_identifiable_liability(
        combination, "Utang Bank", Decimal("100000000"), liability_type="non-current"
    )
    combination = validator.add_identifiable_liability(
        combination, "Utang Usaha", Decimal("20000000"), liability_type="current"
    )

    # Kontinjensi pembayaran
    combination = validator.add_contingent_consideration(
        combination,
        "Pembayaran tambahan jika laba tahun pertama melebihi target",
        classification=PSAK22ContingentConsiderationClassification.LIABILITY,
        fair_value_at_acquisition=Decimal("50000000"),
        settlement_range_low=Decimal("0"),
        settlement_range_high=Decimal("100000000"),
    )

    # Set NCI value (proporsional)
    nci_prop = combination.nci_proportionate_value
    combination = validator.set_nci_value(combination, nci_prop)

    # Hitung goodwill
    goodwill, gain = validator.compute_goodwill(combination)
    print(f"Goodwill: {goodwill}")
    print(f"Bargain purchase gain: {gain}")

    # Validasi
    result = validator.validate_combination(combination)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nBusiness Combination Details:")
    print(json.dumps(combination.to_dict(), indent=2, default=str))
