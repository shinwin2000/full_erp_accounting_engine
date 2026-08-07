#!/usr/bin/env python3
"""
Module: fastapi_hedge_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk manajemen hedging (lindung nilai)
               sesuai PSAK 71 / IFRS 9: hedging relationship, derivative instruments,
               fair value hierarchy, effectiveness test, dan ineffectiveness.

Method Standards (ERP):
- create_derivative() / update_derivative() / delete_derivative() / get_derivative()
- create_hedge_relationship() / update_hedge_relationship() / delete_hedge_relationship()
- designate_hedge() / discontinue_hedge()
- test_effectiveness() / prospective_test() / retrospective_test()
- calculate_ineffectiveness() / recognize_ineffectiveness()
- record_fair_value() / get_fair_value_hierarchy()
- get_hedge_status() / get_hedge_history()
- get_hedge_effectiveness_report()
- audit_trail_hedge() / can_transition_hedge()
- register_hedge_event() / get_hedge_events()
- version_hedge()
"""

from __future__ import annotationsimport hashlibimport jsonimport loggingfrom datetime import UTC, date, datetimefrom decimal import ROUND_HALF_UP, Decimalfrom enum import Enumfrom typing import Anyfrom uuid import UUIDfrom fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, statusfrom fastapi.responses import Responsefrom pydantic import BaseModel, ConfigDict, Field, field_validator, model_validatorfrom adapters.primary_api.common.fastapi_auth_jwt_middleware import (    TokenPayload,    get_current_legal_entity,    get_current_user,    require_permission,)logger = logging.getLogger(__name__)

# ============================================================================
# IDEMPOTENCY MANAGER
# ============================================================================

class IdempotencyManager:
    """
    Simple in-memory idempotency manager untuk FastAPI endpoints.
    Menyimpan hasil operasi berdasarkan idempotency_key + method_name.
    TTL 24 jam.
    """

    def __init__(self):
        self._storage: dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now(UTC) - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now(UTC))


# Global instance
_idempotency_manager = IdempotencyManager()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class HedgeType(str, Enum):
    """Jenis hedging relationship."""

    FAIR_VALUE = "fair_value"  # Fair value hedge
    CASH_FLOW = "cash_flow"  # Cash flow hedge
    NET_INVESTMENT = "net_investment"  # Net investment hedge


class DerivativeType(str, Enum):
    """Jenis derivative instrument."""

    FORWARD = "forward"  # Forward contract
    FUTURES = "futures"  # Futures contract
    OPTION_CALL = "option_call"  # Call option
    OPTION_PUT = "option_put"  # Put option
    SWAP_IRS = "swap_irs"  # Interest rate swap
    SWAP_CCS = "swap_ccs"  # Cross currency swap
    SWAP_CDS = "swap_cds"  # Credit default swap
    WARRANT = "warrant"  # Warrant
    STRUCTURED = "structured"  # Structured product


class EffectivenessMethod(str, Enum):
    """Metode pengujian efektivitas."""

    DOLLAR_OFFSET = "dollar_offset"  # Dollar offset method
    REGRESSION = "regression"  # Regression analysis
    VAR = "var"  # Value at risk
    HYPOTHETICAL_DERIVATIVE = "hypothetical_derivative"


class FairValueLevel(str, Enum):
    """Level hierarki nilai wajar (IFRS 13)."""

    LEVEL_1 = "level_1"  # Quoted prices in active markets
    LEVEL_2 = "level_2"  # Inputs other than quoted prices
    LEVEL_3 = "level_3"  # Unobservable inputs


class HedgeStatus(str, Enum):
    """Status hedge relationship."""

    DRAFT = "draft"
    DESIGNATED = "designated"
    ACTIVE = "active"
    INEFFECTIVE = "ineffective"
    DISCONTINUED = "discontinued"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    LOCKED = "locked"
    ARCHIVED = "archived"


class DerivativeStatus(str, Enum):
    """Status derivative instrument."""

    ACTIVE = "active"
    EXERCISED = "exercised"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    CANCELLED = "cancelled"
    LOCKED = "locked"


# Default effectiveness thresholds (PSAK 71 / IFRS 9)
EFFECTIVENESS_THRESHOLD_LOWER = Decimal("0.80")  # 80%
EFFECTIVENESS_THRESHOLD_UPPER = Decimal("1.25")  # 125%


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class DerivativeCreateSchema(BaseModel):
    """Schema untuk membuat derivative instrument baru."""

    model_config = ConfigDict(from_attributes=True)

    instrument_code: str = Field(..., min_length=3, max_length=50, description="Kode instrument")
    instrument_name: str = Field(..., min_length=3, max_length=200, description="Nama instrument")
    derivative_type: DerivativeType = Field(..., description="Jenis derivative")
    counterparty_id: UUID = Field(..., description="ID counterparty")
    underlying_asset: str = Field(
        ..., max_length=100, description="Underlying asset (IDR/USD, OIL, INDEX)"
    )
    notional_amount: Decimal = Field(..., gt=0, decimal_places=2, description="Notional amount")
    currency_code: str = Field("IDR", min_length=3, max_length=3, description="Mata uang")
    contract_date: date = Field(..., description="Tanggal kontrak")
    settlement_date: date | None = Field(None, description="Tanggal settlement")
    maturity_date: date = Field(..., description="Tanggal jatuh tempo")
    strike_price: Decimal | None = Field(
        None, gt=0, decimal_places=4, description="Strike price (for options)"
    )
    premium_paid: Decimal = Field(0, ge=0, decimal_places=2, description="Premium paid/received")
    fair_value_at_initial: Decimal = Field(
        0, decimal_places=2, description="Fair value at initial recognition"
    )
    valuation_method: str = Field("MARK_TO_MARKET", description="Metode valuasi")
    counterparty_rating: str | None = Field(
        None, max_length=20, description="Credit rating counterparty"
    )
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @field_validator("instrument_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Instrument code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_dates(self) -> DerivativeCreateSchema:
        if self.settlement_date and self.settlement_date < self.contract_date:
            raise ValueError("Settlement date must be after contract date")
        if self.maturity_date < self.contract_date:
            raise ValueError("Maturity date must be after contract date")
        return self


class DerivativeUpdateSchema(BaseModel):
    """Schema untuk update derivative instrument."""

    model_config = ConfigDict(from_attributes=True)

    instrument_name: str | None = Field(None, min_length=3, max_length=200)
    fair_value_at_reporting: Decimal | None = Field(None, gt=0, decimal_places=2)
    valuation_method: str | None = None
    counterparty_rating: str | None = Field(None, max_length=20)
    notes: str | None = Field(None, max_length=500)
    status: DerivativeStatus | None = None


class DerivativeResponseSchema(BaseModel):
    """Response derivative instrument."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    instrument_code: str
    instrument_name: str
    derivative_type: DerivativeType
    counterparty_id: UUID
    counterparty_name: str | None = None
    underlying_asset: str
    notional_amount: Decimal
    currency_code: str
    contract_date: date
    settlement_date: date | None
    maturity_date: date
    strike_price: Decimal | None
    premium_paid: Decimal
    fair_value_at_initial: Decimal
    fair_value_at_reporting: Decimal
    valuation_method: str
    counterparty_rating: str | None
    is_designated_hedge: bool
    hedging_relationship_id: UUID | None = None
    status: DerivativeStatus
    is_locked: bool = False
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class HedgedItemSchema(BaseModel):
    """Schema untuk hedged item."""

    model_config = ConfigDict(from_attributes=True)

    item_type: str = Field(
        ..., description="forecast_transaction, firm_commitment, asset, liability"
    )
    item_id: UUID = Field(..., description="ID of the item")
    item_description: str = Field(..., max_length=500, description="Description")
    amount: Decimal = Field(..., gt=0, decimal_places=2, description="Amount hedged")
    currency_code: str = Field("IDR", min_length=3, max_length=3, description="Mata uang")
    maturity_date: date = Field(..., description="Expected maturity/occurrence date")
    risk_type: str = Field(
        ..., description="interest_rate, foreign_exchange, commodity_price, equity_price"
    )


class HedgeRelationshipCreateSchema(BaseModel):
    """Schema untuk membuat hedge relationship baru."""

    model_config = ConfigDict(from_attributes=True)

    hedge_type: HedgeType = Field(..., description="Jenis hedging")
    hedged_item: HedgedItemSchema = Field(..., description="Item yang dilindungi")
    derivative_id: UUID = Field(..., description="Derivative instrument yang digunakan")
    hedge_ratio: Decimal = Field(1, ge=0.8, le=1.25, decimal_places=4, description="Hedge ratio")
    designation_date: date = Field(default_factory=date.today, description="Tanggal designasi")
    effective_start_date: date = Field(
        default_factory=date.today, description="Tanggal mulai efektif"
    )
    effective_end_date: date | None = Field(None, description="Tanggal akhir efektif")
    risk_management_objective: str = Field(
        ..., max_length=500, description="Tujuan manajemen risiko"
    )
    risk_strategy_document: str | None = Field(
        None, max_length=500, description="Dokumen strategi risiko"
    )
    effectiveness_test_method: EffectivenessMethod = Field(
        EffectivenessMethod.DOLLAR_OFFSET, description="Metode uji efektivitas"
    )
    effectiveness_threshold_lower: Decimal = Field(
        EFFECTIVENESS_THRESHOLD_LOWER, ge=0, le=1, decimal_places=4
    )
    effectiveness_threshold_upper: Decimal = Field(
        EFFECTIVENESS_THRESHOLD_UPPER, ge=1, le=2, decimal_places=4
    )
    notes: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def validate_dates(self) -> HedgeRelationshipCreateSchema:
        if self.effective_end_date and self.effective_end_date <= self.effective_start_date:
            raise ValueError("Effective end date must be after effective start date")
        if self.designation_date > self.effective_start_date:
            raise ValueError("Designation date must be on or before effective start date")
        return self


class HedgeRelationshipUpdateSchema(BaseModel):
    """Schema untuk update hedge relationship."""

    model_config = ConfigDict(from_attributes=True)

    effective_end_date: date | None = None
    risk_management_objective: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=500)
    status: HedgeStatus | None = None


class HedgeRelationshipResponseSchema(BaseModel):
    """Response hedge relationship."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    hedge_type: HedgeType
    hedge_ratio: Decimal
    designation_date: date
    effective_start_date: date
    effective_end_date: date | None
    risk_management_objective: str
    risk_strategy_document: str | None
    effectiveness_test_method: EffectivenessMethod
    effectiveness_threshold_lower: Decimal
    effectiveness_threshold_upper: Decimal
    hedged_item_type: str
    hedged_item_id: UUID
    hedged_item_description: str
    hedged_item_amount: Decimal
    hedged_item_currency: str
    derivative_id: UUID
    derivative_code: str | None = None
    derivative_name: str | None = None
    status: HedgeStatus
    is_effective: bool | None = None
    ineffectiveness_ytd: Decimal = Decimal(0)
    is_locked: bool = False
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class EffectivenessTestCreateSchema(BaseModel):
    """Schema untuk melakukan effectiveness test."""

    model_config = ConfigDict(from_attributes=True)

    test_date: date = Field(..., description="Tanggal pengujian")
    test_method: EffectivenessMethod = Field(..., description="Metode pengujian")
    fair_value_change_derivative: Decimal = Field(
        ..., decimal_places=2, description="Perubahan nilai wajar derivative"
    )
    fair_value_change_hedged_item: Decimal = Field(
        ..., decimal_places=2, description="Perubahan nilai wajar hedged item"
    )
    notes: str | None = Field(None, max_length=500)

    @property
    def effectiveness_ratio(self) -> Decimal:
        """Rasio efektivitas = absolute(change_derivative) / absolute(change_hedged_item)"""
        if abs(self.fair_value_change_hedged_item) == 0:
            return Decimal(0)
        return (
            abs(self.fair_value_change_derivative) / abs(self.fair_value_change_hedged_item)
        ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    @property
    def is_effective(self) -> bool:
        """Cek apakah hedging efektif (80% - 125%)."""
        ratio = self.effectiveness_ratio
        return EFFECTIVENESS_THRESHOLD_LOWER <= ratio <= EFFECTIVENESS_THRESHOLD_UPPER

    @property
    def ineffectiveness_amount(self) -> Decimal:
        """Ineffectiveness amount = absolute difference."""
        derivative_change = abs(self.fair_value_change_derivative)
        hedged_change = abs(self.fair_value_change_hedged_item)
        if derivative_change > hedged_change:
            return (derivative_change - hedged_change).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        elif hedged_change > derivative_change:
            return (hedged_change - derivative_change).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return Decimal(0)


class EffectivenessTestResponseSchema(BaseModel):
    """Response effectiveness test."""

    model_config = ConfigDict(from_attributes=True)

    test_id: UUID
    hedge_relationship_id: UUID
    test_date: date
    test_method: EffectivenessMethod
    fair_value_change_derivative: Decimal
    fair_value_change_hedged_item: Decimal
    effectiveness_ratio: Decimal
    effectiveness_percent: float
    is_effective: bool
    ineffectiveness_amount: Decimal
    prospective_effective: bool | None = None
    prospective_ratio: Decimal | None = None
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None


class FairValueMeasurementSchema(BaseModel):
    """Schema untuk pengukuran nilai wajar."""

    model_config = ConfigDict(from_attributes=True)

    instrument_id: UUID = Field(..., description="ID instrument (derivative atau hedged item)")
    instrument_type: str = Field(..., description="derivative, hedged_item")
    measurement_date: date = Field(..., description="Tanggal pengukuran")
    fair_value: Decimal = Field(..., decimal_places=2, description="Nilai wajar")
    level_input: FairValueLevel = Field(..., description="Level hierarki nilai wajar")
    valuation_technique: str | None = Field(None, max_length=200, description="Teknik valuasi")
    unobservable_inputs: dict[str, Any] | None = Field(
        None, description="Input tidak terobservasi (level 3)"
    )
    valuer_name: str | None = Field(None, max_length=200, description="Nama penilai")
    valuation_report_path: str | None = Field(
        None, max_length=500, description="Path laporan valuasi"
    )
    notes: str | None = Field(None, max_length=500)


class FairValueMeasurementResponseSchema(BaseModel):
    """Response pengukuran nilai wajar."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    instrument_id: UUID
    instrument_code: str | None = None
    instrument_name: str | None = None
    instrument_type: str
    measurement_date: date
    fair_value: Decimal
    level_input: FairValueLevel
    valuation_technique: str | None
    unobservable_inputs: dict[str, Any] | None
    valuer_name: str | None
    valuation_report_path: str | None
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None


class HedgeIneffectivenessRecognitionSchema(BaseModel):
    """Schema untuk pengakuan ineffectiveness."""

    model_config = ConfigDict(from_attributes=True)

    period_end_date: date = Field(..., description="Tanggal akhir periode")
    post_to_ledger: bool = Field(True, description="Posting ke general ledger")
    notes: str | None = Field(None, max_length=500)


class HedgeIneffectivenessResponseSchema(BaseModel):
    """Response pengakuan ineffectiveness."""

    model_config = ConfigDict(from_attributes=True)

    recognition_id: UUID
    hedge_relationship_id: UUID
    period_start: date
    period_end: date
    ineffectiveness_amount: Decimal
    cumulative_ineffectiveness: Decimal
    journal_id: UUID | None = None
    status: str
    created_at: datetime
    created_by: UUID


class HedgeDashboardResponseSchema(BaseModel):
    """Response dashboard hedging."""

    model_config = ConfigDict(from_attributes=True)

    as_of_date: date
    total_derivatives: int
    active_derivatives: int
    total_hedge_relationships: int
    active_hedge_relationships: int
    effective_hedges: int
    ineffective_hedges: int
    total_notional_amount: Decimal
    total_fair_value: Decimal
    total_ineffectiveness_ytd: Decimal
    by_hedge_type: dict[str, dict[str, Any]]
    by_derivative_type: dict[str, int]
    generated_at: datetime


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_hedge_service(request: Request, ) -> Any:
    """Get Hedge Service instance."""

    from application.service_layer.service_hedge import HedgeService

    container = request.app.state.container
    return await container.resolve_async(HedgeService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/hedge", tags=["Hedge Accounting"])


# ----------------------------------------------------------------------------
# DERIVATIVE INSTRUMENTS CRUD
# ----------------------------------------------------------------------------


@router.post(
    "/derivatives",
    response_model=DerivativeResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create derivative instrument",
    operation_id="create_derivative",
)
async def create_derivative(
    request: DerivativeCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("hedge:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> DerivativeResponseSchema:
    """Create a new derivative instrument."""
    method_name = "create_derivative"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return DerivativeResponseSchema(**cached)

    try:
        result = await service.create_derivative(
            instrument_code=request.instrument_code,
            instrument_name=request.instrument_name,
            derivative_type=request.derivative_type.value,
            counterparty_id=request.counterparty_id,
            underlying_asset=request.underlying_asset,
            notional_amount=request.notional_amount,
            currency_code=request.currency_code,
            contract_date=request.contract_date,
            settlement_date=request.settlement_date,
            maturity_date=request.maturity_date,
            strike_price=request.strike_price,
            premium_paid=request.premium_paid,
            fair_value_at_initial=request.fair_value_at_initial,
            valuation_method=request.valuation_method,
            counterparty_rating=request.counterparty_rating,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        response = DerivativeResponseSchema(
            id=result.id,
            instrument_code=result.instrument_code,
            instrument_name=result.instrument_name,
            derivative_type=DerivativeType(result.derivative_type),
            counterparty_id=result.counterparty_id,
            counterparty_name=result.counterparty_name,
            underlying_asset=result.underlying_asset,
            notional_amount=result.notional_amount,
            currency_code=result.currency_code,
            contract_date=result.contract_date,
            settlement_date=result.settlement_date,
            maturity_date=result.maturity_date,
            strike_price=result.strike_price,
            premium_paid=result.premium_paid,
            fair_value_at_initial=result.fair_value_at_initial,
            fair_value_at_reporting=result.fair_value_at_reporting,
            valuation_method=result.valuation_method,
            counterparty_rating=result.counterparty_rating,
            is_designated_hedge=result.is_designated_hedge,
            hedging_relationship_id=result.hedging_relationship_id,
            status=DerivativeStatus(result.status),
            is_locked=result.is_locked,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create derivative: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/derivatives",
    response_model=list[DerivativeResponseSchema],
    summary="List derivative instruments",
    operation_id="list_derivatives",
)
async def list_derivatives(
    derivative_type: DerivativeType | None = Query(None, description="Filter by type"),
    status: DerivativeStatus | None = Query(None, description="Filter by status"),
    is_designated: bool | None = Query(None, description="Filter by designation status"),
    _permission: None = Depends(require_permission("hedge:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> list[DerivativeResponseSchema]:
    """List derivative instruments with filters."""
    try:
        derivatives = await service.list_derivatives(
            legal_entity_id=legal_entity_id,
            derivative_type=derivative_type.value if derivative_type else None,
            status=status.value if status else None,
            is_designated=is_designated,
        )

        return [
            DerivativeResponseSchema(
                id=d.id,
                instrument_code=d.instrument_code,
                instrument_name=d.instrument_name,
                derivative_type=DerivativeType(d.derivative_type),
                counterparty_id=d.counterparty_id,
                counterparty_name=d.counterparty_name,
                underlying_asset=d.underlying_asset,
                notional_amount=d.notional_amount,
                currency_code=d.currency_code,
                contract_date=d.contract_date,
                settlement_date=d.settlement_date,
                maturity_date=d.maturity_date,
                strike_price=d.strike_price,
                premium_paid=d.premium_paid,
                fair_value_at_initial=d.fair_value_at_initial,
                fair_value_at_reporting=d.fair_value_at_reporting,
                valuation_method=d.valuation_method,
                counterparty_rating=d.counterparty_rating,
                is_designated_hedge=d.is_designated_hedge,
                hedging_relationship_id=d.hedging_relationship_id,
                status=DerivativeStatus(d.status),
                is_locked=d.is_locked,
                notes=d.notes,
                created_at=d.created_at,
                updated_at=d.updated_at,
                created_by=d.created_by,
                created_by_name=d.created_by_name,
                version=d.version,
            )
            for d in derivatives
        ]
    except Exception as e:
        logger.exception("Failed to list derivatives: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/derivatives/{derivative_id}",
    response_model=DerivativeResponseSchema,
    summary="Get derivative instrument by ID",
    operation_id="get_derivative",
)
async def get_derivative(
    derivative_id: UUID,
    _permission: None = Depends(require_permission("hedge:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> DerivativeResponseSchema:
    """Get derivative instrument by ID."""
    try:
        derivative = await service.get_derivative_by_id(derivative_id, legal_entity_id)

        if not derivative:
            raise HTTPException(status_code=404, detail="Derivative instrument not found")

        return DerivativeResponseSchema(
            id=derivative.id,
            instrument_code=derivative.instrument_code,
            instrument_name=derivative.instrument_name,
            derivative_type=DerivativeType(derivative.derivative_type),
            counterparty_id=derivative.counterparty_id,
            counterparty_name=derivative.counterparty_name,
            underlying_asset=derivative.underlying_asset,
            notional_amount=derivative.notional_amount,
            currency_code=derivative.currency_code,
            contract_date=derivative.contract_date,
            settlement_date=derivative.settlement_date,
            maturity_date=derivative.maturity_date,
            strike_price=derivative.strike_price,
            premium_paid=derivative.premium_paid,
            fair_value_at_initial=derivative.fair_value_at_initial,
            fair_value_at_reporting=derivative.fair_value_at_reporting,
            valuation_method=derivative.valuation_method,
            counterparty_rating=derivative.counterparty_rating,
            is_designated_hedge=derivative.is_designated_hedge,
            hedging_relationship_id=derivative.hedging_relationship_id,
            status=DerivativeStatus(derivative.status),
            is_locked=derivative.is_locked,
            notes=derivative.notes,
            created_at=derivative.created_at,
            updated_at=derivative.updated_at,
            created_by=derivative.created_by,
            created_by_name=derivative.created_by_name,
            version=derivative.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get derivative: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/derivatives/{derivative_id}",
    response_model=DerivativeResponseSchema,
    summary="Update derivative instrument",
    operation_id="update_derivative",
)
async def update_derivative(
    derivative_id: UUID,
    request: DerivativeUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("hedge:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> DerivativeResponseSchema:
    """Update derivative instrument information."""
    method_name = "update_derivative"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return DerivativeResponseSchema(**cached)

    try:
        result = await service.update_derivative(
            derivative_id=derivative_id,
            legal_entity_id=legal_entity_id,
            instrument_name=request.instrument_name,
            fair_value_at_reporting=request.fair_value_at_reporting,
            valuation_method=request.valuation_method,
            counterparty_rating=request.counterparty_rating,
            notes=request.notes,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Derivative instrument not found")

        response = DerivativeResponseSchema(
            id=result.id,
            instrument_code=result.instrument_code,
            instrument_name=result.instrument_name,
            derivative_type=DerivativeType(result.derivative_type),
            counterparty_id=result.counterparty_id,
            counterparty_name=result.counterparty_name,
            underlying_asset=result.underlying_asset,
            notional_amount=result.notional_amount,
            currency_code=result.currency_code,
            contract_date=result.contract_date,
            settlement_date=result.settlement_date,
            maturity_date=result.maturity_date,
            strike_price=result.strike_price,
            premium_paid=result.premium_paid,
            fair_value_at_initial=result.fair_value_at_initial,
            fair_value_at_reporting=result.fair_value_at_reporting,
            valuation_method=result.valuation_method,
            counterparty_rating=result.counterparty_rating,
            is_designated_hedge=result.is_designated_hedge,
            hedging_relationship_id=result.hedging_relationship_id,
            status=DerivativeStatus(result.status),
            is_locked=result.is_locked,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update derivative: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/derivatives/{derivative_id}",
    response_model=dict[str, Any],
    summary="Terminate derivative instrument",
    operation_id="terminate_derivative",
)
async def terminate_derivative(
    derivative_id: UUID,
    reason: str = Query("", description="Termination reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("hedge:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> dict[str, Any]:
    """Terminate a derivative instrument."""
    method_name = "terminate_derivative"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        result = await service.terminate_derivative(
            derivative_id=derivative_id,
            legal_entity_id=legal_entity_id,
            reason=reason,
            terminated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Derivative instrument not found")

        response = {
            "derivative_id": str(derivative_id),
            "instrument_code": result.instrument_code,
            "status": result.status,
            "message": "Derivative instrument terminated",
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to terminate derivative: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# HEDGE RELATIONSHIP CRUD
# ----------------------------------------------------------------------------


@router.post(
    "/relationships",
    response_model=HedgeRelationshipResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create hedge relationship",
    operation_id="create_hedge_relationship",
)
async def create_hedge_relationship(
    request: HedgeRelationshipCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("hedge:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> HedgeRelationshipResponseSchema:
    """Create a new hedge relationship."""
    method_name = "create_hedge_relationship"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return HedgeRelationshipResponseSchema(**cached)

    try:
        result = await service.create_hedge_relationship(
            hedge_type=request.hedge_type.value,
            hedged_item_type=request.hedged_item.item_type,
            hedged_item_id=request.hedged_item.item_id,
            hedged_item_description=request.hedged_item.item_description,
            hedged_item_amount=request.hedged_item.amount,
            hedged_item_currency=request.hedged_item.currency_code,
            hedged_item_maturity=request.hedged_item.maturity_date,
            hedged_item_risk=request.hedged_item.risk_type,
            derivative_id=request.derivative_id,
            hedge_ratio=request.hedge_ratio,
            designation_date=request.designation_date,
            effective_start_date=request.effective_start_date,
            effective_end_date=request.effective_end_date,
            risk_management_objective=request.risk_management_objective,
            risk_strategy_document=request.risk_strategy_document,
            effectiveness_test_method=request.effectiveness_test_method.value,
            effectiveness_threshold_lower=request.effectiveness_threshold_lower,
            effectiveness_threshold_upper=request.effectiveness_threshold_upper,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        response = HedgeRelationshipResponseSchema(
            id=result.id,
            hedge_type=HedgeType(result.hedge_type),
            hedge_ratio=result.hedge_ratio,
            designation_date=result.designation_date,
            effective_start_date=result.effective_start_date,
            effective_end_date=result.effective_end_date,
            risk_management_objective=result.risk_management_objective,
            risk_strategy_document=result.risk_strategy_document,
            effectiveness_test_method=EffectivenessMethod(result.effectiveness_test_method),
            effectiveness_threshold_lower=result.effectiveness_threshold_lower,
            effectiveness_threshold_upper=result.effectiveness_threshold_upper,
            hedged_item_type=result.hedged_item_type,
            hedged_item_id=result.hedged_item_id,
            hedged_item_description=result.hedged_item_description,
            hedged_item_amount=result.hedged_item_amount,
            hedged_item_currency=result.hedged_item_currency,
            derivative_id=result.derivative_id,
            derivative_code=result.derivative_code,
            derivative_name=result.derivative_name,
            status=HedgeStatus(result.status),
            is_effective=result.is_effective,
            ineffectiveness_ytd=result.ineffectiveness_ytd,
            is_locked=result.is_locked,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create hedge relationship: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/relationships",
    response_model=list[HedgeRelationshipResponseSchema],
    summary="List hedge relationships",
    operation_id="list_hedge_relationships",
)
async def list_hedge_relationships(
    hedge_type: HedgeType | None = Query(None, description="Filter by hedge type"),
    status: HedgeStatus | None = Query(None, description="Filter by status"),
    derivative_id: UUID | None = Query(None, description="Filter by derivative"),
    _permission: None = Depends(require_permission("hedge:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> list[HedgeRelationshipResponseSchema]:
    """List hedge relationships with filters."""
    try:
        relationships = await service.list_hedge_relationships(
            legal_entity_id=legal_entity_id,
            hedge_type=hedge_type.value if hedge_type else None,
            status=status.value if status else None,
            derivative_id=derivative_id,
        )

        return [
            HedgeRelationshipResponseSchema(
                id=r.id,
                hedge_type=HedgeType(r.hedge_type),
                hedge_ratio=r.hedge_ratio,
                designation_date=r.designation_date,
                effective_start_date=r.effective_start_date,
                effective_end_date=r.effective_end_date,
                risk_management_objective=r.risk_management_objective,
                risk_strategy_document=r.risk_strategy_document,
                effectiveness_test_method=EffectivenessMethod(r.effectiveness_test_method),
                effectiveness_threshold_lower=r.effectiveness_threshold_lower,
                effectiveness_threshold_upper=r.effectiveness_threshold_upper,
                hedged_item_type=r.hedged_item_type,
                hedged_item_id=r.hedged_item_id,
                hedged_item_description=r.hedged_item_description,
                hedged_item_amount=r.hedged_item_amount,
                hedged_item_currency=r.hedged_item_currency,
                derivative_id=r.derivative_id,
                derivative_code=r.derivative_code,
                derivative_name=r.derivative_name,
                status=HedgeStatus(r.status),
                is_effective=r.is_effective,
                ineffectiveness_ytd=r.ineffectiveness_ytd,
                is_locked=r.is_locked,
                notes=r.notes,
                created_at=r.created_at,
                updated_at=r.updated_at,
                created_by=r.created_by,
                created_by_name=r.created_by_name,
                version=r.version,
            )
            for r in relationships
        ]
    except Exception as e:
        logger.exception("Failed to list hedge relationships: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/relationships/{relationship_id}",
    response_model=HedgeRelationshipResponseSchema,
    summary="Get hedge relationship by ID",
    operation_id="get_hedge_relationship",
)
async def get_hedge_relationship(
    relationship_id: UUID,
    _permission: None = Depends(require_permission("hedge:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> HedgeRelationshipResponseSchema:
    """Get hedge relationship by ID."""
    try:
        relationship = await service.get_hedge_relationship_by_id(relationship_id, legal_entity_id)

        if not relationship:
            raise HTTPException(status_code=404, detail="Hedge relationship not found")

        return HedgeRelationshipResponseSchema(
            id=relationship.id,
            hedge_type=HedgeType(relationship.hedge_type),
            hedge_ratio=relationship.hedge_ratio,
            designation_date=relationship.designation_date,
            effective_start_date=relationship.effective_start_date,
            effective_end_date=relationship.effective_end_date,
            risk_management_objective=relationship.risk_management_objective,
            risk_strategy_document=relationship.risk_strategy_document,
            effectiveness_test_method=EffectivenessMethod(relationship.effectiveness_test_method),
            effectiveness_threshold_lower=relationship.effectiveness_threshold_lower,
            effectiveness_threshold_upper=relationship.effectiveness_threshold_upper,
            hedged_item_type=relationship.hedged_item_type,
            hedged_item_id=relationship.hedged_item_id,
            hedged_item_description=relationship.hedged_item_description,
            hedged_item_amount=relationship.hedged_item_amount,
            hedged_item_currency=relationship.hedged_item_currency,
            derivative_id=relationship.derivative_id,
            derivative_code=relationship.derivative_code,
            derivative_name=relationship.derivative_name,
            status=HedgeStatus(relationship.status),
            is_effective=relationship.is_effective,
            ineffectiveness_ytd=relationship.ineffectiveness_ytd,
            is_locked=relationship.is_locked,
            notes=relationship.notes,
            created_at=relationship.created_at,
            updated_at=relationship.updated_at,
            created_by=relationship.created_by,
            created_by_name=relationship.created_by_name,
            version=relationship.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get hedge relationship: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/relationships/{relationship_id}",
    response_model=HedgeRelationshipResponseSchema,
    summary="Update hedge relationship",
    operation_id="update_hedge_relationship",
)
async def update_hedge_relationship(
    relationship_id: UUID,
    request: HedgeRelationshipUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("hedge:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> HedgeRelationshipResponseSchema:
    """Update hedge relationship information."""
    method_name = "update_hedge_relationship"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return HedgeRelationshipResponseSchema(**cached)

    try:
        result = await service.update_hedge_relationship(
            relationship_id=relationship_id,
            legal_entity_id=legal_entity_id,
            effective_end_date=request.effective_end_date,
            risk_management_objective=request.risk_management_objective,
            notes=request.notes,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Hedge relationship not found")

        response = HedgeRelationshipResponseSchema(
            id=result.id,
            hedge_type=HedgeType(result.hedge_type),
            hedge_ratio=result.hedge_ratio,
            designation_date=result.designation_date,
            effective_start_date=result.effective_start_date,
            effective_end_date=result.effective_end_date,
            risk_management_objective=result.risk_management_objective,
            risk_strategy_document=result.risk_strategy_document,
            effectiveness_test_method=EffectivenessMethod(result.effectiveness_test_method),
            effectiveness_threshold_lower=result.effectiveness_threshold_lower,
            effectiveness_threshold_upper=result.effectiveness_threshold_upper,
            hedged_item_type=result.hedged_item_type,
            hedged_item_id=result.hedged_item_id,
            hedged_item_description=result.hedged_item_description,
            hedged_item_amount=result.hedged_item_amount,
            hedged_item_currency=result.hedged_item_currency,
            derivative_id=result.derivative_id,
            derivative_code=result.derivative_code,
            derivative_name=result.derivative_name,
            status=HedgeStatus(result.status),
            is_effective=result.is_effective,
            ineffectiveness_ytd=result.ineffectiveness_ytd,
            is_locked=result.is_locked,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update hedge relationship: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/relationships/{relationship_id}/designate",
    response_model=HedgeRelationshipResponseSchema,
    summary="Designate hedge relationship",
    operation_id="designate_hedge",
)
async def designate_hedge(
    relationship_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("hedge:designate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> HedgeRelationshipResponseSchema:
    """Designate a hedge relationship (start hedge accounting)."""
    method_name = "designate_hedge"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return HedgeRelationshipResponseSchema(**cached)

    try:
        result = await service.designate_hedge(
            relationship_id=relationship_id,
            legal_entity_id=legal_entity_id,
            designated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Hedge relationship not found or cannot be designated"
            )

        response = HedgeRelationshipResponseSchema(
            id=result.id,
            hedge_type=HedgeType(result.hedge_type),
            hedge_ratio=result.hedge_ratio,
            designation_date=result.designation_date,
            effective_start_date=result.effective_start_date,
            effective_end_date=result.effective_end_date,
            risk_management_objective=result.risk_management_objective,
            risk_strategy_document=result.risk_strategy_document,
            effectiveness_test_method=EffectivenessMethod(result.effectiveness_test_method),
            effectiveness_threshold_lower=result.effectiveness_threshold_lower,
            effectiveness_threshold_upper=result.effectiveness_threshold_upper,
            hedged_item_type=result.hedged_item_type,
            hedged_item_id=result.hedged_item_id,
            hedged_item_description=result.hedged_item_description,
            hedged_item_amount=result.hedged_item_amount,
            hedged_item_currency=result.hedged_item_currency,
            derivative_id=result.derivative_id,
            derivative_code=result.derivative_code,
            derivative_name=result.derivative_name,
            status=HedgeStatus(result.status),
            is_effective=result.is_effective,
            ineffectiveness_ytd=result.ineffectiveness_ytd,
            is_locked=result.is_locked,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to designate hedge: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/relationships/{relationship_id}/discontinue",
    response_model=HedgeRelationshipResponseSchema,
    summary="Discontinue hedge relationship",
    operation_id="discontinue_hedge",
)
async def discontinue_hedge(
    relationship_id: UUID,
    discontinue_date: date = Query(..., description="Date of discontinuation"),
    reason: str = Query(..., min_length=5, description="Reason for discontinuation"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("hedge:designate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> HedgeRelationshipResponseSchema:
    """Discontinue a hedge relationship (stop hedge accounting)."""
    method_name = "discontinue_hedge"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return HedgeRelationshipResponseSchema(**cached)

    try:
        result = await service.discontinue_hedge(
            relationship_id=relationship_id,
            legal_entity_id=legal_entity_id,
            discontinue_date=discontinue_date,
            reason=reason,
            discontinued_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Hedge relationship not found or cannot be discontinued"
            )

        response = HedgeRelationshipResponseSchema(
            id=result.id,
            hedge_type=HedgeType(result.hedge_type),
            hedge_ratio=result.hedge_ratio,
            designation_date=result.designation_date,
            effective_start_date=result.effective_start_date,
            effective_end_date=result.effective_end_date,
            risk_management_objective=result.risk_management_objective,
            risk_strategy_document=result.risk_strategy_document,
            effectiveness_test_method=EffectivenessMethod(result.effectiveness_test_method),
            effectiveness_threshold_lower=result.effectiveness_threshold_lower,
            effectiveness_threshold_upper=result.effectiveness_threshold_upper,
            hedged_item_type=result.hedged_item_type,
            hedged_item_id=result.hedged_item_id,
            hedged_item_description=result.hedged_item_description,
            hedged_item_amount=result.hedged_item_amount,
            hedged_item_currency=result.hedged_item_currency,
            derivative_id=result.derivative_id,
            derivative_code=result.derivative_code,
            derivative_name=result.derivative_name,
            status=HedgeStatus(result.status),
            is_effective=result.is_effective,
            ineffectiveness_ytd=result.ineffectiveness_ytd,
            is_locked=result.is_locked,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to discontinue hedge: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EFFECTIVENESS TEST
# ----------------------------------------------------------------------------


@router.post(
    "/relationships/{relationship_id}/effectiveness-test",
    response_model=EffectivenessTestResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Run hedge effectiveness test",
    operation_id="run_effectiveness_test",
)
async def run_effectiveness_test(
    relationship_id: UUID,
    request: EffectivenessTestCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("hedge:test")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> EffectivenessTestResponseSchema:
    """Run hedge effectiveness test."""
    method_name = "run_effectiveness_test"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return EffectivenessTestResponseSchema(**cached)

    try:
        result = await service.run_effectiveness_test(
            hedge_relationship_id=relationship_id,
            legal_entity_id=legal_entity_id,
            test_date=request.test_date,
            test_method=request.test_method.value,
            fair_value_change_derivative=request.fair_value_change_derivative,
            fair_value_change_hedged_item=request.fair_value_change_hedged_item,
            notes=request.notes,
            performed_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Hedge relationship not found")

        response = EffectivenessTestResponseSchema(
            test_id=result.test_id,
            hedge_relationship_id=relationship_id,
            test_date=request.test_date,
            test_method=EffectivenessMethod(result.test_method),
            fair_value_change_derivative=result.fair_value_change_derivative,
            fair_value_change_hedged_item=result.fair_value_change_hedged_item,
            effectiveness_ratio=result.effectiveness_ratio,
            effectiveness_percent=result.effectiveness_percent,
            is_effective=result.is_effective,
            ineffectiveness_amount=result.ineffectiveness_amount,
            prospective_effective=result.prospective_effective,
            prospective_ratio=result.prospective_ratio,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to run effectiveness test: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/relationships/{relationship_id}/effectiveness-tests",
    response_model=list[EffectivenessTestResponseSchema],
    summary="List effectiveness tests",
    operation_id="list_effectiveness_tests",
)
async def list_effectiveness_tests(
    relationship_id: UUID,
    _permission: None = Depends(require_permission("hedge:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> list[EffectivenessTestResponseSchema]:
    """List all effectiveness tests for a hedge relationship."""
    try:
        tests = await service.list_effectiveness_tests(relationship_id, legal_entity_id)

        return [
            EffectivenessTestResponseSchema(
                test_id=t.test_id,
                hedge_relationship_id=relationship_id,
                test_date=t.test_date,
                test_method=EffectivenessMethod(t.test_method),
                fair_value_change_derivative=t.fair_value_change_derivative,
                fair_value_change_hedged_item=t.fair_value_change_hedged_item,
                effectiveness_ratio=t.effectiveness_ratio,
                effectiveness_percent=t.effectiveness_percent,
                is_effective=t.is_effective,
                ineffectiveness_amount=t.ineffectiveness_amount,
                prospective_effective=t.prospective_effective,
                prospective_ratio=t.prospective_ratio,
                notes=t.notes,
                created_at=t.created_at,
                created_by=t.created_by,
                created_by_name=t.created_by_name,
            )
            for t in tests
        ]
    except Exception as e:
        logger.exception("Failed to list effectiveness tests: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# FAIR VALUE HIERARCHY
# ----------------------------------------------------------------------------


@router.post(
    "/fair-value",
    response_model=FairValueMeasurementResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record fair value measurement",
    operation_id="record_fair_value",
)
async def record_fair_value(
    request: FairValueMeasurementSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("hedge:fair_value")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> FairValueMeasurementResponseSchema:
    """Record fair value measurement for an instrument."""
    method_name = "record_fair_value"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return FairValueMeasurementResponseSchema(**cached)

    try:
        result = await service.record_fair_value_measurement(
            instrument_id=request.instrument_id,
            instrument_type=request.instrument_type,
            legal_entity_id=legal_entity_id,
            measurement_date=request.measurement_date,
            fair_value=request.fair_value,
            level_input=request.level_input.value,
            valuation_technique=request.valuation_technique,
            unobservable_inputs=request.unobservable_inputs,
            valuer_name=request.valuer_name,
            valuation_report_path=request.valuation_report_path,
            notes=request.notes,
            recorded_by=current_user.user_id,
        )

        response = FairValueMeasurementResponseSchema(
            id=result.id,
            instrument_id=result.instrument_id,
            instrument_code=result.instrument_code,
            instrument_name=result.instrument_name,
            instrument_type=result.instrument_type,
            measurement_date=request.measurement_date,
            fair_value=result.fair_value,
            level_input=FairValueLevel(result.level_input),
            valuation_technique=result.valuation_technique,
            unobservable_inputs=result.unobservable_inputs,
            valuer_name=result.valuer_name,
            valuation_report_path=result.valuation_report_path,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to record fair value: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/fair-value/{instrument_id}",
    response_model=list[FairValueMeasurementResponseSchema],
    summary="Get fair value history",
    operation_id="get_fair_value_history",
)
async def get_fair_value_history(
    instrument_id: UUID,
    instrument_type: str = Query(..., description="derivative, hedged_item"),
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    _permission: None = Depends(require_permission("hedge:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> list[FairValueMeasurementResponseSchema]:
    """Get fair value measurement history for an instrument."""
    try:
        measurements = await service.get_fair_value_history(
            instrument_id=instrument_id,
            instrument_type=instrument_type,
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
        )

        return [
            FairValueMeasurementResponseSchema(
                id=m.id,
                instrument_id=m.instrument_id,
                instrument_code=m.instrument_code,
                instrument_name=m.instrument_name,
                instrument_type=m.instrument_type,
                measurement_date=m.measurement_date,
                fair_value=m.fair_value,
                level_input=FairValueLevel(m.level_input),
                valuation_technique=m.valuation_technique,
                unobservable_inputs=m.unobservable_inputs,
                valuer_name=m.valuer_name,
                valuation_report_path=m.valuation_report_path,
                notes=m.notes,
                created_at=m.created_at,
                created_by=m.created_by,
                created_by_name=m.created_by_name,
            )
            for m in measurements
        ]
    except Exception as e:
        logger.exception("Failed to get fair value history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# INEFFECTIVENESS RECOGNITION
# ----------------------------------------------------------------------------


@router.post(
    "/ineffectiveness/recognize",
    response_model=list[HedgeIneffectivenessResponseSchema],
    status_code=status.HTTP_201_CREATED,
    summary="Recognize hedge ineffectiveness",
    operation_id="recognize_ineffectiveness",
)
async def recognize_ineffectiveness(
    request: HedgeIneffectivenessRecognitionSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("hedge:ineffectiveness")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> list[HedgeIneffectivenessResponseSchema]:
    """Recognize hedge ineffectiveness for the period."""
    method_name = "recognize_ineffectiveness"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            # cached is list of dicts
            return [HedgeIneffectivenessResponseSchema(**item) for item in cached]

    try:
        results = await service.recognize_ineffectiveness(
            legal_entity_id=legal_entity_id,
            period_end_date=request.period_end_date,
            post_to_ledger=request.post_to_ledger,
            notes=request.notes,
            recognized_by=current_user.user_id,
        )

        response = [
            HedgeIneffectivenessResponseSchema(
                recognition_id=r.id,
                hedge_relationship_id=r.hedge_relationship_id,
                period_start=r.period_start,
                period_end=r.period_end,
                ineffectiveness_amount=r.ineffectiveness_amount,
                cumulative_ineffectiveness=r.cumulative_ineffectiveness,
                journal_id=r.journal_id,
                status=r.status,
                created_at=r.created_at,
                created_by=r.created_by,
            )
            for r in results
        ]

        if idempotency_key:
            # Convert list to dict for caching (wrap in dict)
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"items": [r.model_dump() for r in response]}
            )

        return response

    except Exception as e:
        logger.exception("Failed to recognize ineffectiveness: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# HEDGE DASHBOARD
# ----------------------------------------------------------------------------


@router.get(
    "/dashboard",
    response_model=HedgeDashboardResponseSchema,
    summary="Get hedge dashboard",
    operation_id="get_hedge_dashboard",
)
async def get_hedge_dashboard(
    as_of_date: date = Query(..., description="As of date"),
    _permission: None = Depends(require_permission("hedge:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> HedgeDashboardResponseSchema:
    """Get hedge accounting dashboard with key metrics."""
    try:
        dashboard = await service.get_hedge_dashboard(legal_entity_id, as_of_date)

        return HedgeDashboardResponseSchema(
            as_of_date=as_of_date,
            total_derivatives=dashboard.total_derivatives,
            active_derivatives=dashboard.active_derivatives,
            total_hedge_relationships=dashboard.total_hedge_relationships,
            active_hedge_relationships=dashboard.active_hedge_relationships,
            effective_hedges=dashboard.effective_hedges,
            ineffective_hedges=dashboard.ineffective_hedges,
            total_notional_amount=dashboard.total_notional_amount,
            total_fair_value=dashboard.total_fair_value,
            total_ineffectiveness_ytd=dashboard.total_ineffectiveness_ytd,
            by_hedge_type=dashboard.by_hedge_type,
            by_derivative_type=dashboard.by_derivative_type,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception("Failed to get hedge dashboard: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# HEDGE HISTORY & STATUS
# ----------------------------------------------------------------------------


@router.get(
    "/relationships/{relationship_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get hedge relationship history",
    operation_id="get_hedge_history",
)
async def get_hedge_history(
    relationship_id: UUID,
    _permission: None = Depends(require_permission("hedge:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> list[dict[str, Any]]:
    """Get hedge relationship change history (audit trail)."""
    try:
        history = await service.get_hedge_history(relationship_id, legal_entity_id)

        return [
            {
                "timestamp": h.timestamp.isoformat(),
                "action": h.action,
                "field": h.field,
                "old_value": h.old_value,
                "new_value": h.new_value,
                "actor_id": str(h.actor_id),
                "actor_name": h.actor_name,
                "reason": h.reason,
            }
            for h in history
        ]
    except Exception as e:
        logger.exception("Failed to get hedge history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/relationships/{relationship_id}/status",
    response_model=dict[str, Any],
    summary="Get hedge relationship status",
    operation_id="get_hedge_status",
)
async def get_hedge_status(
    relationship_id: UUID,
    _permission: None = Depends(require_permission("hedge:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> dict[str, Any]:
    """Get detailed hedge relationship status."""
    try:
        status_info = await service.get_hedge_status(relationship_id, legal_entity_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="Hedge relationship not found")

        return {
            "relationship_id": str(relationship_id),
            "hedge_type": status_info.hedge_type,
            "status": status_info.status,
            "is_effective": status_info.is_effective,
            "can_test": status_info.can_test,
            "can_discontinue": status_info.can_discontinue,
            "can_edit": status_info.can_edit,
            "is_locked": status_info.is_locked,
            "effectiveness_ratio": float(status_info.effectiveness_ratio)
            if status_info.effectiveness_ratio
            else None,
            "ineffectiveness_ytd": float(status_info.ineffectiveness_ytd),
            "last_test_date": status_info.last_test_date.isoformat()
            if status_info.last_test_date
            else None,
            "next_test_date": status_info.next_test_date.isoformat()
            if status_info.next_test_date
            else None,
            "cumulative_ineffectiveness": float(status_info.cumulative_ineffectiveness),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get hedge status: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT
# ----------------------------------------------------------------------------


@router.get(
    "/export/derivatives",
    summary="Export derivatives",
    operation_id="export_derivatives",
)
async def export_derivatives(
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    as_of_date: date = Query(..., description="As of date"),
    _permission: None = Depends(require_permission("hedge:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> Response:
    """Export derivative instruments to CSV or Excel."""
    try:
        data = await service.export_derivatives(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            format=format,
        )

        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"derivatives_{legal_entity_id}_{as_of_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export derivatives: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/export/hedge-relationships",
    summary="Export hedge relationships",
    operation_id="export_hedge_relationships",
)
async def export_hedge_relationships(
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    as_of_date: date = Query(..., description="As of date"),
    _permission: None = Depends(require_permission("hedge:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_hedge_service),
) -> Response:
    """Export hedge relationships to CSV or Excel."""
    try:
        data = await service.export_hedge_relationships(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            format=format,
        )

        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"hedge_relationships_{legal_entity_id}_{as_of_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export hedge relationships: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
