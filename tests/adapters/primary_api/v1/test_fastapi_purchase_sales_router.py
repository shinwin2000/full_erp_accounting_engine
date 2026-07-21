# tests/adapters/primary_api/v1/test_fastapi_purchase_sales_router.py
"""
Comprehensive tests for fastapi_purchase_sales_router.py
Covers positive/negative paths, idempotency, workflow, and edge cases.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import Response

from adapters.primary_api.v1.fastapi_purchase_sales_router import (
    DeliveryOrderCreateSchema,
    DeliveryOrderResponseSchema,
    DeliveryOrderStatus,
    DOLineSchema,
    GoodsReceiptCreateSchema,
    GoodsReceiptResponseSchema,
    GoodsReceiptStatus,
    GRNLineSchema,
    IdempotencyManager,
    Incoterm,
    OrderType,
    POLineSchema,
    PurchaseOrderCreateSchema,
    PurchaseOrderResponseSchema,
    PurchaseOrderStatus,
    PurchaseOrderUpdateSchema,
    SalesOrderCreateSchema,
    SalesOrderResponseSchema,
    SalesOrderStatus,
    SalesOrderUpdateSchema,
    SOLineSchema,
    approve_purchase_order,
    approve_sales_order,
    cancel_goods_receipt,
    cancel_purchase_order,
    cancel_sales_order,
    close_purchase_order,
    close_sales_order,
    confirm_delivery_order,
    confirm_goods_receipt,
    create_delivery_order,
    create_goods_receipt,
    create_purchase_order,
    create_sales_order,
    export_purchase_orders,
    export_sales_orders,
    get_purchase_order,
    get_purchase_order_by_number,
    get_purchase_order_history,
    get_purchase_order_status,
    get_purchase_sales_service,
    get_sales_order,
    get_sales_order_by_number,
    get_sales_order_history,
    get_sales_order_status,
    list_purchase_orders,
    list_sales_orders,
    reject_purchase_order,
    reject_sales_order,
    ship_delivery_order,
    submit_purchase_order,
    submit_sales_order,
    update_purchase_order,
    update_sales_order,
)

# ---------- Fixtures ----------

@pytest.fixture
def mock_service():
    """Mock PurchaseSalesService with async methods."""
    service = AsyncMock()

    # Default PO result
    default_po = MagicMock(
        id=uuid4(),
        po_number="PO-001",
        po_date=date.today(),
        supplier_id=uuid4(),
        supplier_name="Supplier A",
        supplier_code="SUP001",
        total_amount=Decimal("1000.00"),
        received_amount=Decimal("0.00"),
        invoiced_amount=Decimal("0.00"),
        paid_amount=Decimal("0.00"),
        outstanding_amount=Decimal("1000.00"),
        status="draft",
        expected_delivery_date=date.today() + timedelta(days=30),
        actual_delivery_date=None,
        delivery_term_days=30,
        payment_term_days=45,
        incoterm="FOB",
        order_type="standard",
        reference_number=None,
        notes=None,
        lines=[],
        created_at=datetime.now(),
        updated_at=datetime.now(),
        created_by=uuid4(),
        created_by_name="admin",
        approved_at=None,
        approved_by=None,
        approved_by_name=None,
        rejected_at=None,
        rejected_by=None,
        rejection_reason=None,
        cancelled_at=None,
        cancelled_by=None,
        closed_at=None,
        is_locked=False,
        version=1,
    )

    # Default SO result
    default_so = MagicMock(
        id=uuid4(),
        so_number="SO-001",
        so_date=date.today(),
        customer_id=uuid4(),
        customer_name="Customer A",
        customer_code="CUST001",
        total_amount=Decimal("1000.00"),
        shipped_amount=Decimal("0.00"),
        invoiced_amount=Decimal("0.00"),
        paid_amount=Decimal("0.00"),
        outstanding_amount=Decimal("1000.00"),
        status="draft",
        expected_ship_date=date.today() + timedelta(days=30),
        actual_ship_date=None,
        shipping_term_days=30,
        payment_term_days=45,
        incoterm="FOB",
        order_type="standard",
        reference_number=None,
        notes=None,
        lines=[],
        created_at=datetime.now(),
        updated_at=datetime.now(),
        created_by=uuid4(),
        created_by_name="admin",
        approved_at=None,
        approved_by=None,
        approved_by_name=None,
        rejected_at=None,
        rejected_by=None,
        rejection_reason=None,
        cancelled_at=None,
        cancelled_by=None,
        closed_at=None,
        is_locked=False,
        version=1,
    )

    # Default GRN result
    default_grn = MagicMock(
        id=uuid4(),
        grn_number="GRN-001",
        grn_date=date.today(),
        purchase_order_id=uuid4(),
        po_number="PO-001",
        supplier_id=uuid4(),
        supplier_name="Supplier A",
        warehouse_id=uuid4(),
        warehouse_name="Warehouse A",
        status="draft",
        lines=[],
        notes=None,
        created_at=datetime.now(),
        created_by=uuid4(),
        created_by_name="admin",
        confirmed_at=None,
        confirmed_by=None,
        posted_at=None,
        version=1,
    )

    # Default DO result
    default_do = MagicMock(
        id=uuid4(),
        do_number="DO-001",
        do_date=date.today(),
        sales_order_id=uuid4(),
        so_number="SO-001",
        customer_id=uuid4(),
        customer_name="Customer A",
        warehouse_id=uuid4(),
        warehouse_name="Warehouse A",
        shipping_address="Jl. Test",
        tracking_number=None,
        carrier=None,
        status="draft",
        lines=[],
        notes=None,
        created_at=datetime.now(),
        created_by=uuid4(),
        created_by_name="admin",
        confirmed_at=None,
        confirmed_by=None,
        shipped_at=None,
        delivered_at=None,
        version=1,
    )

    # Set return values for service methods
    service.create_purchase_order = AsyncMock(return_value=default_po)
    service.get_purchase_order_by_id = AsyncMock(return_value=default_po)
    service.get_purchase_order_by_number = AsyncMock(return_value=default_po)
    service.list_purchase_orders = AsyncMock(return_value=MagicMock(items=[default_po], total=1))
    service.update_purchase_order = AsyncMock(return_value=default_po)
    service.submit_purchase_order = AsyncMock(return_value=default_po)
    service.approve_purchase_order = AsyncMock(return_value=default_po)
    service.reject_purchase_order = AsyncMock(return_value=default_po)
    service.cancel_purchase_order = AsyncMock(return_value=default_po)
    service.close_purchase_order = AsyncMock(return_value=default_po)

    service.create_sales_order = AsyncMock(return_value=default_so)
    service.get_sales_order_by_id = AsyncMock(return_value=default_so)
    service.get_sales_order_by_number = AsyncMock(return_value=default_so)
    service.list_sales_orders = AsyncMock(return_value=MagicMock(items=[default_so], total=1))
    service.update_sales_order = AsyncMock(return_value=default_so)
    service.submit_sales_order = AsyncMock(return_value=default_so)
    service.approve_sales_order = AsyncMock(return_value=default_so)
    service.reject_sales_order = AsyncMock(return_value=default_so)
    service.cancel_sales_order = AsyncMock(return_value=default_so)
    service.close_sales_order = AsyncMock(return_value=default_so)

    service.create_goods_receipt_note = AsyncMock(return_value=default_grn)
    service.confirm_goods_receipt_note = AsyncMock(return_value=default_grn)
    service.cancel_goods_receipt_note = AsyncMock(return_value=default_grn)

    service.create_delivery_order = AsyncMock(return_value=default_do)
    service.confirm_delivery_order = AsyncMock(return_value=default_do)
    service.ship_delivery_order = AsyncMock(return_value=default_do)

    service.get_purchase_order_status = AsyncMock(
        return_value=MagicMock(
            po_number="PO-001",
            status="draft",
            status_description="Draft",
            can_submit=True,
            can_approve=False,
            can_reject=False,
            can_cancel=True,
            can_close=False,
            is_locked=False,
            is_archived=False,
            submitted_at=None,
            approved_at=None,
            received_percent=0,
            invoiced_percent=0,
            paid_percent=0,
        )
    )
    service.get_sales_order_status = AsyncMock(
        return_value=MagicMock(
            so_number="SO-001",
            status="draft",
            status_description="Draft",
            can_submit=True,
            can_approve=False,
            can_reject=False,
            can_cancel=True,
            can_close=False,
            is_locked=False,
            is_archived=False,
            submitted_at=None,
            approved_at=None,
            shipped_percent=0,
            invoiced_percent=0,
            paid_percent=0,
        )
    )
    service.get_purchase_order_history = AsyncMock(return_value=[])
    service.get_sales_order_history = AsyncMock(return_value=[])
    service.export_purchase_orders = AsyncMock(return_value=b"csvdata")
    service.export_sales_orders = AsyncMock(return_value=b"csvdata")

    return service


@pytest.fixture
def current_user():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def idempotency_key():
    return "test-idempotency-key"


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
    mgr.cache_result(key, method, result)
    storage_key = mgr._get_key(key, method)
    assert storage_key in mgr._storage
    cached = mgr.get_cached_result(key, method)
    assert cached == result


def test_idempotency_manager_get_missing():
    mgr = IdempotencyManager()
    assert mgr.get_cached_result("missing", "method") is None


def test_idempotency_manager_expiry():
    mgr = IdempotencyManager()
    mgr._ttl_seconds = 0  # force expiry
    mgr.cache_result("key", "method", {"x": 1})
    assert mgr.get_cached_result("key", "method") is None


# ---------- Enum Tests (parametrized to avoid duplication) ----------

ENUM_CLASSES = [
    PurchaseOrderStatus,
    SalesOrderStatus,
    GoodsReceiptStatus,
    DeliveryOrderStatus,
    OrderType,
    Incoterm,
]

EXPECTED_MEMBERS = {
    PurchaseOrderStatus: [
        "DRAFT", "SUBMITTED", "PENDING_APPROVAL", "APPROVED", "REJECTED",
        "PARTIALLY_RECEIVED", "FULLY_RECEIVED", "PARTIALLY_INVOICED", "FULLY_INVOICED",
        "PARTIALLY_PAID", "PAID", "CANCELLED", "CLOSED", "LOCKED", "ARCHIVED"
    ],
    SalesOrderStatus: [
        "DRAFT", "SUBMITTED", "PENDING_APPROVAL", "APPROVED", "REJECTED",
        "PARTIALLY_SHIPPED", "FULLY_SHIPPED", "PARTIALLY_INVOICED", "FULLY_INVOICED",
        "PARTIALLY_PAID", "PAID", "CANCELLED", "CLOSED", "LOCKED", "ARCHIVED"
    ],
    GoodsReceiptStatus: ["DRAFT", "CONFIRMED", "POSTED", "CANCELLED", "ARCHIVED"],
    DeliveryOrderStatus: ["DRAFT", "CONFIRMED", "SHIPPED", "DELIVERED", "CANCELLED", "ARCHIVED"],
    OrderType: ["STANDARD", "RUSH", "BACKORDER", "CONSIGNMENT", "DROPSHIP"],
    Incoterm: ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"],
}


@pytest.mark.parametrize("enum_class", ENUM_CLASSES)
def test_enum_members_exist(enum_class):
    expected = EXPECTED_MEMBERS[enum_class]
    for member in expected:
        assert hasattr(enum_class, member)


@pytest.mark.parametrize("enum_class", ENUM_CLASSES)
def test_enum_member_is_instance(enum_class):
    first_member = list(enum_class)[0]
    assert isinstance(first_member, enum_class)


# ---------- Schema Tests (including negative validation) ----------

def test_po_line_schema_calculation():
    line = POLineSchema(
        item_id=uuid4(),
        quantity=Decimal("2"),
        unit_price=Decimal("100000"),
        discount_percent=Decimal("10"),
        tax_rate=Decimal("11"),
    )
    assert line.net_amount == Decimal("180000.00")  # 2*100000*(1-0.10)
    assert line.tax_amount == Decimal("19800.00")   # 180000*0.11
    assert line.total_amount == Decimal("199800.00")


def test_po_create_schema_total_amount():
    line1 = POLineSchema(item_id=uuid4(), quantity=1, unit_price=100)
    line2 = POLineSchema(item_id=uuid4(), quantity=2, unit_price=50)
    schema = PurchaseOrderCreateSchema(
        po_number="PO-001",
        supplier_id=uuid4(),
        lines=[line1, line2],
    )
    assert schema.total_amount == line1.total_amount + line2.total_amount


def test_po_create_schema_missing_po_number():
    with pytest.raises(ValueError, match="PO number is required"):
        PurchaseOrderCreateSchema(
            po_number="",
            supplier_id=uuid4(),
            lines=[POLineSchema(item_id=uuid4(), quantity=1, unit_price=100)],
        )


def test_grn_line_schema_quantities_validation():
    # Accepted + rejected must equal received
    with pytest.raises(ValueError, match="Accepted \\+ rejected must equal received quantity"):
        GRNLineSchema(
            purchase_order_line_id=uuid4(),
            item_id=uuid4(),
            quantity_received=Decimal("10"),
            quantity_accepted=Decimal("8"),
            quantity_rejected=Decimal("1"),  # 8+1=9 != 10
        )

    # Valid case
    line = GRNLineSchema(
        purchase_order_line_id=uuid4(),
        item_id=uuid4(),
        quantity_received=Decimal("10"),
        quantity_accepted=Decimal("9"),
        quantity_rejected=Decimal("1"),
    )
    assert line.quantity_accepted == Decimal("9")


def test_do_line_schema_construction():
    schema = DOLineSchema(
        sales_order_line_id=uuid4(),
        item_id=uuid4(),
        quantity_shipped=Decimal("5"),
        batch_number="BATCH-001",
        serial_numbers=["SN1", "SN2"],
    )
    assert schema.quantity_shipped == Decimal("5")


# ---------- Dependency Injection ----------

@pytest.mark.asyncio
async def test_get_purchase_sales_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve = MagicMock(return_value=AsyncMock())
    service = await get_purchase_sales_service(request)
    assert service is not None


# ---------- Purchase Order Endpoints ----------

@pytest.mark.asyncio
async def test_create_purchase_order_success(mock_service, current_user, legal_entity_id, idempotency_key):
    request = MagicMock(
        po_number="PO-001",
        po_date=date.today(),
        supplier_id=uuid4(),
        lines=[MagicMock()],
        expected_delivery_date=date.today() + timedelta(days=30),
        delivery_term_days=30,
        payment_term_days=45,
        incoterm=Incoterm.FOB,
        order_type=OrderType.STANDARD,
        reference_number=None,
        notes=None,
    )
    # Force line.dict() to return dict
    request.lines[0].dict = MagicMock(return_value={})
    result = await create_purchase_order(
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, PurchaseOrderResponseSchema)
    assert result.po_number == "PO-001"
    mock_service.create_purchase_order.assert_called_once()


@pytest.mark.asyncio
async def test_create_purchase_order_idempotency_hit(mock_service, current_user, legal_entity_id, idempotency_key):
    # Pre-cache result
    mgr = IdempotencyManager()
    with patch("adapters.primary_api.v1.fastapi_purchase_sales_router._idempotency_manager", mgr):
        cached = PurchaseOrderResponseSchema(
            id=uuid4(),
            po_number="CACHED-PO",
            po_date=date.today(),
            supplier_id=uuid4(),
            supplier_name="Supplier",
            supplier_code="SUP",
            total_amount=Decimal("1000"),
            received_amount=Decimal("0"),
            invoiced_amount=Decimal("0"),
            paid_amount=Decimal("0"),
            outstanding_amount=Decimal("1000"),
            status=PurchaseOrderStatus.DRAFT,
            expected_delivery_date=date.today(),
            actual_delivery_date=None,
            delivery_term_days=30,
            payment_term_days=45,
            incoterm=Incoterm.FOB,
            order_type=OrderType.STANDARD,
            reference_number=None,
            notes=None,
            lines=[],
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=uuid4(),
            created_by_name="admin",
            approved_at=None,
            approved_by=None,
            approved_by_name=None,
            rejected_at=None,
            rejected_by=None,
            rejection_reason=None,
            cancelled_at=None,
            cancelled_by=None,
            closed_at=None,
            is_locked=False,
            version=1,
        )
        mgr.cache_result(idempotency_key, "create_purchase_order", cached.model_dump())
        request = MagicMock()
        result = await create_purchase_order(
            request=request,
            idempotency_key=idempotency_key,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
        mock_service.create_purchase_order.assert_not_called()
        assert result.po_number == "CACHED-PO"


@pytest.mark.asyncio
async def test_create_purchase_order_value_error(mock_service, current_user, legal_entity_id):
    mock_service.create_purchase_order.side_effect = ValueError("Invalid supplier")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await create_purchase_order(
            request=request,
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 422
    assert "Invalid supplier" in exc.value.detail


@pytest.mark.asyncio
async def test_create_purchase_order_general_exception(mock_service, current_user, legal_entity_id):
    mock_service.create_purchase_order.side_effect = RuntimeError("DB error")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await create_purchase_order(
            request=request,
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_get_purchase_order_success(mock_service, legal_entity_id):
    po_id = uuid4()
    result = await get_purchase_order(
        po_id=po_id,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, PurchaseOrderResponseSchema)
    mock_service.get_purchase_order_by_id.assert_called_once_with(po_id, legal_entity_id)


@pytest.mark.asyncio
async def test_get_purchase_order_not_found(mock_service, legal_entity_id):
    mock_service.get_purchase_order_by_id.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_purchase_order(
            po_id=uuid4(),
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_purchase_order_by_number_success(mock_service, legal_entity_id):
    result = await get_purchase_order_by_number(
        po_number="PO-001",
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, PurchaseOrderResponseSchema)
    mock_service.get_purchase_order_by_number.assert_called_once_with("PO-001", legal_entity_id)


@pytest.mark.asyncio
async def test_get_purchase_order_by_number_not_found(mock_service, legal_entity_id):
    mock_service.get_purchase_order_by_number.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_purchase_order_by_number(
            po_number="PO-999",
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_purchase_orders_success(mock_service, legal_entity_id):
    result = await list_purchase_orders(
        supplier_id=uuid4(),
        status=PurchaseOrderStatus.DRAFT,
        start_date=date.today(),
        end_date=date.today(),
        page=1,
        page_size=10,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], PurchaseOrderResponseSchema)
    mock_service.list_purchase_orders.assert_called_once()


@pytest.mark.asyncio
async def test_list_purchase_orders_general_exception(mock_service, legal_entity_id):
    mock_service.list_purchase_orders.side_effect = RuntimeError("Error")
    with pytest.raises(HTTPException) as exc:
        await list_purchase_orders(
            supplier_id=None,
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


@pytest.mark.asyncio
async def test_update_purchase_order_success(mock_service, current_user, legal_entity_id, idempotency_key):
    po_id = uuid4()
    request = PurchaseOrderUpdateSchema(
        expected_delivery_date=date.today() + timedelta(days=60),
        delivery_term_days=60,
        payment_term_days=60,
        notes="Updated",
        status=PurchaseOrderStatus.DRAFT,
    )
    result = await update_purchase_order(
        po_id=po_id,
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, PurchaseOrderResponseSchema)
    mock_service.update_purchase_order.assert_called_once()


@pytest.mark.asyncio
async def test_update_purchase_order_not_found(mock_service, current_user, legal_entity_id):
    mock_service.update_purchase_order.return_value = None
    with pytest.raises(HTTPException) as exc:
        await update_purchase_order(
            po_id=uuid4(),
            request=MagicMock(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404


# ---------- Purchase Order Workflow ----------

@pytest.mark.asyncio
async def test_submit_purchase_order_success(mock_service, current_user, legal_entity_id, idempotency_key):
    po_id = uuid4()
    result = await submit_purchase_order(
        po_id=po_id,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, PurchaseOrderResponseSchema)
    mock_service.submit_purchase_order.assert_called_once_with(po_id, current_user.user_id, legal_entity_id)


@pytest.mark.asyncio
async def test_submit_purchase_order_not_found(mock_service, current_user, legal_entity_id):
    mock_service.submit_purchase_order.return_value = None
    with pytest.raises(HTTPException) as exc:
        await submit_purchase_order(
            po_id=uuid4(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_approve_purchase_order_success(mock_service, current_user, legal_entity_id):
    po_id = uuid4()
    result = await approve_purchase_order(
        po_id=po_id,
        notes="Approved",
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, PurchaseOrderResponseSchema)
    mock_service.approve_purchase_order.assert_called_once_with(po_id, current_user.user_id, legal_entity_id, "Approved")


@pytest.mark.asyncio
async def test_approve_purchase_order_value_error(mock_service, current_user, legal_entity_id):
    mock_service.approve_purchase_order.side_effect = ValueError("Cannot approve")
    with pytest.raises(HTTPException) as exc:
        await approve_purchase_order(
            po_id=uuid4(),
            notes="",
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_approve_purchase_order_permission_error(mock_service, current_user, legal_entity_id):
    mock_service.approve_purchase_order.side_effect = PermissionError("Not allowed")
    with pytest.raises(HTTPException) as exc:
        await approve_purchase_order(
            po_id=uuid4(),
            notes="",
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_reject_purchase_order_success(mock_service, current_user, legal_entity_id):
    po_id = uuid4()
    result = await reject_purchase_order(
        po_id=po_id,
        reason="Bad quality",
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, PurchaseOrderResponseSchema)
    mock_service.reject_purchase_order.assert_called_once_with(po_id, current_user.user_id, legal_entity_id, "Bad quality")


@pytest.mark.asyncio
async def test_cancel_purchase_order_success(mock_service, current_user, legal_entity_id):
    po_id = uuid4()
    result = await cancel_purchase_order(
        po_id=po_id,
        reason="No need",
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert result["po_id"] == str(po_id)
    mock_service.cancel_purchase_order.assert_called_once()


@pytest.mark.asyncio
async def test_close_purchase_order_success(mock_service, current_user, legal_entity_id):
    po_id = uuid4()
    result = await close_purchase_order(
        po_id=po_id,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, PurchaseOrderResponseSchema)
    mock_service.close_purchase_order.assert_called_once_with(po_id, current_user.user_id, legal_entity_id)


# ---------- Sales Order Endpoints ----------

@pytest.mark.asyncio
async def test_create_sales_order_success(mock_service, current_user, legal_entity_id, idempotency_key):
    request = MagicMock(
        so_number="SO-001",
        so_date=date.today(),
        customer_id=uuid4(),
        lines=[MagicMock()],
        expected_ship_date=date.today() + timedelta(days=30),
        shipping_term_days=30,
        payment_term_days=45,
        incoterm=Incoterm.FOB,
        order_type=OrderType.STANDARD,
        reference_number=None,
        notes=None,
    )
    request.lines[0].dict = MagicMock(return_value={})
    result = await create_sales_order(
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, SalesOrderResponseSchema)
    assert result.so_number == "SO-001"
    mock_service.create_sales_order.assert_called_once()


@pytest.mark.asyncio
async def test_get_sales_order_success(mock_service, legal_entity_id):
    so_id = uuid4()
    result = await get_sales_order(
        so_id=so_id,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, SalesOrderResponseSchema)
    mock_service.get_sales_order_by_id.assert_called_once_with(so_id, legal_entity_id)


@pytest.mark.asyncio
async def test_get_sales_order_by_number_success(mock_service, legal_entity_id):
    result = await get_sales_order_by_number(
        so_number="SO-001",
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, SalesOrderResponseSchema)
    mock_service.get_sales_order_by_number.assert_called_once_with("SO-001", legal_entity_id)


@pytest.mark.asyncio
async def test_list_sales_orders_success(mock_service, legal_entity_id):
    result = await list_sales_orders(
        customer_id=uuid4(),
        status=SalesOrderStatus.DRAFT,
        start_date=date.today(),
        end_date=date.today(),
        page=1,
        page_size=10,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], SalesOrderResponseSchema)


@pytest.mark.asyncio
async def test_update_sales_order_success(mock_service, current_user, legal_entity_id, idempotency_key):
    so_id = uuid4()
    request = SalesOrderUpdateSchema(
        expected_ship_date=date.today() + timedelta(days=60),
        shipping_term_days=60,
        payment_term_days=60,
        notes="Updated",
        status=SalesOrderStatus.DRAFT,
    )
    result = await update_sales_order(
        so_id=so_id,
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, SalesOrderResponseSchema)
    mock_service.update_sales_order.assert_called_once()


# ---------- Sales Order Workflow ----------

@pytest.mark.asyncio
async def test_submit_sales_order_success(mock_service, current_user, legal_entity_id, idempotency_key):
    so_id = uuid4()
    result = await submit_sales_order(
        so_id=so_id,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, SalesOrderResponseSchema)
    mock_service.submit_sales_order.assert_called_once_with(so_id, current_user.user_id, legal_entity_id)


@pytest.mark.asyncio
async def test_approve_sales_order_success(mock_service, current_user, legal_entity_id):
    so_id = uuid4()
    result = await approve_sales_order(
        so_id=so_id,
        notes="Approved",
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, SalesOrderResponseSchema)
    mock_service.approve_sales_order.assert_called_once()


@pytest.mark.asyncio
async def test_reject_sales_order_success(mock_service, current_user, legal_entity_id):
    so_id = uuid4()
    result = await reject_sales_order(
        so_id=so_id,
        reason="Bad",
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, SalesOrderResponseSchema)
    mock_service.reject_sales_order.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_sales_order_success(mock_service, current_user, legal_entity_id):
    so_id = uuid4()
    result = await cancel_sales_order(
        so_id=so_id,
        reason="Cancel",
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert result["so_id"] == str(so_id)
    mock_service.cancel_sales_order.assert_called_once()


@pytest.mark.asyncio
async def test_close_sales_order_success(mock_service, current_user, legal_entity_id):
    so_id = uuid4()
    result = await close_sales_order(
        so_id=so_id,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, SalesOrderResponseSchema)
    mock_service.close_sales_order.assert_called_once()


# ---------- Goods Receipt Note ----------

@pytest.mark.asyncio
async def test_create_goods_receipt_success(mock_service, current_user, legal_entity_id, idempotency_key):
    request = MagicMock(
        grn_number="GRN-001",
        grn_date=date.today(),
        purchase_order_id=uuid4(),
        lines=[MagicMock()],
        warehouse_id=uuid4(),
        notes=None,
    )
    request.lines[0].dict = MagicMock(return_value={})
    result = await create_goods_receipt(
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, GoodsReceiptResponseSchema)
    assert result.grn_number == "GRN-001"
    mock_service.create_goods_receipt_note.assert_called_once()


@pytest.mark.asyncio
async def test_confirm_goods_receipt_success(mock_service, current_user, legal_entity_id):
    grn_id = uuid4()
    result = await confirm_goods_receipt(
        grn_id=grn_id,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, GoodsReceiptResponseSchema)
    mock_service.confirm_goods_receipt_note.assert_called_once_with(grn_id, current_user.user_id, legal_entity_id)


@pytest.mark.asyncio
async def test_cancel_goods_receipt_success(mock_service, current_user, legal_entity_id):
    grn_id = uuid4()
    result = await cancel_goods_receipt(
        grn_id=grn_id,
        reason="Wrong",
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert result["grn_id"] == str(grn_id)
    mock_service.cancel_goods_receipt_note.assert_called_once()


# ---------- Delivery Order ----------

@pytest.mark.asyncio
async def test_create_delivery_order_success(mock_service, current_user, legal_entity_id, idempotency_key):
    request = MagicMock(
        do_number="DO-001",
        do_date=date.today(),
        sales_order_id=uuid4(),
        warehouse_id=uuid4(),
        shipping_address="Jl. Test",
        tracking_number=None,
        carrier=None,
        lines=[MagicMock()],
        notes=None,
    )
    request.lines[0].dict = MagicMock(return_value={})
    result = await create_delivery_order(
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, DeliveryOrderResponseSchema)
    assert result.do_number == "DO-001"
    mock_service.create_delivery_order.assert_called_once()


@pytest.mark.asyncio
async def test_confirm_delivery_order_success(mock_service, current_user, legal_entity_id):
    do_id = uuid4()
    result = await confirm_delivery_order(
        do_id=do_id,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, DeliveryOrderResponseSchema)
    mock_service.confirm_delivery_order.assert_called_once_with(do_id, current_user.user_id, legal_entity_id)


@pytest.mark.asyncio
async def test_ship_delivery_order_success(mock_service, current_user, legal_entity_id):
    do_id = uuid4()
    result = await ship_delivery_order(
        do_id=do_id,
        tracking_number="TRK123",
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, DeliveryOrderResponseSchema)
    mock_service.ship_delivery_order.assert_called_once_with(
        do_id=do_id,
        tracking_number="TRK123",
        shipped_by=current_user.user_id,
        legal_entity_id=legal_entity_id,
    )


# ---------- Order Status & History ----------

@pytest.mark.asyncio
async def test_get_purchase_order_status_success(mock_service, legal_entity_id):
    po_id = uuid4()
    result = await get_purchase_order_status(
        po_id=po_id,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert result["status"] == "draft"
    mock_service.get_purchase_order_status.assert_called_once_with(po_id, legal_entity_id)


@pytest.mark.asyncio
async def test_get_purchase_order_status_not_found(mock_service, legal_entity_id):
    mock_service.get_purchase_order_status.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_purchase_order_status(
            po_id=uuid4(),
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_sales_order_status_success(mock_service, legal_entity_id):
    so_id = uuid4()
    result = await get_sales_order_status(
        so_id=so_id,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert result["status"] == "draft"
    mock_service.get_sales_order_status.assert_called_once_with(so_id, legal_entity_id)


@pytest.mark.asyncio
async def test_get_purchase_order_history_success(mock_service, legal_entity_id):
    po_id = uuid4()
    result = await get_purchase_order_history(
        po_id=po_id,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, list)
    mock_service.get_purchase_order_history.assert_called_once_with(po_id, legal_entity_id)


@pytest.mark.asyncio
async def test_get_sales_order_history_success(mock_service, legal_entity_id):
    so_id = uuid4()
    result = await get_sales_order_history(
        so_id=so_id,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, list)
    mock_service.get_sales_order_history.assert_called_once_with(so_id, legal_entity_id)


# ---------- Exports ----------

@pytest.mark.asyncio
async def test_export_purchase_orders_success(mock_service, legal_entity_id):
    start = date.today()
    end = date.today() + timedelta(days=1)
    result = await export_purchase_orders(
        start_date=start,
        end_date=end,
        format="csv",
        status=PurchaseOrderStatus.DRAFT,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, Response)
    assert result.media_type == "text/csv"
    assert result.body == b"csvdata"
    mock_service.export_purchase_orders.assert_called_once()


@pytest.mark.asyncio
async def test_export_purchase_orders_excel(mock_service, legal_entity_id):
    start = date.today()
    end = date.today() + timedelta(days=1)
    result = await export_purchase_orders(
        start_date=start,
        end_date=end,
        format="excel",
        status=None,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert result.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    mock_service.export_purchase_orders.assert_called_once_with(
        legal_entity_id=legal_entity_id,
        start_date=start,
        end_date=end,
        format="excel",
        status=None,
    )


@pytest.mark.asyncio
async def test_export_purchase_orders_general_exception(mock_service, legal_entity_id):
    mock_service.export_purchase_orders.side_effect = RuntimeError("Export error")
    with pytest.raises(HTTPException) as exc:
        await export_purchase_orders(
            start_date=date.today(),
            end_date=date.today(),
            format="csv",
            status=None,
            _permission=MagicMock(),
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_export_sales_orders_success(mock_service, legal_entity_id):
    start = date.today()
    end = date.today() + timedelta(days=1)
    result = await export_sales_orders(
        start_date=start,
        end_date=end,
        format="csv",
        status=SalesOrderStatus.DRAFT,
        _permission=MagicMock(),
        legal_entity_id=legal_entity_id,
        service=mock_service,
    )
    assert isinstance(result, Response)
    assert result.media_type == "text/csv"
    mock_service.export_sales_orders.assert_called_once()


# ---------- Additional Negative Tests for Edge Cases ----------

@pytest.mark.asyncio
async def test_reject_purchase_order_value_error(mock_service, current_user, legal_entity_id):
    mock_service.reject_purchase_order.side_effect = ValueError("Cannot reject")
    with pytest.raises(HTTPException) as exc:
        await reject_purchase_order(
            po_id=uuid4(),
            reason="Bad",
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_cancel_purchase_order_value_error(mock_service, current_user, legal_entity_id):
    mock_service.cancel_purchase_order.side_effect = ValueError("Cannot cancel")
    with pytest.raises(HTTPException) as exc:
        await cancel_purchase_order(
            po_id=uuid4(),
            reason="No need",
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_submit_sales_order_value_error(mock_service, current_user, legal_entity_id):
    mock_service.submit_sales_order.side_effect = ValueError("Invalid")
    with pytest.raises(HTTPException) as exc:
        await submit_sales_order(
            so_id=uuid4(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_close_sales_order_not_found(mock_service, current_user, legal_entity_id):
    mock_service.close_sales_order.return_value = None
    with pytest.raises(HTTPException) as exc:
        await close_sales_order(
            so_id=uuid4(),
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_confirm_goods_receipt_not_found(mock_service, current_user, legal_entity_id):
    mock_service.confirm_goods_receipt_note.return_value = None
    with pytest.raises(HTTPException) as exc:
        await confirm_goods_receipt(
            grn_id=uuid4(),
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_ship_delivery_order_not_found(mock_service, current_user, legal_entity_id):
    mock_service.ship_delivery_order.return_value = None
    with pytest.raises(HTTPException) as exc:
        await ship_delivery_order(
            do_id=uuid4(),
            tracking_number="TRK",
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_service,
        )
    assert exc.value.status_code == 404