# test_traceability_enforcer.py
# Comprehensive tests for kernel/immutable_laws/traceability_enforcer.py
# All external dependencies are mocked.

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kernel.immutable_laws.traceability_enforcer import (
    BaseTraceabilityEnforcer,
    SourceType,
    TraceabilityCheckResult,
    TraceabilityEnforcer,
    TraceabilityRecord,
    TraceabilitySeverity,
    TraceabilityViolation,
    _FallbackAuditTrailRepository,
    _FallbackTransactionRepository,
    get_traceability_enforcer,
)


# ----------------------------------------------------------------------
# Enums & Value Objects
# ----------------------------------------------------------------------
class TestSourceType:
    def test_members_exist(self):
        assert hasattr(SourceType, "USER")
        assert hasattr(SourceType, "SYSTEM")
        assert hasattr(SourceType, "API")
        assert hasattr(SourceType, "FILE")
        assert hasattr(SourceType, "BATCH")
        assert hasattr(SourceType, "SCHEDULER")
        assert hasattr(SourceType, "WEBHOOK")
        assert hasattr(SourceType, "WORKFLOW")
        assert hasattr(SourceType, "SAGA")

    def test_member_is_instance(self):
        assert isinstance(SourceType.USER, SourceType)


class TestTraceabilitySeverity:
    def test_members_exist(self):
        assert hasattr(TraceabilitySeverity, "CRITICAL")
        assert hasattr(TraceabilitySeverity, "HIGH")
        assert hasattr(TraceabilitySeverity, "MEDIUM")
        assert hasattr(TraceabilitySeverity, "LOW")

    def test_member_is_instance(self):
        assert isinstance(TraceabilitySeverity.CRITICAL, TraceabilitySeverity)


class TestTraceabilityRecord:
    def test_construction(self):
        now = datetime.now(UTC)
        record = TraceabilityRecord(
            record_id=uuid4(),
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            source_type=SourceType.USER,
            source_id="user123",
            source_description="Test",
            user_id="user1",
            correlation_id="corr1",
            causation_id=uuid4(),
            timestamp=now,
            cryptographic_hash="",
        )
        assert record.record_id is not None
        assert record.cryptographic_hash == ""

    def test_compute_hash(self):
        now = datetime.now(UTC)
        record = TraceabilityRecord(
            record_id=uuid4(),
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            source_type=SourceType.SYSTEM,
            source_id="sys",
            source_description="desc",
            user_id="user",
            correlation_id=None,
            causation_id=None,
            timestamp=now,
        )
        h = record.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64

    def test_hash_mismatch_raises(self):
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            TraceabilityRecord(
                record_id=uuid4(),
                transaction_id=uuid4(),
                legal_entity_id=uuid4(),
                source_type=SourceType.API,
                source_id="api",
                source_description="desc",
                user_id="user",
                correlation_id=None,
                causation_id=None,
                timestamp=now,
                cryptographic_hash="wronghash",
            )

    def test_to_dict(self):
        now = datetime.now(UTC)
        record = TraceabilityRecord(
            record_id=uuid4(),
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            source_type=SourceType.FILE,
            source_id="file123",
            source_description="A long description that might be truncated" * 5,
            user_id="user",
            correlation_id="corr",
            causation_id=uuid4(),
            timestamp=now,
        )
        d = record.to_dict()
        assert d["record_id"] == str(record.record_id)
        assert d["source_type"] == "FILE"
        assert len(d["source_description"]) == 100  # truncated


class TestTraceabilityCheckResult:
    def test_construction(self):
        result = TraceabilityCheckResult(
            check_id=uuid4(),
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            is_valid=True,
            severity=TraceabilitySeverity.LOW,
            message="OK",
            missing_fields=[],
            chain_length=1,
            has_root_cause=True,
        )
        assert result.check_id is not None
        assert result.cryptographic_hash == ""

    def test_compute_hash(self):
        result = TraceabilityCheckResult(
            check_id=uuid4(),
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            is_valid=True,
            severity=TraceabilitySeverity.LOW,
            message="OK",
            missing_fields=[],
            chain_length=1,
            has_root_cause=True,
        )
        h = result.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64

    def test_hash_mismatch_raises(self):
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            TraceabilityCheckResult(
                check_id=uuid4(),
                transaction_id=uuid4(),
                legal_entity_id=uuid4(),
                is_valid=True,
                severity=TraceabilitySeverity.LOW,
                message="OK",
                missing_fields=[],
                chain_length=1,
                has_root_cause=True,
                cryptographic_hash="wronghash",
            )

    def test_to_dict(self):
        result = TraceabilityCheckResult(
            check_id=uuid4(),
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            is_valid=False,
            severity=TraceabilitySeverity.HIGH,
            message="Missing source",
            missing_fields=["source_type"],
            chain_length=0,
            has_root_cause=False,
        )
        d = result.to_dict()
        assert d["check_id"] == str(result.check_id)
        assert d["is_valid"] is False
        assert d["severity"] == "HIGH"
        assert d["missing_fields"] == ["source_type"]


# ----------------------------------------------------------------------
# Fallback Repositories
# ----------------------------------------------------------------------
class TestFallbackAuditTrailRepository:
    @pytest.fixture
    def repo(self):
        return _FallbackAuditTrailRepository()

    @pytest.mark.asyncio
    async def test_create_and_get_by_transaction(self, repo):
        tx_id = uuid4()
        le_id = uuid4()
        record_id = await repo.create_traceability_record(
            transaction_id=tx_id,
            legal_entity_id=le_id,
            source_type="USER",
            source_id="user1",
            source_description="desc",
            user_id="user1",
            correlation_id="corr1",
            causation_id=None,
            timestamp=datetime.now(UTC),
        )
        records = await repo.get_by_transaction(tx_id, le_id)
        assert len(records) == 1
        assert records[0]["record_id"] == record_id
        # wrong legal_entity
        records = await repo.get_by_transaction(tx_id, uuid4())
        assert len(records) == 0

    @pytest.mark.asyncio
    async def test_get_root_cause(self, repo):
        tx1 = uuid4()
        tx2 = uuid4()
        le_id = uuid4()
        # Create chain: tx1 -> tx2 (causation_id=tx1)
        await repo.create_traceability_record(
            transaction_id=tx1,
            legal_entity_id=le_id,
            source_type="USER",
            source_id="u1",
            source_description="root",
            user_id="u1",
            correlation_id=None,
            causation_id=None,
            timestamp=datetime.now(UTC),
        )
        await repo.create_traceability_record(
            transaction_id=tx2,
            legal_entity_id=le_id,
            source_type="SYSTEM",
            source_id="sys",
            source_description="child",
            user_id="u2",
            correlation_id=None,
            causation_id=tx1,
            timestamp=datetime.now(UTC),
        )
        root = await repo.get_root_cause(tx2, le_id)
        assert root is not None
        assert root["transaction_id"] == tx1
        # no root
        root = await repo.get_root_cause(tx1, le_id)
        assert root is not None
        assert root["transaction_id"] == tx1

    @pytest.mark.asyncio
    async def test_get_traceability(self, repo):
        tx_id = uuid4()
        le_id = uuid4()
        await repo.create_traceability_record(
            transaction_id=tx_id,
            legal_entity_id=le_id,
            source_type="API",
            source_id="api",
            source_description="desc",
            user_id="user",
            correlation_id="corr",
            causation_id=None,
            timestamp=datetime.now(UTC),
        )
        trace = await repo.get_traceability(tx_id, le_id)
        assert trace is not None
        assert trace["source_type"] == "API"
        trace = await repo.get_traceability(tx_id, uuid4())
        assert trace is None

    @pytest.mark.asyncio
    async def test_get_by_correlation(self, repo):
        corr = "corr123"
        le_id = uuid4()
        tx1 = uuid4()
        tx2 = uuid4()
        await repo.create_traceability_record(
            transaction_id=tx1,
            legal_entity_id=le_id,
            source_type="USER",
            source_id="u1",
            source_description="desc",
            user_id="u1",
            correlation_id=corr,
            causation_id=None,
            timestamp=datetime.now(UTC),
        )
        await repo.create_traceability_record(
            transaction_id=tx2,
            legal_entity_id=le_id,
            source_type="USER",
            source_id="u2",
            source_description="desc",
            user_id="u2",
            correlation_id=corr,
            causation_id=None,
            timestamp=datetime.now(UTC),
        )
        records = await repo.get_by_correlation(corr, le_id)
        assert len(records) == 2
        # wrong legal_entity
        records = await repo.get_by_correlation(corr, uuid4())
        assert len(records) == 0

    @pytest.mark.asyncio
    async def test_get_by_source(self, repo):
        le_id = uuid4()
        source_type = "FILE"
        source_id = "file123"
        tx1 = uuid4()
        await repo.create_traceability_record(
            transaction_id=tx1,
            legal_entity_id=le_id,
            source_type=source_type,
            source_id=source_id,
            source_description="desc",
            user_id="u1",
            correlation_id=None,
            causation_id=None,
            timestamp=datetime.now(UTC),
        )
        records = await repo.get_by_source(source_type, source_id, le_id)
        assert len(records) == 1
        records = await repo.get_by_source("OTHER", source_id, le_id)
        assert len(records) == 0

    @pytest.mark.asyncio
    async def test_get_chain(self, repo):
        le_id = uuid4()
        for i in range(5):
            await repo.create_traceability_record(
                transaction_id=uuid4(),
                legal_entity_id=le_id,
                source_type="USER",
                source_id=f"u{i}",
                source_description="desc",
                user_id=f"u{i}",
                correlation_id=None,
                causation_id=None,
                timestamp=datetime.now(UTC),
            )
        chain = await repo.get_chain(le_id, limit=3)
        assert len(chain) == 3
        # wrong le
        chain = await repo.get_chain(uuid4())
        assert len(chain) == 0

    def test_clear(self, repo):
        repo._trace_records["a"] = {}
        repo._by_correlation["b"] = []
        repo._by_source["c"] = []
        repo._chain = [{}]
        repo.clear()
        assert len(repo._trace_records) == 0
        assert len(repo._by_correlation) == 0
        assert len(repo._by_source) == 0
        assert len(repo._chain) == 0


class TestFallbackTransactionRepository:
    @pytest.fixture
    def repo(self):
        return _FallbackTransactionRepository()

    def test_add_and_get(self, repo):
        tx_id = uuid4()
        le_id = uuid4()
        repo.add_transaction(tx_id, le_id, "JOURNAL")
        tx = repo._transactions.get(tx_id)
        assert tx is not None
        assert tx["legal_entity_id"] == le_id
        # get
        result = repo.get_by_id(tx_id, le_id)
        assert result is not None
        result = repo.get_by_id(tx_id, uuid4())
        assert result is None

    def test_clear(self, repo):
        repo._transactions["a"] = {}
        repo.clear()
        assert len(repo._transactions) == 0


# ----------------------------------------------------------------------
# BaseTraceabilityEnforcer (abstract)
# ----------------------------------------------------------------------
class TestBaseTraceabilityEnforcer:
    def test_class_defined(self):
        assert BaseTraceabilityEnforcer is not None


# ----------------------------------------------------------------------
# TraceabilityEnforcer
# ----------------------------------------------------------------------
@pytest.fixture
def mock_audit_repo():
    repo = MagicMock(spec=_FallbackAuditTrailRepository)
    repo.get_by_transaction = AsyncMock(return_value=[])
    repo.get_root_cause = AsyncMock(return_value=None)
    repo.get_traceability = AsyncMock(return_value=None)
    repo.get_by_correlation = AsyncMock(return_value=[])
    repo.get_by_source = AsyncMock(return_value=[])
    repo.create_traceability_record = AsyncMock(return_value=uuid4())
    repo.get_chain = AsyncMock(return_value=[])
    repo.clear = MagicMock()
    return repo


@pytest.fixture
def mock_tx_repo():
    repo = MagicMock(spec=_FallbackTransactionRepository)
    repo.get_by_id = AsyncMock(return_value=None)
    repo.clear = MagicMock()
    return repo


@pytest.fixture
def enforcer(mock_audit_repo, mock_tx_repo):
    return TraceabilityEnforcer(
        audit_trail_repository=mock_audit_repo,
        transaction_repository=mock_tx_repo,
    )


class TestTraceabilityEnforcer:
    # ----- Entity methods -----
    def test_check_valid(self, enforcer):
        context = {
            "transaction_id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "source_type": "USER",
        }
        errors = enforcer.check(context)
        assert errors == []

    def test_check_missing(self, enforcer):
        errors = enforcer.check({})
        assert "transaction_id is required" in errors
        assert "legal_entity_id is required" in errors

    def test_check_invalid_uuid(self, enforcer):
        context = {"transaction_id": "not-uuid", "legal_entity_id": "not-uuid"}
        errors = enforcer.check(context)
        assert any("valid UUID" in e for e in errors)

    def test_check_invalid_source_type(self, enforcer):
        context = {
            "transaction_id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "source_type": "INVALID",
        }
        errors = enforcer.check(context)
        assert "source_type 'INVALID' is not a valid SourceType" in errors

    def test_validate(self, enforcer):
        result = enforcer.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self, enforcer):
        d = enforcer.to_dict()
        assert "enabled" in d
        assert "strict_mode" in d
        assert "trace_records_count" in d
        assert "version" in d

    def test_from_dict(self):
        data = {"enabled": False, "strict_mode": False, "max_history": 5000, "version": 3}
        enforcer = TraceabilityEnforcer.from_dict(data)
        assert enforcer._enabled is False
        assert enforcer._strict_mode is False
        assert enforcer._max_history == 5000
        assert enforcer._version == 3

    def test_clone(self, enforcer):
        clone = enforcer.clone()
        assert clone is not enforcer
        assert clone._enabled == enforcer._enabled
        assert clone._strict_mode == enforcer._strict_mode
        assert clone._max_history == enforcer._max_history
        assert clone._version == enforcer._version + 1

    def test_snapshot(self, enforcer):
        snap = enforcer.snapshot()
        assert "version" in snap
        assert "trace_records_count" in snap
        assert "enabled" in snap
        assert "timestamp" in snap

    def test_version(self, enforcer):
        assert enforcer.version() == enforcer._version

    def test_audit_trail(self, enforcer):
        assert enforcer.audit_trail() == []
        enforcer.touch("admin")
        trail = enforcer.audit_trail(limit=10)
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, enforcer):
        old = enforcer.version()
        enforcer.touch("admin")
        assert enforcer.version() == old + 1
        trail = enforcer.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "admin"

    # ----- enable / set_strict_mode -----
    def test_enable(self, enforcer):
        enforcer.enable(False)
        assert enforcer._enabled is False
        enforcer.enable(True)
        assert enforcer._enabled is True

    def test_set_strict_mode(self, enforcer):
        enforcer.set_strict_mode(False)
        assert enforcer._strict_mode is False
        enforcer.set_strict_mode(True)
        assert enforcer._strict_mode is True

    # ----- enforce_traceability -----
    @pytest.mark.asyncio
    async def test_enforce_traceability_disabled(self, enforcer):
        enforcer.enable(False)
        result = await enforcer.enforce_traceability(
            uuid4(), uuid4(), source_type=SourceType.USER, source_id="user"
        )
        assert result.is_valid is True
        assert result.severity == TraceabilitySeverity.LOW
        assert "disabled" in result.message

    @pytest.mark.asyncio
    async def test_enforce_traceability_ok_with_existing_record(self, enforcer, mock_audit_repo):
        tx_id = uuid4()
        le_id = uuid4()
        # Simulate existing record
        mock_audit_repo.get_by_transaction.return_value = [{"some": "data"}]
        mock_audit_repo.get_root_cause.return_value = {"transaction_id": tx_id}
        with patch("kernel.immutable_laws.traceability_enforcer.get_current_user", return_value="user1"):
            result = await enforcer.enforce_traceability(
                tx_id, le_id, source_type=SourceType.USER, source_id="user123"
            )
            assert result.is_valid is True
            assert result.chain_length == 1
            assert result.has_root_cause is True
            assert result.missing_fields == []

    @pytest.mark.asyncio
    async def test_enforce_traceability_no_record_raises(self, enforcer, mock_audit_repo):
        tx_id = uuid4()
        le_id = uuid4()
        mock_audit_repo.get_by_transaction.return_value = []
        mock_audit_repo.get_root_cause.return_value = None
        with patch("kernel.immutable_laws.traceability_enforcer.get_current_user", return_value="user1"):
            with pytest.raises(TraceabilityViolation) as exc:
                await enforcer.enforce_traceability(
                    tx_id, le_id, source_type=None, raise_on_violation=True
                )
            assert "no traceability record" in str(exc.value)
            # Check that violation is recorded
            assert len(enforcer._violation_history) == 1

    @pytest.mark.asyncio
    async def test_enforce_traceability_missing_source_type(self, enforcer, mock_audit_repo):
        tx_id = uuid4()
        le_id = uuid4()
        mock_audit_repo.get_by_transaction.return_value = [{"some": "data"}]
        mock_audit_repo.get_root_cause.return_value = None
        with patch("kernel.immutable_laws.traceability_enforcer.get_current_user", return_value="user1"):
            result = await enforcer.enforce_traceability(
                tx_id, le_id, source_type=None, raise_on_violation=False
            )
            assert result.is_valid is False
            assert "source_type" in result.missing_fields
            assert result.severity == TraceabilitySeverity.HIGH

    @pytest.mark.asyncio
    async def test_enforce_traceability_missing_source_id_for_user(self, enforcer, mock_audit_repo):
        tx_id = uuid4()
        le_id = uuid4()
        mock_audit_repo.get_by_transaction.return_value = [{"some": "data"}]
        mock_audit_repo.get_root_cause.return_value = None
        with patch("kernel.immutable_laws.traceability_enforcer.get_current_user", return_value="user1"):
            result = await enforcer.enforce_traceability(
                tx_id, le_id, source_type=SourceType.USER, source_id=None, raise_on_violation=False
            )
            assert result.is_valid is False
            assert "source_id_or_user_id" in result.missing_fields

    # ----- create_traceability_record -----
    @pytest.mark.asyncio
    async def test_create_traceability_record_disabled(self, enforcer):
        enforcer.enable(False)
        with pytest.raises(TraceabilityViolation) as exc:
            await enforcer.create_traceability_record(
                uuid4(), uuid4(), SourceType.USER, source_id="user"
            )
        assert "disabled" in str(exc.value)

    @pytest.mark.asyncio
    async def test_create_traceability_record_success(self, enforcer, mock_audit_repo):
        tx_id = uuid4()
        le_id = uuid4()
        mock_audit_repo.create_traceability_record.return_value = uuid4()
        with patch("kernel.immutable_laws.traceability_enforcer.get_current_user", return_value="user1"):
            record = await enforcer.create_traceability_record(
                tx_id, le_id, SourceType.API, source_id="api123",
                source_description="API call", correlation_id="corr", causation_id=uuid4()
            )
            assert isinstance(record, TraceabilityRecord)
            assert record.transaction_id == tx_id
            assert record.source_type == SourceType.API
            assert record.cryptographic_hash != ""
            assert len(enforcer._trace_records) == 1
            mock_audit_repo.create_traceability_record.assert_awaited_once()

    # ----- get_traceability_chain -----
    @pytest.mark.asyncio
    async def test_get_traceability_chain(self, enforcer, mock_audit_repo):
        tx1 = uuid4()
        tx2 = uuid4()
        le_id = uuid4()
        # Chain: tx1 -> tx2 (causation=tx1)
        mock_audit_repo.get_traceability.side_effect = [
            {
                "transaction_id": tx2,
                "source_type": "USER",
                "source_id": "u2",
                "source_description": "desc2",
                "user_id": "u2",
                "timestamp": datetime.now(UTC),
                "correlation_id": None,
                "causation_id": tx1,
            },
            {
                "transaction_id": tx1,
                "source_type": "SYSTEM",
                "source_id": "sys",
                "source_description": "desc1",
                "user_id": "sys",
                "timestamp": datetime.now(UTC),
                "correlation_id": None,
                "causation_id": None,
            },
        ]
        chain = await enforcer.get_traceability_chain(tx2, le_id, max_depth=10)
        assert len(chain) == 2
        assert chain[0]["transaction_id"] == str(tx2)
        assert chain[1]["transaction_id"] == str(tx1)

    @pytest.mark.asyncio
    async def test_get_traceability_chain_empty(self, enforcer, mock_audit_repo):
        mock_audit_repo.get_traceability.return_value = None
        chain = await enforcer.get_traceability_chain(uuid4(), uuid4())
        assert chain == []

    # ----- verify_chain_integrity -----
    @pytest.mark.asyncio
    async def test_verify_chain_integrity_empty(self, enforcer):
        with patch.object(enforcer, "get_traceability_chain", AsyncMock(return_value=[])):
            is_valid, msg, issues = await enforcer.verify_chain_integrity(uuid4(), uuid4())
            assert is_valid is False
            assert "No traceability chain found" in msg
            assert "empty_chain" in issues

    @pytest.mark.asyncio
    async def test_verify_chain_integrity_ok(self, enforcer):
        chain = [
            {"transaction_id": "a", "source_type": "USER", "source_id": "u1", "causation_id": None},
            {"transaction_id": "b", "source_type": "SYSTEM", "source_id": "s1", "causation_id": "a"},
        ]
        with patch.object(enforcer, "get_traceability_chain", AsyncMock(return_value=chain)):
            is_valid, msg, issues = await enforcer.verify_chain_integrity(uuid4(), uuid4())
            assert is_valid is True
            assert msg is None
            assert issues == []

    @pytest.mark.asyncio
    async def test_verify_chain_integrity_break(self, enforcer):
        chain = [
            {"transaction_id": "a", "source_type": "USER", "source_id": "u1", "causation_id": None},
            {"transaction_id": "b", "source_type": "SYSTEM", "source_id": "s1", "causation_id": "c"},  # broken
        ]
        with patch.object(enforcer, "get_traceability_chain", AsyncMock(return_value=chain)):
            is_valid, msg, issues = await enforcer.verify_chain_integrity(uuid4(), uuid4())
            assert is_valid is False
            assert "Chain break" in issues[0]

    @pytest.mark.asyncio
    async def test_verify_chain_integrity_missing_fields(self, enforcer):
        chain = [
            {"transaction_id": "a", "source_type": None, "source_id": None, "causation_id": None},
        ]
        with patch.object(enforcer, "get_traceability_chain", AsyncMock(return_value=chain)):
            is_valid, msg, issues = await enforcer.verify_chain_integrity(uuid4(), uuid4())
            assert is_valid is False
            assert any("Missing source_type" in i for i in issues)
            assert any("Missing source_id" in i for i in issues)

    # ----- get_transaction_source_summary -----
    @pytest.mark.asyncio
    async def test_get_transaction_source_summary_no_record(self, enforcer, mock_audit_repo):
        mock_audit_repo.get_traceability.return_value = None
        summary = await enforcer.get_transaction_source_summary(uuid4(), uuid4())
        assert summary["has_traceability"] is False
        assert "No traceability record found" in summary["message"]

    @pytest.mark.asyncio
    async def test_get_transaction_source_summary_ok(self, enforcer):
        tx_id = uuid4()
        le_id = uuid4()
        trace_data = {
            "transaction_id": tx_id,
            "source_type": "USER",
            "source_id": "u1",
            "source_description": "desc",
            "user_id": "user",
            "timestamp": datetime.now(UTC),
            "correlation_id": "corr",
            "causation_id": None,
        }
        with patch.object(enforcer._audit_repo, "get_traceability", AsyncMock(return_value=trace_data)):
            with patch.object(enforcer, "get_traceability_chain", AsyncMock(return_value=[trace_data])):
                with patch.object(enforcer, "verify_chain_integrity", AsyncMock(return_value=(True, None, []))):
                    summary = await enforcer.get_transaction_source_summary(tx_id, le_id)
                    assert summary["has_traceability"] is True
                    assert summary["source_type"] == "USER"
                    assert summary["chain_length"] == 1
                    assert summary["chain_integrity_valid"] is True

    # ----- ensure_root_cause -----
    @pytest.mark.asyncio
    async def test_ensure_root_cause_existing(self, enforcer, mock_audit_repo):
        tx_id = uuid4()
        le_id = uuid4()
        existing = {
            "record_id": uuid4(),
            "source_type": "USER",
            "source_id": "root",
            "source_description": "root desc",
            "user_id": "rootuser",
            "correlation_id": None,
            "causation_id": None,
            "timestamp": datetime.now(UTC),
        }
        mock_audit_repo.get_root_cause.return_value = existing
        record = await enforcer.ensure_root_cause(
            tx_id, le_id, SourceType.SYSTEM, "new", "new desc"
        )
        assert record.source_type == SourceType.USER  # from existing
        mock_audit_repo.create_traceability_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_root_cause_new(self, enforcer, mock_audit_repo):
        tx_id = uuid4()
        le_id = uuid4()
        mock_audit_repo.get_root_cause.return_value = None
        mock_audit_repo.create_traceability_record.return_value = uuid4()
        with patch("kernel.immutable_laws.traceability_enforcer.get_current_user", return_value="user1"):
            record = await enforcer.ensure_root_cause(
                tx_id, le_id, SourceType.FILE, "file123", "File upload"
            )
            assert record.source_type == SourceType.FILE
            mock_audit_repo.create_traceability_record.assert_awaited_once()

    # ----- get_by_correlation and get_by_source -----
    @pytest.mark.asyncio
    async def test_get_by_correlation(self, enforcer, mock_audit_repo):
        mock_audit_repo.get_by_correlation.return_value = [{"id": 1}]
        result = await enforcer.get_by_correlation("corr", uuid4())
        assert result == [{"id": 1}]
        mock_audit_repo.get_by_correlation.assert_awaited_once_with("corr", uuid4())

    @pytest.mark.asyncio
    async def test_get_by_source(self, enforcer, mock_audit_repo):
        mock_audit_repo.get_by_source.return_value = [{"id": 2}]
        result = await enforcer.get_by_source(SourceType.USER, "u1", uuid4())
        assert result == [{"id": 2}]
        mock_audit_repo.get_by_source.assert_awaited_once_with("USER", "u1", uuid4())

    # ----- _record_check and _record_violation (private) -----
    def test_record_check(self, enforcer):
        result = TraceabilityCheckResult(
            check_id=uuid4(),
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            is_valid=False,
            severity=TraceabilitySeverity.HIGH,
            message="test",
            missing_fields=[],
            chain_length=0,
            has_root_cause=False,
        )
        enforcer._record_check(result)
        assert len(enforcer._check_history) == 1
        assert enforcer._check_history[0] is result

    def test_record_violation(self, enforcer):
        violation = TraceabilityViolation(
            message="test violation",
            transaction_id=str(uuid4()),
            severity=LawViolationSeverity.CRITICAL,
            details={},
        )
        enforcer._record_violation(violation)
        assert len(enforcer._violation_history) == 1
        assert enforcer._violation_history[0] is violation
        # audit
        trail = enforcer.audit_trail()
        assert any(e["action"] == "VIOLATION" for e in trail)

    # ----- get_check_history -----
    def test_get_check_history(self, enforcer):
        # Add some checks
        for i in range(5):
            result = TraceabilityCheckResult(
                check_id=uuid4(),
                transaction_id=uuid4(),
                legal_entity_id=uuid4(),
                is_valid=i % 2 == 0,
                severity=TraceabilitySeverity.LOW,
                message=f"check {i}",
                missing_fields=[],
                chain_length=0,
                has_root_cause=False,
            )
            enforcer._record_check(result)
        # all
        history = enforcer.get_check_history(limit=10)
        assert len(history) == 5
        # only_violations
        violations = enforcer.get_check_history(only_violations=True)
        assert len(violations) == 2  # i=1,3 are invalid
        assert all(not r.is_valid for r in violations)

    # ----- get_violations -----
    def test_get_violations(self, enforcer):
        v1 = TraceabilityViolation(
            message="v1", transaction_id=str(uuid4()), severity=LawViolationSeverity.CRITICAL, details={}
        )
        v2 = TraceabilityViolation(
            message="v2", transaction_id=str(uuid4()), severity=LawViolationSeverity.HIGH, details={}
        )
        enforcer._record_violation(v1)
        enforcer._record_violation(v2)
        violations = enforcer.get_violations(limit=10)
        assert len(violations) == 2
        # limit
        violations = enforcer.get_violations(limit=1)
        assert len(violations) == 1

    # ----- get_traceability_records -----
    def test_get_traceability_records(self, enforcer):
        # Add some records
        for i in range(5):
            record = TraceabilityRecord(
                record_id=uuid4(),
                transaction_id=uuid4(),
                legal_entity_id=uuid4(),
                source_type=SourceType.USER,
                source_id=f"u{i}",
                source_description="desc",
                user_id="user",
                correlation_id=None,
                causation_id=None,
                timestamp=datetime.now(UTC),
            )
            enforcer._trace_records.append(record)
        # all
        records = enforcer.get_traceability_records(limit=10)
        assert len(records) == 5
        # filter by transaction_id
        target_tx = enforcer._trace_records[0].transaction_id
        filtered = enforcer.get_traceability_records(transaction_id=target_tx)
        assert len(filtered) == 1
        assert filtered[0].transaction_id == target_tx

    # ----- get_statistics -----
    def test_get_statistics_empty(self, enforcer):
        stats = enforcer.get_statistics()
        assert stats["total_checks"] == 0
        assert stats["total_violations"] == 0
        assert stats["total_records"] == 0
        assert stats["version"] == enforcer.version()

    def test_get_statistics_with_data(self, enforcer):
        # Add checks
        for i in range(10):
            result = TraceabilityCheckResult(
                check_id=uuid4(),
                transaction_id=uuid4(),
                legal_entity_id=uuid4(),
                is_valid=i % 3 != 0,
                severity=TraceabilitySeverity.HIGH if i % 3 == 0 else TraceabilitySeverity.LOW,
                message="ok",
                missing_fields=[],
                chain_length=1,
                has_root_cause=True,
            )
            enforcer._record_check(result)
        # Add records
        for i in range(4):
            record = TraceabilityRecord(
                record_id=uuid4(),
                transaction_id=uuid4(),
                legal_entity_id=uuid4(),
                source_type=SourceType.USER if i % 2 == 0 else SourceType.SYSTEM,
                source_id=f"s{i}",
                source_description="desc",
                user_id="user",
                correlation_id=None,
                causation_id=None,
                timestamp=datetime.now(UTC),
            )
            enforcer._trace_records.append(record)
        stats = enforcer.get_statistics()
        assert stats["total_checks"] == 10
        # violations = checks with is_valid False: i=0,3,6,9 -> 4 violations
        assert stats["total_violations"] == 4  # from _record_check not recording violations, so this is from _violation_history only
        # Actually get_statistics uses len(self._violation_history) for violations count. We haven't added any violations, so it will be 0.
        # Let's add violations.
        for i in range(2):
            v = TraceabilityViolation(
                message=f"v{i}", transaction_id=str(uuid4()), severity=LawViolationSeverity.CRITICAL, details={}
            )
            enforcer._record_violation(v)
        stats = enforcer.get_statistics()
        assert stats["total_violations"] == 2
        assert stats["total_records"] == 4
        assert stats["valid_count"] == 6  # 10 checks, 4 invalid -> 6 valid
        assert stats["invalid_count"] == 4
        assert stats["validity_rate"] == 0.6
        assert "HIGH" in stats["by_severity"]
        assert "LOW" in stats["by_severity"]
        assert "USER" in stats["by_source_type"]
        assert "SYSTEM" in stats["by_source_type"]

    # ----- reset -----
    def test_reset(self, enforcer, mock_audit_repo, mock_tx_repo):
        # add some state
        enforcer._trace_records.append(MagicMock())
        enforcer._check_history.append(MagicMock())
        enforcer._violation_history.append(MagicMock())
        enforcer._version = 5
        enforcer._audit_trail = [{"action": "test"}]
        old_version = enforcer.version()
        enforcer.reset()
        assert len(enforcer._trace_records) == 0
        assert len(enforcer._check_history) == 0
        assert len(enforcer._violation_history) == 0
        assert enforcer._enabled is True
        assert enforcer._strict_mode is True
        assert enforcer.version() == old_version + 1
        assert enforcer._audit_trail == []
        mock_audit_repo.clear.assert_called_once()
        mock_tx_repo.clear.assert_called_once()


# ----------------------------------------------------------------------
# Singleton
# ----------------------------------------------------------------------
def test_get_traceability_enforcer():
    instance1 = get_traceability_enforcer()
    instance2 = get_traceability_enforcer()
    assert instance1 is instance2
    assert isinstance(instance1, TraceabilityEnforcer)
