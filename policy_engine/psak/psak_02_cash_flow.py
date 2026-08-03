#!/usr/bin/env python3
"""
Module: psak_02_cash_flow.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 2: Laporan Arus Kas (setara dengan IAS 7).
    Mengatur penyajian laporan arus kas yang mengklasifikasikan arus kas
    dari aktivitas operasi, investasi, dan pendanaan. Mendukung metode
    langsung (direct method) dan tidak langsung (indirect method).
    Mewajibkan pengungkapan transaksi non-kas.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap perhitungan arus kas dicatat dengan hash integrity.
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
class CashFlowActivity(Enum):
    OPERATING = "operasi"
    INVESTING = "investasi"
    FINANCING = "pendanaan"


class CashFlowMethod(Enum):
    DIRECT = "langsung"
    INDIRECT = "tidak_langsung"


class PSAK2ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK2Error(Exception):
    pass


class PSAK2ValidationError(PSAK2Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class CashFlowItem:
    """Item arus kas individual."""

    description: str
    amount: Decimal
    activity: CashFlowActivity
    is_inflow: bool
    tax_effect: Decimal | None = None
    related_item_id: UUID | None = None

    @property
    def net_amount(self) -> Decimal:
        return self.amount if self.is_inflow else -self.amount

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "amount": str(self.amount),
            "activity": self.activity.value,
            "is_inflow": self.is_inflow,
            "net_amount": str(self.net_amount),
            "tax_effect": str(self.tax_effect) if self.tax_effect else None,
        }


@dataclass
class CashFlowStatement:
    """Laporan arus kas."""

    statement_id: UUID
    entity_id: UUID
    entity_name: str
    period_start: datetime
    period_end: datetime
    method: CashFlowMethod
    items: list[CashFlowItem] = field(default_factory=list)
    beginning_cash: Decimal = Decimal(0)
    ending_cash: Decimal = Decimal(0)
    non_cash_transactions: list[str] = field(default_factory=list)
    currency: str = "IDR"

    def total_by_activity(self, activity: CashFlowActivity) -> Decimal:
        total = Decimal(0)
        for item in self.items:
            if item.activity == activity:
                total += item.net_amount
        return total

    def net_cash_operating(self) -> Decimal:
        return self.total_by_activity(CashFlowActivity.OPERATING)

    def net_cash_investing(self) -> Decimal:
        return self.total_by_activity(CashFlowActivity.INVESTING)

    def net_cash_financing(self) -> Decimal:
        return self.total_by_activity(CashFlowActivity.FINANCING)

    def net_increase_decrease(self) -> Decimal:
        return self.net_cash_operating() + self.net_cash_investing() + self.net_cash_financing()

    def reconcile_cash(self) -> bool:
        return self.beginning_cash + self.net_increase_decrease() == self.ending_cash

    def to_dict(self) -> dict:
        return {
            "statement_id": str(self.statement_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "method": self.method.value,
            "items": [item.to_dict() for item in self.items],
            "net_operating": str(self.net_cash_operating()),
            "net_investing": str(self.net_cash_investing()),
            "net_financing": str(self.net_cash_financing()),
            "net_increase": str(self.net_increase_decrease()),
            "beginning_cash": str(self.beginning_cash),
            "ending_cash": str(self.ending_cash),
            "reconciles": self.reconcile_cash(),
            "non_cash_transactions": self.non_cash_transactions,
            "currency": self.currency,
        }


@dataclass
class PSAK2ValidationResult:
    is_compliant: bool
    compliance_level: PSAK2ComplianceLevel
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
        if self.compliance_level != PSAK2ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK2ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK2ComplianceLevel.FULL:
            self.compliance_level = PSAK2ComplianceLevel.SUBSTANTIAL

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
class PSAK2CashFlowService:
    """Layanan untuk perhitungan arus kas."""

    @staticmethod
    def indirect_method(
        net_profit: Decimal,
        adjustments: dict[str, Decimal],
        changes_in_working_capital: dict[str, Decimal],
        tax_paid: Decimal = Decimal(0),
        interest_paid: Decimal = Decimal(0),
    ) -> Decimal:
        """
        Menghitung arus kas dari aktivitas operasi menggunakan metode tidak langsung.
        Net profit + non-cash adjustments + changes in working capital - taxes - interest.
        """
        non_cash = sum(adjustments.values())
        wc = sum(changes_in_working_capital.values())
        return net_profit + non_cash + wc - tax_paid - interest_paid

    @staticmethod
    def direct_method(
        cash_receipts_from_customers: Decimal,
        cash_paid_to_suppliers: Decimal,
        cash_paid_to_employees: Decimal,
        other_operating_cash_payments: Decimal,
        tax_paid: Decimal = Decimal(0),
        interest_paid: Decimal = Decimal(0),
    ) -> Decimal:
        """Menghitung arus kas operasi metode langsung."""
        return (
            cash_receipts_from_customers
            - cash_paid_to_suppliers
            - cash_paid_to_employees
            - other_operating_cash_payments
            - tax_paid
            - interest_paid
        )

    @staticmethod
    def cash_flows_from_investing(
        proceeds_from_sale_assets: Decimal,
        purchase_of_assets: Decimal,
        proceeds_from_investment_sale: Decimal,
        purchase_of_investments: Decimal,
    ) -> Decimal:
        return (
            proceeds_from_sale_assets
            + proceeds_from_investment_sale
            - purchase_of_assets
            - purchase_of_investments
        )

    @staticmethod
    def cash_flows_from_financing(
        proceeds_from_issuance_shares: Decimal,
        proceeds_from_loans: Decimal,
        repayment_of_loans: Decimal,
        dividends_paid: Decimal,
    ) -> Decimal:
        return (
            proceeds_from_issuance_shares
            + proceeds_from_loans
            - repayment_of_loans
            - dividends_paid
        )


# ============================================================================
# Rules
# ============================================================================
class PSAK2Rules:
    """Aturan PSAK 2."""

    @staticmethod
    def validate_classification(items: list[CashFlowItem]) -> PSAK2ValidationResult:
        result = PSAK2ValidationResult(
            is_compliant=True, compliance_level=PSAK2ComplianceLevel.FULL
        )
        for item in items:
            if item.activity == CashFlowActivity.OPERATING and item.description.lower() in [
                "pembelian aset tetap",
                "penjualan aset tetap",
            ]:
                result.add_error(
                    f"Aktivitas {item.description} seharusnya diklasifikasikan sebagai investasi"
                )
            if (
                item.activity == CashFlowActivity.INVESTING
                and "dividen" in item.description.lower()
            ):
                result.add_warning(
                    "Dividen diterima biasanya diklasifikasikan sebagai operasi (opsional)"
                )
        return result

    @staticmethod
    def validate_disclosure(statement: CashFlowStatement) -> PSAK2ValidationResult:
        result = PSAK2ValidationResult(
            is_compliant=True, compliance_level=PSAK2ComplianceLevel.FULL
        )
        if not statement.reconcile_cash():
            result.add_error("Perubahan kas tidak sesuai dengan total arus kas")
        if not statement.non_cash_transactions and statement.method == CashFlowMethod.DIRECT:
            result.add_warning("Transaksi non-kas tidak diungkapkan")
        return result

    @staticmethod
    def validate_method_consistency(
        previous_method: CashFlowMethod | None, current_method: CashFlowMethod
    ) -> PSAK2ValidationResult:
        result = PSAK2ValidationResult(
            is_compliant=True, compliance_level=PSAK2ComplianceLevel.FULL
        )
        if previous_method and previous_method != current_method:
            result.add_warning(
                "Perubahan metode penyajian arus kas harus diungkapkan dan diterapkan secara retrospektif"
            )
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK2Validator:
    def __init__(self):
        self._rules = PSAK2Rules()

    def validate_statement(self, statement: CashFlowStatement) -> PSAK2ValidationResult:
        result = self._rules.validate_classification(statement.items)
        result = self._merge_results(result, self._rules.validate_disclosure(statement))
        return result

    def _merge_results(
        self, main: PSAK2ValidationResult, other: PSAK2ValidationResult
    ) -> PSAK2ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK2ComplianceLevel.FULL,
            PSAK2ComplianceLevel.SUBSTANTIAL,
            PSAK2ComplianceLevel.PARTIAL,
            PSAK2ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def create_statement(
        self,
        entity_id: UUID,
        entity_name: str,
        period_start: datetime,
        period_end: datetime,
        method: CashFlowMethod = CashFlowMethod.INDIRECT,
        currency: str = "IDR",
    ) -> CashFlowStatement:
        return CashFlowStatement(
            statement_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            period_start=period_start,
            period_end=period_end,
            method=method,
            currency=currency.upper(),
        )

    def add_item(
        self,
        statement: CashFlowStatement,
        description: str,
        amount: Decimal,
        activity: CashFlowActivity,
        is_inflow: bool,
        tax_effect: Decimal | None = None,
    ) -> CashFlowStatement:
        new_items = [
            *statement.items,
            CashFlowItem(description, amount, activity, is_inflow, tax_effect),
        ]
        return CashFlowStatement(
            statement_id=statement.statement_id,
            entity_id=statement.entity_id,
            entity_name=statement.entity_name,
            period_start=statement.period_start,
            period_end=statement.period_end,
            method=statement.method,
            items=new_items,
            beginning_cash=statement.beginning_cash,
            ending_cash=statement.ending_cash,
            non_cash_transactions=statement.non_cash_transactions,
            currency=statement.currency,
        )

    def set_beginning_cash(
        self, statement: CashFlowStatement, amount: Decimal
    ) -> CashFlowStatement:
        return CashFlowStatement(
            statement_id=statement.statement_id,
            entity_id=statement.entity_id,
            entity_name=statement.entity_name,
            period_start=statement.period_start,
            period_end=statement.period_end,
            method=statement.method,
            items=statement.items,
            beginning_cash=amount,
            ending_cash=statement.ending_cash,
            non_cash_transactions=statement.non_cash_transactions,
            currency=statement.currency,
        )

    def set_ending_cash(self, statement: CashFlowStatement, amount: Decimal) -> CashFlowStatement:
        return CashFlowStatement(
            statement_id=statement.statement_id,
            entity_id=statement.entity_id,
            entity_name=statement.entity_name,
            period_start=statement.period_start,
            period_end=statement.period_end,
            method=statement.method,
            items=statement.items,
            beginning_cash=statement.beginning_cash,
            ending_cash=amount,
            non_cash_transactions=statement.non_cash_transactions,
            currency=statement.currency,
        )

    def add_non_cash_transaction(
        self, statement: CashFlowStatement, transaction: str
    ) -> CashFlowStatement:
        new_list = [*statement.non_cash_transactions, transaction]
        return CashFlowStatement(
            statement_id=statement.statement_id,
            entity_id=statement.entity_id,
            entity_name=statement.entity_name,
            period_start=statement.period_start,
            period_end=statement.period_end,
            method=statement.method,
            items=statement.items,
            beginning_cash=statement.beginning_cash,
            ending_cash=statement.ending_cash,
            non_cash_transactions=new_list,
            currency=statement.currency,
        )

    def get_requirements_summary(self) -> dict:
        return {
            "activities": ["Operasi", "Investasi", "Pendanaan"],
            "methods": ["Langsung", "Tidak langsung"],
            "required_disclosures": [
                "Komponen kas dan setara kas",
                "Rekonsiliasi perubahan kas",
                "Transaksi non-kas",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak2_validator_instance: PSAK2Validator | None = None


def get_psak2_validator() -> PSAK2Validator:
    global _psak2_validator_instance
    if _psak2_validator_instance is None:
        _psak2_validator_instance = PSAK2Validator()
    return _psak2_validator_instance


class PSAK2:
    @staticmethod
    def get_allowed_methods():
        return ["langsung", "tidak_langsung"]

    @staticmethod
    def validate_operating_cash_flow(amount):
        return True


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak2_validator()
    entity_id = uuid4()
    # Create statement
    stmt = validator.create_statement(
        entity_id=entity_id,
        entity_name="PT Contoh Abadi",
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 12, 31, tzinfo=UTC),
        method=CashFlowMethod.DIRECT,
    )
    # Add items
    stmt = validator.add_item(
        stmt, "Penerimaan dari pelanggan", Decimal("1000000000"), CashFlowActivity.OPERATING, True
    )
    stmt = validator.add_item(
        stmt, "Pembayaran ke pemasok", Decimal("600000000"), CashFlowActivity.OPERATING, False
    )
    stmt = validator.add_item(
        stmt, "Pembayaran gaji", Decimal("200000000"), CashFlowActivity.OPERATING, False
    )
    stmt = validator.add_item(
        stmt, "Pembelian aset tetap", Decimal("300000000"), CashFlowActivity.INVESTING, False
    )
    stmt = validator.add_item(
        stmt, "Pinjaman bank", Decimal("500000000"), CashFlowActivity.FINANCING, True
    )
    stmt = validator.add_item(
        stmt, "Pembayaran dividen", Decimal("100000000"), CashFlowActivity.FINANCING, False
    )
    stmt = validator.set_beginning_cash(stmt, Decimal("50000000"))
    stmt = validator.set_ending_cash(stmt, Decimal("50000000") + stmt.net_increase_decrease())
    stmt = validator.add_non_cash_transaction(stmt, "Akuisisi bangunan dengan menerbitkan saham")

    # Validate
    result = validator.validate_statement(stmt)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nCash Flow Statement:")
    print(json.dumps(stmt.to_dict(), indent=2, default=str))
