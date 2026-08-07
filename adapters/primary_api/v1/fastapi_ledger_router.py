#!/usr/bin/env python3
"""
Module: fastapi_ledger_router.py
Layer: Adapters (Primary API - v1)
Responsibility: REST API endpoint untuk membaca data General Ledger (Ledger).
"""

from __future__ import annotationsimport loggingfrom datetime import date, datetimefrom decimal import Decimalfrom enum import Enumfrom typing import Anyfrom uuid import UUIDfrom fastapi import APIRouter, Depends, HTTPException, Query, Requestfrom fastapi.responses import Responsefrom pydantic import BaseModel, ConfigDict, Fieldfrom sqlalchemy.ext.asyncio import AsyncSessionfrom adapters.primary_api.common.fastapi_auth_jwt_middleware import (    get_current_legal_entity,    require_permission,)from infrastructure.database.session_factory_sqlalchemy import get_async_sessionlogger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class ReportPeriod(str, Enum):
    CURRENT_MONTH = "current_month"
    PREVIOUS_MONTH = "previous_month"
    CURRENT_QUARTER = "current_quarter"
    PREVIOUS_QUARTER = "previous_quarter"
    YEAR_TO_DATE = "ytd"
    PREVIOUS_YEAR = "previous_year"
    CUSTOM = "custom"


class ComparisonType(str, Enum):
    NONE = "none"
    PREVIOUS_PERIOD = "previous_period"
    PREVIOUS_YEAR = "previous_year"
    BUDGET = "budget"
    FORECAST = "forecast"


class LedgerEntryType(str, Enum):
    JOURNAL = "journal"
    ADJUSTMENT = "adjustment"
    CLOSING = "closing"
    REVERSAL = "reversal"


class TrialBalanceLineSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    account_code: str
    account_name: str
    account_type: str
    opening_balance_debit: Decimal = Field(0, decimal_places=2)
    opening_balance_credit: Decimal = Field(0, decimal_places=2)
    movement_debit: Decimal = Field(0, decimal_places=2)
    movement_credit: Decimal = Field(0, decimal_places=2)
    closing_balance_debit: Decimal = Field(0, decimal_places=2)
    closing_balance_credit: Decimal = Field(0, decimal_places=2)


class TrialBalanceResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    legal_entity_id: UUID
    legal_entity_name: str | None = None
    as_of_date: date
    start_date: date
    end_date: date
    lines: list[TrialBalanceLineSchema]
    total_debit: Decimal
    total_credit: Decimal
    is_balanced: bool
    generated_at: datetime


class BalanceSheetSectionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lines: list[dict[str, Any]]
    total: Decimal


class BalanceSheetResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    legal_entity_id: UUID
    legal_entity_name: str | None = None
    as_of_date: date
    assets: BalanceSheetSectionSchema
    liabilities: BalanceSheetSectionSchema
    equity: BalanceSheetSectionSchema
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    total_liabilities_equity: Decimal
    is_balanced: bool
    current_ratio: float | None = None
    quick_ratio: float | None = None
    debt_to_equity: float | None = None
    generated_at: datetime


class IncomeStatementLineSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    account_code: str
    account_name: str
    current_period: Decimal
    year_to_date: Decimal
    prior_period: Decimal | None = None
    prior_year: Decimal | None = None
    variance: Decimal | None = None
    variance_percent: float | None = None


class IncomeStatementResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    legal_entity_id: UUID
    legal_entity_name: str | None = None
    start_date: date
    end_date: date
    period_name: str
    revenues: list[IncomeStatementLineSchema]
    cost_of_goods_sold: list[IncomeStatementLineSchema]
    gross_profit: Decimal
    operating_expenses: list[IncomeStatementLineSchema]
    operating_income: Decimal
    other_income: list[IncomeStatementLineSchema]
    other_expenses: list[IncomeStatementLineSchema]
    income_before_tax: Decimal
    tax_expense: Decimal
    net_income: Decimal
    ebitda: Decimal | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    generated_at: datetime


class CashFlowLineSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: str
    description: str
    amount: Decimal


class CashFlowResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    legal_entity_id: UUID
    legal_entity_name: str | None = None
    start_date: date
    end_date: date
    operating_activities: list[CashFlowLineSchema]
    net_cash_operating: Decimal
    investing_activities: list[CashFlowLineSchema]
    net_cash_investing: Decimal
    financing_activities: list[CashFlowLineSchema]
    net_cash_financing: Decimal
    net_increase_decrease: Decimal
    beginning_cash: Decimal
    ending_cash: Decimal
    free_cash_flow: Decimal | None = None
    generated_at: datetime


class EquityStatementLineSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    component: str
    opening_balance: Decimal
    additions: Decimal
    deductions: Decimal
    closing_balance: Decimal
    change: Decimal


class EquityStatementResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    legal_entity_id: UUID
    legal_entity_name: str | None = None
    start_date: date
    end_date: date
    lines: list[EquityStatementLineSchema]
    opening_total_equity: Decimal
    net_income: Decimal
    other_comprehensive_income: Decimal
    dividends_declared: Decimal
    capital_changes: Decimal
    closing_total_equity: Decimal
    generated_at: datetime


class AccountBalanceResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    account_code: str
    account_name: str
    as_of_date: date
    balance: Decimal
    normal_balance: str
    is_debit_balance: bool
    opening_balance: Decimal
    debit_movement: Decimal
    credit_movement: Decimal


class AccountBalanceHistorySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of_date: date
    balance: Decimal
    debit_movement: Decimal
    credit_movement: Decimal
    net_change: Decimal


class LedgerEntryResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    journal_id: UUID
    journal_number: str
    journal_date: date
    account_id: UUID
    account_code: str
    account_name: str
    debit_amount: Decimal
    credit_amount: Decimal
    posting_date: date
    description: str
    reference_number: str | None = None
    cost_center: str | None = None
    department: str | None = None
    project_id: UUID | None = None
    entry_type: LedgerEntryType
    created_at: datetime
    posted_by: UUID


class FinancialRatiosResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of_date: date
    current_ratio: float | None = None
    quick_ratio: float | None = None
    cash_ratio: float | None = None
    debt_to_equity: float | None = None
    debt_to_assets: float | None = None
    interest_coverage: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    return_on_assets: float | None = None
    return_on_equity: float | None = None
    asset_turnover: float | None = None
    inventory_turnover: float | None = None
    receivable_turnover: float | None = None
    payable_turnover: float | None = None
    industry_comparison: dict[str, Any] | None = None
    generated_at: datetime


class AccountActivitySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period: str
    opening_balance: Decimal
    debit: Decimal
    credit: Decimal
    closing_balance: Decimal


async def get_ledger_service(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    from application.service_layer.service_ledger import LedgerService
    container = request.app.state.container
    ledger_service = await container.resolve_async(LedgerService)
    ledger_service._ledger_repo.session = session
    return ledger_service


router = APIRouter(prefix="/ledger", tags=["General Ledger"])


# ----------------------------------------------------------------------------
# SYNCHRONOUS HEALTH CHECKS
# ----------------------------------------------------------------------------

@router.get("/ping")
def ping() -> dict[str, str]:
    return {"status": "ok", "service": "ledger-router"}

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}

@router.get("/info")
def info() -> dict[str, str]:
    return {"version": "1.0", "name": "Ledger Router"}


# ----------------------------------------------------------------------------
# TRIAL BALANCE
# ----------------------------------------------------------------------------

@router.get(
    "/trial-balance",
    response_model=TrialBalanceResponseSchema,
    summary="Get trial balance",
    operation_id="ledger_get_trial_balance",
)
async def get_trial_balance(
    as_of_date: date = Query(..., description="Tanggal neraca saldo"),
    include_zero_balance: bool = Query(False, description="Sertakan akun dengan saldo nol"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> TrialBalanceResponseSchema:
    try:
        result = await ledger_service.get_trial_balance(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            include_zero_balance=include_zero_balance,
        )

        lines = [
            TrialBalanceLineSchema(
                account_id=line.account_id,
                account_code=line.account_code,
                account_name=line.account_name,
                account_type=line.account_type,
                opening_balance_debit=line.opening_balance_debit,
                opening_balance_credit=line.opening_balance_credit,
                movement_debit=line.movement_debit,
                movement_credit=line.movement_credit,
                closing_balance_debit=line.closing_balance_debit,
                closing_balance_credit=line.closing_balance_credit,
            )
            for line in result.lines
        ]

        return TrialBalanceResponseSchema(
            legal_entity_id=legal_entity_id,
            legal_entity_name=result.legal_entity_name,
            as_of_date=as_of_date,
            start_date=result.start_date,
            end_date=as_of_date,
            lines=lines,
            total_debit=result.total_debit,
            total_credit=result.total_credit,
            is_balanced=result.is_balanced,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get trial balance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BALANCE SHEET
# ----------------------------------------------------------------------------

@router.get(
    "/balance-sheet",
    response_model=BalanceSheetResponseSchema,
    summary="Get balance sheet",
    operation_id="ledger_get_balance_sheet",
)
async def get_balance_sheet(
    as_of_date: date = Query(..., description="Tanggal neraca"),
    include_comparatives: bool = Query(False, description="Include prior period comparatives"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> BalanceSheetResponseSchema:
    try:
        result = await ledger_service.get_balance_sheet(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            include_comparatives=include_comparatives,
        )

        return BalanceSheetResponseSchema(
            legal_entity_id=legal_entity_id,
            legal_entity_name=result.legal_entity_name,
            as_of_date=as_of_date,
            assets=BalanceSheetSectionSchema(
                lines=result.assets_lines,
                total=result.total_assets,
            ),
            liabilities=BalanceSheetSectionSchema(
                lines=result.liabilities_lines,
                total=result.total_liabilities,
            ),
            equity=BalanceSheetSectionSchema(
                lines=result.equity_lines,
                total=result.total_equity,
            ),
            total_assets=result.total_assets,
            total_liabilities=result.total_liabilities,
            total_equity=result.total_equity,
            total_liabilities_equity=result.total_liabilities + result.total_equity,
            is_balanced=abs(result.total_assets - (result.total_liabilities + result.total_equity))
            < Decimal("0.01"),
            current_ratio=result.current_ratio,
            quick_ratio=result.quick_ratio,
            debt_to_equity=result.debt_to_equity,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get balance sheet: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# INCOME STATEMENT
# ----------------------------------------------------------------------------

@router.get(
    "/income-statement",
    response_model=IncomeStatementResponseSchema,
    summary="Get income statement (P&L)",
    operation_id="ledger_get_income_statement",
)
async def get_income_statement(
    start_date: date = Query(..., description="Tanggal awal periode"),
    end_date: date = Query(..., description="Tanggal akhir periode"),
    period: ReportPeriod = Query(ReportPeriod.CUSTOM, description="Period preset"),
    comparison: ComparisonType = Query(ComparisonType.NONE, description="Comparison type"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> IncomeStatementResponseSchema:
    try:
        result = await ledger_service.get_income_statement(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            period=period.value,
            comparison=comparison.value,
        )

        return IncomeStatementResponseSchema(
            legal_entity_id=legal_entity_id,
            legal_entity_name=result.legal_entity_name,
            start_date=start_date,
            end_date=end_date,
            period_name=result.period_name,
            revenues=[IncomeStatementLineSchema(**item) for item in result.revenues],
            cost_of_goods_sold=[IncomeStatementLineSchema(**item) for item in result.cogs],
            gross_profit=result.gross_profit,
            operating_expenses=[
                IncomeStatementLineSchema(**item) for item in result.operating_expenses
            ],
            operating_income=result.operating_income,
            other_income=[IncomeStatementLineSchema(**item) for item in result.other_income],
            other_expenses=[IncomeStatementLineSchema(**item) for item in result.other_expenses],
            income_before_tax=result.income_before_tax,
            tax_expense=result.tax_expense,
            net_income=result.net_income,
            ebitda=result.ebitda,
            gross_margin=result.gross_margin,
            operating_margin=result.operating_margin,
            net_margin=result.net_margin,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get income statement: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# CASH FLOW STATEMENT
# ----------------------------------------------------------------------------

@router.get(
    "/cash-flow",
    response_model=CashFlowResponseSchema,
    summary="Get cash flow statement",
    operation_id="ledger_get_cash_flow",
)
async def get_cash_flow(
    start_date: date = Query(..., description="Tanggal awal periode"),
    end_date: date = Query(..., description="Tanggal akhir periode"),
    method: str = Query(
        "indirect", pattern="^(direct|indirect)$", description="Method: direct or indirect"
    ),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> CashFlowResponseSchema:
    try:
        result = await ledger_service.get_cash_flow_statement(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            method=method,
        )

        return CashFlowResponseSchema(
            legal_entity_id=legal_entity_id,
            legal_entity_name=result.legal_entity_name,
            start_date=start_date,
            end_date=end_date,
            operating_activities=[
                CashFlowLineSchema(**item) for item in result.operating_activities
            ],
            net_cash_operating=result.net_cash_operating,
            investing_activities=[
                CashFlowLineSchema(**item) for item in result.investing_activities
            ],
            net_cash_investing=result.net_cash_investing,
            financing_activities=[
                CashFlowLineSchema(**item) for item in result.financing_activities
            ],
            net_cash_financing=result.net_cash_financing,
            net_increase_decrease=result.net_increase_decrease,
            beginning_cash=result.beginning_cash,
            ending_cash=result.ending_cash,
            free_cash_flow=result.free_cash_flow,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get cash flow statement: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EQUITY STATEMENT
# ----------------------------------------------------------------------------

@router.get(
    "/equity-statement",
    response_model=EquityStatementResponseSchema,
    summary="Get statement of changes in equity",
    operation_id="ledger_get_equity_statement",
)
async def get_equity_statement(
    start_date: date = Query(..., description="Tanggal awal periode"),
    end_date: date = Query(..., description="Tanggal akhir periode"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> EquityStatementResponseSchema:
    try:
        result = await ledger_service.get_equity_statement(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
        )

        return EquityStatementResponseSchema(
            legal_entity_id=legal_entity_id,
            legal_entity_name=result.legal_entity_name,
            start_date=start_date,
            end_date=end_date,
            lines=[
                EquityStatementLineSchema(
                    component=line.component,
                    opening_balance=line.opening_balance,
                    additions=line.additions,
                    deductions=line.deductions,
                    closing_balance=line.closing_balance,
                    change=line.change,
                )
                for line in result.lines
            ],
            opening_total_equity=result.opening_total_equity,
            net_income=result.net_income,
            other_comprehensive_income=result.other_comprehensive_income,
            dividends_declared=result.dividends_declared,
            capital_changes=result.capital_changes,
            closing_total_equity=result.closing_total_equity,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get equity statement: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ACCOUNT BALANCE
# ----------------------------------------------------------------------------

@router.get(
    "/accounts/{account_id}/balance",
    response_model=AccountBalanceResponseSchema,
    summary="Get account balance",
    operation_id="ledger_get_account_balance",  # <-- UNIK
)
async def get_account_balance(
    account_id: UUID,
    as_of_date: date = Query(..., description="Tanggal saldo"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> AccountBalanceResponseSchema:
    try:
        result = await ledger_service.get_account_balance(
            account_id=account_id,
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Account not found")

        return AccountBalanceResponseSchema(
            account_id=account_id,
            account_code=result.account_code,
            account_name=result.account_name,
            as_of_date=as_of_date,
            balance=result.balance,
            normal_balance=result.normal_balance,
            is_debit_balance=result.is_debit_balance,
            opening_balance=result.opening_balance,
            debit_movement=result.debit_movement,
            credit_movement=result.credit_movement,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get account balance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/accounts/by-code/{account_code}/balance",
    response_model=AccountBalanceResponseSchema,
    summary="Get account balance by account code",
    operation_id="ledger_get_account_balance_by_code",
)
async def get_account_balance_by_code(
    account_code: str,
    as_of_date: date = Query(..., description="Tanggal saldo"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> AccountBalanceResponseSchema:
    try:
        result = await ledger_service.get_account_balance_by_code(
            account_code=account_code,
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
        )

        if not result:
            raise HTTPException(status_code=404, detail=f"Account {account_code} not found")

        return AccountBalanceResponseSchema(
            account_id=result.account_id,
            account_code=account_code,
            account_name=result.account_name,
            as_of_date=as_of_date,
            balance=result.balance,
            normal_balance=result.normal_balance,
            is_debit_balance=result.is_debit_balance,
            opening_balance=result.opening_balance,
            debit_movement=result.debit_movement,
            credit_movement=result.credit_movement,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get account balance by code: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ACCOUNT BALANCE HISTORY
# ----------------------------------------------------------------------------

@router.get(
    "/accounts/{account_id}/balance-history",
    response_model=list[AccountBalanceHistorySchema],
    summary="Get account balance history",
    operation_id="ledger_get_account_balance_history",
)
async def get_account_balance_history(
    account_id: UUID,
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    interval: str = Query("month", pattern="^(day|week|month|quarter)$", description="Interval"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> list[AccountBalanceHistorySchema]:
    try:
        history = await ledger_service.get_account_balance_history(
            account_id=account_id,
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        return [
            AccountBalanceHistorySchema(
                as_of_date=h.as_of_date,
                balance=h.balance,
                debit_movement=h.debit_movement,
                credit_movement=h.credit_movement,
                net_change=h.net_change,
            )
            for h in history
        ]
    except Exception as e:
        logger.exception(f"Failed to get account balance history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LEDGER ENTRIES
# ----------------------------------------------------------------------------

@router.get(
    "/entries",
    response_model=list[LedgerEntryResponseSchema],
    summary="Get ledger entries",
    operation_id="ledger_get_entries",
)
async def get_ledger_entries(
    account_id: UUID | None = Query(None, description="Filter by account"),
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    journal_id: UUID | None = Query(None, description="Filter by journal"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=1000, description="Items per page"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> list[LedgerEntryResponseSchema]:
    try:
        entries = await ledger_service.get_ledger_entries(
            legal_entity_id=legal_entity_id,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            journal_id=journal_id,
            page=page,
            page_size=page_size,
        )

        return [
            LedgerEntryResponseSchema(
                id=e.id,
                journal_id=e.journal_id,
                journal_number=e.journal_number,
                journal_date=e.journal_date,
                account_id=e.account_id,
                account_code=e.account_code,
                account_name=e.account_name,
                debit_amount=e.debit_amount,
                credit_amount=e.credit_amount,
                posting_date=e.posting_date,
                description=e.description,
                reference_number=e.reference_number,
                cost_center=e.cost_center,
                department=e.department,
                project_id=e.project_id,
                entry_type=LedgerEntryType(e.entry_type),
                created_at=e.created_at,
                posted_by=e.posted_by,
            )
            for e in entries
        ]
    except Exception as e:
        logger.exception(f"Failed to get ledger entries: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/entries/account/{account_id}",
    response_model=list[LedgerEntryResponseSchema],
    summary="Get ledger entries for an account",
    operation_id="ledger_get_account_entries",
)
async def get_account_ledger_entries(
    account_id: UUID,
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=1000, description="Items per page"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> list[LedgerEntryResponseSchema]:
    try:
        entries = await ledger_service.get_account_ledger_entries(
            account_id=account_id,
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        return [
            LedgerEntryResponseSchema(
                id=e.id,
                journal_id=e.journal_id,
                journal_number=e.journal_number,
                journal_date=e.journal_date,
                account_id=e.account_id,
                account_code=e.account_code,
                account_name=e.account_name,
                debit_amount=e.debit_amount,
                credit_amount=e.credit_amount,
                posting_date=e.posting_date,
                description=e.description,
                reference_number=e.reference_number,
                cost_center=e.cost_center,
                department=e.department,
                project_id=e.project_id,
                entry_type=LedgerEntryType(e.entry_type),
                created_at=e.created_at,
                posted_by=e.posted_by,
            )
            for e in entries
        ]
    except Exception as e:
        logger.exception(f"Failed to get account ledger entries: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# JOURNAL LEDGER ENTRIES (FIXED OPERATION ID)
# ----------------------------------------------------------------------------

@router.get(
    "/journals/{journal_id}/entries",
    response_model=list[LedgerEntryResponseSchema],
    summary="Get ledger entries for a journal",
    operation_id="ledger_get_journal_entries",  # <-- UNIK
)
async def get_journal_ledger_entries(
    journal_id: UUID,
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> list[LedgerEntryResponseSchema]:
    try:
        entries = await ledger_service.get_ledger_entries_for_journal(journal_id, legal_entity_id)

        return [
            LedgerEntryResponseSchema(
                id=e.id,
                journal_id=e.journal_id,
                journal_number=e.journal_number,
                journal_date=e.journal_date,
                account_id=e.account_id,
                account_code=e.account_code,
                account_name=e.account_name,
                debit_amount=e.debit_amount,
                credit_amount=e.credit_amount,
                posting_date=e.posting_date,
                description=e.description,
                reference_number=e.reference_number,
                cost_center=e.cost_center,
                department=e.department,
                project_id=e.project_id,
                entry_type=LedgerEntryType(e.entry_type),
                created_at=e.created_at,
                posted_by=e.posted_by,
            )
            for e in entries
        ]
    except Exception as e:
        logger.exception(f"Failed to get journal ledger entries: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ACCOUNT ACTIVITY
# ----------------------------------------------------------------------------

@router.get(
    "/accounts/{account_id}/activity",
    response_model=list[AccountActivitySchema],
    summary="Get account activity by period",
    operation_id="ledger_get_account_activity",
)
async def get_account_activity(
    account_id: UUID,
    fiscal_year: int = Query(..., description="Fiscal year"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> list[AccountActivitySchema]:
    try:
        activity = await ledger_service.get_account_activity(
            account_id=account_id,
            legal_entity_id=legal_entity_id,
            fiscal_year=fiscal_year,
        )

        return [
            AccountActivitySchema(
                period=a.period,
                opening_balance=a.opening_balance,
                debit=a.debit,
                credit=a.credit,
                closing_balance=a.closing_balance,
            )
            for a in activity
        ]
    except Exception as e:
        logger.exception(f"Failed to get account activity: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# FINANCIAL RATIOS
# ----------------------------------------------------------------------------

@router.get(
    "/financial-ratios",
    response_model=FinancialRatiosResponseSchema,
    summary="Get financial ratios",
    operation_id="ledger_get_financial_ratios",
)
async def get_financial_ratios(
    as_of_date: date = Query(..., description="Date for ratios calculation"),
    compare_industry: bool = Query(False, description="Compare with industry averages"),
    industry_code: str | None = Query(None, description="Industry code for comparison"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> FinancialRatiosResponseSchema:
    try:
        result = await ledger_service.get_financial_ratios(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            compare_industry=compare_industry,
            industry_code=industry_code,
        )

        return FinancialRatiosResponseSchema(
            as_of_date=as_of_date,
            current_ratio=result.current_ratio,
            quick_ratio=result.quick_ratio,
            cash_ratio=result.cash_ratio,
            debt_to_equity=result.debt_to_equity,
            debt_to_assets=result.debt_to_assets,
            interest_coverage=result.interest_coverage,
            gross_margin=result.gross_margin,
            operating_margin=result.operating_margin,
            net_margin=result.net_margin,
            return_on_assets=result.return_on_assets,
            return_on_equity=result.return_on_equity,
            asset_turnover=result.asset_turnover,
            inventory_turnover=result.inventory_turnover,
            receivable_turnover=result.receivable_turnover,
            payable_turnover=result.payable_turnover,
            industry_comparison=result.industry_comparison,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get financial ratios: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT REPORTS
# ----------------------------------------------------------------------------

@router.get(
    "/export/trial-balance",
    summary="Export trial balance",
    operation_id="ledger_export_trial_balance",
)
async def export_trial_balance(
    as_of_date: date = Query(..., description="Trial balance date"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    _permission: None = Depends(require_permission("ledger:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> Response:
    try:
        data = await ledger_service.export_trial_balance(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            format=format,
        )

        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"trial_balance_{legal_entity_id}_{as_of_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception(f"Failed to export trial balance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/export/general-ledger",
    summary="Export general ledger",
    operation_id="ledger_export_general_ledger",
)
async def export_general_ledger(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    account_id: UUID | None = Query(None, description="Filter by account"),
    _permission: None = Depends(require_permission("ledger:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> Response:
    try:
        data = await ledger_service.export_general_ledger(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            format=format,
            account_id=account_id,
        )

        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"general_ledger_{legal_entity_id}_{start_date}_{end_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception(f"Failed to export general ledger: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LEDGER SUMMARY
# ----------------------------------------------------------------------------

@router.get(
    "/summary",
    response_model=dict[str, Any],
    summary="Get ledger summary",
    operation_id="ledger_get_summary",
)
async def get_ledger_summary(
    as_of_date: date = Query(..., description="Date for summary"),
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ledger_service: Any = Depends(get_ledger_service),
) -> dict[str, Any]:
    try:
        summary = await ledger_service.get_ledger_summary(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
        )

        return {
            "legal_entity_id": str(legal_entity_id),
            "as_of_date": as_of_date.isoformat(),
            "total_accounts": summary.total_accounts,
            "active_accounts": summary.active_accounts,
            "accounts_with_balance": summary.accounts_with_balance,
            "total_debit_balance": float(summary.total_debit_balance),
            "total_credit_balance": float(summary.total_credit_balance),
            "total_journals_ytd": summary.total_journals_ytd,
            "total_entries_ytd": summary.total_entries_ytd,
            "last_posted_at": summary.last_posted_at.isoformat()
            if summary.last_posted_at
            else None,
            "last_posted_by": str(summary.last_posted_by) if summary.last_posted_by else None,
        }
    except Exception as e:
        logger.exception(f"Failed to get ledger summary: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


__all__ = ["router"]
