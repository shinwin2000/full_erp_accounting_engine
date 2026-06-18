#!/usr/bin/env python3
"""
Module: psak_19_intangible_assets.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 19: Aset Tak Berwujud (setara dengan IAS 38).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class PSAK19IntangibleType(Enum):
    PATENT = "paten"
    TRADEMARK = "merek_dagang"
    COPYRIGHT = "hak_cipta"
    SOFTWARE = "perangkat_lunak"
    LICENSE = "lisensi"
    FRANCHISE = "waralaba"
    CUSTOMER_RELATIONSHIP = "hubungan_pelanggan"
    BRAND = "merek"
    GOODWILL = "goodwill"
    RESEARCH = "riset"
    DEVELOPMENT = "pengembangan"
    OTHER = "lainnya"


class PSAK19AcquisitionMethod(Enum):
    SEPARATE_PURCHASE = "pembelian_terpisah"
    BUSINESS_COMBINATION = "kombinasi_bisnis"
    INTERNALLY_GENERATED = "dihasilkan_internal"
    GOVERNMENT_GRANT = "hibah_pemerintah"
    EXCHANGE = "tukar_menukar"


class PSAK19MeasurementModel(Enum):
    COST = "biaya"
    REVALUATION = "revaluasi"


class PSAK19AmortizationMethod(Enum):
    STRAIGHT_LINE = "garis_lurus"
    DECLINING_BALANCE = "saldo_menurun"
    UNITS_OF_PRODUCTION = "unit_produksi"


class PSAK19UsefulLifeType(Enum):
    FINITE = "terbatas"
    INDEFINITE = "tidak_terbatas"


class PSAK19DevelopmentPhaseCriteria(Enum):
    TECHNICAL_FEASIBILITY = "kelayakan_teknis"
    INTENTION_TO_COMPLETE = "niat_menyelesaikan"
    ABILITY_TO_USE_SELL = "kemampuan_menggunakan_menjual"
    FUTURE_ECONOMIC_BENEFITS = "manfaat_ekonomi_masa_depan"
    RESOURCES_AVAILABLE = "sumber_daya_tersedia"
    EXPENDITURE_MEASURABLE = "pengeluaran_dapat_diukur"


class PSAK19ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK19Error(Exception):
    pass


class IntangibleAssetNotFoundError(PSAK19Error):
    pass


class InvalidAmortizationError(PSAK19Error):
    pass


class DevelopmentCostNotCapitalizableError(PSAK19Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK19RevaluationSurplus:
    surplus_id: UUID
    revaluation_date: datetime
    fair_value_before: Decimal
    fair_value_after: Decimal
    increase_amount: Decimal
    performed_by: str
    effective_date: datetime
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "surplus_id": str(self.surplus_id),
            "revaluation_date": self.revaluation_date.isoformat(),
            "fair_value_before": str(self.fair_value_before),
            "fair_value_after": str(self.fair_value_after),
            "increase_amount": str(self.increase_amount),
            "performed_by": self.performed_by,
            "effective_date": self.effective_date.isoformat(),
            "notes": self.notes,
        }


@dataclass
class PSAK19IntangibleAsset:
    asset_id: UUID
    asset_code: str
    name: str
    asset_type: PSAK19IntangibleType
    acquisition_method: PSAK19AcquisitionMethod
    measurement_model: PSAK19MeasurementModel
    acquisition_date: datetime
    cost: Decimal
    useful_life_type: PSAK19UsefulLifeType
    useful_life_years: int | None = None
    residual_value: Decimal = Decimal(0)
    amortization_method: PSAK19AmortizationMethod = PSAK19AmortizationMethod.STRAIGHT_LINE
    accumulated_amortization: Decimal = Decimal(0)
    accumulated_impairment: Decimal = Decimal(0)
    revaluation_surplus_history: list[PSAK19RevaluationSurplus] = field(default_factory=list)
    current_revaluation_surplus: Decimal = Decimal(0)
    last_revaluation_date: datetime | None = None
    is_active: bool = True
    disposal_date: datetime | None = None
    disposal_proceeds: Decimal = Decimal(0)
    disposal_cost: Decimal = Decimal(0)
    development_criteria_met: bool = False
    development_criteria_details: list[PSAK19DevelopmentPhaseCriteria] = field(default_factory=list)

    @property
    def carrying_amount_cost_model(self) -> Decimal:
        return self.cost - self.accumulated_amortization - self.accumulated_impairment

    @property
    def carrying_amount_revaluation_model(self) -> Decimal:
        if (
            self.measurement_model == PSAK19MeasurementModel.REVALUATION
            and self.revaluation_surplus_history
        ):
            last = self.revaluation_surplus_history[-1]
            return (
                last.fair_value_after - self.accumulated_amortization - self.accumulated_impairment
            )
        return self.carrying_amount_cost_model

    @property
    def carrying_amount(self) -> Decimal:
        return (
            self.carrying_amount_revaluation_model
            if self.measurement_model == PSAK19MeasurementModel.REVALUATION
            else self.carrying_amount_cost_model
        )

    @property
    def net_book_value(self) -> Decimal:
        return self.carrying_amount

    @property
    def amortizable_amount(self) -> Decimal:
        if self.useful_life_type == PSAK19UsefulLifeType.INDEFINITE:
            return Decimal(0)
        return self.cost - self.residual_value

    def annual_amortization(self) -> Decimal:
        if self.useful_life_type == PSAK19UsefulLifeType.INDEFINITE:
            return Decimal(0)
        if not self.useful_life_years or self.useful_life_years <= 0:
            return Decimal(0)
        if self.amortization_method == PSAK19AmortizationMethod.STRAIGHT_LINE:
            return (self.cost - self.residual_value) / Decimal(self.useful_life_years)
        elif self.amortization_method == PSAK19AmortizationMethod.DECLINING_BALANCE:
            rate = Decimal(2) / Decimal(self.useful_life_years)
            return self.carrying_amount * rate
        else:
            return Decimal(0)

    def to_dict(self) -> dict:
        return {
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "name": self.name,
            "asset_type": self.asset_type.value,
            "acquisition_method": self.acquisition_method.value,
            "measurement_model": self.measurement_model.value,
            "acquisition_date": self.acquisition_date.isoformat(),
            "cost": str(self.cost),
            "useful_life_type": self.useful_life_type.value,
            "useful_life_years": self.useful_life_years,
            "residual_value": str(self.residual_value),
            "amortization_method": self.amortization_method.value,
            "accumulated_amortization": str(self.accumulated_amortization),
            "accumulated_impairment": str(self.accumulated_impairment),
            "carrying_amount": str(self.carrying_amount),
            "current_revaluation_surplus": str(self.current_revaluation_surplus),
            "last_revaluation_date": self.last_revaluation_date.isoformat()
            if self.last_revaluation_date
            else None,
            "is_active": self.is_active,
            "development_criteria_met": self.development_criteria_met,
            "development_criteria_details": [c.value for c in self.development_criteria_details],
        }


@dataclass
class PSAK19IntangibleRegister:
    register_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_date: datetime
    assets: list[PSAK19IntangibleAsset] = field(default_factory=list)
    amortization_method_default: PSAK19AmortizationMethod = PSAK19AmortizationMethod.STRAIGHT_LINE
    research_expense_ytd: Decimal = Decimal(0)
    development_cost_capitalized_ytd: Decimal = Decimal(0)

    def total_cost(self) -> Decimal:
        return sum(a.cost for a in self.assets if a.is_active)

    def total_accumulated_amortization(self) -> Decimal:
        return sum(a.accumulated_amortization for a in self.assets if a.is_active)

    def total_carrying_amount(self) -> Decimal:
        return sum(a.carrying_amount for a in self.assets if a.is_active)

    def total_revaluation_surplus(self) -> Decimal:
        return sum(a.current_revaluation_surplus for a in self.assets if a.is_active)

    def to_dict(self) -> dict:
        return {
            "register_id": str(self.register_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_date": self.reporting_date.isoformat(),
            "assets": [a.to_dict() for a in self.assets],
            "total_cost": str(self.total_cost()),
            "total_accumulated_amortization": str(self.total_accumulated_amortization()),
            "total_carrying_amount": str(self.total_carrying_amount()),
            "total_revaluation_surplus": str(self.total_revaluation_surplus()),
            "research_expense_ytd": str(self.research_expense_ytd),
            "development_cost_capitalized_ytd": str(self.development_cost_capitalized_ytd),
        }


@dataclass
class PSAK19ValidationResult:
    is_compliant: bool
    compliance_level: PSAK19ComplianceLevel
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
        if self.compliance_level != PSAK19ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK19ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK19ComplianceLevel.FULL:
            self.compliance_level = PSAK19ComplianceLevel.SUBSTANTIAL

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
class PSAK19IntangibleService:
    @staticmethod
    def calculate_amortization_for_period(
        asset: PSAK19IntangibleAsset, start_date: datetime, end_date: datetime
    ) -> Decimal:
        if asset.useful_life_type == PSAK19UsefulLifeType.INDEFINITE:
            return Decimal(0)
        annual = asset.annual_amortization()
        if annual == 0:
            return Decimal(0)
        days_in_period = (end_date - start_date).days
        if days_in_period <= 0:
            return Decimal(0)
        return (annual * Decimal(days_in_period) / Decimal(365)).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    @staticmethod
    def check_development_capitalization_criteria(
        criteria_met: dict[PSAK19DevelopmentPhaseCriteria, bool],
    ) -> tuple[bool, list[PSAK19DevelopmentPhaseCriteria]]:
        required_criteria = [
            PSAK19DevelopmentPhaseCriteria.TECHNICAL_FEASIBILITY,
            PSAK19DevelopmentPhaseCriteria.INTENTION_TO_COMPLETE,
            PSAK19DevelopmentPhaseCriteria.ABILITY_TO_USE_SELL,
            PSAK19DevelopmentPhaseCriteria.FUTURE_ECONOMIC_BENEFITS,
            PSAK19DevelopmentPhaseCriteria.RESOURCES_AVAILABLE,
            PSAK19DevelopmentPhaseCriteria.EXPENDITURE_MEASURABLE,
        ]
        met = [c for c in required_criteria if criteria_met.get(c, False)]
        return len(met) == len(required_criteria), met

    @staticmethod
    def calculate_gain_loss_on_disposal(asset: PSAK19IntangibleAsset) -> Decimal:
        carrying = asset.carrying_amount
        net_proceeds = asset.disposal_proceeds - asset.disposal_cost
        return net_proceeds - carrying

    @staticmethod
    def revalue_asset(
        asset: PSAK19IntangibleAsset,
        new_fair_value: Decimal,
        valuation_date: datetime,
        performed_by: str,
    ) -> PSAK19IntangibleAsset:
        if asset.measurement_model != PSAK19MeasurementModel.REVALUATION:
            raise PSAK19Error("Aset tidak menggunakan model revaluasi")
        old_carrying = asset.carrying_amount
        increase = new_fair_value - old_carrying
        if increase > 0:
            new_surplus = PSAK19RevaluationSurplus(
                surplus_id=uuid4(),
                revaluation_date=valuation_date,
                fair_value_before=old_carrying,
                fair_value_after=new_fair_value,
                increase_amount=increase,
                performed_by=performed_by,
                effective_date=valuation_date,
            )
            new_history = asset.revaluation_surplus_history + [new_surplus]
            new_current_surplus = asset.current_revaluation_surplus + increase
            return PSAK19IntangibleAsset(
                asset_id=asset.asset_id,
                asset_code=asset.asset_code,
                name=asset.name,
                asset_type=asset.asset_type,
                acquisition_method=asset.acquisition_method,
                measurement_model=asset.measurement_model,
                acquisition_date=asset.acquisition_date,
                cost=asset.cost,
                useful_life_type=asset.useful_life_type,
                useful_life_years=asset.useful_life_years,
                residual_value=asset.residual_value,
                amortization_method=asset.amortization_method,
                accumulated_amortization=Decimal(0),
                accumulated_impairment=Decimal(0),
                revaluation_surplus_history=new_history,
                current_revaluation_surplus=new_current_surplus,
                last_revaluation_date=valuation_date,
                is_active=asset.is_active,
                disposal_date=asset.disposal_date,
                disposal_proceeds=asset.disposal_proceeds,
                disposal_cost=asset.disposal_cost,
                development_criteria_met=asset.development_criteria_met,
                development_criteria_details=asset.development_criteria_details,
            )
        else:
            new_impairment = asset.accumulated_impairment + abs(increase)
            return PSAK19IntangibleAsset(
                asset_id=asset.asset_id,
                asset_code=asset.asset_code,
                name=asset.name,
                asset_type=asset.asset_type,
                acquisition_method=asset.acquisition_method,
                measurement_model=asset.measurement_model,
                acquisition_date=asset.acquisition_date,
                cost=asset.cost,
                useful_life_type=asset.useful_life_type,
                useful_life_years=asset.useful_life_years,
                residual_value=asset.residual_value,
                amortization_method=asset.amortization_method,
                accumulated_amortization=asset.accumulated_amortization,
                accumulated_impairment=new_impairment,
                revaluation_surplus_history=asset.revaluation_surplus_history,
                current_revaluation_surplus=asset.current_revaluation_surplus,
                last_revaluation_date=valuation_date,
                is_active=asset.is_active,
                disposal_date=asset.disposal_date,
                disposal_proceeds=asset.disposal_proceeds,
                disposal_cost=asset.disposal_cost,
                development_criteria_met=asset.development_criteria_met,
                development_criteria_details=asset.development_criteria_details,
            )


# ============================================================================
# Rules
# ============================================================================
class PSAK19Rules:
    @staticmethod
    def validate_separate_acquisition(asset: PSAK19IntangibleAsset) -> PSAK19ValidationResult:
        result = PSAK19ValidationResult(
            is_compliant=True, compliance_level=PSAK19ComplianceLevel.FULL
        )
        if (
            asset.acquisition_method == PSAK19AcquisitionMethod.SEPARATE_PURCHASE
            and asset.cost <= 0
        ):
            result.add_error("Biaya perolehan aset tak berwujud harus positif")
        return result

    @staticmethod
    def validate_internally_generated(asset: PSAK19IntangibleAsset) -> PSAK19ValidationResult:
        result = PSAK19ValidationResult(
            is_compliant=True, compliance_level=PSAK19ComplianceLevel.FULL
        )
        if asset.acquisition_method == PSAK19AcquisitionMethod.INTERNALLY_GENERATED:
            if asset.asset_type in [
                PSAK19IntangibleType.RESEARCH,
                PSAK19IntangibleType.DEVELOPMENT,
            ]:
                if (
                    not asset.development_criteria_met
                    and asset.asset_type == PSAK19IntangibleType.DEVELOPMENT
                ):
                    result.add_error(
                        "Biaya pengembangan tidak memenuhi kriteria kapitalisasi PSAK 19"
                    )
                elif asset.asset_type == PSAK19IntangibleType.RESEARCH:
                    result.add_warning("Biaya riset harus diakui sebagai beban, bukan aset")
            else:
                result.add_error(
                    f"Aset {asset.asset_type.value} tidak dapat dihasilkan secara internal (kecuali pengembangan)"
                )
        return result

    @staticmethod
    def validate_useful_life(asset: PSAK19IntangibleAsset) -> PSAK19ValidationResult:
        result = PSAK19ValidationResult(
            is_compliant=True, compliance_level=PSAK19ComplianceLevel.FULL
        )
        if asset.useful_life_type == PSAK19UsefulLifeType.FINITE and (
            not asset.useful_life_years or asset.useful_life_years <= 0
        ):
            result.add_error(
                "Aset tak berwujud dengan masa manfaat terbatas harus memiliki estimasi masa manfaat"
            )
        if asset.useful_life_type == PSAK19UsefulLifeType.INDEFINITE:
            if asset.amortization_method != PSAK19AmortizationMethod.STRAIGHT_LINE:
                result.add_warning("Aset dengan masa manfaat tidak terbatas tidak diamortisasi")
        return result

    @staticmethod
    def validate_revaluation_model(asset: PSAK19IntangibleAsset) -> PSAK19ValidationResult:
        result = PSAK19ValidationResult(
            is_compliant=True, compliance_level=PSAK19ComplianceLevel.FULL
        )
        if asset.measurement_model == PSAK19MeasurementModel.REVALUATION:
            allowed_types = [
                PSAK19IntangibleType.PATENT,
                PSAK19IntangibleType.TRADEMARK,
                PSAK19IntangibleType.COPYRIGHT,
            ]
            if asset.asset_type not in allowed_types:
                result.add_error(
                    f"Aset {asset.asset_type.value} tidak memiliki pasar aktif, tidak boleh menggunakan model revaluasi"
                )
        return result

    @staticmethod
    def validate_amortization(asset: PSAK19IntangibleAsset) -> PSAK19ValidationResult:
        result = PSAK19ValidationResult(
            is_compliant=True, compliance_level=PSAK19ComplianceLevel.FULL
        )
        if (
            asset.useful_life_type == PSAK19UsefulLifeType.FINITE
            and asset.residual_value > asset.cost
        ):
            result.add_error("Nilai residu tidak boleh melebihi biaya perolehan")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK19Validator:
    def __init__(self):
        self._rules = PSAK19Rules()
        self._service = PSAK19IntangibleService()

    def create_asset(
        self,
        asset_code: str,
        name: str,
        asset_type: PSAK19IntangibleType,
        acquisition_method: PSAK19AcquisitionMethod,
        measurement_model: PSAK19MeasurementModel,
        acquisition_date: datetime,
        cost: Decimal,
        useful_life_type: PSAK19UsefulLifeType,
        useful_life_years: int | None = None,
        residual_value: Decimal = Decimal(0),
        amortization_method: PSAK19AmortizationMethod = PSAK19AmortizationMethod.STRAIGHT_LINE,
        development_criteria: dict[PSAK19DevelopmentPhaseCriteria, bool] | None = None,
    ) -> PSAK19IntangibleAsset:
        criteria_met = False
        criteria_details = []
        if (
            acquisition_method == PSAK19AcquisitionMethod.INTERNALLY_GENERATED
            and asset_type == PSAK19IntangibleType.DEVELOPMENT
            and development_criteria
        ):
            criteria_met, criteria_details = (
                self._service.check_development_capitalization_criteria(development_criteria)
            )
        return PSAK19IntangibleAsset(
            asset_id=uuid4(),
            asset_code=asset_code,
            name=name,
            asset_type=asset_type,
            acquisition_method=acquisition_method,
            measurement_model=measurement_model,
            acquisition_date=acquisition_date,
            cost=cost,
            useful_life_type=useful_life_type,
            useful_life_years=useful_life_years,
            residual_value=residual_value,
            amortization_method=amortization_method,
            development_criteria_met=criteria_met,
            development_criteria_details=criteria_details,
        )

    def create_register(
        self, entity_id: UUID, entity_name: str, reporting_date: datetime
    ) -> PSAK19IntangibleRegister:
        return PSAK19IntangibleRegister(
            register_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_date=reporting_date,
        )

    def add_asset(
        self, register: PSAK19IntangibleRegister, asset: PSAK19IntangibleAsset
    ) -> PSAK19IntangibleRegister:
        new_assets = register.assets + [asset]
        return PSAK19IntangibleRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            reporting_date=register.reporting_date,
            assets=new_assets,
            amortization_method_default=register.amortization_method_default,
            research_expense_ytd=register.research_expense_ytd,
            development_cost_capitalized_ytd=register.development_cost_capitalized_ytd,
        )

    def record_amortization(
        self, register: PSAK19IntangibleRegister, asset_id: UUID, period_end: datetime
    ) -> PSAK19IntangibleRegister:
        new_assets = []
        for asset in register.assets:
            if asset.asset_id == asset_id:
                amort = self._service.calculate_amortization_for_period(
                    asset, asset.acquisition_date, period_end
                )
                new_amort = asset.accumulated_amortization + amort
                updated_asset = PSAK19IntangibleAsset(
                    asset_id=asset.asset_id,
                    asset_code=asset.asset_code,
                    name=asset.name,
                    asset_type=asset.asset_type,
                    acquisition_method=asset.acquisition_method,
                    measurement_model=asset.measurement_model,
                    acquisition_date=asset.acquisition_date,
                    cost=asset.cost,
                    useful_life_type=asset.useful_life_type,
                    useful_life_years=asset.useful_life_years,
                    residual_value=asset.residual_value,
                    amortization_method=asset.amortization_method,
                    accumulated_amortization=new_amort,
                    accumulated_impairment=asset.accumulated_impairment,
                    revaluation_surplus_history=asset.revaluation_surplus_history,
                    current_revaluation_surplus=asset.current_revaluation_surplus,
                    last_revaluation_date=asset.last_revaluation_date,
                    is_active=asset.is_active,
                    disposal_date=asset.disposal_date,
                    disposal_proceeds=asset.disposal_proceeds,
                    disposal_cost=asset.disposal_cost,
                    development_criteria_met=asset.development_criteria_met,
                    development_criteria_details=asset.development_criteria_details,
                )
                new_assets.append(updated_asset)
            else:
                new_assets.append(asset)
        return PSAK19IntangibleRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            reporting_date=register.reporting_date,
            assets=new_assets,
            amortization_method_default=register.amortization_method_default,
            research_expense_ytd=register.research_expense_ytd,
            development_cost_capitalized_ytd=register.development_cost_capitalized_ytd,
        )

    def record_research_expense(
        self, register: PSAK19IntangibleRegister, amount: Decimal
    ) -> PSAK19IntangibleRegister:
        return PSAK19IntangibleRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            reporting_date=register.reporting_date,
            assets=register.assets,
            amortization_method_default=register.amortization_method_default,
            research_expense_ytd=register.research_expense_ytd + amount,
            development_cost_capitalized_ytd=register.development_cost_capitalized_ytd,
        )

    def record_development_capitalization(
        self, register: PSAK19IntangibleRegister, amount: Decimal
    ) -> PSAK19IntangibleRegister:
        return PSAK19IntangibleRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            reporting_date=register.reporting_date,
            assets=register.assets,
            amortization_method_default=register.amortization_method_default,
            research_expense_ytd=register.research_expense_ytd,
            development_cost_capitalized_ytd=register.development_cost_capitalized_ytd + amount,
        )

    def revalue_asset(
        self,
        register: PSAK19IntangibleRegister,
        asset_id: UUID,
        new_fair_value: Decimal,
        valuation_date: datetime,
        performed_by: str,
    ) -> PSAK19IntangibleRegister:
        new_assets = []
        for asset in register.assets:
            if asset.asset_id == asset_id:
                updated_asset = self._service.revalue_asset(
                    asset, new_fair_value, valuation_date, performed_by
                )
                new_assets.append(updated_asset)
            else:
                new_assets.append(asset)
        return PSAK19IntangibleRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            reporting_date=register.reporting_date,
            assets=new_assets,
            amortization_method_default=register.amortization_method_default,
            research_expense_ytd=register.research_expense_ytd,
            development_cost_capitalized_ytd=register.development_cost_capitalized_ytd,
        )

    def dispose_asset(
        self,
        register: PSAK19IntangibleRegister,
        asset_id: UUID,
        disposal_date: datetime,
        proceeds: Decimal,
        cost: Decimal = Decimal(0),
    ) -> tuple[PSAK19IntangibleRegister, Decimal]:
        gain_loss = Decimal(0)
        new_assets = []
        for asset in register.assets:
            if asset.asset_id == asset_id:
                if not asset.is_active:
                    raise PSAK19Error(f"Aset {asset.asset_code} sudah tidak aktif")
                carrying = asset.carrying_amount
                net_proceeds = proceeds - cost
                gain_loss = net_proceeds - carrying
                updated_asset = PSAK19IntangibleAsset(
                    asset_id=asset.asset_id,
                    asset_code=asset.asset_code,
                    name=asset.name,
                    asset_type=asset.asset_type,
                    acquisition_method=asset.acquisition_method,
                    measurement_model=asset.measurement_model,
                    acquisition_date=asset.acquisition_date,
                    cost=asset.cost,
                    useful_life_type=asset.useful_life_type,
                    useful_life_years=asset.useful_life_years,
                    residual_value=asset.residual_value,
                    amortization_method=asset.amortization_method,
                    accumulated_amortization=asset.accumulated_amortization,
                    accumulated_impairment=asset.accumulated_impairment,
                    revaluation_surplus_history=asset.revaluation_surplus_history,
                    current_revaluation_surplus=asset.current_revaluation_surplus,
                    last_revaluation_date=asset.last_revaluation_date,
                    is_active=False,
                    disposal_date=disposal_date,
                    disposal_proceeds=proceeds,
                    disposal_cost=cost,
                    development_criteria_met=asset.development_criteria_met,
                    development_criteria_details=asset.development_criteria_details,
                )
                new_assets.append(updated_asset)
            else:
                new_assets.append(asset)
        return (
            PSAK19IntangibleRegister(
                register_id=register.register_id,
                entity_id=register.entity_id,
                entity_name=register.entity_name,
                reporting_date=register.reporting_date,
                assets=new_assets,
                amortization_method_default=register.amortization_method_default,
                research_expense_ytd=register.research_expense_ytd,
                development_cost_capitalized_ytd=register.development_cost_capitalized_ytd,
            ),
            gain_loss,
        )

    def validate_register(self, register: PSAK19IntangibleRegister) -> PSAK19ValidationResult:
        result = PSAK19ValidationResult(
            is_compliant=True, compliance_level=PSAK19ComplianceLevel.FULL
        )
        for asset in register.assets:
            if asset.is_active:
                result = self._merge_results(
                    result, self._rules.validate_separate_acquisition(asset)
                )
                result = self._merge_results(
                    result, self._rules.validate_internally_generated(asset)
                )
                result = self._merge_results(result, self._rules.validate_useful_life(asset))
                result = self._merge_results(result, self._rules.validate_revaluation_model(asset))
                result = self._merge_results(result, self._rules.validate_amortization(asset))
        return result

    def _merge_results(
        self, main: PSAK19ValidationResult, other: PSAK19ValidationResult
    ) -> PSAK19ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK19ComplianceLevel.FULL,
            PSAK19ComplianceLevel.SUBSTANTIAL,
            PSAK19ComplianceLevel.PARTIAL,
            PSAK19ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "recognition": "Aset tak berwujud diakui jika kemungkinan besar manfaat ekonomi akan mengalir dan biaya dapat diukur secara andal",
            "research_vs_development": "Biaya riset dibebankan; biaya pengembangan dikapitalisasi jika memenuhi 6 kriteria",
            "initial_measurement": "Biaya perolehan untuk pembelian terpisah; nilai wajar untuk kombinasi bisnis",
            "subsequent_measurement": "Cost model atau revaluation model (jika ada pasar aktif)",
            "amortization": "Untuk masa manfaat terbatas; tidak untuk masa manfaat tidak terbatas",
            "impairment": "Diuji sesuai PSAK 48",
            "disclosures": [
                "Kebijakan akuntansi",
                "Metode amortisasi",
                "Masa manfaat atau tingkat amortisasi",
                "Rekonsiliasi nilai tercatat",
                "Aset yang dihasilkan secara internal",
                "Aset dengan masa manfaat tidak terbatas",
            ],
        }


# ============================================================================
# Kelas untuk kompatibilitas dengan unit test (PSAK19)
# ============================================================================


class PSAK19:
    """
    Wrapper sederhana untuk method yang dipanggil oleh test_psak_rules.py.
    """

    @staticmethod
    def amortize(
        cost: Decimal,
        residual_value: Decimal = Decimal(0),
        useful_life: int | None = None,
        method: str = "straight_line",
    ):
        """
        Menghitung amortisasi tahunan.
        """
        if useful_life is None:
            raise ValueError("indefinite life")

        annual = (cost - residual_value) / Decimal(useful_life)

        class AmortizationResult:
            def __init__(self, annual: Decimal):
                self.annual = annual

        return AmortizationResult(annual)


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak19_validator_instance: PSAK19Validator | None = None


def get_psak19_validator() -> PSAK19Validator:
    global _psak19_validator_instance
    if _psak19_validator_instance is None:
        _psak19_validator_instance = PSAK19Validator()
    return _psak19_validator_instance


AmortizationMethod = PSAK19AmortizationMethod
IntangibleAsset = PSAK19IntangibleAsset
IntangibleAssetMeasurementModel = PSAK19MeasurementModel
IntangibleAssetType = PSAK19IntangibleType
UsefulLifeType = PSAK19UsefulLifeType

# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak19_validator()
    entity_id = uuid4()
    register = validator.create_register(
        entity_id, "PT Inovasi Digital", datetime(2026, 12, 31, tzinfo=UTC)
    )
    patent = validator.create_asset(
        asset_code="PAT-001",
        name="Paten Teknologi XYZ",
        asset_type=PSAK19IntangibleType.PATENT,
        acquisition_method=PSAK19AcquisitionMethod.SEPARATE_PURCHASE,
        measurement_model=PSAK19MeasurementModel.COST,
        acquisition_date=datetime(2022, 1, 1, tzinfo=UTC),
        cost=Decimal("200000000"),
        useful_life_type=PSAK19UsefulLifeType.FINITE,
        useful_life_years=10,
    )
    register = validator.add_asset(register, patent)
    result = validator.validate_register(register)
    print("Validation Result:", json.dumps(result.to_dict(), indent=2))
    print("\nIntangible Register:", json.dumps(register.to_dict(), indent=2, default=str))
