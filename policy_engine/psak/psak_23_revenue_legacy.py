#!/usr/bin/env python3
"""
Module: psak_23_revenue_legacy.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 23: Pendapatan (Legacy - sebelum PSAK 72).
    Mengatur pengakuan pendapatan dari transaksi penjualan barang,
    pemberian jasa, penggunaan aset entitas oleh pihak lain (bunga, royalti, dividen).
    Standar ini masih berlaku untuk entitas yang belum mengadopsi PSAK 72
    (misalnya entitas non-publik atau UMKM). Berbeda dengan PSAK 72,
    tidak menggunakan model 5 langkah.
    Kriteria pengakuan pendapatan: risiko dan manfaat signifikan telah dialihkan,
    entitas tidak lagi terlibat dalam manajerial, jumlah pendapatan dapat diukur
    andal, kemungkinan besar manfaat ekonomi akan mengalir, biaya dapat diukur andal.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap pengakuan pendapatan dan biaya terkait dicatat dengan hash.
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
class PSAK23RevenueType(Enum):
    SALE_OF_GOODS = "penjualan_barang"
    RENDERING_OF_SERVICES = "pemberian_jasa"
    INTEREST = "bunga"
    ROYALTIES = "royalti"
    DIVIDENDS = "dividen"


class PSAK23ServiceCompletionMethod(Enum):
    PERCENTAGE_OF_COMPLETION = "persentase_penyelesaian"  # Metode persentase penyelesaian
    COMPLETED_CONTRACT = "kontrak_selesai"  # Metode kontrak selesai (jika tidak dapat diestimasi)


class PSAK23RevenueRecognitionTiming(Enum):
    AT_POINT_OF_SALE = "saat_penjualan"
    UPON_DELIVERY = "saat_pengiriman"
    OVER_TIME = "sepanjang_waktu"
    UPON_COLLECTION = "saat_penerimaan_kas"  # untuk penjualan cicilan tertentu


class PSAK23ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK23Error(Exception):
    pass


class RevenueRecognitionError(PSAK23Error):
    pass


class ServiceContractNotFoundError(PSAK23Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK23GoodsSale:
    """Penjualan barang."""

    sale_id: UUID
    customer_name: str
    invoice_number: str
    sale_date: datetime
    revenue_amount: Decimal
    cost_of_goods_sold: Decimal
    delivery_date: datetime | None = None
    transfer_of_risks_rewards: bool = True  # Kriteria 1
    no_managerial_involvement: bool = True  # Kriteria 2
    revenue_reliably_measurable: bool = True  # Kriteria 3
    probable_economic_benefits: bool = True  # Kriteria 4
    costs_reliably_measurable: bool = True  # Kriteria 5
    recognition_timing: PSAK23RevenueRecognitionTiming = (
        PSAK23RevenueRecognitionTiming.AT_POINT_OF_SALE
    )
    notes: str = ""

    def meets_criteria(self) -> bool:
        return all(
            [
                self.transfer_of_risks_rewards,
                self.no_managerial_involvement,
                self.revenue_reliably_measurable,
                self.probable_economic_benefits,
                self.costs_reliably_measurable,
            ]
        )

    def gross_profit(self) -> Decimal:
        return self.revenue_amount - self.cost_of_goods_sold

    def to_dict(self) -> dict:
        return {
            "sale_id": str(self.sale_id),
            "customer_name": self.customer_name,
            "invoice_number": self.invoice_number,
            "sale_date": self.sale_date.isoformat(),
            "revenue_amount": str(self.revenue_amount),
            "cost_of_goods_sold": str(self.cost_of_goods_sold),
            "gross_profit": str(self.gross_profit()),
            "delivery_date": self.delivery_date.isoformat() if self.delivery_date else None,
            "meets_criteria": self.meets_criteria(),
            "recognition_timing": self.recognition_timing.value,
            "notes": self.notes,
        }


@dataclass
class PSAK23ServiceContract:
    """Kontrak jasa (termasuk konstruksi)."""

    contract_id: UUID
    contract_number: str
    customer_name: str
    contract_value: Decimal
    start_date: datetime
    estimated_completion_date: datetime
    estimated_total_cost: Decimal
    actual_costs_incurred: Decimal = Decimal(0)
    progress_percentage: Decimal = Decimal(0)  # 0-100
    revenue_recognized_to_date: Decimal = Decimal(0)
    completion_method: PSAK23ServiceCompletionMethod = (
        PSAK23ServiceCompletionMethod.PERCENTAGE_OF_COMPLETION
    )
    notes: str = ""

    @property
    def estimated_profit(self) -> Decimal:
        return self.contract_value - self.estimated_total_cost

    @property
    def current_progress(self) -> Decimal:
        if self.estimated_total_cost <= 0:
            return Decimal(0)
        return (self.actual_costs_incurred / self.estimated_total_cost * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    def revenue_to_recognize(self) -> Decimal:
        if self.completion_method == PSAK23ServiceCompletionMethod.PERCENTAGE_OF_COMPLETION:
            return (self.contract_value * self.current_progress / 100).quantize(
                Decimal("0"), rounding=ROUND_HALF_EVEN
            )
        else:
            return Decimal(0)  # Recognized only upon completion

    def profit_to_recognize(self) -> Decimal:
        if self.completion_method == PSAK23ServiceCompletionMethod.PERCENTAGE_OF_COMPLETION:
            return (self.estimated_profit * self.current_progress / 100).quantize(
                Decimal("0"), rounding=ROUND_HALF_EVEN
            )
        else:
            return Decimal(0)

    def to_dict(self) -> dict:
        return {
            "contract_id": str(self.contract_id),
            "contract_number": self.contract_number,
            "customer_name": self.customer_name,
            "contract_value": str(self.contract_value),
            "start_date": self.start_date.isoformat(),
            "estimated_completion_date": self.estimated_completion_date.isoformat(),
            "estimated_total_cost": str(self.estimated_total_cost),
            "actual_costs_incurred": str(self.actual_costs_incurred),
            "progress_percentage": str(self.progress_percentage),
            "revenue_recognized_to_date": str(self.revenue_recognized_to_date),
            "completion_method": self.completion_method.value,
            "estimated_profit": str(self.estimated_profit),
            "current_progress": str(self.current_progress),
            "revenue_to_recognize": str(self.revenue_to_recognize()),
            "profit_to_recognize": str(self.profit_to_recognize()),
        }


@dataclass
class PSAK23PassiveIncome:
    """Pendapatan pasif (bunga, royalti, dividen)."""

    income_id: UUID
    income_type: PSAK23RevenueType
    amount: Decimal
    accrual_date: datetime
    description: str
    effective_interest_rate: Decimal | None = None  # Untuk bunga
    royalty_rate: Decimal | None = None  # Untuk royalti
    declaration_date: datetime | None = None  # Untuk dividen
    is_recognized: bool = True

    def to_dict(self) -> dict:
        return {
            "income_id": str(self.income_id),
            "income_type": self.income_type.value,
            "amount": str(self.amount),
            "accrual_date": self.accrual_date.isoformat(),
            "description": self.description,
            "effective_interest_rate": str(self.effective_interest_rate)
            if self.effective_interest_rate
            else None,
            "royalty_rate": str(self.royalty_rate) if self.royalty_rate else None,
            "declaration_date": self.declaration_date.isoformat()
            if self.declaration_date
            else None,
            "is_recognized": self.is_recognized,
        }


@dataclass
class PSAK23RevenueSummary:
    """Ringkasan pendapatan untuk suatu periode."""

    summary_id: UUID
    entity_id: UUID
    entity_name: str
    period_start: datetime
    period_end: datetime
    goods_sales: list[PSAK23GoodsSale] = field(default_factory=list)
    service_contracts: list[PSAK23ServiceContract] = field(default_factory=list)
    passive_incomes: list[PSAK23PassiveIncome] = field(default_factory=list)

    def total_goods_revenue(self) -> Decimal:
        return sum(s.revenue_amount for s in self.goods_sales if s.meets_criteria())

    def total_service_revenue(self) -> Decimal:
        total = Decimal(0)
        for contract in self.service_contracts:
            if contract.completion_method == PSAK23ServiceCompletionMethod.PERCENTAGE_OF_COMPLETION:
                total += contract.revenue_to_recognize()
            elif (
                contract.completion_method == PSAK23ServiceCompletionMethod.COMPLETED_CONTRACT
                and contract.current_progress >= 100
            ):
                total += contract.contract_value - contract.revenue_recognized_to_date
        return total

    def total_passive_income(self) -> Decimal:
        return sum(i.amount for i in self.passive_incomes if i.is_recognized)

    def total_revenue(self) -> Decimal:
        return (
            self.total_goods_revenue() + self.total_service_revenue() + self.total_passive_income()
        )

    def to_dict(self) -> dict:
        return {
            "summary_id": str(self.summary_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "goods_revenue": str(self.total_goods_revenue()),
            "service_revenue": str(self.total_service_revenue()),
            "passive_income": str(self.total_passive_income()),
            "total_revenue": str(self.total_revenue()),
            "goods_sales": [s.to_dict() for s in self.goods_sales],
            "service_contracts": [c.to_dict() for c in self.service_contracts],
            "passive_incomes": [i.to_dict() for i in self.passive_incomes],
        }


@dataclass
class PSAK23ValidationResult:
    is_compliant: bool
    compliance_level: PSAK23ComplianceLevel
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
        if self.compliance_level != PSAK23ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK23ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK23ComplianceLevel.FULL:
            self.compliance_level = PSAK23ComplianceLevel.SUBSTANTIAL

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
class PSAK23RevenueService:
    """Service untuk pengakuan pendapatan PSAK 23."""

    @staticmethod
    def recognize_goods_sale(sale: PSAK23GoodsSale) -> PSAK23GoodsSale:
        if not sale.meets_criteria():
            raise RevenueRecognitionError(
                "Penjualan barang tidak memenuhi kriteria pengakuan pendapatan PSAK 23"
            )
        return sale

    @staticmethod
    def recognize_service_revenue(
        contract: PSAK23ServiceContract, as_of_date: datetime
    ) -> PSAK23ServiceContract:
        if contract.completion_method == PSAK23ServiceCompletionMethod.PERCENTAGE_OF_COMPLETION:
            # Update progress based on actual costs
            progress = contract.current_progress
            if progress > 100:
                progress = Decimal(100)
            revenue_to_recognize = (contract.contract_value * progress / 100).quantize(
                Decimal("0"), rounding=ROUND_HALF_EVEN
            )
            # Update recognized revenue
            new_revenue_recognized = revenue_to_recognize
            return PSAK23ServiceContract(
                contract_id=contract.contract_id,
                contract_number=contract.contract_number,
                customer_name=contract.customer_name,
                contract_value=contract.contract_value,
                start_date=contract.start_date,
                estimated_completion_date=contract.estimated_completion_date,
                estimated_total_cost=contract.estimated_total_cost,
                actual_costs_incurred=contract.actual_costs_incurred,
                progress_percentage=progress,
                revenue_recognized_to_date=new_revenue_recognized,
                completion_method=contract.completion_method,
                notes=contract.notes,
            )
        else:
            # Completed contract: recognize only when progress >= 100% (or at completion)
            if contract.current_progress >= 100:
                revenue_to_recognize = contract.contract_value - contract.revenue_recognized_to_date
                new_revenue_recognized = contract.contract_value
                return PSAK23ServiceContract(
                    contract_id=contract.contract_id,
                    contract_number=contract.contract_number,
                    customer_name=contract.customer_name,
                    contract_value=contract.contract_value,
                    start_date=contract.start_date,
                    estimated_completion_date=contract.estimated_completion_date,
                    estimated_total_cost=contract.estimated_total_cost,
                    actual_costs_incurred=contract.actual_costs_incurred,
                    progress_percentage=contract.current_progress,
                    revenue_recognized_to_date=new_revenue_recognized,
                    completion_method=contract.completion_method,
                    notes=contract.notes,
                )
        return contract

    @staticmethod
    def record_actual_cost(
        contract: PSAK23ServiceContract, additional_cost: Decimal
    ) -> PSAK23ServiceContract:
        new_costs = contract.actual_costs_incurred + additional_cost
        return PSAK23ServiceContract(
            contract_id=contract.contract_id,
            contract_number=contract.contract_number,
            customer_name=contract.customer_name,
            contract_value=contract.contract_value,
            start_date=contract.start_date,
            estimated_completion_date=contract.estimated_completion_date,
            estimated_total_cost=contract.estimated_total_cost,
            actual_costs_incurred=new_costs,
            progress_percentage=contract.progress_percentage,
            revenue_recognized_to_date=contract.revenue_recognized_to_date,
            completion_method=contract.completion_method,
            notes=contract.notes,
        )


# ============================================================================
# Rules
# ============================================================================
class PSAK23Rules:
    """Aturan PSAK 23."""

    @staticmethod
    def validate_service_contract(contract: PSAK23ServiceContract) -> PSAK23ValidationResult:
        result = PSAK23ValidationResult(
            is_compliant=True, compliance_level=PSAK23ComplianceLevel.FULL
        )
        if contract.completion_method == PSAK23ServiceCompletionMethod.PERCENTAGE_OF_COMPLETION:
            if contract.estimated_total_cost <= 0:
                result.add_error(
                    "Metode persentase penyelesaian membutuhkan estimasi total biaya yang andal"
                )
            if contract.progress_percentage > 100:
                result.add_error("Progres penyelesaian tidak boleh melebihi 100%")
        return result

    @staticmethod
    def validate_goods_sale(sale: PSAK23GoodsSale) -> PSAK23ValidationResult:
        result = PSAK23ValidationResult(
            is_compliant=True, compliance_level=PSAK23ComplianceLevel.FULL
        )
        if sale.revenue_amount <= 0:
            result.add_error("Jumlah pendapatan harus positif")
        if sale.cost_of_goods_sold < 0:
            result.add_error("Harga pokok penjualan tidak boleh negatif")
        return result

    @staticmethod
    def validate_passive_income(income: PSAK23PassiveIncome) -> PSAK23ValidationResult:
        result = PSAK23ValidationResult(
            is_compliant=True, compliance_level=PSAK23ComplianceLevel.FULL
        )
        if income.amount <= 0:
            result.add_warning("Pendapatan pasif non-positif")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK23Validator:
    def __init__(self):
        self._rules = PSAK23Rules()
        self._service = PSAK23RevenueService()

    def create_goods_sale(
        self,
        customer_name: str,
        invoice_number: str,
        sale_date: datetime,
        revenue_amount: Decimal,
        cost_of_goods_sold: Decimal,
        delivery_date: datetime | None = None,
        transfer_risks_rewards: bool = True,
        no_managerial_involvement: bool = True,
        revenue_reliably_measurable: bool = True,
        probable_benefits: bool = True,
        costs_reliably_measurable: bool = True,
        recognition_timing: PSAK23RevenueRecognitionTiming = PSAK23RevenueRecognitionTiming.AT_POINT_OF_SALE,
    ) -> PSAK23GoodsSale:
        return PSAK23GoodsSale(
            sale_id=uuid4(),
            customer_name=customer_name,
            invoice_number=invoice_number,
            sale_date=sale_date,
            revenue_amount=revenue_amount,
            cost_of_goods_sold=cost_of_goods_sold,
            delivery_date=delivery_date,
            transfer_of_risks_rewards=transfer_risks_rewards,
            no_managerial_involvement=no_managerial_involvement,
            revenue_reliably_measurable=revenue_reliably_measurable,
            probable_economic_benefits=probable_benefits,
            costs_reliably_measurable=costs_reliably_measurable,
            recognition_timing=recognition_timing,
        )

    def create_service_contract(
        self,
        contract_number: str,
        customer_name: str,
        contract_value: Decimal,
        start_date: datetime,
        estimated_completion_date: datetime,
        estimated_total_cost: Decimal,
        completion_method: PSAK23ServiceCompletionMethod = PSAK23ServiceCompletionMethod.PERCENTAGE_OF_COMPLETION,
    ) -> PSAK23ServiceContract:
        return PSAK23ServiceContract(
            contract_id=uuid4(),
            contract_number=contract_number,
            customer_name=customer_name,
            contract_value=contract_value,
            start_date=start_date,
            estimated_completion_date=estimated_completion_date,
            estimated_total_cost=estimated_total_cost,
            completion_method=completion_method,
        )

    def create_passive_income(
        self,
        income_type: PSAK23RevenueType,
        amount: Decimal,
        accrual_date: datetime,
        description: str,
        effective_interest_rate: Decimal | None = None,
        royalty_rate: Decimal | None = None,
        declaration_date: datetime | None = None,
    ) -> PSAK23PassiveIncome:
        return PSAK23PassiveIncome(
            income_id=uuid4(),
            income_type=income_type,
            amount=amount,
            accrual_date=accrual_date,
            description=description,
            effective_interest_rate=effective_interest_rate,
            royalty_rate=royalty_rate,
            declaration_date=declaration_date,
        )

    def create_summary(
        self,
        entity_id: UUID,
        entity_name: str,
        period_start: datetime,
        period_end: datetime,
    ) -> PSAK23RevenueSummary:
        return PSAK23RevenueSummary(
            summary_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            period_start=period_start,
            period_end=period_end,
        )

    def add_goods_sale(
        self, summary: PSAK23RevenueSummary, sale: PSAK23GoodsSale
    ) -> PSAK23RevenueSummary:
        new_sales = [*summary.goods_sales, sale]
        return PSAK23RevenueSummary(
            summary_id=summary.summary_id,
            entity_id=summary.entity_id,
            entity_name=summary.entity_name,
            period_start=summary.period_start,
            period_end=summary.period_end,
            goods_sales=new_sales,
            service_contracts=summary.service_contracts,
            passive_incomes=summary.passive_incomes,
        )

    def add_service_contract(
        self, summary: PSAK23RevenueSummary, contract: PSAK23ServiceContract
    ) -> PSAK23RevenueSummary:
        new_contracts = [*summary.service_contracts, contract]
        return PSAK23RevenueSummary(
            summary_id=summary.summary_id,
            entity_id=summary.entity_id,
            entity_name=summary.entity_name,
            period_start=summary.period_start,
            period_end=summary.period_end,
            goods_sales=summary.goods_sales,
            service_contracts=new_contracts,
            passive_incomes=summary.passive_incomes,
        )

    def add_passive_income(
        self, summary: PSAK23RevenueSummary, income: PSAK23PassiveIncome
    ) -> PSAK23RevenueSummary:
        new_incomes = [*summary.passive_incomes, income]
        return PSAK23RevenueSummary(
            summary_id=summary.summary_id,
            entity_id=summary.entity_id,
            entity_name=summary.entity_name,
            period_start=summary.period_start,
            period_end=summary.period_end,
            goods_sales=summary.goods_sales,
            service_contracts=summary.service_contracts,
            passive_incomes=new_incomes,
        )

    def record_service_cost(
        self, summary: PSAK23RevenueSummary, contract_id: UUID, cost: Decimal
    ) -> PSAK23RevenueSummary:
        new_contracts = []
        for c in summary.service_contracts:
            if c.contract_id == contract_id:
                updated = self._service.record_actual_cost(c, cost)
                new_contracts.append(updated)
            else:
                new_contracts.append(c)
        return PSAK23RevenueSummary(
            summary_id=summary.summary_id,
            entity_id=summary.entity_id,
            entity_name=summary.entity_name,
            period_start=summary.period_start,
            period_end=summary.period_end,
            goods_sales=summary.goods_sales,
            service_contracts=new_contracts,
            passive_incomes=summary.passive_incomes,
        )

    def recognize_service_revenue(
        self, summary: PSAK23RevenueSummary, contract_id: UUID, as_of_date: datetime
    ) -> PSAK23RevenueSummary:
        new_contracts = []
        for c in summary.service_contracts:
            if c.contract_id == contract_id:
                updated = self._service.recognize_service_revenue(c, as_of_date)
                new_contracts.append(updated)
            else:
                new_contracts.append(c)
        return PSAK23RevenueSummary(
            summary_id=summary.summary_id,
            entity_id=summary.entity_id,
            entity_name=summary.entity_name,
            period_start=summary.period_start,
            period_end=summary.period_end,
            goods_sales=summary.goods_sales,
            service_contracts=new_contracts,
            passive_incomes=summary.passive_incomes,
        )

    def validate_summary(self, summary: PSAK23RevenueSummary) -> PSAK23ValidationResult:
        result = PSAK23ValidationResult(
            is_compliant=True, compliance_level=PSAK23ComplianceLevel.FULL
        )
        for sale in summary.goods_sales:
            result = self._merge_results(result, self._rules.validate_goods_sale(sale))
        for contract in summary.service_contracts:
            result = self._merge_results(result, self._rules.validate_service_contract(contract))
        for income in summary.passive_incomes:
            result = self._merge_results(result, self._rules.validate_passive_income(income))
        return result

    def _merge_results(
        self, main: PSAK23ValidationResult, other: PSAK23ValidationResult
    ) -> PSAK23ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK23ComplianceLevel.FULL,
            PSAK23ComplianceLevel.SUBSTANTIAL,
            PSAK23ComplianceLevel.PARTIAL,
            PSAK23ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "goods_sale_criteria": [
                "Risiko dan manfaat signifikan telah dialihkan",
                "Entitas tidak lagi terlibat dalam manajerial",
                "Jumlah pendapatan dapat diukur andal",
                "Kemungkinan besar manfaat ekonomi akan mengalir",
                "Biaya yang terjadi dapat diukur andal",
            ],
            "services": "Dapat menggunakan metode persentase penyelesaian jika estimasi andal, atau metode kontrak selesai",
            "interest": "Diakui menggunakan metode bunga efektif",
            "royalties": "Diakui berdasarkan akrual sesuai substansi perjanjian",
            "dividends": "Diakui saat hak pemegang dividen ditetapkan",
            "disclosures": [
                "Kebijakan akuntansi pendapatan",
                "Jumlah pendapatan per kategori",
                "Metode persentase penyelesaian untuk kontrak jasa",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak23_validator_instance: PSAK23Validator | None = None


def get_psak23_validator() -> PSAK23Validator:
    global _psak23_validator_instance
    if _psak23_validator_instance is None:
        _psak23_validator_instance = PSAK23Validator()
    return _psak23_validator_instance


RevenueRecognitionLegacy = PSAK23RevenueService
RevenueTransaction = PSAK23GoodsSale
# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak23_validator()
    entity_id = uuid4()

    summary = validator.create_summary(
        entity_id=entity_id,
        entity_name="PT Dagang Sejahtera",
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 12, 31, tzinfo=UTC),
    )

    # Goods sale
    sale = validator.create_goods_sale(
        customer_name="Toko ABC",
        invoice_number="INV-001",
        sale_date=datetime(2026, 3, 15, tzinfo=UTC),
        revenue_amount=Decimal("50000000"),
        cost_of_goods_sold=Decimal("30000000"),
        delivery_date=datetime(2026, 3, 16, tzinfo=UTC),
    )
    summary = validator.add_goods_sale(summary, sale)

    # Service contract (percentage of completion)
    contract = validator.create_service_contract(
        contract_number="CONT-001",
        customer_name="PT Proyek",
        contract_value=Decimal("200000000"),
        start_date=datetime(2026, 1, 10, tzinfo=UTC),
        estimated_completion_date=datetime(2026, 12, 31, tzinfo=UTC),
        estimated_total_cost=Decimal("150000000"),
    )
    summary = validator.add_service_contract(summary, contract)
    # Record costs
    summary = validator.record_service_cost(summary, contract.contract_id, Decimal("50000000"))
    # Recognize revenue
    summary = validator.recognize_service_revenue(
        summary, contract.contract_id, datetime(2026, 6, 30, tzinfo=UTC)
    )

    # Passive income
    interest = validator.create_passive_income(
        income_type=PSAK23RevenueType.INTEREST,
        amount=Decimal("5000000"),
        accrual_date=datetime(2026, 12, 31, tzinfo=UTC),
        description="Bunga deposito",
        effective_interest_rate=Decimal("0.06"),
    )
    summary = validator.add_passive_income(summary, interest)

    result = validator.validate_summary(summary)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nRevenue Summary:")
    print(json.dumps(summary.to_dict(), indent=2, default=str))
