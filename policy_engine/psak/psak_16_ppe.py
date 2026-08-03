#!/usr/bin/env python3
"""
Module: psak_16_ppe.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 16: Aset Tetap (setara dengan IAS 16).
    Mengatur perlakuan akuntansi untuk aset tetap, termasuk pengakuan,
    pengukuran awal dan setelah pengakuan, depresiasi, dan penghentian
    pengakuan. Mendukung model biaya (cost model) dan model revaluasi
    (revaluation model). Mengatur komponen penting aset (component approach)
    dan pengungkapan yang diperlukan.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap aset tetap, depresiasi, revaluasi, dan penghentian dicatat dengan hash.
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
class PSAK16MeasurementModel(Enum):
    COST = "biaya"
    REVALUATION = "revaluasi"


class PSAK16DepreciationMethod(Enum):
    STRAIGHT_LINE = "garis_lurus"
    DECLINING_BALANCE = "saldo_menurun"
    UNITS_OF_PRODUCTION = "unit_produksi"


# Alias untuk kompatibilitas dengan test_psak_rules.py
DepreciationMethodPSAK = PSAK16DepreciationMethod


class PSAK16AssetCategory(Enum):
    LAND = "tanah"
    BUILDING = "bangunan"
    MACHINERY = "mesin"
    VEHICLE = "kendaraan"
    FURNITURE = "furnitur"
    COMPUTER = "komputer"
    LEASEHOLD_IMPROVEMENT = "perbaikan_sewa"
    OTHER = "lainnya"


class PSAK16RevaluationFrequency(Enum):
    ANNUALLY = "tahunan"
    EVERY_3_YEARS = "3_tahun"
    EVERY_5_YEARS = "5_tahun"
    IRREGULAR = "tidak_beraturan"


class PSAK16ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK16Error(Exception):
    pass


class InvalidRevaluationError(PSAK16Error):
    pass


class AssetNotFoundError(PSAK16Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK16Component:
    """Komponen signifikan dari aset tetap."""

    component_id: UUID
    name: str
    cost: Decimal
    useful_life_years: int
    residual_value: Decimal = Decimal(0)
    depreciation_method: PSAK16DepreciationMethod = PSAK16DepreciationMethod.STRAIGHT_LINE

    def annual_depreciation(self) -> Decimal:
        if self.useful_life_years <= 0:
            return Decimal(0)
        if self.depreciation_method == PSAK16DepreciationMethod.STRAIGHT_LINE:
            return (self.cost - self.residual_value) / Decimal(self.useful_life_years)
        elif self.depreciation_method == PSAK16DepreciationMethod.DECLINING_BALANCE:
            rate = Decimal(2) / Decimal(self.useful_life_years)
            return self.cost * rate
        else:
            return Decimal(0)

    def to_dict(self) -> dict:
        return {
            "component_id": str(self.component_id),
            "name": self.name,
            "cost": str(self.cost),
            "useful_life_years": self.useful_life_years,
            "residual_value": str(self.residual_value),
            "depreciation_method": self.depreciation_method.value,
            "annual_depreciation": str(self.annual_depreciation()),
        }


@dataclass
class PSAK16RevaluationSurplus:
    """Surplus revaluasi untuk suatu aset."""

    surplus_id: UUID
    revaluation_date: datetime
    fair_value_before: Decimal
    fair_value_after: Decimal
    increase_amount: Decimal  # surplus di OCI
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
class PSAK16Asset:
    """Aset tetap individual."""

    asset_id: UUID
    asset_code: str
    name: str
    category: PSAK16AssetCategory
    acquisition_date: datetime
    cost: Decimal
    measurement_model: PSAK16MeasurementModel
    components: list[PSAK16Component] = field(default_factory=list)
    accumulated_depreciation: Decimal = Decimal(0)
    accumulated_impairment: Decimal = Decimal(0)
    revaluation_surplus_history: list[PSAK16RevaluationSurplus] = field(default_factory=list)
    current_revaluation_surplus: Decimal = Decimal(0)
    last_revaluation_date: datetime | None = None
    is_active: bool = True
    disposal_date: datetime | None = None
    disposal_proceeds: Decimal = Decimal(0)
    disposal_cost: Decimal = Decimal(0)

    @property
    def carrying_amount_cost_model(self) -> Decimal:
        return self.cost - self.accumulated_depreciation - self.accumulated_impairment

    @property
    def carrying_amount_revaluation_model(self) -> Decimal:
        if (
            self.measurement_model == PSAK16MeasurementModel.REVALUATION
            and self.revaluation_surplus_history
        ):
            last = self.revaluation_surplus_history[-1]
            return (
                last.fair_value_after - self.accumulated_depreciation - self.accumulated_impairment
            )
        return self.carrying_amount_cost_model

    @property
    def carrying_amount(self) -> Decimal:
        return (
            self.carrying_amount_revaluation_model
            if self.measurement_model == PSAK16MeasurementModel.REVALUATION
            else self.carrying_amount_cost_model
        )

    @property
    def net_book_value(self) -> Decimal:
        return self.carrying_amount

    @property
    def total_useful_life_from_components(self) -> int | None:
        if self.components:
            return max(c.useful_life_years for c in self.components)
        return None

    def annual_depreciation(self) -> Decimal:
        if self.components:
            return sum(c.annual_depreciation() for c in self.components)
        return Decimal(0)

    def to_dict(self) -> dict:
        return {
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "name": self.name,
            "category": self.category.value,
            "acquisition_date": self.acquisition_date.isoformat(),
            "cost": str(self.cost),
            "measurement_model": self.measurement_model.value,
            "components": [c.to_dict() for c in self.components],
            "accumulated_depreciation": str(self.accumulated_depreciation),
            "accumulated_impairment": str(self.accumulated_impairment),
            "carrying_amount": str(self.carrying_amount),
            "current_revaluation_surplus": str(self.current_revaluation_surplus),
            "last_revaluation_date": self.last_revaluation_date.isoformat()
            if self.last_revaluation_date
            else None,
            "is_active": self.is_active,
            "disposal_date": self.disposal_date.isoformat() if self.disposal_date else None,
        }


@dataclass
class PSAK16AssetRegister:
    """Register aset tetap entitas."""

    register_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_date: datetime
    assets: list[PSAK16Asset] = field(default_factory=list)
    revaluation_frequency: PSAK16RevaluationFrequency = PSAK16RevaluationFrequency.ANNUALLY
    depreciation_method_default: PSAK16DepreciationMethod = PSAK16DepreciationMethod.STRAIGHT_LINE

    def total_cost(self) -> Decimal:
        return sum(a.cost for a in self.assets if a.is_active)

    def total_accumulated_depreciation(self) -> Decimal:
        return sum(a.accumulated_depreciation for a in self.assets if a.is_active)

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
            "revaluation_frequency": self.revaluation_frequency.value,
            "depreciation_method_default": self.depreciation_method_default.value,
            "assets": [a.to_dict() for a in self.assets],
            "total_cost": str(self.total_cost()),
            "total_accumulated_depreciation": str(self.total_accumulated_depreciation()),
            "total_carrying_amount": str(self.total_carrying_amount()),
            "total_revaluation_surplus": str(self.total_revaluation_surplus()),
        }


@dataclass
class PSAK16ValidationResult:
    is_compliant: bool
    compliance_level: PSAK16ComplianceLevel
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
        if self.compliance_level != PSAK16ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK16ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK16ComplianceLevel.FULL:
            self.compliance_level = PSAK16ComplianceLevel.SUBSTANTIAL

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
class PSAK16AssetService:
    """Service untuk perhitungan aset tetap."""

    @staticmethod
    def calculate_depreciation_for_period(
        asset: PSAK16Asset,
        start_date: datetime,
        end_date: datetime,
    ) -> Decimal:
        """Menghitung depresiasi untuk periode tertentu (prorata)."""
        if not asset.is_active or (asset.disposal_date and asset.disposal_date <= start_date):
            return Decimal(0)
        annual = asset.annual_depreciation()
        if annual == 0:
            return Decimal(0)
        # Hitung hari dalam tahun
        days_in_period = (end_date - start_date).days
        if days_in_period <= 0:
            return Decimal(0)
        # Asumsi 365 hari setahun
        return (annual * Decimal(days_in_period) / Decimal(365)).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    @staticmethod
    def revalue_asset(
        asset: PSAK16Asset,
        new_fair_value: Decimal,
        valuation_date: datetime,
        performed_by: str,
    ) -> PSAK16Asset:
        if asset.measurement_model != PSAK16MeasurementModel.REVALUATION:
            raise InvalidRevaluationError("Aset tidak menggunakan model revaluasi")
        old_carrying = asset.carrying_amount
        increase = new_fair_value - old_carrying
        if increase > 0:
            new_surplus = PSAK16RevaluationSurplus(
                surplus_id=uuid4(),
                revaluation_date=valuation_date,
                fair_value_before=old_carrying,
                fair_value_after=new_fair_value,
                increase_amount=increase,
                performed_by=performed_by,
                effective_date=valuation_date,
            )
            new_history = [*asset.revaluation_surplus_history, new_surplus]
            new_current_surplus = asset.current_revaluation_surplus + increase
            # Reset accumulated depreciation and impairment after revaluation
            return PSAK16Asset(
                asset_id=asset.asset_id,
                asset_code=asset.asset_code,
                name=asset.name,
                category=asset.category,
                acquisition_date=asset.acquisition_date,
                cost=asset.cost,
                measurement_model=asset.measurement_model,
                components=asset.components,
                accumulated_depreciation=Decimal(0),
                accumulated_impairment=Decimal(0),
                revaluation_surplus_history=new_history,
                current_revaluation_surplus=new_current_surplus,
                last_revaluation_date=valuation_date,
                is_active=asset.is_active,
                disposal_date=asset.disposal_date,
                disposal_proceeds=asset.disposal_proceeds,
                disposal_cost=asset.disposal_cost,
            )
        else:
            # Decrease charged to P&L (impairment), not surplus
            new_impairment = asset.accumulated_impairment + abs(increase)
            return PSAK16Asset(
                asset_id=asset.asset_id,
                asset_code=asset.asset_code,
                name=asset.name,
                category=asset.category,
                acquisition_date=asset.acquisition_date,
                cost=asset.cost,
                measurement_model=asset.measurement_model,
                components=asset.components,
                accumulated_depreciation=asset.accumulated_depreciation,
                accumulated_impairment=new_impairment,
                revaluation_surplus_history=asset.revaluation_surplus_history,
                current_revaluation_surplus=asset.current_revaluation_surplus,
                last_revaluation_date=valuation_date,
                is_active=asset.is_active,
                disposal_date=asset.disposal_date,
                disposal_proceeds=asset.disposal_proceeds,
                disposal_cost=asset.disposal_cost,
            )

    @staticmethod
    def calculate_gain_loss_on_disposal(asset: PSAK16Asset) -> Decimal:
        carrying = asset.carrying_amount
        net_proceeds = asset.disposal_proceeds - asset.disposal_cost
        return net_proceeds - carrying


# ============================================================================
# Rules
# ============================================================================
class PSAK16Rules:
    """Aturan PSAK 16."""

    @staticmethod
    def validate_measurement_consistency(register: PSAK16AssetRegister) -> PSAK16ValidationResult:
        result = PSAK16ValidationResult(
            is_compliant=True, compliance_level=PSAK16ComplianceLevel.FULL
        )
        models = {a.measurement_model for a in register.assets}
        if len(models) > 1:
            result.add_warning("Beberapa aset menggunakan model pengukuran berbeda")
        return result

    @staticmethod
    def validate_revaluation_frequency(register: PSAK16AssetRegister) -> PSAK16ValidationResult:
        result = PSAK16ValidationResult(
            is_compliant=True, compliance_level=PSAK16ComplianceLevel.FULL
        )
        for asset in register.assets:
            if (
                asset.measurement_model == PSAK16MeasurementModel.REVALUATION
                and asset.last_revaluation_date
            ):
                years_diff = (register.reporting_date - asset.last_revaluation_date).days / 365.25
                if (
                    register.revaluation_frequency == PSAK16RevaluationFrequency.ANNUALLY
                    and years_diff > 1
                ):
                    result.add_warning(f"Aset {asset.asset_code} belum direvaluasi dalam 1 tahun")
                elif (
                    register.revaluation_frequency == PSAK16RevaluationFrequency.EVERY_3_YEARS
                    and years_diff > 3
                ):
                    result.add_warning(f"Aset {asset.asset_code} belum direvaluasi dalam 3 tahun")
                elif (
                    register.revaluation_frequency == PSAK16RevaluationFrequency.EVERY_5_YEARS
                    and years_diff > 5
                ):
                    result.add_warning(f"Aset {asset.asset_code} belum direvaluasi dalam 5 tahun")
        return result

    @staticmethod
    def validate_component_depreciation(asset: PSAK16Asset) -> PSAK16ValidationResult:
        result = PSAK16ValidationResult(
            is_compliant=True, compliance_level=PSAK16ComplianceLevel.FULL
        )
        if not asset.components and asset.cost > Decimal("1000000000"):
            result.add_warning(
                f"Aset {asset.asset_code} bernilai besar tanpa identifikasi komponen"
            )
        return result

    @staticmethod
    def validate_disclosure(register: PSAK16AssetRegister) -> PSAK16ValidationResult:
        result = PSAK16ValidationResult(
            is_compliant=True, compliance_level=PSAK16ComplianceLevel.FULL
        )
        if not register.assets:
            result.add_warning("Tidak ada aset tetap yang dicatat")
        # Rekonsiliasi nilai tercatat
        return result

    # ===== METODE BARU UNTUK KOMPATIBILITAS DENGAN TEST =====
    @staticmethod
    def calculate_depreciation(
        cost: Decimal,
        salvage_value: Decimal,
        useful_life_years: int,
        method: PSAK16DepreciationMethod,
        current_year: int,
    ) -> Decimal:
        """
        Hitung depresiasi untuk tahun tertentu (digunakan oleh test_psak_rules).
        """
        if useful_life_years <= 0:
            return Decimal(0)
        if method == PSAK16DepreciationMethod.STRAIGHT_LINE:
            annual = (cost - salvage_value) / Decimal(useful_life_years)
            # Depresiasi garis lurus konstan setiap tahun
            return annual
        elif method == PSAK16DepreciationMethod.DECLINING_BALANCE:
            rate = Decimal(2) / Decimal(useful_life_years)
            book_value = cost
            for _ in range(1, current_year):
                dep = book_value * rate
                book_value -= dep
            dep_current = book_value * rate
            # Pastikan tidak kurang dari salvage_value
            if book_value - dep_current < salvage_value:
                dep_current = book_value - salvage_value
            return dep_current
        else:
            # Units of production tidak diimplementasikan di test
            return Decimal(0)

    @staticmethod
    def validate_revaluation_model(
        fair_value: Decimal,
        carrying_amount: Decimal,
        has_appraisal: bool,
    ) -> PSAK16ValidationResult:
        """
        Validasi apakah revaluasi diperbolehkan (digunakan oleh test_psak_rules).
        """
        result = PSAK16ValidationResult(
            is_compliant=True, compliance_level=PSAK16ComplianceLevel.FULL
        )
        if not has_appraisal:
            result.add_error("Revaluation requires an independent appraisal.")
        if fair_value <= 0:
            result.add_error("Fair value must be positive.")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK16Validator:
    def __init__(self):
        self._rules = PSAK16Rules()
        self._service = PSAK16AssetService()

    def create_asset(
        self,
        asset_code: str,
        name: str,
        category: PSAK16AssetCategory,
        acquisition_date: datetime,
        cost: Decimal,
        measurement_model: PSAK16MeasurementModel = PSAK16MeasurementModel.COST,
        useful_life_years: int | None = None,
        residual_value: Decimal = Decimal(0),
        depreciation_method: PSAK16DepreciationMethod | None = None,
    ) -> PSAK16Asset:
        if depreciation_method is None:
            depreciation_method = PSAK16DepreciationMethod.STRAIGHT_LINE
        return PSAK16Asset(
            asset_id=uuid4(),
            asset_code=asset_code,
            name=name,
            category=category,
            acquisition_date=acquisition_date,
            cost=cost,
            measurement_model=measurement_model,
        )

    def add_component(
        self,
        asset: PSAK16Asset,
        component_name: str,
        cost: Decimal,
        useful_life_years: int,
        residual_value: Decimal = Decimal(0),
        depreciation_method: PSAK16DepreciationMethod = PSAK16DepreciationMethod.STRAIGHT_LINE,
    ) -> PSAK16Asset:
        new_component = PSAK16Component(
            component_id=uuid4(),
            name=component_name,
            cost=cost,
            useful_life_years=useful_life_years,
            residual_value=residual_value,
            depreciation_method=depreciation_method,
        )
        new_components = [*asset.components, new_component]
        return PSAK16Asset(
            asset_id=asset.asset_id,
            asset_code=asset.asset_code,
            name=asset.name,
            category=asset.category,
            acquisition_date=asset.acquisition_date,
            cost=asset.cost,
            measurement_model=asset.measurement_model,
            components=new_components,
            accumulated_depreciation=asset.accumulated_depreciation,
            accumulated_impairment=asset.accumulated_impairment,
            revaluation_surplus_history=asset.revaluation_surplus_history,
            current_revaluation_surplus=asset.current_revaluation_surplus,
            last_revaluation_date=asset.last_revaluation_date,
            is_active=asset.is_active,
            disposal_date=asset.disposal_date,
            disposal_proceeds=asset.disposal_proceeds,
            disposal_cost=asset.disposal_cost,
        )

    def create_register(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_date: datetime,
        revaluation_frequency: PSAK16RevaluationFrequency = PSAK16RevaluationFrequency.ANNUALLY,
    ) -> PSAK16AssetRegister:
        return PSAK16AssetRegister(
            register_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_date=reporting_date,
            revaluation_frequency=revaluation_frequency,
        )

    def add_asset(self, register: PSAK16AssetRegister, asset: PSAK16Asset) -> PSAK16AssetRegister:
        new_assets = [*register.assets, asset]
        return PSAK16AssetRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            reporting_date=register.reporting_date,
            assets=new_assets,
            revaluation_frequency=register.revaluation_frequency,
            depreciation_method_default=register.depreciation_method_default,
        )

    def record_depreciation(
        self,
        register: PSAK16AssetRegister,
        asset_id: UUID,
        period_end: datetime,
    ) -> PSAK16AssetRegister:
        new_assets = []
        for asset in register.assets:
            if asset.asset_id == asset_id:
                dep = self._service.calculate_depreciation_for_period(
                    asset, asset.acquisition_date, period_end
                )
                new_dep = asset.accumulated_depreciation + dep
                updated_asset = PSAK16Asset(
                    asset_id=asset.asset_id,
                    asset_code=asset.asset_code,
                    name=asset.name,
                    category=asset.category,
                    acquisition_date=asset.acquisition_date,
                    cost=asset.cost,
                    measurement_model=asset.measurement_model,
                    components=asset.components,
                    accumulated_depreciation=new_dep,
                    accumulated_impairment=asset.accumulated_impairment,
                    revaluation_surplus_history=asset.revaluation_surplus_history,
                    current_revaluation_surplus=asset.current_revaluation_surplus,
                    last_revaluation_date=asset.last_revaluation_date,
                    is_active=asset.is_active,
                    disposal_date=asset.disposal_date,
                    disposal_proceeds=asset.disposal_proceeds,
                    disposal_cost=asset.disposal_cost,
                )
                new_assets.append(updated_asset)
            else:
                new_assets.append(asset)
        return PSAK16AssetRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            reporting_date=register.reporting_date,
            assets=new_assets,
            revaluation_frequency=register.revaluation_frequency,
            depreciation_method_default=register.depreciation_method_default,
        )

    def revalue_asset(
        self,
        register: PSAK16AssetRegister,
        asset_id: UUID,
        new_fair_value: Decimal,
        valuation_date: datetime,
        performed_by: str,
    ) -> PSAK16AssetRegister:
        new_assets = []
        for asset in register.assets:
            if asset.asset_id == asset_id:
                updated_asset = self._service.revalue_asset(
                    asset, new_fair_value, valuation_date, performed_by
                )
                new_assets.append(updated_asset)
            else:
                new_assets.append(asset)
        return PSAK16AssetRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            reporting_date=register.reporting_date,
            assets=new_assets,
            revaluation_frequency=register.revaluation_frequency,
            depreciation_method_default=register.depreciation_method_default,
        )

    def dispose_asset(
        self,
        register: PSAK16AssetRegister,
        asset_id: UUID,
        disposal_date: datetime,
        proceeds: Decimal,
        cost: Decimal = Decimal(0),
    ) -> tuple[PSAK16AssetRegister, Decimal]:
        gain_loss = Decimal(0)
        new_assets = []
        for asset in register.assets:
            if asset.asset_id == asset_id:
                if not asset.is_active:
                    raise PSAK16Error(f"Aset {asset.asset_code} sudah tidak aktif")
                # Hitung gain/loss
                carrying = asset.carrying_amount
                net_proceeds = proceeds - cost
                gain_loss = net_proceeds - carrying
                # Tandai sebagai disposed
                updated_asset = PSAK16Asset(
                    asset_id=asset.asset_id,
                    asset_code=asset.asset_code,
                    name=asset.name,
                    category=asset.category,
                    acquisition_date=asset.acquisition_date,
                    cost=asset.cost,
                    measurement_model=asset.measurement_model,
                    components=asset.components,
                    accumulated_depreciation=asset.accumulated_depreciation,
                    accumulated_impairment=asset.accumulated_impairment,
                    revaluation_surplus_history=asset.revaluation_surplus_history,
                    current_revaluation_surplus=asset.current_revaluation_surplus,
                    last_revaluation_date=asset.last_revaluation_date,
                    is_active=False,
                    disposal_date=disposal_date,
                    disposal_proceeds=proceeds,
                    disposal_cost=cost,
                )
                new_assets.append(updated_asset)
            else:
                new_assets.append(asset)
        return (
            PSAK16AssetRegister(
                register_id=register.register_id,
                entity_id=register.entity_id,
                entity_name=register.entity_name,
                reporting_date=register.reporting_date,
                assets=new_assets,
                revaluation_frequency=register.revaluation_frequency,
                depreciation_method_default=register.depreciation_method_default,
            ),
            gain_loss,
        )

    def validate_register(self, register: PSAK16AssetRegister) -> PSAK16ValidationResult:
        result = self._rules.validate_measurement_consistency(register)
        result = self._merge_results(result, self._rules.validate_revaluation_frequency(register))
        for asset in register.assets:
            if asset.is_active:
                result = self._merge_results(
                    result, self._rules.validate_component_depreciation(asset)
                )
        result = self._merge_results(result, self._rules.validate_disclosure(register))
        return result

    def _merge_results(
        self, main: PSAK16ValidationResult, other: PSAK16ValidationResult
    ) -> PSAK16ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK16ComplianceLevel.FULL,
            PSAK16ComplianceLevel.SUBSTANTIAL,
            PSAK16ComplianceLevel.PARTIAL,
            PSAK16ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "recognition": "Aset tetap diakui jika kemungkinan besar manfaat ekonomi akan mengalir dan biaya dapat diukur secara andal",
            "initial_measurement": "Biaya perolehan (purchase price + import duties + direct attributable costs)",
            "subsequent_measurement": "Cost model atau revaluation model",
            "depreciation": "Sistematis alokasi nilai yang dapat disusutkan selama masa manfaat",
            "component_approach": "Komponen signifikan harus disusutkan secara terpisah",
            "revaluation": "Revaluasi harus dilakukan secara teratur; surplus diakui di OCI (kecuali membalik penurunan sebelumnya)",
            "derecognition": "Dihentikan pengakuannya saat dilepas atau tidak ada manfaat ekonomi masa depan",
            "disclosures": [
                "Kebijakan akuntansi",
                "Metode depresiasi",
                "Masa manfaat",
                "Rekonsiliasi nilai tercatat awal dan akhir",
                "Aset yang dijaminkan",
                "Informasi revaluasi",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak16_validator_instance: PSAK16Validator | None = None


def get_psak16_validator() -> PSAK16Validator:
    global _psak16_validator_instance
    if _psak16_validator_instance is None:
        _psak16_validator_instance = PSAK16Validator()
    return _psak16_validator_instance


# ============================================================================
# PSAK16 class for test compatibility (simple facade)
# ============================================================================


class PSAK16:
    """
    Simple facade for PSAK 16 tests.
    Provides static methods: depreciate(...) and is_revaluation_allowed(asset_type)
    """

    class DepreciationResult:
        def __init__(self, annual: Decimal):
            self.annual = annual

    @staticmethod
    def depreciate(
        cost: Decimal,
        residual_value: Decimal,
        useful_life: int,
        method: str,
    ) -> DepreciationResult:
        """
        Calculate annual depreciation.
        Supports "straight_line" method.
        """
        if method == "straight_line":
            annual = (cost - residual_value) / Decimal(useful_life)
        elif method == "declining_balance":
            rate = Decimal(2) / Decimal(useful_life)
            annual = cost * rate
        else:
            annual = Decimal(0)
        annual = annual.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        return PSAK16.DepreciationResult(annual)

    @staticmethod
    def is_revaluation_allowed(asset_type: str) -> bool:
        """
        Return True if revaluation is allowed for the given asset type.
        PSAK 16 allows revaluation for all asset types if there is an active market.
        For simplicity, always return True (unless asset_type is something specific).
        """
        # For land and buildings, revaluation is common.
        # For other assets, still allowed if active market exists.
        return True


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak16_validator()
    entity_id = uuid4()

    register = validator.create_register(
        entity_id=entity_id,
        entity_name="PT Aset Tetap",
        reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
        revaluation_frequency=PSAK16RevaluationFrequency.ANNUALLY,
    )

    # Asset 1: Building (cost model)
    building = validator.create_asset(
        asset_code="BDG-01",
        name="Gedung Kantor",
        category=PSAK16AssetCategory.BUILDING,
        acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        cost=Decimal("5000000000"),
    )
    building = validator.add_component(
        building, "Struktur", Decimal("3000000000"), 50, Decimal("300000000")
    )
    building = validator.add_component(building, "AC", Decimal("1000000000"), 15, Decimal("0"))
    building = validator.add_component(building, "Lift", Decimal("1000000000"), 20, Decimal("0"))
    register = validator.add_asset(register, building)

    # Asset 2: Vehicle (revaluation model)
    vehicle = validator.create_asset(
        asset_code="CAR-01",
        name="Mobil Operasional",
        category=PSAK16AssetCategory.VEHICLE,
        acquisition_date=datetime(2022, 6, 1, tzinfo=UTC),
        cost=Decimal("500000000"),
        measurement_model=PSAK16MeasurementModel.REVALUATION,
    )
    register = validator.add_asset(register, vehicle)

    # Record depreciation for building
    register = validator.record_depreciation(register, building.asset_id, register.reporting_date)

    # Revalue vehicle
    register = validator.revalue_asset(
        register,
        vehicle.asset_id,
        Decimal("600000000"),
        datetime(2026, 12, 31, tzinfo=UTC),
        "Appraiser",
    )

    # Validate
    result = validator.validate_register(register)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nAsset Register:")
    print(json.dumps(register.to_dict(), indent=2, default=str))
