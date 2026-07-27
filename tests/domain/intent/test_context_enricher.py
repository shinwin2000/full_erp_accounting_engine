# test_context_enricher.py
# =========================
# Comprehensive tests for context_enricher.py.
# Covers EnrichedContext and ContextEnricher.

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domain.intent.context_enricher import (
    ContextEnricher,
    EnrichedContext,
    get_context_enricher,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def enriched_context() -> EnrichedContext:
    """Create a valid EnrichedContext."""
    return EnrichedContext(
        user_id="test_user",
        correlation_id="corr-123",
        timestamp=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        device_id="device-1",
        session_id="session-1",
        location="Jakarta",
        department="Finance",
        cost_center="CC001",
        legal_entity_id=uuid4(),
        additional_data={"key": "value"},
    )


@pytest.fixture
def context_enricher() -> ContextEnricher:
    """Reset singleton and return fresh ContextEnricher."""
    ContextEnricher._instance = None
    return ContextEnricher()


# ----------------------------------------------------------------------
# Tests for EnrichedContext
# ----------------------------------------------------------------------
class TestEnrichedContext:
    def test_construction_valid(self, enriched_context):
        assert enriched_context.user_id == "test_user"
        assert enriched_context.correlation_id == "corr-123"
        assert enriched_context.timestamp == datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        assert enriched_context.ip_address == "192.168.1.1"
        assert enriched_context.user_agent == "Mozilla/5.0"
        assert enriched_context.device_id == "device-1"
        assert enriched_context.session_id == "session-1"
        assert enriched_context.location == "Jakarta"
        assert enriched_context.department == "Finance"
        assert enriched_context.cost_center == "CC001"
        assert enriched_context.legal_entity_id is not None
        assert enriched_context.additional_data == {"key": "value"}
        assert enriched_context._version == 1
        assert len(enriched_context._snapshots) == 1
        assert len(enriched_context._audit_trail) == 1

    def test_construction_invalid_user_id_empty(self):
        with pytest.raises(ValueError, match="user_id must be a non-empty string"):
            EnrichedContext(
                user_id="",
                correlation_id="corr",
                timestamp=datetime.now(UTC),
            )

    def test_construction_invalid_correlation_id_empty(self):
        with pytest.raises(ValueError, match="correlation_id must be a non-empty string"):
            EnrichedContext(
                user_id="user",
                correlation_id="",
                timestamp=datetime.now(UTC),
            )

    def test_construction_invalid_timestamp_type(self):
        with pytest.raises(ValueError, match="timestamp must be datetime"):
            EnrichedContext(
                user_id="user",
                correlation_id="corr",
                timestamp="2025-01-01",  # type: ignore
            )

    def test_construction_user_agent_truncated(self):
        long_ua = "x" * 600
        ctx = EnrichedContext(
            user_id="user",
            correlation_id="corr",
            timestamp=datetime.now(UTC),
            user_agent=long_ua,
        )
        assert len(ctx.user_agent) == 500

    def test_construction_invalid_legal_entity_id_type(self):
        with pytest.raises(ValueError, match="legal_entity_id must be UUID or None"):
            EnrichedContext(
                user_id="user",
                correlation_id="corr",
                timestamp=datetime.now(UTC),
                legal_entity_id="not-uuid",  # type: ignore
            )

    def test_create(self, enriched_context):
        ctx = enriched_context.create("creator")
        trail = ctx.audit_trail(limit=1)
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "creator"
        assert ctx is enriched_context  # returns self

    def test_update(self, enriched_context):
        new_uuid = uuid4()
        updated = enriched_context.update(
            updated_by="updater",
            user_id="new_user",
            location="Bandung",
            legal_entity_id=new_uuid,
        )
        assert updated.user_id == "new_user"
        assert updated.location == "Bandung"
        assert updated.legal_entity_id == new_uuid
        assert updated._version == 2
        trail = updated.audit_trail(limit=1)
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["performed_by"] == "updater"
        assert "changes" in trail[0]["details"]

    def test_delete(self, enriched_context):
        ctx = enriched_context.delete("deleter", "cleanup")
        trail = ctx.audit_trail(limit=1)
        assert trail[0]["action"] == "DELETE"
        assert trail[0]["performed_by"] == "deleter"
        assert trail[0]["details"]["reason"] == "cleanup"
        # Returns self, no state change
        assert ctx is enriched_context

    def test_restore(self, enriched_context):
        ctx = enriched_context.restore("restorer")
        trail = ctx.audit_trail(limit=1)
        assert trail[0]["action"] == "RESTORE"
        assert trail[0]["performed_by"] == "restorer"
        assert ctx is enriched_context

    def test_activate(self, enriched_context):
        ctx = enriched_context.activate("activator")
        # No state change, just audit
        trail = ctx.audit_trail(limit=1)
        assert trail[0]["action"] == "ACTIVATE"  # Not implemented but no-op

    def test_deactivate(self, enriched_context):
        ctx = enriched_context.deactivate("deactivator", "reason")
        trail = ctx.audit_trail(limit=1)
        assert trail[0]["action"] == "DEACTIVATE"

    def test_lock(self, enriched_context):
        ctx = enriched_context.lock("locker", "audit")
        trail = ctx.audit_trail(limit=1)
        assert trail[0]["action"] == "LOCK"

    def test_unlock(self, enriched_context):
        ctx = enriched_context.unlock("unlocker")
        trail = ctx.audit_trail(limit=1)
        assert trail[0]["action"] == "UNLOCK"

    def test_validate_valid(self, enriched_context):
        result = enriched_context.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["user_id"] == "test_user"
        assert result["version"] == 1

    def test_validate_invalid(self):
        # Create invalid context to test validation errors
        ctx = EnrichedContext(
            user_id="user",
            correlation_id="corr",
            timestamp=datetime.now(UTC),
            user_agent="x" * 600,  # Will be truncated in __post_init__, so not invalid
        )
        # To trigger validation error, we can set invalid internal state.
        # But easier: create with invalid legal_entity_id? Already tested.
        # We'll test with empty user_id in construction, but that raises.
        # So we test that validate catches errors by corrupting internally.
        ctx.user_id = ""  # type: ignore
        result = ctx.validate()
        assert result["is_valid"] is False
        assert "user_id must be a non-empty string" in result["errors"]

    def test_to_dict(self, enriched_context):
        d = enriched_context.to_dict()
        assert d["user_id"] == "test_user"
        assert d["correlation_id"] == "corr-123"
        assert d["timestamp"] == "2025-01-01T12:00:00+00:00"
        assert d["ip_address"] == "192.168.1.1"
        assert d["user_agent"] == "Mozilla/5.0"
        assert d["device_id"] == "device-1"
        assert d["session_id"] == "session-1"
        assert d["location"] == "Jakarta"
        assert d["department"] == "Finance"
        assert d["cost_center"] == "CC001"
        assert d["legal_entity_id"] == str(enriched_context.legal_entity_id)
        assert d["additional"] == {"key": "value"}

    def test_from_dict(self):
        data = {
            "user_id": "alice",
            "correlation_id": "abc-123",
            "timestamp": "2025-02-01T10:00:00+00:00",
            "ip_address": "10.0.0.1",
            "user_agent": "Chrome",
            "device_id": "dev-2",
            "session_id": "sess-2",
            "location": "Surabaya",
            "department": "Sales",
            "cost_center": "CC002",
            "legal_entity_id": str(uuid4()),
            "additional": {"foo": "bar"},
        }
        ctx = EnrichedContext.from_dict(data)
        assert ctx.user_id == "alice"
        assert ctx.correlation_id == "abc-123"
        assert ctx.timestamp == datetime(2025, 2, 1, 10, 0, tzinfo=UTC)
        assert ctx.ip_address == "10.0.0.1"
        assert ctx.user_agent == "Chrome"
        assert ctx.device_id == "dev-2"
        assert ctx.session_id == "sess-2"
        assert ctx.location == "Surabaya"
        assert ctx.department == "Sales"
        assert ctx.cost_center == "CC002"
        assert ctx.legal_entity_id is not None
        assert ctx.additional_data == {"foo": "bar"}

    def test_from_dict_missing_fields(self):
        data = {
            "user_id": "bob",
            "correlation_id": "xyz",
            "timestamp": "2025-03-01T12:00:00+00:00",
        }
        ctx = EnrichedContext.from_dict(data)
        assert ctx.user_id == "bob"
        assert ctx.correlation_id == "xyz"
        assert ctx.ip_address is None
        assert ctx.additional_data == {}

    def test_clone(self, enriched_context):
        cloned = enriched_context.clone()
        assert cloned.user_id == enriched_context.user_id
        assert cloned.correlation_id != enriched_context.correlation_id  # new
        assert cloned.timestamp != enriched_context.timestamp  # new
        assert cloned.ip_address == enriched_context.ip_address
        assert cloned.user_agent == enriched_context.user_agent
        assert cloned.device_id == enriched_context.device_id
        assert cloned.session_id is None  # reset
        assert cloned.location == enriched_context.location
        assert cloned.department == enriched_context.department
        assert cloned.cost_center == enriched_context.cost_center
        assert cloned.legal_entity_id == enriched_context.legal_entity_id
        assert cloned.additional_data == enriched_context.additional_data
        # Should be separate dict
        cloned.additional_data["new"] = "new"
        assert "new" not in enriched_context.additional_data

    def test_snapshot(self, enriched_context):
        snap = enriched_context.snapshot()
        assert snap["version"] == 1
        assert snap["user_id"] == "test_user"
        assert snap["correlation_id"] == "corr-123"
        assert snap["timestamp"] == "2025-01-01T12:00:00+00:00"

    def test_version(self, enriched_context):
        assert enriched_context.version() == 1
        updated = enriched_context.update("updater", user_id="new")
        assert updated.version() == 2

    def test_audit_trail(self, enriched_context):
        trail = enriched_context.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "test_user"
        # Add more actions
        enriched_context.update("updater", location="new")
        enriched_context.touch("toucher")
        trail = enriched_context.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, enriched_context):
        new_ctx = enriched_context.touch("toucher")
        assert new_ctx._version == 2
        assert new_ctx.timestamp != enriched_context.timestamp  # updated to now
        trail = new_ctx.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "toucher"


# ----------------------------------------------------------------------
# Tests for ContextEnricher
# ----------------------------------------------------------------------
class TestContextEnricher:
    def test_singleton(self):
        e1 = get_context_enricher()
        e2 = get_context_enricher()
        assert e1 is e2

    def test_enrich_default(self, context_enricher):
        with patch("domain.intent.context_enricher._get_current_user", return_value="system"):
            with patch("domain.intent.context_enricher._get_correlation_id", return_value="corr-system"):
                ctx = context_enricher.enrich()
        assert ctx.user_id == "system"
        assert ctx.correlation_id == "corr-system"
        assert ctx.timestamp is not None
        assert ctx.ip_address is None
        assert ctx.user_agent is None
        assert ctx.additional_data == {}

    def test_enrich_with_values(self, context_enricher):
        le_id = uuid4()
        ctx = context_enricher.enrich(
            user_id="alice",
            correlation_id="my-corr",
            ip_address="192.168.1.2",
            user_agent="Firefox",
            device_id="phone",
            session_id="sess123",
            location="Tokyo",
            department="IT",
            cost_center="CC10",
            legal_entity_id=le_id,
            additional_data={"meta": "info"},
        )
        assert ctx.user_id == "alice"
        assert ctx.correlation_id == "my-corr"
        assert ctx.ip_address == "192.168.1.2"
        assert ctx.user_agent == "Firefox"
        assert ctx.device_id == "phone"
        assert ctx.session_id == "sess123"
        assert ctx.location == "Tokyo"
        assert ctx.department == "IT"
        assert ctx.cost_center == "CC10"
        assert ctx.legal_entity_id == le_id
        assert ctx.additional_data == {"meta": "info"}

    def test_enrich_user_agent_truncated(self, context_enricher):
        long_ua = "x" * 600
        ctx = context_enricher.enrich(user_agent=long_ua)
        assert len(ctx.user_agent) == 500

    def test_enrich_from_request(self, context_enricher):
        # Mock request object with client and headers
        mock_request = MagicMock()
        mock_request.client.host = "10.0.0.1"
        mock_request.headers = {
            "user-agent": "Chrome/100",
            "x-forwarded-for": "203.0.113.1",
            "x-correlation-id": "req-corr-456",
        }
        with patch("domain.intent.context_enricher._get_current_user", return_value="bob"):
            ctx = context_enricher.enrich_from_request(mock_request, additional_data={"extra": True})
        assert ctx.user_id == "bob"
        assert ctx.correlation_id == "req-corr-456"  # from header
        assert ctx.ip_address == "10.0.0.1"  # from client.host, x-forwarded-for ignored because client exists
        assert ctx.user_agent == "Chrome/100"
        assert ctx.additional_data == {"extra": True}

    def test_enrich_from_request_uses_forwarded_for(self, context_enricher):
        # Mock request without client, but with x-forwarded-for
        mock_request = MagicMock()
        mock_request.client = None
        mock_request.headers = {
            "user-agent": "Safari",
            "x-forwarded-for": "203.0.113.1, 10.0.0.2",
        }
        with patch("domain.intent.context_enricher._get_current_user", return_value="carol"):
            ctx = context_enricher.enrich_from_request(mock_request)
        assert ctx.ip_address == "203.0.113.1"  # first IP from forwarded
        assert ctx.user_agent == "Safari"
        assert ctx.correlation_id is not None  # auto-generated

    def test_enrich_from_request_uses_x_request_id(self, context_enricher):
        mock_request = MagicMock()
        mock_request.client = None
        mock_request.headers = {
            "x-request-id": "req-789",
        }
        with patch("domain.intent.context_enricher._get_current_user", return_value="dave"):
            ctx = context_enricher.enrich_from_request(mock_request)
        assert ctx.correlation_id == "req-789"

    def test_enrich_intent_data_without_context(self, context_enricher):
        with patch("domain.intent.context_enricher._get_current_user", return_value="eve"):
            with patch("domain.intent.context_enricher._get_correlation_id", return_value="corr-123"):
                enriched = context_enricher.enrich_intent_data({"amount": 100})
        assert enriched["amount"] == 100
        assert "_context" in enriched
        ctx_dict = enriched["_context"]
        assert ctx_dict["user_id"] == "eve"
        assert ctx_dict["correlation_id"] == "corr-123"
        assert ctx_dict["hostname"] == context_enricher.get_hostname()
        assert "timestamp" in ctx_dict

    def test_enrich_intent_data_with_provided_context(self, context_enricher):
        ctx = EnrichedContext(
            user_id="frank",
            correlation_id="manual",
            timestamp=datetime.now(UTC),
        )
        enriched = context_enricher.enrich_intent_data({"foo": "bar"}, context=ctx)
        assert enriched["foo"] == "bar"
        ctx_dict = enriched["_context"]
        assert ctx_dict["user_id"] == "frank"
        assert ctx_dict["correlation_id"] == "manual"
        assert ctx_dict["hostname"] == context_enricher.get_hostname()

    def test_add_audit_context(self, context_enricher):
        data = {"id": 123}
        enriched = context_enricher.add_audit_context(data, "CREATE", "invoice", "INV-001")
        assert enriched["id"] == 123
        audit = enriched["_audit"]
        assert audit["action"] == "CREATE"
        assert audit["resource_type"] == "invoice"
        assert audit["resource_id"] == "INV-001"
        assert "timestamp" in audit
        assert audit["hostname"] == context_enricher.get_hostname()

    def test_add_audit_context_without_resource_id(self, context_enricher):
        enriched = context_enricher.add_audit_context({}, "UPDATE", "customer")
        audit = enriched["_audit"]
        assert audit["resource_id"] is None

    def test_get_hostname(self, context_enricher):
        hostname = context_enricher.get_hostname()
        assert isinstance(hostname, str)
        assert hostname != ""

    def test_generate_correlation_id(self, context_enricher):
        cid1 = context_enricher.generate_correlation_id()
        cid2 = context_enricher.generate_correlation_id()
        assert cid1 != cid2
        assert isinstance(cid1, str)
        # Should be UUID format
        assert len(cid1) == 36

    def test_save(self, context_enricher):
        ctx = EnrichedContext(
            user_id="grace",
            correlation_id="corr",
            timestamp=datetime.now(UTC),
        )
        # Save just returns the context (no DB)
        saved = context_enricher.save(ctx)
        assert saved is ctx

    def test_get_latest_context(self, context_enricher):
        # Always returns None (mock DB)
        assert context_enricher.get_latest_context("any_user") is None

    def test_reset(self, context_enricher):
        # Reset hostname to current
        original = context_enricher._hostname
        context_enricher._hostname = "old-host"
        context_enricher.reset()
        assert context_enricher._hostname != "old-host"
        assert context_enricher._hostname == original  # resets to socket.gethostname()