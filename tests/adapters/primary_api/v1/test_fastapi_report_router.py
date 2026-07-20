# tests/adapters/primary_api/v1/test_fastapi_report_router.py
"""
Comprehensive tests for fastapi_report_router.py
Covers positive/negative paths, idempotency, scheduling, distribution, and file download.
"""

import os
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_report_router import (
    DeliveryMethod,
    IdempotencyManager,
    ReportDistributionResponseSchema,
    ReportDistributionSchema,
    ReportFormat,
    ReportListResponseSchema,
    ReportRequestSchema,
    ReportResponseSchema,
    ReportScheduleCreateSchema,
    ReportScheduleResponseSchema,
    ReportStatus,
    ReportType,
    ScheduleFrequency,
    _get_filename,
    _get_media_type,
    delete_report,
    delete_scheduled_report,
    download_report,
    generate_ap_aging,
    generate_ar_aging,
    generate_balance_sheet,
    generate_budget_vs_actual,
    generate_cash_flow,
    generate_equity_statement,
    generate_financial_ratios,
    generate_general_ledger,
    generate_income_statement,
    generate_stock_card,
    generate_tax_summary,
    generate_trial_balance,
    get_report,
    get_report_distributor,
    get_report_history,
    get_report_scheduler,
    get_report_service,
    get_report_status,
    get_scheduled_report,
    list_reports,
    list_scheduled_reports,
    schedule_report,
    send_report,
    update_scheduled_report,
)

# ---------- Fixtures ----------

@pytest.fixture
def mock_service():
    """Mock ReportService with async methods."""
    service = AsyncMock()
    # Default return value for generate methods: object with expected attrs
    default_report = MagicMock(
        id=uuid4(),
        report_number="RPT-001",
        status="generated",
        file_size_bytes=1024,
        file_path="/tmp/report.pdf",
        generated_at=datetime.now(),
        generated_by=uuid4(),
        generated_by_name="admin",
        expires_at=datetime.now() + timedelta(days=1),
        is_deleted=False,
        parameters={},
        version=1,
    )
    # Set all generate_* methods to return default_report
    for method in [
        "generate_balance_sheet",
        "generate_income_statement",
        "generate_cash_flow",
        "generate_equity_statement",
        "generate_trial_balance",
        "generate_general_ledger",
        "generate_ar_aging",
        "generate_ap_aging",
        "generate_stock_card",
        "generate_tax_summary",
        "generate_financial_ratios",
        "generate_budget_vs_actual",
    ]:
        setattr(service, method, AsyncMock(return_value=default_report))

    service.list_reports = AsyncMock(
        return_value=MagicMock(items=[default_report], total=1)
    )
    service.get_report_by_id = AsyncMock(return_value=default_report)
    service.delete_report = AsyncMock(return_value=default_report)
    service.get_report_status = AsyncMock(
        return_value=MagicMock(
            report_number="RPT-001",
            status="generated",
            progress_percent=100,
            current_step="done",
            total_steps=1,
            estimated_remaining_seconds=0,
            error_message=None,
            generated_at=datetime.now(),
        )
    )
    service.get_report_history = AsyncMock(return_value=[])
    return service


@pytest.fixture
def mock_scheduler():
    """Mock ReportScheduler."""
    scheduler = AsyncMock()
    default_schedule = MagicMock(
        id=uuid4(),
        schedule_name="Monthly Report",
        report_type="balance_sheet",
        schedule_frequency="monthly",
        schedule_time="09:00",
        schedule_day_of_week=None,
        schedule_day_of_month=1,
        report_format="pdf",
        parameters={"year": 2026},
        recipient_emails=[],
        recipient_whatsapps=[],
        delivery_methods=["email"],
        is_active=True,
        last_run_at=None,
        next_run_at=datetime.now() + timedelta(days=30),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        created_by=uuid4(),
        created_by_name="admin",
        version=1,
    )
    scheduler.create_schedule = AsyncMock(return_value=default_schedule)
    scheduler.list_schedules = AsyncMock(return_value=[default_schedule])
    scheduler.get_schedule_by_id = AsyncMock(return_value=default_schedule)
    scheduler.update_schedule = AsyncMock(return_value=default_schedule)
    scheduler.delete_schedule = AsyncMock(return_value=default_schedule)
    return scheduler


@pytest.fixture
def mock_distributor():
    """Mock ReportDistributor."""
    distributor = AsyncMock()
    distribution = MagicMock(
        id=uuid4(),
        report_id=uuid4(),
        recipient_email="test@example.com",
        recipient_whatsapp=None,
        delivery_method="email",
        status="sent",
        sent_at=datetime.now(),
        error_message=None,
    )
    distributor.distribute = AsyncMock(return_value=[distribution])
    return distributor


@pytest.fixture
def current_user():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def idempotency_key():
    return "test-idempotency-key"


# ---------- Helper Tests ----------

def test_get_media_type():
    assert _get_media_type(ReportFormat.PDF) == "application/pdf"
    assert _get_media_type(ReportFormat.EXCEL) == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert _get_media_type(ReportFormat.CSV) == "text/csv"
    assert _get_media_type(ReportFormat.HTML) == "text/html"
    assert _get_media_type(ReportFormat.JSON) == "application/json"
    assert _get_media_type(ReportFormat.XML) == "application/xml"


def test_get_filename():
    assert _get_filename("RPT-001", ReportFormat.PDF) == "RPT-001.pdf"
    assert _get_filename("RPT-001", ReportFormat.EXCEL) == "RPT-001.xlsx"
    assert _get_filename("RPT-001", ReportFormat.CSV) == "RPT-001.csv"


# ---------- IdempotencyManager Tests ----------

def test_idempotency_manager_construction():
    mgr = IdempotencyManager()
    assert mgr._storage == {}
    assert mgr._ttl_seconds == 86400


def test_idempotency_manager_cache_and_get():
    mgr = IdempotencyManager()
    key = "key1"
    method = "test_method"
    result = {"data": "value"}

    # Cache
    mgr.cache_result(key, method, result)
    storage_key = mgr._get_key(key, method)
    assert storage_key in mgr._storage

    # Get
    cached = mgr.get_cached_result(key, method)
    assert cached == result


def test_idempotency_manager_get_missing():
    mgr = IdempotencyManager()
    assert mgr.get_cached_result("missing", "method") is None


def test_idempotency_manager_expiry():
    mgr = IdempotencyManager()
    mgr._ttl_seconds = 0  # force expiry
    mgr.cache_result("key", "method", {"x": 1})
    # Immediately expired
    assert mgr.get_cached_result("key", "method") is None


# ---------- Schema Validation Tests (Negative Path) ----------

def test_report_request_schema_start_date_after_end_date():
    with pytest.raises(ValueError, match="Start date must be before end date"):
        ReportRequestSchema(
            report_type=ReportType.BALANCE_SHEET,
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 1),
        )


def test_report_schedule_create_schema_weekly_missing_day():
    with pytest.raises(ValueError, match="day_of_week required for weekly schedule"):
        ReportScheduleCreateSchema(
            report_type=ReportType.BALANCE_SHEET,
            schedule_name="Weekly",
            schedule_frequency=ScheduleFrequency.WEEKLY,
            parameters={},
        )


def test_report_schedule_create_schema_monthly_missing_day():
    with pytest.raises(ValueError, match="day_of_month required for monthly schedule"):
        ReportScheduleCreateSchema(
            report_type=ReportType.BALANCE_SHEET,
            schedule_name="Monthly",
            schedule_frequency=ScheduleFrequency.MONTHLY,
            parameters={},
        )


def test_report_schedule_create_schema_custom_missing_time():
    with pytest.raises(ValueError, match="schedule_time required for custom schedule"):
        ReportScheduleCreateSchema(
            report_type=ReportType.BALANCE_SHEET,
            schedule_name="Custom",
            schedule_frequency=ScheduleFrequency.CUSTOM,
            parameters={},
        )


# ---------- Dependency Injection Tests ----------

@pytest.mark.asyncio
async def test_get_report_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve = MagicMock(return_value=AsyncMock())
    service = await get_report_service(request)
    assert service is not None


@pytest.mark.asyncio
async def test_get_report_scheduler():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve = MagicMock(return_value=AsyncMock())
    scheduler = await get_report_scheduler(request)
    assert scheduler is not None


@pytest.mark.asyncio
async def test_get_report_distributor():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve = MagicMock(return_value=AsyncMock())
    distributor = await get_report_distributor(request)
    assert distributor is not None


# ---------- Generate Report Endpoints (Positive & Negative) ----------

# List of all generate endpoints with their service method name
GENERATE_ENDPOINTS = [
    (generate_balance_sheet, "generate_balance_sheet", ReportType.BALANCE_SHEET),
    (generate_income_statement, "generate_income_statement", ReportType.INCOME_STATEMENT),
    (generate_cash_flow, "generate_cash_flow", ReportType.CASH_FLOW),
    (generate_equity_statement, "generate_equity_statement", ReportType.EQUITY_STATEMENT),
    (generate_trial_balance, "generate_trial_balance", ReportType.TRIAL_BALANCE),
    (generate_general_ledger, "generate_general_ledger", ReportType.GENERAL_LEDGER),
    (generate_ar_aging, "generate_ar_aging", ReportType.AR_AGING),
    (generate_ap_aging, "generate_ap_aging", ReportType.AP_AGING),
    (generate_stock_card, "generate_stock_card", ReportType.STOCK_CARD),
    (generate_tax_summary, "generate_tax_summary", ReportType.TAX_SUMMARY),
    (generate_financial_ratios, "generate_financial_ratios", ReportType.FINANCIAL_RATIOS),
    (generate_budget_vs_actual, "generate_budget_vs_actual", ReportType.BUDGET_VS_ACTUAL),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,method_name,report_type", GENERATE_ENDPOINTS)
async def test_generate_endpoint_success(
    endpoint, method_name, report_type,
    mock_service, current_user, legal_entity_id
):
    """Test each generate endpoint returns ReportResponseSchema on success."""
    request = MagicMock()
    request.report_format = ReportFormat.PDF
    request.as_of_date = date.today()
    request.start_date = date(2026, 1, 1)
    request.end_date = date(2026, 12, 31)
    request.include_details = True
    request.compare_with_previous = False
    request.currency = "IDR"
    request.parameters = {}

    # Mock the service method to return an object with required attrs
    mock_report = MagicMock(
        id=uuid4(),
        report_number="RPT-001",
        status="generated",
        file_size_bytes=1024,
        file_path="/tmp/report.pdf",
        generated_at=datetime.now(),
        generated_by=uuid4(),
        generated_by_name="admin",
        expires_at=datetime.now() + timedelta(days=1),
    )
    getattr(mock_service, method_name).return_value = mock_report

    result = await endpoint(
        request=request,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )

    assert isinstance(result, ReportResponseSchema)
    assert result.report_type == report_type
    assert result.report_number == "RPT-001"
    assert result.download_url == f"/api/v1/reports/{mock_report.id}/download"
    # Ensure service method called with correct args
    getattr(mock_service, method_name).assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,method_name,report_type", GENERATE_ENDPOINTS)
async def test_generate_endpoint_value_error(
    endpoint, method_name, report_type,
    mock_service, current_user, legal_entity_id
):
    """Test that ValueError raises HTTP 422."""
    getattr(mock_service, method_name).side_effect = ValueError("Invalid input")

    with pytest.raises(HTTPException) as exc:
        await endpoint(
            request=MagicMock(),
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 422
    assert "Invalid input" in exc.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,method_name,report_type", GENERATE_ENDPOINTS)
async def test_generate_endpoint_general_exception(
    endpoint, method_name, report_type,
    mock_service, current_user, legal_entity_id
):
    """Test that unexpected exception raises HTTP 500."""
    getattr(mock_service, method_name).side_effect = RuntimeError("Unexpected")

    with pytest.raises(HTTPException) as exc:
        await endpoint(
            request=MagicMock(),
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 500


# ---------- List Reports ----------

@pytest.mark.asyncio
async def test_list_reports_success(mock_service, legal_entity_id):
    result = await list_reports(
        report_type=ReportType.BALANCE_SHEET,
        status=ReportStatus.GENERATED,
        start_date=datetime.now(),
        end_date=datetime.now(),
        page=1,
        page_size=10,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, ReportListResponseSchema)
    assert result.total == 1
    mock_service.list_reports.assert_called_once()


@pytest.mark.asyncio
async def test_list_reports_general_exception(mock_service, legal_entity_id):
    mock_service.list_reports.side_effect = RuntimeError("DB error")
    with pytest.raises(HTTPException) as exc:
        await list_reports(
            report_type=None,
            status=None,
            start_date=None,
            end_date=None,
            page=1,
            page_size=10,
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 500


# ---------- Get Report ----------

@pytest.mark.asyncio
async def test_get_report_success(mock_service, legal_entity_id):
    report_id = uuid4()
    result = await get_report(
        report_id=report_id,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, ReportResponseSchema)
    mock_service.get_report_by_id.assert_called_once_with(report_id, legal_entity_id)


@pytest.mark.asyncio
async def test_get_report_not_found(mock_service, legal_entity_id):
    mock_service.get_report_by_id.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_report(
            report_id=uuid4(),
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_report_general_exception(mock_service, legal_entity_id):
    mock_service.get_report_by_id.side_effect = RuntimeError("Error")
    with pytest.raises(HTTPException) as exc:
        await get_report(
            report_id=uuid4(),
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 500


# ---------- Download Report ----------

@pytest.mark.asyncio
async def test_download_report_success(mock_service, legal_entity_id):
    report_id = uuid4()
    mock_report = MagicMock(
        status="generated",
        is_deleted=False,
        file_path="/tmp/report.pdf",
        report_number="RPT-001",
        report_format="pdf",
    )
    mock_service.get_report_by_id.return_value = mock_report

    with patch("os.path.exists", return_value=True):
        with patch("adapters.primary_api.v1.fastapi_report_router.FileResponse") as MockFileResponse:
            result = await download_report(
                report_id=report_id,
                _permission=MagicMock(),
                legal_entity_id=legal_entity_id,
                service=mock_service,
            )
            MockFileResponse.assert_called_once_with(
                path="/tmp/report.pdf",
                media_type="application/pdf",
                filename="RPT-001.pdf",
            )
            assert result == MockFileResponse.return_value


@pytest.mark.asyncio
async def test_download_report_not_found(mock_service, legal_entity_id):
    mock_service.get_report_by_id.return_value = None
    with pytest.raises(HTTPException) as exc:
        await download_report(
            report_id=uuid4(),
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_download_report_not_generated(mock_service, legal_entity_id):
    mock_report = MagicMock(status="pending", is_deleted=False)
    mock_service.get_report_by_id.return_value = mock_report
    with pytest.raises(HTTPException) as exc:
        await download_report(
            report_id=uuid4(),
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_download_report_deleted(mock_service, legal_entity_id):
    mock_report = MagicMock(status="generated", is_deleted=True)
    mock_service.get_report_by_id.return_value = mock_report
    with pytest.raises(HTTPException) as exc:
        await download_report(
            report_id=uuid4(),
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_download_report_file_missing(mock_service, legal_entity_id):
    mock_report = MagicMock(status="generated", is_deleted=False, file_path="/missing.pdf")
    mock_service.get_report_by_id.return_value = mock_report
    with patch("os.path.exists", return_value=False):
        with pytest.raises(HTTPException) as exc:
            await download_report(
                report_id=uuid4(),
                _permission=MagicMock(),
                legal_entity_id=legal_entity_id,
                service=mock_service,
            )
        assert exc.value.status_code == 404


# ---------- Delete Report ----------

@pytest.mark.asyncio
async def test_delete_report_success(mock_service, current_user, legal_entity_id, idempotency_key):
    report_id = uuid4()
    result = await delete_report(
        report_id=report_id,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert result["deleted"] is True
    mock_service.delete_report.assert_called_once_with(report_id, legal_entity_id, current_user.user_id)


@pytest.mark.asyncio
async def test_delete_report_idempotency_hit(mock_service, current_user, legal_entity_id, idempotency_key):
    # Pre-cache result
    mgr = IdempotencyManager()
    with patch("adapters.primary_api.v1.fastapi_report_router._idempotency_manager", mgr):
        mgr.cache_result(idempotency_key, "delete_report", {"deleted": True, "id": "cached"})
        result = await delete_report(
            report_id=uuid4(),
            idempotency_key=idempotency_key,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
        # Service should not be called
        mock_service.delete_report.assert_not_called()
        assert result == {"deleted": True, "id": "cached"}


@pytest.mark.asyncio
async def test_delete_report_not_found(mock_service, current_user, legal_entity_id):
    mock_service.delete_report.return_value = None
    with pytest.raises(HTTPException) as exc:
        await delete_report(
            report_id=uuid4(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_report_value_error(mock_service, current_user, legal_entity_id):
    mock_service.delete_report.side_effect = ValueError("Cannot delete")
    with pytest.raises(HTTPException) as exc:
        await delete_report(
            report_id=uuid4(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 422


# ---------- Send Report (Distribution) ----------

@pytest.mark.asyncio
async def test_send_report_success(mock_distributor, current_user, legal_entity_id):
    report_id = uuid4()
    distribution_schema = ReportDistributionSchema(
        report_id=report_id,
        recipient_emails=["a@b.com"],
        delivery_methods=[DeliveryMethod.EMAIL],
    )
    result = await send_report(
        report_id=report_id,
        request=distribution_schema,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        distributor=mock_distributor,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], ReportDistributionResponseSchema)
    mock_distributor.distribute.assert_called_once()


@pytest.mark.asyncio
async def test_send_report_value_error(mock_distributor, current_user, legal_entity_id):
    mock_distributor.distribute.side_effect = ValueError("Invalid")
    with pytest.raises(HTTPException) as exc:
        await send_report(
            report_id=uuid4(),
            request=MagicMock(),
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            distributor=mock_distributor,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_send_report_general_exception(mock_distributor, current_user, legal_entity_id):
    mock_distributor.distribute.side_effect = RuntimeError("Fail")
    with pytest.raises(HTTPException) as exc:
        await send_report(
            report_id=uuid4(),
            request=MagicMock(),
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            distributor=mock_distributor,
        )
    assert exc.value.status_code == 500


# ---------- Schedule Report ----------

@pytest.mark.asyncio
async def test_schedule_report_success(mock_scheduler, current_user, legal_entity_id):
    schema = ReportScheduleCreateSchema(
        report_type=ReportType.BALANCE_SHEET,
        schedule_name="Monthly",
        schedule_frequency=ScheduleFrequency.MONTHLY,
        schedule_day_of_month=1,
        schedule_time="09:00",
        parameters={},
        delivery_methods=[DeliveryMethod.EMAIL],
    )
    result = await schedule_report(
        request=schema,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        scheduler=mock_scheduler,
    )
    assert isinstance(result, ReportScheduleResponseSchema)
    mock_scheduler.create_schedule.assert_called_once()


@pytest.mark.asyncio
async def test_schedule_report_value_error(mock_scheduler, current_user, legal_entity_id):
    mock_scheduler.create_schedule.side_effect = ValueError("Invalid")
    schema = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await schedule_report(
            request=schema,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            scheduler=mock_scheduler,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_schedule_report_general_exception(mock_scheduler, current_user, legal_entity_id):
    mock_scheduler.create_schedule.side_effect = RuntimeError("Fail")
    schema = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await schedule_report(
            request=schema,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            scheduler=mock_scheduler,
        )
    assert exc.value.status_code == 500


# ---------- List Scheduled Reports ----------

@pytest.mark.asyncio
async def test_list_scheduled_reports_success(mock_scheduler, legal_entity_id):
    result = await list_scheduled_reports(
        is_active=True,
        report_type=ReportType.BALANCE_SHEET,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        scheduler=mock_scheduler,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], ReportScheduleResponseSchema)
    mock_scheduler.list_schedules.assert_called_once()


@pytest.mark.asyncio
async def test_list_scheduled_reports_general_exception(mock_scheduler, legal_entity_id):
    mock_scheduler.list_schedules.side_effect = RuntimeError("Error")
    with pytest.raises(HTTPException) as exc:
        await list_scheduled_reports(
            is_active=True,
            report_type=None,
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            scheduler=mock_scheduler,
        )
    assert exc.value.status_code == 500


# ---------- Get Scheduled Report ----------

@pytest.mark.asyncio
async def test_get_scheduled_report_success(mock_scheduler, legal_entity_id):
    schedule_id = uuid4()
    result = await get_scheduled_report(
        schedule_id=schedule_id,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        scheduler=mock_scheduler,
    )
    assert isinstance(result, ReportScheduleResponseSchema)
    mock_scheduler.get_schedule_by_id.assert_called_once_with(schedule_id, legal_entity_id)


@pytest.mark.asyncio
async def test_get_scheduled_report_not_found(mock_scheduler, legal_entity_id):
    mock_scheduler.get_schedule_by_id.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_scheduled_report(
            schedule_id=uuid4(),
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            scheduler=mock_scheduler,
        )
    assert exc.value.status_code == 404


# ---------- Update Scheduled Report ----------

@pytest.mark.asyncio
async def test_update_scheduled_report_success(mock_scheduler, current_user, legal_entity_id, idempotency_key):
    schedule_id = uuid4()
    schema = MagicMock()
    result = await update_scheduled_report(
        schedule_id=schedule_id,
        request=schema,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        scheduler=mock_scheduler,
    )
    assert isinstance(result, ReportScheduleResponseSchema)
    mock_scheduler.update_schedule.assert_called_once()


@pytest.mark.asyncio
async def test_update_scheduled_report_not_found(mock_scheduler, current_user, legal_entity_id):
    mock_scheduler.update_schedule.return_value = None
    with pytest.raises(HTTPException) as exc:
        await update_scheduled_report(
            schedule_id=uuid4(),
            request=MagicMock(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            scheduler=mock_scheduler,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_scheduled_report_idempotency_hit(mock_scheduler, current_user, legal_entity_id, idempotency_key):
    mgr = IdempotencyManager()
    with patch("adapters.primary_api.v1.fastapi_report_router._idempotency_manager", mgr):
        cached_response = ReportScheduleResponseSchema(
            schedule_id=uuid4(),
            schedule_name="cached",
            report_type=ReportType.BALANCE_SHEET,
            schedule_frequency=ScheduleFrequency.MONTHLY,
            schedule_time="09:00",
            schedule_day_of_week=1,
            schedule_day_of_month=1,
            report_format=ReportFormat.PDF,
            parameters={},
            recipient_emails=[],
            recipient_whatsapps=[],
            delivery_methods=[DeliveryMethod.EMAIL],
            is_active=True,
            last_run_at=None,
            next_run_at=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=uuid4(),
            version=1,
        )
        mgr.cache_result(idempotency_key, "update_scheduled_report", cached_response.model_dump())
        result = await update_scheduled_report(
            schedule_id=uuid4(),
            request=MagicMock(),
            idempotency_key=idempotency_key,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            scheduler=mock_scheduler,
        )
        mock_scheduler.update_schedule.assert_not_called()
        assert result.schedule_name == "cached"


# ---------- Delete Scheduled Report ----------

@pytest.mark.asyncio
async def test_delete_scheduled_report_success(mock_scheduler, current_user, legal_entity_id, idempotency_key):
    schedule_id = uuid4()
    result = await delete_scheduled_report(
        schedule_id=schedule_id,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        scheduler=mock_scheduler,
    )
    assert result["deleted"] is True
    mock_scheduler.delete_schedule.assert_called_once_with(schedule_id, legal_entity_id, current_user.user_id)


@pytest.mark.asyncio
async def test_delete_scheduled_report_not_found(mock_scheduler, current_user, legal_entity_id):
    mock_scheduler.delete_schedule.return_value = None
    with pytest.raises(HTTPException) as exc:
        await delete_scheduled_report(
            schedule_id=uuid4(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            scheduler=mock_scheduler,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_scheduled_report_value_error(mock_scheduler, current_user, legal_entity_id):
    mock_scheduler.delete_schedule.side_effect = ValueError("Cannot")
    with pytest.raises(HTTPException) as exc:
        await delete_scheduled_report(
            schedule_id=uuid4(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            scheduler=mock_scheduler,
        )
    assert exc.value.status_code == 422


# ---------- Get Report Status ----------

@pytest.mark.asyncio
async def test_get_report_status_success(mock_service, legal_entity_id):
    report_id = uuid4()
    result = await get_report_status(
        report_id=report_id,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert result["status"] == "generated"
    mock_service.get_report_status.assert_called_once_with(report_id, legal_entity_id)


@pytest.mark.asyncio
async def test_get_report_status_not_found(mock_service, legal_entity_id):
    mock_service.get_report_status.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_report_status(
            report_id=uuid4(),
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404


# ---------- Get Report History ----------

@pytest.mark.asyncio
async def test_get_report_history_success(mock_service, legal_entity_id):
    report_id = uuid4()
    result = await get_report_history(
        report_id=report_id,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, list)
    mock_service.get_report_history.assert_called_once_with(report_id, legal_entity_id)


@pytest.mark.asyncio
async def test_get_report_history_general_exception(mock_service, legal_entity_id):
    mock_service.get_report_history.side_effect = RuntimeError("Error")
    with pytest.raises(HTTPException) as exc:
        await get_report_history(
            report_id=uuid4(),
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 500