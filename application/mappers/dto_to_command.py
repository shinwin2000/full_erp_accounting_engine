#!/usr/bin/env python3

"""
Module: dto_to_command.py

Layer: 8 - Application / Mappers

Responsibility:
    Mapping dari DTO objects (Data Transfer Objects) ke Command objects yang
    digunakan oleh Command Bus dan Use Case handlers.

Perbaikan presisi (MNY-003):
    - Mengganti _safe_float() dengan _safe_decimal() untuk nilai moneter
    - Semua konversi nilai moneter menggunakan str() untuk serialisasi
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

# DTO imports
from application.dto_objects.ap_invoice_request import APInvoiceRequestDTO, APPaymentRequestDTO
from application.dto_objects.ar_invoice_request import ARInvoiceRequestDTO, ARPaymentRequestDTO
from application.dto_objects.coretax_submission_request import (
    BuktiPotongPPh23DTO,
    FakturPajakKeluaranDTO,
    SPTMasaPph21Request,
    SPTMasaPpnRequest,
    SPTTahunanBadanRequest,
)
from application.dto_objects.financial_statement_request import FinancialStatementRequestDTO
from application.dto_objects.journal_request import JournalEntryRequestDTO
from application.dto_objects.payment_run_request import PaymentRunRequestDTO
from application.dto_objects.period_close_request import PeriodCloseRequestDTO

logger = logging.getLogger(__name__)


# === SAFE CONVERSION HELPERS ===

ZERO = Decimal("0")


def _safe_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    """Safely convert to Decimal for monetary values."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return default


def _safe_str(value: Any, default: str = "") -> str:
    """Safely convert to string."""
    if value is None:
        return default
    return str(value)


# === 1. COMMAND BASE CLASS ===


@dataclass(kw_only=True)
class Command:
    """Base class untuk semua command."""

    command_id: UUID = field(default_factory=uuid4)
    command_type: str
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=datetime.utcnow)
    user_id: UUID | None = None
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert command to dictionary."""
        return {
            "command_id": str(self.command_id),
            "command_type": self.command_type,
            "correlation_id": self.correlation_id,
            "occurred_at": self.occurred_at.isoformat(),
            "user_id": str(self.user_id) if self.user_id else None,
            "idempotency_key": self.idempotency_key,
        }


# === 2. CONCRETE COMMAND CLASSES ===


@dataclass(kw_only=True)
class PostJournalEntryCommand(Command):
    """Command untuk posting jurnal umum."""

    journal_date: date
    period: str  # Format "YYYY-MM"
    description: str
    lines: list[dict[str, Any]]
    source_system: str = "api"
    attachment_ids: list[UUID] = field(default_factory=list)

    def __post_init__(self):
        self.command_type = "post_journal_entry"


@dataclass(kw_only=True)
class CreateARInvoiceCommand(Command):
    """Command untuk membuat AR Invoice."""

    customer_id: UUID
    invoice_date: date
    due_date: date
    amount: Decimal
    currency: str = "IDR"
    description: str = ""
    tax_code: str | None = None
    sales_order_id: UUID | None = None

    def __post_init__(self):
        self.command_type = "create_ar_invoice"


@dataclass(kw_only=True)
class RecordARPaymentCommand(Command):
    """Command untuk mencatat pembayaran AR."""

    invoice_id: UUID
    payment_date: date
    amount: Decimal
    payment_method: str
    reference_number: str = ""
    bank_account_id: UUID | None = None

    def __post_init__(self):
        self.command_type = "record_ar_payment"


@dataclass(kw_only=True)
class CreateAPInvoiceCommand(Command):
    """Command untuk membuat AP Invoice."""

    vendor_id: UUID
    invoice_date: date
    due_date: date
    amount: Decimal
    currency: str = "IDR"
    description: str = ""
    tax_code: str | None = None
    po_reference: str | None = None
    grn_reference: str | None = None

    def __post_init__(self):
        self.command_type = "create_ap_invoice"


@dataclass(kw_only=True)
class RecordAPPaymentCommand(Command):
    """Command untuk mencatat pembayaran AP."""

    invoice_id: UUID
    payment_date: date
    amount: Decimal
    payment_method: str
    reference_number: str = ""
    bank_account_id: UUID | None = None

    def __post_init__(self):
        self.command_type = "record_ap_payment"


@dataclass(kw_only=True)
class ExecutePaymentRunCommand(Command):
    """Command untuk mengeksekusi payment run."""

    run_date: date
    invoice_ids: list[UUID]
    payment_method: str
    bank_account_id: UUID | None = None

    def __post_init__(self):
        self.command_type = "execute_payment_run"


@dataclass(kw_only=True)
class ExecutePeriodCloseCommand(Command):
    """Command untuk menutup periode akuntansi."""

    period_year: int
    period_month: int
    dry_run: bool = False

    def __post_init__(self):
        self.command_type = "execute_period_close"


@dataclass(kw_only=True)
class GenerateFinancialStatementCommand(Command):
    """Command untuk generate laporan keuangan."""

    legal_entity_id: UUID
    statement_type: str
    period_start: date
    period_end: date
    currency_code: str = "IDR"

    def __post_init__(self):
        self.command_type = "generate_financial_statement"


@dataclass(kw_only=True)
class SubmitCoretaxCommand(Command):
    """Command untuk submit ke Coretax DJP."""

    submission_type: str  # spt_masa_ppn, spt_masa_pph21, faktur_pajak, etc.
    payload: dict[str, Any]

    def __post_init__(self):
        self.command_type = "submit_coretax"


# === 3. MAPPER FUNCTIONS ===


def dto_to_post_journal_command(
    dto: JournalEntryRequestDTO,
    user_id: UUID | None = None,
    correlation_id: str | None = None,
) -> PostJournalEntryCommand:
    """
    Mapping dari JournalEntryRequestDTO ke PostJournalEntryCommand.
    """
    lines = []
    total_debit = ZERO
    total_credit = ZERO

    for line_dto in dto.lines:
        line_debit = _safe_decimal(line_dto.debit)
        line_credit = _safe_decimal(line_dto.credit)

        line_dict = {
            "account_code": line_dto.account_code,
            "debit": line_debit,
            "credit": line_credit,
            "description": line_dto.description,
            "cost_center": line_dto.cost_center,
            "department": line_dto.department,
            "tax_code": line_dto.tax_code,
            "project_code": line_dto.project_code,
            "auxiliary_1": line_dto.auxiliary_1,
            "auxiliary_2": line_dto.auxiliary_2,
        }
        total_debit += line_debit
        total_credit += line_credit
        lines.append(line_dict)

    if total_debit != total_credit:
        raise ValueError(f"Journal not balanced: debit={total_debit}, credit={total_credit}")

    return PostJournalEntryCommand(
        journal_date=dto.journal_date,
        period=dto.period,
        description=dto.description,
        lines=lines,
        source_system=dto.source_system or "api",
        attachment_ids=dto.attachment_ids or [],
        user_id=user_id,
        correlation_id=correlation_id or dto.idempotency_key,
        idempotency_key=dto.idempotency_key,
    )


def dto_to_create_ar_invoice_command(
    dto: ARInvoiceRequestDTO,
    user_id: UUID | None = None,
    correlation_id: str | None = None,
) -> CreateARInvoiceCommand:
    """Mapping ARInvoiceRequestDTO ke CreateARInvoiceCommand."""
    if dto.amount <= 0:
        raise ValueError(f"Invoice amount must be positive: {dto.amount}")

    return CreateARInvoiceCommand(
        customer_id=dto.customer_id,
        invoice_date=dto.invoice_date,
        due_date=dto.due_date,
        amount=dto.amount,
        currency=dto.currency,
        description=dto.description or "",
        tax_code=dto.tax_code,
        sales_order_id=dto.sales_order_id,
        user_id=user_id,
        correlation_id=correlation_id,
        idempotency_key=dto.idempotency_key,
    )


def dto_to_record_ar_payment_command(
    dto: ARPaymentRequestDTO,
    user_id: UUID | None = None,
    correlation_id: str | None = None,
) -> RecordARPaymentCommand:
    """Mapping ARPaymentRequestDTO ke RecordARPaymentCommand."""
    if dto.amount <= 0:
        raise ValueError(f"Payment amount must be positive: {dto.amount}")

    return RecordARPaymentCommand(
        invoice_id=dto.invoice_id,
        payment_date=dto.payment_date,
        amount=dto.amount,
        payment_method=dto.payment_method,
        reference_number=dto.reference_number or "",
        bank_account_id=dto.bank_account_id,
        user_id=user_id,
        correlation_id=correlation_id,
        idempotency_key=dto.idempotency_key,
    )


def dto_to_create_ap_invoice_command(
    dto: APInvoiceRequestDTO,
    user_id: UUID | None = None,
    correlation_id: str | None = None,
) -> CreateAPInvoiceCommand:
    """Mapping APInvoiceRequestDTO ke CreateAPInvoiceCommand."""
    if dto.amount <= 0:
        raise ValueError(f"Invoice amount must be positive: {dto.amount}")

    return CreateAPInvoiceCommand(
        vendor_id=dto.vendor_id,
        invoice_date=dto.invoice_date,
        due_date=dto.due_date,
        amount=dto.amount,
        currency=dto.currency,
        description=dto.description or "",
        tax_code=dto.tax_code,
        po_reference=dto.po_reference,
        grn_reference=dto.grn_reference,
        user_id=user_id,
        correlation_id=correlation_id,
        idempotency_key=dto.idempotency_key,
    )


def dto_to_record_ap_payment_command(
    dto: APPaymentRequestDTO,
    user_id: UUID | None = None,
    correlation_id: str | None = None,
) -> RecordAPPaymentCommand:
    """Mapping APPaymentRequestDTO ke RecordAPPaymentCommand."""
    if dto.amount <= 0:
        raise ValueError(f"Payment amount must be positive: {dto.amount}")

    return RecordAPPaymentCommand(
        invoice_id=dto.invoice_id,
        payment_date=dto.payment_date,
        amount=dto.amount,
        payment_method=dto.payment_method,
        reference_number=dto.reference_number or "",
        bank_account_id=dto.bank_account_id,
        user_id=user_id,
        correlation_id=correlation_id,
        idempotency_key=dto.idempotency_key,
    )


def dto_to_execute_payment_run_command(
    dto: PaymentRunRequestDTO,
    user_id: UUID | None = None,
    correlation_id: str | None = None,
) -> ExecutePaymentRunCommand:
    """Mapping PaymentRunRequestDTO ke ExecutePaymentRunCommand."""
    return ExecutePaymentRunCommand(
        run_date=dto.run_date,
        invoice_ids=dto.invoice_ids,
        payment_method=dto.payment_method,
        bank_account_id=dto.bank_account_id,
        user_id=user_id,
        correlation_id=correlation_id,
        idempotency_key=getattr(dto, "idempotency_key", None),
    )


def dto_to_execute_period_close_command(
    dto: PeriodCloseRequestDTO,
    user_id: UUID | None = None,
    correlation_id: str | None = None,
) -> ExecutePeriodCloseCommand:
    """Mapping PeriodCloseRequestDTO ke ExecutePeriodCloseCommand."""
    return ExecutePeriodCloseCommand(
        period_year=dto.period_year,
        period_month=dto.period_month,
        dry_run=getattr(dto, "dry_run", False),
        user_id=user_id,
        correlation_id=correlation_id,
        idempotency_key=getattr(dto, "idempotency_key", None),
    )


def dto_to_generate_financial_statement_command(
    dto: FinancialStatementRequestDTO,
    user_id: UUID | None = None,
    correlation_id: str | None = None,
) -> GenerateFinancialStatementCommand:
    """Mapping FinancialStatementRequestDTO ke GenerateFinancialStatementCommand."""
    return GenerateFinancialStatementCommand(
        legal_entity_id=dto.legal_entity_id,
        statement_type=dto.statement_type,
        period_start=dto.period_start,
        period_end=dto.period_end,
        currency_code=dto.currency_code,
        user_id=user_id,
        correlation_id=correlation_id,
    )


def dto_to_submit_coretax_command(
    dto: (
        SPTMasaPpnRequest
        | SPTMasaPph21Request
        | SPTTahunanBadanRequest
        | FakturPajakKeluaranDTO
        | BuktiPotongPPh23DTO
    ),
    user_id: UUID | None = None,
    correlation_id: str | None = None,
) -> SubmitCoretaxCommand:
    """
    Mapping Coretax DTO ke SubmitCoretaxCommand.
    """
    # Tentukan tipe submission berdasarkan jenis DTO
    if hasattr(dto, "to_coretax_payload") and callable(dto.to_coretax_payload):
        payload = dto.to_coretax_payload()

        if isinstance(dto, SPTMasaPpnRequest):
            submission_type = "spt_masa_ppn"
        elif isinstance(dto, SPTMasaPph21Request):
            submission_type = "spt_masa_pph21"
        elif isinstance(dto, SPTTahunanBadanRequest):
            submission_type = "spt_tahunan_badan"
        elif isinstance(dto, FakturPajakKeluaranDTO):
            submission_type = "faktur_pajak_keluaran"
        elif isinstance(dto, BuktiPotongPPh23DTO):
            submission_type = "bukti_potong_pph23"
        else:
            submission_type = "coretax_generic"
    else:
        # Generic mapping - gunakan string untuk nilai moneter
        submission_type = dto.__class__.__name__.lower().replace("dto", "")
        payload = {}
        for key, value in dto.__dict__.items():
            if not key.startswith("_"):
                if hasattr(value, "value"):
                    payload[key] = value.value
                elif isinstance(value, (UUID, datetime, date)):
                    payload[key] = str(value)
                elif isinstance(value, Decimal):
                    # Gunakan string untuk presisi, bukan float
                    payload[key] = str(value)
                else:
                    payload[key] = value

    return SubmitCoretaxCommand(
        submission_type=submission_type,
        payload=payload,
        user_id=user_id,
        correlation_id=correlation_id,
        idempotency_key=getattr(dto, "idempotency_key", None),
    )


# === 4. GENERIC DISPATCHER ===


def map_dto_to_command(
    dto: Any,
    user_id: UUID | None = None,
    correlation_id: str | None = None,
) -> Command:
    """
    Generic dispatcher: memilih mapper berdasarkan tipe DTO.
    """
    # Journal
    if hasattr(dto, "journal_date") and hasattr(dto, "lines"):
        return dto_to_post_journal_command(dto, user_id, correlation_id)

    # AR Invoice
    if hasattr(dto, "customer_id") and hasattr(dto, "invoice_date") and hasattr(dto, "amount"):
        if hasattr(dto, "payment_method"):  # Payment
            return dto_to_record_ar_payment_command(dto, user_id, correlation_id)
        return dto_to_create_ar_invoice_command(dto, user_id, correlation_id)

    # AP Invoice
    if hasattr(dto, "vendor_id") and hasattr(dto, "invoice_date") and hasattr(dto, "amount"):
        if hasattr(dto, "payment_method"):  # Payment
            return dto_to_record_ap_payment_command(dto, user_id, correlation_id)
        return dto_to_create_ap_invoice_command(dto, user_id, correlation_id)

    # Payment Run
    if hasattr(dto, "run_date") and hasattr(dto, "invoice_ids"):
        return dto_to_execute_payment_run_command(dto, user_id, correlation_id)

    # Period Close
    if hasattr(dto, "period_year") and hasattr(dto, "period_month"):
        return dto_to_execute_period_close_command(dto, user_id, correlation_id)

    # Financial Statement
    if hasattr(dto, "statement_type") and hasattr(dto, "period_start"):
        return dto_to_generate_financial_statement_command(dto, user_id, correlation_id)

    # Coretax
    if (
        hasattr(dto, "npwp_pemotong")
        or hasattr(dto, "npwp_pemilik")
        or hasattr(dto, "npwp_wajib_pajak")
    ):
        return dto_to_submit_coretax_command(dto, user_id, correlation_id)

    raise TypeError(f"No mapper registered for DTO type: {type(dto)}")


# === 5. EXPORTS ===

__all__ = [
    "Command",
    "CreateAPInvoiceCommand",
    "CreateARInvoiceCommand",
    "ExecutePaymentRunCommand",
    "ExecutePeriodCloseCommand",
    "GenerateFinancialStatementCommand",
    "PostJournalEntryCommand",
    "RecordAPPaymentCommand",
    "RecordARPaymentCommand",
    "SubmitCoretaxCommand",
    "dto_to_create_ap_invoice_command",
    "dto_to_create_ar_invoice_command",
    "dto_to_execute_payment_run_command",
    "dto_to_execute_period_close_command",
    "dto_to_generate_financial_statement_command",
    "dto_to_post_journal_command",
    "dto_to_record_ap_payment_command",
    "dto_to_record_ar_payment_command",
    "dto_to_submit_coretax_command",
    "map_dto_to_command",
]
