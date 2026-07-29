# tests/application/dto_objects/test_financial_statement_request.py
# Comprehensive tests for application/dto_objects/financial_statement_request.py

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from application.dto_objects.financial_statement_request import (
    AccountFilter,
    BalanceSheetDTO,
    BalanceSheetRequest,
    CashFlowDTO,
    CashFlowMethod,
    CashFlowStatementRequest,
    ComparativeType,
    CurrencyType,
    DateRange,
    EquityStatementRequest,
    FinancialStatementRequestDTO,
    FinancialStatementRequestFactory,
    FinancialStatementResult,
    FinancialStatementType,
    GeneralLedgerRequest,
    IncomeStatementDTO,
    IncomeStatementRequest,
    OutputFormat,
    SubsidiaryLedgerRequest,
    TrialBalanceDTO,
    TrialBalanceRequest,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def date_range():
    return DateRange(
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        end_date=datetime(2026, 1, 31, tzinfo=UTC),
        period_name="Jan 2026",
    )


@pytest.fixture
def account_filter():
    return AccountFilter(
        account_types=["ASSET", "LIABILITY"],
        account_codes=["1.1", "2.1"],
        account_ids=[uuid4(), uuid4()],
        parent_account_id=uuid4(),
        include_children=False,
        exclude_zero_balance=True,
        min_balance=Decimal("100"),
        max_balance=Decimal("10000"),
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestEnums:
    def test_financial_statement_type(self):
        assert FinancialStatementType.BALANCE_SHEET.value == "balance_sheet"
        assert FinancialStatementType.INCOME_STATEMENT.value == "income_statement"
        assert FinancialStatementType.CASH_FLOW.value == "cash_flow"
        assert FinancialStatementType.EQUITY_STATEMENT.value == "equity_statement"
        assert FinancialStatementType.TRIAL_BALANCE.value == "trial_balance"
        assert FinancialStatementType.GENERAL_LEDGER.value == "general_ledger"
        assert FinancialStatementType.SUBSIDIARY_LEDGER.value == "subsidiary_ledger"

    def test_cash_flow_method(self):
        assert CashFlowMethod.DIRECT.value == "direct"
        assert CashFlowMethod.INDIRECT.value == "indirect"

    def test_comparative_type(self):
        assert ComparativeType.NONE.value == "none"
        assert ComparativeType.PRIOR_PERIOD.value == "prior_period"
        assert ComparativeType.PRIOR_YEAR.value == "prior_year"
        assert ComparativeType.BUDGET.value == "budget"

    def test_output_format(self):
        assert OutputFormat.JSON.value == "json"
        assert OutputFormat.PDF.value == "pdf"
        assert OutputFormat.EXCEL.value == "excel"
        assert OutputFormat.CSV.value == "csv"
        assert OutputFormat.HTML.value == "html"
        assert OutputFormat.XBRL.value == "xbrl"

    def test_currency_type(self):
        assert CurrencyType.FUNCTIONAL.value == "functional"
        assert CurrencyType.PRESENTATION.value == "presentation"
        assert CurrencyType.BOTH.value == "both"


# ============================================================================
# Tests for DateRange
# ============================================================================

class TestDateRange:
    def test_construction_valid(self, date_range):
        assert date_range.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert date_range.end_date == datetime(2026, 1, 31, tzinfo=UTC)
        assert date_range.period_name == "Jan 2026"

    def test_construction_auto_tz(self):
        # Without tzinfo, should be set to UTC
        start = datetime(2026, 1, 1)
        end = datetime(2026, 1, 31)
        dr = DateRange(start_date=start, end_date=end)
        assert dr.start_date.tzinfo is not None
        assert dr.end_date.tzinfo is not None

    def test_construction_start_after_end_raises(self):
        start = datetime(2026, 1, 31, tzinfo=UTC)
        end = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="Start date.*must be before"):
            DateRange(start_date=start, end_date=end)

    def test_duration_days(self, date_range):
        assert date_range.duration_days == 30

    def test_to_dict(self, date_range):
        d = date_range.to_dict()
        assert d["start_date"] == "2026-01-01T00:00:00+00:00"
        assert d["end_date"] == "2026-01-31T00:00:00+00:00"
        assert d["period_name"] == "Jan 2026"
        assert d["duration_days"] == 30

    def test_from_month(self):
        dr = DateRange.from_month(2026, 1)
        assert dr.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert dr.end_date == datetime(2026, 2, 1, tzinfo=UTC)
        assert dr.period_name == "01/2026"

        # December
        dr2 = DateRange.from_month(2026, 12)
        assert dr2.end_date == datetime(2027, 1, 1, tzinfo=UTC)

    def test_from_year(self):
        dr = DateRange.from_year(2026)
        assert dr.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert dr.end_date == datetime(2027, 1, 1, tzinfo=UTC)
        assert dr.period_name == "2026"

    def test_from_quarter(self):
        dr = DateRange.from_quarter(2026, 1)
        assert dr.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert dr.end_date == datetime(2026, 4, 1, tzinfo=UTC)
        assert dr.period_name == "Q1/2026"

        dr2 = DateRange.from_quarter(2026, 4)
        assert dr2.start_date == datetime(2026, 10, 1, tzinfo=UTC)
        assert dr2.end_date == datetime(2027, 1, 1, tzinfo=UTC)
        assert dr2.period_name == "Q4/2026"


# ============================================================================
# Tests for AccountFilter
# ============================================================================

class TestAccountFilter:
    def test_to_dict(self, account_filter):
        d = account_filter.to_dict()
        assert d["account_types"] == ["ASSET", "LIABILITY"]
        assert d["account_codes"] == ["1.1", "2.1"]
        assert len(d["account_ids"]) == 2
        assert d["include_children"] is False
        assert d["exclude_zero_balance"] is True
        assert d["min_balance"] == "100"
        assert d["max_balance"] == "10000"
        assert "parent_account_id" in d

    def test_to_dict_empty(self):
        af = AccountFilter()
        d = af.to_dict()
        assert d["account_types"] is None
        assert d["account_codes"] is None
        assert d["account_ids"] is None
        assert d["parent_account_id"] is None
        assert d["include_children"] is True
        assert d["exclude_zero_balance"] is False
        assert d["min_balance"] is None
        assert d["max_balance"] is None


# ============================================================================
# Tests for Request DTOs
# ============================================================================

class TestBalanceSheetRequest:
    def test_construction_valid(self, legal_entity_id):
        as_of = datetime(2026, 1, 31, tzinfo=UTC)
        req = BalanceSheetRequest(legal_entity_id=legal_entity_id, as_of_date=as_of)
        assert req.legal_entity_id == legal_entity_id
        assert req.as_of_date == as_of
        assert req.comparative == ComparativeType.NONE
        assert req.output_format == OutputFormat.JSON

    def test_auto_tz(self, legal_entity_id):
        as_of = datetime(2026, 1, 31)  # naive
        req = BalanceSheetRequest(legal_entity_id=legal_entity_id, as_of_date=as_of)
        assert req.as_of_date.tzinfo is not None

    def test_to_dict(self, legal_entity_id, account_filter):
        as_of = datetime(2026, 1, 31, tzinfo=UTC)
        req = BalanceSheetRequest(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of,
            comparative=ComparativeType.PRIOR_YEAR,
            comparative_period=DateRange.from_year(2025),
            account_filter=account_filter,
            include_previous_year=True,
            currency_type=CurrencyType.BOTH,
            presentation_currency="USD",
            output_format=OutputFormat.PDF,
            entity_name="Test Entity",
        )
        d = req.to_dict()
        assert d["legal_entity_id"] == str(legal_entity_id)
        assert d["as_of_date"] == "2026-01-31T00:00:00+00:00"
        assert d["comparative"] == "prior_year"
        assert "comparative_period" in d
        assert "account_filter" in d
        assert d["include_previous_year"] is True
        assert d["currency_type"] == "both"
        assert d["presentation_currency"] == "USD"
        assert d["output_format"] == "pdf"
        assert d["entity_name"] == "Test Entity"


class TestIncomeStatementRequest:
    def test_construction(self, legal_entity_id, date_range):
        req = IncomeStatementRequest(legal_entity_id=legal_entity_id, period=date_range)
        assert req.legal_entity_id == legal_entity_id
        assert req.period is date_range
        assert req.comparative == ComparativeType.PRIOR_PERIOD  # default

    def test_to_dict(self, legal_entity_id, date_range, account_filter):
        req = IncomeStatementRequest(
            legal_entity_id=legal_entity_id,
            period=date_range,
            comparative=ComparativeType.BUDGET,
            account_filter=account_filter,
            show_operating_expenses_detail=False,
            show_other_income_expense=False,
            currency_type=CurrencyType.PRESENTATION,
            presentation_currency="EUR",
            output_format=OutputFormat.EXCEL,
            entity_name="Income Entity",
        )
        d = req.to_dict()
        assert d["legal_entity_id"] == str(legal_entity_id)
        assert d["period"] == date_range.to_dict()
        assert d["comparative"] == "budget"
        assert "account_filter" in d
        assert d["show_operating_expenses_detail"] is False
        assert d["show_other_income_expense"] is False
        assert d["currency_type"] == "presentation"
        assert d["presentation_currency"] == "EUR"
        assert d["output_format"] == "excel"


class TestCashFlowStatementRequest:
    def test_construction(self, legal_entity_id, date_range):
        req = CashFlowStatementRequest(legal_entity_id=legal_entity_id, period=date_range)
        assert req.method == CashFlowMethod.INDIRECT  # default

    def test_to_dict(self, legal_entity_id, date_range):
        req = CashFlowStatementRequest(
            legal_entity_id=legal_entity_id,
            period=date_range,
            method=CashFlowMethod.DIRECT,
            comparative=ComparativeType.PRIOR_YEAR,
            include_non_cash_transactions=True,
            currency_type=CurrencyType.FUNCTIONAL,
            presentation_currency="IDR",
            output_format=OutputFormat.CSV,
            entity_name="CashFlow Co",
        )
        d = req.to_dict()
        assert d["method"] == "direct"
        assert d["comparative"] == "prior_year"
        assert d["include_non_cash_transactions"] is True
        assert d["currency_type"] == "functional"
        assert d["output_format"] == "csv"


class TestEquityStatementRequest:
    def test_to_dict(self, legal_entity_id, date_range):
        req = EquityStatementRequest(
            legal_entity_id=legal_entity_id,
            period=date_range,
            comparative=ComparativeType.NONE,
            include_capital_changes=False,
            include_dividends=False,
            include_other_comprehensive_income=False,
            currency_type=CurrencyType.BOTH,
            presentation_currency="USD",
            output_format=OutputFormat.HTML,
            entity_name="Equity Entity",
        )
        d = req.to_dict()
        assert d["include_capital_changes"] is False
        assert d["include_dividends"] is False
        assert d["include_other_comprehensive_income"] is False
        assert d["currency_type"] == "both"
        assert d["output_format"] == "html"


class TestTrialBalanceRequest:
    def test_auto_tz(self, legal_entity_id):
        as_of = datetime(2026, 1, 31)  # naive
        req = TrialBalanceRequest(legal_entity_id=legal_entity_id, as_of_date=as_of)
        assert req.as_of_date.tzinfo is not None

    def test_to_dict(self, legal_entity_id, account_filter):
        as_of = datetime(2026, 1, 31, tzinfo=UTC)
        req = TrialBalanceRequest(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of,
            account_filter=account_filter,
            include_period_activity=False,
            currency_type=CurrencyType.PRESENTATION,
            presentation_currency="JPY",
            output_format=OutputFormat.XBRL,
            entity_name="TB Entity",
        )
        d = req.to_dict()
        assert d["as_of_date"] == "2026-01-31T00:00:00+00:00"
        assert "account_filter" in d
        assert d["include_period_activity"] is False
        assert d["currency_type"] == "presentation"
        assert d["presentation_currency"] == "JPY"
        assert d["output_format"] == "xbrl"


class TestGeneralLedgerRequest:
    def test_to_dict(self, legal_entity_id, date_range, account_filter):
        req = GeneralLedgerRequest(
            legal_entity_id=legal_entity_id,
            period=date_range,
            account_filter=account_filter,
            show_beginning_balance=False,
            show_ending_balance=False,
            show_running_balance=False,
            currency_type=CurrencyType.FUNCTIONAL,
            presentation_currency="IDR",
            output_format=OutputFormat.JSON,
            entity_name="GL Entity",
        )
        d = req.to_dict()
        assert d["show_beginning_balance"] is False
        assert d["show_ending_balance"] is False
        assert d["show_running_balance"] is False
        assert "account_filter" in d


class TestSubsidiaryLedgerRequest:
    def test_valid_ledger_types(self, legal_entity_id, date_range):
        for ledger_type in ["AR", "AP", "FIXED_ASSET", "INVENTORY"]:
            req = SubsidiaryLedgerRequest(
                legal_entity_id=legal_entity_id,
                period=date_range,
                ledger_type=ledger_type,
            )
            assert req.ledger_type == ledger_type

    def test_invalid_ledger_type_raises(self, legal_entity_id, date_range):
        with pytest.raises(ValueError, match="ledger_type must be one of"):
            SubsidiaryLedgerRequest(
                legal_entity_id=legal_entity_id,
                period=date_range,
                ledger_type="INVALID",
            )

    def test_to_dict(self, legal_entity_id, date_range):
        entity_id = uuid4()
        req = SubsidiaryLedgerRequest(
            legal_entity_id=legal_entity_id,
            period=date_range,
            ledger_type="AR",
            entity_id=entity_id,
            entity_code="CUST-001",
            show_beginning_balance=False,
            show_ending_balance=False,
            output_format=OutputFormat.CSV,
        )
        d = req.to_dict()
        assert d["ledger_type"] == "AR"
        assert d["entity_id"] == str(entity_id)
        assert d["entity_code"] == "CUST-001"
        assert d["show_beginning_balance"] is False
        assert d["show_ending_balance"] is False
        assert d["output_format"] == "csv"


# ============================================================================
# Tests for Response DTOs
# ============================================================================

class TestBalanceSheetDTO:
    def test_to_dict(self, legal_entity_id):
        dto = BalanceSheetDTO(
            legal_entity_id=legal_entity_id,
            as_of_date=date(2026, 1, 31),
            assets_current=Decimal("1000"),
            assets_fixed=Decimal("2000"),
            assets_intangible=Decimal("3000"),
            total_assets=Decimal("6000"),
            liabilities_current=Decimal("1000"),
            liabilities_long_term=Decimal("2000"),
            total_liabilities=Decimal("3000"),
            equity=Decimal("3000"),
            total_liabilities_equity=Decimal("6000"),
            is_balanced=True,
        )
        d = dto.to_dict()
        assert d["legal_entity_id"] == str(legal_entity_id)
        assert d["as_of_date"] == "2026-01-31"
        assert d["assets_current"] == "1000"
        assert d["total_assets"] == "6000"
        assert d["is_balanced"] is True


class TestIncomeStatementDTO:
    def test_to_dict(self, legal_entity_id):
        dto = IncomeStatementDTO(
            legal_entity_id=legal_entity_id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            revenue=Decimal("10000"),
            cost_of_goods_sold=Decimal("6000"),
            gross_profit=Decimal("4000"),
            operating_expenses=Decimal("2000"),
            operating_income=Decimal("2000"),
            other_income=Decimal("100"),
            other_expenses=Decimal("50"),
            income_before_tax=Decimal("2050"),
            tax_expense=Decimal("500"),
            net_income=Decimal("1550"),
        )
        d = dto.to_dict()
        assert d["revenue"] == "10000"
        assert d["gross_profit"] == "4000"
        assert d["net_income"] == "1550"


class TestCashFlowDTO:
    def test_to_dict(self, legal_entity_id):
        dto = CashFlowDTO(
            legal_entity_id=legal_entity_id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            operating_activities=Decimal("1000"),
            investing_activities=Decimal("-500"),
            financing_activities=Decimal("-200"),
            net_cash_flow=Decimal("300"),
            beginning_cash=Decimal("500"),
            ending_cash=Decimal("800"),
        )
        d = dto.to_dict()
        assert d["operating_activities"] == "1000"
        assert d["net_cash_flow"] == "300"
        assert d["ending_cash"] == "800"


class TestTrialBalanceDTO:
    def test_to_dict(self, legal_entity_id):
        rows = [
            {"account": "Cash", "debit": "100", "credit": "0"},
            {"account": "Revenue", "debit": "0", "credit": "100"},
        ]
        dto = TrialBalanceDTO(
            legal_entity_id=legal_entity_id,
            period_end_date=date(2026, 1, 31),
            rows=rows,
            total_debit_opening=Decimal("100"),
            total_credit_opening=Decimal("100"),
            total_debit_movement=Decimal("50"),
            total_credit_movement=Decimal("50"),
            total_debit_closing=Decimal("150"),
            total_credit_closing=Decimal("150"),
            is_balanced=True,
        )
        d = dto.to_dict()
        assert d["rows"] == rows
        assert d["total_debit_opening"] == "100"
        assert d["is_balanced"] is True


# ============================================================================
# Tests for FinancialStatementResult
# ============================================================================

class TestFinancialStatementResult:
    def test_auto_tz(self, legal_entity_id, date_range):
        generated = datetime.now()  # naive
        result = FinancialStatementResult(
            statement_type=FinancialStatementType.BALANCE_SHEET,
            legal_entity_id=legal_entity_id,
            legal_entity_name="Test",
            period=date_range,
            generated_at=generated,
            data={},
        )
        assert result.generated_at.tzinfo is not None

    def test_to_dict(self, legal_entity_id, date_range):
        generated = datetime(2026, 1, 31, 12, 0, 0, tzinfo=UTC)
        result = FinancialStatementResult(
            statement_type=FinancialStatementType.BALANCE_SHEET,
            legal_entity_id=legal_entity_id,
            legal_entity_name="My Entity",
            period=date_range,
            generated_at=generated,
            data={"key": "value"},
            total_assets=Decimal("1000"),
            total_liabilities=Decimal("400"),
            total_equity=Decimal("600"),
            total_revenue=Decimal("500"),
            total_expenses=Decimal("300"),
            net_income=Decimal("200"),
            output_format=OutputFormat.PDF,
        )
        d = result.to_dict()
        assert d["statement_type"] == "balance_sheet"
        assert d["legal_entity_name"] == "My Entity"
        assert d["generated_at"] == "2026-01-31T12:00:00+00:00"
        assert d["data"] == {"key": "value"}
        assert d["total_assets"] == "1000"
        assert d["total_liabilities"] == "400"
        assert d["total_equity"] == "600"
        assert d["total_revenue"] == "500"
        assert d["net_income"] == "200"
        assert d["output_format"] == "pdf"

    def test_get_balance_sheet_equation_true(self, legal_entity_id, date_range):
        result = FinancialStatementResult(
            statement_type=FinancialStatementType.BALANCE_SHEET,
            legal_entity_id=legal_entity_id,
            legal_entity_name="Test",
            period=date_range,
            generated_at=datetime.now(UTC),
            data={},
            total_assets=Decimal("1000"),
            total_liabilities=Decimal("400"),
            total_equity=Decimal("600"),
        )
        assert result.get_balance_sheet_equation() is True

    def test_get_balance_sheet_equation_false(self, legal_entity_id, date_range):
        result = FinancialStatementResult(
            statement_type=FinancialStatementType.BALANCE_SHEET,
            legal_entity_id=legal_entity_id,
            legal_entity_name="Test",
            period=date_range,
            generated_at=datetime.now(UTC),
            data={},
            total_assets=Decimal("1000"),
            total_liabilities=Decimal("300"),
            total_equity=Decimal("600"),  # 300+600=900 != 1000
        )
        assert result.get_balance_sheet_equation() is False

    def test_get_balance_sheet_equation_missing_fields(self, legal_entity_id, date_range):
        result = FinancialStatementResult(
            statement_type=FinancialStatementType.BALANCE_SHEET,
            legal_entity_id=legal_entity_id,
            legal_entity_name="Test",
            period=date_range,
            generated_at=datetime.now(UTC),
            data={},
            total_assets=Decimal("1000"),
            # total_liabilities and total_equity are None
        )
        # Should return True because it's not possible to check
        assert result.get_balance_sheet_equation() is True


# ============================================================================
# Tests for FinancialStatementRequestDTO
# ============================================================================

class TestFinancialStatementRequestDTO:
    def test_to_dict(self, legal_entity_id):
        dto = FinancialStatementRequestDTO(
            legal_entity_id=legal_entity_id,
            statement_type="balance_sheet",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            currency_code="IDR",
        )
        d = dto.to_dict()
        assert d["legal_entity_id"] == str(legal_entity_id)
        assert d["statement_type"] == "balance_sheet"
        assert d["period_start"] == "2026-01-01"
        assert d["period_end"] == "2026-01-31"
        assert d["currency_code"] == "IDR"


# ============================================================================
# Tests for FinancialStatementRequestFactory
# ============================================================================

class TestFinancialStatementRequestFactory:
    def test_create_balance_sheet_request(self, legal_entity_id):
        as_of = datetime(2026, 1, 31, tzinfo=UTC)
        req = FinancialStatementRequestFactory.create_balance_sheet_request(
            legal_entity_id, as_of, entity_name="BS Entity"
        )
        assert isinstance(req, BalanceSheetRequest)
        assert req.legal_entity_id == legal_entity_id
        assert req.as_of_date == as_of
        assert req.entity_name == "BS Entity"

    def test_create_income_statement_request(self, legal_entity_id):
        req = FinancialStatementRequestFactory.create_income_statement_request(
            legal_entity_id, 2026, 1, entity_name="IS Entity"
        )
        assert isinstance(req, IncomeStatementRequest)
        assert req.legal_entity_id == legal_entity_id
        assert req.period.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert req.period.end_date == datetime(2026, 2, 1, tzinfo=UTC)
        assert req.entity_name == "IS Entity"

    def test_create_yearly_income_statement(self, legal_entity_id):
        req = FinancialStatementRequestFactory.create_yearly_income_statement(
            legal_entity_id, 2026, entity_name="Yearly IS"
        )
        assert isinstance(req, IncomeStatementRequest)
        assert req.period.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert req.period.end_date == datetime(2027, 1, 1, tzinfo=UTC)
        assert req.comparative == ComparativeType.PRIOR_YEAR
        assert req.entity_name == "Yearly IS"

    def test_create_cash_flow_request(self, legal_entity_id):
        req = FinancialStatementRequestFactory.create_cash_flow_request(
            legal_entity_id, 2026, 1, method=CashFlowMethod.DIRECT, entity_name="CF Entity"
        )
        assert isinstance(req, CashFlowStatementRequest)
        assert req.method == CashFlowMethod.DIRECT
        assert req.entity_name == "CF Entity"

    def test_create_trial_balance_request(self, legal_entity_id):
        as_of = datetime(2026, 1, 31, tzinfo=UTC)
        req = FinancialStatementRequestFactory.create_trial_balance_request(
            legal_entity_id, as_of, entity_name="TB Entity"
        )
        assert isinstance(req, TrialBalanceRequest)
        assert req.as_of_date == as_of
        assert req.entity_name == "TB Entity"

    def test_create_general_ledger_request(self, legal_entity_id):
        req = FinancialStatementRequestFactory.create_general_ledger_request(
            legal_entity_id, 2026, 1, entity_name="GL Entity"
        )
        assert isinstance(req, GeneralLedgerRequest)
        assert req.period.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert req.entity_name == "GL Entity"

    def test_create_general_ledger_request_with_filter(self, legal_entity_id, account_filter):
        req = FinancialStatementRequestFactory.create_general_ledger_request(
            legal_entity_id, 2026, 1, account_filter=account_filter, entity_name="GL Entity"
        )
        assert req.account_filter is account_filter
