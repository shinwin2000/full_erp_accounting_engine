#!/usr/bin/env python3
"""
Module: psak_13_investment_property.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 13: Properti Investasi (setara dengan IAS 40).
    Mengatur akuntansi untuk properti investasi (tanah/bangunan yang dikuasai
    untuk menghasilkan sewa atau kenaikan nilai, bukan untuk dijual dalam
    kegiatan usaha biasa atau digunakan dalam produksi).
    Menyediakan pilihan model biaya (cost model) atau model nilai wajar
    (fair value model). Jika menggunakan model nilai wajar, perubahan nilai
    wajar diakui dalam laba rugi.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap properti investasi, penilaian, dan perubahan model diakui dengan hash.
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
class PSAK13MeasurementModel(Enum):
    COST = "biaya"
    FAIR_VALUE = "nilai_wajar"


class PSAK13PropertyType(Enum):
    LAND = "tanah"
    BUILDING = "bangunan"
    LAND_AND_BUILDING = "tanah_dan_bangunan"


class PSAK13FairValueLevel(Enum):
    LEVEL_1 = "tingkat_1"  # Harga kuotasi di pasar aktif
    LEVEL_2 = "tingkat_2"  # Input selain harga kuotasi yang dapat diobservasi
    LEVEL_3 = "tingkat_3"  # Input tidak dapat diobservasi


class PSAK13ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK13Error(Exception):
    pass


class InvalidMeasurementModelChangeError(PSAK13Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK13InvestmentProperty:
    """Properti investasi individual."""

    property_id: UUID
    property_code: str
    property_name: str
    property_type: PSAK13PropertyType
    measurement_model: PSAK13MeasurementModel
    acquisition_date: datetime
    cost: Decimal
    accumulated_depreciation: Decimal = Decimal(0)
    accumulated_impairment: Decimal = Decimal(0)
    fair_value: Decimal | None = None
    fair_value_date: datetime | None = None
    fair_value_level: PSAK13FairValueLevel | None = None
    useful_life_years: int | None = None  # For cost model depreciation
    residual_value: Decimal = Decimal(0)
    is_active: bool = True

    @property
    def carrying_amount_cost_model(self) -> Decimal:
        return self.cost - self.accumulated_depreciation - self.accumulated_impairment

    @property
    def carrying_amount_fair_value_model(self) -> Decimal | None:
        return self.fair_value

    def annual_depreciation(self) -> Decimal:
        if self.useful_life_years and self.useful_life_years > 0:
            return (self.cost - self.residual_value) / Decimal(self.useful_life_years)
        return Decimal(0)

    def to_dict(self) -> dict:
        return {
            "property_id": str(self.property_id),
            "property_code": self.property_code,
            "property_name": self.property_name,
            "property_type": self.property_type.value,
            "measurement_model": self.measurement_model.value,
            "acquisition_date": self.acquisition_date.isoformat(),
            "cost": str(self.cost),
            "accumulated_depreciation": str(self.accumulated_depreciation),
            "accumulated_impairment": str(self.accumulated_impairment),
            "carrying_amount_cost": str(self.carrying_amount_cost_model),
            "fair_value": str(self.fair_value) if self.fair_value else None,
            "fair_value_date": self.fair_value_date.isoformat() if self.fair_value_date else None,
            "fair_value_level": self.fair_value_level.value if self.fair_value_level else None,
            "useful_life_years": self.useful_life_years,
            "is_active": self.is_active,
        }


@dataclass
class PSAK13InvestmentPropertyRegister:
    """Register properti investasi."""

    register_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_date: datetime
    properties: list[PSAK13InvestmentProperty] = field(default_factory=list)
    measurement_model: PSAK13MeasurementModel = PSAK13MeasurementModel.COST
    has_transferred_properties: bool = False
    transfer_disclosure: str = ""

    def total_cost(self) -> Decimal:
        return sum(p.cost for p in self.properties if p.is_active)

    def total_carrying_amount(self) -> Decimal:
        if self.measurement_model == PSAK13MeasurementModel.COST:
            return sum(p.carrying_amount_cost_model for p in self.properties if p.is_active)
        else:
            return sum(
                p.fair_value for p in self.properties if p.is_active and p.fair_value is not None
            )

    def total_fair_value(self) -> Decimal:
        return sum(
            p.fair_value for p in self.properties if p.is_active and p.fair_value is not None
        )

    def to_dict(self) -> dict:
        return {
            "register_id": str(self.register_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_date": self.reporting_date.isoformat(),
            "measurement_model": self.measurement_model.value,
            "properties": [p.to_dict() for p in self.properties],
            "total_cost": str(self.total_cost()),
            "total_carrying_amount": str(self.total_carrying_amount()),
            "total_fair_value": str(self.total_fair_value()),
            "has_transferred_properties": self.has_transferred_properties,
            "transfer_disclosure": self.transfer_disclosure,
        }


@dataclass
class PSAK13ValidationResult:
    is_compliant: bool
    compliance_level: PSAK13ComplianceLevel
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
        if self.compliance_level != PSAK13ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK13ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK13ComplianceLevel.FULL:
            self.compliance_level = PSAK13ComplianceLevel.SUBSTANTIAL

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
class PSAK13InvestmentPropertyService:
    """Service untuk properti investasi."""

    @staticmethod
    def determine_fair_value(
        market_price: Decimal | None = None,
        discounted_cash_flow: Decimal | None = None,
        independent_appraisal: Decimal | None = None,
    ) -> tuple[Decimal, PSAK13FairValueLevel]:
        """Menentukan nilai wajar dan tingkatnya."""
        if market_price is not None:
            return market_price, PSAK13FairValueLevel.LEVEL_1
        if independent_appraisal is not None:
            return independent_appraisal, PSAK13FairValueLevel.LEVEL_2
        if discounted_cash_flow is not None:
            return discounted_cash_flow, PSAK13FairValueLevel.LEVEL_3
        raise PSAK13Error("Tidak ada input untuk menentukan nilai wajar")

    @staticmethod
    def calculate_depreciation(cost: Decimal, residual: Decimal, useful_life: int) -> Decimal:
        return (cost - residual) / Decimal(useful_life) if useful_life > 0 else Decimal(0)

    @staticmethod
    def can_change_measurement_model(
        current_model: PSAK13MeasurementModel,
        new_model: PSAK13MeasurementModel,
        justification: str,
    ) -> bool:
        """Perubahan model hanya diperbolehkan jika menghasilkan penyajian yang lebih relevan."""
        if current_model == new_model:
            return False
        if (
            current_model == PSAK13MeasurementModel.COST
            and new_model == PSAK13MeasurementModel.FAIR_VALUE
        ):
            return True  # Selalu diperbolehkan (tidak dapat kembali ke cost model)
        # Dari fair value ke cost tidak diperbolehkan
        return False


# ============================================================================
# Rules
# ============================================================================
class PSAK13Rules:
    """Aturan PSAK 13."""

    @staticmethod
    def validate_measurement_consistency(
        register: PSAK13InvestmentPropertyRegister,
    ) -> PSAK13ValidationResult:
        result = PSAK13ValidationResult(
            is_compliant=True, compliance_level=PSAK13ComplianceLevel.FULL
        )
        for prop in register.properties:
            if prop.measurement_model != register.measurement_model:
                result.add_error(
                    f"Properti {prop.property_code} menggunakan model pengukuran berbeda dari kebijakan entitas"
                )
        return result

    @staticmethod
    def validate_fair_value_disclosure(
        register: PSAK13InvestmentPropertyRegister,
    ) -> PSAK13ValidationResult:
        result = PSAK13ValidationResult(
            is_compliant=True, compliance_level=PSAK13ComplianceLevel.FULL
        )
        if register.measurement_model == PSAK13MeasurementModel.FAIR_VALUE:
            for prop in register.properties:
                if prop.fair_value is None:
                    result.add_error(f"Nilai wajar properti {prop.property_code} tidak ditentukan")
                if prop.fair_value_level is None:
                    result.add_warning(
                        f"Tingkat hierarki nilai wajar properti {prop.property_code} tidak diungkapkan"
                    )
                if prop.fair_value_date is None:
                    result.add_warning(
                        f"Tanggal penilaian properti {prop.property_code} tidak diungkapkan"
                    )
        return result

    @staticmethod
    def validate_transfer_classification(
        register: PSAK13InvestmentPropertyRegister,
    ) -> PSAK13ValidationResult:
        result = PSAK13ValidationResult(
            is_compliant=True, compliance_level=PSAK13ComplianceLevel.FULL
        )
        if register.has_transferred_properties and not register.transfer_disclosure:
            result.add_error("Perpindahan properti investasi ke properti lain tidak diungkapkan")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK13Validator:
    def __init__(self):
        self._rules = PSAK13Rules()
        self._service = PSAK13InvestmentPropertyService()

    def create_property(
        self,
        property_code: str,
        property_name: str,
        property_type: PSAK13PropertyType,
        measurement_model: PSAK13MeasurementModel,
        acquisition_date: datetime,
        cost: Decimal,
        useful_life_years: int | None = None,
        residual_value: Decimal = Decimal(0),
        fair_value: Decimal | None = None,
        fair_value_date: datetime | None = None,
        fair_value_level: PSAK13FairValueLevel | None = None,
    ) -> PSAK13InvestmentProperty:
        return PSAK13InvestmentProperty(
            property_id=uuid4(),
            property_code=property_code,
            property_name=property_name,
            property_type=property_type,
            measurement_model=measurement_model,
            acquisition_date=acquisition_date,
            cost=cost,
            useful_life_years=useful_life_years,
            residual_value=residual_value,
            fair_value=fair_value,
            fair_value_date=fair_value_date,
            fair_value_level=fair_value_level,
        )

    def create_register(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_date: datetime,
        measurement_model: PSAK13MeasurementModel = PSAK13MeasurementModel.COST,
    ) -> PSAK13InvestmentPropertyRegister:
        return PSAK13InvestmentPropertyRegister(
            register_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_date=reporting_date,
            measurement_model=measurement_model,
        )

    def add_property(
        self, register: PSAK13InvestmentPropertyRegister, prop: PSAK13InvestmentProperty
    ) -> PSAK13InvestmentPropertyRegister:
        new_props = register.properties + [prop]
        return PSAK13InvestmentPropertyRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            reporting_date=register.reporting_date,
            properties=new_props,
            measurement_model=register.measurement_model,
            has_transferred_properties=register.has_transferred_properties,
            transfer_disclosure=register.transfer_disclosure,
        )

    def record_depreciation(
        self,
        prop: PSAK13InvestmentProperty,
        period_end: datetime,
    ) -> PSAK13InvestmentProperty:
        if prop.measurement_model == PSAK13MeasurementModel.COST and prop.useful_life_years:
            annual_dep = prop.annual_depreciation()
            months = (period_end - prop.acquisition_date).days / 30.44
            depreciation = annual_dep * Decimal(months / 12)
            new_accum = prop.accumulated_depreciation + depreciation
            return PSAK13InvestmentProperty(
                property_id=prop.property_id,
                property_code=prop.property_code,
                property_name=prop.property_name,
                property_type=prop.property_type,
                measurement_model=prop.measurement_model,
                acquisition_date=prop.acquisition_date,
                cost=prop.cost,
                accumulated_depreciation=new_accum,
                accumulated_impairment=prop.accumulated_impairment,
                fair_value=prop.fair_value,
                fair_value_date=prop.fair_value_date,
                fair_value_level=prop.fair_value_level,
                useful_life_years=prop.useful_life_years,
                residual_value=prop.residual_value,
                is_active=prop.is_active,
            )
        return prop

    def record_fair_value_change(
        self,
        prop: PSAK13InvestmentProperty,
        new_fair_value: Decimal,
        valuation_date: datetime,
        level: PSAK13FairValueLevel,
    ) -> PSAK13InvestmentProperty:
        if prop.measurement_model == PSAK13MeasurementModel.FAIR_VALUE:
            return PSAK13InvestmentProperty(
                property_id=prop.property_id,
                property_code=prop.property_code,
                property_name=prop.property_name,
                property_type=prop.property_type,
                measurement_model=prop.measurement_model,
                acquisition_date=prop.acquisition_date,
                cost=prop.cost,
                accumulated_depreciation=prop.accumulated_depreciation,
                accumulated_impairment=prop.accumulated_impairment,
                fair_value=new_fair_value,
                fair_value_date=valuation_date,
                fair_value_level=level,
                useful_life_years=prop.useful_life_years,
                residual_value=prop.residual_value,
                is_active=prop.is_active,
            )
        return prop

    def transfer_to_owner_occupied(
        self, register: PSAK13InvestmentPropertyRegister, property_id: UUID, disclosure: str
    ) -> PSAK13InvestmentPropertyRegister:
        new_props = []
        for p in register.properties:
            if p.property_id == property_id:
                p.is_active = False
            new_props.append(p)
        return PSAK13InvestmentPropertyRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            reporting_date=register.reporting_date,
            properties=new_props,
            measurement_model=register.measurement_model,
            has_transferred_properties=True,
            transfer_disclosure=disclosure,
        )

    def validate_register(
        self, register: PSAK13InvestmentPropertyRegister
    ) -> PSAK13ValidationResult:
        result = self._rules.validate_measurement_consistency(register)
        result = self._merge_results(result, self._rules.validate_fair_value_disclosure(register))
        result = self._merge_results(result, self._rules.validate_transfer_classification(register))
        return result

    def _merge_results(
        self, main: PSAK13ValidationResult, other: PSAK13ValidationResult
    ) -> PSAK13ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK13ComplianceLevel.FULL,
            PSAK13ComplianceLevel.SUBSTANTIAL,
            PSAK13ComplianceLevel.PARTIAL,
            PSAK13ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "measurement_models": ["Biaya (cost model)", "Nilai wajar (fair value model)"],
            "fair_value_measurement": "Nilai wajar harus ditentukan secara andal (jika menggunakan model nilai wajar)",
            "depreciation": "Jika menggunakan model biaya, properti disusutkan",
            "transfer": "Perpindahan properti investasi ke properti lain harus diungkapkan",
            "disclosures": [
                "Kebijakan akuntansi yang digunakan",
                "Jumlah properti investasi",
                "Nilai wajar (bahkan jika menggunakan model biaya)",
                "Metode dan asumsi valuasi",
                "Rekonsiliasi nilai tercatat",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak13_validator_instance: PSAK13Validator | None = None


def get_psak13_validator() -> PSAK13Validator:
    global _psak13_validator_instance
    if _psak13_validator_instance is None:
        _psak13_validator_instance = PSAK13Validator()
    return _psak13_validator_instance


InvestmentProperty = PSAK13InvestmentProperty
InvestmentPropertyClassification = PSAK13PropertyType
InvestmentPropertyMeasurementModel = PSAK13MeasurementModel
PropertyUsageStatus = PSAK13PropertyType  # atau sesuaikan


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak13_validator()
    entity_id = uuid4()

    # Create register with cost model
    register = validator.create_register(
        entity_id=entity_id,
        entity_name="PT Properti Investasi",
        reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
        measurement_model=PSAK13MeasurementModel.COST,
    )

    # Add property (cost model)
    prop1 = validator.create_property(
        property_code="GED-01",
        property_name="Gedung Perkantoran",
        property_type=PSAK13PropertyType.BUILDING,
        measurement_model=PSAK13MeasurementModel.COST,
        acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        cost=Decimal("10000000000"),
        useful_life_years=50,
        residual_value=Decimal("1000000000"),
    )
    register = validator.add_property(register, prop1)

    # Add property (fair value model)
    prop2 = validator.create_property(
        property_code="TNH-01",
        property_name="Tanah Kavling",
        property_type=PSAK13PropertyType.LAND,
        measurement_model=PSAK13MeasurementModel.FAIR_VALUE,
        acquisition_date=datetime(2025, 6, 1, tzinfo=UTC),
        cost=Decimal("5000000000"),
        fair_value=Decimal("6000000000"),
        fair_value_date=datetime(2026, 12, 31, tzinfo=UTC),
        fair_value_level=PSAK13FairValueLevel.LEVEL_2,
    )
    register = validator.add_property(register, prop2)

    # Record depreciation for cost model property
    prop1_updated = validator.record_depreciation(prop1, register.reporting_date)
    # Replace property in register (simplified: rebuild register)
    new_props = []
    for p in register.properties:
        if p.property_id == prop1.property_id:
            new_props.append(prop1_updated)
        else:
            new_props.append(p)
    register = PSAK13InvestmentPropertyRegister(
        register_id=register.register_id,
        entity_id=register.entity_id,
        entity_name=register.entity_name,
        reporting_date=register.reporting_date,
        properties=new_props,
        measurement_model=register.measurement_model,
        has_transferred_properties=register.has_transferred_properties,
        transfer_disclosure=register.transfer_disclosure,
    )

    # Transfer property to owner-occupied
    register = validator.transfer_to_owner_occupied(
        register,
        prop1.property_id,
        "Gedung perkantoran mulai digunakan sendiri untuk operasional perusahaan efektif 1 Januari 2027",
    )

    # Validate
    result = validator.validate_register(register)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nRegister:")
    print(json.dumps(register.to_dict(), indent=2, default=str))
