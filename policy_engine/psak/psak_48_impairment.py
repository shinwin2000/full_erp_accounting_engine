#!/usr/bin/env python3
"""
Module: psak_48_impairment.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 48: Penurunan Nilai Aset (setara dengan IAS 36).
    Mengatur prosedur yang harus diterapkan entitas untuk memastikan aset
    dicatat tidak melebihi jumlah terpulihkannya (recoverable amount).
    Jumlah terpulihkan adalah nilai tertinggi antara nilai wajar dikurangi
    biaya pelepasan (fair value less costs to sell) dan nilai pakai
    (value in use). Jika nilai tercatat aset lebih tinggi dari jumlah
    terpulihkan, selisihnya diakui sebagai kerugian penurunan nilai.
    Berlaku untuk goodwill, aset takberwujud dengan masa manfaat tidak terbatas,
    aset tetap, dan aset lainnya yang diindikasikan penurunan nilai.
    Goodwill wajib diuji penurunan nilai setiap tahun.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap uji penurunan nilai, perhitungan recoverable amount, dan pengakuan
    impairment loss dicatat dengan hash integrity.
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
class PSAK48AssetType(Enum):
    GOODWILL = "goodwill"
    INTANGIBLE_ASSET = "aset_tak_berwujud"
    PROPERTY_PLANT_EQUIPMENT = "aset_tetap"
    INVESTMENT_PROPERTY = "properti_investasi"
    RIGHT_OF_USE_ASSET = "aset_hak_guna"
    OTHER = "lainnya"


class PSAK48ImpairmentIndicator(Enum):
    EXTERNAL_DECLINE_IN_MARKET_VALUE = "penurunan_nilai_pasar_eksternal"
    EXTERNAL_SIGNIFICANT_CHANGE = "perubahan_signifikan_lingkungan_eksternal"
    EXTERNAL_INTEREST_RATE_INCREASE = "kenaikan_suku_bunga"
    INTERNAL_OBSOLESCENCE = "keusangan_fisik_atau_teknis"
    INTERNAL_ASSET_IDLE = "aset_menganggur"
    INTERNAL_ECONOMIC_PERFORMANCE_DECLINE = "penurunan_kinerja_ekonomi"
    INTERNAL_RESTRUCTURING = "restrukturisasi"
    INTERNAL_CASH_FLOW_NEGATIVE = "arus_kas_negatif"


class PSAK48CashGeneratingUnitType(Enum):
    SINGLE_ASSET = "aset_tunggal"
    GROUP_OF_ASSETS = "kelompok_aset"
    REPORTING_SEGMENT = "segmen_pelaporan"


class PSAK48ImpairmentTestTiming(Enum):
    ANNUALLY = "tahunan"  # Untuk goodwill dan intangible indefinite life
    WHEN_INDICATOR = "saat_indikasi"  # Untuk aset lain jika ada indikasi


class PSAK48ImpairmentLossAllocation(Enum):
    FIRST_TO_GOODWILL = "alokasi_pertama_goodwill"
    PRO_RATA_TO_OTHER_ASSETS = "pro_rata_ke_aset_lain"


class PSAK48ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK48Error(Exception):
    pass


class CGUNotFoundError(PSAK48Error):
    pass


class RecoverableAmountNotDeterminableError(PSAK48Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK48RecoverableAmount:
    """Jumlah terpulihkan suatu aset atau CGU."""

    fair_value_less_costs_to_sell: Decimal | None
    value_in_use: Decimal | None
    recoverable_amount: Decimal

    def __post_init__(self):
        candidates = []
        if self.fair_value_less_costs_to_sell is not None:
            candidates.append(self.fair_value_less_costs_to_sell)
        if self.value_in_use is not None:
            candidates.append(self.value_in_use)
        if not candidates:
            raise RecoverableAmountNotDeterminableError("Neither FVLCS nor VIU is available")
        self.recoverable_amount = max(candidates)

    def to_dict(self) -> dict:
        return {
            "fair_value_less_costs_to_sell": str(self.fair_value_less_costs_to_sell)
            if self.fair_value_less_costs_to_sell
            else None,
            "value_in_use": str(self.value_in_use) if self.value_in_use else None,
            "recoverable_amount": str(self.recoverable_amount),
        }


@dataclass
class PSAK48ImpairmentLoss:
    """Kerugian penurunan nilai untuk suatu aset atau CGU."""

    loss_id: UUID
    asset_id: UUID
    carrying_amount_before: Decimal
    recoverable_amount: Decimal
    impairment_loss: Decimal
    allocated_to_goodwill: Decimal = Decimal(0)
    allocated_to_other_assets: dict[UUID, Decimal] = field(default_factory=dict)
    reversal_allowed: bool = False
    reversal_amount: Decimal = Decimal(0)

    def __post_init__(self):
        self.impairment_loss = (self.carrying_amount_before - self.recoverable_amount).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )
        if self.impairment_loss < 0:
            self.impairment_loss = Decimal(0)

    def to_dict(self) -> dict:
        return {
            "loss_id": str(self.loss_id),
            "asset_id": str(self.asset_id),
            "carrying_before": str(self.carrying_amount_before),
            "recoverable_amount": str(self.recoverable_amount),
            "impairment_loss": str(self.impairment_loss),
            "allocated_to_goodwill": str(self.allocated_to_goodwill),
            "allocated_to_other_assets": {
                str(k): str(v) for k, v in self.allocated_to_other_assets.items()
            },
            "reversal_allowed": self.reversal_allowed,
            "reversal_amount": str(self.reversal_amount),
        }


@dataclass
class PSAK48CashGeneratingUnit:
    """Unit penghasil kas (CGU)."""

    cgu_id: UUID
    cgu_code: str
    name: str
    cgu_type: PSAK48CashGeneratingUnitType
    assets: list[UUID] = field(default_factory=list)  # asset ids
    allocated_goodwill: dict[UUID, Decimal] = field(
        default_factory=dict
    )  # asset_id -> goodwill amount
    carrying_amount: Decimal = Decimal(0)
    recoverable_amount: Decimal | None = None
    impairment_loss_recognized: Decimal = Decimal(0)
    value_in_use_assumptions: dict[str, Any] = field(default_factory=dict)

    def total_carrying_amount(self, asset_carrying_map: dict[UUID, Decimal]) -> Decimal:
        total = Decimal(0)
        for aid in self.assets:
            total += asset_carrying_map.get(aid, Decimal(0))
        total += sum(self.allocated_goodwill.values())
        return total

    def allocate_impairment_loss(
        self,
        loss: Decimal,
        asset_carrying_map: dict[UUID, Decimal],
        goodwill_first: bool = True,
    ) -> dict[UUID, Decimal]:
        """Mengalokasikan impairment loss ke goodwill dahulu, lalu ke aset lain proporsional."""
        allocation = {}
        remaining = loss
        if goodwill_first and self.allocated_goodwill:
            total_gw = sum(self.allocated_goodwill.values())
            gw_alloc = min(remaining, total_gw)
            # Alokasi ke masing-masing goodwill proporsional
            for aid, gw_amt in self.allocated_goodwill.items():
                share = (gw_amt / total_gw) * gw_alloc if total_gw > 0 else 0
                allocation[aid] = share.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
            remaining -= gw_alloc
        if remaining > 0:
            # Alokasi ke aset lain proporsional terhadap carrying amount (exclude goodwill)
            total_other = sum(asset_carrying_map.get(aid, Decimal(0)) for aid in self.assets)
            if total_other > 0:
                for aid in self.assets:
                    share = (asset_carrying_map.get(aid, Decimal(0)) / total_other) * remaining
                    allocation[aid] = allocation.get(aid, Decimal(0)) + share.quantize(
                        Decimal("0"), rounding=ROUND_HALF_EVEN
                    )
        return allocation

    def to_dict(self) -> dict:
        return {
            "cgu_id": str(self.cgu_id),
            "cgu_code": self.cgu_code,
            "name": self.name,
            "cgu_type": self.cgu_type.value,
            "assets": [str(a) for a in self.assets],
            "allocated_goodwill": {str(k): str(v) for k, v in self.allocated_goodwill.items()},
            "carrying_amount": str(self.carrying_amount),
            "recoverable_amount": str(self.recoverable_amount) if self.recoverable_amount else None,
            "impairment_loss": str(self.impairment_loss_recognized),
        }


@dataclass
class PSAK48ImpairmentTestResult:
    """Hasil uji penurunan nilai untuk suatu aset atau CGU."""

    test_id: UUID
    entity_id: UUID
    entity_name: str
    test_date: datetime
    asset_id: UUID
    asset_type: PSAK48AssetType
    is_cgu: bool
    carrying_amount_before: Decimal
    recoverable_amount: Decimal
    impairment_loss: Decimal
    indicators_present: list[PSAK48ImpairmentIndicator] = field(default_factory=list)
    fair_value_less_costs_to_sell: Decimal | None = None
    value_in_use: Decimal | None = None
    discount_rate_used: Decimal | None = None
    growth_rate_used: Decimal | None = None
    reversal_recognized: Decimal = Decimal(0)
    reversal_reason: str = ""

    def __post_init__(self):
        self.impairment_loss = (self.carrying_amount_before - self.recoverable_amount).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )
        if self.impairment_loss < 0:
            self.impairment_loss = Decimal(0)

    def to_dict(self) -> dict:
        return {
            "test_id": str(self.test_id),
            "entity_id": str(self.entity_id),
            "test_date": self.test_date.isoformat(),
            "asset_id": str(self.asset_id),
            "asset_type": self.asset_type.value,
            "is_cgu": self.is_cgu,
            "carrying_before": str(self.carrying_amount_before),
            "recoverable_amount": str(self.recoverable_amount),
            "impairment_loss": str(self.impairment_loss),
            "indicators": [i.value for i in self.indicators_present],
            "fvlcs": str(self.fair_value_less_costs_to_sell)
            if self.fair_value_less_costs_to_sell
            else None,
            "viu": str(self.value_in_use) if self.value_in_use else None,
            "discount_rate": str(self.discount_rate_used) if self.discount_rate_used else None,
            "reversal": str(self.reversal_recognized),
            "reversal_reason": self.reversal_reason,
        }


@dataclass
class PSAK48ValidationResult:
    is_compliant: bool
    compliance_level: PSAK48ComplianceLevel
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
        if self.compliance_level != PSAK48ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK48ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK48ComplianceLevel.FULL:
            self.compliance_level = PSAK48ComplianceLevel.SUBSTANTIAL

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
class PSAK48ImpairmentService:
    """Service untuk uji penurunan nilai."""

    @staticmethod
    def calculate_value_in_use(
        future_cash_flows: list[tuple[int, Decimal]],  # (year, cash_flow)
        discount_rate: Decimal,
        growth_rate: Decimal = Decimal(0),
        perpetual_growth_rate: Decimal = Decimal("0.02"),
    ) -> Decimal:
        """Menghitung nilai pakai (value in use) dengan diskonto arus kas masa depan."""
        pv = Decimal(0)
        for year, cf in future_cash_flows:
            discount_factor = (Decimal(1) + discount_rate / 100) ** year
            pv += cf / discount_factor
        # Terminal value (perpetuity) jika ada
        if perpetual_growth_rate > 0 and future_cash_flows:
            last_cf = future_cash_flows[-1][1]
            terminal = (
                last_cf
                * (1 + perpetual_growth_rate / 100)
                / ((discount_rate / 100) - (perpetual_growth_rate / 100))
            )
            pv += terminal / ((1 + discount_rate / 100) ** len(future_cash_flows))
        return pv.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    @staticmethod
    def calculate_fair_value_less_costs_to_sell(
        fair_value: Decimal, costs_to_sell: Decimal
    ) -> Decimal:
        return (fair_value - costs_to_sell).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    @staticmethod
    def determine_recoverable_amount(
        fvlcs: Decimal | None, viu: Decimal | None
    ) -> PSAK48RecoverableAmount:
        candidates = []
        if fvlcs is not None:
            candidates.append(fvlcs)
        if viu is not None:
            candidates.append(viu)
        if not candidates:
            raise RecoverableAmountNotDeterminableError("Cannot determine recoverable amount")
        return PSAK48RecoverableAmount(
            fair_value_less_costs_to_sell=fvlcs,
            value_in_use=viu,
            recoverable_amount=max(candidates),
        )

    @staticmethod
    def identify_impairment_indicators(
        asset_type: PSAK48AssetType,
        market_value_decline: bool,
        significant_change: bool,
        interest_rate_increase: bool,
        obsolescence: bool,
        idle_asset: bool,
        performance_decline: bool,
        cash_flow_negative: bool,
    ) -> list[PSAK48ImpairmentIndicator]:
        indicators = []
        if market_value_decline:
            indicators.append(PSAK48ImpairmentIndicator.EXTERNAL_DECLINE_IN_MARKET_VALUE)
        if significant_change:
            indicators.append(PSAK48ImpairmentIndicator.EXTERNAL_SIGNIFICANT_CHANGE)
        if interest_rate_increase:
            indicators.append(PSAK48ImpairmentIndicator.EXTERNAL_INTEREST_RATE_INCREASE)
        if obsolescence:
            indicators.append(PSAK48ImpairmentIndicator.INTERNAL_OBSOLESCENCE)
        if idle_asset:
            indicators.append(PSAK48ImpairmentIndicator.INTERNAL_ASSET_IDLE)
        if performance_decline:
            indicators.append(PSAK48ImpairmentIndicator.INTERNAL_ECONOMIC_PERFORMANCE_DECLINE)
        if cash_flow_negative:
            indicators.append(PSAK48ImpairmentIndicator.INTERNAL_CASH_FLOW_NEGATIVE)
        return indicators

    @staticmethod
    def can_reverse_impairment(asset_type: PSAK48AssetType) -> bool:
        """Apakah impairment dapat dibalik (goodwill tidak dapat dibalik)."""
        return asset_type != PSAK48AssetType.GOODWILL


# ============================================================================
# Rules
# ============================================================================
class PSAK48Rules:
    """Aturan PSAK 48."""

    @staticmethod
    def validate_annual_testing_requirement(
        asset_type: PSAK48AssetType,
        last_test_date: datetime | None,
        current_date: datetime,
    ) -> PSAK48ValidationResult:
        result = PSAK48ValidationResult(
            is_compliant=True, compliance_level=PSAK48ComplianceLevel.FULL
        )
        if asset_type in [PSAK48AssetType.GOODWILL, PSAK48AssetType.INTANGIBLE_ASSET]:
            if not last_test_date:
                result.add_error(f"{asset_type.value} harus diuji penurunan nilai setiap tahun")
            else:
                days_diff = (current_date - last_test_date).days
                if days_diff > 365:
                    result.add_error(
                        f"{asset_type.value} belum diuji penurunan nilai dalam 12 bulan"
                    )
        return result

    @staticmethod
    def validate_cgu_identification(cgu: PSAK48CashGeneratingUnit) -> PSAK48ValidationResult:
        result = PSAK48ValidationResult(
            is_compliant=True, compliance_level=PSAK48ComplianceLevel.FULL
        )
        if not cgu.assets and not cgu.allocated_goodwill:
            result.add_error("CGU tidak memiliki aset atau goodwill")
        return result

    @staticmethod
    def validate_allocation_method(
        method: PSAK48ImpairmentLossAllocation,
    ) -> PSAK48ValidationResult:
        result = PSAK48ValidationResult(
            is_compliant=True, compliance_level=PSAK48ComplianceLevel.FULL
        )
        if method != PSAK48ImpairmentLossAllocation.FIRST_TO_GOODWILL:
            result.add_warning("Alokasi impairment loss harus ke goodwill terlebih dahulu")
        return result

    @staticmethod
    def validate_disclosure(test_result: PSAK48ImpairmentTestResult) -> PSAK48ValidationResult:
        result = PSAK48ValidationResult(
            is_compliant=True, compliance_level=PSAK48ComplianceLevel.FULL
        )
        if test_result.impairment_loss > 0 and not test_result.discount_rate_used and test_result.value_in_use:
            result.add_warning("Asumsi diskonto untuk nilai pakai tidak diungkapkan")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK48Validator:
    def __init__(self):
        self._rules = PSAK48Rules()
        self._service = PSAK48ImpairmentService()

    def create_cgu(
        self,
        cgu_code: str,
        name: str,
        cgu_type: PSAK48CashGeneratingUnitType = PSAK48CashGeneratingUnitType.GROUP_OF_ASSETS,
    ) -> PSAK48CashGeneratingUnit:
        return PSAK48CashGeneratingUnit(
            cgu_id=uuid4(),
            cgu_code=cgu_code,
            name=name,
            cgu_type=cgu_type,
        )

    def add_asset_to_cgu(
        self, cgu: PSAK48CashGeneratingUnit, asset_id: UUID
    ) -> PSAK48CashGeneratingUnit:
        new_assets = [*cgu.assets, asset_id]
        return PSAK48CashGeneratingUnit(
            cgu_id=cgu.cgu_id,
            cgu_code=cgu.cgu_code,
            name=cgu.name,
            cgu_type=cgu.cgu_type,
            assets=new_assets,
            allocated_goodwill=cgu.allocated_goodwill,
            carrying_amount=cgu.carrying_amount,
            recoverable_amount=cgu.recoverable_amount,
            impairment_loss_recognized=cgu.impairment_loss_recognized,
        )

    def allocate_goodwill_to_cgu(
        self, cgu: PSAK48CashGeneratingUnit, asset_id: UUID, goodwill_amount: Decimal
    ) -> PSAK48CashGeneratingUnit:
        new_gw = cgu.allocated_goodwill.copy()
        new_gw[asset_id] = goodwill_amount
        return PSAK48CashGeneratingUnit(
            cgu_id=cgu.cgu_id,
            cgu_code=cgu.cgu_code,
            name=cgu.name,
            cgu_type=cgu.cgu_type,
            assets=cgu.assets,
            allocated_goodwill=new_gw,
            carrying_amount=cgu.carrying_amount,
            recoverable_amount=cgu.recoverable_amount,
            impairment_loss_recognized=cgu.impairment_loss_recognized,
        )

    def calculate_value_in_use(
        self,
        future_cash_flows: list[tuple[int, Decimal]],
        discount_rate: Decimal,
        growth_rate: Decimal = Decimal(0),
        perpetual_growth_rate: Decimal = Decimal("0.02"),
    ) -> Decimal:
        return self._service.calculate_value_in_use(
            future_cash_flows, discount_rate, growth_rate, perpetual_growth_rate
        )

    def calculate_fair_value_less_costs_to_sell(
        self, fair_value: Decimal, costs_to_sell: Decimal
    ) -> Decimal:
        return self._service.calculate_fair_value_less_costs_to_sell(fair_value, costs_to_sell)

    def determine_recoverable_amount(
        self, fvlcs: Decimal | None, viu: Decimal | None
    ) -> PSAK48RecoverableAmount:
        return self._service.determine_recoverable_amount(fvlcs, viu)

    def perform_impairment_test(
        self,
        entity_id: UUID,
        entity_name: str,
        asset_id: UUID,
        asset_type: PSAK48AssetType,
        carrying_amount: Decimal,
        is_cgu: bool,
        fvlcs: Decimal | None = None,
        viu: Decimal | None = None,
        discount_rate: Decimal | None = None,
        growth_rate: Decimal | None = None,
        indicators: list[PSAK48ImpairmentIndicator] | None = None,
    ) -> PSAK48ImpairmentTestResult:
        recoverable = self.determine_recoverable_amount(fvlcs, viu)
        test_result = PSAK48ImpairmentTestResult(
            test_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            test_date=datetime.now(UTC),
            asset_id=asset_id,
            asset_type=asset_type,
            is_cgu=is_cgu,
            carrying_amount_before=carrying_amount,
            recoverable_amount=recoverable.recoverable_amount,
            fair_value_less_costs_to_sell=fvlcs,
            value_in_use=viu,
            discount_rate_used=discount_rate,
            growth_rate_used=growth_rate,
            indicators_present=indicators or [],
        )
        return test_result

    def allocate_impairment_to_cgu(
        self,
        cgu: PSAK48CashGeneratingUnit,
        asset_carrying_map: dict[UUID, Decimal],
        total_impairment: Decimal,
    ) -> dict[UUID, Decimal]:
        return cgu.allocate_impairment_loss(total_impairment, asset_carrying_map)

    def validate_impairment_test(
        self, test_result: PSAK48ImpairmentTestResult
    ) -> PSAK48ValidationResult:
        result = PSAK48ValidationResult(
            is_compliant=True, compliance_level=PSAK48ComplianceLevel.FULL
        )
        if (
            test_result.impairment_loss > 0
            and test_result.asset_type == PSAK48AssetType.GOODWILL
            and test_result.reversal_recognized > 0
        ):
            result.add_error("Goodwill impairment tidak dapat dibalik")
        result = self._merge_results(result, self._rules.validate_disclosure(test_result))
        return result

    def _merge_results(
        self, main: PSAK48ValidationResult, other: PSAK48ValidationResult
    ) -> PSAK48ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK48ComplianceLevel.FULL,
            PSAK48ComplianceLevel.SUBSTANTIAL,
            PSAK48ComplianceLevel.PARTIAL,
            PSAK48ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "scope": "Aset tetap, aset tak berwujud, goodwill, aset hak-guna, properti investasi",
            "indicators": "Indikator eksternal (penurunan nilai pasar, perubahan teknologi) dan internal (keusangan, kinerja buruk)",
            "recoverable_amount": "Nilai tertinggi antara nilai wajar dikurangi biaya pelepasan dan nilai pakai",
            "annual_testing": "Wajib untuk goodwill dan aset tak berwujud dengan masa manfaat tidak terbatas",
            "cgu": "Unit penghasil kas (CGU) untuk aset yang tidak menghasilkan arus kas independen",
            "allocation": "Impairment dialokasikan ke goodwill terlebih dahulu, lalu ke aset lain secara pro rata",
            "reversal": "Penurunan nilai aset selain goodwill dapat dibalik jika kondisi membaik",
            "disclosures": [
                "Jumlah kerugian penurunan nilai yang diakui",
                "Aset atau CGU yang terkena",
                "Asumsi kunci untuk nilai pakai (tingkat diskonto, tingkat pertumbuhan)",
                "Metode penentuan nilai wajar",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak48_validator_instance: PSAK48Validator | None = None


def get_psak48_validator() -> PSAK48Validator:
    global _psak48_validator_instance
    if _psak48_validator_instance is None:
        _psak48_validator_instance = PSAK48Validator()
    return _psak48_validator_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak48_validator()
    entity_id = uuid4()

    # Example 1: Impairment test for a single asset (machine)
    indicators = [
        PSAK48ImpairmentIndicator.INTERNAL_OBSOLESCENCE,
        PSAK48ImpairmentIndicator.INTERNAL_ECONOMIC_PERFORMANCE_DECLINE,
    ]
    future_cash_flows = [
        (1, Decimal("20000000")),
        (2, Decimal("15000000")),
        (3, Decimal("10000000")),
    ]
    viu = validator.calculate_value_in_use(future_cash_flows, discount_rate=Decimal("12"))
    fvlcs = validator.calculate_fair_value_less_costs_to_sell(
        Decimal("30000000"), Decimal("2000000")
    )
    print(f"Value in use: {viu}, FVLCS: {fvlcs}")

    test_result = validator.perform_impairment_test(
        entity_id=entity_id,
        entity_name="PT Manufaktur",
        asset_id=uuid4(),
        asset_type=PSAK48AssetType.PROPERTY_PLANT_EQUIPMENT,
        carrying_amount=Decimal("45000000"),
        is_cgu=False,
        fvlcs=fvlcs,
        viu=viu,
        discount_rate=Decimal("12"),
        indicators=indicators,
    )
    print("Impairment Test Result:")
    print(json.dumps(test_result.to_dict(), indent=2))

    # Example 2: CGU with goodwill
    cgu = validator.create_cgu("CGU-MFG", "Manufacturing Segment")
    asset_ids = [uuid4(), uuid4()]
    for aid in asset_ids:
        cgu = validator.add_asset_to_cgu(cgu, aid)
    cgu = validator.allocate_goodwill_to_cgu(cgu, uuid4(), Decimal("100000000"))
    asset_carrying = {aid: Decimal("200000000") for aid in asset_ids}
    total_carrying = cgu.total_carrying_amount(asset_carrying)
    print(f"Total CGU carrying amount: {total_carrying}")

    # Assume recoverable amount of CGU is 450M
    recoverable = Decimal("450000000")
    impairment = total_carrying - recoverable
    allocation = validator.allocate_impairment_to_cgu(cgu, asset_carrying, impairment)
    print(f"Impairment allocation: {allocation}")

    # Validate
    result = validator.validate_impairment_test(test_result)
    print("\nValidation Result:")
    print(json.dumps(result.to_dict(), indent=2))
# ============================================================================
# Compatibility aliases for aggregator orchestration
# ============================================================================
CashGeneratingUnit = PSAK48CashGeneratingUnit

# ============================================================================
# Compatibility alias for ImpairmentIndicator orchestration
# ============================================================================
ImpairmentIndicator = PSAK48ImpairmentIndicator

# ============================================================================
# Compatibility alias for ImpairmentLoss orchestration
# ============================================================================
ImpairmentLoss = PSAK48ImpairmentLoss

# ============================================================================
# Compatibility alias for RecoverableAmount orchestration
# ============================================================================
RecoverableAmount = PSAK48RecoverableAmount
