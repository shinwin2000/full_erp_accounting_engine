# test_production_routing_entity.py
# =========================================
# Lengkap: Semua test asli dipertahankan + tambahan test coverage untuk semua metode yang hilang.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.manufacturing.production_routing_entity import (
    ProductionRoutingEntity,
    ProductionRoutingRepository,
    RoutingOperation,
    RoutingStatus,
)


class TestRoutingStatus:
    """Tests for the RoutingStatus enum."""
    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(RoutingStatus, 'DRAFT')
        assert hasattr(RoutingStatus, 'ACTIVE')
        assert hasattr(RoutingStatus, 'OBSOLETE')

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(RoutingStatus.DRAFT, RoutingStatus)


class TestRoutingOperation:
    """Tests for the RoutingOperation value object / model."""

    def _build_kwargs(self):
        return {
            'operation_id': uuid4(),
            'operation_code': "OP-001",
            'operation_name': "Test Operation",
            'sequence': 1,
            'work_center_id': uuid4(),
            'work_center_name': "WC-01",
            'setup_time_hours': Decimal("1.5"),
            'run_time_per_unit_hours': Decimal("0.5"),
            'labor_cost_per_hour': Decimal("100.00"),
            'machine_cost_per_hour': Decimal("50.00"),
            'fixed_cost': Decimal("20.00"),
            'description': "Test",
        }

    def test_construction_success(self):
        """RoutingOperation can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        instance = RoutingOperation(**kwargs)
        assert isinstance(instance, RoutingOperation)
        assert instance.operation_id == kwargs['operation_id']

    # --- TAMBAHAN: Test cost calculation methods ---
    def test_get_total_labor_cost(self):
        op = RoutingOperation(
            operation_id=uuid4(),
            operation_code="OP-001",
            operation_name="Test",
            sequence=1,
            work_center_id=uuid4(),
            work_center_name="WC-01",
            setup_time_hours=Decimal("2"),
            run_time_per_unit_hours=Decimal("0.5"),
            labor_cost_per_hour=Decimal("100"),
            machine_cost_per_hour=Decimal("50"),
            fixed_cost=Decimal("0"),
        )
        # For quantity = 10: setup 2 + run 10*0.5 = 2 + 5 = 7 hours; labor = 7 * 100 = 700
        assert op.get_total_labor_cost(Decimal("10")) == Decimal("700")

    def test_get_total_machine_cost(self):
        op = RoutingOperation(
            operation_id=uuid4(),
            operation_code="OP-001",
            operation_name="Test",
            sequence=1,
            work_center_id=uuid4(),
            work_center_name="WC-01",
            setup_time_hours=Decimal("2"),
            run_time_per_unit_hours=Decimal("0.5"),
            labor_cost_per_hour=Decimal("100"),
            machine_cost_per_hour=Decimal("50"),
            fixed_cost=Decimal("0"),
        )
        # same hours = 7, machine = 7 * 50 = 350
        assert op.get_total_machine_cost(Decimal("10")) == Decimal("350")

    def test_get_total_cost(self):
        op = RoutingOperation(
            operation_id=uuid4(),
            operation_code="OP-001",
            operation_name="Test",
            sequence=1,
            work_center_id=uuid4(),
            work_center_name="WC-01",
            setup_time_hours=Decimal("2"),
            run_time_per_unit_hours=Decimal("0.5"),
            labor_cost_per_hour=Decimal("100"),
            machine_cost_per_hour=Decimal("50"),
            fixed_cost=Decimal("20"),
        )
        # total = labor 700 + machine 350 + fixed 20 = 1070
        assert op.get_total_cost(Decimal("10")) == Decimal("1070")


class TestProductionRoutingEntity:
    """Tests for the ProductionRoutingEntity value object / model."""

    def _create_sample_operation(self, seq=1, setup=Decimal("1"), run=Decimal("0.5"), labor=Decimal("100"), machine=Decimal("50"), fixed=Decimal("10")):
        return RoutingOperation(
            operation_id=uuid4(),
            operation_code=f"OP-{seq:03d}",
            operation_name=f"Operation {seq}",
            sequence=seq,
            work_center_id=uuid4(),
            work_center_name=f"WC-{seq:02d}",
            setup_time_hours=setup,
            run_time_per_unit_hours=run,
            labor_cost_per_hour=labor,
            machine_cost_per_hour=machine,
            fixed_cost=fixed,
            description=f"Step {seq}",
        )

    def _create_sample_routing(self, operations=None):
        if operations is None:
            ops = [self._create_sample_operation(1), self._create_sample_operation(2)]
        else:
            ops = operations
        return ProductionRoutingEntity(
            routing_id=uuid4(),
            routing_code="ROUTE-001",
            product_id=uuid4(),
            product_code="PROD-001",
            product_name="Test Product",
            version=1,
            operations=ops,
            status=RoutingStatus.DRAFT,
            effective_date=None,
            expiry_date=None,
            notes="Test routing",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            created_by="tester",
            version_counter=1,
        )

    def _build_kwargs(self):
        return {
            'routing_id': uuid4(),
            'routing_code': "ROU",
            'product_id': uuid4(),
            'product_code': "PC",
            'product_name': "PN",
            'version': 1,
            'operations': [],
            'status': RoutingStatus.DRAFT,
            'effective_date': datetime.now(UTC),
            'expiry_date': datetime.now(UTC),
            'notes': "test",
            'created_at': datetime.now(UTC),
            'updated_at': datetime.now(UTC),
            'created_by': "system",
            'version_counter': 1,
        }

    def test_construction_success(self):
        """ProductionRoutingEntity can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        instance = ProductionRoutingEntity(**kwargs)
        assert isinstance(instance, ProductionRoutingEntity)
        assert instance.routing_id == kwargs['routing_id']

    # --- TAMBAHAN: Test get_total_* methods ---
    def test_get_total_setup_time(self):
        routing = self._create_sample_routing()
        # operations: op1 setup=1, op2 setup=1 (from defaults) => total 2
        assert routing.get_total_setup_time() == Decimal("2")

    def test_get_total_run_time_per_unit(self):
        routing = self._create_sample_routing()
        # op1 run=0.5, op2 run=0.5 => total 1
        assert routing.get_total_run_time_per_unit() == Decimal("1")

    def test_get_total_labor_cost(self):
        routing = self._create_sample_routing()
        # op1: setup=1, run=0.5 => hours=1+10*0.5=6, labor=6*100=600
        # op2: same => 600, total 1200
        assert routing.get_total_labor_cost(Decimal("10")) == Decimal("1200")

    def test_get_total_machine_cost(self):
        routing = self._create_sample_routing()
        # op1: hours=6, machine=6*50=300, op2=300, total 600
        assert routing.get_total_machine_cost(Decimal("10")) == Decimal("600")

    def test_get_total_routing_cost(self):
        routing = self._create_sample_routing()
        # each op: labor 600 + machine 300 + fixed 10 = 910, two ops = 1820
        assert routing.get_total_routing_cost(Decimal("10")) == Decimal("1820")

    def test_get_cost_per_unit(self):
        routing = self._create_sample_routing()
        # total cost 1820 / 10 = 182
        assert routing.get_cost_per_unit(Decimal("10")) == Decimal("182")
        # quantity zero => 0
        assert routing.get_cost_per_unit(Decimal("0")) == Decimal("0")

    # --- TAMBAHAN: Test add_operation ---
    def test_add_operation(self):
        routing = self._create_sample_routing()
        new_op = self._create_sample_operation(seq=3)
        new_routing = routing.add_operation(new_op, "tester")
        assert len(new_routing.operations) == 3
        assert new_routing.operations[-1].sequence == 3
        assert new_routing.version_counter == routing.version_counter + 1
        assert new_routing.updated_at > routing.updated_at

    # --- TAMBAHAN: Test remove_operation ---
    def test_remove_operation(self):
        routing = self._create_sample_routing()
        op_id = routing.operations[0].operation_id
        new_routing = routing.remove_operation(op_id, "tester")
        assert len(new_routing.operations) == 1
        assert new_routing.operations[0].operation_id != op_id
        assert new_routing.version_counter == routing.version_counter + 1

    # --- TAMBAHAN: Test update_operation ---
    def test_update_operation(self):
        routing = self._create_sample_routing()
        op_id = routing.operations[0].operation_id
        new_routing = routing.update_operation(
            op_id,
            new_setup_time=Decimal("5"),
            new_run_time=Decimal("1"),
            new_labor_rate=Decimal("200"),
            new_machine_rate=Decimal("100"),
            new_fixed_cost=Decimal("50"),
            updated_by="updater",
        )
        updated_op = new_routing.operations[0]
        assert updated_op.setup_time_hours == Decimal("5")
        assert updated_op.run_time_per_unit_hours == Decimal("1")
        assert updated_op.labor_cost_per_hour == Decimal("200")
        assert updated_op.machine_cost_per_hour == Decimal("100")
        assert updated_op.fixed_cost == Decimal("50")
        assert new_routing.version_counter == routing.version_counter + 1

    # --- TAMBAHAN: Test activate ---
    def test_activate(self):
        routing = self._create_sample_routing()
        datetime.now(UTC)
        new_routing = routing.activate("activator")
        assert new_routing.status == RoutingStatus.ACTIVE
        assert new_routing.effective_date is not None
        assert new_routing.version_counter == routing.version_counter + 1

    # --- TAMBAHAN: Test obsoleted ---
    def test_obsoleted(self):
        routing = self._create_sample_routing()
        new_routing = routing.obsoleted("obsoleter", "Reason for obsolescence")
        assert new_routing.status == RoutingStatus.OBSOLETE
        assert new_routing.expiry_date is not None
        assert "Obsoleted: Reason for obsolescence" in new_routing.notes
        assert new_routing.version_counter == routing.version_counter + 1

    # --- TAMBAHAN: Test increment_version ---
    def test_increment_version(self):
        routing = self._create_sample_routing()
        new_routing = routing.increment_version(2, "versioner")
        assert new_routing.version == 2
        assert new_routing.status == RoutingStatus.DRAFT
        assert new_routing.effective_date is None
        assert new_routing.expiry_date is None
        assert new_routing.version_counter == routing.version_counter + 1

    # --- TAMBAHAN: Test is_active_at ---
    def test_is_active_at_active(self):
        routing = self._create_sample_routing()
        now = datetime.now(UTC)
        # Activate first
        active = routing.activate("activator")
        # Effective date is now, so should be active
        assert active.is_active_at(now + timedelta(seconds=1)) is True
        # Before effective date
        assert active.is_active_at(now - timedelta(seconds=1)) is False

    def test_is_active_at_with_expiry(self):
        routing = self._create_sample_routing()
        now = datetime.now(UTC)
        routing.activate("activator")
        # Manually set expiry date by obsoleting? Better: we can create a routing with expiry date.
        # Since we can't set expiry directly, we can use update? Actually, we can create a new routing with expiry.
        # But we'll test that if expiry is set, it works.
        # We'll create a new instance with expiry date in future.
        now + timedelta(days=30)
        # We don't have a setter, so we'll use the obsoleted method which sets expiry to now.
        # So we need a routing that is active and has expiry in future. We can create a routing manually.
        op = self._create_sample_operation()
        routing_with_expiry = ProductionRoutingEntity(
            routing_id=uuid4(),
            routing_code="ROUTE-002",
            product_id=uuid4(),
            product_code="PROD-002",
            product_name="Test",
            version=1,
            operations=[op],
            status=RoutingStatus.ACTIVE,
            effective_date=now - timedelta(days=1),
            expiry_date=now + timedelta(days=30),
            notes="",
            created_at=now,
            updated_at=now,
            created_by="tester",
            version_counter=1,
        )
        assert routing_with_expiry.is_active_at(now) is True
        assert routing_with_expiry.is_active_at(now + timedelta(days=60)) is False

    def test_is_active_at_not_active(self):
        routing = self._create_sample_routing()
        # DRAFT status, should return False
        assert routing.is_active_at(datetime.now(UTC)) is False


class TestProductionRoutingRepository:
    """Tests for ProductionRoutingRepository."""

    def _build_instance(self):
        return ProductionRoutingRepository()

    def test_construction(self):
        """ProductionRoutingRepository can be instantiated."""
        instance = self._build_instance()
        assert isinstance(instance, ProductionRoutingRepository)

    async def test_get_by_id_smoke(self):
        """Smoke test for ProductionRoutingRepository.get_by_id."""
        instance = self._build_instance()
        # Should raise NotImplementedError
        with pytest.raises(NotImplementedError):
            await instance.get_by_id(routing_id=uuid4(), legal_entity_id=uuid4())

    async def test_get_by_code_smoke(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.get_by_code(routing_code="test", legal_entity_id=uuid4())

    async def test_get_by_product_smoke(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.get_by_product(product_id=uuid4(), legal_entity_id=uuid4())

    async def test_save_smoke(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.save(routing=MagicMock(), legal_entity_id=uuid4())

    async def test_delete_smoke(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.delete(routing_id=uuid4(), legal_entity_id=uuid4())
