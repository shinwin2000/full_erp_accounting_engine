# tests/adapters/primary_api/v1/test_fastapi_inventory_router.py
"""
Comprehensive unit tests for FastAPI Inventory Router.

Perbaikan:
- Semua async test diberi @pytest.mark.asyncio
- Flaky tests menggunakan mock datetime
- Duplikasi struktural dihilangkan dengan parametrize
- Mock quality ditingkatkan: AsyncMock, verifikasi panggilan
- Negative path ditambahkan: ValueError, Exception
- Semua assertion bermakna
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import Response

from adapters.primary_api.v1.fastapi_inventory_router import (
    IdempotencyManager,
    InterWarehouseTransferCreateSchema,
    InterWarehouseTransferLineSchema,
    InterWarehouseTransferResponseSchema,
    InventoryValuationLayerSchema,
    InventoryValuationRepositoryAdapter,
    InventoryValuationResponseSchema,
    ItemCreateSchema,
    ItemResponseSchema,
    ItemType,
    ItemUpdateSchema,
    LowStockAlertSchema,
    MovementStatus,
    MovementType,
    NRVTestResponseSchema,
    StockCardLineSchema,
    StockCardResponseSchema,
    StockMovementCreateSchema,
    StockMovementResponseSchema,
    StockOpnameCreateSchema,
    StockOpnameLineSchema,
    StockOpnameResponseSchema,
    StockOpnameStatus,
    TransferStatus,
    ValuationMethod,
    WarehouseCreateSchema,
    WarehouseResponseSchema,
    activate_item,
    approve_stock_opname,
    approve_warehouse_transfer,
    cancel_stock_opname,
    complete_warehouse_transfer,
    create_item,
    create_stock_opname,
    create_warehouse_transfer,
    deactivate_item,
    export_items,
    get_inventory_service,
    get_inventory_valuation,
    get_inventory_valuation_by_path,
    get_item,
    get_item_by_code,
    get_low_stock_alerts,
    get_movement,
    get_stock_card,
    health,
    info,
    list_items,
    list_warehouses,
    ping,
    record_stock_movement,
    reverse_movement,
    test_nrv,
    update_item,
)

# ============================================================================
# FIXED DATETIME - untuk menghindari flaky tests
# ============================================================================
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 1, 1)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now() dan date.today() untuk menghindari flaky tests."""
    with patch("adapters.primary_api.v1.fastapi_inventory_router.datetime") as mock_dt, \
         patch("adapters.primary_api.v1.fastapi_inventory_router.date") as mock_date:
        mock_dt.now.return_value = FIXED_NOW
        mock_date.today.return_value = FIXED_DATE
        yield


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_token_payload():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_inventory_service():
    """Create a fully mocked InventoryService with realistic return values."""
    svc = AsyncMock()

    # Helper to create mock item
    def mock_item(**kwargs):
        defaults = {
            "id": uuid4(),
            "item_code": "ITEM001",
            "item_name": "Raw Material A",
            "item_type": "raw_material",
            "unit_of_measure": "PCS",
            "category": "Materials",
            "brand": "BrandX",
            "reorder_point": Decimal("10"),
            "reorder_quantity": Decimal("50"),
            "standard_cost": Decimal("1000"),
            "selling_price": Decimal("1200"),
            "valuation_method": "FIFO",
            "is_active": True,
            "is_locked": False,
            "current_stock": Decimal("75"),
            "average_cost": Decimal("1050"),
            "total_value": Decimal("78750"),
            "last_purchase_price": Decimal("1000"),
            "last_purchase_date": FIXED_DATE,
            "min_stock": Decimal("5"),
            "max_stock": Decimal("100"),
            "weight_kg": Decimal("1.5"),
            "volume_m3": Decimal("0.5"),
            "created_at": FIXED_NOW,
            "updated_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    # Item methods
    svc.create_item.return_value = mock_item()
    svc.get_item_by_id.return_value = mock_item()
    svc.get_item_by_code.return_value = mock_item()
    svc.update_item.return_value = mock_item()
    svc.deactivate_item.return_value = mock_item(is_active=False)
    svc.void_item.return_value = mock_item(is_active=False)
    svc.activate_item.return_value = mock_item(is_active=True)
    svc.list_items.return_value = MagicMock(items=[mock_item()], total=1)

    # Movement
    def mock_movement(**kwargs):
        defaults = {
            "id": uuid4(),
            "movement_number": "MOV-001",
            "item_id": uuid4(),
            "item_code": "ITEM001",
            "item_name": "Raw Material A",
            "movement_type": "IN",
            "quantity": Decimal("100"),
            "unit_cost": Decimal("1000"),
            "total_cost": Decimal("100000"),
            "movement_date": FIXED_DATE,
            "reference_type": "PURCHASE_ORDER",
            "reference_id": uuid4(),
            "warehouse_id": uuid4(),
            "warehouse_name": "Main Warehouse",
            "to_warehouse_id": None,
            "batch_number": None,
            "serial_number": None,
            "expiry_date": None,
            "notes": None,
            "status": "confirmed",
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "reversed_at": None,
            "reversed_by": None,
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.record_movement.return_value = mock_movement()
    svc.get_movement_by_id.return_value = mock_movement()
    svc.reverse_movement.return_value = mock_movement(status="reversed")

    # Stock card
    def mock_stock_card(**kwargs):
        defaults = {
            "item_id": uuid4(),
            "item_code": "ITEM001",
            "item_name": "Raw Material A",
            "warehouse_name": "Main Warehouse",
            "opening_quantity": Decimal("0"),
            "opening_value": Decimal("0"),
            "opening_unit_cost": Decimal("0"),
            "lines": [],
            "closing_quantity": Decimal("100"),
            "closing_value": Decimal("100000"),
            "closing_unit_cost": Decimal("1000"),
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.get_stock_card.return_value = mock_stock_card()

    # Stock opname
    def mock_opname(**kwargs):
        defaults = {
            "id": uuid4(),
            "opname_number": "OPN-001",
            "warehouse_id": uuid4(),
            "warehouse_name": "Main Warehouse",
            "opname_date": FIXED_DATE,
            "status": "draft",
            "total_adjustments": 0,
            "adjustment_value": Decimal("0"),
            "lines": [],
            "notes": None,
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "approved_at": None,
            "approved_by": None,
            "applied_at": None,
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_stock_opname.return_value = mock_opname()
    svc.approve_stock_opname.return_value = mock_opname(status="approved")
    svc.cancel_stock_opname.return_value = mock_opname(status="cancelled")

    # Transfer
    def mock_transfer(**kwargs):
        defaults = {
            "id": uuid4(),
            "transfer_number": "TRF-001",
            "from_warehouse_id": uuid4(),
            "from_warehouse_name": "WH A",
            "to_warehouse_id": uuid4(),
            "to_warehouse_name": "WH B",
            "transfer_date": FIXED_DATE,
            "status": "draft",
            "items": [],
            "notes": None,
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "approved_at": None,
            "approved_by": None,
            "completed_at": None,
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_warehouse_transfer.return_value = mock_transfer()
    svc.approve_warehouse_transfer.return_value = mock_transfer(status="approved")
    svc.complete_warehouse_transfer.return_value = mock_transfer(status="completed")

    # Valuation
    def mock_valuation(**kwargs):
        defaults = {
            "item_id": uuid4(),
            "item_code": "ITEM001",
            "item_name": "Raw Material A",
            "valuation_method": "FIFO",
            "total_quantity": Decimal("100"),
            "total_value": Decimal("100000"),
            "weighted_average_cost": Decimal("1000"),
            "layers": [],
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.get_valuation.return_value = mock_valuation()

    # NRV
    def mock_nrv(**kwargs):
        defaults = {
            "item_id": uuid4(),
            "item_code": "ITEM001",
            "item_name": "Raw Material A",
            "carrying_value": Decimal("100000"),
            "net_realizable_value": Decimal("90000"),
            "impairment_loss": Decimal("10000"),
            "nrv_less_than_cost": True,
            "recommended_adjustment": Decimal("10000"),
            "journal_id": uuid4(),
            "status": "completed",
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.test_nrv.return_value = mock_nrv()

    # Low stock alerts
    def mock_alert(**kwargs):
        defaults = {
            "item_id": uuid4(),
            "item_code": "ITEM001",
            "item_name": "Raw Material A",
            "current_stock": Decimal("8"),
            "reorder_point": Decimal("10"),
            "reorder_quantity": Decimal("50"),
            "shortage": Decimal("2"),
            "warehouse_id": uuid4(),
            "warehouse_name": "Main Warehouse",
            "days_until_out": 3,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.get_low_stock_alerts.return_value = [mock_alert()]

    # Warehouses
    def mock_warehouse(**kwargs):
        defaults = {
            "id": uuid4(),
            "warehouse_code": "WH001",
            "warehouse_name": "Main Warehouse",
            "location": "Jakarta",
            "is_active": True,
            "is_default": True,
            "notes": None,
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.list_warehouses.return_value = [mock_warehouse()]
    svc.export_items.return_value = b"csv data"

    return svc


# ============================================================================
# IDEMPOTENCY MANAGER TESTS
# ============================================================================

class TestIdempotencyManager:
    def test_construction(self):
        instance = IdempotencyManager()
        assert isinstance(instance, IdempotencyManager)
        assert instance._storage == {}
        assert instance._ttl_seconds == 86400

    def test_get_cached_result_miss(self):
        instance = IdempotencyManager()
        result = instance.get_cached_result("key", "method")
        assert result is None

    def test_cache_and_retrieve(self):
        instance = IdempotencyManager()
        data = {"id": "123", "status": "ok"}
        instance.cache_result("key", "method", data)
        cached = instance.get_cached_result("key", "method")
        assert cached == data

    @patch("adapters.primary_api.v1.fastapi_inventory_router.datetime")
    def test_cache_expiration(self, mock_dt):
        mock_dt.now.return_value = FIXED_NOW
        instance = IdempotencyManager()
        instance._ttl_seconds = 0
        instance.cache_result("key", "method", {"foo": "bar"})
        cached = instance.get_cached_result("key", "method")
        assert cached is None

    def test_key_generation_deterministic(self):
        instance = IdempotencyManager()
        key1 = instance._get_key("abc", "create_inventory_item")
        key2 = instance._get_key("abc", "create_inventory_item")
        key3 = instance._get_key("abc", "update_inventory_item")
        assert key1 == key2
        assert key1 != key3


# ============================================================================
# ENUM TESTS (parametrized untuk menghindari duplikasi)
# ============================================================================

ENUM_TEST_DATA = [
    (ItemType, [
        "RAW_MATERIAL", "WORK_IN_PROCESS", "FINISHED_GOOD", "TRADING",
        "CONSUMABLE", "SERVICE", "ASSET"
    ]),
    (MovementType, [
        "IN", "OUT", "ADJUSTMENT", "TRANSFER_IN", "TRANSFER_OUT",
        "RETURN_IN", "RETURN_OUT", "SCRAP", "SAMPLE"
    ]),
    (MovementStatus, ["DRAFT", "PENDING", "CONFIRMED", "POSTED", "REVERSED", "CANCELLED"]),
    (StockOpnameStatus, ["DRAFT", "IN_PROGRESS", "SUBMITTED", "APPROVED", "REJECTED", "APPLIED", "CANCELLED"]),
    (TransferStatus, ["DRAFT", "SUBMITTED", "APPROVED", "IN_TRANSIT", "COMPLETED", "REJECTED", "CANCELLED"]),
    (ValuationMethod, ["FIFO", "LIFO", "AVERAGE", "STANDARD"]),
]


class TestEnums:
    @pytest.mark.parametrize("enum_class, members", ENUM_TEST_DATA)
    def test_members_exist(self, enum_class, members):
        for member in members:
            assert hasattr(enum_class, member)

    @pytest.mark.parametrize("enum_class, members", ENUM_TEST_DATA)
    def test_member_is_instance(self, enum_class, members):
        first_member = getattr(enum_class, members[0])
        assert isinstance(first_member, enum_class)


# ============================================================================
# SCHEMA TESTS (parametrized)
# ============================================================================

SCHEMA_TEST_DATA = [
    (ItemCreateSchema, {
        "item_code": "ITEM001",
        "item_name": "Raw Material A",
        "item_type": ItemType.RAW_MATERIAL,
        "unit_of_measure": "PCS",
        "category": "Materials",
        "brand": "BrandX",
        "reorder_point": Decimal("10"),
        "reorder_quantity": Decimal("50"),
        "standard_cost": Decimal("1000"),
        "selling_price": Decimal("1200"),
        "valuation_method": ValuationMethod.FIFO,
        "warehouse_id": uuid4(),
        "min_stock": Decimal("5"),
        "max_stock": Decimal("100"),
        "description": "Test item",
        "tax_rate_purchase": Decimal("0.11"),
        "tax_rate_sales": Decimal("0.11"),
        "weight_kg": Decimal("1.5"),
        "volume_m3": Decimal("0.5"),
        "is_active": True,
        "is_lot_tracked": False,
        "is_serial_tracked": False,
        "is_expiry_tracked": False,
    }),
    (ItemUpdateSchema, {
        "item_name": "Updated",
        "item_type": ItemType.RAW_MATERIAL,
        "unit_of_measure": "PCS",
        "category": "Materials",
        "reorder_point": Decimal("15"),
        "reorder_quantity": Decimal("60"),
        "standard_cost": Decimal("1100"),
        "selling_price": Decimal("1300"),
        "valuation_method": ValuationMethod.FIFO,
        "warehouse_id": uuid4(),
        "min_stock": Decimal("5"),
        "max_stock": Decimal("120"),
        "description": "Updated",
        "is_active": True,
    }),
    (ItemResponseSchema, {
        "id": uuid4(),
        "item_code": "ITEM001",
        "item_name": "Raw Material A",
        "item_type": ItemType.RAW_MATERIAL,
        "unit_of_measure": "PCS",
        "category": "Materials",
        "brand": "BrandX",
        "reorder_point": Decimal("10"),
        "reorder_quantity": Decimal("50"),
        "standard_cost": Decimal("1000"),
        "selling_price": Decimal("1200"),
        "valuation_method": ValuationMethod.FIFO,
        "is_active": True,
        "is_locked": False,
        "current_stock": Decimal("75"),
        "average_cost": Decimal("1050"),
        "total_value": Decimal("78750"),
        "last_purchase_price": Decimal("1000"),
        "last_purchase_date": FIXED_DATE,
        "min_stock": Decimal("5"),
        "max_stock": Decimal("100"),
        "weight_kg": Decimal("1.5"),
        "volume_m3": Decimal("0.5"),
        "created_at": FIXED_NOW,
        "updated_at": FIXED_NOW,
        "created_by": uuid4(),
        "created_by_name": "Admin",
        "version": 1,
    }),
    (StockMovementCreateSchema, {
        "item_id": uuid4(),
        "movement_type": MovementType.IN,
        "quantity": Decimal("100"),
        "unit_cost": Decimal("1000"),
        "movement_date": FIXED_DATE,
        "reference_type": "PURCHASE_ORDER",
        "reference_id": uuid4(),
        "warehouse_id": uuid4(),
        "to_warehouse_id": None,
        "batch_number": None,
        "serial_number": None,
        "expiry_date": None,
        "notes": None,
    }),
    (StockMovementResponseSchema, {
        "id": uuid4(),
        "movement_number": "MOV-001",
        "item_id": uuid4(),
        "item_code": "ITEM001",
        "item_name": "Raw Material A",
        "movement_type": MovementType.IN,
        "quantity": Decimal("100"),
        "unit_cost": Decimal("1000"),
        "total_cost": Decimal("100000"),
        "movement_date": FIXED_DATE,
        "reference_type": "PURCHASE_ORDER",
        "reference_id": uuid4(),
        "warehouse_id": uuid4(),
        "warehouse_name": "Main Warehouse",
        "to_warehouse_id": None,
        "batch_number": None,
        "serial_number": None,
        "expiry_date": None,
        "notes": None,
        "status": MovementStatus.DRAFT,
        "created_at": FIXED_NOW,
        "created_by": uuid4(),
        "created_by_name": "Admin",
        "reversed_at": None,
        "reversed_by": None,
        "version": 1,
    }),
    (StockCardLineSchema, {
        "date": FIXED_DATE,
        "reference": "PO-001",
        "reference_id": uuid4(),
        "in_quantity": Decimal("100"),
        "out_quantity": Decimal("0"),
        "balance_quantity": Decimal("100"),
        "unit_cost": Decimal("1000"),
        "in_value": Decimal("100000"),
        "out_value": Decimal("0"),
        "balance_value": Decimal("100000"),
    }),
    (StockCardResponseSchema, {
        "item_id": uuid4(),
        "item_code": "ITEM001",
        "item_name": "Raw Material A",
        "warehouse_id": uuid4(),
        "warehouse_name": "Main Warehouse",
        "start_date": FIXED_DATE,
        "end_date": FIXED_DATE,
        "opening_quantity": Decimal("0"),
        "opening_value": Decimal("0"),
        "opening_unit_cost": Decimal("0"),
        "lines": [],
        "closing_quantity": Decimal("100"),
        "closing_value": Decimal("100000"),
        "closing_unit_cost": Decimal("1000"),
        "generated_at": FIXED_NOW,
    }),
    (StockOpnameLineSchema, {
        "item_id": uuid4(),
        "system_quantity": Decimal("100"),
        "physical_quantity": Decimal("95"),
        "notes": "Discrepancy",
    }),
    (StockOpnameCreateSchema, {
        "warehouse_id": uuid4(),
        "opname_date": FIXED_DATE,
        "lines": [StockOpnameLineSchema(item_id=uuid4(), system_quantity=Decimal("100"), physical_quantity=Decimal("95"))],
        "notes": "Monthly",
    }),
    (StockOpnameResponseSchema, {
        "id": uuid4(),
        "opname_number": "OPN-001",
        "warehouse_id": uuid4(),
        "warehouse_name": "Main Warehouse",
        "opname_date": FIXED_DATE,
        "status": StockOpnameStatus.DRAFT,
        "total_adjustments": 0,
        "adjustment_value": Decimal("0"),
        "lines": [],
        "notes": None,
        "created_at": FIXED_NOW,
        "created_by": uuid4(),
        "created_by_name": "Admin",
        "approved_at": None,
        "approved_by": None,
        "applied_at": None,
        "version": 1,
    }),
    (InterWarehouseTransferLineSchema, {
        "item_id": uuid4(),
        "quantity": Decimal("50"),
        "batch_number": "BATCH-001",
        "serial_numbers": ["SN001", "SN002"],
    }),
    (InterWarehouseTransferCreateSchema, {
        "from_warehouse_id": uuid4(),
        "to_warehouse_id": uuid4(),
        "transfer_date": FIXED_DATE,
        "items": [InterWarehouseTransferLineSchema(item_id=uuid4(), quantity=Decimal("50"))],
        "notes": "Transfer",
    }),
    (InterWarehouseTransferResponseSchema, {
        "id": uuid4(),
        "transfer_number": "TRF-001",
        "from_warehouse_id": uuid4(),
        "from_warehouse_name": "WH A",
        "to_warehouse_id": uuid4(),
        "to_warehouse_name": "WH B",
        "transfer_date": FIXED_DATE,
        "status": TransferStatus.DRAFT,
        "items": [],
        "notes": None,
        "created_at": FIXED_NOW,
        "created_by": uuid4(),
        "created_by_name": "Admin",
        "approved_at": None,
        "approved_by": None,
        "completed_at": None,
        "version": 1,
    }),
    (InventoryValuationLayerSchema, {
        "layer_id": uuid4(),
        "quantity": Decimal("50"),
        "unit_cost": Decimal("1000"),
        "total_value": Decimal("50000"),
        "remaining_quantity": Decimal("50"),
        "remaining_value": Decimal("50000"),
        "created_at": FIXED_NOW,
        "expiry_date": FIXED_DATE,
    }),
    (InventoryValuationResponseSchema, {
        "item_id": uuid4(),
        "item_code": "ITEM001",
        "item_name": "Raw Material A",
        "valuation_method": ValuationMethod.FIFO,
        "as_of_date": FIXED_DATE,
        "total_quantity": Decimal("100"),
        "total_value": Decimal("100000"),
        "weighted_average_cost": Decimal("1000"),
        "layers": [],
        "generated_at": FIXED_NOW,
    }),
    (NRVTestResponseSchema, {
        "item_id": uuid4(),
        "item_code": "ITEM001",
        "item_name": "Raw Material A",
        "test_date": FIXED_DATE,
        "carrying_value": Decimal("100000"),
        "net_realizable_value": Decimal("90000"),
        "impairment_loss": Decimal("10000"),
        "nrv_less_than_cost": True,
        "recommended_adjustment": Decimal("10000"),
        "journal_id": uuid4(),
        "status": "completed",
        "created_at": FIXED_NOW,
        "created_by": uuid4(),
    }),
    (LowStockAlertSchema, {
        "item_id": uuid4(),
        "item_code": "ITEM001",
        "item_name": "Raw Material A",
        "current_stock": Decimal("8"),
        "reorder_point": Decimal("10"),
        "reorder_quantity": Decimal("50"),
        "shortage": Decimal("2"),
        "warehouse_id": uuid4(),
        "warehouse_name": "Main Warehouse",
        "days_until_out": 3,
    }),
    (WarehouseCreateSchema, {
        "warehouse_code": "WH001",
        "warehouse_name": "Main Warehouse",
        "location": "Jakarta",
        "is_active": True,
        "is_default": True,
        "notes": "Primary",
    }),
    (WarehouseResponseSchema, {
        "id": uuid4(),
        "warehouse_code": "WH001",
        "warehouse_name": "Main Warehouse",
        "location": "Jakarta",
        "is_active": True,
        "is_default": True,
        "notes": "Primary",
        "created_at": FIXED_NOW,
        "created_by": uuid4(),
        "version": 1,
    }),
]


class TestSchemas:
    @pytest.mark.parametrize("schema_class, kwargs", SCHEMA_TEST_DATA)
    def test_construction_success(self, schema_class, kwargs):
        instance = schema_class(**kwargs)
        assert isinstance(instance, schema_class)
        first_key = next(iter(kwargs))
        assert getattr(instance, first_key) == kwargs[first_key]


# ============================================================================
# HEALTH CHECK TESTS
# ============================================================================

def test_ping():
    result = ping()
    assert result == {"status": "ok", "service": "inventory-router"}


def test_health():
    result = health()
    assert result == {"status": "healthy"}


def test_info():
    result = info()
    assert result["version"] == "1.0"
    assert result["name"] == "Inventory Router"


# ============================================================================
# DEPENDENCY INJECTION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_inventory_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_inventory_service(request)
    assert result == "service"


# ============================================================================
# ITEM CRUD TESTS
# ============================================================================

@pytest.mark.asyncio
class TestItemCRUD:
    async def test_create_item_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        request = ItemCreateSchema(
            item_code="ITEM001",
            item_name="Raw Material A",
            item_type=ItemType.RAW_MATERIAL,
            unit_of_measure="PCS",
            valuation_method=ValuationMethod.FIFO,
        )
        result = await create_item(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, ItemResponseSchema)
        assert result.item_code == "ITEM001"
        mock_inventory_service.create_item.assert_called_once()

    @pytest.mark.parametrize("side_effect, expected_status", [
        (ValueError("Invalid code"), 422),
        (Exception("DB error"), 500),
    ])
    async def test_create_item_errors(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id,
                                      side_effect, expected_status):
        mock_inventory_service.create_item.side_effect = side_effect
        request = ItemCreateSchema(
            item_code="ITEM001",
            item_name="Test",
            item_type=ItemType.RAW_MATERIAL,
            unit_of_measure="PCS",
            valuation_method=ValuationMethod.FIFO,
        )
        with pytest.raises(HTTPException) as exc:
            await create_item(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                inventory_service=mock_inventory_service,
            )
        assert exc.value.status_code == expected_status

    async def test_create_item_idempotency(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        request = ItemCreateSchema(
            item_code="ITEM001",
            item_name="Test",
            item_type=ItemType.RAW_MATERIAL,
            unit_of_measure="PCS",
            valuation_method=ValuationMethod.FIFO,
        )
        with patch("adapters.primary_api.v1.fastapi_inventory_router._idempotency_manager") as mock_im:
            cached = {
                "id": str(uuid4()),
                "item_code": "ITEM001",
                "item_name": "Test",
                "item_type": "raw_material",
                "unit_of_measure": "PCS",
                "category": None,
                "brand": None,
                "reorder_point": "0",
                "reorder_quantity": "0",
                "standard_cost": "0",
                "selling_price": "0",
                "valuation_method": "FIFO",
                "is_active": True,
                "is_locked": False,
                "current_stock": "0",
                "average_cost": "0",
                "total_value": "0",
                "last_purchase_price": None,
                "last_purchase_date": None,
                "min_stock": "0",
                "max_stock": "0",
                "weight_kg": None,
                "volume_m3": None,
                "created_at": FIXED_NOW.isoformat(),
                "updated_at": FIXED_NOW.isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "version": 1,
            }
            mock_im.get_cached_result.return_value = cached
            result = await create_item(
                request=request,
                idempotency_key="key123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                inventory_service=mock_inventory_service,
            )
            assert isinstance(result, ItemResponseSchema)
            assert result.item_code == "ITEM001"
            mock_inventory_service.create_item.assert_not_called()

    async def test_get_item_success(self, mock_inventory_service, mock_legal_entity_id):
        item_id = uuid4()
        result = await get_item(
            item_id=item_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, ItemResponseSchema)
        assert result.item_code == "ITEM001"
        mock_inventory_service.get_item_by_id.assert_called_once_with(item_id, mock_legal_entity_id)

    async def test_get_item_not_found(self, mock_inventory_service, mock_legal_entity_id):
        mock_inventory_service.get_item_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_item(
                item_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                inventory_service=mock_inventory_service,
            )
        assert exc.value.status_code == 404

    async def test_get_item_by_code_success(self, mock_inventory_service, mock_legal_entity_id):
        result = await get_item_by_code(
            item_code="ITEM001",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, ItemResponseSchema)
        assert result.item_code == "ITEM001"
        mock_inventory_service.get_item_by_code.assert_called_once_with("ITEM001", mock_legal_entity_id)

    async def test_get_item_by_code_not_found(self, mock_inventory_service, mock_legal_entity_id):
        mock_inventory_service.get_item_by_code.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_item_by_code(
                item_code="UNKNOWN",
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                inventory_service=mock_inventory_service,
            )
        assert exc.value.status_code == 404

    async def test_update_item_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        item_id = uuid4()
        request = ItemUpdateSchema(item_name="Updated Name")
        result = await update_item(
            item_id=item_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, ItemResponseSchema)
        assert result.item_code == "ITEM001"
        mock_inventory_service.update_item.assert_called_once()

    async def test_update_item_not_found(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        mock_inventory_service.update_item.return_value = None
        request = ItemUpdateSchema()
        with pytest.raises(HTTPException) as exc:
            await update_item(
                item_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                inventory_service=mock_inventory_service,
            )
        assert exc.value.status_code == 404

    async def test_update_item_value_error(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        mock_inventory_service.update_item.side_effect = ValueError("Invalid data")
        request = ItemUpdateSchema()
        with pytest.raises(HTTPException) as exc:
            await update_item(
                item_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                inventory_service=mock_inventory_service,
            )
        assert exc.value.status_code == 422

    async def test_deactivate_item_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        item_id = uuid4()
        result = await deactivate_item(
            item_id=item_id,
            permanent=False,
            reason="Not needed",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert result["action"] == "deactivated"
        assert result["item_code"] == "ITEM001"
        mock_inventory_service.deactivate_item.assert_called_once()

    async def test_deactivate_item_permanent(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        item_id = uuid4()
        result = await deactivate_item(
            item_id=item_id,
            permanent=True,
            reason="Void",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert result["action"] == "voided"
        mock_inventory_service.void_item.assert_called_once()

    async def test_deactivate_item_not_found(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        mock_inventory_service.deactivate_item.return_value = None
        with pytest.raises(HTTPException) as exc:
            await deactivate_item(
                item_id=uuid4(),
                permanent=False,
                reason="",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                inventory_service=mock_inventory_service,
            )
        assert exc.value.status_code == 404

    async def test_activate_item_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        item_id = uuid4()
        result = await activate_item(
            item_id=item_id,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, ItemResponseSchema)
        assert result.is_active is True
        mock_inventory_service.activate_item.assert_called_once()


# ============================================================================
# LIST ITEMS TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_list_items_success(mock_inventory_service, mock_legal_entity_id):
    result = await list_items(
        item_type=ItemType.RAW_MATERIAL,
        category="Materials",
        is_active=True,
        low_stock_only=False,
        search="",
        warehouse_id=uuid4(),
        page=1,
        page_size=10,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        inventory_service=mock_inventory_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], ItemResponseSchema)
    mock_inventory_service.list_items.assert_called_once()


# ============================================================================
# STOCK MOVEMENT TESTS
# ============================================================================

@pytest.mark.asyncio
class TestStockMovement:
    async def test_record_stock_movement_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        request = StockMovementCreateSchema(
            item_id=uuid4(),
            movement_type=MovementType.IN,
            quantity=Decimal("100"),
            unit_cost=Decimal("1000"),
            movement_date=FIXED_DATE,
            reference_type="PURCHASE_ORDER",
            reference_id=uuid4(),
            warehouse_id=uuid4(),
        )
        result = await record_stock_movement(
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, StockMovementResponseSchema)
        assert result.movement_number == "MOV-001"
        assert result.quantity == Decimal("100")
        mock_inventory_service.record_movement.assert_called_once()

    async def test_record_stock_movement_value_error(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        mock_inventory_service.record_movement.side_effect = ValueError("Invalid quantity")
        request = StockMovementCreateSchema(
            item_id=uuid4(),
            movement_type=MovementType.IN,
            quantity=Decimal("-100"),
            reference_type="PURCHASE_ORDER",
            warehouse_id=uuid4(),
        )
        with pytest.raises(HTTPException) as exc:
            await record_stock_movement(
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                inventory_service=mock_inventory_service,
            )
        assert exc.value.status_code == 422

    async def test_get_movement_success(self, mock_inventory_service, mock_legal_entity_id):
        movement_id = uuid4()
        result = await get_movement(
            movement_id=movement_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, StockMovementResponseSchema)
        assert result.movement_number == "MOV-001"
        mock_inventory_service.get_movement_by_id.assert_called_once_with(movement_id, mock_legal_entity_id)

    async def test_get_movement_not_found(self, mock_inventory_service, mock_legal_entity_id):
        mock_inventory_service.get_movement_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_movement(
                movement_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                inventory_service=mock_inventory_service,
            )
        assert exc.value.status_code == 404

    async def test_reverse_movement_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        movement_id = uuid4()
        result = await reverse_movement(
            movement_id=movement_id,
            reason="Error",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, StockMovementResponseSchema)
        assert result.status == MovementStatus.REVERSED
        mock_inventory_service.reverse_movement.assert_called_once_with(
            movement_id=movement_id,
            reversed_by=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
            reason="Error",
        )


# ============================================================================
# STOCK CARD TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_stock_card_success(mock_inventory_service, mock_legal_entity_id):
    item_id = uuid4()
    warehouse_id = uuid4()
    result = await get_stock_card(
        item_id=item_id,
        warehouse_id=warehouse_id,
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        inventory_service=mock_inventory_service,
    )
    assert isinstance(result, StockCardResponseSchema)
    assert result.item_id == item_id
    assert result.closing_quantity == Decimal("100")
    mock_inventory_service.get_stock_card.assert_called_once_with(
        item_id=item_id,
        warehouse_id=warehouse_id,
        legal_entity_id=mock_legal_entity_id,
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
    )


# ============================================================================
# STOCK OPNAME TESTS
# ============================================================================

@pytest.mark.asyncio
class TestStockOpname:
    async def test_create_stock_opname_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        line = StockOpnameLineSchema(item_id=uuid4(), system_quantity=Decimal("100"), physical_quantity=Decimal("95"))
        request = StockOpnameCreateSchema(
            warehouse_id=uuid4(),
            opname_date=FIXED_DATE,
            lines=[line],
            notes="Monthly",
        )
        result = await create_stock_opname(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, StockOpnameResponseSchema)
        assert result.opname_number == "OPN-001"
        mock_inventory_service.create_stock_opname.assert_called_once()

    async def test_approve_stock_opname_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        opname_id = uuid4()
        result = await approve_stock_opname(
            opname_id=opname_id,
            apply_adjustments=True,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, StockOpnameResponseSchema)
        assert result.status == StockOpnameStatus.APPROVED
        mock_inventory_service.approve_stock_opname.assert_called_once_with(
            opname_id=opname_id,
            approver_id=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
            apply_adjustments=True,
        )

    async def test_cancel_stock_opname_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        opname_id = uuid4()
        result = await cancel_stock_opname(
            opname_id=opname_id,
            reason="Cancelled",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert result["status"] == "cancelled"
        mock_inventory_service.cancel_stock_opname.assert_called_once()


# ============================================================================
# WAREHOUSE TRANSFER TESTS
# ============================================================================

@pytest.mark.asyncio
class TestWarehouseTransfer:
    async def test_create_warehouse_transfer_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        item_line = InterWarehouseTransferLineSchema(item_id=uuid4(), quantity=Decimal("50"))
        request = InterWarehouseTransferCreateSchema(
            from_warehouse_id=uuid4(),
            to_warehouse_id=uuid4(),
            transfer_date=FIXED_DATE,
            items=[item_line],
            notes="Transfer",
        )
        result = await create_warehouse_transfer(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, InterWarehouseTransferResponseSchema)
        assert result.transfer_number == "TRF-001"
        mock_inventory_service.create_warehouse_transfer.assert_called_once()

    async def test_approve_warehouse_transfer_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        transfer_id = uuid4()
        result = await approve_warehouse_transfer(
            transfer_id=transfer_id,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, InterWarehouseTransferResponseSchema)
        assert result.status == TransferStatus.APPROVED
        mock_inventory_service.approve_warehouse_transfer.assert_called_once()

    async def test_complete_warehouse_transfer_success(self, mock_inventory_service, mock_token_payload, mock_legal_entity_id):
        transfer_id = uuid4()
        result = await complete_warehouse_transfer(
            transfer_id=transfer_id,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            inventory_service=mock_inventory_service,
        )
        assert isinstance(result, InterWarehouseTransferResponseSchema)
        assert result.status == TransferStatus.COMPLETED
        mock_inventory_service.complete_warehouse_transfer.assert_called_once()


# ============================================================================
# VALUATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_inventory_valuation_by_path_success(mock_inventory_service, mock_legal_entity_id):
    item_id = uuid4()
    result = await get_inventory_valuation_by_path(
        item_id=item_id,
        as_of_date=FIXED_DATE,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        inventory_service=mock_inventory_service,
    )
    assert isinstance(result, InventoryValuationResponseSchema)
    assert result.item_id == item_id
    assert result.total_value == Decimal("100000")
    mock_inventory_service.get_valuation.assert_called_once_with(
        item_id=item_id,
        legal_entity_id=mock_legal_entity_id,
        as_of_date=FIXED_DATE,
    )


@pytest.mark.asyncio
async def test_get_inventory_valuation_query_success(mock_inventory_service, mock_legal_entity_id):
    item_id = uuid4()
    result = await get_inventory_valuation(
        item_id=item_id,
        as_of_date=FIXED_DATE,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        inventory_service=mock_inventory_service,
    )
    assert isinstance(result, InventoryValuationResponseSchema)
    assert result.item_id == item_id
    mock_inventory_service.get_valuation.assert_called_once_with(
        item_id=item_id,
        legal_entity_id=mock_legal_entity_id,
        as_of_date=FIXED_DATE,
    )


# ============================================================================
# NRV TEST TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_test_nrv_success(mock_inventory_service, mock_token_payload, mock_legal_entity_id):
    item_id = uuid4()
    result = await test_nrv(
        item_id=item_id,
        test_date=FIXED_DATE,
        nrv=Decimal("90000"),
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        inventory_service=mock_inventory_service,
    )
    assert isinstance(result, NRVTestResponseSchema)
    assert result.item_id == item_id
    assert result.impairment_loss == Decimal("10000")
    mock_inventory_service.test_nrv.assert_called_once()


# ============================================================================
# LOW STOCK ALERTS TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_low_stock_alerts_success(mock_inventory_service, mock_legal_entity_id):
    result = await get_low_stock_alerts(
        warehouse_id=uuid4(),
        include_zero_stock=True,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        inventory_service=mock_inventory_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], LowStockAlertSchema)
    assert result[0].shortage == Decimal("2")
    mock_inventory_service.get_low_stock_alerts.assert_called_once()


# ============================================================================
# WAREHOUSE LIST TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_list_warehouses_success(mock_inventory_service, mock_legal_entity_id):
    result = await list_warehouses(
        is_active=True,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        inventory_service=mock_inventory_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], WarehouseResponseSchema)
    mock_inventory_service.list_warehouses.assert_called_once()


# ============================================================================
# EXPORT TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_export_items_success(mock_inventory_service, mock_legal_entity_id):
    result = await export_items(
        format="csv",
        item_type=ItemType.RAW_MATERIAL,
        category="Materials",
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        inventory_service=mock_inventory_service,
    )
    assert isinstance(result, Response)
    assert result.body == b"csv data"
    assert result.media_type == "text/csv"
    mock_inventory_service.export_items.assert_called_once()


# ============================================================================
# INVENTORY VALUATION REPOSITORY ADAPTER TESTS
# ============================================================================

@pytest.mark.asyncio
class TestInventoryValuationRepositoryAdapter:
    @pytest.fixture
    def adapter(self):
        return InventoryValuationRepositoryAdapter()

    async def test_get_inventory_valuation_raises_not_implemented(self, adapter):
        with pytest.raises(NotImplementedError):
            await adapter.get_inventory_valuation(
                legal_entity_id=uuid4(),
                item_id=uuid4(),
                as_of_date=FIXED_DATE,
                valuation_method="FIFO"
            )

    async def test_calculate_valuation_by_product_raises_not_implemented(self, adapter):
        with pytest.raises(NotImplementedError):
            await adapter.calculate_valuation_by_product(
                legal_entity_id=uuid4(),
                product_id=uuid4(),
                as_of_date=FIXED_DATE,
                valuation_method="FIFO"
            )

    async def test_get_movement_summary_raises_not_implemented(self, adapter):
        with pytest.raises(NotImplementedError):
            await adapter.get_movement_summary(
                legal_entity_id=uuid4(),
                item_id=uuid4(),
                warehouse_id=uuid4(),
                start_date=FIXED_DATE,
                end_date=FIXED_DATE
            )

    async def test_get_reorder_report_raises_not_implemented(self, adapter):
        with pytest.raises(NotImplementedError):
            await adapter.get_reorder_report(
                legal_entity_id=uuid4(),
                warehouse_id=uuid4(),
                include_zero_stock=True
            )
