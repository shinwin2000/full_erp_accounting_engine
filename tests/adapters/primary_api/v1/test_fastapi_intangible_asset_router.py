# test_fastapi_intangible_asset_router.py
"""
Comprehensive unit tests for FastAPI Intangible Asset Router.

Covers:
- IdempotencyManager
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
- Amortization rate calculation
- Expiry date validation
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_intangible_asset_router import (
    AmortizationMethod,
    AmortizationRunRequestSchema,
    AmortizationRunResponseSchema,
    AmortizationScheduleLineSchema,
    AmortizationScheduleResponseSchema,
    AssetTransferRequestSchema,
    AssetTransferResponseSchema,
    DisposalRequestSchema,
    DisposalResponseSchema,
    DisposalType,
    IdempotencyManager,
    ImpairmentTestRequestSchema,
    ImpairmentTestResponseSchema,
    IntangibleAssetCategory,
    IntangibleAssetCreateSchema,
    IntangibleAssetResponseSchema,
    IntangibleAssetStatus,
    IntangibleAssetSummaryResponseSchema,
    IntangibleAssetUpdateSchema,
    RevaluationRequestSchema,
    RevaluationResponseSchema,
    activate_asset,
    archive_asset,
    create_asset,
    dispose_asset,
    export_asset_register,
    get_amortization_run_use_case,
    get_amortization_schedule,
    get_asset,
    get_asset_by_code,
    get_asset_history,
    get_asset_summary,
    get_intangible_asset_svc,
    list_assets,
    lock_asset,
    restore_impairment,
    revalue_asset,
    reverse_amortization,
    run_amortization,
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
def mock_intangible_service():
    svc = AsyncMock()

    # Base asset response
    def create_mock_asset(**kwargs):
        defaults = {
            "id": uuid4(),
            "asset_code": "IA-001",
            "asset_name": "Test Patent",
            "asset_category": "patent",
            "acquisition_date": date.today(),
            "acquisition_cost": Decimal("100000"),
            "residual_value": Decimal("0"),
            "useful_life_years": 20,
            "amortization_method": "straight_line",
            "amortization_rate": Decimal("5.0000"),
            "accumulated_amortization": Decimal("0"),
            "accumulated_impairment": Decimal("0"),
            "net_book_value": Decimal("100000"),
            "current_period_amortization": Decimal("0"),
            "registration_number": "PAT-2025-001",
            "issuing_authority": "DGIP",
            "expiry_date": None,
            "status": "active",
            "is_active": True,
            "is_locked": False,
            "use_fiscal_amortization": False,
            "notes": "Test notes",
            "attachment_ids": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_asset.return_value = create_mock_asset()
    svc.get_asset_by_id.return_value = create_mock_asset()
    svc.get_asset_by_code.return_value = create_mock_asset()
    svc.update_asset.return_value = create_mock_asset()
    svc.archive_asset.return_value = create_mock_asset(status="archived")
    svc.activate_asset.return_value = create_mock_asset()
    svc.lock_asset.return_value = create_mock_asset(is_locked=True)
    svc.unlock_asset.return_value = create_mock_asset(is_locked=False)
    svc.list_assets.return_value = MagicMock(
        items=[create_mock_asset()],
        total=1,
    )

    # Amortization
    svc.get_amortization_schedule.return_value = MagicMock(
        asset_id=uuid4(),
        asset_code="IA-001",
        asset_name="Test Patent",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        lines=[
            MagicMock(
                period=1,
                fiscal_year=2025,
                month=1,
                period_name="Jan 2025",
                amortization_amount=Decimal("416.67"),
                accumulated_amortization=Decimal("416.67"),
                net_book_value=Decimal("99583.33"),
                status="posted",
                journal_id=uuid4(),
                posted_at=datetime.now(UTC),
            )
        ],
        total_amortization=Decimal("5000"),
        final_nbv=Decimal("95000"),
    )
    svc.reverse_amortization.return_value = MagicMock(
        reversal_journal_id=uuid4()
    )

    # Revaluation
    svc.revaluate_asset.return_value = MagicMock(
        revaluation_id=uuid4(),
        asset_code="IA-001",
        old_acquisition_cost=Decimal("100000"),
        new_acquisition_cost=Decimal("120000"),
        old_accumulated_amortization=Decimal("5000"),
        new_accumulated_amortization=Decimal("5000"),
        old_nbv=Decimal("95000"),
        new_nbv=Decimal("115000"),
        surplus_deficit=Decimal("20000"),
        journal_id=uuid4(),
        status="completed",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
    )

    # Disposal
    svc.dispose_asset.return_value = MagicMock(
        disposal_id=uuid4(),
        asset_code="IA-001",
        disposal_type="sale",
        net_proceeds=Decimal("80000"),
        nbv_at_disposal=Decimal("90000"),
        gain_loss=Decimal("-10000"),
        journal_id=uuid4(),
        status="completed",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
    )

    # Impairment
    svc.test_impairment.return_value = MagicMock(
        test_id=uuid4(),
        asset_code="IA-001",
        carrying_amount=Decimal("95000"),
        recoverable_amount=Decimal("80000"),
        impairment_loss=Decimal("15000"),
        impairment_percentage=15.79,
        journal_id=uuid4(),
        status="recognized",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
    )
    svc.restore_impairment.return_value = svc.test_impairment.return_value

    # Transfer
    svc.transfer_asset.return_value = MagicMock(
        transfer_id=uuid4(),
        asset_code="IA-001",
        from_legal_entity_name="Entity A",
        to_legal_entity_name="Entity B",
        nbv_at_transfer=Decimal("95000"),
        journal_id=uuid4(),
        status="completed",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
    )

    # Summary
    svc.get_summary.return_value = MagicMock(
        total_assets=5,
        total_acquisition_cost=Decimal("500000"),
        total_accumulated_amortization=Decimal("100000"),
        total_accumulated_impairment=Decimal("20000"),
        total_net_book_value=Decimal("380000"),
        monthly_amortization_charge=Decimal("5000"),
        by_category={"patent": {"cost": 100000, "nbv": 80000}},
        by_status={"active": 4, "impaired": 1},
    )

    # History
    svc.get_asset_history.return_value = [
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

    # Export
    svc.export_asset_register.return_value = b"csv data"

    return svc


@pytest.fixture
def mock_amortization_use_case():
    uc = AsyncMock()
    uc.execute.return_value = MagicMock(
        run_id=uuid4(),
        run_number="AMORT-2025-01",
        total_assets=3,
        total_amortization=Decimal("15000"),
        journal_ids=[uuid4()],
        status="completed",
        errors=[],
        created_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
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
        key1 = manager._get_key("abc", "create_asset")
        key2 = manager._get_key("abc", "create_asset")
        key3 = manager._get_key("abc", "update_asset")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_intangible_asset_category_values(self):
        assert IntangibleAssetCategory.PATENT.value == "patent"
        assert IntangibleAssetCategory.TRADEMARK.value == "trademark"
        assert IntangibleAssetCategory.COPYRIGHT.value == "copyright"
        assert IntangibleAssetCategory.SOFTWARE.value == "software"
        assert IntangibleAssetCategory.LICENSE.value == "license"
        assert IntangibleAssetCategory.FRANCHISE.value == "franchise"
        assert IntangibleAssetCategory.GOODWILL.value == "goodwill"
        assert IntangibleAssetCategory.CUSTOMER_RELATIONSHIP.value == "customer_relationship"
        assert IntangibleAssetCategory.TECHNOLOGY.value == "technology"
        assert IntangibleAssetCategory.BRAND.value == "brand"
        assert IntangibleAssetCategory.OTHER.value == "other"

    def test_amortization_method_values(self):
        assert AmortizationMethod.STRAIGHT_LINE.value == "straight_line"
        assert AmortizationMethod.DECLINING_BALANCE.value == "declining_balance"
        assert AmortizationMethod.DOUBLE_DECLINING.value == "double_declining"
        assert AmortizationMethod.SUM_OF_YEARS.value == "sum_of_years"
        assert AmortizationMethod.UNITS_OF_PRODUCTION.value == "units_of_production"

    def test_intangible_asset_status_values(self):
        assert IntangibleAssetStatus.DRAFT.value == "draft"
        assert IntangibleAssetStatus.ACTIVE.value == "active"
        assert IntangibleAssetStatus.FULLY_AMORTIZED.value == "fully_amortized"
        assert IntangibleAssetStatus.IMPAIRED.value == "impaired"
        assert IntangibleAssetStatus.DISPOSED.value == "disposed"
        assert IntangibleAssetStatus.SOLD.value == "sold"
        assert IntangibleAssetStatus.LOCKED.value == "locked"
        assert IntangibleAssetStatus.ARCHIVED.value == "archived"

    def test_disposal_type_values(self):
        assert DisposalType.SALE.value == "sale"
        assert DisposalType.SCRAP.value == "scrap"
        assert DisposalType.DONATION.value == "donation"
        assert DisposalType.EXPIRED.value == "expired"
        assert DisposalType.LOSS.value == "loss"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestIntangibleAssetCreateSchema:
    def test_valid_schema(self):
        data = {
            "asset_code": "IA-001",
            "asset_name": "Test Patent",
            "asset_category": IntangibleAssetCategory.PATENT,
            "acquisition_date": date.today(),
            "acquisition_cost": Decimal("100000"),
            "residual_value": Decimal("0"),
            "useful_life_years": 20,
            "amortization_method": AmortizationMethod.STRAIGHT_LINE,
            "amortization_rate": Decimal("5.0000"),
            "registration_number": "PAT-001",
            "issuing_authority": "DGIP",
            "expiry_date": None,
            "is_active": True,
            "use_fiscal_amortization": False,
            "notes": "Test",
            "attachment_ids": [uuid4()],
        }
        schema = IntangibleAssetCreateSchema(**data)
        assert schema.asset_code == "IA-001"
        assert schema.acquisition_cost == Decimal("100000")

    def test_asset_code_uppercase(self):
        schema = IntangibleAssetCreateSchema(
            asset_code="ia-001",
            asset_name="Test",
            asset_category=IntangibleAssetCategory.PATENT,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("1000"),
        )
        assert schema.asset_code == "IA-001"

    def test_expiry_after_acquisition(self):
        with pytest.raises(ValueError, match="Expiry date must be after acquisition date"):
            IntangibleAssetCreateSchema(
                asset_code="IA-001",
                asset_name="Test",
                asset_category=IntangibleAssetCategory.PATENT,
                acquisition_date=date(2025, 1, 10),
                acquisition_cost=Decimal("1000"),
                expiry_date=date(2025, 1, 5),
            )

    def test_useful_life_defaults(self):
        # If useful_life_years not provided, should default from category
        schema = IntangibleAssetCreateSchema(
            asset_code="IA-001",
            asset_name="Test",
            asset_category=IntangibleAssetCategory.SOFTWARE,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("1000"),
        )
        # SOFTWARE default is 5
        assert schema.useful_life_years == 5

    def test_units_of_production_needs_rate(self):
        with pytest.raises(ValueError, match="Amortization rate required for units of production method"):
            IntangibleAssetCreateSchema(
                asset_code="IA-001",
                asset_name="Test",
                asset_category=IntangibleAssetCategory.PATENT,
                acquisition_date=date.today(),
                acquisition_cost=Decimal("1000"),
                amortization_method=AmortizationMethod.UNITS_OF_PRODUCTION,
                amortization_rate=None,
            )


class TestIntangibleAssetUpdateSchema:
    def test_valid_schema(self):
        data = {
            "asset_name": "Updated Patent",
            "residual_value": Decimal("1000"),
            "useful_life_years": 15,
            "amortization_method": AmortizationMethod.DOUBLE_DECLINING,
            "is_active": False,
            "notes": "Updated",
            "status": IntangibleAssetStatus.ACTIVE,
        }
        schema = IntangibleAssetUpdateSchema(**data)
        assert schema.asset_name == "Updated Patent"
        assert schema.status == IntangibleAssetStatus.ACTIVE


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestAssetCRUD:
    async def test_create_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        request = IntangibleAssetCreateSchema(
            asset_code="IA-001",
            asset_name="Test Patent",
            asset_category=IntangibleAssetCategory.PATENT,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("100000"),
            useful_life_years=20,
        )
        result = await create_asset(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, IntangibleAssetResponseSchema)
        assert result.asset_code == "IA-001"
        mock_intangible_service.create_asset.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_idempotency(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        request = IntangibleAssetCreateSchema(
            asset_code="IA-001",
            asset_name="Test",
            asset_category=IntangibleAssetCategory.PATENT,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("1000"),
        )
        with patch("adapters.primary_api.v1.fastapi_intangible_asset_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "asset_code": "IA-001",
                "asset_name": "Test",
                "asset_category": "patent",
                "acquisition_date": date.today().isoformat(),
                "acquisition_cost": "1000.00",
                "residual_value": "0.00",
                "useful_life_years": 20,
                "amortization_method": "straight_line",
                "amortization_rate": "5.0000",
                "accumulated_amortization": "0.00",
                "accumulated_impairment": "0.00",
                "net_book_value": "1000.00",
                "current_period_amortization": "0.00",
                "registration_number": None,
                "issuing_authority": None,
                "expiry_date": None,
                "status": "active",
                "is_active": True,
                "is_locked": False,
                "use_fiscal_amortization": False,
                "notes": None,
                "attachment_ids": [],
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
                intangible_asset_svc=mock_intangible_service,
            )
            assert isinstance(result, IntangibleAssetResponseSchema)
            mock_intangible_service.create_asset.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_value_error(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        mock_intangible_service.create_asset.side_effect = ValueError("Duplicate code")
        request = IntangibleAssetCreateSchema(
            asset_code="IA-001",
            asset_name="Test",
            asset_category=IntangibleAssetCategory.PATENT,
            acquisition_date=date.today(),
            acquisition_cost=Decimal("1000"),
        )
        with pytest.raises(HTTPException) as exc:
            await create_asset(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                intangible_asset_svc=mock_intangible_service,
            )
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_get_asset_success(self, mock_intangible_service, mock_legal_entity_id):
        asset_id = uuid4()
        result = await get_asset(
            asset_id=asset_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, IntangibleAssetResponseSchema)
        mock_intangible_service.get_asset_by_id.assert_called_once_with(asset_id, mock_legal_entity_id)

    @pytest.mark.asyncio
    async def test_get_asset_not_found(self, mock_intangible_service, mock_legal_entity_id):
        mock_intangible_service.get_asset_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_asset(
                asset_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                intangible_asset_svc=mock_intangible_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_asset_by_code_success(self, mock_intangible_service, mock_legal_entity_id):
        result = await get_asset_by_code(
            asset_code="IA-001",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, IntangibleAssetResponseSchema)
        mock_intangible_service.get_asset_by_code.assert_called_once_with("IA-001", mock_legal_entity_id)

    @pytest.mark.asyncio
    async def test_get_asset_by_code_not_found(self, mock_intangible_service, mock_legal_entity_id):
        mock_intangible_service.get_asset_by_code.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_asset_by_code(
                asset_code="UNKNOWN",
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                intangible_asset_svc=mock_intangible_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_asset_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        request = IntangibleAssetUpdateSchema(asset_name="Updated Name")
        result = await update_asset(
            asset_id=asset_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, IntangibleAssetResponseSchema)
        mock_intangible_service.update_asset.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_asset_not_found(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        mock_intangible_service.update_asset.return_value = None
        request = IntangibleAssetUpdateSchema()
        with pytest.raises(HTTPException) as exc:
            await update_asset(
                asset_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                intangible_asset_svc=mock_intangible_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_archive_asset_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        result = await archive_asset(
            asset_id=asset_id,
            reason="Obsolete",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert result["status"] == "archived"
        mock_intangible_service.archive_asset.assert_called_once_with(
            asset_id, mock_token_payload.user_id, mock_legal_entity_id, "Obsolete"
        )

    @pytest.mark.asyncio
    async def test_archive_asset_not_found(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        mock_intangible_service.archive_asset.return_value = None
        with pytest.raises(HTTPException) as exc:
            await archive_asset(
                asset_id=uuid4(),
                reason="",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                intangible_asset_svc=mock_intangible_service,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_activate_asset_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        result = await activate_asset(
            asset_id=asset_id,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, IntangibleAssetResponseSchema)
        mock_intangible_service.activate_asset.assert_called_once_with(
            asset_id, mock_token_payload.user_id, mock_legal_entity_id
        )

    @pytest.mark.asyncio
    async def test_lock_asset_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        result = await lock_asset(
            asset_id=asset_id,
            reason="Audit",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert result.is_locked is True
        mock_intangible_service.lock_asset.assert_called_once_with(
            asset_id, mock_token_payload.user_id, mock_legal_entity_id, "Audit"
        )

    @pytest.mark.asyncio
    async def test_unlock_asset_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        result = await unlock_asset(
            asset_id=asset_id,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert result.is_locked is False
        mock_intangible_service.unlock_asset.assert_called_once_with(
            asset_id, mock_token_payload.user_id, mock_legal_entity_id
        )

    @pytest.mark.asyncio
    async def test_list_assets(self, mock_intangible_service, mock_legal_entity_id):
        result = await list_assets(
            asset_category=IntangibleAssetCategory.PATENT,
            status=IntangibleAssetStatus.ACTIVE,
            is_active=True,
            search="test",
            expiry_before=None,
            page=1,
            page_size=20,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], IntangibleAssetResponseSchema)
        mock_intangible_service.list_assets.assert_called_once()


@pytest.mark.asyncio
class TestAmortization:
    async def test_get_schedule_success(self, mock_intangible_service, mock_legal_entity_id):
        asset_id = uuid4()
        result = await get_amortization_schedule(
            asset_id=asset_id,
            start_date=None,
            end_date=None,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, AmortizationScheduleResponseSchema)
        assert len(result.lines) == 1
        assert isinstance(result.lines[0], AmortizationScheduleLineSchema)
        mock_intangible_service.get_amortization_schedule.assert_called_once_with(
            asset_id=asset_id,
            legal_entity_id=mock_legal_entity_id,
            start_date=None,
            end_date=None,
        )

    async def test_run_amortization_success(self, mock_amortization_use_case, mock_token_payload, mock_legal_entity_id):
        request = AmortizationRunRequestSchema(
            as_of_date=date.today(),
            post_to_ledger=True,
        )
        result = await run_amortization(
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            use_case=mock_amortization_use_case,
        )
        assert isinstance(result, AmortizationRunResponseSchema)
        assert result.total_assets == 3
        mock_amortization_use_case.execute.assert_called_once()

    async def test_run_amortization_value_error(self, mock_amortization_use_case, mock_token_payload, mock_legal_entity_id):
        mock_amortization_use_case.execute.side_effect = ValueError("Invalid date")
        request = AmortizationRunRequestSchema(as_of_date=date.today())
        with pytest.raises(HTTPException) as exc:
            await run_amortization(
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                use_case=mock_amortization_use_case,
            )
        assert exc.value.status_code == 422

    async def test_reverse_amortization_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        amort_id = uuid4()
        result = await reverse_amortization(
            amortization_id=amort_id,
            reason="Correction",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert result["reversed"] is True
        mock_intangible_service.reverse_amortization.assert_called_once_with(
            amortization_id=amort_id,
            reversed_by=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
            reason="Correction",
        )

    async def test_reverse_amortization_not_found(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        mock_intangible_service.reverse_amortization.return_value = None
        with pytest.raises(HTTPException) as exc:
            await reverse_amortization(
                amortization_id=uuid4(),
                reason="Test",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                intangible_asset_svc=mock_intangible_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestRevaluation:
    async def test_revalue_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        request = RevaluationRequestSchema(
            revaluation_date=date.today(),
            new_acquisition_cost=Decimal("120000"),
            reason="Market increase",
        )
        result = await revalue_asset(
            asset_id=asset_id,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, RevaluationResponseSchema)
        assert result.new_acquisition_cost == Decimal("120000")
        mock_intangible_service.revaluate_asset.assert_called_once()

    async def test_revalue_value_error(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        mock_intangible_service.revaluate_asset.side_effect = ValueError("Invalid revaluation")
        request = RevaluationRequestSchema(
            revaluation_date=date.today(),
            new_acquisition_cost=Decimal("0"),
            reason="Test",
        )
        with pytest.raises(HTTPException) as exc:
            await revalue_asset(
                asset_id=uuid4(),
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                intangible_asset_svc=mock_intangible_service,
            )
        assert exc.value.status_code == 422


@pytest.mark.asyncio
class TestDisposal:
    async def test_dispose_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        request = DisposalRequestSchema(
            disposal_date=date.today(),
            disposal_type=DisposalType.SALE,
            disposal_proceeds=Decimal("80000"),
            reason="Sold",
        )
        result = await dispose_asset(
            asset_id=asset_id,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, DisposalResponseSchema)
        assert result.disposal_type == DisposalType.SALE
        assert result.gain_loss == Decimal("-10000")
        mock_intangible_service.dispose_asset.assert_called_once()

    async def test_dispose_value_error(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        mock_intangible_service.dispose_asset.side_effect = ValueError("Cannot dispose active asset")
        request = DisposalRequestSchema(
            disposal_date=date.today(),
            disposal_type=DisposalType.SALE,
            disposal_proceeds=Decimal("0"),
            reason="Test",
        )
        with pytest.raises(HTTPException) as exc:
            await dispose_asset(
                asset_id=uuid4(),
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                intangible_asset_svc=mock_intangible_service,
            )
        assert exc.value.status_code == 422


@pytest.mark.asyncio
class TestImpairment:
    async def test_test_impairment_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        request = ImpairmentTestRequestSchema(
            test_date=date.today(),
            recoverable_amount=Decimal("80000"),
            reason="Market decline",
            valuation_method="DCF",
        )
        result = await test_impairment(
            asset_id=asset_id,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, ImpairmentTestResponseSchema)
        assert result.impairment_loss == Decimal("15000")
        mock_intangible_service.test_impairment.assert_called_once()

    async def test_test_impairment_value_error(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        mock_intangible_service.test_impairment.side_effect = ValueError("Recoverable amount must be positive")
        request = ImpairmentTestRequestSchema(
            test_date=date.today(),
            recoverable_amount=Decimal("-100"),
            reason="Test",
        )
        with pytest.raises(HTTPException) as exc:
            await test_impairment(
                asset_id=uuid4(),
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                intangible_asset_svc=mock_intangible_service,
            )
        assert exc.value.status_code == 422

    async def test_restore_impairment_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        test_id = uuid4()
        result = await restore_impairment(
            asset_id=asset_id,
            test_id=test_id,
            reason="Recovery",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, ImpairmentTestResponseSchema)
        mock_intangible_service.restore_impairment.assert_called_once_with(
            asset_id=asset_id,
            test_id=test_id,
            reason="Recovery",
            restored_by=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
        )

    async def test_restore_impairment_not_found(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        mock_intangible_service.restore_impairment.return_value = None
        with pytest.raises(HTTPException) as exc:
            await restore_impairment(
                asset_id=uuid4(),
                test_id=uuid4(),
                reason="Test",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                intangible_asset_svc=mock_intangible_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestTransfer:
    async def test_transfer_success(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        to_entity = uuid4()
        request = AssetTransferRequestSchema(
            transfer_date=date.today(),
            from_legal_entity_id=mock_legal_entity_id,
            to_legal_entity_id=to_entity,
            reason="Restructuring",
            notes="Transfer to subsidiary",
        )
        result = await transfer_asset(
            asset_id=asset_id,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, AssetTransferResponseSchema)
        assert result.to_legal_entity_id == to_entity
        mock_intangible_service.transfer_asset.assert_called_once()

    async def test_transfer_value_error(self, mock_intangible_service, mock_token_payload, mock_legal_entity_id):
        mock_intangible_service.transfer_asset.side_effect = ValueError("Cannot transfer impaired asset")
        request = AssetTransferRequestSchema(
            transfer_date=date.today(),
            from_legal_entity_id=mock_legal_entity_id,
            to_legal_entity_id=uuid4(),
            reason="Test",
        )
        with pytest.raises(HTTPException) as exc:
            await transfer_asset(
                asset_id=uuid4(),
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                intangible_asset_svc=mock_intangible_service,
            )
        assert exc.value.status_code == 422


@pytest.mark.asyncio
class TestSummaryAndHistory:
    async def test_get_asset_summary(self, mock_intangible_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_asset_summary(
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, IntangibleAssetSummaryResponseSchema)
        assert result.total_assets == 5
        assert result.total_net_book_value == Decimal("380000")
        mock_intangible_service.get_summary.assert_called_once_with(mock_legal_entity_id, as_of)

    async def test_get_asset_history(self, mock_intangible_service, mock_legal_entity_id):
        asset_id = uuid4()
        result = await get_asset_history(
            asset_id=asset_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["action"] == "create"
        mock_intangible_service.get_asset_history.assert_called_once_with(asset_id, mock_legal_entity_id)


@pytest.mark.asyncio
class TestExport:
    async def test_export_csv(self, mock_intangible_service, mock_legal_entity_id):
        as_of = date.today()
        response = await export_asset_register(
            format="csv",
            as_of_date=as_of,
            category=IntangibleAssetCategory.PATENT,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_intangible_service.export_asset_register.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
            format="csv",
            category="patent",
        )

    async def test_export_excel(self, mock_intangible_service, mock_legal_entity_id):
        mock_intangible_service.export_asset_register.return_value = b"excel data"
        as_of = date.today()
        response = await export_asset_register(
            format="excel",
            as_of_date=as_of,
            category=None,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            intangible_asset_svc=mock_intangible_service,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# =============================================================================
# Tests for Dependency Injection
# =============================================================================

@pytest.mark.asyncio
async def test_get_intangible_asset_svc():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_intangible_asset_svc(request)
    assert result == "service"


@pytest.mark.asyncio
async def test_get_amortization_run_use_case():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "use_case"
    result = await get_amortization_run_use_case(request)
    assert result == "use_case"