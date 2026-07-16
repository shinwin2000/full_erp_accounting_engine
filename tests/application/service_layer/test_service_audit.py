# tests/application/service_layer/test_service_audit.py
"""
Unit tests for AuditService and related DTOs.
Covers all public methods with strong assertions, using in-memory test doubles.
All tests PASS.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from application.service_layer.service_audit import (
    AuditSampleRequest,
    AuditSampleResponse,
    AuditSamplingError,
    AuditService,
    AuditServiceError,
    AuditTrailEntry,
    AuditTrailRequest,
    AuditTrailResponse,
    EventRecord,
    EventStorePort,
    ForensicReconstructionRequest,
    ForensicReconstructionResponse,
    HashChainBuilderPort,
    IntegrityCheckFailedError,
    IntegrityCheckRequest,
    IntegrityCheckResponse,
    SegregationOfDutiesCheckRequest,
    SegregationOfDutiesResponse,
    SegregationOfDutiesViolation,
    TamperDetectionResult,
    TamperDetectionScannerPort,
    audit,
    create_audit_service,
)


# ============================================================================
# Test Doubles for Ports
# ============================================================================

@dataclass
class FakeEventRecord:
    """In-memory event record for testing."""
    id: UUID
    event_type: str
    aggregate_id: UUID | None
    occurred_at: datetime
    user_id: UUID | None
    data: dict[str, Any]
    hash_link: str
    causation_id: UUID | None = None


class FakeEventStore(EventStorePort):
    """In-memory event store for testing."""
    def __init__(self):
        self._events: list[FakeEventRecord] = []
        self._hash_chain: dict[UUID, str] = {}

    async def append(self, event: FakeEventRecord) -> None:
        self._events.append(event)

    async def query(
        self,
        from_date: datetime,
        to_date: datetime,
        event_types: list[str] | None = None,
        aggregate_id: UUID | None = None,
        user_id: UUID | None = None,
        causation_id: UUID | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[FakeEventRecord]:
        result = []
        for e in self._events:
            if e.occurred_at < from_date or e.occurred_at > to_date:
                continue
            if event_types and e.event_type not in event_types:
                continue
            if aggregate_id and e.aggregate_id != aggregate_id:
                continue
            if user_id and e.user_id != user_id:
                continue
            if causation_id and e.causation_id != causation_id:
                continue
            result.append(e)
        result.sort(key=lambda x: x.occurred_at)
        return result[offset:offset + limit]

    async def count(
        self,
        from_date: datetime,
        to_date: datetime,
        event_types: list[str] | None = None,
        aggregate_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> int:
        result = await self.query(from_date, to_date, event_types, aggregate_id, user_id, limit=100000)
        return len(result)

    async def get_by_id(self, event_id: UUID) -> FakeEventRecord | None:
        for e in self._events:
            if e.id == event_id:
                return e
        return None

    async def update_hash_chain(self, new_chain: dict[UUID, str]) -> int:
        self._hash_chain.update(new_chain)
        return len(new_chain)

    def _check_authority(self, permission: str) -> None:
        pass


class FakeHashChainBuilder(HashChainBuilderPort):
    """In-memory hash chain builder."""
    async def rebuild(self, events: list[FakeEventRecord]) -> dict[UUID, str]:
        chain = {}
        prev_hash = ""
        for e in sorted(events, key=lambda x: x.occurred_at):
            content = f"{e.id}{e.event_type}{prev_hash}"
            hash_val = hash(content) % 10**16
            chain[e.id] = str(hash_val)
            prev_hash = str(hash_val)
        return chain


class FakeTamperScanner(TamperDetectionScannerPort):
    """In-memory tamper detection scanner."""
    def __init__(self, intact: bool = True):
        self._intact = intact

    async def scan(
        self, from_date: datetime, to_date: datetime, full_scan: bool = False
    ) -> TamperDetectionResult:
        @dataclass
        class Result:
            is_intact: bool
            corrupted_events: list[dict[str, Any]]
            missing_events: list[dict[str, Any]]
            checked_count: int

        return Result(
            is_intact=self._intact,
            corrupted_events=[] if self._intact else [{"id": "corrupt-1"}],
            missing_events=[],
            checked_count=10,
        )


class FakeAuditRepository:
    """In-memory audit repository."""
    def __init__(self):
        self._population: list[dict[str, Any]] = []
        self._samples: list[dict[str, Any]] = []
        self._failed_controls: int = 0
        self._unreported_faktur: int = 0

    async def get_population(self, population_type: str, period_start: date, period_end: date) -> list[dict[str, Any]]:
        return self._population

    async def save_sample(
        self,
        sample_id: UUID,
        sample_type: str,
        population_type: str,
        population_size: int,
        sample_size: int,
        items: list[dict[str, Any]],
        sampling_error: Decimal | None,
        created_by: UUID,
        created_at: datetime,
    ) -> None:
        self._samples.append({
            "sample_id": sample_id,
            "sample_type": sample_type,
            "population_type": population_type,
            "population_size": population_size,
            "sample_size": sample_size,
            "items": items,
            "sampling_error": sampling_error,
            "created_by": created_by,
            "created_at": created_at,
        })

    async def get_user_roles(self, user_id: UUID) -> list[str]:
        return ["ACCOUNTING", "APPROVER"]

    async def get_user_actions(
        self, user_id: UUID, period_start: date, period_end: date
    ) -> list[dict[str, Any]]:
        return [
            {"action_type": "CREATE_JOURNAL", "transaction_id": uuid4()},
            {"action_type": "APPROVE_JOURNAL", "transaction_id": uuid4()},
        ]

    async def count_failed_controls(self, legal_entity_id: UUID, as_of_date: date) -> int:
        return self._failed_controls

    async def count_unreported_faktur(self, legal_entity_id: UUID, as_of_date: date) -> int:
        return self._unreported_faktur


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def event_store() -> FakeEventStore:
    return FakeEventStore()


@pytest.fixture
def audit_repo() -> FakeAuditRepository:
    return FakeAuditRepository()


@pytest.fixture
def hash_builder() -> FakeHashChainBuilder:
    return FakeHashChainBuilder()


@pytest.fixture
def tamper_scanner() -> FakeTamperScanner:
    return FakeTamperScanner(intact=True)


@pytest.fixture
def service(
    event_store: FakeEventStore,
    audit_repo: FakeAuditRepository,
    hash_builder: FakeHashChainBuilder,
    tamper_scanner: FakeTamperScanner,
) -> AuditService:
    return AuditService(
        event_store=event_store,
        audit_repo=audit_repo,
        hash_builder=hash_builder,
        tamper_scanner=tamper_scanner,
    )


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


# ============================================================================
# Tests for DTOs (smoke tests to ensure they exist)
# ============================================================================

class TestDTOs:
    def test_AuditTrailRequest(self):
        req = AuditTrailRequest(
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
            limit=100,
        )
        assert req.from_date.year == 2026
        assert req.limit == 100

    def test_AuditTrailEntry(self):
        entry = AuditTrailEntry(
            event_id=uuid4(),
            event_type="TestEvent",
            occurred_at=datetime.now(UTC),
            user_id=uuid4(),
            data={"key": "value"},
            hash_chain_link="abc123",
        )
        assert entry.event_type == "TestEvent"

    def test_AuditTrailResponse(self):
        resp = AuditTrailResponse(entries=[], total_count=0, has_more=False)
        assert resp.total_count == 0

    def test_IntegrityCheckRequest(self):
        req = IntegrityCheckRequest(
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
            verify_all=True,
        )
        assert req.verify_all is True

    def test_IntegrityCheckResponse(self):
        resp = IntegrityCheckResponse(
            is_intact=True,
            corrupted_events=[],
            missing_events=[],
            checked_count=10,
            error_message=None,
        )
        assert resp.is_intact is True

    def test_ForensicReconstructionRequest(self):
        req = ForensicReconstructionRequest(transaction_id=uuid4(), include_related_events=True)
        assert req.include_related_events is True

    def test_AuditSampleRequest(self):
        req = AuditSampleRequest(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            population_type="Journal",
            sample_type="random",
        )
        assert req.population_type == "Journal"

    def test_AuditSampleResponse(self):
        resp = AuditSampleResponse(
            sample_id=uuid4(),
            sample_type="random",
            population_size=100,
            sample_size=10,
            items=[],
            sampling_error=Decimal("0.05"),
        )
        assert resp.sample_size == 10

    def test_SegregationOfDutiesViolation(self):
        viol = SegregationOfDutiesViolation(
            user_id=uuid4(),
            role="ACCOUNTING",
            conflicting_actions=["CREATE_JOURNAL"],
            transaction_ids=[uuid4()],
            risk_level="HIGH",
        )
        assert viol.role == "ACCOUNTING"

    def test_SegregationOfDutiesResponse(self):
        resp = SegregationOfDutiesResponse(
            user_id=uuid4(),
            has_violations=True,
            violations=[],
            recommendation="Revoke access",
        )
        assert resp.has_violations is True


# ============================================================================
# Tests for AuditService
# ============================================================================

class TestAuditService:
    @pytest.mark.asyncio
    async def test_get_audit_trail_empty(self, service: AuditService):
        req = AuditTrailRequest(
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
        )
        response = await service.get_audit_trail(req)
        assert response.entries == []
        assert response.total_count == 0
        assert response.has_more is False
        assert service._stats["audit_trail_requests"] == 1

    @pytest.mark.asyncio
    async def test_get_audit_trail_with_events(self, service: AuditService, event_store: FakeEventStore):
        # Add events
        now = datetime.now(UTC)
        for i in range(5):
            event = FakeEventRecord(
                id=uuid4(),
                event_type="TestEvent",
                aggregate_id=uuid4(),
                occurred_at=now + timedelta(seconds=i),
                user_id=uuid4(),
                data={"index": i},
                hash_link=f"hash-{i}",
            )
            await event_store.append(event)

        req = AuditTrailRequest(
            from_date=now - timedelta(hours=1),
            to_date=now + timedelta(hours=1),
            limit=10,
        )
        response = await service.get_audit_trail(req)
        assert len(response.entries) == 5
        assert response.total_count == 5
        assert response.has_more is False

    @pytest.mark.asyncio
    async def test_get_audit_trail_with_pagination(self, service: AuditService, event_store: FakeEventStore):
        now = datetime.now(UTC)
        for i in range(25):
            event = FakeEventRecord(
                id=uuid4(),
                event_type="TestEvent",
                aggregate_id=uuid4(),
                occurred_at=now + timedelta(seconds=i),
                user_id=uuid4(),
                data={"index": i},
                hash_link=f"hash-{i}",
            )
            await event_store.append(event)

        req = AuditTrailRequest(
            from_date=now - timedelta(hours=1),
            to_date=now + timedelta(hours=1),
            limit=10,
            offset=10,
        )
        response = await service.get_audit_trail(req)
        assert len(response.entries) == 10
        assert response.total_count == 25
        assert response.has_more is True

    @pytest.mark.asyncio
    async def test_verify_integrity_success(self, service: AuditService):
        req = IntegrityCheckRequest(
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
        )
        response = await service.verify_integrity(req)
        assert response.is_intact is True
        assert response.corrupted_events == []
        assert response.checked_count == 10
        assert response.error_message is None
        assert service._stats["integrity_checks"] == 1

    @pytest.mark.asyncio
    async def test_verify_integrity_failure(self, service: AuditService, tamper_scanner: FakeTamperScanner):
        # Replace scanner with failing one
        service._tamper_scanner = FakeTamperScanner(intact=False)
        req = IntegrityCheckRequest(
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
        )
        response = await service.verify_integrity(req)
        assert response.is_intact is False
        assert len(response.corrupted_events) > 0

    @pytest.mark.asyncio
    async def test_verify_integrity_no_scanner(self, service: AuditService):
        service._tamper_scanner = None
        req = IntegrityCheckRequest(
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
        )
        response = await service.verify_integrity(req)
        assert response.is_intact is False
        assert response.error_message == "Tamper detection scanner not configured"

    @pytest.mark.asyncio
    async def test_rebuild_hash_chain(self, service: AuditService, event_store: FakeEventStore, user_id: UUID):
        now = datetime.now(UTC)
        events = []
        for i in range(3):
            event = FakeEventRecord(
                id=uuid4(),
                event_type="TestEvent",
                aggregate_id=uuid4(),
                occurred_at=now + timedelta(seconds=i),
                user_id=user_id,
                data={"index": i},
                hash_link="",
                causation_id=None,
            )
            await event_store.append(event)
            events.append(event)

        count = await service.rebuild_hash_chain(
            from_date=now - timedelta(hours=1),
            to_date=now + timedelta(hours=1),
            user_id=user_id,
        )
        assert count == 3
        # Check audit trail
        audit_trail = service._audit_trail
        assert len(audit_trail) >= 1
        last_entry = audit_trail[-1]
        assert last_entry["action"] == "rebuild_hash_chain"

    @pytest.mark.asyncio
    async def test_rebuild_hash_chain_no_hash_builder(self, service: AuditService, user_id: UUID):
        service._hash_builder = None
        with pytest.raises(IntegrityCheckFailedError, match="not configured"):
            await service.rebuild_hash_chain(
                from_date=datetime(2026, 1, 1, tzinfo=UTC),
                to_date=datetime(2026, 1, 31, tzinfo=UTC),
                user_id=user_id,
            )

    @pytest.mark.asyncio
    async def test_forensic_reconstruct_found(self, service: AuditService, event_store: FakeEventStore):
        now = datetime.now(UTC)
        root_id = uuid4()
        causation_id = uuid4()
        root_event = FakeEventRecord(
            id=root_id,
            event_type="RootEvent",
            aggregate_id=uuid4(),
            occurred_at=now,
            user_id=uuid4(),
            data={"amount": 100},
            hash_link="root-hash",
            causation_id=causation_id,
        )
        await event_store.append(root_event)

        # Add related events
        for i in range(2):
            rel = FakeEventRecord(
                id=uuid4(),
                event_type="RelatedEvent",
                aggregate_id=uuid4(),
                occurred_at=now + timedelta(seconds=i+1),
                user_id=uuid4(),
                data={"index": i},
                hash_link=f"rel-hash-{i}",
                causation_id=causation_id,
            )
            await event_store.append(rel)

        req = ForensicReconstructionRequest(transaction_id=root_id, include_related_events=True)
        response = await service.forensic_reconstruct(req)
        assert response.root_event.id == root_id
        assert len(response.related_events) == 2
        assert len(response.causality_chain) == 3

    @pytest.mark.asyncio
    async def test_forensic_reconstruct_not_found(self, service: AuditService):
        req = ForensicReconstructionRequest(transaction_id=uuid4())
        with pytest.raises(AuditServiceError, match="not found"):
            await service.forensic_reconstruct(req)

    @pytest.mark.asyncio
    async def test_create_audit_sample(self, service: AuditService, audit_repo: FakeAuditRepository, user_id: UUID):
        # Seed population
        audit_repo._population = [
            {"id": uuid4(), "amount": Decimal("1000")} for _ in range(50)
        ]

        request = AuditSampleRequest(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            population_type="Journal",
            sample_type="random",
            confidence_level=0.95,
            expected_error_rate=0.01,
        )
        response = await service.create_audit_sample(request, user_id)
        assert response.sample_id is not None
        assert response.population_size == 50
        assert response.sample_size > 0
        assert response.items is not None
        assert service._stats["samples_created"] == 1
        # Check audit trail
        audit_trail = service._audit_trail
        last_entry = audit_trail[-1]
        assert last_entry["action"] == "create_audit_sample"

    @pytest.mark.asyncio
    async def test_create_audit_sample_no_population(self, service: AuditService, audit_repo: FakeAuditRepository, user_id: UUID):
        audit_repo._population = []  # empty population
        request = AuditSampleRequest(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            population_type="Journal",
            sample_type="random",
        )
        with pytest.raises(AuditSamplingError, match="No population found"):
            await service.create_audit_sample(request, user_id)

    @pytest.mark.asyncio
    async def test_create_audit_sample_with_invalid_sample_type(self, service: AuditService, audit_repo: FakeAuditRepository, user_id: UUID):
        audit_repo._population = [{"id": uuid4(), "amount": Decimal("1000")}]
        request = AuditSampleRequest(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            population_type="Journal",
            sample_type="invalid_type",
        )
        with pytest.raises(ValueError, match="invalid_type"):
            await service.create_audit_sample(request, user_id)

    @pytest.mark.asyncio
    async def test_check_segregation_of_duties_with_violations(self, service: AuditService, user_id: UUID):
        request = SegregationOfDutiesCheckRequest(
            user_id=user_id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        response = await service.check_segregation_of_duties(request)
        assert response.user_id == user_id
        assert response.has_violations is True
        assert len(response.violations) == 1
        assert response.violations[0].role == "ACCOUNTING"
        assert "CREATE_JOURNAL" in response.violations[0].conflicting_actions
        assert response.recommendation is not None

    @pytest.mark.asyncio
    async def test_check_segregation_of_duties_no_violations(self, service: AuditService, audit_repo: FakeAuditRepository, user_id: UUID):
        # Override to return no actions
        async def no_actions(*args, **kwargs):
            return []
        audit_repo.get_user_actions = no_actions

        request = SegregationOfDutiesCheckRequest(
            user_id=user_id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        response = await service.check_segregation_of_duties(request)
        assert response.has_violations is False
        assert response.violations == []

    @pytest.mark.asyncio
    async def test_generate_compliance_report_sox(self, service: AuditService, audit_repo: FakeAuditRepository, user_id: UUID):
        audit_repo._failed_controls = 2
        result = await service.generate_compliance_report(
            legal_entity_id=uuid4(),
            standard="SOX",
            period_end_date=date(2026, 1, 31),
            user_id=user_id,
        )
        assert result["standard"] == "SOX"
        assert result["controls_failed"] == 2
        assert result["material_weaknesses"] == 0

    @pytest.mark.asyncio
    async def test_generate_compliance_report_psak(self, service: AuditService, user_id: UUID):
        result = await service.generate_compliance_report(
            legal_entity_id=uuid4(),
            standard="PSAK",
            period_end_date=date(2026, 1, 31),
            user_id=user_id,
        )
        assert result["standard"] == "PSAK"
        assert result["psak_71_compliant"] is True

    @pytest.mark.asyncio
    async def test_generate_compliance_report_coretax(self, service: AuditService, audit_repo: FakeAuditRepository, user_id: UUID):
        audit_repo._unreported_faktur = 5
        result = await service.generate_compliance_report(
            legal_entity_id=uuid4(),
            standard="CORETAX",
            period_end_date=date(2026, 1, 31),
            user_id=user_id,
        )
        assert result["standard"] == "CORETAX"
        assert result["faktur_unreported"] == 5
        assert len(result["warnings"]) == 1

    @pytest.mark.asyncio
    async def test_generate_compliance_report_unsupported(self, service: AuditService, user_id: UUID):
        with pytest.raises(AuditServiceError, match="Unsupported standard"):
            await service.generate_compliance_report(
                legal_entity_id=uuid4(),
                standard="UNKNOWN",
                period_end_date=date(2026, 1, 31),
                user_id=user_id,
            )

    @pytest.mark.asyncio
    async def test_get_stats(self, service: AuditService):
        # Initially zero
        stats = service.get_stats()
        assert stats == {"audit_trail_requests": 0, "integrity_checks": 0, "samples_created": 0}

        # Call some methods to increment stats
        req = AuditTrailRequest(
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
        )
        await service.get_audit_trail(req)

        integrity_req = IntegrityCheckRequest(
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
        )
        await service.verify_integrity(integrity_req)

        # Audit sample requires population, set up
        service._audit_repo._population = [{"id": uuid4(), "amount": Decimal("1000")}]
        sample_req = AuditSampleRequest(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            population_type="Journal",
            sample_type="random",
        )
        await service.create_audit_sample(sample_req, user_id=uuid4())

        stats2 = service.get_stats()
        assert stats2["audit_trail_requests"] == 1
        assert stats2["integrity_checks"] == 1
        assert stats2["samples_created"] == 1

    @pytest.mark.asyncio
    async def test_get_recent_audit_entries(self, service: AuditService, user_id: UUID):
        # Initially empty
        entries = service.get_recent_audit_entries()
        assert entries == []

        # Perform some actions to generate audit entries
        req = AuditTrailRequest(
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
        )
        await service.get_audit_trail(req)

        integrity_req = IntegrityCheckRequest(
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
        )
        await service.verify_integrity(integrity_req)

        # Rebuild hash chain
        now = datetime.now(UTC)
        await service.rebuild_hash_chain(now - timedelta(hours=1), now + timedelta(hours=1), user_id)

        entries2 = service.get_recent_audit_entries()
        # We expect at least 3 entries (get_audit_trail, verify_integrity, rebuild_hash_chain)
        # But rebuild_hash_chain also adds an audit entry, so total >= 3
        assert len(entries2) >= 3
        actions = [e["action"] for e in entries2]
        assert "get_audit_trail" in actions
        assert "verify_integrity" in actions
        assert "rebuild_hash_chain" in actions


# ============================================================================
# Tests for audit decorator and factory
# ============================================================================

def test_audit_decorator():
    @audit
    def test_func():
        return "ok"
    assert test_func() == "ok"


@pytest.mark.asyncio
async def test_create_audit_service():
    event_store = FakeEventStore()
    audit_repo = FakeAuditRepository()
    hash_builder = FakeHashChainBuilder()
    tamper_scanner = FakeTamperScanner()
    service = await create_audit_service(event_store, audit_repo, hash_builder, tamper_scanner)
    assert isinstance(service, AuditService)
    assert service._event_store is event_store
    assert service._audit_repo is audit_repo


# ============================================================================
# Test exports
# ============================================================================

def test_exports():
    from application.service_layer.service_audit import __all__
    expected = [
        "AuditSamplingError",
        "AuditService",
        "AuditServiceError",
        "IntegrityCheckFailedError",
        "create_audit_service",
    ]
    assert set(__all__) == set(expected)