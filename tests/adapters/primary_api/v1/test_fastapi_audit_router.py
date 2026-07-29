# adapters/primary_api/v1/test_fastapi_audit_router.py
"""
Comprehensive unit tests for FastAPI Audit Router.

Covers:
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
- Sampling setup validation (decimal handling)
- Forensic replay, hash chain, gap detection, SOX, reporting
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_audit_router import (
    AuditEventType,
    AuditFindingSchema,
    AuditReportRequestSchema,
    AuditReportResponseSchema,
    AuditSeverity,
    AuditStatisticsSchema,
    AuditStatus,
    AuditTrailSchema,
    EventStoreEntrySchema,
    EventStoreQuerySchema,
    ForensicReplayRequestSchema,
    ForensicReplayResponseSchema,
    GapDetectionResultSchema,
    HashChainStatusSchema,
    HashChainVerifyResultSchema,
    SamplingConclusion,
    SamplingConclusionSchema,
    SamplingEvaluationSchema,
    SamplingMethod,
    SamplingResponseSchema,
    SamplingSetupSchema,
    SOXControlTestResponseSchema,
    SOXControlTestSchema,
    detect_gaps,
    download_audit_report,
    evaluate_sampling,
    export_audit_data,
    forensic_replay,
    generate_audit_report,
    get_aggregate_events,
    get_audit_findings,
    get_audit_service,
    get_audit_statistics,
    get_audit_trail,
    get_hash_chain_status,
    get_sampling_engine,
    get_sox_controls_status,
    project_sampling,
    query_event_store,
    resolve_audit_finding,
    setup_sampling,
    test_sox_control,
    verify_all_chains,
    verify_hash_chain,
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
def mock_audit_service():
    svc = AsyncMock()

    # Event store
    svc.query_event_store.return_value = [
        MagicMock(
            id=uuid4(),
            aggregate_type="journal",
            aggregate_id=uuid4(),
            version=1,
            event_type="create",
            event_data={"amount": 1000},
            metadata={"user": "admin"},
            hash_prev=None,
            hash_current="abc123",
            recorded_at=datetime.now(UTC),
            recorded_by=uuid4(),
            recorded_by_name="Admin",
            legal_entity_id=uuid4(),
        )
    ]
    svc.get_aggregate_events.return_value = svc.query_event_store.return_value

    # Hash chain
    svc.verify_hash_chain.return_value = MagicMock(
        chain_type="event",
        chain_id=uuid4(),
        total_entries=10,
        valid_count=10,
        invalid_count=0,
        invalid_entries=[],
        first_invalid_index=None,
        is_chain_valid=True,
        verified_at=datetime.now(UTC),
        verified_by=uuid4(),
    )
    svc.get_hash_chain_status.return_value = MagicMock(
        last_verified_at=datetime.now(UTC),
        total_chains=5,
        valid_chains=5,
        invalid_chains=0,
        chains=[{"chain_id": str(uuid4()), "valid": True}],
    )
    svc.verify_all_chains.return_value = MagicMock(
        total_chains=5,
        valid_chains=5,
        invalid_chains=0,
        verified_at=datetime.now(UTC),
        details={"chain1": "ok"},
    )

    # Forensic replay
    svc.forensic_replay.return_value = MagicMock(
        aggregate_type="journal",
        aggregate_id=uuid4(),
        snapshot_version=5,
        events_replayed=3,
        final_state={"amount": 5000},
        replay_duration_ms=12.5,
        replayed_at=datetime.now(UTC),
        replayed_by=uuid4(),
    )

    # Gap detection
    svc.detect_gaps.return_value = [
        MagicMock(
            gap_start=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
            gap_end=datetime(2025, 1, 1, 10, 5, tzinfo=UTC),
            gap_duration_seconds=300.0,
            missing_sequence_numbers=[3, 4],
            expected_count=10,
            actual_count=8,
        )
    ]

    # Sampling (simplified)
    svc.setup_sampling.return_value = MagicMock(
        engagement_id=uuid4(),
        sample_size=50,
        sampling_interval=Decimal("2000"),
        materiality_threshold=Decimal("50000"),
        performance_materiality=Decimal("37500"),
        clearly_trivial_threshold=Decimal("2500"),
        confidence_level=95,
        expected_error=Decimal("1.0"),
        tolerable_error=Decimal("5.0"),
        sampling_method="random",
    )
    svc.evaluate_sample_errors.return_value = MagicMock(
        conclusion="no_material_misstatement",
        recommendation="No further testing needed",
        details={"projected_error": 1000},
        projected_error=Decimal("1000"),
        upper_error_limit=Decimal("2500"),
        margin_of_error=Decimal("500"),
        is_material=False,
    )
    svc.project_and_conclude.return_value = MagicMock(
        conclusion="no_material_misstatement",
        recommendation="Control effective",
        details={"deviation_rate": 0.02},
        projected_error=Decimal("0.02"),
        upper_error_limit=Decimal("0.05"),
        margin_of_error=Decimal("0.01"),
        is_material=False,
    )

    # SOX
    svc.test_sox_control.return_value = MagicMock(
        test_id=uuid4(),
        control_id="SOX-001",
        control_name="Access Control",
        control_category="ITGC",
        test_period_start=date(2025, 1, 1),
        test_period_end=date(2025, 1, 31),
        sample_size=25,
        deviations=1,
        deviation_rate=4.0,
        threshold_rate=5.0,
        is_effective=True,
        conclusion="Control is effective",
        recommendations=["Monitor access logs"],
        tested_at=datetime.now(UTC),
        tested_by=uuid4(),
        tested_by_name="Admin",
    )
    svc.get_sox_controls_status.return_value = [
        {"control_id": "SOX-001", "effective": True}
    ]

    # Report
    svc.generate_audit_report.return_value = MagicMock(
        report_id=uuid4(),
        report_number="AUD-2025-001",
        report_type="Comprehensive",
        generated_at=datetime.now(UTC),
        generated_by=uuid4(),
        generated_by_name="Admin",
        findings_count=2,
        recommendations_count=3,
        hash_chain_status="valid",
        gap_detection_status="no_gaps",
        file_url="https://storage/report.pdf",
    )
    svc.download_audit_report.return_value = (b"PDF content", "audit_report_2025.pdf")

    # Audit trail
    svc.get_audit_trail.return_value = [
        MagicMock(
            id=uuid4(),
            entity_type="journal",
            entity_id=uuid4(),
            entity_reference="JRN-001",
            action="update",
            old_value={"amount": 100},
            new_value={"amount": 200},
            changes={"amount": {"old": 100, "new": 200}},
            actor_id=uuid4(),
            actor_name="Admin",
            actor_ip="192.168.1.1",
            actor_user_agent="Mozilla/5.0",
            timestamp=datetime.now(UTC),
            severity="info",
            status="success",
            notes="Updated amount",
        )
    ]

    # Findings
    svc.get_audit_findings.return_value = [
        MagicMock(
            id=uuid4(),
            finding_number="FIND-001",
            category="Segregation of duties",
            severity="warning",
            description="User has conflicting roles",
            affected_entities=[{"user": "john"}],
            root_cause="Lack of SOD policy",
            recommendation="Revoke one role",
            status="open",
            created_at=datetime.now(UTC),
            resolved_at=None,
            resolved_by=None,
        )
    ]
    svc.resolve_audit_finding.return_value = MagicMock(
        id=uuid4(),
        finding_number="FIND-001",
        category="Segregation of duties",
        severity="warning",
        description="User has conflicting roles",
        affected_entities=[{"user": "john"}],
        root_cause="Lack of SOD policy",
        recommendation="Revoke one role",
        status="resolved",
        created_at=datetime.now(UTC),
        resolved_at=datetime.now(UTC),
        resolved_by=uuid4(),
    )

    # Statistics
    svc.get_audit_statistics.return_value = MagicMock(
        total_events=1000,
        by_event_type={"create": 200, "update": 600, "delete": 100},
        by_severity={"info": 700, "warning": 200, "error": 100},
        by_status={"success": 900, "failure": 100},
        by_actor={"admin": 400, "user1": 300},
        by_hour={"09": 150, "10": 180, "11": 170},
        events_last_24h=80,
        events_last_7d=500,
        events_last_30d=1000,
        average_events_per_day=33.3,
    )

    # Export
    svc.export_audit_data.return_value = (b"csv data", "audit_export_2025.csv")

    return svc


@pytest.fixture
def mock_sampling_engine():
    engine = AsyncMock()
    engine.setup_engagement.return_value = {
        "engagement_id": uuid4(),
        "sample_size": 50,
        "sampling_interval": "2000",
        "materiality_threshold": "50000",
        "performance_materiality": "37500",
        "clearly_trivial_threshold": "2500",
        "confidence_level": 95,
        "expected_error": "1.0",
        "tolerable_error": "5.0",
        "sampling_method": "random",
    }
    engine.evaluate_sample_errors.return_value = {
        "conclusion": "no_material_misstatement",
        "recommendation": "OK",
        "details": {},
        "projected_error": "1000",
        "upper_error_limit": "2500",
        "margin_of_error": "500",
        "is_material": False,
    }
    engine.project_and_conclude.return_value = {
        "conclusion": "no_material_misstatement",
        "recommendation": "OK",
        "details": {},
        "projected_error": "0.02",
        "upper_error_limit": "0.05",
        "margin_of_error": "0.01",
        "is_material": False,
    }
    return engine


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_audit_event_type_values(self):
        assert AuditEventType.CREATE.value == "create"
        assert AuditEventType.UPDATE.value == "update"
        assert AuditEventType.DELETE.value == "delete"
        assert AuditEventType.READ.value == "read"
        assert AuditEventType.SUBMIT.value == "submit"
        assert AuditEventType.APPROVE.value == "approve"
        assert AuditEventType.REJECT.value == "reject"
        assert AuditEventType.POST.value == "post"
        assert AuditEventType.REVERSE.value == "reverse"
        assert AuditEventType.CANCEL.value == "cancel"
        assert AuditEventType.LOCK.value == "lock"
        assert AuditEventType.UNLOCK.value == "unlock"
        assert AuditEventType.ARCHIVE.value == "archive"
        assert AuditEventType.RESTORE.value == "restore"
        assert AuditEventType.EXPORT.value == "export"
        assert AuditEventType.IMPORT.value == "import"
        assert AuditEventType.LOGIN.value == "login"
        assert AuditEventType.LOGOUT.value == "logout"
        assert AuditEventType.PASSWORD_CHANGE.value == "password_change"
        assert AuditEventType.PERMISSION_CHANGE.value == "permission_change"
        assert AuditEventType.SYSTEM_CONFIG.value == "system_config"
        assert AuditEventType.DATA_MIGRATION.value == "data_migration"
        assert AuditEventType.FORENSIC_REPLAY.value == "forensic_replay"
        assert AuditEventType.INTEGRITY_CHECK.value == "integrity_check"

    def test_audit_severity_values(self):
        assert AuditSeverity.DEBUG.value == "debug"
        assert AuditSeverity.INFO.value == "info"
        assert AuditSeverity.WARNING.value == "warning"
        assert AuditSeverity.ERROR.value == "error"
        assert AuditSeverity.CRITICAL.value == "critical"

    def test_audit_status_values(self):
        assert AuditStatus.SUCCESS.value == "success"
        assert AuditStatus.FAILURE.value == "failure"
        assert AuditStatus.PENDING.value == "pending"
        assert AuditStatus.SKIPPED.value == "skipped"

    def test_sampling_method_values(self):
        assert SamplingMethod.RANDOM.value == "random"
        assert SamplingMethod.SYSTEMATIC.value == "systematic"
        assert SamplingMethod.STRATIFIED.value == "stratified"
        assert SamplingMethod.MONETARY_UNIT.value == "monetary_unit"
        assert SamplingMethod.CLUSTER.value == "cluster"
        assert SamplingMethod.JUDGMENTAL.value == "judgmental"

    def test_sampling_conclusion_values(self):
        assert SamplingConclusion.NO_MATERIAL_MISSTATEMENT.value == "no_material_misstatement"
        assert SamplingConclusion.MATERIAL_MISSTATEMENT.value == "material_misstatement"
        assert SamplingConclusion.INCONCLUSIVE.value == "inconclusive"
        assert SamplingConclusion.NEEDS_FURTHER_TESTING.value == "needs_further_testing"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestSamplingSetupSchema:
    def test_valid_schema(self):
        data = {
            "basis_value": Decimal("1000000"),
            "basis_type": "revenue",
            "population_size": 100,
            "population_value": Decimal("50000000"),
            "confidence_level": 95,
            "expected_error_percent": Decimal("1.0"),
            "tolerable_error_percent": Decimal("5.0"),
            "sampling_method": SamplingMethod.RANDOM,
            "materiality_threshold": Decimal("50000"),
        }
        schema = SamplingSetupSchema(**data)
        assert schema.basis_value == Decimal("1000000")
        assert schema.expected_error_percent == Decimal("1.0")

    def test_confidence_level_range(self):
        # valid
        schema = SamplingSetupSchema(
            basis_value=Decimal("1000"),
            basis_type="asset",
            population_size=10,
            confidence_level=80,
            expected_error_percent=Decimal("1"),
            tolerable_error_percent=Decimal("5"),
        )
        assert schema.confidence_level == 80
        # invalid <80
        with pytest.raises(ValueError):
            SamplingSetupSchema(
                basis_value=Decimal("1000"),
                basis_type="asset",
                population_size=10,
                confidence_level=70,
                expected_error_percent=Decimal("1"),
                tolerable_error_percent=Decimal("5"),
            )

    def test_expected_error_range(self):
        # valid
        schema = SamplingSetupSchema(
            basis_value=Decimal("1000"),
            basis_type="asset",
            population_size=10,
            expected_error_percent=Decimal("0"),
            tolerable_error_percent=Decimal("5"),
        )
        assert schema.expected_error_percent == Decimal("0")
        # invalid >100
        with pytest.raises(ValueError):
            SamplingSetupSchema(
                basis_value=Decimal("1000"),
                basis_type="asset",
                population_size=10,
                expected_error_percent=Decimal("150"),
                tolerable_error_percent=Decimal("5"),
            )

    def test_tolerable_error_range(self):
        # valid
        schema = SamplingSetupSchema(
            basis_value=Decimal("1000"),
            basis_type="asset",
            population_size=10,
            expected_error_percent=Decimal("0"),
            tolerable_error_percent=Decimal("100"),
        )
        assert schema.tolerable_error_percent == Decimal("100")
        # invalid >100
        with pytest.raises(ValueError):
            SamplingSetupSchema(
                basis_value=Decimal("1000"),
                basis_type="asset",
                population_size=10,
                expected_error_percent=Decimal("0"),
                tolerable_error_percent=Decimal("101"),
            )

    def test_validate_decimal(self):
        # Test that the validator correctly converts ints/floats to Decimal
        # and returns None for None.
        cls = SamplingSetupSchema

        # int -> Decimal
        result = cls.validate_decimal(123)
        assert isinstance(result, Decimal)
        assert result == Decimal("123")

        # float -> Decimal
        result = cls.validate_decimal(123.45)
        assert isinstance(result, Decimal)
        assert result == Decimal("123.45")

        # Decimal -> Decimal (unchanged)
        d = Decimal("456.78")
        result = cls.validate_decimal(d)
        assert result is d  # should return the same object

        # None -> None
        result = cls.validate_decimal(None)
        assert result is None

        # Already Decimal with different value
        d2 = Decimal("999.99")
        result = cls.validate_decimal(d2)
        assert result is d2

        # Large int
        result = cls.validate_decimal(10**18)
        assert isinstance(result, Decimal)
        assert result == Decimal(10**18)


class TestSamplingEvaluationSchema:
    def test_valid_schema(self):
        data = {
            "errors": [Decimal("100"), Decimal("200")],
            "confidence_level": 95,
        }
        schema = SamplingEvaluationSchema(**data)
        assert len(schema.errors) == 2
        assert schema.errors[0] == Decimal("100")

    def test_errors_converted_to_decimal(self):
        # If ints passed, should convert
        schema = SamplingEvaluationSchema(errors=[100, 200])
        assert isinstance(schema.errors[0], Decimal)
        assert schema.errors[0] == Decimal("100")

    def test_confidence_level_range(self):
        with pytest.raises(ValueError):
            SamplingEvaluationSchema(errors=[1], confidence_level=70)

    def test_validate_errors(self):
        # Test that validator converts list elements to Decimal
        cls = SamplingEvaluationSchema

        # List of ints
        result = cls.validate_errors([1, 2, 3])
        assert isinstance(result, list)
        assert all(isinstance(x, Decimal) for x in result)
        assert result == [Decimal(1), Decimal(2), Decimal(3)]

        # List of floats
        result = cls.validate_errors([1.1, 2.2, 3.3])
        assert all(isinstance(x, Decimal) for x in result)
        assert result == [Decimal("1.1"), Decimal("2.2"), Decimal("3.3")]

        # List of mixed types
        result = cls.validate_errors([1, 2.2, Decimal("3.3")])
        assert all(isinstance(x, Decimal) for x in result)
        assert result == [Decimal(1), Decimal("2.2"), Decimal("3.3")]

        # Empty list
        result = cls.validate_errors([])
        assert result == []

        # List of Decimal objects (should remain unchanged)
        d_list = [Decimal("1.1"), Decimal("2.2")]
        result = cls.validate_errors(d_list)
        assert result is d_list  # should return same list object (identity)

        # Non-list input (should be passed through as is, but will be validated later)
        # The validator just handles the conversion; if it's not a list, it returns as is.
        result = cls.validate_errors("not a list")
        assert result == "not a list"


class TestAuditReportRequestSchema:
    def test_valid_schema(self):
        data = {
            "start_date": date(2025, 1, 1),
            "end_date": date(2025, 1, 31),
            "include_hash_chain_verification": True,
            "include_gap_detection": True,
            "include_sampling_results": False,
            "sampling_engagement_id": uuid4(),
            "report_format": "pdf",
        }
        schema = AuditReportRequestSchema(**data)
        assert schema.start_date == date(2025, 1, 1)
        assert schema.report_format == "pdf"

    def test_report_format_validation(self):
        with pytest.raises(ValueError):
            AuditReportRequestSchema(
                start_date=date.today(),
                end_date=date.today(),
                report_format="docx",  # invalid
            )


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestEventStore:
    async def test_query_event_store(self, mock_audit_service, mock_legal_entity_id):
        request = EventStoreQuerySchema(
            aggregate_type="journal",
            limit=10,
        )
        result = await query_event_store(
            request=request,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], EventStoreEntrySchema)
        mock_audit_service.query_event_store.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            aggregate_type="journal",
            aggregate_id=None,
            event_type=None,
            start_time=None,
            end_time=None,
            user_id=None,
            limit=10,
            offset=0,
        )

    async def test_get_aggregate_events(self, mock_audit_service, mock_legal_entity_id):
        agg_id = uuid4()
        result = await get_aggregate_events(
            aggregate_type="journal",
            aggregate_id=agg_id,
            from_version=1,
            to_version=5,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        mock_audit_service.get_aggregate_events.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            aggregate_type="journal",
            aggregate_id=agg_id,
            from_version=1,
            to_version=5,
        )

    async def test_query_event_store_exception(self, mock_audit_service, mock_legal_entity_id):
        mock_audit_service.query_event_store.side_effect = Exception("DB error")
        request = EventStoreQuerySchema()
        with pytest.raises(HTTPException) as exc:
            await query_event_store(
                request=request,
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                audit_service=mock_audit_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestHashChain:
    async def test_verify_hash_chain_success(self, mock_audit_service, mock_legal_entity_id):
        chain_id = uuid4()
        result = await verify_hash_chain(
            chain_type="event",
            chain_id=chain_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, HashChainVerifyResultSchema)
        assert result.is_chain_valid is True
        mock_audit_service.verify_hash_chain.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            chain_type="event",
            chain_id=chain_id,
        )

    async def test_get_hash_chain_status(self, mock_audit_service, mock_legal_entity_id):
        result = await get_hash_chain_status(
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, HashChainStatusSchema)
        assert result.total_chains == 5
        mock_audit_service.get_hash_chain_status.assert_called_once_with(mock_legal_entity_id)

    async def test_verify_all_chains(self, mock_audit_service, mock_legal_entity_id):
        result = await verify_all_chains(
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert result["total_chains"] == 5
        assert result["valid_chains"] == 5
        mock_audit_service.verify_all_chains.assert_called_once_with(mock_legal_entity_id)


@pytest.mark.asyncio
class TestForensic:
    async def test_forensic_replay_success(self, mock_audit_service, mock_token_payload, mock_legal_entity_id):
        agg_id = uuid4()
        request = ForensicReplayRequestSchema(
            aggregate_type="journal",
            aggregate_id=agg_id,
            target_version=3,
            rebuild_snapshot=True,
        )
        result = await forensic_replay(
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, ForensicReplayResponseSchema)
        assert result.events_replayed == 3
        mock_audit_service.forensic_replay.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            aggregate_type="journal",
            aggregate_id=agg_id,
            target_version=3,
            as_of_time=None,
            rebuild_snapshot=True,
            replayed_by=mock_token_payload.user_id,
        )

    async def test_forensic_replay_value_error(self, mock_audit_service, mock_token_payload, mock_legal_entity_id):
        mock_audit_service.forensic_replay.side_effect = ValueError("Invalid aggregate")
        request = ForensicReplayRequestSchema(
            aggregate_type="invalid",
            aggregate_id=uuid4(),
        )
        with pytest.raises(HTTPException) as exc:
            await forensic_replay(
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                audit_service=mock_audit_service,
            )
        assert exc.value.status_code == 422


@pytest.mark.asyncio
class TestGapDetection:
    async def test_detect_gaps(self, mock_audit_service, mock_legal_entity_id):
        start = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 1, 23, 59, tzinfo=UTC)
        result = await detect_gaps(
            aggregate_type="journal",
            start_time=start,
            end_time=end,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], GapDetectionResultSchema)
        assert result[0].missing_sequence_numbers == [3, 4]
        mock_audit_service.detect_gaps.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            aggregate_type="journal",
            start_time=start,
            end_time=end,
        )


@pytest.mark.asyncio
class TestSampling:
    async def test_setup_sampling_success(self, mock_sampling_engine, mock_legal_entity_id):
        request = SamplingSetupSchema(
            basis_value=Decimal("1000000"),
            basis_type="revenue",
            population_size=1000,
            confidence_level=95,
            expected_error_percent=Decimal("1.0"),
            tolerable_error_percent=Decimal("5.0"),
            sampling_method=SamplingMethod.RANDOM,
            materiality_threshold=Decimal("50000"),
        )
        result = await setup_sampling(
            request=request,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            sampling_engine=mock_sampling_engine,
        )
        assert isinstance(result, SamplingResponseSchema)
        assert result.sample_size == 50
        mock_sampling_engine.setup_engagement.assert_called_once_with(
            legal_entity_id=str(mock_legal_entity_id),
            basis_value=Decimal("1000000"),
            basis_type="revenue",
            population_size=1000,
            population_value=None,
            confidence_level=95,
            expected_error_percent=Decimal("1.0"),
            tolerable_error_percent=Decimal("5.0"),
            sampling_method="random",
            materiality_threshold=Decimal("50000"),
        )

    async def test_setup_sampling_value_error(self, mock_sampling_engine, mock_legal_entity_id):
        mock_sampling_engine.setup_engagement.side_effect = ValueError("Invalid basis")
        request = SamplingSetupSchema(
            basis_value=Decimal("1000"),
            basis_type="revenue",
            population_size=10,
            expected_error_percent=Decimal("1"),
            tolerable_error_percent=Decimal("5"),
        )
        with pytest.raises(HTTPException) as exc:
            await setup_sampling(
                request=request,
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                sampling_engine=mock_sampling_engine,
            )
        assert exc.value.status_code == 422

    async def test_evaluate_sampling(self, mock_sampling_engine, mock_legal_entity_id):
        errors = [Decimal("100"), Decimal("200")]
        result = await evaluate_sampling(
            errors=errors,
            confidence_level=95,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            sampling_engine=mock_sampling_engine,
        )
        assert isinstance(result, SamplingConclusionSchema)
        assert result.conclusion == SamplingConclusion.NO_MATERIAL_MISSTATEMENT
        mock_sampling_engine.evaluate_sample_errors.assert_called_once_with(
            sample_errors=[Decimal("100"), Decimal("200")],
            confidence_level=95,
        )

    async def test_project_sampling(self, mock_sampling_engine, mock_legal_entity_id):
        errors = [Decimal("0.02"), Decimal("0.03")]
        result = await project_sampling(
            sample_errors=errors,
            population_size=1000,
            confidence_level=95,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            sampling_engine=mock_sampling_engine,
        )
        assert isinstance(result, SamplingConclusionSchema)
        mock_sampling_engine.project_and_conclude.assert_called_once_with(
            sample_errors=[Decimal("0.02"), Decimal("0.03")],
            population_size=1000,
            confidence_level=95,
        )


@pytest.mark.asyncio
class TestSOX:
    async def test_test_sox_control_success(self, mock_audit_service, mock_token_payload, mock_legal_entity_id):
        request = SOXControlTestSchema(
            control_id="SOX-001",
            control_name="Access Control",
            control_category="ITGC",
            test_period_start=date(2025, 1, 1),
            test_period_end=date(2025, 1, 31),
            sample_size=25,
            deviations=1,
            notes="Test",
        )
        result = await test_sox_control(
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, SOXControlTestResponseSchema)
        assert result.is_effective is True
        mock_audit_service.test_sox_control.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            control_id="SOX-001",
            control_name="Access Control",
            control_category="ITGC",
            test_period_start=date(2025, 1, 1),
            test_period_end=date(2025, 1, 31),
            sample_size=25,
            deviations=1,
            notes="Test",
            tested_by=mock_token_payload.user_id,
        )

    async def test_test_sox_control_value_error(self, mock_audit_service, mock_token_payload, mock_legal_entity_id):
        mock_audit_service.test_sox_control.side_effect = ValueError("Invalid sample size")
        request = SOXControlTestSchema(
            control_id="SOX-001",
            control_name="Test",
            control_category="ITGC",
            test_period_start=date.today(),
            test_period_end=date.today(),
            sample_size=0,
            deviations=0,
        )
        with pytest.raises(HTTPException) as exc:
            await test_sox_control(
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                audit_service=mock_audit_service,
            )
        assert exc.value.status_code == 422

    async def test_get_sox_controls_status(self, mock_audit_service, mock_legal_entity_id):
        result = await get_sox_controls_status(
            effective_only=True,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["control_id"] == "SOX-001"
        mock_audit_service.get_sox_controls_status.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            effective_only=True,
        )


@pytest.mark.asyncio
class TestAuditReport:
    async def test_generate_report_success(self, mock_audit_service, mock_token_payload, mock_legal_entity_id):
        request = AuditReportRequestSchema(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            report_format="pdf",
        )
        result = await generate_audit_report(
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, AuditReportResponseSchema)
        assert result.report_number == "AUD-2025-001"
        mock_audit_service.generate_audit_report.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            include_hash_chain_verification=True,
            include_gap_detection=True,
            include_sampling_results=False,
            sampling_engagement_id=None,
            report_format="pdf",
            generated_by=mock_token_payload.user_id,
        )

    async def test_download_report_success(self, mock_audit_service, mock_legal_entity_id):
        report_id = uuid4()
        response = await download_audit_report(
            report_id=report_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert response.body == b"PDF content"
        assert response.media_type == "application/pdf"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_audit_service.download_audit_report.assert_called_once_with(
            report_id=report_id,
            legal_entity_id=mock_legal_entity_id,
        )

    async def test_download_report_not_found(self, mock_audit_service, mock_legal_entity_id):
        mock_audit_service.download_audit_report.side_effect = ValueError("Report not found")
        with pytest.raises(HTTPException) as exc:
            await download_audit_report(
                report_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                audit_service=mock_audit_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestAuditTrail:
    async def test_get_audit_trail(self, mock_audit_service, mock_legal_entity_id):
        entity_id = uuid4()
        result = await get_audit_trail(
            entity_type="journal",
            entity_id=entity_id,
            start_time=None,
            end_time=None,
            limit=50,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], AuditTrailSchema)
        mock_audit_service.get_audit_trail.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            entity_type="journal",
            entity_id=entity_id,
            start_time=None,
            end_time=None,
            limit=50,
        )


@pytest.mark.asyncio
class TestAuditFindings:
    async def test_get_findings(self, mock_audit_service, mock_legal_entity_id):
        result = await get_audit_findings(
            status="open",
            severity=AuditSeverity.WARNING,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], AuditFindingSchema)
        mock_audit_service.get_audit_findings.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            status="open",
            severity="warning",
        )

    async def test_resolve_finding_success(self, mock_audit_service, mock_token_payload, mock_legal_entity_id):
        finding_id = uuid4()
        result = await resolve_audit_finding(
            finding_id=finding_id,
            resolution_notes="Fixed",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, AuditFindingSchema)
        assert result.status == "resolved"
        mock_audit_service.resolve_audit_finding.assert_called_once_with(
            finding_id=finding_id,
            legal_entity_id=mock_legal_entity_id,
            resolution_notes="Fixed",
            resolved_by=mock_token_payload.user_id,
        )

    async def test_resolve_finding_not_found(self, mock_audit_service, mock_token_payload, mock_legal_entity_id):
        mock_audit_service.resolve_audit_finding.return_value = None
        with pytest.raises(HTTPException) as exc:
            await resolve_audit_finding(
                finding_id=uuid4(),
                resolution_notes="Test",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                audit_service=mock_audit_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestAuditStatistics:
    async def test_get_statistics(self, mock_audit_service, mock_legal_entity_id):
        result = await get_audit_statistics(
            days=30,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert isinstance(result, AuditStatisticsSchema)
        assert result.total_events == 1000
        assert result.events_last_24h == 80
        mock_audit_service.get_audit_statistics.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            days=30,
        )


@pytest.mark.asyncio
class TestExport:
    async def test_export_csv(self, mock_audit_service, mock_legal_entity_id):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        response = await export_audit_data(
            start_time=start,
            end_time=end,
            format="csv",
            event_types=["create", "update"],
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_audit_service.export_audit_data.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_time=start,
            end_time=end,
            format="csv",
            event_types=["create", "update"],
        )

    async def test_export_excel(self, mock_audit_service, mock_legal_entity_id):
        mock_audit_service.export_audit_data.return_value = (b"excel data", "audit.xlsx")
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        response = await export_audit_data(
            start_time=start,
            end_time=end,
            format="excel",
            event_types=None,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            audit_service=mock_audit_service,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# =============================================================================
# Tests for Dependency Injections
# =============================================================================

@pytest.mark.asyncio
async def test_get_audit_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_audit_service(request)
    assert result == "service"


@pytest.mark.asyncio
async def test_get_sampling_engine():
    with patch("importlib.import_module") as mock_import:
        mock_mod = MagicMock()
        mock_mod.get_sampling_engine.return_value = "engine"
        mock_import.return_value = mock_mod
        result = await get_sampling_engine()
        assert result == "engine"
        mock_import.assert_called_once_with(
            "audit.sampling_materiality.audit_sampling_engine_materiality_based"
        )
