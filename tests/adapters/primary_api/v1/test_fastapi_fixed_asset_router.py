# adapters/primary_api/v1/test_fastapi_fixed_asset_router.py
"""
Comprehensive unit tests for FastAPI Fixed Asset Router.

Covers:
- IdempotencyManager
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service/use case)
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_fixed_asset_router import (
    AssetCategory,
    AssetCreateSchema,
    AssetResponseSchema,
    AssetStatus,
    AssetTransferRequestSchema,
    AssetTransferResponseSchema,
    AssetUpdateSchema,
    DepreciationMethod,
    DepreciationRunRequestSchema,
    DepreciationRunResponseSchema,
    DepreciationScheduleResponseSchema,
    DisposalRequestSchema,
    DisposalResponseSchema,
    DisposalType,
    FixedAssetSummaryResponseSchema,
    IdempotencyManager,
    ImpairmentTestRequestSchema,
    ImpairmentTestResponseSchema,
    RevaluationRequestSchema,
    RevaluationResponseSchema,
    RevaluationType,
    activate_asset,
    create_asset,
    deactivate_asset,
    dispose_asset,
    export_asset_register,
    get_asset,
    get_asset_by_code,
    get_asset_history,
    get_asset_summary,
    get_depreciation_schedule,
    list_assets,
    lock_asset,
    restore_impairment,
    revalue_asset,
    reverse_depreciation,
    run_depreciation,
    test_impairment,
    transfer_asset,
    unlock_asset,
    update_asset,
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
def mock_fixed_asset_svc():
    svc = AsyncMock()
    svc.create_asset.return_value = MagicMock(
        id=uuid4(),
        asset_code="TEST-001",
        asset_name="Test Asset",
        asset_category="equipment",
        acquisition_date=date.today(),
        acquisition_cost=Decimal("1000"),
        residual_value=Decimal("0"),
        useful_life_years=5,
        depreciation_method="straight_line",
        depreciation_rate=Decimal("0.2"),
        accumulated_depreciation=Decimal("0"),
        net_book_value=Decimal("1000"),
        current_period_depreciation=Decimal("0"),
        status="active",
        location="Warehouse",
        responsible_party="John Doe",
        is_active=True,
        is_locked=False,
        is_component=False,
        parent_asset_id=None,
        parent_asset_code=None,
        serial_number="SN123",
        supplier_name="Supplier Inc",
        purchase_order_number="PO-001",
        invoice_number="INV-001",
        notes="Test notes",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.get_asset_by_id.return_value = svc.create_asset.return_value
    svc.get_asset_by_code.return_value = svc.create_asset.return_value
    svc.update_asset.return_value = svc.create_asset.return_value
    svc.deactivate_asset.return_value = MagicMock(asset_code="TEST-001")
    svc.activate_asset.return_value = svc.create_asset.return_value
    svc.lock_asset.return_value = svc.create_asset.return_value
    svc.unlock_asset.return_value = svc.create_asset.return_value
    svc.list_assets.return_value = MagicMock(
        items=[svc.create_asset.return_value],
        total=1,
        page=1,
        page_size=20,
    )
    svc.get_depreciation_schedule.return_value = MagicMock(
        asset_id=uuid4(),
        asset_code="TEST-001",
        asset_name="Test Asset",
        start_date=date.today(),
        end_date=date.today(),
        lines=[],
        total_depreciation=Decimal("0"),
        final_nbv=Decimal("1000"),
    )
    svc.reverse_depreciation.return_value = MagicMock(
        reversal_journal_id=uuid4()
    )
    svc.get_summary.return_value = MagicMock(
        total_assets=10,
        total_acquisition_cost=Decimal("100000"),
        total_accumulated_depreciation=Decimal("20000"),
        total_net_book_value=Decimal("80000"),
        monthly_depreciation_charge=Decimal("500"),
        by_category={"equipment": {"cost": 50000, "nbv": 40000}},
        by_status={"active": 8, "disposed": 2},
        by_location={"WH1": 80000},
    )
    svc.export_asset_register.return_value = b"csv data"
    svc.get_asset_history.return_value = []
    return svc


@pytest.fixture
def mock_use_case():
    uc = AsyncMock()
    uc.execute.return_value = MagicMock(
        run_id=uuid4(),
        run_number="DEP-2025-01",
        total_assets=5,
        total_depreciation=Decimal("500"),
        journal_ids=[uuid4()],
        status="completed",
        errors=[],
        created_at=datetime.now(UTC),
    )
    return uc


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
        # Should be serialized to strings; we just check it doesn't error
        assert cached is not None
        assert "date" in cached

    def test_cache_expiration(self):
        manager = IdempotencyManager()
        manager._ttl_seconds = 0  # Force expiration on next check
        manager.cache_result("key3", "method3", {"foo": "bar"})
        # The TTL is checked when retrieving, so it should be None
        cached = manager.get_cached_result("key3", "method3")
        assert cached is None

    def test_key_generation_deterministic(self):
        manager = IdempotencyManager()
        key1 = manager._get_key("abc", "create_asset")
        key2 = manager._get_key("abc", "create_asset")
        key3 = manager._get_key("abc", "update_asset")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_asset_category_values(self):
        assert AssetCategory.BUILDING.value == "building"
        assert AssetCategory.LAND.value == "land"
        assert AssetCategory.MACHINERY.value == "machinery"
        assert AssetCategory.VEHICLE.value == "vehicle"
        assert AssetCategory.EQUIPMENT.value == "equipment"
        assert AssetCategory.FURNITURE.value == "furniture"
        assert AssetCategory.COMPUTER.value == "computer"
        assert AssetCategory.SOFTWARE.value == "software"
        assert AssetCategory.LEASEHOLD.value == "leasehold"
        assert AssetCategory.OTHER.value == "other"

    def test_depreciation_method_values(self):
        assert DepreciationMethod.STRAIGHT_LINE.value == "straight_line"
        assert DepreciationMethod.DECLINING_BALANCE.value == "declining_balance"
        assert DepreciationMethod.DOUBLE_DECLINING.value == "double_declining"
        assert DepreciationMethod.SUM_OF_YEARS.value == "sum_of_years"
        assert DepreciationMethod.UNITS_OF_PRODUCTION.value == "units_of_production"

    def test_asset_status_values(self):
        assert AssetStatus.DRAFT.value == "draft"
        assert AssetStatus.ACTIVE.value == "active"
        assert AssetStatus.IN_USE.value == "in_use"
        assert AssetStatus.UNDER_MAINTENANCE.value == "under_maintenance"
        assert AssetStatus.IDLE.value == "idle"
        assert AssetStatus.FULLY_DEPRECIATED.value == "fully_depreciated"
        assert AssetStatus.DISPOSED.value == "disposed"
        assert AssetStatus.SOLD.value == "sold"
        assert AssetStatus.SCRAPPED.value == "scrapped"
        assert AssetStatus.IMPAIRED.value == "impaired"
        assert AssetStatus.LOCKED.value == "locked"
        assert AssetStatus.ARCHIVED.value == "archived"

    def test_disposal_type_values(self):
        assert DisposalType.SALE.value == "sale"
        assert DisposalType.SCRAP.value == "scrap"
        assert DisposalType.DONATION.value == "donation"
        assert DisposalType.TRADE_IN.value == "trade_in"
        assert DisposalType.LOSS.value == "loss"
        assert DisposalType.THEFT.value == "theft"

    def test_revaluation_type_values(self):
        assert RevaluationType.INCREASE.value == "increase"
        assert RevaluationType.DECREASE.value == "decrease"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestAssetCreateSchema:
    def test_valid_schema(self):
        data = {
            "asset_code": "AST-001",
            "asset_name": "Test Asset",
            "asset_category": AssetCategory.EQUIPMENT,
            "acquisition_date": date.today(),
            "acquisition_cost": Decimal("1500.50"),
            "residual_value": Decimal("100.00"),
            "useful_life_years": 5,
            "depreciation_method": DepreciationMethod.STRAIGHT_LINE,
        }
        schema = AssetCreateSchema(**data)
        assert schema.asset_code == "AST-001"
        assert schema.asset_name == "Test Asset"
        assert schema.asset_category == AssetCategory.EQUIPMENT
        assert schema.acquisition_cost == Decimal("1500.50")

    def test_asset_code_uppercase(self):
        data = {
            "asset_code": "ast-001",  # lowercase
            "asset_name": "Test",
            "asset_category": AssetCategory.EQUIPMENT,
            "acquisition_date": date.today(),
            "acquisition_cost": Decimal("100"),
            "useful_life_years": 5,
        }
        schema = AssetCreateSchema(**data)
        assert schema.asset_code == "AST-001"  # validator uppercases

    def test_asset_code_required(self):
        with pytest.raises(ValueError, match="Asset code is required"):
            AssetCreateSchema(
                asset_code="",  # empty
                asset_name="Test",
                asset_category=AssetCategory.EQUIPMENT,
                acquisition_date=date.today(),
                acquisition_cost=Decimal("100"),
                useful_life_years=5,
            )

    def test_units_of_production_needs_rate(self):
        with pytest.raises(ValueError, match="Depreciation rate required"):
            AssetCreateSchema(
                asset_code="AST-001",
                asset_name="Test",
                asset_category=AssetCategory.EQUIPMENT,
                acquisition_date=date.today(),
                acquisition_cost=Decimal("100"),
                useful_life_years=5,
                depreciation_method=DepreciationMethod.UNITS_OF_PRODUCTION,
                depreciation_rate=None,
            )

    def test_units_of_production_with_rate_passes(self):
        schema = AssetCreateSchema(
            asset_code="AST-001",
            asset_name="Test",
            asset_category=AssetCategory.EQUIPMENT,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("100"),
            useful_life_years=5,
            depreciation_method=DepreciationMethod.UNITS_OF_PRODUCTION,
            depreciation_rate=Decimal("0.5"),
        )
        assert schema.depreciation_rate == Decimal("0.5")

    def test_acquisition_cost_positive(self):
        with pytest.raises(ValueError):
            AssetCreateSchema(
                asset_code="AST-001",
                asset_name="Test",
                asset_category=AssetCategory.EQUIPMENT,
                acquisition_date=date.today(),
                acquisition_cost=Decimal("-100"),
                useful_life_years=5,
            )


class TestAssetUpdateSchema:
    def test_valid_schema(self):
        data = {
            "asset_name": "Updated Asset",
            "location": "New Location",
            "status": AssetStatus.ACTIVE,
        }
        schema = AssetUpdateSchema(**data)
        assert schema.asset_name == "Updated Asset"
        assert schema.location == "New Location"
        assert schema.status == AssetStatus.ACTIVE

    def test_partial_update(self):
        schema = AssetUpdateSchema(asset_name="Only Name")
        assert schema.asset_name == "Only Name"
        assert schema.location is None


class TestAssetResponseSchema:
    def test_valid_schema(self):
        now = datetime.now(UTC)
        data = {
            "id": uuid4(),
            "asset_code": "AST-001",
            "asset_name": "Test",
            "asset_category": AssetCategory.EQUIPMENT,
            "acquisition_date": date.today(),
            "acquisition_cost": Decimal("1000"),
            "residual_value": Decimal("100"),
            "useful_life_years": 5,
            "depreciation_method": DepreciationMethod.STRAIGHT_LINE,
            "depreciation_rate": Decimal("0.2"),
            "accumulated_depreciation": Decimal("400"),
            "net_book_value": Decimal("600"),
            "current_period_depreciation": Decimal("100"),
            "status": AssetStatus.ACTIVE,
            "location": "WH1",
            "responsible_party": "John",
            "is_active": True,
            "is_locked": False,
            "is_component": False,
            "parent_asset_id": None,
            "parent_asset_code": None,
            "serial_number": "SN123",
            "supplier_name": "Supplier",
            "purchase_order_number": "PO-001",
            "invoice_number": "INV-001",
            "notes": None,
            "created_at": now,
            "updated_at": now,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "version": 1,
        }
        schema = AssetResponseSchema(**data)
        assert schema.id == data["id"]
        assert schema.asset_code == "AST-001"
        assert schema.status == AssetStatus.ACTIVE


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestCreateAsset:
    async def test_success(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        request = AssetCreateSchema(
            asset_code="TEST-001",
            asset_name="Test Asset",
            asset_category=AssetCategory.EQUIPMENT,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("1000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            depreciation_method=DepreciationMethod.STRAIGHT_LINE,
        )
        result = await create_asset(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, AssetResponseSchema)
        assert result.asset_code == "TEST-001"
        mock_fixed_asset_svc.create_asset.assert_called_once()

    async def test_idempotency_hit(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        request = AssetCreateSchema(
            asset_code="TEST-001",
            asset_name="Test Asset",
            asset_category=AssetCategory.EQUIPMENT,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("1000"),
            useful_life_years=5,
        )
        # Patch the IdempotencyManager to return a cached result
        with patch("adapters.primary_api.v1.fastapi_fixed_asset_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "asset_code": "TEST-001",
                "asset_name": "Test Asset",
                "asset_category": "equipment",
                "acquisition_date": date.today().isoformat(),
                "acquisition_cost": "1000.00",
                "residual_value": "0.00",
                "useful_life_years": 5,
                "depreciation_method": "straight_line",
                "depreciation_rate": None,
                "accumulated_depreciation": "0.00",
                "net_book_value": "1000.00",
                "current_period_depreciation": "0.00",
                "status": "active",
                "location": None,
                "responsible_party": None,
                "is_active": True,
                "is_locked": False,
                "is_component": False,
                "parent_asset_id": None,
                "parent_asset_code": None,
                "serial_number": None,
                "supplier_name": None,
                "purchase_order_number": None,
                "invoice_number": None,
                "notes": None,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "version": 1,
            }
            result = await create_asset(
                request=request,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                fixed_asset_svc=mock_fixed_asset_svc,
            )
            assert isinstance(result, AssetResponseSchema)
            # Service should NOT be called
            mock_fixed_asset_svc.create_asset.assert_not_called()

    async def test_validation_error(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        request = MagicMock()  # invalid
        with pytest.raises(HTTPException) as exc:
            await create_asset(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                fixed_asset_svc=mock_fixed_asset_svc,
            )
        assert exc.value.status_code == 422

    async def test_service_error(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        mock_fixed_asset_svc.create_asset.side_effect = Exception("DB error")
        request = AssetCreateSchema(
            asset_code="TEST-001",
            asset_name="Test",
            asset_category=AssetCategory.EQUIPMENT,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("1000"),
            useful_life_years=5,
        )
        with pytest.raises(HTTPException) as exc:
            await create_asset(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                fixed_asset_svc=mock_fixed_asset_svc,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestGetAsset:
    async def test_success(self, mock_fixed_asset_svc, mock_legal_entity_id):
        asset_id = uuid4()
        result = await get_asset(
            asset_id=asset_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, AssetResponseSchema)
        mock_fixed_asset_svc.get_asset_by_id.assert_called_once_with(asset_id, mock_legal_entity_id)

    async def test_not_found(self, mock_fixed_asset_svc, mock_legal_entity_id):
        mock_fixed_asset_svc.get_asset_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_asset(
                asset_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                fixed_asset_svc=mock_fixed_asset_svc,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestGetAssetByCode:
    async def test_success(self, mock_fixed_asset_svc, mock_legal_entity_id):
        result = await get_asset_by_code(
            asset_code="TEST-001",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, AssetResponseSchema)
        mock_fixed_asset_svc.get_asset_by_code.assert_called_once_with("TEST-001", mock_legal_entity_id)

    async def test_not_found(self, mock_fixed_asset_svc, mock_legal_entity_id):
        mock_fixed_asset_svc.get_asset_by_code.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_asset_by_code(
                asset_code="UNKNOWN",
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                fixed_asset_svc=mock_fixed_asset_svc,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestUpdateAsset:
    async def test_success(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        request = AssetUpdateSchema(asset_name="New Name")
        result = await update_asset(
            asset_id=asset_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, AssetResponseSchema)
        mock_fixed_asset_svc.update_asset.assert_called_once()

    async def test_not_found(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        mock_fixed_asset_svc.update_asset.return_value = None
        request = AssetUpdateSchema(asset_name="New Name")
        with pytest.raises(HTTPException) as exc:
            await update_asset(
                asset_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                fixed_asset_svc=mock_fixed_asset_svc,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestDeactivateAsset:
    async def test_deactivate(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        result = await deactivate_asset(
            asset_id=asset_id,
            permanent=False,
            reason="Test reason",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert result["action"] == "deactivated"
        mock_fixed_asset_svc.deactivate_asset.assert_called_once_with(
            asset_id, mock_token_payload.user_id, mock_legal_entity_id, "Test reason"
        )

    async def test_void(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        result = await deactivate_asset(
            asset_id=asset_id,
            permanent=True,
            reason="Test void",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert result["action"] == "voided"
        mock_fixed_asset_svc.void_asset.assert_called_once_with(
            asset_id, mock_token_payload.user_id, mock_legal_entity_id, "Test void"
        )


@pytest.mark.asyncio
class TestActivateAsset:
    async def test_success(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        result = await activate_asset(
            asset_id=asset_id,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, AssetResponseSchema)
        mock_fixed_asset_svc.activate_asset.assert_called_once_with(
            asset_id, mock_token_payload.user_id, mock_legal_entity_id
        )


@pytest.mark.asyncio
class TestLockUnlockAsset:
    async def test_lock(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        result = await lock_asset(
            asset_id=asset_id,
            reason="audit",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert result.is_locked is True
        mock_fixed_asset_svc.lock_asset.assert_called_once()

    async def test_unlock(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        result = await unlock_asset(
            asset_id=asset_id,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert result.is_locked is False
        mock_fixed_asset_svc.unlock_asset.assert_called_once()


@pytest.mark.asyncio
class TestListAssets:
    async def test_success(self, mock_fixed_asset_svc, mock_legal_entity_id):
        result = await list_assets(
            asset_category=AssetCategory.EQUIPMENT,
            status=AssetStatus.ACTIVE,
            is_active=True,
            location="WH1",
            search="test",
            page=2,
            page_size=10,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], AssetResponseSchema)
        mock_fixed_asset_svc.list_assets.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            category="equipment",
            status="active",
            is_active=True,
            location="WH1",
            search="test",
            page=2,
            page_size=10,
        )


@pytest.mark.asyncio
class TestDepreciationSchedule:
    async def test_success(self, mock_fixed_asset_svc, mock_legal_entity_id):
        asset_id = uuid4()
        start = date(2025, 1, 1)
        end = date(2025, 12, 31)
        result = await get_depreciation_schedule(
            asset_id=asset_id,
            start_date=start,
            end_date=end,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, DepreciationScheduleResponseSchema)
        mock_fixed_asset_svc.get_depreciation_schedule.assert_called_once_with(
            asset_id=asset_id,
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
        )


@pytest.mark.asyncio
class TestRunDepreciation:
    async def test_success(self, mock_use_case, mock_token_payload, mock_legal_entity_id):
        request = DepreciationRunRequestSchema(
            as_of_date=date.today(),
            post_to_ledger=True,
        )
        result = await run_depreciation(
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            use_case=mock_use_case,
        )
        assert isinstance(result, DepreciationRunResponseSchema)
        assert result.status == "completed"
        mock_use_case.execute.assert_called_once()


@pytest.mark.asyncio
class TestReverseDepreciation:
    async def test_success(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        dep_id = uuid4()
        result = await reverse_depreciation(
            depreciation_id=dep_id,
            reason="Error correction",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert result["reversed"] is True
        mock_fixed_asset_svc.reverse_depreciation.assert_called_once_with(
            depreciation_id=dep_id,
            reversed_by=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
            reason="Error correction",
        )

    async def test_not_found(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        mock_fixed_asset_svc.reverse_depreciation.return_value = None
        with pytest.raises(HTTPException) as exc:
            await reverse_depreciation(
                depreciation_id=uuid4(),
                reason="test",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                fixed_asset_svc=mock_fixed_asset_svc,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestRevalueAsset:
    async def test_success(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        request = RevaluationRequestSchema(
            revaluation_date=date.today(),
            new_acquisition_cost=Decimal("2000"),
            reason="Market increase",
        )
        mock_fixed_asset_svc.revaluate_asset.return_value = MagicMock(
            revaluation_id=uuid4(),
            asset_code="TEST-001",
            old_acquisition_cost=Decimal("1000"),
            new_acquisition_cost=Decimal("2000"),
            old_accumulated_depreciation=Decimal("400"),
            new_accumulated_depreciation=Decimal("400"),
            old_nbv=Decimal("600"),
            new_nbv=Decimal("1600"),
            surplus_deficit=Decimal("1000"),
            revaluation_type="increase",
            journal_id=uuid4(),
            status="completed",
            created_at=datetime.now(UTC),
            created_by=uuid4(),
        )
        result = await revalue_asset(
            asset_id=asset_id,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, RevaluationResponseSchema)
        assert result.revaluation_type == RevaluationType.INCREASE


@pytest.mark.asyncio
class TestDisposeAsset:
    async def test_success(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        request = DisposalRequestSchema(
            disposal_date=date.today(),
            disposal_type=DisposalType.SALE,
            disposal_proceeds=Decimal("800"),
            reason="Sold",
        )
        mock_fixed_asset_svc.dispose_asset.return_value = MagicMock(
            disposal_id=uuid4(),
            asset_code="TEST-001",
            disposal_type="sale",
            net_proceeds=Decimal("800"),
            nbv_at_disposal=Decimal("600"),
            gain_loss=Decimal("200"),
            journal_id=uuid4(),
            status="completed",
            created_at=datetime.now(UTC),
            created_by=uuid4(),
        )
        result = await dispose_asset(
            asset_id=asset_id,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, DisposalResponseSchema)
        assert result.disposal_type == DisposalType.SALE
        assert result.gain_loss == Decimal("200")


@pytest.mark.asyncio
class TestImpairment:
    async def test_impairment_test(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        request = ImpairmentTestRequestSchema(
            test_date=date.today(),
            recoverable_amount=Decimal("500"),
            reason="Market decline",
        )
        mock_fixed_asset_svc.test_impairment.return_value = MagicMock(
            test_id=uuid4(),
            asset_code="TEST-001",
            carrying_amount=Decimal("600"),
            recoverable_amount=Decimal("500"),
            impairment_loss=Decimal("100"),
            journal_id=uuid4(),
            status="recognized",
            created_at=datetime.now(UTC),
            created_by=uuid4(),
        )
        result = await test_impairment(
            asset_id=asset_id,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, ImpairmentTestResponseSchema)
        assert result.impairment_loss == Decimal("100")

    async def test_restore_impairment(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        test_id = uuid4()
        mock_fixed_asset_svc.restore_impairment.return_value = MagicMock(
            test_id=test_id,
            asset_code="TEST-001",
            test_date=date.today(),
            carrying_amount=Decimal("600"),
            recoverable_amount=Decimal("700"),
            impairment_loss=Decimal("0"),
            journal_id=uuid4(),
            status="restored",
            created_at=datetime.now(UTC),
            created_by=uuid4(),
        )
        result = await restore_impairment(
            asset_id=asset_id,
            test_id=test_id,
            reason="Recovery",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, ImpairmentTestResponseSchema)
        assert result.status == "restored"


@pytest.mark.asyncio
class TestTransferAsset:
    async def test_success(self, mock_fixed_asset_svc, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        to_entity = uuid4()
        request = AssetTransferRequestSchema(
            transfer_date=date.today(),
            from_legal_entity_id=mock_legal_entity_id,
            to_legal_entity_id=to_entity,
            reason="Internal transfer",
        )
        mock_fixed_asset_svc.transfer_asset.return_value = MagicMock(
            transfer_id=uuid4(),
            asset_code="TEST-001",
            from_legal_entity_name="Entity A",
            to_legal_entity_name="Entity B",
            nbv_at_transfer=Decimal("600"),
            journal_id=uuid4(),
            status="completed",
            created_at=datetime.now(UTC),
            created_by=uuid4(),
        )
        result = await transfer_asset(
            asset_id=asset_id,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, AssetTransferResponseSchema)
        assert result.to_legal_entity_id == to_entity


@pytest.mark.asyncio
class TestAssetSummary:
    async def test_success(self, mock_fixed_asset_svc, mock_legal_entity_id):
        as_of = date.today()
        result = await get_asset_summary(
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, FixedAssetSummaryResponseSchema)
        assert result.total_assets == 10
        assert result.total_acquisition_cost == Decimal("100000")
        mock_fixed_asset_svc.get_summary.assert_called_once_with(mock_legal_entity_id, as_of)


@pytest.mark.asyncio
class TestExportAssetRegister:
    async def test_csv_export(self, mock_fixed_asset_svc, mock_legal_entity_id):
        as_of = date.today()
        response = await export_asset_register(
            format="csv",
            as_of_date=as_of,
            category=AssetCategory.EQUIPMENT,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_fixed_asset_svc.export_asset_register.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
            format="csv",
            category="equipment",
        )

    async def test_excel_export(self, mock_fixed_asset_svc, mock_legal_entity_id):
        as_of = date.today()
        response = await export_asset_register(
            format="excel",
            as_of_date=as_of,
            category=None,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.asyncio
class TestAssetHistory:
    async def test_success(self, mock_fixed_asset_svc, mock_legal_entity_id):
        asset_id = uuid4()
        result = await get_asset_history(
            asset_id=asset_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            fixed_asset_svc=mock_fixed_asset_svc,
        )
        assert isinstance(result, list)
        mock_fixed_asset_svc.get_asset_history.assert_called_once_with(asset_id, mock_legal_entity_id)
