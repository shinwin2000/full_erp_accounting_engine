# test_standard_cost_entity.py
# =========================================
# Lengkap: Semua test asli dipertahankan + tambahan test coverage untuk semua metode yang hilang.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.manufacturing.cost_element_enum import CostElement
from domain.manufacturing.standard_cost_entity import (
    StandardCost,
    StandardCostComponent,
    StandardCostEntity,
    StandardCostRepository,
    StandardCostStatus,
)


class TestStandardCostStatus:
    """Tests for the StandardCostStatus enum."""
    def test_members_exist(self):
        assert hasattr(StandardCostStatus, 'DRAFT')
        assert hasattr(StandardCostStatus, 'ACTIVE')
        assert hasattr(StandardCostStatus, 'OBSOLETE')

    def test_member_is_instance(self):
        assert isinstance(StandardCostStatus.DRAFT, StandardCostStatus)


class TestStandardCostComponent:
    """Tests for StandardCostComponent."""

    def test_construction_success(self):
        comp = StandardCostComponent(
            cost_element=CostElement.MATERIAL,
            amount=Decimal("100"),
            quantity=Decimal("2"),
            unit_cost=Decimal("50"),
            notes="test",
        )
        assert comp.cost_element == CostElement.MATERIAL
        assert comp.amount == Decimal("100")

    def test_validation_negative_amount(self):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            StandardCostComponent(
                cost_element=CostElement.MATERIAL,
                amount=Decimal("-1"),
            )

    def test_validation_negative_quantity(self):
        with pytest.raises(ValueError, match="Quantity cannot be negative"):
            StandardCostComponent(
                cost_element=CostElement.MATERIAL,
                amount=Decimal("10"),
                quantity=Decimal("-1"),
            )

    def test_validation_negative_unit_cost(self):
        with pytest.raises(ValueError, match="Unit cost cannot be negative"):
            StandardCostComponent(
                cost_element=CostElement.MATERIAL,
                amount=Decimal("10"),
                unit_cost=Decimal("-1"),
            )

    def test_to_dict(self):
        comp = StandardCostComponent(
            cost_element=CostElement.MATERIAL,
            amount=Decimal("100"),
            quantity=Decimal("2"),
            unit_cost=Decimal("50"),
            notes="test",
        )
        d = comp.to_dict()
        assert d["cost_element"] == "material"
        assert d["amount"] == "100"
        assert d["quantity"] == "2"
        assert d["unit_cost"] == "50"
        assert d["notes"] == "test"


class TestStandardCostEntity:
    """Tests for StandardCostEntity."""

    def _create_valid_instance(self, effective_date=None):
        if effective_date is None:
            effective_date = datetime.now(UTC)
        return StandardCostEntity(
            standard_cost_id=uuid4(),
            product_id=uuid4(),
            product_code="PROD-001",
            product_name="Test Product",
            version=1,
            effective_date=effective_date,
            material_cost=Decimal("100"),
            labor_cost=Decimal("50"),
            overhead_cost=Decimal("30"),
            total_cost=Decimal("180"),
            components=[
                StandardCostComponent(
                    cost_element=CostElement.MATERIAL,
                    amount=Decimal("100"),
                ),
                StandardCostComponent(
                    cost_element=CostElement.LABOR,
                    amount=Decimal("50"),
                ),
                StandardCostComponent(
                    cost_element=CostElement.OVERHEAD,
                    amount=Decimal("30"),
                ),
            ],
            status=StandardCostStatus.DRAFT,
            expiry_date=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            created_by="tester",
            version_counter=1,
        )

    def test_construction_success(self):
        instance = self._create_valid_instance()
        assert isinstance(instance, StandardCostEntity)
        assert instance.total_cost == Decimal("180")

    def test_validation_version_less_than_1(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            StandardCostEntity(
                standard_cost_id=uuid4(),
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                version=0,
                effective_date=datetime.now(UTC),
                material_cost=Decimal(0),
                labor_cost=Decimal(0),
                overhead_cost=Decimal(0),
                total_cost=Decimal(0),
            )

    def test_validation_negative_material_cost(self):
        with pytest.raises(ValueError, match="Material cost cannot be negative"):
            StandardCostEntity(
                standard_cost_id=uuid4(),
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                version=1,
                effective_date=datetime.now(UTC),
                material_cost=Decimal("-1"),
                labor_cost=Decimal(0),
                overhead_cost=Decimal(0),
                total_cost=Decimal(0),
            )

    def test_validation_total_cost_mismatch(self):
        with pytest.raises(ValueError, match="Total cost mismatch"):
            StandardCostEntity(
                standard_cost_id=uuid4(),
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                version=1,
                effective_date=datetime.now(UTC),
                material_cost=Decimal("10"),
                labor_cost=Decimal("10"),
                overhead_cost=Decimal("10"),
                total_cost=Decimal("100"),  # should be 30
            )

    def test_validation_effective_date_timezone_aware(self):
        naive = datetime(2025, 1, 1)
        with pytest.raises(ValueError, match="effective_date must be timezone-aware"):
            StandardCostEntity(
                standard_cost_id=uuid4(),
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                version=1,
                effective_date=naive,
                material_cost=Decimal(0),
                labor_cost=Decimal(0),
                overhead_cost=Decimal(0),
                total_cost=Decimal(0),
            )

    # --- Test create factory ---
    def test_create(self):
        entity = StandardCostEntity.create(
            product_id=uuid4(),
            product_code="PROD-002",
            product_name="Product 2",
            material_cost=Decimal("200"),
            labor_cost=Decimal("100"),
            overhead_cost=Decimal("50"),
            effective_date=datetime.now(UTC),
            created_by="creator",
        )
        assert entity.version == 1
        assert entity.total_cost == Decimal("350")
        assert len(entity.components) == 3
        assert entity.status == StandardCostStatus.DRAFT
        assert entity.created_by == "creator"

    # --- Test update_cost ---
    def test_update_cost(self):
        instance = self._create_valid_instance()
        new_instance = instance.update_cost(
            material_cost=Decimal("150"),
            labor_cost=Decimal("75"),
            overhead_cost=Decimal("40"),
            updated_by="updater",
        )
        assert new_instance.version == instance.version + 1
        assert new_instance.material_cost == Decimal("150")
        assert new_instance.labor_cost == Decimal("75")
        assert new_instance.overhead_cost == Decimal("40")
        assert new_instance.total_cost == Decimal("265")
        assert new_instance.status == StandardCostStatus.DRAFT
        assert new_instance.version_counter == instance.version_counter + 1
        # Check components updated
        mat_comp = next(c for c in new_instance.components if c.cost_element == CostElement.MATERIAL)
        assert mat_comp.amount == Decimal("150")

    def test_update_cost_partial(self):
        instance = self._create_valid_instance()
        new_instance = instance.update_cost(
            material_cost=Decimal("200"),
            updated_by="updater",
        )
        assert new_instance.material_cost == Decimal("200")
        assert new_instance.labor_cost == instance.labor_cost  # unchanged
        assert new_instance.overhead_cost == instance.overhead_cost
        assert new_instance.total_cost == Decimal("280")  # 200+50+30

    # --- Test update_effective_date ---
    def test_update_effective_date(self):
        instance = self._create_valid_instance()
        new_date = datetime.now(UTC) + timedelta(days=10)
        new_instance = instance.update_effective_date(new_date, "updater")
        assert new_instance.version == instance.version + 1
        assert new_instance.effective_date == new_date
        assert new_instance.status == StandardCostStatus.DRAFT
        assert new_instance.version_counter == instance.version_counter + 1

    # --- Test activate ---
    def test_activate(self):
        instance = self._create_valid_instance()
        activated = instance.activate("activator")
        assert activated.status == StandardCostStatus.ACTIVE
        assert activated.version_counter == instance.version_counter + 1

    def test_activate_non_draft_raises(self):
        instance = self._create_valid_instance()
        active = instance.activate("activator")
        with pytest.raises(ValueError, match="Cannot activate standard cost in status active"):
            active.activate("activator2")

    # --- Test obsoleted ---
    def test_obsoleted(self):
        instance = self._create_valid_instance()
        obs = instance.obsoleted("obsoleter", "Reason for obsolescence")
        assert obs.status == StandardCostStatus.OBSOLETE
        assert obs.expiry_date is not None
        assert obs.version_counter == instance.version_counter + 1
        # Check that a component with notes was added
        note_comp = next((c for c in obs.components if c.notes and "Obsoleted" in c.notes), None)
        assert note_comp is not None

    # --- Test is_active_at_date ---
    def test_is_active_at_date(self):
        instance = self._create_valid_instance()
        active = instance.activate("activator")
        now = datetime.now(UTC)
        assert active.is_active_at_date(now) is True
        assert active.is_active_at_date(now - timedelta(days=1)) is False  # before effective

        # With expiry
        now + timedelta(days=30)
        # We need to create an active instance with expiry set (obsoleted sets expiry to now)
        # Let's manually create an active with expiry in future
        active_with_expiry = StandardCostEntity(
            standard_cost_id=uuid4(),
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            version=1,
            effective_date=now - timedelta(days=1),
            material_cost=Decimal(0),
            labor_cost=Decimal(0),
            overhead_cost=Decimal(0),
            total_cost=Decimal(0),
            status=StandardCostStatus.ACTIVE,
            expiry_date=now + timedelta(days=30),
            created_at=now,
            updated_at=now,
            created_by="tester",
            version_counter=1,
        )
        assert active_with_expiry.is_active_at_date(now) is True
        assert active_with_expiry.is_active_at_date(now + timedelta(days=60)) is False

    def test_is_active_at_date_not_active(self):
        instance = self._create_valid_instance()
        assert instance.is_active_at_date(datetime.now(UTC)) is False  # DRAFT

    # --- Test get_cost_by_element ---
    def test_get_cost_by_element(self):
        instance = self._create_valid_instance()
        assert instance.get_cost_by_element(CostElement.MATERIAL) == Decimal("100")
        assert instance.get_cost_by_element(CostElement.LABOR) == Decimal("50")
        assert instance.get_cost_by_element(CostElement.OVERHEAD) == Decimal("30")
        # For OTHER, should return 0 (not in components)
        assert instance.get_cost_by_element(CostElement.OTHER) == Decimal(0)

    # --- Test to_dict ---
    def test_to_dict(self):
        instance = self._create_valid_instance()
        d = instance.to_dict()
        assert d["product_code"] == "PROD-001"
        assert d["total_cost"] == "180"
        assert len(d["components"]) == 3

    # --- Test alias StandardCost ---
    def test_alias(self):
        assert StandardCost is StandardCostEntity


class TestStandardCostRepository:
    """Tests for StandardCostRepository."""

    def _build_instance(self):
        return StandardCostRepository()

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, StandardCostRepository)

    async def test_get_by_id(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.get_by_id(standard_cost_id=uuid4(), legal_entity_id=uuid4())

    async def test_get_by_product(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.get_by_product(product_id=uuid4(), legal_entity_id=uuid4())

    async def test_get_active(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.get_active(product_id=uuid4(), legal_entity_id=uuid4())

    async def test_save(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.save(standard_cost=MagicMock(), legal_entity_id=uuid4())

    async def test_delete(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.delete(standard_cost_id=uuid4(), legal_entity_id=uuid4())
