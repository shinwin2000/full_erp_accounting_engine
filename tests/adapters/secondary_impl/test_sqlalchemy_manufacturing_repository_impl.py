# tests/adapters/secondary_impl/test_sqlalchemy_manufacturing_repository_impl.py
"""
Comprehensive tests for sqlalchemy_manufacturing_repository_impl.py.

Covers:
- Repository initialization and session/legal_entity_id management
- All mapping methods: _bom_to_domain, _bom_from_domain, _wo_to_domain, _wo_from_domain,
  _cost_card_to_domain, _cost_card_from_domain, _wip_to_domain
- BOM operations: save_bom, get_bom_by_id, get_active_bom, get_bom_by_product_and_version,
  list_boms_by_product
- Work Order operations: save_work_order, get_work_order, get_work_order_by_number,
  list_work_orders_by_product, list_completed_work_orders, get_last_work_order_number,
  count_work_orders_by_status
- WIP operations: save_wip, get_wip_by_work_order, list_open_wip
- Cost Card operations: save_cost_card, get_cost_card, get_cost_card_by_id,
  list_cost_cards_by_product
- Standard Cost operations: save_standard_cost, get_standard_cost_by_product,
  get_standard_cost_by_id
- Period operations: close_period, is_period_closed
- Batch operations: save_bom_batch, save_work_order_batch
- All exceptions and edge cases: not found, deleted records, invalid legal_entity_id
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from adapters.secondary_impl.sqlalchemy_manufacturing_repository_impl import (
    SQLAlchemyManufacturingRepository,
)
from domain.manufacturing.bill_of_materials_entity import BillOfMaterialsEntity, BOMStatus
from domain.manufacturing.cost_card_entity import CostCardEntity
from domain.manufacturing.standard_cost_entity import StandardCostEntity, StandardCostStatus
from domain.manufacturing.work_in_process_entity import WIPStatus, WorkInProcessEntity
from domain.manufacturing.work_order_entity import WorkOrderEntity, WorkOrderStatus
from infrastructure.persistence_orm.bill_of_materials_table import BillOfMaterialsTable
from infrastructure.persistence_orm.manufacturing_cost_card_table import ManufacturingCostCardTable
from infrastructure.persistence_orm.manufacturing_work_order_table import (
    ManufacturingWorkOrderTable,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.get = AsyncMock()
    session.execute = AsyncMock()
    session.add = AsyncMock()
    session.flush = AsyncMock()
    # session.begin jika diperlukan
    return session


@pytest.fixture
def mock_get_async_session():
    with patch(
        "adapters.secondary_impl.sqlalchemy_manufacturing_repository_impl.get_async_session"
    ) as mock:
        mock.return_value = AsyncMock()
        yield mock


@pytest.fixture
def repo(mock_session, legal_entity_id) -> SQLAlchemyManufacturingRepository:
    return SQLAlchemyManufacturingRepository(session=mock_session, legal_entity_id=legal_entity_id)


@pytest.fixture
def sample_bom(legal_entity_id) -> BillOfMaterialsEntity:
    return BillOfMaterialsEntity(
        id=uuid4(),
        product_id=uuid4(),
        product_code="PROD-001",
        product_name="Test Product",
        version=1,
        status=BOMStatus.DRAFT,
        effective_date=date(2025, 1, 1),
        expiry_date=date(2025, 12, 31),
        is_active=False,
        created_by=uuid4(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@pytest.fixture
def sample_work_order(legal_entity_id) -> WorkOrderEntity:
    return WorkOrderEntity(
        id=uuid4(),
        work_order_number="WO-001",
        product_id=uuid4(),
        product_code="PROD-001",
        product_name="Test Product",
        planned_quantity=Decimal("100"),
        completed_quantity=Decimal("0"),
        status=WorkOrderStatus.DRAFT,
        bom_id=uuid4(),
        start_date=date(2025, 1, 1),
        due_date=date(2025, 2, 1),
        completed_at=None,
        material_cost=Decimal("0"),
        labor_cost=Decimal("0"),
        overhead_cost=Decimal("0"),
        created_by=uuid4(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@pytest.fixture
def sample_cost_card(legal_entity_id) -> CostCardEntity:
    return CostCardEntity(
        id=uuid4(),
        product_id=uuid4(),
        product_code="PROD-001",
        product_name="Test Product",
        period="2025-01",
        material_cost=Decimal("100"),
        labor_cost=Decimal("50"),
        overhead_cost=Decimal("20"),
        total_cost=Decimal("170"),
        is_active=True,
        created_by=uuid4(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@pytest.fixture
def sample_wip(legal_entity_id, sample_work_order) -> WorkInProcessEntity:
    return WorkInProcessEntity(
        id=uuid4(),
        work_order_id=sample_work_order.id,
        work_order_number=sample_work_order.work_order_number,
        product_id=sample_work_order.product_id,
        product_code=sample_work_order.product_code,
        product_name=sample_work_order.product_name,
        quantity_started=Decimal("50"),
        quantity_completed=Decimal("10"),
        status=WIPStatus.OPEN,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@pytest.fixture
def sample_standard_cost(legal_entity_id) -> StandardCostEntity:
    return StandardCostEntity(
        id=uuid4(),
        product_id=uuid4(),
        product_code="PROD-001",
        product_name="Test Product",
        unit_cost=Decimal("100"),
        total_cost=Decimal("100"),
        effective_date=date(2025, 1, 1),
        period="2025-01",
        status=StandardCostStatus.ACTIVE,
        created_by=uuid4(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


# ============================================================================
# Tests for initialization and helpers
# ============================================================================

class TestRepositoryInit:
    def test_init_with_session_and_legal_entity(self, mock_session, legal_entity_id):
        repo = SQLAlchemyManufacturingRepository(session=mock_session, legal_entity_id=legal_entity_id)
        assert repo._session == mock_session
        assert repo._legal_entity_id == legal_entity_id

    def test_init_without_session(self, mock_get_async_session, legal_entity_id):
        repo = SQLAlchemyManufacturingRepository(legal_entity_id=legal_entity_id)
        assert repo._session is None
        # _get_session will lazily create
        session = repo._get_session()
        assert session is not None

    def test_get_legal_entity_id_raises_if_not_set(self):
        repo = SQLAlchemyManufacturingRepository()
        with pytest.raises(ValueError, match="legal_entity_id not set"):
            repo._get_legal_entity_id()


# ============================================================================
# Tests for mapping methods
# ============================================================================

class TestMappingMethods:
    def test_bom_to_domain(self, repo, sample_bom):
        table = BillOfMaterialsTable(
            id=sample_bom.id,
            product_id=sample_bom.product_id,
            product_code=sample_bom.product_code,
            product_name=sample_bom.product_name,
            version=sample_bom.version,
            status="draft",
            effective_date=sample_bom.effective_date,
            expiry_date=sample_bom.expiry_date,
            is_active=sample_bom.is_active,
            created_by=sample_bom.created_by,
            created_at=sample_bom.created_at,
            updated_at=sample_bom.updated_at,
        )
        domain = repo._bom_to_domain(table)
        assert domain.id == table.id
        assert domain.product_id == table.product_id
        assert domain.status == BOMStatus.DRAFT
        assert domain.effective_date == table.effective_date

    def test_bom_from_domain(self, repo, sample_bom):
        table = repo._bom_from_domain(sample_bom)
        assert table.id == sample_bom.id
        assert table.product_id == sample_bom.product_id
        assert table.status == "draft"
        assert table.legal_entity_id == repo._get_legal_entity_id()

    def test_wo_to_domain(self, repo, sample_work_order):
        table = ManufacturingWorkOrderTable(
            id=sample_work_order.id,
            work_order_number=sample_work_order.work_order_number,
            product_id=sample_work_order.product_id,
            product_code=sample_work_order.product_code,
            product_name=sample_work_order.product_name,
            planned_quantity=sample_work_order.planned_quantity,
            completed_quantity=sample_work_order.completed_quantity,
            status="draft",
            bom_id=sample_work_order.bom_id,
            start_date=sample_work_order.start_date,
            due_date=sample_work_order.due_date,
            completed_at=sample_work_order.completed_at,
            material_cost=sample_work_order.material_cost,
            labor_cost=sample_work_order.labor_cost,
            overhead_cost=sample_work_order.overhead_cost,
            created_by=sample_work_order.created_by,
            created_at=sample_work_order.created_at,
            updated_at=sample_work_order.updated_at,
        )
        domain = repo._wo_to_domain(table)
        assert domain.id == table.id
        assert domain.work_order_number == table.work_order_number
        assert domain.status == WorkOrderStatus.DRAFT

    def test_wo_from_domain(self, repo, sample_work_order):
        table = repo._wo_from_domain(sample_work_order)
        assert table.id == sample_work_order.id
        assert table.work_order_number == sample_work_order.work_order_number
        assert table.status == "draft"
        assert table.legal_entity_id == repo._get_legal_entity_id()

    def test_cost_card_to_domain(self, repo, sample_cost_card):
        table = ManufacturingCostCardTable(
            id=sample_cost_card.id,
            product_id=sample_cost_card.product_id,
            product_code=sample_cost_card.product_code,
            product_name=sample_cost_card.product_name,
            period=sample_cost_card.period,
            material_cost=sample_cost_card.material_cost,
            labor_cost=sample_cost_card.labor_cost,
            overhead_cost=sample_cost_card.overhead_cost,
            total_cost=sample_cost_card.total_cost,
            is_active=sample_cost_card.is_active,
            created_by=sample_cost_card.created_by,
            created_at=sample_cost_card.created_at,
            updated_at=sample_cost_card.updated_at,
        )
        domain = repo._cost_card_to_domain(table)
        assert domain.id == table.id
        assert domain.period == table.period
        assert domain.total_cost == table.total_cost

    def test_cost_card_from_domain(self, repo, sample_cost_card):
        table = repo._cost_card_from_domain(sample_cost_card)
        assert table.id == sample_cost_card.id
        assert table.period == sample_cost_card.period
        assert table.legal_entity_id == repo._get_legal_entity_id()

    def test_wip_to_domain(self, repo, sample_work_order):
        # Use a work order with status "in_progress"
        table = ManufacturingWorkOrderTable(
            id=sample_work_order.id,
            work_order_number=sample_work_order.work_order_number,
            product_id=sample_work_order.product_id,
            product_code=sample_work_order.product_code,
            product_name=sample_work_order.product_name,
            planned_quantity=Decimal("100"),
            completed_quantity=Decimal("30"),
            status="in_progress",
            bom_id=sample_work_order.bom_id,
            start_date=sample_work_order.start_date,
            due_date=sample_work_order.due_date,
            created_at=sample_work_order.created_at,
            updated_at=sample_work_order.updated_at,
        )
        wip = repo._wip_to_domain(table)
        assert wip.work_order_id == table.id
        assert wip.quantity_started == Decimal("70")  # planned - completed
        assert wip.quantity_completed == Decimal("30")
        assert wip.status == WIPStatus.OPEN

        # Test with status "completed"
        table.status = "completed"
        wip2 = repo._wip_to_domain(table)
        assert wip2.status == WIPStatus.CLOSED


# ============================================================================
# BOM tests
# ============================================================================

class TestBOMOperations:
    @pytest.mark.asyncio
    async def test_save_bom_new(self, repo, mock_session, sample_bom):
        mock_session.get.return_value = None
        await repo.save_bom(sample_bom)
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_bom_existing(self, repo, mock_session, sample_bom):
        existing_table = BillOfMaterialsTable(id=sample_bom.id)
        mock_session.get.return_value = existing_table
        await repo.save_bom(sample_bom)
        mock_session.add.assert_not_called()
        mock_session.flush.assert_called_once()
        # Check that update happened
        assert existing_table.product_code == sample_bom.product_code

    @pytest.mark.asyncio
    async def test_get_bom_by_id_found(self, repo, mock_session, sample_bom):
        table = BillOfMaterialsTable(
            id=sample_bom.id,
            product_id=sample_bom.product_id,
            product_code=sample_bom.product_code,
            product_name=sample_bom.product_name,
            version=sample_bom.version,
            status="draft",
            effective_date=sample_bom.effective_date,
            expiry_date=sample_bom.expiry_date,
            is_active=sample_bom.is_active,
            created_by=sample_bom.created_by,
            created_at=sample_bom.created_at,
            updated_at=sample_bom.updated_at,
            deleted_at=None,
        )
        mock_session.get.return_value = table
        result = await repo.get_bom_by_id(sample_bom.id)
        assert result is not None
        assert result.id == sample_bom.id

    @pytest.mark.asyncio
    async def test_get_bom_by_id_not_found(self, repo, mock_session):
        mock_session.get.return_value = None
        result = await repo.get_bom_by_id(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_bom_by_id_deleted(self, repo, mock_session, sample_bom):
        table = BillOfMaterialsTable(id=sample_bom.id, deleted_at=datetime.utcnow())
        mock_session.get.return_value = table
        result = await repo.get_bom_by_id(sample_bom.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_bom_found(self, repo, mock_session, sample_bom):
        table = BillOfMaterialsTable(
            id=sample_bom.id,
            product_id=sample_bom.product_id,
            product_code=sample_bom.product_code,
            product_name=sample_bom.product_name,
            version=sample_bom.version,
            status="active",
            effective_date=date(2025, 1, 1),
            expiry_date=date(2025, 12, 31),
            is_active=True,
            created_by=sample_bom.created_by,
            created_at=sample_bom.created_at,
            updated_at=sample_bom.updated_at,
            deleted_at=None,
        )
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = table
        mock_session.execute.return_value = mock_result
        result = await repo.get_active_bom(sample_bom.product_id, as_of_date=date(2025, 6, 1))
        assert result is not None
        assert result.id == sample_bom.id

    @pytest.mark.asyncio
    async def test_get_active_bom_expired(self, repo, mock_session, sample_bom):
        table = BillOfMaterialsTable(
            id=sample_bom.id,
            product_id=sample_bom.product_id,
            product_code=sample_bom.product_code,
            product_name=sample_bom.product_name,
            is_active=True,
            effective_date=date(2025, 1, 1),
            expiry_date=date(2025, 3, 1),
            deleted_at=None,
        )
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = table
        mock_session.execute.return_value = mock_result
        result = await repo.get_active_bom(sample_bom.product_id, as_of_date=date(2025, 6, 1))
        assert result is None  # expired

    @pytest.mark.asyncio
    async def test_get_bom_by_product_and_version_found(self, repo, mock_session, sample_bom):
        table = BillOfMaterialsTable(
            id=sample_bom.id,
            product_id=sample_bom.product_id,
            product_code=sample_bom.product_code,
            product_name=sample_bom.product_name,
            version=2,
            deleted_at=None,
        )
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = table
        mock_session.execute.return_value = mock_result
        result = await repo.get_bom_by_product_and_version(sample_bom.product_id, 2)
        assert result is not None
        assert result.id == sample_bom.id

    @pytest.mark.asyncio
    async def test_list_boms_by_product(self, repo, mock_session, sample_bom):
        table = BillOfMaterialsTable(
            id=sample_bom.id,
            product_id=sample_bom.product_id,
            product_code=sample_bom.product_code,
            product_name=sample_bom.product_name,
            version=1,
            deleted_at=None,
        )
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [table]
        mock_session.execute.return_value = mock_result
        results = await repo.list_boms_by_product(sample_bom.product_id, limit=10, offset=0)
        assert len(results) == 1
        assert results[0].id == sample_bom.id


# ============================================================================
# Work Order tests
# ============================================================================

class TestWorkOrderOperations:
    @pytest.mark.asyncio
    async def test_save_work_order_new(self, repo, mock_session, sample_work_order):
        mock_session.get.return_value = None
        await repo.save_work_order(sample_work_order)
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_work_order_existing(self, repo, mock_session, sample_work_order):
        existing = ManufacturingWorkOrderTable(id=sample_work_order.id)
        mock_session.get.return_value = existing
        await repo.save_work_order(sample_work_order)
        mock_session.add.assert_not_called()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_work_order_found(self, repo, mock_session, sample_work_order):
        table = ManufacturingWorkOrderTable(
            id=sample_work_order.id,
            work_order_number=sample_work_order.work_order_number,
            product_id=sample_work_order.product_id,
            status="draft",
            deleted_at=None,
        )
        mock_session.get.return_value = table
        result = await repo.get_work_order(sample_work_order.id)
        assert result is not None
        assert result.id == sample_work_order.id

    @pytest.mark.asyncio
    async def test_get_work_order_not_found(self, repo, mock_session):
        mock_session.get.return_value = None
        result = await repo.get_work_order(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_work_order_by_number_found(self, repo, mock_session, sample_work_order):
        table = ManufacturingWorkOrderTable(
            id=sample_work_order.id,
            work_order_number=sample_work_order.work_order_number,
            product_id=sample_work_order.product_id,
            status="draft",
            deleted_at=None,
        )
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = table
        mock_session.execute.return_value = mock_result
        result = await repo.get_work_order_by_number(sample_work_order.work_order_number)
        assert result is not None

    @pytest.mark.asyncio
    async def test_list_work_orders_by_product(self, repo, mock_session, sample_work_order):
        table = ManufacturingWorkOrderTable(
            id=sample_work_order.id,
            work_order_number=sample_work_order.work_order_number,
            product_id=sample_work_order.product_id,
            status="draft",
            deleted_at=None,
        )
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [table]
        mock_session.execute.return_value = mock_result
        results = await repo.list_work_orders_by_product(
            sample_work_order.product_id, limit=10, offset=0
        )
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_list_work_orders_by_product_with_filters(self, repo, mock_session):
        # Just ensure filters don't break
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        results = await repo.list_work_orders_by_product(
            product_id=uuid4(),
            from_date=date(2025, 1, 1),
            to_date=date(2025, 2, 1),
            status=WorkOrderStatus.APPROVED,
            limit=5,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_list_completed_work_orders(self, repo, mock_session, sample_work_order):
        table = ManufacturingWorkOrderTable(
            id=sample_work_order.id,
            work_order_number=sample_work_order.work_order_number,
            product_id=sample_work_order.product_id,
            status="completed",
            completed_at=datetime.utcnow(),
            deleted_at=None,
        )
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [table]
        mock_session.execute.return_value = mock_result
        results = await repo.list_completed_work_orders(
            legal_entity_id=uuid4(), from_date=date(2025, 1, 1), to_date=date(2025, 2, 1)
        )
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_last_work_order_number(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = "WO-099"
        mock_session.execute.return_value = mock_result
        result = await repo.get_last_work_order_number()
        assert result == "WO-099"

    @pytest.mark.asyncio
    async def test_count_work_orders_by_status(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_result
        count = await repo.count_work_orders_by_status(WorkOrderStatus.APPROVED, uuid4())
        assert count == 5


# ============================================================================
# WIP tests
# ============================================================================

class TestWIPOperations:
    @pytest.mark.asyncio
    async def test_save_wip_updates_work_order(self, repo, mock_session, sample_wip, sample_work_order):
        wo_table = ManufacturingWorkOrderTable(id=sample_wip.work_order_id)
        mock_session.get.return_value = wo_table
        await repo.save_wip(sample_wip)
        assert wo_table.completed_quantity == sample_wip.quantity_completed
        assert wo_table.status == "in_progress"
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_wip_work_order_not_found(self, repo, mock_session, sample_wip):
        mock_session.get.return_value = None
        with pytest.raises(ValueError, match="Work order .* not found"):
            await repo.save_wip(sample_wip)

    @pytest.mark.asyncio
    async def test_get_wip_by_work_order_found(self, repo, mock_session, sample_work_order):
        wo_table = ManufacturingWorkOrderTable(
            id=sample_work_order.id,
            work_order_number=sample_work_order.work_order_number,
            product_id=sample_work_order.product_id,
            product_code=sample_work_order.product_code,
            product_name=sample_work_order.product_name,
            planned_quantity=Decimal("100"),
            completed_quantity=Decimal("30"),
            status="in_progress",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            deleted_at=None,
        )
        mock_session.get.return_value = wo_table
        result = await repo.get_wip_by_work_order(sample_work_order.id)
        assert result is not None
        assert result.work_order_id == sample_work_order.id
        assert result.quantity_started == Decimal("70")

    @pytest.mark.asyncio
    async def test_list_open_wip(self, repo, mock_session):
        table1 = ManufacturingWorkOrderTable(
            id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="P1",
            product_name="P1",
            planned_quantity=Decimal("100"),
            completed_quantity=Decimal("0"),
            status="in_progress",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            deleted_at=None,
        )
        table2 = ManufacturingWorkOrderTable(
            id=uuid4(),
            work_order_number="WO-002",
            product_id=uuid4(),
            product_code="P2",
            product_name="P2",
            planned_quantity=Decimal("50"),
            completed_quantity=Decimal("50"),
            status="approved",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            deleted_at=None,
        )
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [table1, table2]
        mock_session.execute.return_value = mock_result
        results = await repo.list_open_wip(legal_entity_id=uuid4())
        assert len(results) == 2


# ============================================================================
# Cost Card tests
# ============================================================================

class TestCostCardOperations:
    @pytest.mark.asyncio
    async def test_save_cost_card_new(self, repo, mock_session, sample_cost_card):
        mock_session.get.return_value = None
        await repo.save_cost_card(sample_cost_card)
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_cost_card_existing(self, repo, mock_session, sample_cost_card):
        existing = ManufacturingCostCardTable(id=sample_cost_card.id)
        mock_session.get.return_value = existing
        await repo.save_cost_card(sample_cost_card)
        mock_session.add.assert_not_called()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_cost_card_found(self, repo, mock_session, sample_cost_card):
        table = ManufacturingCostCardTable(
            id=sample_cost_card.id,
            product_id=sample_cost_card.product_id,
            product_code=sample_cost_card.product_code,
            product_name=sample_cost_card.product_name,
            period=sample_cost_card.period,
            material_cost=sample_cost_card.material_cost,
            labor_cost=sample_cost_card.labor_cost,
            overhead_cost=sample_cost_card.overhead_cost,
            total_cost=sample_cost_card.total_cost,
            is_active=sample_cost_card.is_active,
            created_by=sample_cost_card.created_by,
            created_at=sample_cost_card.created_at,
            updated_at=sample_cost_card.updated_at,
            deleted_at=None,
        )
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = table
        mock_session.execute.return_value = mock_result
        result = await repo.get_cost_card(sample_cost_card.product_id, sample_cost_card.period)
        assert result is not None
        assert result.id == sample_cost_card.id

    @pytest.mark.asyncio
    async def test_get_cost_card_by_id_found(self, repo, mock_session, sample_cost_card):
        table = ManufacturingCostCardTable(
            id=sample_cost_card.id,
            product_id=sample_cost_card.product_id,
            period=sample_cost_card.period,
            deleted_at=None,
        )
        mock_session.get.return_value = table
        result = await repo.get_cost_card_by_id(sample_cost_card.id)
        assert result is not None

    @pytest.mark.asyncio
    async def test_list_cost_cards_by_product(self, repo, mock_session, sample_cost_card):
        table = ManufacturingCostCardTable(
            id=sample_cost_card.id,
            product_id=sample_cost_card.product_id,
            period=sample_cost_card.period,
            deleted_at=None,
        )
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [table]
        mock_session.execute.return_value = mock_result
        results = await repo.list_cost_cards_by_product(sample_cost_card.product_id, limit=10)
        assert len(results) == 1


# ============================================================================
# Standard Cost tests
# ============================================================================

class TestStandardCostOperations:
    @pytest.mark.asyncio
    async def test_save_standard_cost_new(self, repo, mock_session, sample_standard_cost):
        # Mock existing standard cost card not found
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        await repo.save_standard_cost(sample_standard_cost)
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_standard_cost_existing(self, repo, mock_session, sample_standard_cost):
        existing = ManufacturingCostCardTable(id=sample_standard_cost.id)
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result
        await repo.save_standard_cost(sample_standard_cost)
        mock_session.add.assert_not_called()
        mock_session.flush.assert_called_once()
        assert existing.unit_cost == sample_standard_cost.unit_cost

    @pytest.mark.asyncio
    async def test_get_standard_cost_by_product_found(self, repo, mock_session, sample_standard_cost):
        table = ManufacturingCostCardTable(
            id=sample_standard_cost.id,
            product_id=sample_standard_cost.product_id,
            product_code=sample_standard_cost.product_code,
            product_name=sample_standard_cost.product_name,
            unit_cost=sample_standard_cost.unit_cost,
            total_cost=sample_standard_cost.total_cost,
            effective_date=sample_standard_cost.effective_date,
            period=sample_standard_cost.period,
            is_active=True,
            cost_type="standard",
            created_by=sample_standard_cost.created_by,
            created_at=sample_standard_cost.created_at,
            updated_at=sample_standard_cost.updated_at,
            deleted_at=None,
        )
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = table
        mock_session.execute.return_value = mock_result
        result = await repo.get_standard_cost_by_product(sample_standard_cost.product_id)
        assert result is not None
        assert result.id == sample_standard_cost.id

    @pytest.mark.asyncio
    async def test_get_standard_cost_by_id_found(self, repo, mock_session, sample_standard_cost):
        table = ManufacturingCostCardTable(
            id=sample_standard_cost.id,
            product_id=sample_standard_cost.product_id,
            cost_type="standard",
            deleted_at=None,
        )
        mock_session.get.return_value = table
        result = await repo.get_standard_cost_by_id(sample_standard_cost.id)
        assert result is not None


# ============================================================================
# Period operations tests
# ============================================================================

class TestPeriodOperations:
    @pytest.mark.asyncio
    async def test_close_period(self, repo, mock_session):
        mock_session.execute.return_value = AsyncMock()
        await repo.close_period(legal_entity_id=uuid4(), period="2025-01", user_id=uuid4())
        mock_session.execute.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_period_closed_true(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar.return_value = 0
        mock_session.execute.return_value = mock_result
        result = await repo.is_period_closed(legal_entity_id=uuid4(), period="2025-01")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_period_closed_false(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_result
        result = await repo.is_period_closed(legal_entity_id=uuid4(), period="2025-01")
        assert result is False


# ============================================================================
# Batch operations tests
# ============================================================================

class TestBatchOperations:
    @pytest.mark.asyncio
    async def test_save_bom_batch_empty(self, repo, mock_session):
        await repo.save_bom_batch([])
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_bom_batch_new(self, repo, mock_session, sample_bom):
        # Mock existing_map empty
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        await repo.save_bom_batch([sample_bom])
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_work_order_batch_empty(self, repo, mock_session):
        await repo.save_work_order_batch([])
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_work_order_batch_new(self, repo, mock_session, sample_work_order):
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        await repo.save_work_order_batch([sample_work_order])
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()


# ============================================================================
# Additional edge cases
# ============================================================================

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_get_standard_cost_by_product_not_found(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        result = await repo.get_standard_cost_by_product(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_standard_cost_by_id_not_found(self, repo, mock_session):
        mock_session.get.return_value = None
        result = await repo.get_standard_cost_by_id(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_standard_cost_by_id_not_standard(self, repo, mock_session, sample_standard_cost):
        table = ManufacturingCostCardTable(
            id=sample_standard_cost.id,
            product_id=sample_standard_cost.product_id,
            cost_type="actual",  # not standard
            deleted_at=None,
        )
        mock_session.get.return_value = table
        result = await repo.get_standard_cost_by_id(sample_standard_cost.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_bom_from_domain_with_none_status(self, repo, sample_bom):
        # Test status conversion when status is None (should default)
        sample_bom.status = None
        table = repo._bom_from_domain(sample_bom)
        assert table.status == "draft"