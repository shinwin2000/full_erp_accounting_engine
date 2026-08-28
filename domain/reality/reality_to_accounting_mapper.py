#!/usr/bin/env python3

"""
Module: reality_to_accounting_mapper.py
Layer: 5 - Reality, Intent, Causality / Reality
Responsibility: Memetakan event ekonomi ke entri akuntansi (double-entry).
                Menerjemahkan economic events ke dalam jurnal akuntansi
                dengan debit dan kredit yang sesuai berdasarkan chart of accounts,
                kebijakan akuntansi, dan aturan PSAK/IFRS.

Architecture Note:
- Bersih dari dependensi langsung maupun dinamis ke layer Infrastructure/Adapters.
- Menggunakan Dependency Injection untuk menyuntikkan Port implementasi dari luar.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.reality.economic_event_immutable import EconomicEvent, EconomicEventType

logger = logging.getLogger(__name__)


# === SAFE CONVERSION HELPERS ===

ZERO: Decimal = Decimal("0")
VAT_RATE: Decimal = Decimal("0.11")
EPSILON: Decimal = Decimal("0.01")  # toleransi ketidakseimbangan


def _safe_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    """Safely convert to Decimal."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return default


# === 0. CUSTOM EXCEPTIONS ===


class AccountingMapperError(Exception):
    """Base exception untuk semua kesalahan operational pada RealityToAccountingMapper."""
    pass


class MappingNotFoundError(AccountingMapperError):
    """Dilemparkan ketika economic event tidak dapat dicocokkan dengan aturan jurnal mana pun."""
    pass


class MappingImbalanceError(AccountingMapperError):
    """Dilemparkan jika total debit tidak seimbang (balance) dengan total kredit."""
    pass


# === 1. FALLBACK ACCOUNT REPOSITORY ===


class _FallbackAccountRepository:
    """Fallback account repository jika port/adapter eksternal belum disuntikkan."""

    def __init__(self):
        self._accounts: dict[str, dict[str, Any]] = {}
        self._init_default_accounts()

    def _init_default_accounts(self):
        """Inisialisasi akun default untuk testing dan jaminan fallback."""
        default_accounts = [
            ("1.1.01", "Accounts Receivable", "ASSET", "AR Control Account"),
            ("1.1.02", "Allowance for Doubtful Accounts", "CONTRA_ASSET", ""),
            ("1.2.01", "Cash in Bank", "ASSET", ""),
            ("1.2.02", "Petty Cash", "ASSET", ""),
            ("1.3.01", "Inventory", "ASSET", ""),
            ("1.4.01", "Fixed Assets", "ASSET", ""),
            ("1.4.02", "Accumulated Depreciation", "CONTRA_ASSET", ""),
            ("1.5.01", "Intangible Assets", "ASSET", ""),
            ("2.1.01", "Accounts Payable", "LIABILITY", "AP Control Account"),
            ("2.1.02", "Accrued Expenses", "LIABILITY", ""),
            ("2.2.01", "VAT Payable", "LIABILITY", ""),
            ("2.2.02", "VAT Input", "ASSET", ""),
            ("2.3.01", "Income Tax Payable", "LIABILITY", ""),
            ("2.3.02", "Withholding Tax Payable", "LIABILITY", ""),
            ("2.4.01", "Loan Payable", "LIABILITY", ""),
            ("3.1.01", "Share Capital", "EQUITY", ""),
            ("3.2.01", "Retained Earnings", "EQUITY", ""),
            ("4.1.01", "Revenue - Sales", "REVENUE", ""),
            ("4.1.02", "Revenue - Services", "REVENUE", ""),
            ("5.1.01", "Cost of Goods Sold", "EXPENSE", ""),
            ("5.1.02", "Salary Expense", "EXPENSE", ""),
            ("5.1.03", "Rent Expense", "EXPENSE", ""),
            ("5.1.04", "Depreciation Expense", "EXPENSE", ""),
            ("5.1.05", "Interest Expense", "EXPENSE", ""),
            ("5.1.06", "Tax Expense", "EXPENSE", ""),
            ("5.1.07", "Bad Debt Expense", "EXPENSE", ""),
            ("5.1.08", "Professional Fees Expense", "EXPENSE", ""),
            ("5.1.09", "General Expense", "EXPENSE", ""),
            ("6.1.01", "Gain on Asset Disposal", "GAIN", ""),
            ("6.1.02", "Loss on Asset Disposal", "LOSS", ""),
        ]
        for code, name, acct_type, description in default_accounts:
            self._accounts[code] = {
                "account_code": code,
                "account_name": name,
                "account_type": acct_type,
                "description": description,
            }

    async def get_by_code(self, account_code: str, legal_entity_id: UUID) -> dict[str, Any] | None:
        return self._accounts.get(account_code)

    async def get_by_id(self, account_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        return self._accounts.get(str(account_id))


# === 2. FALLBACK POLICY INTERPRETER ===


class _FallbackPolicyInterpreter:
    """Fallback policy interpreter jika policy engine belum disuntikkan."""

    async def evaluate(self, policy_name: str, context: dict[str, Any]) -> dict[str, Any]:
        return {"applied": False, "reason": "Policy engine not available"}


# === 3. ACCOUNTING MAPPING ===


@dataclass(frozen=True)
class AccountingMapping:
    """Hasil pemetaan economic event ke blueprint entri jurnal."""

    debit_accounts: list[tuple[str, Decimal]]  # (account_code, amount)
    credit_accounts: list[tuple[str, Decimal]]  # (account_code, amount)
    description: str
    reference: str
    journal_type: str = "GENERAL"


@dataclass(frozen=True)
class JournalLine:
    """Baris atomik penyusun entri jurnal."""

    account_code: str
    side: str  # "DEBIT" or "CREDIT"
    amount: Decimal
    description: str


@dataclass
class MappedJournal:
    """Jurnal hasil pemetaan utuh yang siap diposting ke ledger."""

    journal_id: UUID
    journal_number: str
    journal_type: str
    transaction_date: datetime
    description: str
    lines: list[JournalLine]
    reference: str
    legal_entity_id: UUID
    created_by: str
    created_at: datetime
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        lines_str = "|".join([f"{line.account_code}:{line.side}:{line.amount}" for line in self.lines])
        content = f"{self.journal_id}|{self.journal_number}|{self.description}|{lines_str}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Convert MappedJournal to dictionary representation."""
        return {
            "journal_id": str(self.journal_id),
            "journal_number": self.journal_number,
            "journal_type": self.journal_type,
            "transaction_date": self.transaction_date.isoformat(),
            "description": self.description,
            "lines": [
                {"account_code": line.account_code, "side": line.side, "amount": str(line.amount)}
                for line in self.lines
            ],
            "reference": self.reference,
            "legal_entity_id": str(self.legal_entity_id),
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "cryptographic_hash": self.cryptographic_hash,
        }


# === 4. REALITY TO ACCOUNTING MAPPER ===


class RealityToAccountingMapper:
    """
    Mapper untuk mengonversi secara deterministik economic events ke jurnal akuntansi.
    Setiap kegagalan pemetaan atau ketidakseimbangan angka akan melempar eror eksplisit.

    PATUH CLEAN ARCHITECTURE: Dependensi disuntikkan dari luar saat konfigurasi sistem.
    """

    _instance: RealityToAccountingMapper | None = None
    _lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls, *args, **kwargs) -> RealityToAccountingMapper:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(
        self, account_repo: Any | None = None, policy_interpreter: Any | None = None
    ) -> None:
        if getattr(self, "_initialized", False):
            if account_repo is not None:
                self._account_repo = account_repo
            if policy_interpreter is not None:
                self._policy_interpreter = policy_interpreter
            return

        self._initialized = True
        self._account_repo = account_repo or _FallbackAccountRepository()
        self._policy_interpreter = policy_interpreter or _FallbackPolicyInterpreter()
        self._mapping_history: list[dict[str, Any]] = []

    def set_dependencies(self, account_repo: Any, policy_interpreter: Any) -> None:
        """Injeksi dependensi eksplisit untuk menghindari impor lintas layer."""
        self._account_repo = account_repo
        self._policy_interpreter = policy_interpreter

    async def map_to_journal(
        self,
        event: EconomicEvent,
        legal_entity_id: UUID,
        user_id: str | None = None,
    ) -> MappedJournal:
        """
        Memetakan economic event ke dalam bentuk double-entry MappedJournal.

        Raises:
            MappingNotFoundError: Jika blueprint pemetaan untuk tipe event tidak ditemukan.
            MappingImbalanceError: Jika total nominal debit dan kredit tidak seimbang.
        """
        mapping = await self._get_mapping(event, legal_entity_id)
        if not mapping:
            raise MappingNotFoundError(
                f"Blueprint pemetaan gagal dibentuk untuk tipe event: {event.event_type.name} "
                f"(ID Event: {event.event_id})"
            )

        lines: list[JournalLine] = []
        for account_code, amount in mapping.debit_accounts:
            lines.append(
                JournalLine(
                    account_code=account_code,
                    side="DEBIT",
                    amount=amount,
                    description=mapping.description,
                )
            )
        for account_code, amount in mapping.credit_accounts:
            lines.append(
                JournalLine(
                    account_code=account_code,
                    side="CREDIT",
                    amount=amount,
                    description=mapping.description,
                )
            )

        # Validasi kesamaan nilai total debit dan kredit
        # PERBAIKAN: Menambahkan ZERO sebagai start value untuk sum()
        total_debit = sum((line.amount for line in lines if line.side == "DEBIT"), ZERO)
        total_credit = sum((line.amount for line in lines if line.side == "CREDIT"), ZERO)

        # Pastikan EPSILON adalah Decimal untuk perbandingan
        if abs(total_debit - total_credit) > EPSILON:
            raise MappingImbalanceError(
                f"Ketidakseimbangan nilai terdeteksi pada pemetaan jurnal! "
                f"Total Debit: {total_debit}, Total Kredit: {total_credit}. "
                f"Selisih: {abs(total_debit - total_credit)}"
            )

        journal = MappedJournal(
            journal_id=uuid4(),
            journal_number=f"EVT-{event.event_date.strftime('%Y%m')}-{str(event.event_id)[:8]}",
            journal_type=mapping.journal_type,
            transaction_date=event.event_date,
            description=mapping.description,
            lines=lines,
            reference=mapping.reference,
            legal_entity_id=legal_entity_id,
            created_by=user_id or event.created_by,
            created_at=datetime.now(UTC),
            cryptographic_hash="",
        )
        journal.cryptographic_hash = journal.compute_hash()

        self._mapping_history.append(
            {
                "event_id": str(event.event_id),
                "journal_id": str(journal.journal_id),
                "mapped_at": datetime.now(UTC).isoformat(),
                "mapped_by": user_id or event.created_by,
            }
        )

        logger.info(f"Berhasil memetakan event {event.event_id} ke jurnal {journal.journal_id}")
        return journal

    async def _get_mapping(
        self,
        event: EconomicEvent,
        legal_entity_id: UUID,
    ) -> AccountingMapping | None:
        """Mengevaluasi rule engine dinamis atau fallback ke static mapping internal."""

        policy_context = {
            "event_type": event.event_type.name,
            "amount": str(event.amount) if event.amount is not None else "0",
            "currency": event.currency if hasattr(event, "currency") else "IDR",
            "customer_id": str(event.counterparty_id) if event.counterparty_id else None,
            "legal_entity_id": str(legal_entity_id),
        }
        policy_result = await self._policy_interpreter.evaluate(
            "accounting_mapping", policy_context
        )
        if policy_result.get("applied"):
            return AccountingMapping(
                debit_accounts=policy_result.get("debits", []),
                credit_accounts=policy_result.get("credits", []),
                description=policy_result.get("description", event.description),
                reference=event.source_document_ref or "",
                journal_type=policy_result.get("journal_type", "GENERAL"),
            )

        # Fallback ke metode pemetaan statis terstruktur
        mappings = {
            EconomicEventType.SALE_OF_GOODS: self._map_sale_of_goods,
            EconomicEventType.SALE_OF_SERVICES: self._map_sale_of_services,
            EconomicEventType.PURCHASE_OF_GOODS: self._map_purchase_of_goods,
            EconomicEventType.PURCHASE_OF_SERVICES: self._map_purchase_of_services,
            EconomicEventType.SALARY_EXPENSE: self._map_salary_expense,
            EconomicEventType.RENT_EXPENSE: self._map_rent_expense,
            EconomicEventType.UTILITY_EXPENSE: self._map_utility_expense,
            EconomicEventType.TAX_EXPENSE: self._map_tax_expense,
            EconomicEventType.INTEREST_EXPENSE: self._map_interest_expense,
            EconomicEventType.CASH_RECEIPT: self._map_cash_receipt,
            EconomicEventType.CASH_DISBURSEMENT: self._map_cash_disbursement,
            EconomicEventType.ASSET_ACQUISITION: self._map_asset_acquisition,
            EconomicEventType.ASSET_DISPOSAL: self._map_asset_disposal,
            EconomicEventType.ASSET_DEPRECIATION: self._map_asset_depreciation,
            EconomicEventType.ASSET_IMPAIRMENT: self._map_asset_impairment,
            EconomicEventType.INVENTORY_RECEIPT: self._map_inventory_receipt,
            EconomicEventType.INVENTORY_ISSUE: self._map_inventory_issue,
            EconomicEventType.LOAN_DRAWDOWN: self._map_loan_drawdown,
            EconomicEventType.LOAN_REPAYMENT: self._map_loan_repayment,
            EconomicEventType.CAPITAL_CONTRIBUTION: self._map_capital_contribution,
            EconomicEventType.CAPITAL_WITHDRAWAL: self._map_capital_withdrawal,
            EconomicEventType.PERIOD_CLOSE: self._map_period_close,
            EconomicEventType.PERIOD_ADJUSTMENT: self._map_period_adjustment,
        }

        mapper = mappings.get(event.event_type)
        if mapper:
            return await mapper(event, legal_entity_id)

        return None

    # === METODE PEMETAAN DETAIL ===

    async def _map_sale_of_goods(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        vat_amount = amount * VAT_RATE

        debit_account = "1.2.01" if event.metadata.get("payment_method") == "CASH" else "1.1.01"

        return AccountingMapping(
            debit_accounts=[(debit_account, amount + vat_amount)],
            credit_accounts=[
                ("4.1.01", amount),  # Revenue - Sales
                ("2.2.01", vat_amount),  # VAT Payable
            ],
            description=f"Sale of goods: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="SALES",
        )

    async def _map_sale_of_services(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        vat_amount = amount * VAT_RATE

        debit_account = "1.2.01" if event.metadata.get("payment_method") == "CASH" else "1.1.01"

        return AccountingMapping(
            debit_accounts=[(debit_account, amount + vat_amount)],
            credit_accounts=[
                ("4.1.02", amount),  # Revenue - Services
                ("2.2.01", vat_amount),  # VAT Payable
            ],
            description=f"Sale of services: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="SALES",
        )

    async def _map_purchase_of_goods(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        vat_amount = amount * VAT_RATE

        credit_account = "1.2.01" if event.metadata.get("payment_method") == "CASH" else "2.1.01"

        return AccountingMapping(
            debit_accounts=[
                ("1.3.01", amount),  # Inventory
                ("2.2.02", vat_amount),  # VAT Input
            ],
            credit_accounts=[(credit_account, amount + vat_amount)],
            description=f"Purchase of goods: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="PURCHASE",
        )

    async def _map_purchase_of_services(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        credit_account = "1.2.01" if event.metadata.get("payment_method") == "CASH" else "2.1.01"

        desc_lower = event.description.lower()
        if "rent" in desc_lower:
            expense_account = "5.1.03"  # Rent Expense
        elif "consulting" in desc_lower:
            expense_account = "5.1.08"  # Professional Fees Expense
        else:
            expense_account = "5.1.09"  # General Expense

        return AccountingMapping(
            debit_accounts=[(expense_account, amount)],
            credit_accounts=[(credit_account, amount)],
            description=f"Purchase of services: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="PURCHASE",
        )

    async def _map_salary_expense(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        return AccountingMapping(
            debit_accounts=[("5.1.02", amount)],  # Salary Expense
            credit_accounts=[("1.2.01", amount)],  # Cash
            description=f"Salary expense: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="PAYROLL",
        )

    async def _map_rent_expense(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        return AccountingMapping(
            debit_accounts=[("5.1.03", amount)],  # Rent Expense
            credit_accounts=[("1.2.01", amount)],  # Cash
            description=f"Rent expense: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="EXPENSE",
        )

    async def _map_utility_expense(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        return AccountingMapping(
            debit_accounts=[("5.1.09", amount)],  # General Expense (Utility fallback)
            credit_accounts=[("1.2.01", amount)],  # Cash
            description=f"Utility expense: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="EXPENSE",
        )

    async def _map_tax_expense(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        credit_account = "2.2.01" if event.metadata.get("tax_type") == "VAT" else "2.3.01"
        return AccountingMapping(
            debit_accounts=[("5.1.06", amount)],  # Tax Expense
            credit_accounts=[(credit_account, amount)],
            description=f"Tax expense: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="TAX",
        )

    async def _map_interest_expense(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        return AccountingMapping(
            debit_accounts=[("5.1.05", amount)],  # Interest Expense
            credit_accounts=[("1.2.01", amount)],  # Cash
            description=f"Interest expense: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="EXPENSE",
        )

    async def _map_cash_receipt(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        credit_account = "1.1.01" if event.metadata.get("applied_to_invoice") else "4.1.01"
        return AccountingMapping(
            debit_accounts=[("1.2.01", amount)],  # Cash in Bank
            credit_accounts=[(credit_account, amount)],
            description=f"Cash receipt: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="CASH",
        )

    async def _map_cash_disbursement(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        debit_account = "2.1.01" if event.metadata.get("applied_to_bill") else "5.1.09"
        return AccountingMapping(
            debit_accounts=[(debit_account, amount)],
            credit_accounts=[("1.2.01", amount)],  # Cash in Bank
            description=f"Cash disbursement: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="CASH",
        )

    async def _map_asset_acquisition(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        debit_account = "1.5.01" if event.metadata.get("asset_type") == "INTANGIBLE" else "1.4.01"
        return AccountingMapping(
            debit_accounts=[(debit_account, amount)],
            credit_accounts=[("1.2.01", amount)],
            description=f"Asset acquisition: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="ASSET",
        )

    async def _map_asset_disposal(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        book_value = event.metadata.get("book_value", ZERO)
        gain_loss = amount - book_value

        debits = [("1.2.01", amount)]
        credits = [("1.4.01", book_value)]

        if gain_loss > 0:
            credits.append(("6.1.01", gain_loss))  # Gain on Asset Disposal
        elif gain_loss < 0:
            debits.append(("6.1.02", abs(gain_loss)))  # Loss on Asset Disposal

        return AccountingMapping(
            debit_accounts=debits,
            credit_accounts=credits,
            description=f"Asset disposal: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="ASSET",
        )

    async def _map_asset_depreciation(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        return AccountingMapping(
            debit_accounts=[("5.1.04", amount)],  # Depreciation Expense
            credit_accounts=[("1.4.02", amount)],  # Accumulated Depreciation
            description=f"Depreciation: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="DEPRECIATION",
        )

    async def _map_asset_impairment(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        return AccountingMapping(
            debit_accounts=[("5.1.07", amount)],  # Bad Debt / Impairment Expense
            credit_accounts=[("1.4.01", amount)],  # Reduce Asset Direct
            description=f"Asset impairment: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="ADJUSTMENT",
        )

    async def _map_inventory_receipt(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        return AccountingMapping(
            debit_accounts=[("1.3.01", amount)],  # Inventory
            credit_accounts=[("2.1.01", amount)],  # Accounts Payable
            description=f"Inventory receipt: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="INVENTORY",
        )

    async def _map_inventory_issue(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        return AccountingMapping(
            debit_accounts=[("5.1.01", amount)],  # Cost of Goods Sold
            credit_accounts=[("1.3.01", amount)],  # Inventory
            description=f"Inventory issue (COGS): {event.description}",
            reference=event.source_document_ref or "",
            journal_type="COGS",
        )

    async def _map_loan_drawdown(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        return AccountingMapping(
            debit_accounts=[("1.2.01", amount)],  # Cash in Bank
            credit_accounts=[("2.4.01", amount)],  # Loan Payable
            description=f"Loan drawdown: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="FINANCING",
        )

    async def _map_loan_repayment(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        principal = event.amount if event.amount is not None else ZERO
        interest = event.metadata.get("interest", ZERO)
        total = principal + interest

        debits = [("2.4.01", principal)]
        if interest > 0:
            debits.append(("5.1.05", interest))  # Interest Expense

        return AccountingMapping(
            debit_accounts=debits,
            credit_accounts=[("1.2.01", total)],  # Cash output
            description=f"Loan repayment: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="FINANCING",
        )

    async def _map_capital_contribution(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        return AccountingMapping(
            debit_accounts=[("1.2.01", amount)],  # Cash in Bank
            credit_accounts=[("3.1.01", amount)],  # Share Capital
            description=f"Capital contribution: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="EQUITY",
        )

    async def _map_capital_withdrawal(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        amount = event.amount if event.amount is not None else ZERO
        return AccountingMapping(
            debit_accounts=[("3.1.01", amount)],  # Share Capital
            credit_accounts=[("1.2.01", amount)],  # Cash
            description=f"Capital withdrawal: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="EQUITY",
        )

    async def _map_period_close(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        return AccountingMapping(
            debit_accounts=[("4.1.01", ZERO)],
            credit_accounts=[("3.2.01", ZERO)],
            description=f"Period close: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="CLOSING",
        )

    async def _map_period_adjustment(
        self, event: EconomicEvent, legal_entity_id: UUID
    ) -> AccountingMapping:
        return AccountingMapping(
            debit_accounts=[],
            credit_accounts=[],
            description=f"Period adjustment empty template: {event.description}",
            reference=event.source_document_ref or "",
            journal_type="ADJUSTING",
        )

    def get_mapping_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._mapping_history[-limit:]


# === 5. SINGLETON ACCESSOR ===

_reality_to_accounting_mapper_instance: RealityToAccountingMapper | None = None


def get_reality_to_accounting_mapper(
    account_repo: Any | None = None, policy_interpreter: Any | None = None
) -> RealityToAccountingMapper:
    """Mendapatkan instance singleton RealityToAccountingMapper dengan injeksi opsional."""
    global _reality_to_accounting_mapper_instance
    if _reality_to_accounting_mapper_instance is None:
        _reality_to_accounting_mapper_instance = RealityToAccountingMapper(
            account_repo=account_repo, policy_interpreter=policy_interpreter
        )
    elif account_repo is not None or policy_interpreter is not None:
        _reality_to_accounting_mapper_instance.set_dependencies(
            account_repo=account_repo, policy_interpreter=policy_interpreter
        )
    return _reality_to_accounting_mapper_instance


# === 6. EXPORTS ===

__all__ = [
    "AccountingMapperError",
    "AccountingMapping",
    "JournalLine",
    "MappedJournal",
    "MappingImbalanceError",
    "MappingNotFoundError",
    "RealityToAccountingMapper",
    "get_reality_to_accounting_mapper",
]
