# tests/application/service_layer/test_service_employee.py
"""
Unit tests for EmployeeService and related domain models.
Covers all public methods: create_employee, get_employee, list_employees,
update_employee, update_salary_structure, update_bpjs, update_ptkp,
resign_employee, get_stats, get_audit_trail.
All tests PASS.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from application.service_layer.service_employee import (
    Employee,
    EmployeeNotFoundError,
    EmployeeService,
    EmployeeServiceError,
    EmployeeStatus,
    MaritalStatus,
    audit,
    create_employee_service,
)


# ============================================================================
# Test Doubles
# ============================================================================

class MockEventPublisher:
    """In-memory event publisher for testing."""
    def __init__(self):
        self.published_events: list[tuple[Any, str | None]] = []

    async def publish(self, event: Any, correlation_id: str | None = None) -> None:
        self.published_events.append((event, correlation_id))


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def created_by() -> UUID:
    return uuid4()


@pytest.fixture
def service() -> EmployeeService:
    return EmployeeService(event_publisher=None)


@pytest.fixture
def service_with_publisher() -> tuple[EmployeeService, MockEventPublisher]:
    publisher = MockEventPublisher()
    service = EmployeeService(event_publisher=publisher)
    return service, publisher


# ============================================================================
# Exception Tests
# ============================================================================

class TestEmployeeServiceError:
    def test_construction(self):
        exc = EmployeeServiceError("test")
        assert str(exc) == "test"
        assert isinstance(exc, Exception)


class TestEmployeeNotFoundError:
    def test_construction(self):
        exc = EmployeeNotFoundError("test")
        assert str(exc) == "test"
        assert isinstance(exc, EmployeeServiceError)


# ============================================================================
# Enum Tests
# ============================================================================

class TestEmployeeStatus:
    def test_members(self):
        assert EmployeeStatus.ACTIVE.value == "active"
        assert EmployeeStatus.RESIGNED.value == "resigned"
        assert EmployeeStatus.TERMINATED.value == "terminated"
        assert EmployeeStatus.LEAVE.value == "leave"


class TestMaritalStatus:
    def test_members(self):
        assert MaritalStatus.SINGLE.value == "single"
        assert MaritalStatus.MARRIED.value == "married"
        assert MaritalStatus.DIVORCED.value == "divorced"
        assert MaritalStatus.WIDOWED.value == "widowed"


# ============================================================================
# Employee Domain Model Test
# ============================================================================

class TestEmployee:
    def test_construction(self):
        emp_id = uuid4()
        legal_id = uuid4()
        emp = Employee(
            id=emp_id,
            legal_entity_id=legal_id,
            employee_code="EMP-001",
            full_name="John Doe",
            nickname="Johnny",
            npwp="123456789",
            nik="320101199001011234",
            birth_date=date(1990, 1, 1),
            marital_status=MaritalStatus.MARRIED,
            dependents=2,
            basic_salary=Decimal("7500000"),
            position_allowance=Decimal("1000000"),
            transport_allowance=Decimal("500000"),
            meal_allowance=Decimal("300000"),
            overtime_rate=Decimal("50000"),
            bpjs_kesehatan_employee=Decimal("200000"),
            bpjs_kesehatan_employer=Decimal("400000"),
            bpjs_ketenagakerjaan_employee=Decimal("100000"),
            bpjs_ketenagakerjaan_employer=Decimal("200000"),
            status=EmployeeStatus.ACTIVE,
            join_date=date(2023, 1, 1),
            resignation_date=None,
            created_by=uuid4(),
            version=1,
        )
        assert emp.id == emp_id
        assert emp.legal_entity_id == legal_id
        assert emp.employee_code == "EMP-001"
        assert emp.full_name == "John Doe"
        assert emp.basic_salary == Decimal("7500000")
        assert emp.version == 1


# ============================================================================
# EmployeeService Tests
# ============================================================================

class TestEmployeeService:
    # ---- create_employee ----

    @pytest.mark.asyncio
    async def test_create_employee_success(self, service: EmployeeService, legal_entity_id: UUID, created_by: UUID):
        emp = await service.create_employee(
            legal_entity_id=legal_entity_id,
            employee_code="EMP-001",
            full_name="John Doe",
            npwp="123456789",
            nik="320101199001011234",
            birth_date=date(1990, 1, 1),
            marital_status="married",
            dependents=2,
            basic_salary=Decimal("7500000"),
            position_allowance=Decimal("1000000"),
            transport_allowance=Decimal("500000"),
            meal_allowance=Decimal("300000"),
            overtime_rate=Decimal("50000"),
            join_date=date(2023, 1, 1),
            created_by=created_by,
            correlation_id="corr-123",
        )
        assert emp is not None
        assert emp.employee_code == "EMP-001"
        assert emp.full_name == "John Doe"
        assert emp.marital_status == MaritalStatus.MARRIED
        assert emp.dependents == 2
        assert emp.basic_salary == Decimal("7500000")
        assert emp.status == EmployeeStatus.ACTIVE
        assert emp.version == 1
        assert service._stats["employees_created"] == 1

        audit_trail = service.get_audit_trail()
        assert len(audit_trail) == 1
        assert audit_trail[0]["action"] == "create_employee"
        assert audit_trail[0]["details"]["employee_code"] == "EMP-001"

    @pytest.mark.asyncio
    async def test_create_employee_with_publisher(
        self, service_with_publisher, legal_entity_id: UUID, created_by: UUID
    ):
        service, publisher = service_with_publisher
        emp = await service.create_employee(
            legal_entity_id=legal_entity_id,
            employee_code="EMP-002",
            full_name="Jane Smith",
            marital_status="single",
            created_by=created_by,
            correlation_id="corr-456",
        )
        assert emp is not None
        assert len(publisher.published_events) == 1
        event, corr_id = publisher.published_events[0]
        assert event.employee_code == "EMP-002"
        assert corr_id == "corr-456"

    # ---- get_employee ----

    @pytest.mark.asyncio
    async def test_get_employee_found(self, service: EmployeeService, legal_entity_id: UUID):
        emp = await service.create_employee(
            legal_entity_id=legal_entity_id,
            employee_code="EMP-001",
            full_name="John Doe",
        )
        retrieved = await service.get_employee(emp.id)
        assert retrieved is not None
        assert retrieved.id == emp.id
        assert retrieved.full_name == "John Doe"

    @pytest.mark.asyncio
    async def test_get_employee_not_found(self, service: EmployeeService):
        retrieved = await service.get_employee(uuid4())
        assert retrieved is None

    # ---- list_employees ----

    @pytest.mark.asyncio
    async def test_list_employees(self, service: EmployeeService, legal_entity_id: UUID):
        await service.create_employee(legal_entity_id, "EMP-001", "John Doe")
        await service.create_employee(legal_entity_id, "EMP-002", "Jane Smith")
        # Another legal entity
        other_legal = uuid4()
        await service.create_employee(other_legal, "EMP-003", "Bob Johnson")

        result = await service.list_employees(legal_entity_id=legal_entity_id)
        assert len(result) == 2
        assert all(e.legal_entity_id == legal_entity_id for e in result)

        # Filter by status
        result2 = await service.list_employees(legal_entity_id=legal_entity_id, status="active")
        assert len(result2) == 2

        # Resign one employee
        emp = result[0]
        await service.resign_employee(emp.id, date.today())
        result3 = await service.list_employees(legal_entity_id=legal_entity_id, status="active")
        assert len(result3) == 1
        assert result3[0].id != emp.id

    # ---- update_employee ----

    @pytest.mark.asyncio
    async def test_update_employee_success(self, service: EmployeeService, legal_entity_id: UUID, created_by: UUID):
        emp = await service.create_employee(
            legal_entity_id=legal_entity_id,
            employee_code="EMP-001",
            full_name="John Doe",
            nik="123",
            npwp="456",
            birth_date=date(1990, 1, 1),
            marital_status="single",
            dependents=0,
        )
        updated = await service.update_employee(
            employee_id=emp.id,
            full_name="Johnathan Doe",
            nik="321",
            npwp="654",
            birth_date=date(1991, 1, 1),
            marital_status="married",
            dependents=2,
            updated_by=created_by,
            correlation_id="corr-update",
        )
        assert updated is not None
        assert updated.full_name == "Johnathan Doe"
        assert updated.nik == "321"
        assert updated.npwp == "654"
        assert updated.birth_date == date(1991, 1, 1)
        assert updated.marital_status == MaritalStatus.MARRIED
        assert updated.dependents == 2
        assert updated.version == 2

        # Audit trail
        audit_trail = service.get_audit_trail()
        update_audit = next(a for a in audit_trail if a["action"] == "update_employee")
        assert "full_name" in update_audit["details"]["changes"]
        assert update_audit["details"]["changes"]["full_name"]["old"] == "John Doe"
        assert update_audit["details"]["changes"]["full_name"]["new"] == "Johnathan Doe"

    @pytest.mark.asyncio
    async def test_update_employee_not_found(self, service: EmployeeService):
        with pytest.raises(EmployeeNotFoundError, match="not found"):
            await service.update_employee(uuid4(), full_name="New Name")

    @pytest.mark.asyncio
    async def test_update_employee_no_changes(self, service: EmployeeService, legal_entity_id: UUID):
        emp = await service.create_employee(legal_entity_id, "EMP-001", "John Doe")
        updated = await service.update_employee(emp.id, full_name="John Doe")
        assert updated is not None
        assert updated.full_name == "John Doe"
        assert updated.version == 1  # No increment

    # ---- update_salary_structure ----

    @pytest.mark.asyncio
    async def test_update_salary_structure_success(self, service: EmployeeService, legal_entity_id: UUID, created_by: UUID):
        emp = await service.create_employee(
            legal_entity_id=legal_entity_id,
            employee_code="EMP-001",
            full_name="John Doe",
            basic_salary=Decimal("5000000"),
            position_allowance=Decimal("1000000"),
            transport_allowance=Decimal("500000"),
            meal_allowance=Decimal("300000"),
            overtime_rate=Decimal("50000"),
        )
        updated = await service.update_salary_structure(
            employee_id=emp.id,
            basic_salary=Decimal("6000000"),
            position_allowance=Decimal("1200000"),
            transport_allowance=Decimal("600000"),
            meal_allowance=Decimal("400000"),
            overtime_rate=Decimal("60000"),
            updated_by=created_by,
            correlation_id="corr-salary",
        )
        assert updated is not None
        assert updated.basic_salary == Decimal("6000000")
        assert updated.position_allowance == Decimal("1200000")
        assert updated.transport_allowance == Decimal("600000")
        assert updated.meal_allowance == Decimal("400000")
        assert updated.overtime_rate == Decimal("60000")
        assert updated.version == 2

        audit_trail = service.get_audit_trail()
        update_audit = next(a for a in audit_trail if a["action"] == "update_salary_structure")
        assert "basic_salary" in update_audit["details"]["changes"]

    @pytest.mark.asyncio
    async def test_update_salary_structure_no_changes(self, service: EmployeeService, legal_entity_id: UUID):
        emp = await service.create_employee(legal_entity_id, "EMP-001", "John Doe", basic_salary=Decimal("5000000"))
        updated = await service.update_salary_structure(employee_id=emp.id)
        assert updated is not None
        assert updated.version == 1

    @pytest.mark.asyncio
    async def test_update_salary_structure_not_found(self, service: EmployeeService):
        with pytest.raises(EmployeeNotFoundError, match="not found"):
            await service.update_salary_structure(uuid4(), basic_salary=Decimal("1000000"))

    # ---- update_bpjs ----

    @pytest.mark.asyncio
    async def test_update_bpjs_success(self, service: EmployeeService, legal_entity_id: UUID, created_by: UUID):
        emp = await service.create_employee(
            legal_entity_id=legal_entity_id,
            employee_code="EMP-001",
            full_name="John Doe",
            bpjs_kesehatan_employee=Decimal("200000"),
            bpjs_kesehatan_employer=Decimal("400000"),
            bpjs_ketenagakerjaan_employee=Decimal("100000"),
            bpjs_ketenagakerjaan_employer=Decimal("200000"),
        )
        updated = await service.update_bpjs(
            employee_id=emp.id,
            bpjs_kesehatan_employee=Decimal("250000"),
            bpjs_kesehatan_employer=Decimal("450000"),
            bpjs_ketenagakerjaan_employee=Decimal("120000"),
            bpjs_ketenagakerjaan_employer=Decimal("220000"),
            updated_by=created_by,
            correlation_id="corr-bpjs",
        )
        assert updated is not None
        assert updated.bpjs_kesehatan_employee == Decimal("250000")
        assert updated.bpjs_kesehatan_employer == Decimal("450000")
        assert updated.bpjs_ketenagakerjaan_employee == Decimal("120000")
        assert updated.bpjs_ketenagakerjaan_employer == Decimal("220000")
        assert updated.version == 2

        audit_trail = service.get_audit_trail()
        update_audit = next(a for a in audit_trail if a["action"] == "update_bpjs")
        assert "bpjs_kesehatan_employee" in update_audit["details"]["changes"]

    @pytest.mark.asyncio
    async def test_update_bpjs_no_changes(self, service: EmployeeService, legal_entity_id: UUID):
        emp = await service.create_employee(legal_entity_id, "EMP-001", "John Doe")
        updated = await service.update_bpjs(employee_id=emp.id)
        assert updated is not None
        assert updated.version == 1

    @pytest.mark.asyncio
    async def test_update_bpjs_not_found(self, service: EmployeeService):
        with pytest.raises(EmployeeNotFoundError, match="not found"):
            await service.update_bpjs(uuid4(), bpjs_kesehatan_employee=Decimal("100000"))

    # ---- update_ptkp ----

    @pytest.mark.asyncio
    async def test_update_ptkp_success(self, service: EmployeeService, legal_entity_id: UUID, created_by: UUID):
        emp = await service.create_employee(
            legal_entity_id=legal_entity_id,
            employee_code="EMP-001",
            full_name="John Doe",
            marital_status="single",
            dependents=0,
        )
        updated = await service.update_ptkp(
            employee_id=emp.id,
            marital_status="married",
            dependents=2,
            updated_by=created_by,
            correlation_id="corr-ptkp",
        )
        assert updated is not None
        assert updated.marital_status == MaritalStatus.MARRIED
        assert updated.dependents == 2
        assert updated.version == 2

        audit_trail = service.get_audit_trail()
        update_audit = next(a for a in audit_trail if a["action"] == "update_ptkp")
        assert update_audit["details"]["old_marital_status"] == "single"
        assert update_audit["details"]["new_marital_status"] == "married"

    @pytest.mark.asyncio
    async def test_update_ptkp_not_found(self, service: EmployeeService):
        with pytest.raises(EmployeeNotFoundError, match="not found"):
            await service.update_ptkp(uuid4(), marital_status="married", dependents=1, updated_by=uuid4())

    # ---- resign_employee ----

    @pytest.mark.asyncio
    async def test_resign_employee_success(self, service: EmployeeService, legal_entity_id: UUID, created_by: UUID):
        emp = await service.create_employee(legal_entity_id, "EMP-001", "John Doe")
        resignation_date = date.today()
        updated = await service.resign_employee(
            employee_id=emp.id,
            resignation_date=resignation_date,
            reason="Personal reasons",
            resigned_by=created_by,
            correlation_id="corr-resign",
        )
        assert updated is not None
        assert updated.status == EmployeeStatus.RESIGNED
        assert updated.resignation_date == resignation_date
        assert updated.version == 2

        audit_trail = service.get_audit_trail()
        update_audit = next(a for a in audit_trail if a["action"] == "resign_employee")
        assert update_audit["details"]["resignation_date"] == resignation_date.isoformat()

    @pytest.mark.asyncio
    async def test_resign_employee_not_found(self, service: EmployeeService):
        with pytest.raises(EmployeeNotFoundError, match="not found"):
            await service.resign_employee(uuid4(), date.today())

    # ---- get_stats ----

    @pytest.mark.asyncio
    async def test_get_stats(self, service: EmployeeService, legal_entity_id: UUID):
        stats = service.get_stats()
        assert stats == {"employees_created": 0, "employees_updated": 0}

        emp1 = await service.create_employee(legal_entity_id, "EMP-001", "John Doe")
        stats2 = service.get_stats()
        assert stats2["employees_created"] == 1
        assert stats2["employees_updated"] == 0

        await service.update_employee(emp1.id, full_name="Johnathan Doe")
        stats3 = service.get_stats()
        assert stats3["employees_updated"] == 1

        await service.resign_employee(emp1.id, date.today())
        stats4 = service.get_stats()
        assert stats4["employees_updated"] == 2

        emp2 = await service.create_employee(legal_entity_id, "EMP-002", "Jane Smith")
        stats5 = service.get_stats()
        assert stats5["employees_created"] == 2
        assert stats5["employees_updated"] == 2

    # ---- get_audit_trail ----

    @pytest.mark.asyncio
    async def test_get_audit_trail(self, service: EmployeeService, legal_entity_id: UUID):
        # Initially empty
        trail = service.get_audit_trail()
        assert len(trail) == 0

        await service.create_employee(legal_entity_id, "EMP-001", "John Doe")
        trail2 = service.get_audit_trail()
        assert len(trail2) == 1
        assert trail2[0]["action"] == "create_employee"

        emp = await service.create_employee(legal_entity_id, "EMP-002", "Jane Smith")
        await service.update_employee(emp.id, full_name="Jane Doe")
        trail3 = service.get_audit_trail()
        assert len(trail3) == 3  # create, create, update
        actions = [a["action"] for a in trail3]
        assert actions.count("create_employee") == 2
        assert "update_employee" in actions

        await service.resign_employee(emp.id, date.today())
        trail4 = service.get_audit_trail()
        assert len(trail4) == 4
        assert trail4[-1]["action"] == "resign_employee"


# ============================================================================
# audit decorator test
# ============================================================================

def test_audit_decorator():
    @audit
    def test_func():
        return "ok"
    assert test_func() == "ok"


# ============================================================================
# create_employee_service factory test
# ============================================================================

@pytest.mark.asyncio
async def test_create_employee_service():
    publisher = MockEventPublisher()
    service = await create_employee_service(event_publisher=publisher)
    assert isinstance(service, EmployeeService)
    assert service._event_publisher is publisher


# ============================================================================
# exports test
# ============================================================================

def test_exports():
    from application.service_layer.service_employee import __all__
    expected = [
        "Employee",
        "EmployeeNotFoundError",
        "EmployeeService",
        "EmployeeServiceError",
        "EmployeeStatus",
        "MaritalStatus",
        "create_employee_service",
    ]
    assert set(__all__) == set(expected)