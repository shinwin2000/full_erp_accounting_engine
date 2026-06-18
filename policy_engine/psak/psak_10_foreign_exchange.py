#!/usr/bin/env python3
"""
Module: psak_10_foreign_exchange.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 10: Pengaruh Perubahan Kurs Valuta Asing (setara dengan IAS 21).
    Mengatur penentuan mata uang fungsional, penjabaran transaksi mata uang asing,
    pengakuan selisih kurs, dan penjabaran laporan keuangan entitas asing ke
    mata uang penyajian (presentation currency). Mendukung identifikasi indikator
    mata uang fungsional, perhitungan selisih kurs, translasi laporan keuangan,
    dan penyesuaian cumulative translation adjustment (CTA).

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap transaksi valas dan keputusan mata uang fungsional dicatat dengan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class FunctionalCurrencyIndicator(Enum):
    """Indikator penentuan mata uang fungsional."""

    SALES_PRICE_SETTING = "penentuan_harga_jual"
    COMPETITIVE_FORCES = "kekuatan_persaingan"
    LABOR_MATERIAL_COSTS = "biaya_tenaga_kerja_dan_bahan"
    FINANCING_CURRENCY = "mata_uang_pendanaan"
    OPERATING_ACTIVITIES = "aktivitas_operasi"
    REGULATORY_ENVIRONMENT = "lingkungan_regulasi"


class TranslationMethod(Enum):
    """Metode penjabaran laporan keuangan."""

    CLOSING_RATE = "kurs_penutup"  # Aset & liabilitas: kurs penutup
    TEMPORAL = "temporal"  # Metode temporal (untuk hiperinflasi atau kondisi khusus)


class ExchangeDifferenceTreatment(Enum):
    """Perlakuan selisih kurs."""

    RECOGNIZED_IN_PL = "diakui_di_laba_rugi"
    RECOGNIZED_IN_OCI = "diakui_di_penghasilan_komprehensif_lain"  # Untuk investasi neto


class PSAK10ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK10Error(Exception):
    pass


class FunctionalCurrencyNotDeterminedError(PSAK10Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class ExchangeRate:
    """Kurs valuta asing untuk suatu tanggal."""

    currency_code: str
    rate: Decimal  # Nilai dalam IDR (atau mata uang fungsional)
    effective_date: date

    def to_dict(self) -> dict:
        return {
            "currency": self.currency_code,
            "rate": str(self.rate),
            "effective_date": self.effective_date.isoformat(),
        }


@dataclass
class ForeignCurrencyTransaction:
    """Transaksi dalam mata uang asing."""

    transaction_id: UUID
    date: datetime
    foreign_currency: str
    amount_fcy: Decimal
    functional_currency: str
    spot_rate: Decimal
    amount_functional: Decimal
    settlement_date: datetime | None = None
    settlement_rate: Decimal | None = None
    exchange_difference: Decimal = Decimal(0)
    recognized_in: ExchangeDifferenceTreatment = ExchangeDifferenceTreatment.RECOGNIZED_IN_PL

    def __post_init__(self):
        if self.amount_functional == 0:
            self.amount_functional = self.amount_fcy * self.spot_rate

    def calculate_settlement_difference(self) -> Decimal:
        if not self.settlement_date or not self.settlement_rate:
            raise PSAK10Error("Settlement date and rate required")
        settled_functional = self.amount_fcy * self.settlement_rate
        return settled_functional - self.amount_functional

    def to_dict(self) -> dict:
        return {
            "transaction_id": str(self.transaction_id),
            "date": self.date.isoformat(),
            "foreign_currency": self.foreign_currency,
            "amount_fcy": str(self.amount_fcy),
            "spot_rate": str(self.spot_rate),
            "amount_functional": str(self.amount_functional),
            "settlement_date": self.settlement_date.isoformat() if self.settlement_date else None,
            "exchange_difference": str(self.exchange_difference),
        }


@dataclass
class FunctionalCurrencyAssessment:
    """Penilaian dan penetapan mata uang fungsional."""

    assessment_id: UUID
    entity_id: UUID
    assessment_date: datetime
    primary_sales_currency: str
    labor_material_currency: str
    financing_currency: str
    operating_currency: str
    regulatory_currency: str
    determined_currency: str
    indicators_used: list[FunctionalCurrencyIndicator] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "assessment_id": str(self.assessment_id),
            "entity_id": str(self.entity_id),
            "assessment_date": self.assessment_date.isoformat(),
            "primary_sales": self.primary_sales_currency,
            "labor_material": self.labor_material_currency,
            "financing": self.financing_currency,
            "operating": self.operating_currency,
            "regulatory": self.regulatory_currency,
            "determined": self.determined_currency,
            "indicators": [i.value for i in self.indicators_used],
            "reasoning": self.reasoning,
        }


@dataclass
class ForeignOperation:
    """Operasi luar negeri (entitas asing)."""

    operation_id: UUID
    entity_id: UUID
    name: str
    functional_currency: str
    reporting_currency: str
    net_assets_beginning: Decimal
    net_assets_end: Decimal
    cumulative_translation_adjustment: Decimal = Decimal(0)
    opening_rate: Decimal = Decimal(1)
    closing_rate: Decimal = Decimal(1)
    average_rate: Decimal = Decimal(1)

    def translation_adjustment_for_period(self) -> Decimal:
        """Menghitung penyesuaian translasi periode berjalan."""
        # CTA = closing_net_assets * (closing_rate - average_rate) - opening_net_assets * (opening_rate - average_rate)
        # Simplified: selisih antara nilai yang dijabarkan dengan kurs penutup vs kurs rata-rata
        opening_translated = self.net_assets_beginning * self.opening_rate
        closing_translated = self.net_assets_end * self.closing_rate
        average_translated = self.net_assets_end * self.average_rate  # simplified
        return (
            closing_translated
            - average_translated
            - (opening_translated - self.net_assets_beginning * self.average_rate)
        )

    def to_dict(self) -> dict:
        return {
            "operation_id": str(self.operation_id),
            "entity_id": str(self.entity_id),
            "name": self.name,
            "functional_currency": self.functional_currency,
            "reporting_currency": self.reporting_currency,
            "net_assets_beginning": str(self.net_assets_beginning),
            "net_assets_end": str(self.net_assets_end),
            "cumulative_translation_adjustment": str(self.cumulative_translation_adjustment),
            "opening_rate": str(self.opening_rate),
            "closing_rate": str(self.closing_rate),
            "average_rate": str(self.average_rate),
        }


@dataclass
class ForeignExchangeDisclosure:
    """Pengungkapan terkait mata uang asing."""

    disclosure_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_period_end: datetime
    functional_currency: str
    presentation_currency: str
    functional_currency_assessment: FunctionalCurrencyAssessment | None = None
    transactions: list[ForeignCurrencyTransaction] = field(default_factory=list)
    foreign_operations: list[ForeignOperation] = field(default_factory=list)
    total_exchange_differences_pl: Decimal = Decimal(0)
    total_exchange_differences_oci: Decimal = Decimal(0)

    def total_net_exchange_difference(self) -> Decimal:
        return self.total_exchange_differences_pl + self.total_exchange_differences_oci

    def to_dict(self) -> dict:
        return {
            "disclosure_id": str(self.disclosure_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_period_end": self.reporting_period_end.isoformat(),
            "functional_currency": self.functional_currency,
            "presentation_currency": self.presentation_currency,
            "functional_currency_assessment": self.functional_currency_assessment.to_dict()
            if self.functional_currency_assessment
            else None,
            "transactions": [t.to_dict() for t in self.transactions],
            "foreign_operations": [o.to_dict() for o in self.foreign_operations],
            "total_exchange_differences_pl": str(self.total_exchange_differences_pl),
            "total_exchange_differences_oci": str(self.total_exchange_differences_oci),
        }


@dataclass
class PSAK10ValidationResult:
    is_compliant: bool
    compliance_level: PSAK10ComplianceLevel
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
        if self.compliance_level != PSAK10ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK10ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK10ComplianceLevel.FULL:
            self.compliance_level = PSAK10ComplianceLevel.SUBSTANTIAL

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
class PSAK10FunctionalCurrencyService:
    """Service penentuan mata uang fungsional."""

    @staticmethod
    def determine_functional_currency(
        primary_sales_currency: str,
        labor_material_currency: str,
        financing_currency: str,
        operating_currency: str,
        regulatory_currency: str = "IDR",
    ) -> tuple[str, list[FunctionalCurrencyIndicator]]:
        """
        Menentukan mata uang fungsional berdasarkan faktor dominan.
        Biasanya mata uang yang mempengaruhi harga jual, biaya, pendanaan, dan lingkungan operasi.
        """
        currencies = [
            primary_sales_currency,
            labor_material_currency,
            financing_currency,
            operating_currency,
        ]
        # Hitung frekuensi kemunculan (sederhana: pilih yang paling sering muncul)
        from collections import Counter

        counter = Counter(currencies)
        most_common = counter.most_common(1)[0][0]
        indicators = []
        if most_common == primary_sales_currency:
            indicators.append(FunctionalCurrencyIndicator.SALES_PRICE_SETTING)
        if most_common == labor_material_currency:
            indicators.append(FunctionalCurrencyIndicator.LABOR_MATERIAL_COSTS)
        if most_common == financing_currency:
            indicators.append(FunctionalCurrencyIndicator.FINANCING_CURRENCY)
        if most_common == operating_currency:
            indicators.append(FunctionalCurrencyIndicator.OPERATING_ACTIVITIES)
        if regulatory_currency == most_common:
            indicators.append(FunctionalCurrencyIndicator.REGULATORY_ENVIRONMENT)
        if not indicators:
            indicators = [FunctionalCurrencyIndicator.SALES_PRICE_SETTING]
        return most_common, indicators

    @staticmethod
    def can_change_functional_currency(
        old_currency: str,
        new_currency: str,
        has_significant_change: bool,
    ) -> bool:
        """Perubahan mata uang fungsional hanya diperbolehkan jika ada perubahan signifikan dalam transaksi dan kondisi."""
        return has_significant_change and old_currency != new_currency


class PSAK10TranslationService:
    """Service untuk penjabaran laporan keuangan entitas asing."""

    @staticmethod
    def translate_balance_sheet(
        assets_liabilities: dict[str, Decimal],
        closing_rate: Decimal,
        reporting_currency: str,
    ) -> dict[str, Decimal]:
        """Menjabarkan aset dan liabilitas dengan kurs penutup."""
        return {key: value * closing_rate for key, value in assets_liabilities.items()}

    @staticmethod
    def translate_income_statement(
        income_expenses: dict[str, Decimal],
        average_rate: Decimal,
        reporting_currency: str,
    ) -> dict[str, Decimal]:
        """Menjabarkan pendapatan dan beban dengan kurs rata-rata (bisa kurs tanggal transaksi atau rata-rata)."""
        return {key: value * average_rate for key, value in income_expenses.items()}

    @staticmethod
    def calculate_cta(
        opening_net_assets: Decimal,
        closing_net_assets: Decimal,
        opening_rate: Decimal,
        closing_rate: Decimal,
        average_rate: Decimal,
    ) -> Decimal:
        """Menghitung cumulative translation adjustment (CTA) di OCI."""
        # CTA = (closing_net_assets * closing_rate - closing_net_assets * average_rate) -
        #       (opening_net_assets * opening_rate - opening_net_assets * average_rate)
        current_period = closing_net_assets * (closing_rate - average_rate)
        prior_period = opening_net_assets * (opening_rate - average_rate)
        return current_period - prior_period


# ============================================================================
# Rules
# ============================================================================
class PSAK10Rules:
    """Aturan PSAK 10."""

    @staticmethod
    def validate_functional_currency_assessment(
        assessment: FunctionalCurrencyAssessment,
    ) -> PSAK10ValidationResult:
        result = PSAK10ValidationResult(
            is_compliant=True, compliance_level=PSAK10ComplianceLevel.FULL
        )
        if not assessment.determined_currency:
            result.add_error("Mata uang fungsional tidak ditentukan")
        if assessment.determined_currency not in [
            assessment.primary_sales_currency,
            assessment.labor_material_currency,
            assessment.financing_currency,
            assessment.operating_currency,
        ]:
            result.add_warning("Mata uang fungsional tidak sesuai dengan indikator dominan")
        return result

    @staticmethod
    def validate_transaction_classification(
        transactions: list[ForeignCurrencyTransaction],
    ) -> PSAK10ValidationResult:
        result = PSAK10ValidationResult(
            is_compliant=True, compliance_level=PSAK10ComplianceLevel.FULL
        )
        for tx in transactions:
            if tx.amount_functional == 0:
                result.add_error(f"Transaksi {tx.transaction_id} memiliki nilai fungsional nol")
            if tx.spot_rate <= 0:
                result.add_error(f"Kurs spot transaksi {tx.transaction_id} tidak valid")
        return result

    @staticmethod
    def validate_foreign_operation_translation(
        operations: list[ForeignOperation],
    ) -> PSAK10ValidationResult:
        result = PSAK10ValidationResult(
            is_compliant=True, compliance_level=PSAK10ComplianceLevel.FULL
        )
        for op in operations:
            if op.closing_rate <= 0 or op.average_rate <= 0:
                result.add_error(f"Kurs untuk operasi luar negeri {op.name} tidak valid")
            if op.reporting_currency == op.functional_currency:
                result.add_warning(
                    f"Operasi {op.name} memiliki mata uang fungsional sama dengan mata uang penyajian, tidak perlu penjabaran"
                )
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK10Validator:
    def __init__(self):
        self._rules = PSAK10Rules()
        self._func_service = PSAK10FunctionalCurrencyService()
        self._translation_service = PSAK10TranslationService()

    def assess_functional_currency(
        self,
        entity_id: UUID,
        primary_sales_currency: str,
        labor_material_currency: str,
        financing_currency: str,
        operating_currency: str,
        regulatory_currency: str = "IDR",
        reasoning: str = "",
    ) -> FunctionalCurrencyAssessment:
        currency, indicators = self._func_service.determine_functional_currency(
            primary_sales_currency,
            labor_material_currency,
            financing_currency,
            operating_currency,
            regulatory_currency,
        )
        return FunctionalCurrencyAssessment(
            assessment_id=uuid4(),
            entity_id=entity_id,
            assessment_date=datetime.now(UTC),
            primary_sales_currency=primary_sales_currency,
            labor_material_currency=labor_material_currency,
            financing_currency=financing_currency,
            operating_currency=operating_currency,
            regulatory_currency=regulatory_currency,
            determined_currency=currency,
            indicators_used=indicators,
            reasoning=reasoning
            or f"Berdasarkan indikator dominan: {[i.value for i in indicators]}",
        )

    def create_transaction(
        self,
        foreign_currency: str,
        amount_fcy: Decimal,
        functional_currency: str,
        spot_rate: Decimal,
        date: datetime,
        settlement_date: datetime | None = None,
        settlement_rate: Decimal | None = None,
        recognized_in: ExchangeDifferenceTreatment = ExchangeDifferenceTreatment.RECOGNIZED_IN_PL,
    ) -> ForeignCurrencyTransaction:
        amount_func = amount_fcy * spot_rate
        return ForeignCurrencyTransaction(
            transaction_id=uuid4(),
            date=date,
            foreign_currency=foreign_currency.upper(),
            amount_fcy=amount_fcy,
            functional_currency=functional_currency.upper(),
            spot_rate=spot_rate,
            amount_functional=amount_func,
            settlement_date=settlement_date,
            settlement_rate=settlement_rate,
            recognized_in=recognized_in,
        )

    def create_foreign_operation(
        self,
        entity_id: UUID,
        name: str,
        functional_currency: str,
        reporting_currency: str,
        net_assets_beginning: Decimal,
        net_assets_end: Decimal,
        opening_rate: Decimal = Decimal(1),
        closing_rate: Decimal = Decimal(1),
        average_rate: Decimal = Decimal(1),
    ) -> ForeignOperation:
        return ForeignOperation(
            operation_id=uuid4(),
            entity_id=entity_id,
            name=name,
            functional_currency=functional_currency.upper(),
            reporting_currency=reporting_currency.upper(),
            net_assets_beginning=net_assets_beginning,
            net_assets_end=net_assets_end,
            opening_rate=opening_rate,
            closing_rate=closing_rate,
            average_rate=average_rate,
        )

    def create_disclosure(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_period_end: datetime,
        functional_currency: str,
        presentation_currency: str,
        assessment: FunctionalCurrencyAssessment | None = None,
    ) -> ForeignExchangeDisclosure:
        return ForeignExchangeDisclosure(
            disclosure_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_period_end=reporting_period_end,
            functional_currency=functional_currency.upper(),
            presentation_currency=presentation_currency.upper(),
            functional_currency_assessment=assessment,
        )

    def add_transaction(
        self, disclosure: ForeignExchangeDisclosure, transaction: ForeignCurrencyTransaction
    ) -> ForeignExchangeDisclosure:
        new_txns = disclosure.transactions + [transaction]
        total_pl = sum(
            t.exchange_difference
            for t in new_txns
            if t.recognized_in == ExchangeDifferenceTreatment.RECOGNIZED_IN_PL
        )
        total_oci = sum(
            t.exchange_difference
            for t in new_txns
            if t.recognized_in == ExchangeDifferenceTreatment.RECOGNIZED_IN_OCI
        )
        return ForeignExchangeDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_period_end=disclosure.reporting_period_end,
            functional_currency=disclosure.functional_currency,
            presentation_currency=disclosure.presentation_currency,
            functional_currency_assessment=disclosure.functional_currency_assessment,
            transactions=new_txns,
            foreign_operations=disclosure.foreign_operations,
            total_exchange_differences_pl=total_pl,
            total_exchange_differences_oci=total_oci,
        )

    def add_foreign_operation(
        self, disclosure: ForeignExchangeDisclosure, operation: ForeignOperation
    ) -> ForeignExchangeDisclosure:
        new_ops = disclosure.foreign_operations + [operation]
        return ForeignExchangeDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_period_end=disclosure.reporting_period_end,
            functional_currency=disclosure.functional_currency,
            presentation_currency=disclosure.presentation_currency,
            functional_currency_assessment=disclosure.functional_currency_assessment,
            transactions=disclosure.transactions,
            foreign_operations=new_ops,
            total_exchange_differences_pl=disclosure.total_exchange_differences_pl,
            total_exchange_differences_oci=disclosure.total_exchange_differences_oci,
        )

    def update_exchange_difference(
        self, transaction: ForeignCurrencyTransaction, settlement_rate: Decimal
    ) -> ForeignCurrencyTransaction:
        diff = transaction.calculate_settlement_difference()
        transaction.exchange_difference = diff
        transaction.settlement_rate = settlement_rate
        return transaction

    def validate_disclosure(self, disclosure: ForeignExchangeDisclosure) -> PSAK10ValidationResult:
        result = PSAK10ValidationResult(
            is_compliant=True, compliance_level=PSAK10ComplianceLevel.FULL
        )
        if disclosure.functional_currency_assessment:
            result = self._merge_results(
                result,
                self._rules.validate_functional_currency_assessment(
                    disclosure.functional_currency_assessment
                ),
            )
        result = self._merge_results(
            result, self._rules.validate_transaction_classification(disclosure.transactions)
        )
        result = self._merge_results(
            result,
            self._rules.validate_foreign_operation_translation(disclosure.foreign_operations),
        )
        # Additional check: functional currency should be used consistently
        for tx in disclosure.transactions:
            if tx.functional_currency != disclosure.functional_currency:
                result.add_error(
                    f"Transaksi {tx.transaction_id} menggunakan mata uang fungsional {tx.functional_currency} berbeda dari entitas {disclosure.functional_currency}"
                )
        return result

    def _merge_results(
        self, main: PSAK10ValidationResult, other: PSAK10ValidationResult
    ) -> PSAK10ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK10ComplianceLevel.FULL,
            PSAK10ComplianceLevel.SUBSTANTIAL,
            PSAK10ComplianceLevel.PARTIAL,
            PSAK10ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "functional_currency": "Mata uang lingkungan ekonomi utama entitas beroperasi",
            "indicators": ["Penjualan", "Biaya", "Pendanaan", "Aktivitas operasi", "Regulasi"],
            "initial_recognition": "Transaksi mata uang asing dijabarkan ke mata uang fungsional dengan kurs spot tanggal transaksi",
            "subsequent_measurement": "Aset/liabilitas moneter dijabarkan dengan kurs penutup, non-moneter dengan kurs historis",
            "exchange_differences": "Selisih kurs aset/liabilitas moneter diakui di laba rugi",
            "foreign_operations_translation": "Aset/liabilitas: kurs penutup, pendapatan/beban: kurs rata-rata, CTA di OCI",
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak10_validator_instance: PSAK10Validator | None = None


def get_psak10_validator() -> PSAK10Validator:
    global _psak10_validator_instance
    if _psak10_validator_instance is None:
        _psak10_validator_instance = PSAK10Validator()
    return _psak10_validator_instance


FunctionalCurrencyDetermination = FunctionalCurrencyAssessment
ForeignOperationNetInvestment = ForeignOperation
ForeignExchangeRegistry = ForeignExchangeDisclosure
ForeignOperationType = TranslationMethod

# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak10_validator()
    entity_id = uuid4()

    # Assess functional currency
    assessment = validator.assess_functional_currency(
        entity_id=entity_id,
        primary_sales_currency="IDR",
        labor_material_currency="IDR",
        financing_currency="USD",
        operating_currency="IDR",
        regulatory_currency="IDR",
        reasoning="Mayoritas penjualan dan biaya dalam IDR, meskipun pendanaan dalam USD",
    )
    print("Functional currency assessment:", assessment.determined_currency)

    # Create disclosure
    disclosure = validator.create_disclosure(
        entity_id=entity_id,
        entity_name="PT Ekspor Impor",
        reporting_period_end=datetime(2026, 12, 31, tzinfo=UTC),
        functional_currency="IDR",
        presentation_currency="IDR",
        assessment=assessment,
    )

    # Create transaction in USD
    tx = validator.create_transaction(
        foreign_currency="USD",
        amount_fcy=Decimal("10000"),
        functional_currency="IDR",
        spot_rate=Decimal("15200"),
        date=datetime(2026, 6, 15, tzinfo=UTC),
    )
    disclosure = validator.add_transaction(disclosure, tx)

    # Foreign operation
    foreign_op = validator.create_foreign_operation(
        entity_id=uuid4(),
        name="Subsidiary Singapore",
        functional_currency="SGD",
        reporting_currency="IDR",
        net_assets_beginning=Decimal("500000"),
        net_assets_end=Decimal("550000"),
        opening_rate=Decimal("10500"),
        closing_rate=Decimal("10600"),
        average_rate=Decimal("10550"),
    )
    disclosure = validator.add_foreign_operation(disclosure, foreign_op)

    # Validate
    result = validator.validate_disclosure(disclosure)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nDisclosure:")
    print(json.dumps(disclosure.to_dict(), indent=2, default=str))
