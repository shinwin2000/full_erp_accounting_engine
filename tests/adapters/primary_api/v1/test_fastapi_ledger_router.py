# adapters/primary_api/v1/test_fastapi_ledger_router.py
"""
Comprehensive unit tests for FastAPI Ledger Router.

Covers:
- All enum classes
- All request/response schemas (construction)
- All endpoint functions (with mocked service layer)
- Health check endpoints (ping, health, info)
- Export endpoints (trial balance, general ledger)
- Dependency injection (get_ledger_service)
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_ledger_router import (
    AccountActivitySchema,
    AccountBalanceHistorySchema,
    AccountBalanceResponseSchema,
    BalanceSheetResponseSchema,
    BalanceSheetSectionSchema,
    CashFlowLineSchema,
    CashFlowResponseSchema,
    ComparisonType,
    EquityStatementLineSchema,
    EquityStatementResponseSchema,
    FinancialRatiosResponseSchema,
    IncomeStatementLineSchema,
    IncomeStatementResponseSchema,
    LedgerEntryResponseSchema,
    LedgerEntryType,
    ReportPeriod,
    TrialBalanceLineSchema,
    TrialBalanceResponseSchema,
    export_general_ledger,
    export_trial_balance,
    get_account_activity,
    get_account_balance,
    get_account_balance_by_code,
    get_account_balance_history,
    get_account_ledger_entries,
    get_balance_sheet,
    get_cash_flow,
    get_equity_statement,
    get_financial_ratios,
    get_income_statement,
    get_journal_ledger_entries,
    get_ledger_entries,
    get_ledger_service,
    get_ledger_summary,
    get_trial_balance,
    health,
    info,
    ping,
)

# =============================================================================
# Helper fixtures
# =============================================================================

@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_ledger_service():
    svc = AsyncMock()

    # Trial balance
    svc.get_trial_balance.return_value = MagicMock(
        legal_entity_name="Test Entity",
        start_date=date(2025, 1, 1),
        lines=[
            MagicMock(
                account_id=uuid4(),
                account_code="1-1000",
                account_name="Cash",
                account_type="Asset",
                opening_balance_debit=Decimal("0"),
                opening_balance_credit=Decimal("0"),
                movement_debit=Decimal("1000"),
                movement_credit=Decimal("500"),
                closing_balance_debit=Decimal("500"),
                closing_balance_credit=Decimal("0"),
            )
        ],
        total_debit=Decimal("1000"),
        total_credit=Decimal("500"),
        is_balanced=True,
    )

    # Balance sheet
    svc.get_balance_sheet.return_value = MagicMock(
        legal_entity_name="Test Entity",
        assets_lines=[{"account": "Cash", "amount": 1000}],
        total_assets=Decimal("1000"),
        liabilities_lines=[{"account": "Payable", "amount": 200}],
        total_liabilities=Decimal("200"),
        equity_lines=[{"account": "Capital", "amount": 800}],
        total_equity=Decimal("800"),
        current_ratio=2.5,
        quick_ratio=1.8,
        debt_to_equity=0.25,
    )

    # Income statement
    svc.get_income_statement.return_value = MagicMock(
        legal_entity_name="Test Entity",
        period_name="January 2025",
        revenues=[{"account_id": uuid4(), "account_code": "4-1000", "account_name": "Revenue", "current_period": 1000, "year_to_date": 1000}],
        cogs=[{"account_id": uuid4(), "account_code": "5-1000", "account_name": "COGS", "current_period": 600, "year_to_date": 600}],
        gross_profit=Decimal("400"),
        operating_expenses=[{"account_id": uuid4(), "account_code": "5-2000", "account_name": "Expense", "current_period": 200, "year_to_date": 200}],
        operating_income=Decimal("200"),
        other_income=[],
        other_expenses=[],
        income_before_tax=Decimal("200"),
        tax_expense=Decimal("40"),
        net_income=Decimal("160"),
        ebitda=Decimal("220"),
        gross_margin=40.0,
        operating_margin=20.0,
        net_margin=16.0,
    )

    # Cash flow
    svc.get_cash_flow_statement.return_value = MagicMock(
        legal_entity_name="Test Entity",
        operating_activities=[{"category": "Receipts", "description": "Cash sales", "amount": 1000}],
        net_cash_operating=Decimal("1000"),
        investing_activities=[{"category": "Purchase", "description": "Equipment", "amount": -200}],
        net_cash_investing=Decimal("-200"),
        financing_activities=[{"category": "Loan", "description": "Bank loan", "amount": 300}],
        net_cash_financing=Decimal("300"),
        net_increase_decrease=Decimal("1100"),
        beginning_cash=Decimal("500"),
        ending_cash=Decimal("1600"),
        free_cash_flow=Decimal("800"),
    )

    # Equity statement
    svc.get_equity_statement.return_value = MagicMock(
        legal_entity_name="Test Entity",
        lines=[
            MagicMock(
                component="Capital",
                opening_balance=Decimal("1000"),
                additions=Decimal("200"),
                deductions=Decimal("0"),
                closing_balance=Decimal("1200"),
                change=Decimal("200"),
            )
        ],
        opening_total_equity=Decimal("1000"),
        net_income=Decimal("160"),
        other_comprehensive_income=Decimal("0"),
        dividends_declared=Decimal("50"),
        capital_changes=Decimal("200"),
        closing_total_equity=Decimal("1310"),
    )

    # Account balance
    svc.get_account_balance.return_value = MagicMock(
        account_code="1-1000",
        account_name="Cash",
        balance=Decimal("500"),
        normal_balance="debit",
        is_debit_balance=True,
        opening_balance=Decimal("0"),
        debit_movement=Decimal("1000"),
        credit_movement=Decimal("500"),
    )
    svc.get_account_balance_by_code.return_value = MagicMock(
        account_id=uuid4(),
        account_name="Cash",
        balance=Decimal("500"),
        normal_balance="debit",
        is_debit_balance=True,
        opening_balance=Decimal("0"),
        debit_movement=Decimal("1000"),
        credit_movement=Decimal("500"),
    )

    # Balance history
    svc.get_account_balance_history.return_value = [
        MagicMock(
            as_of_date=date(2025, 1, 1),
            balance=Decimal("500"),
            debit_movement=Decimal("1000"),
            credit_movement=Decimal("500"),
            net_change=Decimal("500"),
        )
    ]

    # Ledger entries
    svc.get_ledger_entries.return_value = [
        MagicMock(
            id=uuid4(),
            journal_id=uuid4(),
            journal_number="JRN-001",
            journal_date=date.today(),
            account_id=uuid4(),
            account_code="1-1000",
            account_name="Cash",
            debit_amount=Decimal("1000"),
            credit_amount=Decimal("0"),
            posting_date=date.today(),
            description="Sale",
            reference_number="REF-001",
            cost_center="CC1",
            department="Dept1",
            project_id=uuid4(),
            entry_type="journal",
            created_at=datetime.now(UTC),
            posted_by=uuid4(),
        )
    ]
    svc.get_account_ledger_entries.return_value = svc.get_ledger_entries.return_value
    svc.get_ledger_entries_for_journal.return_value = svc.get_ledger_entries.return_value

    # Account activity
    svc.get_account_activity.return_value = [
        MagicMock(
            period="2025-01",
            opening_balance=Decimal("0"),
            debit=Decimal("1000"),
            credit=Decimal("500"),
            closing_balance=Decimal("500"),
        )
    ]

    # Financial ratios
    svc.get_financial_ratios.return_value = MagicMock(
        current_ratio=2.5,
        quick_ratio=1.8,
        cash_ratio=0.5,
        debt_to_equity=0.25,
        debt_to_assets=0.2,
        interest_coverage=10.0,
        gross_margin=40.0,
        operating_margin=20.0,
        net_margin=16.0,
        return_on_assets=8.0,
        return_on_equity=12.0,
        asset_turnover=1.5,
        inventory_turnover=6.0,
        receivable_turnover=8.0,
        payable_turnover=5.0,
        industry_comparison={"industry": "Retail", "average_ratio": 2.0},
    )

    # Export
    svc.export_trial_balance.return_value = b"csv data"
    svc.export_general_ledger.return_value = b"csv data"

    # Summary
    svc.get_ledger_summary.return_value = MagicMock(
        total_accounts=10,
        active_accounts=8,
        accounts_with_balance=5,
        total_debit_balance=Decimal("10000"),
        total_credit_balance=Decimal("10000"),
        total_journals_ytd=50,
        total_entries_ytd=200,
        last_posted_at=datetime.now(UTC),
        last_posted_by=uuid4(),
    )

    return svc


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_report_period_values(self):
        assert ReportPeriod.CURRENT_MONTH.value == "current_month"
        assert ReportPeriod.PREVIOUS_MONTH.value == "previous_month"
        assert ReportPeriod.CURRENT_QUARTER.value == "current_quarter"
        assert ReportPeriod.PREVIOUS_QUARTER.value == "previous_quarter"
        assert ReportPeriod.YEAR_TO_DATE.value == "ytd"
        assert ReportPeriod.PREVIOUS_YEAR.value == "previous_year"
        assert ReportPeriod.CUSTOM.value == "custom"

    def test_comparison_type_values(self):
        assert ComparisonType.NONE.value == "none"
        assert ComparisonType.PREVIOUS_PERIOD.value == "previous_period"
        assert ComparisonType.PREVIOUS_YEAR.value == "previous_year"
        assert ComparisonType.BUDGET.value == "budget"
        assert ComparisonType.FORECAST.value == "forecast"

    def test_ledger_entry_type_values(self):
        assert LedgerEntryType.JOURNAL.value == "journal"
        assert LedgerEntryType.ADJUSTMENT.value == "adjustment"
        assert LedgerEntryType.CLOSING.value == "closing"
        assert LedgerEntryType.REVERSAL.value == "reversal"


# =============================================================================
# Tests for Schemas (construction)
# =============================================================================

class TestSchemas:
    def test_trial_balance_line_schema(self):
        data = {
            "account_id": uuid4(),
            "account_code": "1-1000",
            "account_name": "Cash",
            "account_type": "Asset",
            "opening_balance_debit": Decimal("0"),
            "opening_balance_credit": Decimal("0"),
            "movement_debit": Decimal("1000"),
            "movement_credit": Decimal("500"),
            "closing_balance_debit": Decimal("500"),
            "closing_balance_credit": Decimal("0"),
        }
        schema = TrialBalanceLineSchema(**data)
        assert schema.account_code == "1-1000"
        assert schema.closing_balance_debit == Decimal("500")

    def test_trial_balance_response_schema(self):
        now = datetime.now(UTC)
        data = {
            "legal_entity_id": uuid4(),
            "legal_entity_name": "Test",
            "as_of_date": date.today(),
            "start_date": date.today(),
            "end_date": date.today(),
            "lines": [MagicMock()],
            "total_debit": Decimal("1000"),
            "total_credit": Decimal("1000"),
            "is_balanced": True,
            "generated_at": now,
        }
        schema = TrialBalanceResponseSchema(**data)
        assert schema.legal_entity_id == data["legal_entity_id"]
        assert schema.is_balanced is True

    def test_balance_sheet_section_schema(self):
        schema = BalanceSheetSectionSchema(lines=[{"a": 1}], total=Decimal("100"))
        assert schema.total == Decimal("100")

    def test_balance_sheet_response_schema(self):
        now = datetime.now(UTC)
        schema = BalanceSheetResponseSchema(
            legal_entity_id=uuid4(),
            legal_entity_name="Test",
            as_of_date=date.today(),
            assets=BalanceSheetSectionSchema(lines=[], total=Decimal("0")),
            liabilities=BalanceSheetSectionSchema(lines=[], total=Decimal("0")),
            equity=BalanceSheetSectionSchema(lines=[], total=Decimal("0")),
            total_assets=Decimal("1000"),
            total_liabilities=Decimal("200"),
            total_equity=Decimal("800"),
            total_liabilities_equity=Decimal("1000"),
            is_balanced=True,
            current_ratio=2.5,
            quick_ratio=1.8,
            debt_to_equity=0.25,
            generated_at=now,
        )
        assert schema.total_assets == Decimal("1000")
        assert schema.current_ratio == 2.5

    def test_income_statement_line_schema(self):
        data = {
            "account_id": uuid4(),
            "account_code": "4-1000",
            "account_name": "Revenue",
            "current_period": Decimal("1000"),
            "year_to_date": Decimal("1000"),
            "prior_period": Decimal("900"),
            "prior_year": Decimal("800"),
            "variance": Decimal("100"),
            "variance_percent": 10.0,
        }
        schema = IncomeStatementLineSchema(**data)
        assert schema.current_period == Decimal("1000")
        assert schema.variance_percent == 10.0

    def test_income_statement_response_schema(self):
        now = datetime.now(UTC)
        schema = IncomeStatementResponseSchema(
            legal_entity_id=uuid4(),
            legal_entity_name="Test",
            start_date=date.today(),
            end_date=date.today(),
            period_name="Jan",
            revenues=[],
            cost_of_goods_sold=[],
            gross_profit=Decimal("400"),
            operating_expenses=[],
            operating_income=Decimal("200"),
            other_income=[],
            other_expenses=[],
            income_before_tax=Decimal("200"),
            tax_expense=Decimal("40"),
            net_income=Decimal("160"),
            ebitda=Decimal("220"),
            gross_margin=40.0,
            operating_margin=20.0,
            net_margin=16.0,
            generated_at=now,
        )
        assert schema.net_income == Decimal("160")

    def test_cash_flow_line_schema(self):
        schema = CashFlowLineSchema(category="Operations", description="Sales", amount=Decimal("1000"))
        assert schema.amount == Decimal("1000")

    def test_cash_flow_response_schema(self):
        now = datetime.now(UTC)
        schema = CashFlowResponseSchema(
            legal_entity_id=uuid4(),
            legal_entity_name="Test",
            start_date=date.today(),
            end_date=date.today(),
            operating_activities=[],
            net_cash_operating=Decimal("1000"),
            investing_activities=[],
            net_cash_investing=Decimal("0"),
            financing_activities=[],
            net_cash_financing=Decimal("0"),
            net_increase_decrease=Decimal("1000"),
            beginning_cash=Decimal("500"),
            ending_cash=Decimal("1500"),
            free_cash_flow=Decimal("800"),
            generated_at=now,
        )
        assert schema.ending_cash == Decimal("1500")

    def test_equity_statement_line_schema(self):
        schema = EquityStatementLineSchema(
            component="Capital",
            opening_balance=Decimal("1000"),
            additions=Decimal("200"),
            deductions=Decimal("0"),
            closing_balance=Decimal("1200"),
            change=Decimal("200"),
        )
        assert schema.change == Decimal("200")

    def test_account_balance_response_schema(self):
        schema = AccountBalanceResponseSchema(
            account_id=uuid4(),
            account_code="1-1000",
            account_name="Cash",
            as_of_date=date.today(),
            balance=Decimal("500"),
            normal_balance="debit",
            is_debit_balance=True,
            opening_balance=Decimal("0"),
            debit_movement=Decimal("1000"),
            credit_movement=Decimal("500"),
        )
        assert schema.balance == Decimal("500")

    def test_ledger_entry_response_schema(self):
        now = datetime.now(UTC)
        schema = LedgerEntryResponseSchema(
            id=uuid4(),
            journal_id=uuid4(),
            journal_number="JRN-001",
            journal_date=date.today(),
            account_id=uuid4(),
            account_code="1-1000",
            account_name="Cash",
            debit_amount=Decimal("1000"),
            credit_amount=Decimal("0"),
            posting_date=date.today(),
            description="Sale",
            reference_number="REF-001",
            cost_center="CC1",
            department="Dept1",
            project_id=uuid4(),
            entry_type=LedgerEntryType.JOURNAL,
            created_at=now,
            posted_by=uuid4(),
        )
        assert schema.journal_number == "JRN-001"


# =============================================================================
# Tests for Health Check Endpoints
# =============================================================================

def test_ping():
    result = ping()
    assert result["status"] == "ok"
    assert result["service"] == "ledger-router"

def test_health():
    result = health()
    assert result["status"] == "healthy"

def test_info():
    result = info()
    assert result["version"] == "1.0"
    assert result["name"] == "Ledger Router"


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestTrialBalance:
    async def test_success(self, mock_ledger_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_trial_balance(
            as_of_date=as_of,
            include_zero_balance=True,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, TrialBalanceResponseSchema)
        assert result.legal_entity_id == mock_legal_entity_id
        assert len(result.lines) == 1
        mock_ledger_service.get_trial_balance.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
            include_zero_balance=True,
        )

    async def test_service_error(self, mock_ledger_service, mock_legal_entity_id):
        mock_ledger_service.get_trial_balance.side_effect = Exception("DB error")
        with pytest.raises(HTTPException) as exc:
            await get_trial_balance(
                as_of_date=date.today(),
                include_zero_balance=False,
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                ledger_service=mock_ledger_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestBalanceSheet:
    async def test_success(self, mock_ledger_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_balance_sheet(
            as_of_date=as_of,
            include_comparatives=True,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, BalanceSheetResponseSchema)
        assert result.legal_entity_id == mock_legal_entity_id
        assert result.total_assets == Decimal("1000")
        assert result.current_ratio == 2.5
        mock_ledger_service.get_balance_sheet.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
            include_comparatives=True,
        )


@pytest.mark.asyncio
class TestIncomeStatement:
    async def test_success(self, mock_ledger_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_income_statement(
            start_date=start,
            end_date=end,
            period=ReportPeriod.CUSTOM,
            comparison=ComparisonType.NONE,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, IncomeStatementResponseSchema)
        assert result.legal_entity_id == mock_legal_entity_id
        assert result.gross_profit == Decimal("400")
        assert result.net_income == Decimal("160")
        mock_ledger_service.get_income_statement.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
            period="custom",
            comparison="none",
        )


@pytest.mark.asyncio
class TestCashFlow:
    async def test_success_indirect(self, mock_ledger_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_cash_flow(
            start_date=start,
            end_date=end,
            method="indirect",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, CashFlowResponseSchema)
        assert result.legal_entity_id == mock_legal_entity_id
        assert result.beginning_cash == Decimal("500")
        assert result.ending_cash == Decimal("1600")
        mock_ledger_service.get_cash_flow_statement.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
            method="indirect",
        )

    async def test_success_direct(self, mock_ledger_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_cash_flow(
            start_date=start,
            end_date=end,
            method="direct",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, CashFlowResponseSchema)
        mock_ledger_service.get_cash_flow_statement.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
            method="direct",
        )


@pytest.mark.asyncio
class TestEquityStatement:
    async def test_success(self, mock_ledger_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_equity_statement(
            start_date=start,
            end_date=end,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, EquityStatementResponseSchema)
        assert result.legal_entity_id == mock_legal_entity_id
        assert result.closing_total_equity == Decimal("1310")
        mock_ledger_service.get_equity_statement.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
        )


@pytest.mark.asyncio
class TestAccountBalance:
    async def test_by_id_success(self, mock_ledger_service, mock_legal_entity_id):
        account_id = uuid4()
        as_of = date.today()
        result = await get_account_balance(
            account_id=account_id,
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, AccountBalanceResponseSchema)
        assert result.account_id == account_id
        assert result.balance == Decimal("500")
        mock_ledger_service.get_account_balance.assert_called_once_with(
            account_id=account_id,
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
        )

    async def test_by_id_not_found(self, mock_ledger_service, mock_legal_entity_id):
        mock_ledger_service.get_account_balance.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_account_balance(
                account_id=uuid4(),
                as_of_date=date.today(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                ledger_service=mock_ledger_service,
            )
        assert exc.value.status_code == 404

    async def test_by_code_success(self, mock_ledger_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_account_balance_by_code(
            account_code="1-1000",
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, AccountBalanceResponseSchema)
        assert result.account_code == "1-1000"
        mock_ledger_service.get_account_balance_by_code.assert_called_once_with(
            account_code="1-1000",
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
        )

    async def test_by_code_not_found(self, mock_ledger_service, mock_legal_entity_id):
        mock_ledger_service.get_account_balance_by_code.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_account_balance_by_code(
                account_code="UNKNOWN",
                as_of_date=date.today(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                ledger_service=mock_ledger_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestAccountBalanceHistory:
    async def test_success(self, mock_ledger_service, mock_legal_entity_id):
        account_id = uuid4()
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_account_balance_history(
            account_id=account_id,
            start_date=start,
            end_date=end,
            interval="month",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], AccountBalanceHistorySchema)
        mock_ledger_service.get_account_balance_history.assert_called_once_with(
            account_id=account_id,
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
            interval="month",
        )


@pytest.mark.asyncio
class TestLedgerEntries:
    async def test_get_entries(self, mock_ledger_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_ledger_entries(
            account_id=None,
            start_date=start,
            end_date=end,
            journal_id=None,
            page=1,
            page_size=50,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], LedgerEntryResponseSchema)
        mock_ledger_service.get_ledger_entries.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            account_id=None,
            start_date=start,
            end_date=end,
            journal_id=None,
            page=1,
            page_size=50,
        )

    async def test_get_account_entries(self, mock_ledger_service, mock_legal_entity_id):
        account_id = uuid4()
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_account_ledger_entries(
            account_id=account_id,
            start_date=start,
            end_date=end,
            page=1,
            page_size=50,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        mock_ledger_service.get_account_ledger_entries.assert_called_once_with(
            account_id=account_id,
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
            page=1,
            page_size=50,
        )

    async def test_get_journal_entries(self, mock_ledger_service, mock_legal_entity_id):
        journal_id = uuid4()
        result = await get_journal_ledger_entries(
            journal_id=journal_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        mock_ledger_service.get_ledger_entries_for_journal.assert_called_once_with(journal_id, mock_legal_entity_id)


@pytest.mark.asyncio
class TestAccountActivity:
    async def test_success(self, mock_ledger_service, mock_legal_entity_id):
        account_id = uuid4()
        fiscal_year = 2025
        result = await get_account_activity(
            account_id=account_id,
            fiscal_year=fiscal_year,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], AccountActivitySchema)
        mock_ledger_service.get_account_activity.assert_called_once_with(
            account_id=account_id,
            legal_entity_id=mock_legal_entity_id,
            fiscal_year=fiscal_year,
        )


@pytest.mark.asyncio
class TestFinancialRatios:
    async def test_success(self, mock_ledger_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_financial_ratios(
            as_of_date=as_of,
            compare_industry=True,
            industry_code="RETAIL",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert isinstance(result, FinancialRatiosResponseSchema)
        assert result.current_ratio == 2.5
        assert result.industry_comparison == {"industry": "Retail", "average_ratio": 2.0}
        mock_ledger_service.get_financial_ratios.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
            compare_industry=True,
            industry_code="RETAIL",
        )


@pytest.mark.asyncio
class TestExport:
    async def test_export_trial_balance_csv(self, mock_ledger_service, mock_legal_entity_id):
        as_of = date.today()
        response = await export_trial_balance(
            as_of_date=as_of,
            format="csv",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_ledger_service.export_trial_balance.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
            format="csv",
        )

    async def test_export_trial_balance_excel(self, mock_ledger_service, mock_legal_entity_id):
        mock_ledger_service.export_trial_balance.return_value = b"excel data"
        as_of = date.today()
        response = await export_trial_balance(
            as_of_date=as_of,
            format="excel",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    async def test_export_general_ledger_csv(self, mock_ledger_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        response = await export_general_ledger(
            start_date=start,
            end_date=end,
            format="csv",
            account_id=None,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        mock_ledger_service.export_general_ledger.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
            format="csv",
            account_id=None,
        )


@pytest.mark.asyncio
class TestLedgerSummary:
    async def test_success(self, mock_ledger_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_ledger_summary(
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ledger_service=mock_ledger_service,
        )
        assert result["total_accounts"] == 10
        assert result["active_accounts"] == 8
        assert result["total_journals_ytd"] == 50
        mock_ledger_service.get_ledger_summary.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
        )


# =============================================================================
# Tests for Dependency Injection
# =============================================================================

@pytest.mark.asyncio
async def test_get_ledger_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_ledger_service(request)
    assert result == "service"
