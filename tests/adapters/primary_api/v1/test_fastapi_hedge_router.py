# adapters/primary_api/v1/test_fastapi_hedge_router.py
"""
Comprehensive unit tests for FastAPI Hedge Router.

Covers:
- IdempotencyManager
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
- Effectiveness test computed properties (effectiveness_ratio, is_effective, ineffectiveness_amount)
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_hedge_router import (
    DerivativeCreateSchema,
    DerivativeResponseSchema,
    DerivativeStatus,
    DerivativeType,
    DerivativeUpdateSchema,
    EffectivenessMethod,
    EffectivenessTestCreateSchema,
    EffectivenessTestResponseSchema,
    FairValueLevel,
    FairValueMeasurementResponseSchema,
    FairValueMeasurementSchema,
    HedgeDashboardResponseSchema,
    HedgedItemSchema,
    HedgeIneffectivenessRecognitionSchema,
    HedgeIneffectivenessResponseSchema,
    HedgeRelationshipCreateSchema,
    HedgeRelationshipResponseSchema,
    HedgeRelationshipUpdateSchema,
    HedgeStatus,
    HedgeType,
    IdempotencyManager,
    create_derivative,
    create_hedge_relationship,
    designate_hedge,
    discontinue_hedge,
    export_derivatives,
    export_hedge_relationships,
    get_derivative,
    get_fair_value_history,
    get_hedge_dashboard,
    get_hedge_history,
    get_hedge_relationship,
    get_hedge_service,
    get_hedge_status,
    list_derivatives,
    list_effectiveness_tests,
    list_hedge_relationships,
    recognize_ineffectiveness,
    record_fair_value,
    run_effectiveness_test,
    terminate_derivative,
    update_derivative,
    update_hedge_relationship,
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
def mock_hedge_service():
    svc = AsyncMock()

    # Derivative responses
    svc.create_derivative.return_value = MagicMock(
        id=uuid4(),
        instrument_code="DER-001",
        instrument_name="Test Derivative",
        derivative_type="forward",
        counterparty_id=uuid4(),
        counterparty_name="Counterparty A",
        underlying_asset="USD/IDR",
        notional_amount=Decimal("100000"),
        currency_code="IDR",
        contract_date=date.today(),
        settlement_date=date.today(),
        maturity_date=date.today(),
        strike_price=Decimal("15000"),
        premium_paid=Decimal("0"),
        fair_value_at_initial=Decimal("0"),
        fair_value_at_reporting=Decimal("500"),
        valuation_method="MARK_TO_MARKET",
        counterparty_rating="AAA",
        is_designated_hedge=False,
        hedging_relationship_id=None,
        status="active",
        is_locked=False,
        notes="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.get_derivative_by_id.return_value = svc.create_derivative.return_value
    svc.list_derivatives.return_value = [svc.create_derivative.return_value]
    svc.update_derivative.return_value = svc.create_derivative.return_value
    svc.terminate_derivative.return_value = MagicMock(
        instrument_code="DER-001",
        status="terminated",
    )

    # Hedge relationship responses
    svc.create_hedge_relationship.return_value = MagicMock(
        id=uuid4(),
        hedge_type="fair_value",
        hedge_ratio=Decimal("1.0"),
        designation_date=date.today(),
        effective_start_date=date.today(),
        effective_end_date=None,
        risk_management_objective="Manage interest rate risk",
        risk_strategy_document="Strategy doc",
        effectiveness_test_method="dollar_offset",
        effectiveness_threshold_lower=Decimal("0.8"),
        effectiveness_threshold_upper=Decimal("1.25"),
        hedged_item_type="asset",
        hedged_item_id=uuid4(),
        hedged_item_description="Loan receivable",
        hedged_item_amount=Decimal("100000"),
        hedged_item_currency="IDR",
        derivative_id=uuid4(),
        derivative_code="DER-001",
        derivative_name="Test Derivative",
        status="draft",
        is_effective=None,
        ineffectiveness_ytd=Decimal("0"),
        is_locked=False,
        notes="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.get_hedge_relationship_by_id.return_value = svc.create_hedge_relationship.return_value
    svc.list_hedge_relationships.return_value = [svc.create_hedge_relationship.return_value]
    svc.update_hedge_relationship.return_value = svc.create_hedge_relationship.return_value
    svc.designate_hedge.return_value = svc.create_hedge_relationship.return_value
    svc.discontinue_hedge.return_value = svc.create_hedge_relationship.return_value

    # Effectiveness test
    svc.run_effectiveness_test.return_value = MagicMock(
        test_id=uuid4(),
        test_method="dollar_offset",
        fair_value_change_derivative=Decimal("1000"),
        fair_value_change_hedged_item=Decimal("1100"),
        effectiveness_ratio=Decimal("0.9091"),
        effectiveness_percent=90.91,
        is_effective=True,
        ineffectiveness_amount=Decimal("100"),
        prospective_effective=True,
        prospective_ratio=Decimal("0.95"),
        notes="Test",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
    )
    svc.list_effectiveness_tests.return_value = [svc.run_effectiveness_test.return_value]

    # Fair value
    svc.record_fair_value_measurement.return_value = MagicMock(
        id=uuid4(),
        instrument_id=uuid4(),
        instrument_code="DER-001",
        instrument_name="Test Derivative",
        instrument_type="derivative",
        measurement_date=date.today(),
        fair_value=Decimal("500"),
        level_input="level_1",
        valuation_technique="Mark-to-market",
        unobservable_inputs=None,
        valuer_name="Valuer A",
        valuation_report_path="/reports/fv.pdf",
        notes="Test",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
    )
    svc.get_fair_value_history.return_value = [svc.record_fair_value_measurement.return_value]

    # Ineffectiveness
    svc.recognize_ineffectiveness.return_value = [
        MagicMock(
            id=uuid4(),
            hedge_relationship_id=uuid4(),
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            ineffectiveness_amount=Decimal("100"),
            cumulative_ineffectiveness=Decimal("200"),
            journal_id=uuid4(),
            status="posted",
            created_at=datetime.now(UTC),
            created_by=uuid4(),
        )
    ]

    # Dashboard
    svc.get_hedge_dashboard.return_value = MagicMock(
        total_derivatives=10,
        active_derivatives=5,
        total_hedge_relationships=8,
        active_hedge_relationships=6,
        effective_hedges=5,
        ineffective_hedges=1,
        total_notional_amount=Decimal("5000000"),
        total_fair_value=Decimal("25000"),
        total_ineffectiveness_ytd=Decimal("500"),
        by_hedge_type={"fair_value": {"count": 3, "notional": 3000000}},
        by_derivative_type={"forward": 4, "swap_irs": 2},
    )

    # History & status
    svc.get_hedge_history.return_value = [
        MagicMock(
            timestamp=datetime.now(UTC),
            action="create",
            field=None,
            old_value=None,
            new_value=None,
            actor_id=uuid4(),
            actor_name="Admin",
            reason="Initial creation",
        )
    ]
    svc.get_hedge_status.return_value = MagicMock(
        hedge_type="fair_value",
        status="active",
        is_effective=True,
        can_test=True,
        can_discontinue=True,
        can_edit=False,
        is_locked=False,
        effectiveness_ratio=Decimal("0.95"),
        ineffectiveness_ytd=Decimal("100"),
        last_test_date=date(2025, 1, 15),
        next_test_date=date(2025, 2, 15),
        cumulative_ineffectiveness=Decimal("200"),
    )

    # Export
    svc.export_derivatives.return_value = b"csv data"
    svc.export_hedge_relationships.return_value = b"csv data"

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
        data = {"date": datetime.now(UTC), "decimal": Decimal("10.50")}
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
        key1 = manager._get_key("abc", "create_derivative")
        key2 = manager._get_key("abc", "create_derivative")
        key3 = manager._get_key("abc", "update_derivative")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_hedge_type_values(self):
        assert HedgeType.FAIR_VALUE.value == "fair_value"
        assert HedgeType.CASH_FLOW.value == "cash_flow"
        assert HedgeType.NET_INVESTMENT.value == "net_investment"

    def test_derivative_type_values(self):
        assert DerivativeType.FORWARD.value == "forward"
        assert DerivativeType.FUTURES.value == "futures"
        assert DerivativeType.OPTION_CALL.value == "option_call"
        assert DerivativeType.OPTION_PUT.value == "option_put"
        assert DerivativeType.SWAP_IRS.value == "swap_irs"
        assert DerivativeType.SWAP_CCS.value == "swap_ccs"
        assert DerivativeType.SWAP_CDS.value == "swap_cds"
        assert DerivativeType.WARRANT.value == "warrant"
        assert DerivativeType.STRUCTURED.value == "structured"

    def test_effectiveness_method_values(self):
        assert EffectivenessMethod.DOLLAR_OFFSET.value == "dollar_offset"
        assert EffectivenessMethod.REGRESSION.value == "regression"
        assert EffectivenessMethod.VAR.value == "var"
        assert EffectivenessMethod.HYPOTHETICAL_DERIVATIVE.value == "hypothetical_derivative"

    def test_fair_value_level_values(self):
        assert FairValueLevel.LEVEL_1.value == "level_1"
        assert FairValueLevel.LEVEL_2.value == "level_2"
        assert FairValueLevel.LEVEL_3.value == "level_3"

    def test_hedge_status_values(self):
        assert HedgeStatus.DRAFT.value == "draft"
        assert HedgeStatus.DESIGNATED.value == "designated"
        assert HedgeStatus.ACTIVE.value == "active"
        assert HedgeStatus.INEFFECTIVE.value == "ineffective"
        assert HedgeStatus.DISCONTINUED.value == "discontinued"
        assert HedgeStatus.EXPIRED.value == "expired"
        assert HedgeStatus.CANCELLED.value == "cancelled"
        assert HedgeStatus.LOCKED.value == "locked"
        assert HedgeStatus.ARCHIVED.value == "archived"

    def test_derivative_status_values(self):
        assert DerivativeStatus.ACTIVE.value == "active"
        assert DerivativeStatus.EXERCISED.value == "exercised"
        assert DerivativeStatus.EXPIRED.value == "expired"
        assert DerivativeStatus.TERMINATED.value == "terminated"
        assert DerivativeStatus.CANCELLED.value == "cancelled"
        assert DerivativeStatus.LOCKED.value == "locked"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestDerivativeCreateSchema:
    def test_valid_schema(self):
        data = {
            "instrument_code": "DER-001",
            "instrument_name": "USD/IDR Forward",
            "derivative_type": DerivativeType.FORWARD,
            "counterparty_id": uuid4(),
            "underlying_asset": "USD/IDR",
            "notional_amount": Decimal("100000"),
            "currency_code": "IDR",
            "contract_date": date(2025, 1, 1),
            "settlement_date": date(2025, 6, 1),
            "maturity_date": date(2025, 6, 1),
            "strike_price": Decimal("15000"),
            "premium_paid": Decimal("0"),
            "fair_value_at_initial": Decimal("0"),
            "valuation_method": "MARK_TO_MARKET",
            "counterparty_rating": "AAA",
            "notes": "Test",
        }
        schema = DerivativeCreateSchema(**data)
        assert schema.instrument_code == "DER-001"
        assert schema.derivative_type == DerivativeType.FORWARD

    def test_instrument_code_uppercase(self):
        schema = DerivativeCreateSchema(
            instrument_code="der-001",
            instrument_name="Test",
            derivative_type=DerivativeType.FORWARD,
            counterparty_id=uuid4(),
            underlying_asset="USD",
            notional_amount=Decimal("1000"),
            contract_date=date.today(),
            maturity_date=date.today(),
        )
        assert schema.instrument_code == "DER-001"

    def test_settlement_date_after_contract(self):
        with pytest.raises(ValueError, match="Settlement date must be after contract date"):
            DerivativeCreateSchema(
                instrument_code="DER-001",
                instrument_name="Test",
                derivative_type=DerivativeType.FORWARD,
                counterparty_id=uuid4(),
                underlying_asset="USD",
                notional_amount=Decimal("1000"),
                contract_date=date(2025, 6, 1),
                settlement_date=date(2025, 1, 1),
                maturity_date=date(2025, 6, 1),
            )

    def test_maturity_date_after_contract(self):
        with pytest.raises(ValueError, match="Maturity date must be after contract date"):
            DerivativeCreateSchema(
                instrument_code="DER-001",
                instrument_name="Test",
                derivative_type=DerivativeType.FORWARD,
                counterparty_id=uuid4(),
                underlying_asset="USD",
                notional_amount=Decimal("1000"),
                contract_date=date(2025, 6, 1),
                maturity_date=date(2025, 1, 1),
            )


class TestHedgeRelationshipCreateSchema:
    def test_valid_schema(self):
        hedged_item = HedgedItemSchema(
            item_type="asset",
            item_id=uuid4(),
            item_description="Loan",
            amount=Decimal("100000"),
            currency_code="IDR",
            maturity_date=date(2025, 12, 31),
            risk_type="interest_rate",
        )
        data = {
            "hedge_type": HedgeType.FAIR_VALUE,
            "hedged_item": hedged_item,
            "derivative_id": uuid4(),
            "hedge_ratio": Decimal("1.0"),
            "designation_date": date.today(),
            "effective_start_date": date.today(),
            "effective_end_date": None,
            "risk_management_objective": "Manage risk",
            "risk_strategy_document": "Strategy",
            "effectiveness_test_method": EffectivenessMethod.DOLLAR_OFFSET,
            "effectiveness_threshold_lower": Decimal("0.8"),
            "effectiveness_threshold_upper": Decimal("1.25"),
            "notes": "Test",
        }
        schema = HedgeRelationshipCreateSchema(**data)
        assert schema.hedge_type == HedgeType.FAIR_VALUE
        assert schema.hedge_ratio == Decimal("1.0")

    def test_effective_end_after_start(self):
        hedged_item = HedgedItemSchema(
            item_type="asset",
            item_id=uuid4(),
            item_description="Test",
            amount=Decimal("1000"),
            maturity_date=date.today(),
            risk_type="interest_rate",
        )
        with pytest.raises(ValueError, match="Effective end date must be after effective start date"):
            HedgeRelationshipCreateSchema(
                hedge_type=HedgeType.FAIR_VALUE,
                hedged_item=hedged_item,
                derivative_id=uuid4(),
                hedge_ratio=Decimal("1.0"),
                designation_date=date(2025, 1, 1),
                effective_start_date=date(2025, 1, 1),
                effective_end_date=date(2024, 12, 31),
                risk_management_objective="Test",
                effectiveness_test_method=EffectivenessMethod.DOLLAR_OFFSET,
            )

    def test_designation_date_on_or_before_start(self):
        hedged_item = HedgedItemSchema(
            item_type="asset",
            item_id=uuid4(),
            item_description="Test",
            amount=Decimal("1000"),
            maturity_date=date.today(),
            risk_type="interest_rate",
        )
        with pytest.raises(ValueError, match="Designation date must be on or before effective start date"):
            HedgeRelationshipCreateSchema(
                hedge_type=HedgeType.FAIR_VALUE,
                hedged_item=hedged_item,
                derivative_id=uuid4(),
                hedge_ratio=Decimal("1.0"),
                designation_date=date(2025, 1, 10),
                effective_start_date=date(2025, 1, 1),
                risk_management_objective="Test",
                effectiveness_test_method=EffectivenessMethod.DOLLAR_OFFSET,
            )


class TestEffectivenessTestCreateSchema:
    def test_properties(self):
        schema = EffectivenessTestCreateSchema(
            test_date=date.today(),
            test_method=EffectivenessMethod.DOLLAR_OFFSET,
            fair_value_change_derivative=Decimal("1000"),
            fair_value_change_hedged_item=Decimal("1100"),
            notes="Test",
        )
        # effectiveness_ratio = abs(1000)/abs(1100) = 0.9091
        assert schema.effectiveness_ratio == Decimal("0.9091")
        assert schema.is_effective is True  # 0.9091 within [0.8, 1.25]
        assert schema.ineffectiveness_amount == Decimal("100.00")  # 1100 - 1000

    def test_ineffectiveness_when_derivative_larger(self):
        schema = EffectivenessTestCreateSchema(
            test_date=date.today(),
            test_method=EffectivenessMethod.DOLLAR_OFFSET,
            fair_value_change_derivative=Decimal("1200"),
            fair_value_change_hedged_item=Decimal("1000"),
            notes="Test",
        )
        assert schema.effectiveness_ratio == Decimal("1.2")
        assert schema.is_effective is True  # within range
        assert schema.ineffectiveness_amount == Decimal("200.00")  # 1200 - 1000

    def test_ineffective_outside_range(self):
        schema = EffectivenessTestCreateSchema(
            test_date=date.today(),
            test_method=EffectivenessMethod.DOLLAR_OFFSET,
            fair_value_change_derivative=Decimal("1000"),
            fair_value_change_hedged_item=Decimal("2000"),
            notes="Test",
        )
        assert schema.effectiveness_ratio == Decimal("0.5")
        assert schema.is_effective is False  # 0.5 < 0.8
        assert schema.ineffectiveness_amount == Decimal("1000.00")


# =============================================================================
# Tests for Endpoint Functions
# =============================================================================

@pytest.mark.asyncio
class TestDerivativeEndpoints:
    async def test_create_derivative_success(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        request = DerivativeCreateSchema(
            instrument_code="DER-001",
            instrument_name="Forward USD/IDR",
            derivative_type=DerivativeType.FORWARD,
            counterparty_id=uuid4(),
            underlying_asset="USD/IDR",
            notional_amount=Decimal("100000"),
            contract_date=date.today(),
            maturity_date=date.today(),
        )
        result = await create_derivative(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, DerivativeResponseSchema)
        assert result.instrument_code == "DER-001"
        mock_hedge_service.create_derivative.assert_called_once()

    async def test_create_derivative_idempotency(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        request = DerivativeCreateSchema(
            instrument_code="DER-001",
            instrument_name="Test",
            derivative_type=DerivativeType.FORWARD,
            counterparty_id=uuid4(),
            underlying_asset="USD",
            notional_amount=Decimal("1000"),
            contract_date=date.today(),
            maturity_date=date.today(),
        )
        with patch("adapters.primary_api.v1.fastapi_hedge_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "instrument_code": "DER-001",
                "instrument_name": "Test",
                "derivative_type": "forward",
                "counterparty_id": str(uuid4()),
                "counterparty_name": None,
                "underlying_asset": "USD",
                "notional_amount": "1000.00",
                "currency_code": "IDR",
                "contract_date": date.today().isoformat(),
                "settlement_date": None,
                "maturity_date": date.today().isoformat(),
                "strike_price": None,
                "premium_paid": "0.00",
                "fair_value_at_initial": "0.00",
                "fair_value_at_reporting": "0.00",
                "valuation_method": "MARK_TO_MARKET",
                "counterparty_rating": None,
                "is_designated_hedge": False,
                "hedging_relationship_id": None,
                "status": "active",
                "is_locked": False,
                "notes": None,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "version": 1,
            }
            result = await create_derivative(
                request=request,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_hedge_service,
            )
            assert isinstance(result, DerivativeResponseSchema)
            mock_hedge_service.create_derivative.assert_not_called()

    async def test_list_derivatives(self, mock_hedge_service, mock_legal_entity_id):
        result = await list_derivatives(
            derivative_type=DerivativeType.FORWARD,
            status=DerivativeStatus.ACTIVE,
            is_designated=True,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], DerivativeResponseSchema)
        mock_hedge_service.list_derivatives.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            derivative_type="forward",
            status="active",
            is_designated=True,
        )

    async def test_get_derivative_success(self, mock_hedge_service, mock_legal_entity_id):
        derivative_id = uuid4()
        result = await get_derivative(
            derivative_id=derivative_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, DerivativeResponseSchema)
        mock_hedge_service.get_derivative_by_id.assert_called_once_with(derivative_id, mock_legal_entity_id)

    async def test_get_derivative_not_found(self, mock_hedge_service, mock_legal_entity_id):
        mock_hedge_service.get_derivative_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_derivative(
                derivative_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_hedge_service,
            )
        assert exc.value.status_code == 404

    async def test_update_derivative_success(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        derivative_id = uuid4()
        request = DerivativeUpdateSchema(instrument_name="Updated Name")
        result = await update_derivative(
            derivative_id=derivative_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, DerivativeResponseSchema)
        mock_hedge_service.update_derivative.assert_called_once()

    async def test_update_derivative_not_found(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        mock_hedge_service.update_derivative.return_value = None
        request = DerivativeUpdateSchema()
        with pytest.raises(HTTPException) as exc:
            await update_derivative(
                derivative_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_hedge_service,
            )
        assert exc.value.status_code == 404

    async def test_terminate_derivative_success(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        derivative_id = uuid4()
        result = await terminate_derivative(
            derivative_id=derivative_id,
            reason="Expired",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert result["status"] == "terminated"
        mock_hedge_service.terminate_derivative.assert_called_once_with(
            derivative_id, mock_legal_entity_id, "Expired", mock_token_payload.user_id
        )


@pytest.mark.asyncio
class TestHedgeRelationshipEndpoints:
    async def test_create_relationship_success(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        hedged_item = HedgedItemSchema(
            item_type="asset",
            item_id=uuid4(),
            item_description="Loan",
            amount=Decimal("100000"),
            maturity_date=date.today(),
            risk_type="interest_rate",
        )
        request = HedgeRelationshipCreateSchema(
            hedge_type=HedgeType.FAIR_VALUE,
            hedged_item=hedged_item,
            derivative_id=uuid4(),
            hedge_ratio=Decimal("1.0"),
            designation_date=date.today(),
            effective_start_date=date.today(),
            risk_management_objective="Test",
            effectiveness_test_method=EffectivenessMethod.DOLLAR_OFFSET,
        )
        result = await create_hedge_relationship(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, HedgeRelationshipResponseSchema)
        assert result.hedge_type == HedgeType.FAIR_VALUE
        mock_hedge_service.create_hedge_relationship.assert_called_once()

    async def test_list_relationships(self, mock_hedge_service, mock_legal_entity_id):
        result = await list_hedge_relationships(
            hedge_type=HedgeType.FAIR_VALUE,
            status=HedgeStatus.ACTIVE,
            derivative_id=None,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], HedgeRelationshipResponseSchema)
        mock_hedge_service.list_hedge_relationships.assert_called_once()

    async def test_get_relationship_success(self, mock_hedge_service, mock_legal_entity_id):
        rel_id = uuid4()
        result = await get_hedge_relationship(
            relationship_id=rel_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, HedgeRelationshipResponseSchema)
        mock_hedge_service.get_hedge_relationship_by_id.assert_called_once_with(rel_id, mock_legal_entity_id)

    async def test_get_relationship_not_found(self, mock_hedge_service, mock_legal_entity_id):
        mock_hedge_service.get_hedge_relationship_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_hedge_relationship(
                relationship_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_hedge_service,
            )
        assert exc.value.status_code == 404

    async def test_update_relationship_success(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        rel_id = uuid4()
        request = HedgeRelationshipUpdateSchema(risk_management_objective="Updated Objective")
        result = await update_hedge_relationship(
            relationship_id=rel_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, HedgeRelationshipResponseSchema)
        mock_hedge_service.update_hedge_relationship.assert_called_once()

    async def test_designate_hedge_success(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        rel_id = uuid4()
        result = await designate_hedge(
            relationship_id=rel_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, HedgeRelationshipResponseSchema)
        mock_hedge_service.designate_hedge.assert_called_once_with(
            rel_id, mock_legal_entity_id, mock_token_payload.user_id
        )

    async def test_designate_hedge_not_found(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        mock_hedge_service.designate_hedge.return_value = None
        with pytest.raises(HTTPException) as exc:
            await designate_hedge(
                relationship_id=uuid4(),
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_hedge_service,
            )
        assert exc.value.status_code == 404

    async def test_discontinue_hedge_success(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        rel_id = uuid4()
        result = await discontinue_hedge(
            relationship_id=rel_id,
            discontinue_date=date.today(),
            reason="Ended",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, HedgeRelationshipResponseSchema)
        mock_hedge_service.discontinue_hedge.assert_called_once_with(
            rel_id, mock_legal_entity_id, date.today(), "Ended", mock_token_payload.user_id
        )


@pytest.mark.asyncio
class TestEffectivenessTestEndpoints:
    async def test_run_effectiveness_test_success(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        rel_id = uuid4()
        request = EffectivenessTestCreateSchema(
            test_date=date.today(),
            test_method=EffectivenessMethod.DOLLAR_OFFSET,
            fair_value_change_derivative=Decimal("1000"),
            fair_value_change_hedged_item=Decimal("1100"),
        )
        result = await run_effectiveness_test(
            relationship_id=rel_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, EffectivenessTestResponseSchema)
        assert result.is_effective is True
        mock_hedge_service.run_effectiveness_test.assert_called_once()

    async def test_run_effectiveness_test_not_found(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        mock_hedge_service.run_effectiveness_test.return_value = None
        request = EffectivenessTestCreateSchema(
            test_date=date.today(),
            test_method=EffectivenessMethod.DOLLAR_OFFSET,
            fair_value_change_derivative=Decimal("1000"),
            fair_value_change_hedged_item=Decimal("1000"),
        )
        with pytest.raises(HTTPException) as exc:
            await run_effectiveness_test(
                relationship_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_hedge_service,
            )
        assert exc.value.status_code == 404

    async def test_list_effectiveness_tests(self, mock_hedge_service, mock_legal_entity_id):
        rel_id = uuid4()
        result = await list_effectiveness_tests(
            relationship_id=rel_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], EffectivenessTestResponseSchema)
        mock_hedge_service.list_effectiveness_tests.assert_called_once_with(rel_id, mock_legal_entity_id)


@pytest.mark.asyncio
class TestFairValueEndpoints:
    async def test_record_fair_value_success(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        request = FairValueMeasurementSchema(
            instrument_id=uuid4(),
            instrument_type="derivative",
            measurement_date=date.today(),
            fair_value=Decimal("500"),
            level_input=FairValueLevel.LEVEL_1,
            valuation_technique="Mark-to-market",
        )
        result = await record_fair_value(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, FairValueMeasurementResponseSchema)
        assert result.fair_value == Decimal("500")
        mock_hedge_service.record_fair_value_measurement.assert_called_once()

    async def test_get_fair_value_history(self, mock_hedge_service, mock_legal_entity_id):
        instrument_id = uuid4()
        result = await get_fair_value_history(
            instrument_id=instrument_id,
            instrument_type="derivative",
            start_date=None,
            end_date=None,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], FairValueMeasurementResponseSchema)
        mock_hedge_service.get_fair_value_history.assert_called_once()


@pytest.mark.asyncio
class TestIneffectivenessEndpoints:
    async def test_recognize_ineffectiveness_success(self, mock_hedge_service, mock_token_payload, mock_legal_entity_id):
        request = HedgeIneffectivenessRecognitionSchema(
            period_end_date=date.today(),
            post_to_ledger=True,
            notes="Test",
        )
        result = await recognize_ineffectiveness(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], HedgeIneffectivenessResponseSchema)
        mock_hedge_service.recognize_ineffectiveness.assert_called_once()


@pytest.mark.asyncio
class TestDashboardAndStatus:
    async def test_get_hedge_dashboard(self, mock_hedge_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_hedge_dashboard(
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, HedgeDashboardResponseSchema)
        assert result.total_derivatives == 10
        assert result.active_derivatives == 5
        mock_hedge_service.get_hedge_dashboard.assert_called_once_with(mock_legal_entity_id, as_of)

    async def test_get_hedge_history(self, mock_hedge_service, mock_legal_entity_id):
        rel_id = uuid4()
        result = await get_hedge_history(
            relationship_id=rel_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert "action" in result[0]
        mock_hedge_service.get_hedge_history.assert_called_once_with(rel_id, mock_legal_entity_id)

    async def test_get_hedge_status_success(self, mock_hedge_service, mock_legal_entity_id):
        rel_id = uuid4()
        result = await get_hedge_status(
            relationship_id=rel_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert result["status"] == "active"
        assert result["is_effective"] is True
        mock_hedge_service.get_hedge_status.assert_called_once_with(rel_id, mock_legal_entity_id)

    async def test_get_hedge_status_not_found(self, mock_hedge_service, mock_legal_entity_id):
        mock_hedge_service.get_hedge_status.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_hedge_status(
                relationship_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_hedge_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestExportEndpoints:
    async def test_export_derivatives_csv(self, mock_hedge_service, mock_legal_entity_id):
        as_of = date.today()
        response = await export_derivatives(
            format="csv",
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_hedge_service.export_derivatives.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
            format="csv",
        )

    async def test_export_derivatives_excel(self, mock_hedge_service, mock_legal_entity_id):
        mock_hedge_service.export_derivatives.return_value = b"excel data"
        as_of = date.today()
        response = await export_derivatives(
            format="excel",
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    async def test_export_hedge_relationships_csv(self, mock_hedge_service, mock_legal_entity_id):
        as_of = date.today()
        response = await export_hedge_relationships(
            format="csv",
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_hedge_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"


# =============================================================================
# Tests for get_hedge_service dependency
# =============================================================================

@pytest.mark.asyncio
async def test_get_hedge_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_hedge_service(request)
    assert result == "service"
