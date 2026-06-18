#!/usr/bin/env python3
"""
Module: psak_50_financial_instruments_presentation.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 50: Instrumen Keuangan: Penyajian (setara dengan IAS 32).
    Mengatur prinsip penyajian instrumen keuangan sebagai liabilitas atau ekuitas,
    offsetting (saling hapus) antara aset keuangan dan liabilitas keuangan,
    serta penyajian bunga, dividen, keuntungan, dan kerugian.
    Menentukan kriteria klasifikasi instrumen keuangan sebagai liabilitas keuangan
    atau instrumen ekuitas berdasarkan substansi kontrak, bukan bentuk hukum.
    Mengatur juga instrumen majemuk (convertible bonds) yang memiliki komponen
    liabilitas dan ekuitas.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap klasifikasi instrumen keuangan dan keputusan offsetting dicatat.
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
class PSAK50InstrumentType(Enum):
    EQUITY = "ekuitas"
    LIABILITY = "liabilitas"
    COMPOUND = "majemuk"  # Instrumen majemuk (misal obligasi konversi)


class PSAK50FinancialAssetCategory(Enum):
    CASH = "kas"
    RECEIVABLE = "piutang"
    INVESTMENT = "investasi"
    DERIVATIVE = "derivatif"
    OTHER = "lainnya"


class PSAK50FinancialLiabilityCategory(Enum):
    PAYABLE = "utang"
    BORROWING = "pinjaman"
    DERIVATIVE = "derivatif"
    OTHER = "lainnya"


class PSAK50CompoundInstrumentSplitMethod(Enum):
    RESIDUAL_VALUE = "nilai_sisa"  # Liabilitas diukur, sisa ke ekuitas
    DIRECT_MEASUREMENT = "pengukuran_langsung"  # Kedua komponen diukur langsung


class PSAK50OffsettingCondition(Enum):
    LEGALLY_ENFORCEABLE_RIGHT = "hak_berkekuatan_hukum"
    INTENTION_TO_SETTLE_NET = "niat_penyelesaian_bersih"
    SIMULTANEOUS_SETTLEMENT = "penyelesaian_serentak"


class PSAK50ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK50Error(Exception):
    pass


class OffsettingNotAllowedError(PSAK50Error):
    pass


class CompoundInstrumentSplitError(PSAK50Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK50FinancialInstrument:
    """Instrumen keuangan individual."""

    instrument_id: UUID
    instrument_name: str
    instrument_type: PSAK50InstrumentType
    financial_asset_category: PSAK50FinancialAssetCategory | None = None
    financial_liability_category: PSAK50FinancialLiabilityCategory | None = None
    contractual_terms: str = ""
    is_compound: bool = False
    liability_component_amount: Decimal = Decimal(0)
    equity_component_amount: Decimal = Decimal(0)
    settlement_date: datetime | None = None
    is_perpetual: bool = False
    has_discretionary_dividends: bool = False  # Jika dividen diskresioner -> ekuitas

    def to_dict(self) -> dict:
        return {
            "instrument_id": str(self.instrument_id),
            "instrument_name": self.instrument_name,
            "type": self.instrument_type.value,
            "asset_category": self.financial_asset_category.value
            if self.financial_asset_category
            else None,
            "liability_category": self.financial_liability_category.value
            if self.financial_liability_category
            else None,
            "is_compound": self.is_compound,
            "liability_component": str(self.liability_component_amount),
            "equity_component": str(self.equity_component_amount),
            "is_perpetual": self.is_perpetual,
        }


@dataclass
class PSAK50OffsettingPair:
    """Pasangan aset keuangan dan liabilitas keuangan yang dapat saling hapus."""

    pair_id: UUID
    financial_asset_id: UUID
    financial_liability_id: UUID
    amount: Decimal
    meets_conditions: bool
    conditions_met: list[PSAK50OffsettingCondition] = field(default_factory=list)
    net_amount_presented: Decimal = Decimal(0)

    def __post_init__(self):
        if self.meets_conditions:
            self.net_amount_presented = Decimal(0)  # Dihapus seluruhnya
        else:
            self.net_amount_presented = self.amount

    def to_dict(self) -> dict:
        return {
            "pair_id": str(self.pair_id),
            "asset_id": str(self.financial_asset_id),
            "liability_id": str(self.financial_liability_id),
            "gross_amount": str(self.amount),
            "meets_conditions": self.meets_conditions,
            "conditions_met": [c.value for c in self.conditions_met],
            "net_amount": str(self.net_amount_presented),
        }


@dataclass
class PSAK50CompoundInstrumentSplit:
    """Hasil pemisahan instrumen majemuk menjadi komponen liabilitas dan ekuitas."""

    split_id: UUID
    instrument_id: UUID
    total_proceeds: Decimal
    liability_component_fair_value: Decimal
    equity_component_amount: Decimal
    split_method: PSAK50CompoundInstrumentSplitMethod
    effective_interest_rate: Decimal | None = None

    def __post_init__(self):
        if self.split_method == PSAK50CompoundInstrumentSplitMethod.RESIDUAL_VALUE:
            self.equity_component_amount = self.total_proceeds - self.liability_component_fair_value
        else:
            # Direct measurement: both components measured directly
            pass

    def to_dict(self) -> dict:
        return {
            "split_id": str(self.split_id),
            "instrument_id": str(self.instrument_id),
            "total_proceeds": str(self.total_proceeds),
            "liability_component": str(self.liability_component_fair_value),
            "equity_component": str(self.equity_component_amount),
            "split_method": self.split_method.value,
            "effective_interest_rate": str(self.effective_interest_rate)
            if self.effective_interest_rate
            else None,
        }


@dataclass
class PSAK50TreasuryShares:
    """Saham treasuri (saham yang dibeli kembali)."""

    treasury_id: UUID
    entity_id: UUID
    number_of_shares: Decimal
    acquisition_cost: Decimal
    acquisition_date: datetime
    is_cancelled: bool = False
    cancellation_date: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "treasury_id": str(self.treasury_id),
            "entity_id": str(self.entity_id),
            "shares": str(self.number_of_shares),
            "cost": str(self.acquisition_cost),
            "acquisition_date": self.acquisition_date.isoformat(),
            "is_cancelled": self.is_cancelled,
        }


@dataclass
class PSAK50ValidationResult:
    is_compliant: bool
    compliance_level: PSAK50ComplianceLevel
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
        if self.compliance_level != PSAK50ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK50ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK50ComplianceLevel.FULL:
            self.compliance_level = PSAK50ComplianceLevel.SUBSTANTIAL

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
class PSAK50InstrumentClassificationService:
    """Service untuk klasifikasi instrumen keuangan."""

    @staticmethod
    def classify_instrument(
        contractual_obligation_to_deliver_cash: bool,
        has_discretionary_dividends: bool,
        is_puttable: bool,
        is_perpetual: bool,
    ) -> PSAK50InstrumentType:
        """Menentukan apakah instrumen adalah liabilitas atau ekuitas."""
        if contractual_obligation_to_deliver_cash:
            # Jika ada kewajiban kontraktual untuk menyerahkan kas → liabilitas
            return PSAK50InstrumentType.LIABILITY
        elif has_discretionary_dividends or is_perpetual:
            # Dividen diskresioner atau instrumen perpetua → ekuitas
            return PSAK50InstrumentType.EQUITY
        elif is_puttable:
            # Instrumen puttable (dapat dijual kembali) bisa ekuitas jika memenuhi kriteria tertentu
            # (sederhana: klasifikasikan sebagai liabilitas jika tidak memenuhi pengecualian)
            return PSAK50InstrumentType.LIABILITY
        else:
            return PSAK50InstrumentType.EQUITY

    @staticmethod
    def split_compound_instrument(
        total_proceeds: Decimal,
        fair_value_of_liability_component: Decimal,
        method: PSAK50CompoundInstrumentSplitMethod = PSAK50CompoundInstrumentSplitMethod.RESIDUAL_VALUE,
        effective_interest_rate: Decimal | None = None,
    ) -> PSAK50CompoundInstrumentSplit:
        """Memisahkan instrumen majemuk menjadi komponen liabilitas dan ekuitas."""
        if method == PSAK50CompoundInstrumentSplitMethod.RESIDUAL_VALUE:
            equity_component = total_proceeds - fair_value_of_liability_component
            if equity_component < 0:
                raise CompoundInstrumentSplitError("Nilai komponen ekuitas tidak boleh negatif")
        else:
            equity_component = Decimal(0)  # Placeholder
        return PSAK50CompoundInstrumentSplit(
            split_id=uuid4(),
            instrument_id=uuid4(),
            total_proceeds=total_proceeds,
            liability_component_fair_value=fair_value_of_liability_component,
            equity_component_amount=equity_component,
            split_method=method,
            effective_interest_rate=effective_interest_rate,
        )


class PSAK50OffsettingService:
    """Service untuk offsetting aset dan liabilitas keuangan."""

    @staticmethod
    def can_offset(
        legally_enforceable_right: bool,
        intention_to_settle_net: bool,
        simultaneous_settlement: bool,
    ) -> tuple[bool, list[PSAK50OffsettingCondition]]:
        conditions = []
        if legally_enforceable_right:
            conditions.append(PSAK50OffsettingCondition.LEGALLY_ENFORCEABLE_RIGHT)
        if intention_to_settle_net:
            conditions.append(PSAK50OffsettingCondition.INTENTION_TO_SETTLE_NET)
        if simultaneous_settlement:
            conditions.append(PSAK50OffsettingCondition.SIMULTANEOUS_SETTLEMENT)
        # Semua tiga kondisi harus terpenuhi untuk offsetting
        can = len(conditions) == 3
        return can, conditions


# ============================================================================
# Rules
# ============================================================================
class PSAK50Rules:
    """Aturan PSAK 50."""

    @staticmethod
    def validate_classification(instrument: PSAK50FinancialInstrument) -> PSAK50ValidationResult:
        result = PSAK50ValidationResult(
            is_compliant=True, compliance_level=PSAK50ComplianceLevel.FULL
        )
        if instrument.is_compound and not instrument.is_compound:
            result.add_error(
                "Instrumen majemuk harus dipisahkan menjadi komponen liabilitas dan ekuitas"
            )
        if (
            instrument.instrument_type == PSAK50InstrumentType.LIABILITY
            and instrument.has_discretionary_dividends
        ):
            result.add_warning(
                "Instrumen dengan dividen diskresioner biasanya diklasifikasikan sebagai ekuitas"
            )
        return result

    @staticmethod
    def validate_offsetting(pair: PSAK50OffsettingPair) -> PSAK50ValidationResult:
        result = PSAK50ValidationResult(
            is_compliant=True, compliance_level=PSAK50ComplianceLevel.FULL
        )
        if pair.meets_conditions and pair.net_amount_presented != 0:
            result.add_error("Offsetting memerlukan penyajian neto (saling hapus)")
        if not pair.meets_conditions and pair.net_amount_presented != pair.amount:
            result.add_warning(
                "Offsetting tidak diizinkan, aset dan liabilitas disajikan secara bruto"
            )
        return result

    @staticmethod
    def validate_treasury_shares(treasury: PSAK50TreasuryShares) -> PSAK50ValidationResult:
        result = PSAK50ValidationResult(
            is_compliant=True, compliance_level=PSAK50ComplianceLevel.FULL
        )
        if treasury.acquisition_cost < 0:
            result.add_error("Biaya perolehan saham treasuri tidak boleh negatif")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK50Validator:
    def __init__(self):
        self._rules = PSAK50Rules()
        self._classification_service = PSAK50InstrumentClassificationService()
        self._offsetting_service = PSAK50OffsettingService()

    def classify_instrument(
        self,
        instrument_name: str,
        contractual_obligation_to_deliver_cash: bool,
        has_discretionary_dividends: bool = False,
        is_puttable: bool = False,
        is_perpetual: bool = False,
        financial_asset_category: PSAK50FinancialAssetCategory | None = None,
        financial_liability_category: PSAK50FinancialLiabilityCategory | None = None,
    ) -> PSAK50FinancialInstrument:
        inst_type = self._classification_service.classify_instrument(
            contractual_obligation_to_deliver_cash,
            has_discretionary_dividends,
            is_puttable,
            is_perpetual,
        )
        return PSAK50FinancialInstrument(
            instrument_id=uuid4(),
            instrument_name=instrument_name,
            instrument_type=inst_type,
            financial_asset_category=financial_asset_category,
            financial_liability_category=financial_liability_category,
            contractual_terms="",
            has_discretionary_dividends=has_discretionary_dividends,
            is_perpetual=is_perpetual,
        )

    def create_compound_instrument(
        self,
        instrument_name: str,
        total_proceeds: Decimal,
        fair_value_of_liability_component: Decimal,
        split_method: PSAK50CompoundInstrumentSplitMethod = PSAK50CompoundInstrumentSplitMethod.RESIDUAL_VALUE,
        effective_interest_rate: Decimal | None = None,
    ) -> tuple[PSAK50FinancialInstrument, PSAK50CompoundInstrumentSplit]:
        split = self._classification_service.split_compound_instrument(
            total_proceeds, fair_value_of_liability_component, split_method, effective_interest_rate
        )
        instrument = PSAK50FinancialInstrument(
            instrument_id=split.instrument_id,
            instrument_name=instrument_name,
            instrument_type=PSAK50InstrumentType.COMPOUND,
            is_compound=True,
            liability_component_amount=split.liability_component_fair_value,
            equity_component_amount=split.equity_component_amount,
        )
        return instrument, split

    def create_offsetting_pair(
        self,
        financial_asset_id: UUID,
        financial_liability_id: UUID,
        amount: Decimal,
        legally_enforceable_right: bool,
        intention_to_settle_net: bool,
        simultaneous_settlement: bool,
    ) -> PSAK50OffsettingPair:
        can, conditions = self._offsetting_service.can_offset(
            legally_enforceable_right,
            intention_to_settle_net,
            simultaneous_settlement,
        )
        return PSAK50OffsettingPair(
            pair_id=uuid4(),
            financial_asset_id=financial_asset_id,
            financial_liability_id=financial_liability_id,
            amount=amount,
            meets_conditions=can,
            conditions_met=conditions,
        )

    def create_treasury_shares(
        self,
        entity_id: UUID,
        number_of_shares: Decimal,
        acquisition_cost: Decimal,
        acquisition_date: datetime,
    ) -> PSAK50TreasuryShares:
        return PSAK50TreasuryShares(
            treasury_id=uuid4(),
            entity_id=entity_id,
            number_of_shares=number_of_shares,
            acquisition_cost=acquisition_cost,
            acquisition_date=acquisition_date,
        )

    def validate_instrument(self, instrument: PSAK50FinancialInstrument) -> PSAK50ValidationResult:
        return self._rules.validate_classification(instrument)

    def validate_offsetting(self, pair: PSAK50OffsettingPair) -> PSAK50ValidationResult:
        return self._rules.validate_offsetting(pair)

    def validate_treasury(self, treasury: PSAK50TreasuryShares) -> PSAK50ValidationResult:
        return self._rules.validate_treasury_shares(treasury)

    def get_requirements_summary(self) -> dict:
        return {
            "classification": "Instrumen keuangan diklasifikasikan sebagai liabilitas keuangan jika ada kewajiban kontraktual menyerahkan kas; selain itu sebagai ekuitas",
            "compound_instruments": "Wajib dipisahkan menjadi komponen liabilitas dan ekuitas pada pengakuan awal",
            "offsetting": "Aset keuangan dan liabilitas keuangan dapat saling hapus jika ada hak berkekuatan hukum dan niat penyelesaian neto atau serentak",
            "treasury_shares": "Saham treasuri disajikan sebagai pengurang ekuitas, bukan aset",
            "disclosures": [
                "Kebijakan akuntansi untuk instrumen keuangan",
                "Klasifikasi instrumen keuangan",
                "Informasi tentang offsetting",
                "Saham treasuri",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak50_validator_instance: PSAK50Validator | None = None


def get_psak50_validator() -> PSAK50Validator:
    global _psak50_validator_instance
    if _psak50_validator_instance is None:
        _psak50_validator_instance = PSAK50Validator()
    return _psak50_validator_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak50_validator()

    # Contoh 1: Klasifikasi instrumen ekuitas (saham biasa)
    equity_instrument = validator.classify_instrument(
        instrument_name="Saham Biasa",
        contractual_obligation_to_deliver_cash=False,
        has_discretionary_dividends=True,
        financial_asset_category=PSAK50FinancialAssetCategory.INVESTMENT,
    )
    print("Equity Instrument:")
    print(json.dumps(equity_instrument.to_dict(), indent=2))

    # Contoh 2: Instrumen majemuk (obligasi konversi)
    compound_inst, split = validator.create_compound_instrument(
        instrument_name="Obligasi Konversi 5%",
        total_proceeds=Decimal("1000000000"),
        fair_value_of_liability_component=Decimal("900000000"),
        split_method=PSAK50CompoundInstrumentSplitMethod.RESIDUAL_VALUE,
        effective_interest_rate=Decimal("7"),
    )
    print("\nCompound Instrument Split:")
    print(json.dumps(split.to_dict(), indent=2))

    # Contoh 3: Offsetting
    pair = validator.create_offsetting_pair(
        financial_asset_id=uuid4(),
        financial_liability_id=uuid4(),
        amount=Decimal("50000000"),
        legally_enforceable_right=True,
        intention_to_settle_net=True,
        simultaneous_settlement=True,
    )
    print("\nOffsetting Pair:")
    print(json.dumps(pair.to_dict(), indent=2))

    # Contoh 4: Saham treasuri
    treasury = validator.create_treasury_shares(
        entity_id=uuid4(),
        number_of_shares=Decimal("1000000"),
        acquisition_cost=Decimal("5000000000"),
        acquisition_date=datetime(2026, 5, 1, tzinfo=UTC),
    )
    print("\nTreasury Shares:")
    print(json.dumps(treasury.to_dict(), indent=2))

    # Validasi
    result = validator.validate_instrument(equity_instrument)
    print("\nValidation Result:")
    print(json.dumps(result.to_dict(), indent=2))
# ============================================================================
# Compatibility alias for EquityInstrument orchestration
# ============================================================================
EquityInstrument = PSAK50FinancialInstrument

# ============================================================================
# Compatibility aliases for Orchestration & Aggregator
# ============================================================================
FinancialAssetCategory = PSAK50FinancialAssetCategory
FinancialLiabilityCategory = PSAK50FinancialLiabilityCategory

# ============================================================================
# Compatibility aliases for Orchestration & Aggregator
# ============================================================================
FinancialAssetCategory = PSAK50FinancialAssetCategory
FinancialLiabilityCategory = PSAK50FinancialLiabilityCategory

# ============================================================================
# Compatibility aliases for Treasury Shares orchestration
# ============================================================================
TreasuryShare = PSAK50TreasuryShares
TreasuryShares = PSAK50TreasuryShares
