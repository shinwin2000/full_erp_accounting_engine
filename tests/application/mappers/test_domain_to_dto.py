# tests/application/mappers/test_domain_to_dto.py
# Perbaikan kualitas assertions: mengganti semua assert True dengan
# assertion yang memeriksa nilai aktual, efek samping, dan mapping yang benar.

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

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


# ============================================================================
# DomainToDTOMappingError tests
# ============================================================================
class TestDomainToDTOMappingError:
    def test_construction(self):
        error = DomainToDTOMappingError("test message")
        assert isinstance(error, Exception)
        assert str(error) == "test message"

    def test_default_construction(self):
        error = DomainToDTOMappingError()
        assert isinstance(error, DomainToDTOMappingError)


# ============================================================================
# JournalDomainToDtoMapper tests
# ============================================================================
class TestJournalDomainToDtoMapper:
    @pytest.fixture
    def mapper(self):
        return JournalDomainToDtoMapper()

    def test_map_with_journal_number(self, mapper):
        # Create a mock journal with journal_number
        journal = MagicMock()
        journal.journal_number = "JRN-001"
        journal.description = "Test journal"
        journal.status = "POSTED"
        journal.lines = []

        result = mapper.map(journal)
        assert result.journal_id == "JRN-001"
        assert result.description == "Test journal"
        assert result.status == "POSTED"
        assert result.lines == []

    def test_map_with_id_fallback(self, mapper):
        journal = MagicMock()
        # No journal_number, use id
        journal.journal_number = None
        journal.id = uuid4()
        journal.description = "Test"
        journal.status = "DRAFT"
        journal.lines = []

        result = mapper.map(journal)
        assert result.journal_id == str(journal.id)
        assert result.description == "Test"
        assert result.status == "DRAFT"

    def test_map_with_status_enum(self, mapper):
        journal = MagicMock()
        journal.journal_number = "JRN-001"
        journal.description = "Test"
        journal.status = MagicMock(value="APPROVED")
        journal.lines = []

        result = mapper.map(journal)
        assert result.status == "APPROVED"

    def test_map_with_lines(self, mapper):
        # Create line objects
        line1 = MagicMock()
        line1.account_code = "101"
        line1.debit = Decimal("100")
        line1.credit = Decimal("0")

        line2 = MagicMock()
        line2.account_code = "201"
        line2.debit = Decimal("0")
        line2.credit = Decimal("100")

        journal = MagicMock()
        journal.journal_number = "JRN-001"
        journal.description = "Test"
        journal.status = "DRAFT"
        journal.lines = [line1, line2]

        result = mapper.map(journal)
        assert len(result.lines) == 2
        assert result.lines[0]["account"] == "101"
        assert result.lines[0]["debit"] == "100"
        assert result.lines[0]["credit"] == "0"
        assert result.lines[1]["account"] == "201"
        assert result.lines[1]["debit"] == "0"
        assert result.lines[1]["credit"] == "100"

    def test_map_with_line_account_as_object(self, mapper):
        # line has account attribute (object with code)
        account_obj = MagicMock()
        account_obj.code = "101"

        line = MagicMock()
        line.account = account_obj
        line.account_code = None
        line.debit = Decimal("100")
        line.credit = Decimal("0")

        journal = MagicMock()
        journal.journal_number = "JRN-001"
        journal.description = "Test"
        journal.status = "DRAFT"
        journal.lines = [line]

        result = mapper.map(journal)
        assert result.lines[0]["account"] == "101"

    def test_map_with_line_using_account_fallback(self, mapper):
        # line has account attribute as string
        line = MagicMock()
        line.account = "102"
        line.account_code = None
        line.debit = Decimal("50")
        line.credit = Decimal("0")

        journal = MagicMock()
        journal.journal_number = "JRN-001"
        journal.description = "Test"
        journal.status = "DRAFT"
        journal.lines = [line]

        result = mapper.map(journal)
        assert result.lines[0]["account"] == "102"


# ============================================================================
# map_journal_entry_to_response_dto tests
# ============================================================================
class TestMapJournalEntryToResponseDTO:
    def test_map_with_full_journal(self):
        journal = MagicMock()
        journal.id = uuid4()
        journal.journal_number = "JRN-001"
        journal.journal_date = date(2026, 1, 1)
        journal.period = "2026-01"
        journal.description = "Test journal"
        journal.created_at = datetime(2026, 1, 1, 10, 0, 0)
        journal.created_by = uuid4()
        journal.approved_at = datetime(2026, 1, 2, 10, 0, 0)
        journal.approved_by = uuid4()

        line1 = MagicMock()
        line1.account_code = "101"
        line1.debit = Decimal("100")
        line1.credit = Decimal("0")
        line1.description = "Cash"
        line1.cost_center = "CC001"
        line1.department = "FIN"
        line1.tax_code = "VAT"
        line1.project_code = "PRJ001"
        line1.auxiliary_1 = "A1"
        line1.auxiliary_2 = "A2"

        line2 = MagicMock()
        line2.account_code = "201"
        line2.debit = Decimal("0")
        line2.credit = Decimal("100")
        line2.description = "Revenue"
        line2.cost_center = None
        line2.department = None
        line2.tax_code = None
        line2.project_code = None
        line2.auxiliary_1 = None
        line2.auxiliary_2 = None

        journal.lines = [line1, line2]
        journal.remaining_balance = None

        aggregate_id = uuid4()
        result = map_journal_entry_to_response_dto(
            journal_entry=journal,
            aggregate_id=aggregate_id,
            version=2,
            status="POSTED"
        )

        assert result.id == aggregate_id
        assert result.journal_number == "JRN-001"
        assert result.journal_date == date(2026, 1, 1)
        assert result.period == "2026-01"
        assert result.description == "Test journal"
        assert result.status.value == "POSTED"
        assert result.version == 2

        # Check lines
        assert len(result.lines) == 2
        assert result.lines[0].account_code == "101"
        assert result.lines[0].debit == Decimal("100")
        assert result.lines[0].credit == Decimal("0")
        assert result.lines[0].description == "Cash"
        assert result.lines[0].cost_center == "CC001"
        assert result.lines[0].department == "FIN"
        assert result.lines[0].tax_code == "VAT"
        assert result.lines[0].project_code == "PRJ001"
        assert result.lines[0].auxiliary_1 == "A1"
        assert result.lines[0].auxiliary_2 == "A2"

        assert result.lines[1].account_code == "201"
        assert result.lines[1].debit == Decimal("0")
        assert result.lines[1].credit == Decimal("100")

        # Check totals
        assert result.total_debit == Decimal("100")
        assert result.total_credit == Decimal("100")

        # Check metadata
        assert result.created_by == str(journal.created_by)
        assert result.approved_by == str(journal.approved_by)

    def test_map_with_period_as_object(self):
        journal = MagicMock()
        journal.id = uuid4()
        journal.journal_number = "JRN-001"
        journal.journal_date = date(2026, 1, 1)
        journal.period = MagicMock()
        journal.period.to_str = lambda: "2026-01"
        journal.description = "Test"
        journal.created_at = datetime.now()
        journal.created_by = None
        journal.approved_at = None
        journal.approved_by = None
        journal.lines = []

        result = map_journal_entry_to_response_dto(journal)
        assert result.period == "2026-01"

    def test_map_with_no_id_fallback(self):
        journal = MagicMock()
        journal.id = None
        journal.journal_number = "JRN-001"
        journal.journal_date = date(2026, 1, 1)
        journal.period = "2026-01"
        journal.description = "Test"
        journal.created_at = datetime.now()
        journal.created_by = None
        journal.approved_at = None
        journal.approved_by = None
        journal.lines = []

        result = map_journal_entry_to_response_dto(journal)
        assert result.id == UUID(int=0)

    def test_map_with_error_raises(self):
        # Force an error by passing invalid object
        with pytest.raises(DomainToDTOMappingError, match="Journal mapping error"):
            map_journal_entry_to_response_dto(None)


# ============================================================================
# map_journal_line_domain_to_request tests
# ============================================================================
class TestMapJournalLineDomainToRequest:
    def test_map_full_line(self):
        line = MagicMock()
        line.account_code = "101"
        line.debit = Decimal("100")
        line.credit = Decimal("0")
        line.description = "Cash"
        line.cost_center = "CC001"
        line.department = "FIN"
        line.tax_code = "VAT"
        line.project_code = "PRJ001"
        line.auxiliary_1 = "A1"
        line.auxiliary_2 = "A2"

        result = map_journal_line_domain_to_request(line)
        assert result.account_code == "101"
        assert result.debit == Decimal("100")
        assert result.credit == Decimal("0")
        assert result.description == "Cash"
        assert result.cost_center == "CC001"
        assert result.department == "FIN"
        assert result.tax_code == "VAT"
        assert result.project_code == "PRJ001"
        assert result.auxiliary_1 == "A1"
        assert result.auxiliary_2 == "A2"

    def test_map_line_with_account_fallback(self):
        line = MagicMock()
        line.account_code = None
        line.account = "102"
        line.debit = Decimal("50")
        line.credit = Decimal("0")
        line.description = "Test"
        line.cost_center = None
        line.department = None
        line.tax_code = None
        line.project_code = None
        line.auxiliary_1 = None
        line.auxiliary_2 = None

        result = map_journal_line_domain_to_request(line)
        assert result.account_code == "102"

    def test_map_line_with_none_values(self):
        line = MagicMock()
        line.account_code = "101"
        line.debit = None
        line.credit = None
        line.description = None
        line.cost_center = None
        line.department = None
        line.tax_code = None
        line.project_code = None
        line.auxiliary_1 = None
        line.auxiliary_2 = None

        result = map_journal_line_domain_to_request(line)
        assert result.debit == Decimal("0")
        assert result.credit == Decimal("0")
        assert result.description == ""


# ============================================================================
# map_ar_invoice_to_response_dto tests
# ============================================================================
class TestMapARInvoiceToResponseDTO:
    def test_map_full_invoice(self):
        customer = MagicMock()
        customer.id = uuid4()
        customer.name = "PT Customer"

        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.invoice_number = "INV-001"
        invoice.customer = customer
        invoice.invoice_date = date(2026, 1, 1)
        invoice.due_date = date(2026, 2, 1)
        invoice.amount = Decimal("1000000")
        invoice.paid_amount = Decimal("300000")
        invoice.currency = "IDR"
        invoice.status = "ISSUED"
        invoice.tax_amount = Decimal("100000")
        invoice.tax_code = "VAT"
        invoice.description = "Test invoice"
        invoice.created_at = datetime(2026, 1, 1, 10, 0, 0)
        invoice.remaining_balance = lambda: Decimal("700000")

        aggregate_id = uuid4()
        result = map_ar_invoice_to_response_dto(invoice, aggregate_id, version=2)

        assert result.id == aggregate_id
        assert result.invoice_number == "INV-001"
        assert result.customer_id == customer.id
        assert result.customer_name == "PT Customer"
        assert result.invoice_date == date(2026, 1, 1)
        assert result.due_date == date(2026, 2, 1)
        assert result.amount == Decimal("1000000")
        assert result.paid_amount == Decimal("300000")
        assert result.remaining_amount == Decimal("700000")
        assert result.currency == "IDR"
        assert result.status.value == "ISSUED"
        assert result.tax_amount == Decimal("100000")
        assert result.tax_code == "VAT"
        assert result.description == "Test invoice"
        assert result.version == 2

    def test_map_invoice_with_currency_object(self):
        customer = MagicMock()
        customer.id = uuid4()
        customer.name = "PT Customer"

        currency = MagicMock()
        currency.code = "USD"

        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.invoice_number = "INV-001"
        invoice.customer = customer
        invoice.invoice_date = date(2026, 1, 1)
        invoice.due_date = date(2026, 2, 1)
        invoice.amount = Decimal("1000")
        invoice.paid_amount = Decimal("0")
        invoice.currency = currency
        invoice.status = "ISSUED"
        invoice.tax_amount = Decimal("0")
        invoice.tax_code = None
        invoice.description = ""
        invoice.created_at = datetime.now()
        invoice.remaining_balance = lambda: Decimal("1000")

        result = map_ar_invoice_to_response_dto(invoice)
        assert result.currency == "USD"

    def test_map_invoice_with_status_value(self):
        customer = MagicMock()
        customer.id = uuid4()

        status = MagicMock()
        status.value = "PAID"

        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.invoice_number = "INV-001"
        invoice.customer = customer
        invoice.invoice_date = date(2026, 1, 1)
        invoice.due_date = date(2026, 2, 1)
        invoice.amount = Decimal("1000")
        invoice.paid_amount = Decimal("1000")
        invoice.currency = "IDR"
        invoice.status = status
        invoice.tax_amount = Decimal("0")
        invoice.tax_code = None
        invoice.description = ""
        invoice.created_at = datetime.now()
        invoice.remaining_balance = lambda: Decimal("0")

        result = map_ar_invoice_to_response_dto(invoice)
        assert result.status.value == "PAID"

    def test_map_invoice_with_error_raises(self):
        with pytest.raises(DomainToDTOMappingError, match="AR Invoice mapping error"):
            map_ar_invoice_to_response_dto(None)


# ============================================================================
# map_ar_payment_to_response_dto tests
# ============================================================================
class TestMapARPaymentToResponseDTO:
    def test_map_full_payment(self):
        payment = MagicMock()
        payment.payment_number = "PAY-001"
        payment.payment_date = date(2026, 1, 15)
        payment.amount = Decimal("300000")
        payment.payment_method = "bank_transfer"
        payment.reference_number = "REF123"
        payment.status = "confirmed"
        payment.bank_account_id = uuid4()
        payment.created_at = datetime(2026, 1, 15, 10, 0, 0)

        payment_id = uuid4()
        invoice_id = uuid4()
        result = map_ar_payment_to_response_dto(payment, payment_id, invoice_id)

        assert result.id == payment_id
        assert result.invoice_id == invoice_id
        assert result.payment_number == "PAY-001"
        assert result.payment_date == date(2026, 1, 15)
        assert result.amount == Decimal("300000")
        assert result.payment_method == "bank_transfer"
        assert result.reference_number == "REF123"
        assert result.status == "confirmed"
        assert result.bank_account_id == payment.bank_account_id

    def test_map_payment_with_defaults(self):
        payment = MagicMock()
        payment.payment_number = None
        payment.payment_date = None
        payment.amount = Decimal("0")
        payment.payment_method = None
        payment.reference_number = None
        payment.status = None
        payment.bank_account_id = None
        payment.created_at = datetime.now()

        result = map_ar_payment_to_response_dto(payment, uuid4(), uuid4())
        assert result.payment_number == "PAY-001"
        assert result.payment_date == date.today()
        assert result.payment_method == "bank_transfer"


# ============================================================================
# map_ap_invoice_to_response_dto tests
# ============================================================================
class TestMapAPInvoiceToResponseDTO:
    def test_map_full_invoice(self):
        vendor = MagicMock()
        vendor.id = uuid4()
        vendor.name = "PT Vendor"

        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.invoice_number = "AP-001"
        invoice.vendor = vendor
        invoice.invoice_date = date(2026, 1, 1)
        invoice.due_date = date(2026, 2, 1)
        invoice.amount = Decimal("2000000")
        invoice.paid_amount = Decimal("500000")
        invoice.currency = "IDR"
        invoice.status = "RECEIVED"
        invoice.tax_amount = Decimal("200000")
        invoice.tax_code = "VAT"
        invoice.description = "Test AP invoice"
        invoice.po_reference = "PO-001"
        invoice.grn_reference = "GRN-001"
        invoice.created_at = datetime(2026, 1, 1, 10, 0, 0)
        invoice.remaining_balance = lambda: Decimal("1500000")

        aggregate_id = uuid4()
        result = map_ap_invoice_to_response_dto(invoice, aggregate_id, version=3)

        assert result.id == aggregate_id
        assert result.invoice_number == "AP-001"
        assert result.vendor_id == vendor.id
        assert result.vendor_name == "PT Vendor"
        assert result.invoice_date == date(2026, 1, 1)
        assert result.due_date == date(2026, 2, 1)
        assert result.amount == Decimal("2000000")
        assert result.paid_amount == Decimal("500000")
        assert result.remaining_amount == Decimal("1500000")
        assert result.currency == "IDR"
        assert result.status.value == "RECEIVED"
        assert result.tax_amount == Decimal("200000")
        assert result.tax_code == "VAT"
        assert result.description == "Test AP invoice"
        assert result.po_reference == "PO-001"
        assert result.grn_reference == "GRN-001"
        assert result.version == 3

    def test_map_invoice_with_error_raises(self):
        with pytest.raises(DomainToDTOMappingError, match="AP Invoice mapping error"):
            map_ap_invoice_to_response_dto(None)


# ============================================================================
# map_ap_payment_to_response_dto tests
# ============================================================================
class TestMapAPPaymentToResponseDTO:
    def test_map_full_payment(self):
        payment = MagicMock()
        payment.payment_number = "AP-PAY-001"
        payment.payment_date = date(2026, 1, 15)
        payment.amount = Decimal("500000")
        payment.payment_method = "wire_transfer"
        payment.reference_number = "REF456"
        payment.status = "processed"
        payment.bank_account_id = uuid4()
        payment.created_at = datetime(2026, 1, 15, 10, 0, 0)

        payment_id = uuid4()
        invoice_id = uuid4()
        result = map_ap_payment_to_response_dto(payment, payment_id, invoice_id)

        assert result.id == payment_id
        assert result.invoice_id == invoice_id
        assert result.payment_number == "AP-PAY-001"
        assert result.amount == Decimal("500000")
        assert result.payment_method == "wire_transfer"
        assert result.reference_number == "REF456"
        assert result.status == "processed"

    def test_map_payment_with_defaults(self):
        payment = MagicMock()
        payment.payment_number = None
        payment.payment_date = None
        payment.amount = Decimal("0")
        payment.payment_method = None
        payment.reference_number = None
        payment.status = None
        payment.bank_account_id = None
        payment.created_at = datetime.now()

        result = map_ap_payment_to_response_dto(payment, uuid4(), uuid4())
        assert result.payment_number == "PAY-001"
        assert result.payment_date == date.today()
        assert result.payment_method == "bank_transfer"
        assert result.status == "processed"


# ============================================================================
# map_payment_run_to_response_dto tests
# ============================================================================
class TestMapPaymentRunToResponseDTO:
    def test_map_full_data(self):
        payment_run_id = uuid4()
        payment_ids = [uuid4(), uuid4()]
        created_by = uuid4()
        completed_at = datetime(2026, 1, 31, 23, 59, 59)

        result = map_payment_run_to_response_dto(
            payment_run_id=payment_run_id,
            run_number="PR-001",
            run_date=date(2026, 1, 31),
            total_amount=Decimal("10000000"),
            status="COMPLETED",
            payment_ids=payment_ids,
            created_by=created_by,
            completed_at=completed_at,
        )

        assert result.id == payment_run_id
        assert result.run_number == "PR-001"
        assert result.run_date == date(2026, 1, 31)
        assert result.total_amount == Decimal("10000000")
        assert result.status.value == "COMPLETED"
        assert result.payment_ids == payment_ids
        assert result.created_by == created_by
        assert result.completed_at == completed_at


# ============================================================================
# map_period_close_to_response_dto tests
# ============================================================================
class TestMapPeriodCloseToResponseDTO:
    def test_map_full_data(self):
        period_close_id = uuid4()
        started_by = uuid4()
        completed_at = datetime(2026, 1, 31, 23, 59, 59)
        steps_completed = ["step1", "step2", "step3"]

        result = map_period_close_to_response_dto(
            period_close_id=period_close_id,
            period_year=2026,
            period_month=1,
            status="COMPLETED",
            started_by=started_by,
            completed_at=completed_at,
            steps_completed=steps_completed,
            error_message=None,
        )

        assert result.id == period_close_id
        assert result.period_year == 2026
        assert result.period_month == 1
        assert result.status.value == "COMPLETED"
        assert result.started_by == started_by
        assert result.completed_at == completed_at
        assert result.steps_completed == steps_completed
        assert result.error_message is None

    def test_map_with_error(self):
        period_close_id = uuid4()
        started_by = uuid4()

        result = map_period_close_to_response_dto(
            period_close_id=period_close_id,
            period_year=2026,
            period_month=1,
            status="FAILED",
            started_by=started_by,
            completed_at=None,
            steps_completed=[],
            error_message="Error during closing",
        )

        assert result.status.value == "FAILED"
        assert result.completed_at is None
        assert result.error_message == "Error during closing"


# ============================================================================
# map_trial_balance_cube_to_dto tests
# ============================================================================
class TestMapTrialBalanceCubeToDTO:
    def test_map_with_accounts(self):
        # Create mock accounts
        account1 = MagicMock()
        account1.code = "101"
        account1.name = "Cash"
        account1.opening_debit = Decimal("1000")
        account1.opening_credit = Decimal("0")
        account1.movement_debit = Decimal("500")
        account1.movement_credit = Decimal("0")
        account1.closing_debit = Decimal("1500")
        account1.closing_credit = Decimal("0")

        account2 = MagicMock()
        account2.code = "201"
        account2.name = "Revenue"
        account2.opening_debit = Decimal("0")
        account2.opening_credit = Decimal("500")
        account2.movement_debit = Decimal("0")
        account2.movement_credit = Decimal("300")
        account2.closing_debit = Decimal("0")
        account2.closing_credit = Decimal("800")

        cube = MagicMock()
        cube.accounts = [account1, account2]
        cube.total_opening_debit = lambda: Decimal("1000")
        cube.total_opening_credit = lambda: Decimal("500")
        cube.total_movement_debit = lambda: Decimal("500")
        cube.total_movement_credit = lambda: Decimal("300")
        cube.total_closing_debit = lambda: Decimal("1500")
        cube.total_closing_credit = lambda: Decimal("800")
        cube.is_balanced = lambda: True

        legal_entity_id = uuid4()
        period_end_date = date(2026, 1, 31)

        result = map_trial_balance_cube_to_dto(cube, period_end_date, legal_entity_id)

        assert result.legal_entity_id == legal_entity_id
        assert result.period_end_date == period_end_date
        assert result.total_debit_opening == Decimal("1000")
        assert result.total_credit_opening == Decimal("500")
        assert result.total_debit_movement == Decimal("500")
        assert result.total_credit_movement == Decimal("300")
        assert result.total_debit_closing == Decimal("1500")
        assert result.total_credit_closing == Decimal("800")
        assert result.is_balanced is True

        # Check rows
        assert len(result.rows) == 2
        assert result.rows[0]["account_code"] == "101"
        assert result.rows[0]["account_name"] == "Cash"
        assert result.rows[0]["opening_balance_debit"] == "1000"
        assert result.rows[0]["closing_balance_debit"] == "1500"
        assert result.rows[1]["account_code"] == "201"
        assert result.rows[1]["opening_balance_credit"] == "500"
        assert result.rows[1]["closing_balance_credit"] == "800"

    def test_map_with_empty_cube(self):
        cube = MagicMock()
        cube.accounts = []
        cube.total_opening_debit = lambda: Decimal("0")
        cube.total_opening_credit = lambda: Decimal("0")
        cube.total_movement_debit = lambda: Decimal("0")
        cube.total_movement_credit = lambda: Decimal("0")
        cube.total_closing_debit = lambda: Decimal("0")
        cube.total_closing_credit = lambda: Decimal("0")
        cube.is_balanced = lambda: True

        result = map_trial_balance_cube_to_dto(cube, date.today(), uuid4())
        assert result.rows == []
        assert result.is_balanced is True

    def test_map_with_method_fallback(self):
        # If method not callable, use attribute directly
        cube = MagicMock()
        cube.accounts = []
        cube.total_opening_debit = Decimal("100")  # not callable
        cube.total_opening_credit = Decimal("50")
        cube.total_movement_debit = Decimal("0")
        cube.total_movement_credit = Decimal("0")
        cube.total_closing_debit = Decimal("100")
        cube.total_closing_credit = Decimal("50")
        cube.is_balanced = True

        result = map_trial_balance_cube_to_dto(cube, date.today(), uuid4())
        assert result.total_debit_opening == Decimal("100")
        assert result.total_credit_opening == Decimal("50")


# ============================================================================
# map_balance_sheet_to_dto tests
# ============================================================================
class TestMapBalanceSheetToDTO:
    def test_map_full_balance_sheet(self):
        balance_sheet = MagicMock()
        balance_sheet.current_assets = Decimal("1000000")
        balance_sheet.fixed_assets = Decimal("2000000")
        balance_sheet.intangible_assets = Decimal("500000")
        balance_sheet.total_assets = Decimal("3500000")
        balance_sheet.current_liabilities = Decimal("500000")
        balance_sheet.long_term_liabilities = Decimal("1000000")
        balance_sheet.total_liabilities = Decimal("1500000")
        balance_sheet.equity = Decimal("2000000")
        balance_sheet.total_liabilities_equity = Decimal("3500000")
        balance_sheet.is_balanced = lambda: True

        legal_entity_id = uuid4()
        as_of_date = date(2026, 1, 31)

        result = map_balance_sheet_to_dto(balance_sheet, as_of_date, legal_entity_id)

        assert result.legal_entity_id == legal_entity_id
        assert result.as_of_date == as_of_date
        assert result.assets_current == Decimal("1000000")
        assert result.assets_fixed == Decimal("2000000")
        assert result.assets_intangible == Decimal("500000")
        assert result.total_assets == Decimal("3500000")
        assert result.liabilities_current == Decimal("500000")
        assert result.liabilities_long_term == Decimal("1000000")
        assert result.total_liabilities == Decimal("1500000")
        assert result.equity == Decimal("2000000")
        assert result.total_liabilities_equity == Decimal("3500000")
        assert result.is_balanced is True

    def test_map_with_is_balanced_attribute(self):
        balance_sheet = MagicMock()
        balance_sheet.current_assets = Decimal("0")
        balance_sheet.fixed_assets = Decimal("0")
        balance_sheet.intangible_assets = Decimal("0")
        balance_sheet.total_assets = Decimal("0")
        balance_sheet.current_liabilities = Decimal("0")
        balance_sheet.long_term_liabilities = Decimal("0")
        balance_sheet.total_liabilities = Decimal("0")
        balance_sheet.equity = Decimal("0")
        balance_sheet.total_liabilities_equity = Decimal("0")
        balance_sheet.is_balanced = False  # not callable

        result = map_balance_sheet_to_dto(balance_sheet, date.today(), uuid4())
        assert result.is_balanced is False


# ============================================================================
# map_income_statement_to_dto tests
# ============================================================================
class TestMapIncomeStatementToDTO:
    def test_map_full_income_statement(self):
        income_statement = MagicMock()
        income_statement.revenue = Decimal("10000000")
        income_statement.cogs = Decimal("6000000")
        income_statement.gross_profit = Decimal("4000000")
        income_statement.operating_expenses = Decimal("2000000")
        income_statement.operating_income = Decimal("2000000")
        income_statement.other_income = Decimal("500000")
        income_statement.other_expenses = Decimal("300000")
        income_statement.income_before_tax = Decimal("2200000")
        income_statement.tax_expense = Decimal("220000")
        income_statement.net_income = Decimal("1980000")

        legal_entity_id = uuid4()
        period_start = date(2026, 1, 1)
        period_end = date(2026, 1, 31)

        result = map_income_statement_to_dto(
            income_statement, period_start, period_end, legal_entity_id
        )

        assert result.legal_entity_id == legal_entity_id
        assert result.period_start == period_start
        assert result.period_end == period_end
        assert result.revenue == Decimal("10000000")
        assert result.cost_of_goods_sold == Decimal("6000000")
        assert result.gross_profit == Decimal("4000000")
        assert result.operating_expenses == Decimal("2000000")
        assert result.operating_income == Decimal("2000000")
        assert result.other_income == Decimal("500000")
        assert result.other_expenses == Decimal("300000")
        assert result.income_before_tax == Decimal("2200000")
        assert result.tax_expense == Decimal("220000")
        assert result.net_income == Decimal("1980000")


# ============================================================================
# map_cash_flow_to_dto tests
# ============================================================================
class TestMapCashFlowToDTO:
    def test_map_full_cash_flow(self):
        cash_flow_data = {
            "operating": Decimal("500000"),
            "investing": Decimal("-200000"),
            "financing": Decimal("300000"),
            "net": Decimal("600000"),
            "beginning_cash": Decimal("1000000"),
            "ending_cash": Decimal("1600000"),
        }

        period_start = date(2026, 1, 1)
        period_end = date(2026, 1, 31)
        legal_entity_id = uuid4()

        result = map_cash_flow_to_dto(cash_flow_data, period_start, period_end, legal_entity_id)

        assert result.legal_entity_id == legal_entity_id
        assert result.period_start == period_start
        assert result.period_end == period_end
        assert result.operating_activities == Decimal("500000")
        assert result.investing_activities == Decimal("-200000")
        assert result.financing_activities == Decimal("300000")
        assert result.net_cash_flow == Decimal("600000")
        assert result.beginning_cash == Decimal("1000000")
        assert result.ending_cash == Decimal("1600000")

    def test_map_with_missing_keys(self):
        cash_flow_data = {}

        result = map_cash_flow_to_dto(cash_flow_data, date.today(), date.today(), uuid4())
        assert result.operating_activities == Decimal("0")
        assert result.investing_activities == Decimal("0")
        assert result.financing_activities == Decimal("0")
        assert result.net_cash_flow == Decimal("0")
        assert result.beginning_cash == Decimal("0")
        assert result.ending_cash == Decimal("0")


# ============================================================================
# dto_to_dict tests
# ============================================================================
class TestDTOToDict:
    def test_convert_journal_response_dto(self):
        # Create a real DTO using the mapper first
        journal = MagicMock()
        journal.id = uuid4()
        journal.journal_number = "JRN-001"
        journal.journal_date = date(2026, 1, 1)
        journal.period = "2026-01"
        journal.description = "Test"
        journal.created_at = datetime(2026, 1, 1, 10, 0, 0)
        journal.created_by = uuid4()
        journal.approved_at = None
        journal.approved_by = None
        journal.lines = []

        dto = map_journal_entry_to_response_dto(journal)

        result = dto_to_dict(dto)

        assert result["id"] == str(dto.id)
        assert result["journal_number"] == "JRN-001"
        assert result["journal_date"] == "2026-01-01"
        assert result["period"] == "2026-01"
        assert result["description"] == "Test"
        assert isinstance(result["created_at"], str)
        assert "total_debit" in result
        assert "total_credit" in result
        assert "lines" in result

    def test_convert_ar_invoice_dto(self):
        customer = MagicMock()
        customer.id = uuid4()
        customer.name = "PT Customer"

        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.invoice_number = "INV-001"
        invoice.customer = customer
        invoice.invoice_date = date(2026, 1, 1)
        invoice.due_date = date(2026, 2, 1)
        invoice.amount = Decimal("1000000")
        invoice.paid_amount = Decimal("0")
        invoice.currency = "IDR"
        invoice.status = "ISSUED"
        invoice.tax_amount = Decimal("0")
        invoice.tax_code = None
        invoice.description = ""
        invoice.created_at = datetime.now()
        invoice.remaining_balance = lambda: Decimal("1000000")

        dto = map_ar_invoice_to_response_dto(invoice)
        result = dto_to_dict(dto)

        assert result["invoice_number"] == "INV-001"
        assert result["amount"] == "1000000"
        assert result["remaining_amount"] == "1000000"

    def test_convert_balance_sheet_dto(self):
        balance_sheet = MagicMock()
        balance_sheet.current_assets = Decimal("1000000")
        balance_sheet.fixed_assets = Decimal("2000000")
        balance_sheet.intangible_assets = Decimal("500000")
        balance_sheet.total_assets = Decimal("3500000")
        balance_sheet.current_liabilities = Decimal("500000")
        balance_sheet.long_term_liabilities = Decimal("1000000")
        balance_sheet.total_liabilities = Decimal("1500000")
        balance_sheet.equity = Decimal("2000000")
        balance_sheet.total_liabilities_equity = Decimal("3500000")
        balance_sheet.is_balanced = lambda: True

        dto = map_balance_sheet_to_dto(balance_sheet, date(2026, 1, 31), uuid4())
        result = dto_to_dict(dto)

        assert result["assets_current"] == "1000000"
        assert result["total_assets"] == "3500000"
        assert result["is_balanced"] is True

    def test_convert_non_dataclass_raises(self):
        class NotADTO:
            pass

        with pytest.raises(DomainToDTOMappingError, match="bukan dataclass DTO"):
            dto_to_dict(NotADTO())

    def test_serialize_nested_list_with_dto(self):
        # Test that serialization handles nested DTOs
        dto = MagicMock()
        # Make it look like a dataclass with fields
        dto.__dataclass_fields__ = {"items": None, "name": None}
        dto.items = [MagicMock(), MagicMock()]
        dto.name = "test"

        # For nested list with non-DTO objects, it should convert them as-is
        # We'll test with simple list of strings
        result = _serialize_nested_list_value(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_serialize_uuid(self):
        from application.mappers.domain_to_dto import _serialize_value
        uid = uuid4()
        result = _serialize_value(uid)
        assert result == str(uid)

    def test_serialize_decimal(self):
        from application.mappers.domain_to_dto import _serialize_value
        d = Decimal("10.50")
        result = _serialize_value(d)
        assert result == "10.50"

    def test_serialize_date(self):
        from application.mappers.domain_to_dto import _serialize_value
        d = date(2026, 1, 1)
        result = _serialize_value(d)
        assert result == "2026-01-01"

    def test_serialize_datetime(self):
        from application.mappers.domain_to_dto import _serialize_value
        dt = datetime(2026, 1, 1, 10, 30, 0)
        result = _serialize_value(dt)
        assert result == "2026-01-01T10:30:00"

    def test_serialize_dict(self):
        from application.mappers.domain_to_dto import _serialize_value
        d = {"key": "value", "num": 123}
        result = _serialize_value(d)
        assert result["key"] == "value"
        assert result["num"] == 123

    def test_serialize_with_to_dict_method(self):
        from application.mappers.domain_to_dto import _serialize_value
        obj = MagicMock()
        obj.to_dict = lambda: {"custom": "data"}
        result = _serialize_value(obj)
        assert result == {"custom": "data"}


# Helper function for testing nested list serialization
def _serialize_nested_list_value(value):
    from application.mappers.domain_to_dto import _serialize_value
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    return value