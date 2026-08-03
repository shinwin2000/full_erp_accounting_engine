"""
Package: application.mappers

Mapping:
- Domain aggregates/entities -> DTO objects (response)
- DTO objects -> Command objects
- Domain events -> Read model updates (projections)

This package contains pure mapping functions with no infrastructure dependencies.
All mappers are stateless and thread-safe.
"""

from __future__ import annotations

# Domain to DTO
from application.mappers.domain_to_dto import (
    DomainToDTOMappingError,
    JournalDomainToDtoMapper,
    dto_to_dict,
    map_ap_invoice_to_response_dto,
    map_ap_payment_to_response_dto,
    map_ar_invoice_to_response_dto,
    map_ar_payment_to_response_dto,
    map_balance_sheet_to_dto,
    map_cash_flow_to_dto,
    map_income_statement_to_dto,
    map_journal_entry_to_response_dto,
    map_journal_line_domain_to_request,
    map_payment_run_to_response_dto,
    map_period_close_to_response_dto,
    map_trial_balance_cube_to_dto,
)

# DTO to Command
from application.mappers.dto_to_command import (
    CreateAPInvoiceCommand,
    CreateARInvoiceCommand,
    ExecutePaymentRunCommand,
    ExecutePeriodCloseCommand,
    GenerateFinancialStatementCommand,
    PostJournalEntryCommand,
    RecordAPPaymentCommand,
    RecordARPaymentCommand,
    SubmitCoretaxCommand,
    dto_to_create_ap_invoice_command,
    dto_to_create_ar_invoice_command,
    dto_to_execute_payment_run_command,
    dto_to_execute_period_close_command,
    dto_to_generate_financial_statement_command,
    dto_to_post_journal_command,
    dto_to_record_ap_payment_command,
    dto_to_record_ar_payment_command,
    dto_to_submit_coretax_command,
    map_dto_to_command,
)

# Event to Read Model
from application.mappers.event_to_read_model import (
    EventHandlerNotFoundError,
    EventToReadModelMappingError,
    ReadModelUpdateError,
    event_to_read_model_registry,
    process_event_for_read_model,
    register_all_handlers,
)

__all__ = [
    "CreateAPInvoiceCommand",
    "CreateARInvoiceCommand",
    "DomainToDTOMappingError",
    "EventHandlerNotFoundError",
    "EventToReadModelMappingError",
    "ExecutePaymentRunCommand",
    "ExecutePeriodCloseCommand",
    "GenerateFinancialStatementCommand",
    "JournalDomainToDtoMapper",
    "PostJournalEntryCommand",
    "ReadModelUpdateError",
    "RecordAPPaymentCommand",
    "RecordARPaymentCommand",
    "SubmitCoretaxCommand",
    "dto_to_create_ap_invoice_command",
    "dto_to_create_ar_invoice_command",
    "dto_to_dict",
    "dto_to_execute_payment_run_command",
    "dto_to_execute_period_close_command",
    "dto_to_generate_financial_statement_command",
    "dto_to_post_journal_command",
    "dto_to_record_ap_payment_command",
    "dto_to_record_ar_payment_command",
    "dto_to_submit_coretax_command",
    "event_to_read_model_registry",
    "map_ap_invoice_to_response_dto",
    "map_ap_payment_to_response_dto",
    "map_ar_invoice_to_response_dto",
    "map_ar_payment_to_response_dto",
    "map_balance_sheet_to_dto",
    "map_cash_flow_to_dto",
    "map_dto_to_command",
    "map_income_statement_to_dto",
    "map_journal_entry_to_response_dto",
    "map_journal_line_domain_to_request",
    "map_payment_run_to_response_dto",
    "map_period_close_to_response_dto",
    "map_trial_balance_cube_to_dto",
    "process_event_for_read_model",
    "register_all_handlers",
]
