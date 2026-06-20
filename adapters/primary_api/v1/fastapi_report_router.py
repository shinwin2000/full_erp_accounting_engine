
#!/usr/bin/env python3
"""
Module: fastapi_report_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk generate dan mengunduh
               berbagai laporan keuangan dan manajerial, termasuk laporan terjadwal,
               distribusi via email/WhatsApp, dan export ke berbagai format.

Method Standards (ERP):
- generate_financial_report() / generate_balance_sheet() / generate_income_statement()
- generate_cash_flow() / generate_equity_statement()
- generate_trial_balance() / generate_general_ledger()
- generate_aging_report() / generate_stock_card()
- generate_fixed_asset_register() / generate_depreciation_schedule()
- generate_tax_report() / generate_budget_vs_actual()
- generate_financial_ratios() / generate_kpi_dashboard()
- schedule_report() / unschedule_report() / get_scheduled_reports()
- send_report() / distribute_report() / get_report_distribution_status()
- export_report() / download_report()
- get_report_history() / get_report_status()
- audit_trail_report() / register_report_event()
- version_report()
"""


from __future__ import annotations
from fastapi import Request

import logging
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from adapters.dependency_provider import get_service
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class ReportType(str, Enum):
    """Jenis laporan."""

    # Financial Statements
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    EQUITY_STATEMENT = "equity_statement"

    # Ledger Reports
    TRIAL_BALANCE = "trial_balance"
    GENERAL_LEDGER = "general_ledger"
    JOURNAL = "journal"

    # Subledger Reports
    AR_AGING = "ar_aging"
    AP_AGING = "ap_aging"
    AR_SUBLEDGER = "ar_subledger"
    AP_SUBLEDGER = "ap_subledger"

    # Inventory Reports
    STOCK_CARD = "stock_card"
    INVENTORY_VALUATION = "inventory_valuation"
    INVENTORY_SUMMARY = "inventory_summary"
    LOW_STOCK = "low_stock"

    # Fixed Asset Reports
    FIXED_ASSET_REGISTER = "fixed_asset_register"
    DEPRECIATION_SCHEDULE = "depreciation_schedule"
    FIXED_ASSET_SUMMARY = "fixed_asset_summary"

    # Tax Reports
    TAX_SUMMARY = "tax_summary"
    VAT_RETURN = "vat_return"
    WITHHOLDING_TAX = "withholding_tax"
    CORPORATE_TAX = "corporate_tax"

    # Budget Reports
    BUDGET_VS_ACTUAL = "budget_vs_actual"
    BUDGET_SUMMARY = "budget_summary"

    # Analytics Reports
    FINANCIAL_RATIOS = "financial_ratios"
    KPI_DASHBOARD = "kpi_dashboard"
    TREND_ANALYSIS = "trend_analysis"

    # Manufacturing Reports
    COST_CARD = "cost_card"
    WORK_ORDER = "work_order"
    VARIANCE_ANALYSIS = "variance_analysis"
    HPP = "hpp"

    # Project Reports
    PROJECT_COST = "project_cost"
    PROJECT_REVENUE = "project_revenue"
    PROJECT_SUMMARY = "project_summary"

    # Audit Reports
    AUDIT_TRAIL = "audit_trail"
    HASH_CHAIN = "hash_chain"
    CONSISTENCY_CHECK = "consistency_check"


class ReportFormat(str, Enum):
    """Format laporan."""

    PDF = "pdf"
    EXCEL = "xlsx"
    CSV = "csv"
    HTML = "html"
    JSON = "json"
    XML = "xml"


class ScheduleFrequency(str, Enum):
    """Frekuensi penjadwalan."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUALLY = "semi_annually"
    YEARLY = "yearly"
    CUSTOM = "custom"


class DeliveryMethod(str, Enum):
    """Metode pengiriman."""

    EMAIL = "email"
    WHATSAPP = "whatsapp"
    WEBHOOK = "webhook"
    FTP = "ftp"
    S3 = "s3"
    PRINT = "print"


class ReportStatus(str, Enum):
    """Status laporan."""

    PENDING = "pending"
    PROCESSING = "processing"
    GENERATED = "generated"
    FAILED = "failed"
    SENT = "sent"
    CANCELLED = "cancelled"


# Default report settings
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 500
REPORT_RETENTION_DAYS = 90
MAX_REPORT_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class ReportRequestSchema(BaseModel):
    """Schema untuk request generate laporan."""

    model_config = ConfigDict(from_attributes=True)

    report_type: ReportType = Field(..., description="Jenis laporan")
    report_format: ReportFormat = Field(ReportFormat.PDF, description="Format laporan")
    start_date: date | None = Field(None, description="Tanggal awal periode")
    end_date: date | None = Field(None, description="Tanggal akhir periode")
    as_of_date: date | None = Field(None, description="Tanggal laporan (untuk balance sheet)")
    account_id: UUID | None = Field(None, description="Filter by account")
    account_code: str | None = Field(None, description="Filter by account code")
    customer_id: UUID | None = Field(None, description="Filter by customer")
    vendor_id: UUID | None = Field(None, description="Filter by vendor")
    item_id: UUID | None = Field(None, description="Filter by item")
    warehouse_id: UUID | None = Field(None, description="Filter by warehouse")
    project_id: UUID | None = Field(None, description="Filter by project")
    include_details: bool = Field(True, description="Include detailed lines")
    compare_with_previous: bool = Field(False, description="Compare with previous period")
    currency: str = Field("IDR", description="Mata uang laporan")
    parameters: dict[str, Any] | None = Field(None, description="Parameter tambahan")

    @model_validator(mode="after")
    def validate_dates(self) -> ReportRequestSchema:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Start date must be before end date")
        return self


class ReportResponseSchema(BaseModel):
    """Response laporan."""

    model_config = ConfigDict(from_attributes=True)

    report_id: UUID
    report_number: str
    report_type: ReportType
    report_format: ReportFormat
    status: ReportStatus
    file_size_bytes: int | None = None
    file_path: str | None = None
    download_url: str | None = None
    parameters: dict[str, Any]
    generated_at: datetime
    generated_by: UUID
    generated_by_name: str | None = None
    expires_at: datetime | None = None
    is_deleted: bool = False


class ReportListResponseSchema(BaseModel):
    """Response list laporan."""

    model_config = ConfigDict(from_attributes=True)

    items: list[ReportResponseSchema]
    total: int
    page: int
    page_size: int


class ReportScheduleCreateSchema(BaseModel):
    """Schema untuk membuat jadwal laporan."""

    model_config = ConfigDict(from_attributes=True)

    report_type: ReportType = Field(..., description="Jenis laporan")
    schedule_name: str = Field(..., min_length=3, max_length=200, description="Nama jadwal")
    schedule_frequency: ScheduleFrequency = Field(..., description="Frekuensi")
    schedule_time: str | None = Field(None, description="Waktu eksekusi (HH:MM)")
    schedule_day_of_week: int | None = Field(None, ge=0, le=6, description="Day of week (0=Monday)")
    schedule_day_of_month: int | None = Field(None, ge=1, le=31, description="Day of month")
    report_format: ReportFormat = Field(ReportFormat.PDF, description="Format laporan")
    parameters: dict[str, Any] = Field(..., description="Parameter laporan")
    recipient_emails: list[str] = Field(default_factory=list, description="Email recipients")
    recipient_whatsapps: list[str] = Field(default_factory=list, description="WhatsApp recipients")
    delivery_methods: list[DeliveryMethod] = Field(
        default_factory=list, description="Delivery methods"
    )
    is_active: bool = Field(True, description="Aktif")
    notes: str | None = Field(None, max_length=500)

    @field_validator("schedule_name")
    @classmethod
    def validate_schedule_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Schedule name is required")
        return v.strip()

    @model_validator(mode="after")
    def validate_schedule(self) -> ReportScheduleCreateSchema:
        if (
            self.schedule_frequency == ScheduleFrequency.WEEKLY
            and self.schedule_day_of_week is None
        ):
            raise ValueError("day_of_week required for weekly schedule")
        if (
            self.schedule_frequency == ScheduleFrequency.MONTHLY
            and self.schedule_day_of_month is None
        ):
            raise ValueError("day_of_month required for monthly schedule")
        if self.schedule_frequency == ScheduleFrequency.CUSTOM and not self.schedule_time:
            raise ValueError("schedule_time required for custom schedule")
        return self


class ReportScheduleResponseSchema(BaseModel):
    """Response jadwal laporan."""

    model_config = ConfigDict(from_attributes=True)

    schedule_id: UUID
    schedule_name: str
    report_type: ReportType
    schedule_frequency: ScheduleFrequency
    schedule_time: str | None
    schedule_day_of_week: int | None
    schedule_day_of_month: int | None
    report_format: ReportFormat
    parameters: dict[str, Any]
    recipient_emails: list[str]
    recipient_whatsapps: list[str]
    delivery_methods: list[DeliveryMethod]
    is_active: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class ReportDistributionSchema(BaseModel):
    """Schema untuk distribusi laporan."""

    model_config = ConfigDict(from_attributes=True)

    report_id: UUID = Field(..., description="ID laporan")
    recipient_emails: list[str] = Field(default_factory=list, description="Email recipients")
    recipient_whatsapps: list[str] = Field(default_factory=list, description="WhatsApp recipients")
    subject: str | None = Field(None, max_length=500, description="Subject")
    message: str | None = Field(None, max_length=1000, description="Message")
    delivery_methods: list[DeliveryMethod] = Field(default_factory=list)


class ReportDistributionResponseSchema(BaseModel):
    """Response distribusi laporan."""

    model_config = ConfigDict(from_attributes=True)

    distribution_id: UUID
    report_id: UUID
    recipient_email: str | None
    recipient_whatsapp: str | None
    delivery_method: DeliveryMethod
    status: str
    sent_at: datetime | None
    error_message: str | None


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_report_service(request: Request, ) -> Any:
    """Get Report Service instance."""
    from application.service_layer.service_report import ReportService
    from fastapi import Request

    container = request.app.state.container
    return container.resolve(ReportService)


async def get_report_scheduler() -> Any:
    """Get Report Scheduler instance."""
    from fastapi import Request
    from reports.scheduler_cron import ReportScheduler

    container = request.app.state.container
    return container.resolve(ReportScheduler)


async def get_report_distributor() -> Any:
    """Get Report Distributor instance."""
    from fastapi import Request
    from reports.distributor_email_whatsapp import ReportDistributor

    container = request.app.state.container
    return container.resolve(ReportDistributor)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _get_media_type(format: ReportFormat) -> str:
    """Get media type for response."""
    return {
        ReportFormat.PDF: "application/pdf",
        ReportFormat.EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ReportFormat.CSV: "text/csv",
        ReportFormat.HTML: "text/html",
        ReportFormat.JSON: "application/json",
        ReportFormat.XML: "application/xml",
    }.get(format, "application/octet-stream")


def _get_filename(report_number: str, report_format: ReportFormat) -> str:
    """Get filename for download."""
    extension = {
        ReportFormat.PDF: "pdf",
        ReportFormat.EXCEL: "xlsx",
        ReportFormat.CSV: "csv",
        ReportFormat.HTML: "html",
        ReportFormat.JSON: "json",
        ReportFormat.XML: "xml",
    }.get(report_format, "pdf")
    return "{}.{}".format(report_number, extension)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/reports", tags=["Reports"])


# ----------------------------------------------------------------------------
# FINANCIAL REPORTS
# ----------------------------------------------------------------------------


@router.post(
    "/financial/balance-sheet",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate balance sheet",
    operation_id="generate_balance_sheet",
)
async def generate_balance_sheet(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate balance sheet (neraca) report."""
    try:
        result = await service.generate_balance_sheet(
            legal_entity_id=legal_entity_id,
            as_of_date=request.as_of_date or date.today(),
            include_details=request.include_details,
            compare_with_previous=request.compare_with_previous,
            currency=request.currency,
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.BALANCE_SHEET,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate balance sheet: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/financial/income-statement",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate income statement",
    operation_id="generate_income_statement",
)
async def generate_income_statement(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate income statement (laporan laba rugi)."""
    try:
        result = await service.generate_income_statement(
            legal_entity_id=legal_entity_id,
            start_date=request.start_date,
            end_date=request.end_date,
            include_details=request.include_details,
            compare_with_previous=request.compare_with_previous,
            currency=request.currency,
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.INCOME_STATEMENT,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate income statement: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/financial/cash-flow",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate cash flow statement",
    operation_id="generate_cash_flow",
)
async def generate_cash_flow(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate cash flow statement (laporan arus kas)."""
    try:
        result = await service.generate_cash_flow(
            legal_entity_id=legal_entity_id,
            start_date=request.start_date,
            end_date=request.end_date,
            method=request.parameters.get("method", "indirect"),
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.CASH_FLOW,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate cash flow: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/financial/equity-statement",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate equity statement",
    operation_id="generate_equity_statement",
)
async def generate_equity_statement(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate statement of changes in equity."""
    try:
        result = await service.generate_equity_statement(
            legal_entity_id=legal_entity_id,
            start_date=request.start_date,
            end_date=request.end_date,
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.EQUITY_STATEMENT,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate equity statement: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LEDGER REPORTS
# ----------------------------------------------------------------------------


@router.post(
    "/ledger/trial-balance",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate trial balance",
    operation_id="generate_trial_balance",
)
async def generate_trial_balance(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate trial balance (neraca saldo)."""
    try:
        result = await service.generate_trial_balance(
            legal_entity_id=legal_entity_id,
            as_of_date=request.as_of_date or date.today(),
            include_zero_balance=request.parameters.get("include_zero_balance", False),
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.TRIAL_BALANCE,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate trial balance: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/ledger/general-ledger",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate general ledger",
    operation_id="generate_general_ledger",
)
async def generate_general_ledger(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate general ledger (buku besar)."""
    try:
        result = await service.generate_general_ledger(
            legal_entity_id=legal_entity_id,
            start_date=request.start_date,
            end_date=request.end_date,
            account_id=request.account_id,
            account_code=request.account_code,
            include_details=request.include_details,
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.GENERAL_LEDGER,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate general ledger: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SUBLEDGER REPORTS
# ----------------------------------------------------------------------------


@router.post(
    "/subledger/ar-aging",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate AR aging report",
    operation_id="generate_ar_aging",
)
async def generate_ar_aging(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate Accounts Receivable aging report."""
    try:
        result = await service.generate_ar_aging(
            legal_entity_id=legal_entity_id,
            as_of_date=request.as_of_date or date.today(),
            customer_id=request.customer_id,
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.AR_AGING,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate AR aging: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/subledger/ap-aging",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate AP aging report",
    operation_id="generate_ap_aging",
)
async def generate_ap_aging(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate Accounts Payable aging report."""
    try:
        result = await service.generate_ap_aging(
            legal_entity_id=legal_entity_id,
            as_of_date=request.as_of_date or date.today(),
            vendor_id=request.vendor_id,
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.AP_AGING,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate AP aging: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# INVENTORY REPORTS
# ----------------------------------------------------------------------------


@router.post(
    "/inventory/stock-card",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate stock card",
    operation_id="generate_stock_card",
)
async def generate_stock_card(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate stock card (kartu stok)."""
    try:
        result = await service.generate_stock_card(
            legal_entity_id=legal_entity_id,
            start_date=request.start_date,
            end_date=request.end_date,
            item_id=request.item_id,
            warehouse_id=request.warehouse_id,
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.STOCK_CARD,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate stock card: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# TAX REPORTS
# ----------------------------------------------------------------------------


@router.post(
    "/tax/summary",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate tax summary report",
    operation_id="generate_tax_summary",
)
async def generate_tax_summary(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate tax summary report."""
    try:
        result = await service.generate_tax_summary(
            legal_entity_id=legal_entity_id,
            start_date=request.start_date,
            end_date=request.end_date,
            tax_type=request.parameters.get("tax_type"),
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.TAX_SUMMARY,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate tax summary: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# FINANCIAL RATIOS & ANALYTICS
# ----------------------------------------------------------------------------


@router.post(
    "/analytics/financial-ratios",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate financial ratios report",
    operation_id="generate_financial_ratios",
)
async def generate_financial_ratios(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate financial ratios report."""
    try:
        result = await service.generate_financial_ratios(
            legal_entity_id=legal_entity_id,
            as_of_date=request.as_of_date or date.today(),
            compare_industry=request.parameters.get("compare_industry", False),
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.FINANCIAL_RATIOS,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate financial ratios: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BUDGET REPORTS
# ----------------------------------------------------------------------------


@router.post(
    "/budget/vs-actual",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate budget vs actual report",
    operation_id="generate_budget_vs_actual",
)
async def generate_budget_vs_actual(
    request: ReportRequestSchema,
    _permission: None = Depends(require_permission("report:generate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Generate budget vs actual report."""
    try:
        result = await service.generate_budget_vs_actual(
            legal_entity_id=legal_entity_id,
            fiscal_year=request.parameters.get("fiscal_year"),
            period=request.parameters.get("period"),
            budget_id=request.parameters.get("budget_id"),
            report_format=request.report_format.value,
            generated_by=current_user.user_id,
        )

        return ReportResponseSchema(
            report_id=result.id,
            report_number=result.report_number,
            report_type=ReportType.BUDGET_VS_ACTUAL,
            report_format=request.report_format,
            status=ReportStatus(result.status),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            download_url="/api/v1/reports/{}/download".format(result.id),
            parameters=request.dict(),
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            expires_at=result.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate budget vs actual: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# REPORT MANAGEMENT
# ----------------------------------------------------------------------------


@router.get(
    "/",
    response_model=ReportListResponseSchema,
    summary="List reports",
    operation_id="list_reports",
)
async def list_reports(
    report_type: ReportType | None = Query(None, description="Filter by report type"),
    status: ReportStatus | None = Query(None, description="Filter by status"),
    start_date: datetime | None = Query(None, description="Start date"),
    end_date: datetime | None = Query(None, description="End date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    _permission: None = Depends(require_permission("report:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportListResponseSchema:
    """List generated reports with pagination."""
    try:
        result = await service.list_reports(
            legal_entity_id=legal_entity_id,
            report_type=report_type.value if report_type else None,
            status=status.value if status else None,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        items = [
            ReportResponseSchema(
                report_id=r.id,
                report_number=r.report_number,
                report_type=ReportType(r.report_type),
                report_format=ReportFormat(r.report_format),
                status=ReportStatus(r.status),
                file_size_bytes=r.file_size_bytes,
                file_path=r.file_path,
                download_url="/api/v1/reports/{}/download".format(r.id),
                parameters=r.parameters,
                generated_at=r.generated_at,
                generated_by=r.generated_by,
                generated_by_name=r.generated_by_name,
                expires_at=r.expires_at,
                is_deleted=r.is_deleted,
            )
            for r in result.items
        ]

        return ReportListResponseSchema(
            items=items,
            total=result.total,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.exception("Failed to list reports: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{report_id}",
    response_model=ReportResponseSchema,
    summary="Get report by ID",
    operation_id="get_report",
)
async def get_report(
    report_id: UUID,
    _permission: None = Depends(require_permission("report:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> ReportResponseSchema:
    """Get report metadata by ID."""
    try:
        report = await service.get_report_by_id(report_id, legal_entity_id)

        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        return ReportResponseSchema(
            report_id=report.id,
            report_number=report.report_number,
            report_type=ReportType(report.report_type),
            report_format=ReportFormat(report.report_format),
            status=ReportStatus(report.status),
            file_size_bytes=report.file_size_bytes,
            file_path=report.file_path,
            download_url="/api/v1/reports/{}/download".format(report.id),
            parameters=report.parameters,
            generated_at=report.generated_at,
            generated_by=report.generated_by,
            generated_by_name=report.generated_by_name,
            expires_at=report.expires_at,
            is_deleted=report.is_deleted,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get report: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{report_id}/download",
    summary="Download report file",
    operation_id="download_report",
)
async def download_report(
    report_id: UUID,
    _permission: None = Depends(require_permission("report:download")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
):
    """Download generated report file."""
    try:
        report = await service.get_report_by_id(report_id, legal_entity_id)

        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        if report.status != ReportStatus.GENERATED.value:
            raise HTTPException(
                status_code=400,
                detail="Report not ready (status: {})".format(report.status),  # nosec
            )

        if report.is_deleted:
            raise HTTPException(status_code=410, detail="Report has been deleted")

        # Check if file exists
        import os

        if not os.path.exists(report.file_path):
            raise HTTPException(status_code=404, detail="Report file not found")

        media_type = _get_media_type(ReportFormat(report.report_format))
        filename = _get_filename(report.report_number, ReportFormat(report.report_format))

        return FileResponse(
            path=report.file_path,
            media_type=media_type,
            filename=filename,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to download report: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{report_id}",
    response_model=dict[str, Any],
    summary="Delete report",
    operation_id="delete_report",
)
async def delete_report(
    report_id: UUID,
    _permission: None = Depends(require_permission("report:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> dict[str, Any]:
    """Delete a report (soft delete)."""
    try:
        result = await service.delete_report(report_id, legal_entity_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="Report not found")

        return {
            "report_id": str(report_id),
            "report_number": result.report_number,
            "deleted": True,
            "message": "Report deleted",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to delete report: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# REPORT DISTRIBUTION
# ----------------------------------------------------------------------------


@router.post(
    "/{report_id}/send",
    response_model=list[ReportDistributionResponseSchema],
    status_code=status.HTTP_201_CREATED,
    summary="Send report via email/WhatsApp",
    operation_id="send_report",
)
async def send_report(
    report_id: UUID,
    request: ReportDistributionSchema,
    _permission: None = Depends(require_permission("report:send")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    distributor: Any = Depends(get_report_distributor),
) -> list[ReportDistributionResponseSchema]:
    """Send generated report to recipients."""
    try:
        results = await distributor.distribute(
            report_id=report_id,
            legal_entity_id=legal_entity_id,
            recipient_emails=request.recipient_emails,
            recipient_whatsapps=request.recipient_whatsapps,
            subject=request.subject,
            message=request.message,
            delivery_methods=[m.value for m in request.delivery_methods]
            if request.delivery_methods
            else None,
            sent_by=current_user.user_id,
        )

        return [
            ReportDistributionResponseSchema(
                distribution_id=r.id,
                report_id=r.report_id,
                recipient_email=r.recipient_email,
                recipient_whatsapp=r.recipient_whatsapp,
                delivery_method=DeliveryMethod(r.delivery_method),
                status=r.status,
                sent_at=r.sent_at,
                error_message=r.error_message,
            )
            for r in results
        ]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to send report: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# REPORT SCHEDULING
# ----------------------------------------------------------------------------


@router.post(
    "/schedule",
    response_model=ReportScheduleResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a report",
    operation_id="schedule_report",
)
async def schedule_report(
    request: ReportScheduleCreateSchema,
    _permission: None = Depends(require_permission("report:schedule")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    scheduler: Any = Depends(get_report_scheduler),
) -> ReportScheduleResponseSchema:
    """Schedule a report to be generated automatically."""
    try:
        result = await scheduler.create_schedule(
            legal_entity_id=legal_entity_id,
            report_type=request.report_type.value,
            schedule_name=request.schedule_name,
            schedule_frequency=request.schedule_frequency.value,
            schedule_time=request.schedule_time,
            schedule_day_of_week=request.schedule_day_of_week,
            schedule_day_of_month=request.schedule_day_of_month,
            report_format=request.report_format.value,
            parameters=request.parameters,
            recipient_emails=request.recipient_emails,
            recipient_whatsapps=request.recipient_whatsapps,
            delivery_methods=[m.value for m in request.delivery_methods],
            is_active=request.is_active,
            notes=request.notes,
            created_by=current_user.user_id,
        )

        return ReportScheduleResponseSchema(
            schedule_id=result.id,
            schedule_name=result.schedule_name,
            report_type=ReportType(result.report_type),
            schedule_frequency=ScheduleFrequency(result.schedule_frequency),
            schedule_time=result.schedule_time,
            schedule_day_of_week=result.schedule_day_of_week,
            schedule_day_of_month=result.schedule_day_of_month,
            report_format=ReportFormat(result.report_format),
            parameters=result.parameters,
            recipient_emails=result.recipient_emails,
            recipient_whatsapps=result.recipient_whatsapps,
            delivery_methods=[DeliveryMethod(m) for m in result.delivery_methods],
            is_active=result.is_active,
            last_run_at=result.last_run_at,
            next_run_at=result.next_run_at,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to schedule report: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/schedule",
    response_model=list[ReportScheduleResponseSchema],
    summary="List scheduled reports",
    operation_id="list_scheduled_reports",
)
async def list_scheduled_reports(
    is_active: bool | None = Query(None, description="Filter by active status"),
    report_type: ReportType | None = Query(None, description="Filter by report type"),
    _permission: None = Depends(require_permission("report:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    scheduler: Any = Depends(get_report_scheduler),
) -> list[ReportScheduleResponseSchema]:
    """List all scheduled reports."""
    try:
        schedules = await scheduler.list_schedules(
            legal_entity_id=legal_entity_id,
            is_active=is_active,
            report_type=report_type.value if report_type else None,
        )

        return [
            ReportScheduleResponseSchema(
                schedule_id=s.id,
                schedule_name=s.schedule_name,
                report_type=ReportType(s.report_type),
                schedule_frequency=ScheduleFrequency(s.schedule_frequency),
                schedule_time=s.schedule_time,
                schedule_day_of_week=s.schedule_day_of_week,
                schedule_day_of_month=s.schedule_day_of_month,
                report_format=ReportFormat(s.report_format),
                parameters=s.parameters,
                recipient_emails=s.recipient_emails,
                recipient_whatsapps=s.recipient_whatsapps,
                delivery_methods=[DeliveryMethod(m) for m in s.delivery_methods],
                is_active=s.is_active,
                last_run_at=s.last_run_at,
                next_run_at=s.next_run_at,
                created_at=s.created_at,
                updated_at=s.updated_at,
                created_by=s.created_by,
                created_by_name=s.created_by_name,
                version=s.version,
            )
            for s in schedules
        ]
    except Exception as e:
        logger.exception("Failed to list scheduled reports: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/schedule/{schedule_id}",
    response_model=ReportScheduleResponseSchema,
    summary="Get scheduled report by ID",
    operation_id="get_scheduled_report",
)
async def get_scheduled_report(
    schedule_id: UUID,
    _permission: None = Depends(require_permission("report:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    scheduler: Any = Depends(get_report_scheduler),
) -> ReportScheduleResponseSchema:
    """Get scheduled report by ID."""
    try:
        schedule = await scheduler.get_schedule_by_id(schedule_id, legal_entity_id)

        if not schedule:
            raise HTTPException(status_code=404, detail="Scheduled report not found")

        return ReportScheduleResponseSchema(
            schedule_id=schedule.id,
            schedule_name=schedule.schedule_name,
            report_type=ReportType(schedule.report_type),
            schedule_frequency=ScheduleFrequency(schedule.schedule_frequency),
            schedule_time=schedule.schedule_time,
            schedule_day_of_week=schedule.schedule_day_of_week,
            schedule_day_of_month=schedule.schedule_day_of_month,
            report_format=ReportFormat(schedule.report_format),
            parameters=schedule.parameters,
            recipient_emails=schedule.recipient_emails,
            recipient_whatsapps=schedule.recipient_whatsapps,
            delivery_methods=[DeliveryMethod(m) for m in schedule.delivery_methods],
            is_active=schedule.is_active,
            last_run_at=schedule.last_run_at,
            next_run_at=schedule.next_run_at,
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
            created_by=schedule.created_by,
            created_by_name=schedule.created_by_name,
            version=schedule.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get scheduled report: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/schedule/{schedule_id}",
    response_model=ReportScheduleResponseSchema,
    summary="Update scheduled report",
    operation_id="update_scheduled_report",
)
async def update_scheduled_report(
    schedule_id: UUID,
    request: ReportScheduleCreateSchema,
    _permission: None = Depends(require_permission("report:schedule")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    scheduler: Any = Depends(get_report_scheduler),
) -> ReportScheduleResponseSchema:
    """Update a scheduled report."""
    try:
        result = await scheduler.update_schedule(
            schedule_id=schedule_id,
            legal_entity_id=legal_entity_id,
            schedule_name=request.schedule_name,
            schedule_frequency=request.schedule_frequency.value,
            schedule_time=request.schedule_time,
            schedule_day_of_week=request.schedule_day_of_week,
            schedule_day_of_month=request.schedule_day_of_month,
            report_format=request.report_format.value,
            parameters=request.parameters,
            recipient_emails=request.recipient_emails,
            recipient_whatsapps=request.recipient_whatsapps,
            delivery_methods=[m.value for m in request.delivery_methods],
            is_active=request.is_active,
            notes=request.notes,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Scheduled report not found")

        return ReportScheduleResponseSchema(
            schedule_id=result.id,
            schedule_name=result.schedule_name,
            report_type=ReportType(result.report_type),
            schedule_frequency=ScheduleFrequency(result.schedule_frequency),
            schedule_time=result.schedule_time,
            schedule_day_of_week=result.schedule_day_of_week,
            schedule_day_of_month=result.schedule_day_of_month,
            report_format=ReportFormat(result.report_format),
            parameters=result.parameters,
            recipient_emails=result.recipient_emails,
            recipient_whatsapps=result.recipient_whatsapps,
            delivery_methods=[DeliveryMethod(m) for m in result.delivery_methods],
            is_active=result.is_active,
            last_run_at=result.last_run_at,
            next_run_at=result.next_run_at,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update scheduled report: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/schedule/{schedule_id}",
    response_model=dict[str, Any],
    summary="Delete scheduled report",
    operation_id="delete_scheduled_report",
)
async def delete_scheduled_report(
    schedule_id: UUID,
    _permission: None = Depends(require_permission("report:schedule")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    scheduler: Any = Depends(get_report_scheduler),
) -> dict[str, Any]:
    """Delete a scheduled report."""
    try:
        result = await scheduler.delete_schedule(schedule_id, legal_entity_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="Scheduled report not found")

        return {
            "schedule_id": str(schedule_id),
            "schedule_name": result.schedule_name,
            "deleted": True,
            "message": "Scheduled report deleted",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to delete scheduled report: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# REPORT HISTORY & STATUS
# ----------------------------------------------------------------------------


@router.get(
    "/{report_id}/status",
    response_model=dict[str, Any],
    summary="Get report generation status",
    operation_id="get_report_status",
)
async def get_report_status(
    report_id: UUID,
    _permission: None = Depends(require_permission("report:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> dict[str, Any]:
    """Get report generation status."""
    try:
        status_info = await service.get_report_status(report_id, legal_entity_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="Report not found")

        return {
            "report_id": str(report_id),
            "report_number": status_info.report_number,
            "status": status_info.status,
            "progress_percent": status_info.progress_percent,
            "current_step": status_info.current_step,
            "total_steps": status_info.total_steps,
            "estimated_remaining_seconds": status_info.estimated_remaining_seconds,
            "error_message": status_info.error_message,
            "generated_at": status_info.generated_at.isoformat()
            if status_info.generated_at
            else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get report status: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{report_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get report history",
    operation_id="get_report_history",
)
async def get_report_history(
    report_id: UUID,
    _permission: None = Depends(require_permission("report:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_report_service),
) -> list[dict[str, Any]]:
    """Get report generation history (audit trail)."""
    try:
        history = await service.get_report_history(report_id, legal_entity_id)

        return [
            {
                "timestamp": h.timestamp.isoformat(),
                "action": h.action,
                "status": h.status,
                "actor_id": str(h.actor_id),
                "actor_name": h.actor_name,
                "reason": h.reason,
                "details": h.details,
            }
            for h in history
        ]
    except Exception as e:
        logger.exception("Failed to get report history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]