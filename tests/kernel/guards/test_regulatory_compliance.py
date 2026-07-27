# tests/kernel/guards/test_regulatory_compliance.py
"""
Comprehensive tests for kernel/guards/regulatory_compliance.py.

Covers:
- Enums: RegulatoryDomain, ComplianceSeverity
- RegulatoryRule: construction, hash, to_dict
- ComplianceViolation: construction, hash, resolve, mark_report_sent, to_dict
- _FallbackRegulatoryConfig: get/set config
- RegulatoryComplianceGuard:
  - enable, validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch
  - check (sync)
  - register_rule, get_rule, get_all_rules, update_rule_status
  - enforce with all check types (FX, AML, structuring, tax, transfer pricing, reporting, corporate action)
  - resolve_violation, mark_violation_reported, get_violations
  - get_statistics, reset
- Singleton get_regulatory_compliance_guard
- Private methods: _create_violation, _record_violation, _record_transaction, _get_customer_transactions (tested indirectly)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from kernel.guards.regulatory_compliance import (
    BaseRegulatoryComplianceGuard,
    ComplianceSeverity,
    ComplianceViolation,
    RegulatoryComplianceGuard,
    RegulatoryDomain,
    RegulatoryRule,
    _FallbackRegulatoryConfig,
    get_regulatory_compliance_guard,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_config():
    """Mock regulatory config with predictable values."""
    config = MagicMock(spec=_FallbackRegulatoryConfig)
    config.get_config = AsyncMock(side_effect=lambda key, default=None: {
        "fx_limit_usd": 1000000,
        "fx_reporting_threshold_usd": 100000,
        "aml_threshold_idr": 100000000,
        "aml_lookback_days": 7,
        "aml_small_transaction_threshold": 90000000,
        "aml_max_small_transactions": 5,
        "transfer_pricing_tolerance_percent": 5,
        "tax_invoice_threshold": 1000000,
    }.get(key, default))
    config.set_config = AsyncMock()
    config.get_all_config = AsyncMock(return_value={"fx_limit_usd": 1000000})
    return config


@pytest.fixture
def guard(mock_config):
    """RegulatoryComplianceGuard instance with mocked config."""
    # Reset singleton for clean state
    RegulatoryComplianceGuard._instance = None
    return RegulatoryComplianceGuard(regulatory_config=mock_config)


@pytest.fixture
def sample_rule():
    return RegulatoryRule(
        rule_id="TEST_RULE",
        domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING,
        description="Test rule",
        severity=ComplianceSeverity.MEDIUM,
        is_active=True,
        parameters={"threshold": 1000},
        created_by="tester",
    )


@pytest.fixture
def sample_violation():
    return ComplianceViolation(
        violation_id=uuid4(),
        rule_id="TEST_RULE",
        domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING,
        severity=ComplianceSeverity.MEDIUM,
        transaction_id=uuid4(),
        legal_entity_id=uuid4(),
        user_id="user123",
        amount=Decimal("1000"),
        currency="IDR",
        message="Test violation",
        details={"reason": "test"},
        detected_at=datetime.now(UTC),
        is_resolved=False,
        report_sent_to_regulator=False,
    )


# ============================================================================
# Tests for _FallbackRegulatoryConfig
# ============================================================================

class TestFallbackRegulatoryConfig:
    def test_construction(self):
        config = _FallbackRegulatoryConfig()
        assert config._config is not None

    @pytest.mark.asyncio
    async def test_get_config_default(self):
        config = _FallbackRegulatoryConfig()
        result = await config.get_config("nonexistent", "default")
        assert result == "default"

    @pytest.mark.asyncio
    async def test_get_config_existing(self):
        config = _FallbackRegulatoryConfig()
        result = await config.get_config("fx_limit_usd")
        assert result == 1000000

    @pytest.mark.asyncio
    async def test_set_config(self):
        config = _FallbackRegulatoryConfig()
        await config.set_config("new_key", 123)
        assert await config.get_config("new_key") == 123

    @pytest.mark.asyncio
    async def test_get_all_config(self):
        config = _FallbackRegulatoryConfig()
        all_config = await config.get_all_config()
        assert "fx_limit_usd" in all_config


# ============================================================================
# Tests for Enums
# ============================================================================

class TestRegulatoryDomain:
    def test_members(self):
        assert RegulatoryDomain.FOREIGN_EXCHANGE.value == "foreign_exchange"
        assert RegulatoryDomain.ANTI_MONEY_LAUNDERING.value == "aml"
        assert RegulatoryDomain.TAX_COMPLIANCE.value == "tax"
        assert RegulatoryDomain.CORPORATE_GOVERNANCE.value == "governance"
        assert RegulatoryDomain.CAPITAL_MARKET.value == "capital_market"
        assert RegulatoryDomain.DATA_PRIVACY.value == "privacy"
        assert RegulatoryDomain.TRANSFER_PRICING.value == "transfer_pricing"
        assert RegulatoryDomain.ENVIRONMENTAL.value == "environmental"
        assert RegulatoryDomain.LABOR.value == "labor"


class TestComplianceSeverity:
    def test_members(self):
        assert ComplianceSeverity.CRITICAL.value == 80
        assert ComplianceSeverity.HIGH.value == 60
        assert ComplianceSeverity.MEDIUM.value == 40
        assert ComplianceSeverity.LOW.value == 20
        assert ComplianceSeverity.INFO.value == 0


# ============================================================================
# Tests for RegulatoryRule
# ============================================================================

class TestRegulatoryRule:
    def test_construction(self):
        rule = RegulatoryRule(
            rule_id="RULE_001",
            domain=RegulatoryDomain.TAX_COMPLIANCE,
            description="Test",
            severity=ComplianceSeverity.HIGH,
        )
        assert rule.rule_id == "RULE_001"
        assert rule.is_active is True
        assert rule.cryptographic_hash != ""

    def test_compute_hash(self):
        rule = RegulatoryRule(
            rule_id="HASH_TEST",
            domain=RegulatoryDomain.FOREIGN_EXCHANGE,
            description="Hash test",
            severity=ComplianceSeverity.LOW,
        )
        h1 = rule.compute_hash()
        h2 = rule.compute_hash()
        assert h1 == h2

        # Change description should change hash
        rule2 = RegulatoryRule(
            rule_id="HASH_TEST",
            domain=RegulatoryDomain.FOREIGN_EXCHANGE,
            description="Different",
            severity=ComplianceSeverity.LOW,
        )
        assert rule2.compute_hash() != h1

    def test_hash_mismatch_raises(self):
        # Creating with incorrect hash should raise ValueError
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            RegulatoryRule(
                rule_id="RULE_001",
                domain=RegulatoryDomain.TAX_COMPLIANCE,
                description="Test",
                severity=ComplianceSeverity.HIGH,
                cryptographic_hash="wronghash",
            )

    def test_to_dict(self):
        rule = RegulatoryRule(
            rule_id="RULE_002",
            domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING,
            description="AML rule",
            severity=ComplianceSeverity.CRITICAL,
            parameters={"threshold": 100000000},
        )
        d = rule.to_dict()
        assert d["rule_id"] == "RULE_002"
        assert d["domain"] == "aml"
        assert d["severity"] == "CRITICAL"
        assert d["parameters"]["threshold"] == 100000000


# ============================================================================
# Tests for ComplianceViolation
# ============================================================================

class TestComplianceViolation:
    def test_construction(self):
        violation = ComplianceViolation(
            violation_id=uuid4(),
            rule_id="VIOL_001",
            domain=RegulatoryDomain.FOREIGN_EXCHANGE,
            severity=ComplianceSeverity.HIGH,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="user",
            amount=Decimal("1000"),
            currency="USD",
            message="Test",
            details={"key": "value"},
            detected_at=datetime.now(UTC),
        )
        assert violation.rule_id == "VIOL_001"
        assert violation.is_resolved is False
        assert violation.cryptographic_hash != ""

    def test_compute_hash(self):
        now = datetime.now(UTC)
        v1 = ComplianceViolation(
            violation_id=uuid4(),
            rule_id="HASH",
            domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING,
            severity=ComplianceSeverity.CRITICAL,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="user",
            amount=Decimal("100"),
            currency="IDR",
            message="Msg",
            details={},
            detected_at=now,
        )
        h1 = v1.compute_hash()
        h2 = v1.compute_hash()
        assert h1 == h2

        # Change message
        v2 = ComplianceViolation(
            violation_id=v1.violation_id,
            rule_id="HASH",
            domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING,
            severity=ComplianceSeverity.CRITICAL,
            transaction_id=v1.transaction_id,
            legal_entity_id=v1.legal_entity_id,
            user_id="user",
            amount=Decimal("100"),
            currency="IDR",
            message="Different",
            details={},
            detected_at=now,
        )
        assert v2.compute_hash() != h1

    def test_hash_mismatch_raises(self):
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            ComplianceViolation(
                violation_id=uuid4(),
                rule_id="TEST",
                domain=RegulatoryDomain.FOREIGN_EXCHANGE,
                severity=ComplianceSeverity.LOW,
                transaction_id=uuid4(),
                legal_entity_id=uuid4(),
                user_id="user",
                amount=Decimal(0),
                currency="IDR",
                message="Test",
                details={},
                detected_at=datetime.now(UTC),
                cryptographic_hash="wrong",
            )

    def test_resolve(self):
        now = datetime.now(UTC)
        violation = ComplianceViolation(
            violation_id=uuid4(),
            rule_id="RESOLVE",
            domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING,
            severity=ComplianceSeverity.MEDIUM,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="user",
            amount=Decimal("100"),
            currency="IDR",
            message="Test",
            details={},
            detected_at=now,
        )
        resolved = violation.resolve("admin", "Fixed")
        assert resolved is not violation
        assert resolved.is_resolved is True
        assert resolved.resolved_by == "admin"
        assert resolved.resolution_action == "Fixed"
        assert resolved.resolved_at is not None

    def test_mark_report_sent(self):
        now = datetime.now(UTC)
        violation = ComplianceViolation(
            violation_id=uuid4(),
            rule_id="REPORT",
            domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING,
            severity=ComplianceSeverity.CRITICAL,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="user",
            amount=Decimal("100"),
            currency="IDR",
            message="Test",
            details={},
            detected_at=now,
        )
        reported = violation.mark_report_sent("reporter")
        assert reported.report_sent_to_regulator is True
        assert reported.report_sent_at is not None

    def test_to_dict(self):
        now = datetime.now(UTC)
        violation = ComplianceViolation(
            violation_id=uuid4(),
            rule_id="DICT",
            domain=RegulatoryDomain.FOREIGN_EXCHANGE,
            severity=ComplianceSeverity.HIGH,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="user",
            amount=Decimal("5000"),
            currency="USD",
            message="Violation",
            details={"reason": "too high"},
            detected_at=now,
        )
        d = violation.to_dict()
        assert d["rule_id"] == "DICT"
        assert d["domain"] == "foreign_exchange"
        assert d["severity"] == "HIGH"
        assert d["amount"] == "5000"
        assert "detected_at" in d


# ============================================================================
# Tests for RegulatoryComplianceGuard
# ============================================================================

class TestRegulatoryComplianceGuard:
    def test_init(self, guard):
        assert guard._enabled is True
        assert len(guard._rules) > 0
        assert guard._violations == []
        assert guard._transaction_history == {}

    def test_enable(self, guard):
        guard.enable(False)
        assert guard._enabled is False
        guard.enable(True)
        assert guard._enabled is True

    def test_validate(self, guard):
        result = guard.validate()
        assert result["is_valid"] is True

        # Break validation by setting max_history to 0
        guard._max_history = 0
        result2 = guard.validate()
        assert result2["is_valid"] is False
        assert any("max_history" in e for e in result2["errors"])

    def test_to_dict(self, guard):
        d = guard.to_dict()
        assert "enabled" in d
        assert "rules_count" in d
        assert "active_rules" in d
        assert "version" in d

    def test_from_dict(self):
        data = {"enabled": False, "max_history": 5000, "version": 3}
        guard = RegulatoryComplianceGuard.from_dict(data)
        assert guard._enabled is False
        assert guard._max_history == 5000
        assert guard._version == 3

    def test_clone(self, guard):
        clone = guard.clone()
        assert clone is not guard
        assert clone._enabled == guard._enabled
        assert clone._max_history == guard._max_history
        assert clone._version == guard._version + 1

    def test_snapshot(self, guard):
        snap = guard.snapshot()
        assert "version" in snap
        assert "violations_count" in snap
        assert "enabled" in snap
        assert "timestamp" in snap

    def test_version(self, guard):
        assert guard.version() == 1
        guard.touch("tester")
        assert guard.version() == 2

    def test_audit_trail(self, guard):
        guard.touch("user1")
        guard.touch("user2")
        trail = guard.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "user1"
        assert trail[1]["action"] == "TOUCH"
        assert trail[1]["performed_by"] == "user2"

    def test_touch(self, guard):
        old_version = guard.version()
        guard.touch("tester")
        assert guard.version() == old_version + 1
        trail = guard.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)

    # ---- check method ----

    def test_check_valid_context(self, guard):
        context = {"checks": [("foreign_exchange_limit", {"amount": 1000})]}
        errors = guard.check(context)
        assert errors == []

    def test_check_missing_checks(self, guard):
        errors = guard.check({})
        assert "checks list is required" in errors

    def test_check_invalid_checks_type(self, guard):
        errors = guard.check({"checks": "not a list"})
        assert "checks must be a list of tuples" in errors

    def test_check_invalid_check_tuple(self, guard):
        context = {"checks": [("only_one")]}
        errors = guard.check(context)
        assert "must be a tuple of (check_name, params)" in errors

    def test_check_empty_check_name(self, guard):
        context = {"checks": [("", {})]}
        errors = guard.check(context)
        assert "check_name is empty" in errors

    def test_check_invalid_params_type(self, guard):
        context = {"checks": [("fx", "not a dict")]}
        errors = guard.check(context)
        assert "params must be a dict" in errors

    # ---- Rule management ----

    def test_register_rule(self, guard, sample_rule):
        guard.register_rule(sample_rule)
        assert guard.get_rule("TEST_RULE") == sample_rule
        # Registering again with same ID should overwrite
        new_rule = RegulatoryRule(
            rule_id="TEST_RULE",
            domain=RegulatoryDomain.FOREIGN_EXCHANGE,
            description="New",
            severity=ComplianceSeverity.LOW,
        )
        guard.register_rule(new_rule)
        assert guard.get_rule("TEST_RULE").description == "New"

    def test_get_rule_not_found(self, guard):
        assert guard.get_rule("NONEXISTENT") is None

    def test_get_all_rules(self, guard):
        all_rules = guard.get_all_rules(active_only=False)
        assert len(all_rules) >= len(guard._rules)
        active_only = guard.get_all_rules(active_only=True)
        assert len(active_only) == len([r for r in guard._rules.values() if r.is_active])

    def test_update_rule_status(self, guard, sample_rule):
        guard.register_rule(sample_rule)
        result = guard.update_rule_status("TEST_RULE", False, "admin")
        assert result is True
        rule = guard.get_rule("TEST_RULE")
        assert rule.is_active is False

        # Update non-existent
        result2 = guard.update_rule_status("NONEXISTENT", True, "admin")
        assert result2 is False

    # ---- enforce and individual checks ----

    @pytest.mark.asyncio
    async def test_enforce_disabled(self, guard):
        guard.enable(False)
        is_ok, violations = await guard.enforce([("foreign_exchange_limit", {"amount": 1000})])
        assert is_ok is True
        assert violations == []

    @pytest.mark.asyncio
    async def test_enforce_foreign_exchange_limit_pass(self, guard):
        is_ok, violations = await guard.enforce([
            ("foreign_exchange_limit", {"amount": Decimal("50000"), "currency": "USD"})
        ])
        assert is_ok is True
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_enforce_foreign_exchange_limit_fail(self, guard):
        is_ok, violations = await guard.enforce([
            ("foreign_exchange_limit", {"amount": Decimal("2000000"), "currency": "USD"})
        ])
        assert is_ok is False
        assert len(violations) == 1
        assert violations[0].rule_id == "FX_LIMIT_IDR"

    @pytest.mark.asyncio
    async def test_enforce_aml_threshold_pass(self, guard):
        is_ok, violations = await guard.enforce([
            ("aml_threshold", {"amount": Decimal("50000000")})
        ])
        assert is_ok is True
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_enforce_aml_threshold_fail(self, guard):
        is_ok, violations = await guard.enforce([
            ("aml_threshold", {"amount": Decimal("150000000")})
        ])
        assert is_ok is False
        assert len(violations) == 1
        assert violations[0].rule_id == "AML_THRESHOLD"

    @pytest.mark.asyncio
    async def test_enforce_aml_structuring(self, guard):
        customer_id = uuid4()
        # Add some recent transactions
        guard._record_transaction(customer_id, {
            "amount": Decimal("95000000"),
            "timestamp": datetime.now(UTC) - timedelta(days=1),
        })
        guard._record_transaction(customer_id, {
            "amount": Decimal("95000000"),
            "timestamp": datetime.now(UTC) - timedelta(days=2),
        })
        guard._record_transaction(customer_id, {
            "amount": Decimal("95000000"),
            "timestamp": datetime.now(UTC) - timedelta(days=3),
        })
        guard._record_transaction(customer_id, {
            "amount": Decimal("95000000"),
            "timestamp": datetime.now(UTC) - timedelta(days=4),
        })
        guard._record_transaction(customer_id, {
            "amount": Decimal("95000000"),
            "timestamp": datetime.now(UTC) - timedelta(days=5),
        })  # 5 transactions, should trigger structuring

        is_ok, violations = await guard.enforce([
            ("aml_structuring", {
                "amount": Decimal("50000"),
                "customer_id": customer_id,
                "transaction_date": datetime.now(UTC),
            })
        ])
        assert is_ok is False
        assert len(violations) == 1
        assert violations[0].rule_id == "AML_STRUCTURING"

    @pytest.mark.asyncio
    async def test_enforce_tax_withholding(self, guard):
        # This check currently only logs, does not create violations unless we add logic.
        # We'll call it and verify no violation (it returns True, None)
        is_ok, violations = await guard.enforce([
            ("tax_withholding", {
                "transaction_type": "SERVICE_PAYMENT",
                "amount": Decimal("1000000"),
                "supplier_type": "PKP",
                "is_intercompany": False,
            })
        ])
        assert is_ok is True
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_enforce_transfer_pricing_pass(self, guard):
        is_ok, violations = await guard.enforce([
            ("transfer_pricing", {
                "amount": Decimal("10000"),
                "fair_market_value": Decimal("10000"),
                "related_party_id": uuid4(),
            })
        ])
        assert is_ok is True
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_enforce_transfer_pricing_fail(self, guard):
        is_ok, violations = await guard.enforce([
            ("transfer_pricing", {
                "amount": Decimal("12000"),
                "fair_market_value": Decimal("10000"),
                "related_party_id": uuid4(),
            })
        ])
        assert is_ok is False
        assert len(violations) == 1
        assert violations[0].rule_id == "TRANSFER_PRICING_ARM_LENGTH"

    @pytest.mark.asyncio
    async def test_enforce_fx_reporting(self, guard):
        is_ok, violations = await guard.enforce([
            ("fx_reporting", {
                "amount": Decimal("200000"),
                "currency": "USD",
            })
        ])
        assert is_ok is False
        assert len(violations) == 1
        assert violations[0].rule_id == "FX_REPORTING"

    @pytest.mark.asyncio
    async def test_enforce_corporate_action(self, guard):
        # Without approval -> violation
        is_ok, violations = await guard.enforce([
            ("corporate_action", {
                "action_type": "DIVIDEND",
                "amount": Decimal("1000000"),
                "has_board_approval": False,
            })
        ])
        assert is_ok is False
        assert len(violations) == 1
        assert violations[0].rule_id == "CORPORATE_ACTION_APPROVAL"

        # With approval -> pass
        is_ok2, violations2 = await guard.enforce([
            ("corporate_action", {
                "action_type": "DIVIDEND",
                "amount": Decimal("1000000"),
                "has_board_approval": True,
            })
        ])
        assert is_ok2 is True
        assert len(violations2) == 0

    @pytest.mark.asyncio
    async def test_enforce_raises_on_critical(self, guard):
        with pytest.raises(RegulatoryComplianceError) as exc:
            await guard.enforce([
                ("aml_threshold", {"amount": Decimal("150000000")})
            ], raise_on_violation=True)
        assert "Regulatory compliance violation" in str(exc.value)
        assert exc.value.domain == "aml"
        assert exc.value.rule_id == "AML_THRESHOLD"

    # ---- Violation management ----

    def test_record_violation_and_get_violations(self, guard, sample_violation):
        # Use private method to record a violation
        guard._record_violation(sample_violation)
        violations = guard.get_violations(limit=10)
        assert len(violations) == 1
        assert violations[0].violation_id == sample_violation.violation_id

    def test_get_violations_with_filters(self, guard):
        v1 = ComplianceViolation(
            violation_id=uuid4(),
            rule_id="R1",
            domain=RegulatoryDomain.FOREIGN_EXCHANGE,
            severity=ComplianceSeverity.HIGH,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="user1",
            amount=Decimal("100"),
            currency="USD",
            message="V1",
            details={},
            detected_at=datetime.now(UTC) - timedelta(days=1),
            is_resolved=False,
        )
        v2 = ComplianceViolation(
            violation_id=uuid4(),
            rule_id="R2",
            domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING,
            severity=ComplianceSeverity.CRITICAL,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="user2",
            amount=Decimal("200"),
            currency="IDR",
            message="V2",
            details={},
            detected_at=datetime.now(UTC),
            is_resolved=False,
        )
        guard._record_violation(v1)
        guard._record_violation(v2)

        all_v = guard.get_violations()
        assert len(all_v) == 2

        by_domain = guard.get_violations(domain=RegulatoryDomain.FOREIGN_EXCHANGE)
        assert len(by_domain) == 1
        assert by_domain[0].rule_id == "R1"

        by_severity = guard.get_violations(domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING)
        assert len(by_severity) == 1

        # Resolve one
        guard.resolve_violation(v1.violation_id, "admin", "fixed")
        unresolved = guard.get_violations(unresolved_only=True)
        assert len(unresolved) == 1
        assert unresolved[0].rule_id == "R2"

        # Date filters
        start = datetime.now(UTC) - timedelta(hours=1)
        recent = guard.get_violations(start_date=start)
        assert len(recent) == 1
        assert recent[0].rule_id == "R2"

    def test_resolve_violation(self, guard, sample_violation):
        guard._record_violation(sample_violation)
        resolved = guard.resolve_violation(sample_violation.violation_id, "admin", "fixed")
        assert resolved is not None
        assert resolved.is_resolved is True
        assert resolved.resolved_by == "admin"
        assert resolved.resolution_action == "fixed"

        # Resolve again should return None
        resolved2 = guard.resolve_violation(sample_violation.violation_id, "admin", "again")
        assert resolved2 is None

    def test_mark_violation_reported(self, guard, sample_violation):
        guard._record_violation(sample_violation)
        reported = guard.mark_violation_reported(sample_violation.violation_id, "reporter")
        assert reported is not None
        assert reported.report_sent_to_regulator is True
        assert reported.report_sent_at is not None

        # Already reported
        reported2 = guard.mark_violation_reported(sample_violation.violation_id, "reporter")
        assert reported2 is None

    # ---- Statistics ----

    def test_get_statistics(self, guard):
        stats = guard.get_statistics()
        assert stats["total_violations"] == 0
        assert stats["enabled"] is True

        # Add some violations
        v1 = ComplianceViolation(
            violation_id=uuid4(),
            rule_id="R1",
            domain=RegulatoryDomain.FOREIGN_EXCHANGE,
            severity=ComplianceSeverity.HIGH,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="user",
            amount=Decimal("100"),
            currency="USD",
            message="V1",
            details={},
            detected_at=datetime.now(UTC),
        )
        v2 = ComplianceViolation(
            violation_id=uuid4(),
            rule_id="R2",
            domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING,
            severity=ComplianceSeverity.CRITICAL,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="user",
            amount=Decimal("200"),
            currency="IDR",
            message="V2",
            details={},
            detected_at=datetime.now(UTC),
        )
        guard._record_violation(v1)
        guard._record_violation(v2)
        guard.resolve_violation(v1.violation_id, "admin", "fixed")
        guard.mark_violation_reported(v2.violation_id, "reporter")

        stats2 = guard.get_statistics()
        assert stats2["total_violations"] == 2
        assert stats2["unresolved_violations"] == 1
        assert stats2["reported_to_regulator"] == 1
        assert stats2["by_domain"]["foreign_exchange"] == 1
        assert stats2["by_domain"]["aml"] == 1
        assert stats2["by_severity"]["HIGH"] == 1
        assert stats2["by_severity"]["CRITICAL"] == 1

    # ---- Reset ----

    def test_reset(self, guard):
        guard._violations = [MagicMock()]
        guard._transaction_history = {uuid4(): []}
        old_version = guard.version()
        guard.reset()
        assert guard._violations == []
        assert guard._transaction_history == {}
        assert guard._enabled is True
        assert guard.version() == old_version + 1

    # ---- Private methods (tested indirectly) ----

    def test_create_violation(self, guard):
        rule = guard._rules.get("FX_LIMIT_IDR")
        violation = guard._create_violation(
            rule_id=rule.rule_id,
            domain=rule.domain,
            severity=rule.severity,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="user",
            amount=Decimal("1000"),
            currency="USD",
            message="Test",
            details={"detail": "value"},
        )
        assert isinstance(violation, ComplianceViolation)
        assert violation.rule_id == rule.rule_id
        assert violation.cryptographic_hash != ""

    def test_record_transaction_and_get_customer_transactions(self, guard):
        customer_id = uuid4()
        now = datetime.now(UTC)
        guard._record_transaction(customer_id, {"amount": 100, "timestamp": now})
        guard._record_transaction(customer_id, {"amount": 200, "timestamp": now - timedelta(days=1)})

        result = guard._get_customer_transactions(
            customer_id, now - timedelta(days=2), now + timedelta(days=1)
        )
        assert len(result) == 2

        result2 = guard._get_customer_transactions(
            customer_id, now, now + timedelta(days=1)
        )
        assert len(result2) == 1
        assert result2[0]["amount"] == 100


# ============================================================================
# Tests for Singleton
# ============================================================================

def test_get_regulatory_compliance_guard():
    # Reset singleton
    RegulatoryComplianceGuard._instance = None
    g1 = get_regulatory_compliance_guard()
    g2 = get_regulatory_compliance_guard()
    assert g1 is g2
    assert isinstance(g1, RegulatoryComplianceGuard)