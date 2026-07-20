# adapters/primary_api/v1/test_fastapi_goodwill_router.py
"""
Comprehensive unit tests for FastAPI Goodwill Router.

Covers:
- IdempotencyManager
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
- Impairment test validation (recoverable amount calculation)
- Goodwill creation validation (bargain purchase)
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_goodwill_router import (
    AmortizationScheduleLineSchema,
    GoodwillAmortizationResponseSchema,
    GoodwillCreateSchema,
    GoodwillDisposalResponseSchema,
    GoodwillDisposalSchema,
    GoodwillResponseSchema,
    GoodwillStatus,
    GoodwillSummaryResponseSchema,
    GoodwillType,
    GoodwillUpdateSchema,
    IdempotencyManager,
    ImpairmentRecognitionSchema,
    ImpairmentStatus,
    ImpairmentTestCreateSchema,
    ImpairmentTestResponseSchema,
    archive_goodwill,
    create_goodwill,
    dispose_goodwill,
    export_goodwill,
    get_amortization_schedule,
    get_goodwill,
    get_goodwill_by_code,
    get_goodwill_history,
    get_goodwill_service,
    get_goodwill_status,
    get_goodwill_summary,
    get_impairment_test,
    get_impairment_tests,
    list_goodwill,
    recognize_impairment,
    restore_goodwill,
    reverse_impairment,
    run_amortization,
    test_impairment,
    update_goodwill,
)

# =============================================================================
# Helper fixtures
# =============================================================================

@pytest.fixture
def mock_token_payload():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_goodwill_service():
    svc = AsyncMock()

    # Base goodwill response
    def create_mock_goodwill(**kwargs):
        defaults = {
            "id": uuid4(),
            "goodwill_code": "GW-001",
            "goodwill_name": "Test Goodwill",
            "goodwill_type": "purchase",
            "acquisition_date": date.today(),
            "acquisition_cost": Decimal("1000000"),
            "accumulated_amortization": Decimal("0"),
            "accumulated_impairment": Decimal("0"),
            "net_book_value": Decimal("1000000"),
            "useful_life_years": 10,
            "remaining_life_years": 10,
            "amortization_method": "straight_line",
            "acquired_entity_id": uuid4(),
            "acquired_entity_name": "Acquired Corp",
            "cash_generating_unit": "CGU_MAIN",
            "status": "active",
            "description": "Test",
            "notes": "Test notes",
            "is_locked": False,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_goodwill.return_value = create_mock_goodwill()
    svc.get_goodwill_by_id.return_value = create_mock_goodwill()
    svc.get_goodwill_by_code.return_value = create_mock_goodwill()
    svc.list_goodwill.return_value = [create_mock_goodwill()]
    svc.update_goodwill.return_value = create_mock_goodwill()
    svc.archive_goodwill.return_value = MagicMock(goodwill_code="GW-001", status="archived")
    svc.restore_goodwill.return_value = create_mock_goodwill(status="active")

    # Amortization
    svc.get_amortization_schedule.return_value = MagicMock(
        goodwill_id=uuid4(),
        goodwill_code="GW-001",
        goodwill_name="Test Goodwill",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        total_amortization=Decimal("100000"),
        total_impairment=Decimal("0"),
        final_nbv=Decimal("900000"),
        lines=[
            MagicMock(
                period=1,
                fiscal_year=2025,
                month=1,
                amortization_amount=Decimal("8333.33"),
                accumulated_amortization=Decimal("8333.33"),
                net_book_value=Decimal("991666.67"),
                journal_id=uuid4(),
                posted_at=datetime.now(UTC),
            )
        ],
    )
    svc.run_amortization.return_value = svc.get_amortization_schedule.return_value

    # Impairment
    svc.test_impairment.return_value = MagicMock(
        test_id=uuid4(),
        goodwill_code="GW-001",
        goodwill_name="Test Goodwill",
        carrying_amount=Decimal("1000000"),
        recoverable_amount=Decimal("800000"),
        fair_value_less_cost=Decimal("800000"),
        value_in_use=None,
        impairment_loss=Decimal("200000"),
        impairment_percentage=20.0,
        status="completed",
        recognized=False,
        recognized_at=None,
        journal_id=None,
        reason="Market decline",
        notes="Test",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
    )
    svc.get_impairment_tests.return_value = [svc.test_impairment.return_value]
    svc.get_impairment_test.return_value = svc.test_impairment.return_value
    svc.recognize_impairment.return_value = svc.test_impairment.return_value
    svc.reverse_impairment.return_value = svc.test_impairment.return_value

    # Disposal
    svc.dispose_goodwill.return_value = MagicMock(
        disposal_id=uuid4(),
        goodwill_code="GW-001",
        goodwill_name="Test Goodwill",
        carrying_amount=Decimal("800000"),
        disposal_proceeds=Decimal("900000"),
        gain_loss=Decimal("100000"),
        journal_id=uuid4(),
        status="completed",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
    )

    # Summary
    svc.get_goodwill_summary.return_value = MagicMock(
        total_goodwill=5,
        total_acquisition_cost=Decimal("5000000"),
        total_amortization=Decimal("200000"),
        total_impairment=Decimal("300000"),
        total_net_book_value=Decimal("4500000"),
        by_status={"active": 3, "impaired": 2},
        by_type={"purchase": 4000000, "consolidation": 1000000},
    )

    # History & status
    svc.get_goodwill_history.return_value = [
        MagicMock(
            timestamp=datetime.now(UTC),
            action="create",
            field=None,
            old_value=None,
            new_value=None,
            actor_id=uuid4(),
            actor_name="Admin",
            reason="Initial",
        )
    ]
    svc.get_goodwill_status.return_value = MagicMock(
        goodwill_code="GW-001",
        status="active",
        status_description="Goodwill is active",
        can_amortize=True,
        can_test_impairment=True,
        can_recognize_impairment=False,
        can_dispose=True,
        is_locked=False,
        is_archived=False,
        impairment_status="none",
        last_impairment_test=date.today(),
        last_impairment_loss=Decimal("0"),
        remaining_value=Decimal("1000000"),
    )

    # Export
    svc.export_goodwill.return_value = b"csv data"

    return svc


# =============================================================================
# Tests for IdempotencyManager
# =============================================================================

class TestIdempotencyManager:
    def test_initialization(self):
        manager = IdempotencyManager()
        assert manager._storage == {}
        assert manager._ttl_seconds == 86400

    def test_get_cached_result_miss(self):
        manager = IdempotencyManager()
        result = manager.get_cached_result("key1", "method1")
        assert result is None

    def test_cache_and_retrieve(self):
        manager = IdempotencyManager()
        data = {"id": "123", "status": "ok"}
        manager.cache_result("key1", "method1", data)
        cached = manager.get_cached_result("key1", "method1")
        assert cached == data

    def test_cache_serializes_complex_types(self):
        manager = IdempotencyManager()
        data = {"date": date.today(), "decimal": Decimal("10.50")}
        manager.cache_result("key2", "method2", data)
        cached = manager.get_cached_result("key2", "method2")
        assert cached is not None
        assert "date" in cached

    def test_cache_expiration(self):
        manager = IdempotencyManager()
        manager._ttl_seconds = 0
        manager.cache_result("key3", "method3", {"foo": "bar"})
        cached = manager.get_cached_result("key3", "method3")
        assert cached is None

    def test_key_generation_deterministic(self):
        manager = IdempotencyManager()
        key1 = manager._get_key("abc", "create_goodwill")
        key2 = manager._get_key("abc", "create_goodwill")
        key3 = manager._get_key("abc", "update_goodwill")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_goodwill_status_values(self):
        assert GoodwillStatus.ACTIVE.value == "active"
        assert GoodwillStatus.PARTIALLY_IMPAIRED.value == "partially_impaired"
        assert GoodwillStatus.FULLY_IMPAIRED.value == "fully_impaired"
        assert GoodwillStatus.AMORTIZED.value == "amortized"
        assert GoodwillStatus.DISPOSED.value == "disposed"
        assert GoodwillStatus.LOCKED.value == "locked"
        assert GoodwillStatus.ARCHIVED.value == "archived"

    def test_goodwill_type_values(self):
        assert GoodwillType.PURCHASE.value == "purchase"
        assert GoodwillType.BARGAIN.value == "bargain"
        assert GoodwillType.INTERNAL.value == "internal"
        assert GoodwillType.CONSOLIDATION.value == "consolidation"

    def test_impairment_status_values(self):
        assert ImpairmentStatus.DRAFT.value == "draft"
        assert ImpairmentStatus.COMPLETED.value == "completed"
        assert ImpairmentStatus.RECOGNIZED.value == "recognized"
        assert ImpairmentStatus.REVERSED.value == "reversed"
        assert ImpairmentStatus.CANCELLED.value == "cancelled"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestGoodwillCreateSchema:
    def test_valid_schema(self):
        data = {
            "goodwill_code": "GW-001",
            "goodwill_name": "Test Goodwill",
            "goodwill_type": GoodwillType.PURCHASE,
            "acquisition_date": date.today(),
            "acquisition_cost": Decimal("1000000"),
            "acquired_entity_id": uuid4(),
            "cash_generating_unit": "CGU_MAIN",
            "useful_life_years": 10,
            "amortization_method": "straight_line",
            "description": "Test",
            "notes": "Test notes",
        }
        schema = GoodwillCreateSchema(**data)
        assert schema.goodwill_code == "GW-001"
        assert schema.acquisition_cost == Decimal("1000000")

    def test_goodwill_code_uppercase(self):
        schema = GoodwillCreateSchema(
            goodwill_code="gw-001",
            goodwill_name="Test",
            goodwill_type=GoodwillType.PURCHASE,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("1000"),
        )
        assert schema.goodwill_code == "GW-001"

    def test_bargain_purchase_should_not_amortize(self):
        with pytest.raises(ValueError, match="Bargain purchase goodwill should not be amortized"):
            GoodwillCreateSchema(
                goodwill_code="GW-002",
                goodwill_name="Bargain",
                goodwill_type=GoodwillType.BARGAIN,
                acquisition_date=date.today(),
                acquisition_cost=Decimal("-500000"),  # negative goodwill
                useful_life_years=10,  # should be invalid
            )

    def test_acquisition_cost_positive(self):
        with pytest.raises(ValueError):
            GoodwillCreateSchema(
                goodwill_code="GW-001",
                goodwill_name="Test",
                goodwill_type=GoodwillType.PURCHASE,
                acquisition_date=date.today(),
                acquisition_cost=Decimal("-1000"),
            )


class TestImpairmentTestCreateSchema:
    def test_valid_with_fair_value(self):
        data = {
            "test_date": date.today(),
            "recoverable_amount": Decimal("800000"),
            "fair_value_less_cost": Decimal("800000"),
            "value_in_use": None,
            "discount_rate": Decimal("10.0"),
            "growth_rate": Decimal("5.0"),
            "reason": "Market decline",
            "notes": "Test",
        }
        schema = ImpairmentTestCreateSchema(**data)
        # recoverable_amount should be set to fair_value_less_cost
        assert schema.recoverable_amount == Decimal("800000")

    def test_valid_with_value_in_use(self):
        data = {
            "test_date": date.today(),
            "recoverable_amount": Decimal("900000"),
            "fair_value_less_cost": None,
            "value_in_use": Decimal("900000"),
            "discount_rate": Decimal("10.0"),
            "growth_rate": Decimal("5.0"),
            "reason": "Market decline",
            "notes": "Test",
        }
        schema = ImpairmentTestCreateSchema(**data)
        assert schema.recoverable_amount == Decimal("900000")

    def test_both_provided_takes_max(self):
        data = {
            "test_date": date.today(),
            "recoverable_amount": Decimal("0"),
            "fair_value_less_cost": Decimal("800000"),
            "value_in_use": Decimal("900000"),
            "discount_rate": Decimal("10.0"),
            "growth_rate": Decimal("5.0"),
            "reason": "Market decline",
            "notes": "Test",
        }
        schema = ImpairmentTestCreateSchema(**data)
        assert schema.recoverable_amount == Decimal("900000")  # max of the two

    def test_neither_provided_raises_error(self):
        with pytest.raises(ValueError, match="Either fair_value_less_cost or value_in_use must be provided"):
            ImpairmentTestCreateSchema(
                test_date=date.today(),
                recoverable_amount=Decimal("0"),
                fair_value_less_cost=None,
                value_in_use=None,
                reason="Test",
            )


class TestGoodwillDisposalSchema:
    def test_valid_schema(self):
        data = {
            "disposal_date": date.today(),
            "disposal_proceeds": Decimal("100000"),
            "reason": "Sold",
            "notes": "Test",
        }
        schema = GoodwillDisposalSchema(**data)
        assert schema.reason == "Sold"


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestGoodwillCRUD:
    async def test_create_success(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        request = GoodwillCreateSchema(
            goodwill_code="GW-001",
            goodwill_name="Test",
            goodwill_type=GoodwillType.PURCHASE,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("1000000"),
        )
        result = await create_goodwill(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, GoodwillResponseSchema)
        assert result.goodwill_code == "GW-001"
        mock_goodwill_service.create_goodwill.assert_called_once()

    async def test_create_idempotency(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        request = GoodwillCreateSchema(
            goodwill_code="GW-001",
            goodwill_name="Test",
            goodwill_type=GoodwillType.PURCHASE,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("1000"),
        )
        with patch("adapters.primary_api.v1.fastapi_goodwill_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "goodwill_code": "GW-001",
                "goodwill_name": "Test",
                "goodwill_type": "purchase",
                "acquisition_date": date.today().isoformat(),
                "acquisition_cost": "1000.00",
                "accumulated_amortization": "0.00",
                "accumulated_impairment": "0.00",
                "net_book_value": "1000.00",
                "useful_life_years": None,
                "remaining_life_years": None,
                "amortization_method": None,
                "acquired_entity_id": None,
                "acquired_entity_name": None,
                "cash_generating_unit": "CGU_MAIN",
                "status": "active",
                "description": None,
                "notes": None,
                "is_locked": False,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "version": 1,
            }
            result = await create_goodwill(
                request=request,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
            assert isinstance(result, GoodwillResponseSchema)
            mock_goodwill_service.create_goodwill.assert_not_called()

    async def test_create_value_error(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        mock_goodwill_service.create_goodwill.side_effect = ValueError("Duplicate code")
        request = GoodwillCreateSchema(
            goodwill_code="GW-001",
            goodwill_name="Test",
            goodwill_type=GoodwillType.PURCHASE,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("1000"),
        )
        with pytest.raises(HTTPException) as exc:
            await create_goodwill(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 422

    async def test_list_goodwill(self, mock_goodwill_service, mock_legal_entity_id):
        result = await list_goodwill(
            status=GoodwillStatus.ACTIVE,
            goodwill_type=GoodwillType.PURCHASE,
            cash_generating_unit="CGU1",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], GoodwillResponseSchema)
        mock_goodwill_service.list_goodwill.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            status="active",
            goodwill_type="purchase",
            cash_generating_unit="CGU1",
        )

    async def test_get_goodwill_success(self, mock_goodwill_service, mock_legal_entity_id):
        gid = uuid4()
        result = await get_goodwill(
            goodwill_id=gid,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, GoodwillResponseSchema)
        mock_goodwill_service.get_goodwill_by_id.assert_called_once_with(gid, mock_legal_entity_id)

    async def test_get_goodwill_not_found(self, mock_goodwill_service, mock_legal_entity_id):
        mock_goodwill_service.get_goodwill_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_goodwill(
                goodwill_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404

    async def test_get_goodwill_by_code_success(self, mock_goodwill_service, mock_legal_entity_id):
        result = await get_goodwill_by_code(
            goodwill_code="GW-001",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, GoodwillResponseSchema)
        mock_goodwill_service.get_goodwill_by_code.assert_called_once_with("GW-001", mock_legal_entity_id)

    async def test_get_goodwill_by_code_not_found(self, mock_goodwill_service, mock_legal_entity_id):
        mock_goodwill_service.get_goodwill_by_code.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_goodwill_by_code(
                goodwill_code="UNKNOWN",
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404

    async def test_update_goodwill_success(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        gid = uuid4()
        request = GoodwillUpdateSchema(goodwill_name="Updated Name")
        result = await update_goodwill(
            goodwill_id=gid,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, GoodwillResponseSchema)
        mock_goodwill_service.update_goodwill.assert_called_once()

    async def test_update_goodwill_not_found(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        mock_goodwill_service.update_goodwill.return_value = None
        request = GoodwillUpdateSchema()
        with pytest.raises(HTTPException) as exc:
            await update_goodwill(
                goodwill_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404

    async def test_archive_goodwill_success(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        gid = uuid4()
        result = await archive_goodwill(
            goodwill_id=gid,
            reason="Obsolete",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert result["status"] == "archived"
        mock_goodwill_service.archive_goodwill.assert_called_once_with(
            gid, mock_token_payload.user_id, mock_legal_entity_id, "Obsolete"
        )

    async def test_archive_goodwill_not_found(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        mock_goodwill_service.archive_goodwill.return_value = None
        with pytest.raises(HTTPException) as exc:
            await archive_goodwill(
                goodwill_id=uuid4(),
                reason="",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404

    async def test_restore_goodwill_success(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        gid = uuid4()
        result = await restore_goodwill(
            goodwill_id=gid,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, GoodwillResponseSchema)
        mock_goodwill_service.restore_goodwill.assert_called_once_with(
            gid, mock_token_payload.user_id, mock_legal_entity_id
        )

    async def test_restore_goodwill_not_found(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        mock_goodwill_service.restore_goodwill.return_value = None
        with pytest.raises(HTTPException) as exc:
            await restore_goodwill(
                goodwill_id=uuid4(),
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestAmortization:
    async def test_get_schedule_success(self, mock_goodwill_service, mock_legal_entity_id):
        gid = uuid4()
        result = await get_amortization_schedule(
            goodwill_id=gid,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, GoodwillAmortizationResponseSchema)
        assert len(result.lines) == 1
        assert isinstance(result.lines[0], AmortizationScheduleLineSchema)
        mock_goodwill_service.get_amortization_schedule.assert_called_once_with(gid, mock_legal_entity_id)

    async def test_get_schedule_not_found(self, mock_goodwill_service, mock_legal_entity_id):
        mock_goodwill_service.get_amortization_schedule.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_amortization_schedule(
                goodwill_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404

    async def test_run_amortization_success(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        gid = uuid4()
        period_end = date.today()
        result = await run_amortization(
            goodwill_id=gid,
            period_end_date=period_end,
            post_to_ledger=True,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, GoodwillAmortizationResponseSchema)
        mock_goodwill_service.run_amortization.assert_called_once_with(
            goodwill_id=gid,
            legal_entity_id=mock_legal_entity_id,
            period_end_date=period_end,
            post_to_ledger=True,
            performed_by=mock_token_payload.user_id,
        )

    async def test_run_amortization_not_found(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        mock_goodwill_service.run_amortization.return_value = None
        with pytest.raises(HTTPException) as exc:
            await run_amortization(
                goodwill_id=uuid4(),
                period_end_date=date.today(),
                post_to_ledger=True,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestImpairment:
    async def test_test_impairment_success(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        gid = uuid4()
        request = ImpairmentTestCreateSchema(
            test_date=date.today(),
            recoverable_amount=Decimal("800000"),
            fair_value_less_cost=Decimal("800000"),
            value_in_use=None,
            discount_rate=Decimal("10.0"),
            growth_rate=Decimal("5.0"),
            reason="Market decline",
            notes="Test",
        )
        result = await test_impairment(
            goodwill_id=gid,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, ImpairmentTestResponseSchema)
        assert result.impairment_loss == Decimal("200000")
        mock_goodwill_service.test_impairment.assert_called_once()

    async def test_test_impairment_not_found(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        mock_goodwill_service.test_impairment.return_value = None
        request = ImpairmentTestCreateSchema(
            test_date=date.today(),
            recoverable_amount=Decimal("800000"),
            fair_value_less_cost=Decimal("800000"),
            value_in_use=None,
            reason="Test",
        )
        with pytest.raises(HTTPException) as exc:
            await test_impairment(
                goodwill_id=uuid4(),
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404

    async def test_get_impairment_tests(self, mock_goodwill_service, mock_legal_entity_id):
        gid = uuid4()
        result = await get_impairment_tests(
            goodwill_id=gid,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ImpairmentTestResponseSchema)
        mock_goodwill_service.get_impairment_tests.assert_called_once_with(gid, mock_legal_entity_id)

    async def test_get_impairment_test_success(self, mock_goodwill_service, mock_legal_entity_id):
        tid = uuid4()
        result = await get_impairment_test(
            test_id=tid,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, ImpairmentTestResponseSchema)
        mock_goodwill_service.get_impairment_test.assert_called_once_with(tid, mock_legal_entity_id)

    async def test_get_impairment_test_not_found(self, mock_goodwill_service, mock_legal_entity_id):
        mock_goodwill_service.get_impairment_test.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_impairment_test(
                test_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404

    async def test_recognize_impairment_success(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        tid = uuid4()
        request = ImpairmentRecognitionSchema(
            test_id=tid,
            recognition_date=date.today(),
            notes="Recognized",
        )
        result = await recognize_impairment(
            test_id=tid,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, ImpairmentTestResponseSchema)
        mock_goodwill_service.recognize_impairment.assert_called_once()

    async def test_recognize_impairment_not_found(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        mock_goodwill_service.recognize_impairment.return_value = None
        request = ImpairmentRecognitionSchema(
            test_id=uuid4(),
            recognition_date=date.today(),
            notes="Test",
        )
        with pytest.raises(HTTPException) as exc:
            await recognize_impairment(
                test_id=uuid4(),
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404

    async def test_reverse_impairment_success(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        tid = uuid4()
        result = await reverse_impairment(
            test_id=tid,
            reason="Recovery",
            reversal_date=date.today(),
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, ImpairmentTestResponseSchema)
        mock_goodwill_service.reverse_impairment.assert_called_once_with(
            test_id=tid,
            legal_entity_id=mock_legal_entity_id,
            reversal_date=date.today(),
            reason="Recovery",
            reversed_by=mock_token_payload.user_id,
        )

    async def test_reverse_impairment_not_found(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        mock_goodwill_service.reverse_impairment.return_value = None
        with pytest.raises(HTTPException) as exc:
            await reverse_impairment(
                test_id=uuid4(),
                reason="Test",
                reversal_date=date.today(),
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestDisposal:
    async def test_dispose_success(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        gid = uuid4()
        request = GoodwillDisposalSchema(
            disposal_date=date.today(),
            disposal_proceeds=Decimal("100000"),
            reason="Sold",
            notes="Test",
        )
        result = await dispose_goodwill(
            goodwill_id=gid,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, GoodwillDisposalResponseSchema)
        assert result.gain_loss == Decimal("100000")
        mock_goodwill_service.dispose_goodwill.assert_called_once()

    async def test_dispose_not_found(self, mock_goodwill_service, mock_token_payload, mock_legal_entity_id):
        mock_goodwill_service.dispose_goodwill.return_value = None
        request = GoodwillDisposalSchema(
            disposal_date=date.today(),
            disposal_proceeds=Decimal("0"),
            reason="Test",
        )
        with pytest.raises(HTTPException) as exc:
            await dispose_goodwill(
                goodwill_id=uuid4(),
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestSummaryAndStatus:
    async def test_get_summary(self, mock_goodwill_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_goodwill_summary(
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, GoodwillSummaryResponseSchema)
        assert result.total_goodwill == 5
        mock_goodwill_service.get_goodwill_summary.assert_called_once_with(mock_legal_entity_id, as_of)

    async def test_get_history(self, mock_goodwill_service, mock_legal_entity_id):
        gid = uuid4()
        result = await get_goodwill_history(
            goodwill_id=gid,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert "action" in result[0]
        mock_goodwill_service.get_goodwill_history.assert_called_once_with(gid, mock_legal_entity_id)

    async def test_get_status_success(self, mock_goodwill_service, mock_legal_entity_id):
        gid = uuid4()
        result = await get_goodwill_status(
            goodwill_id=gid,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert result["status"] == "active"
        assert result["can_amortize"] is True
        mock_goodwill_service.get_goodwill_status.assert_called_once_with(gid, mock_legal_entity_id)

    async def test_get_status_not_found(self, mock_goodwill_service, mock_legal_entity_id):
        mock_goodwill_service.get_goodwill_status.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_goodwill_status(
                goodwill_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_goodwill_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestExport:
    async def test_export_csv(self, mock_goodwill_service, mock_legal_entity_id):
        as_of = date.today()
        response = await export_goodwill(
            format="csv",
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_goodwill_service.export_goodwill.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
            format="csv",
        )

    async def test_export_excel(self, mock_goodwill_service, mock_legal_entity_id):
        mock_goodwill_service.export_goodwill.return_value = b"excel data"
        as_of = date.today()
        response = await export_goodwill(
            format="excel",
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_goodwill_service,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# =============================================================================
# Tests for Dependency Injection
# =============================================================================

@pytest.mark.asyncio
async def test_get_goodwill_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_goodwill_service(request)
    assert result == "service"
