# test_reality_exceptions.py
# Comprehensive tests for reality_exceptions.py

import pytest

from domain.reality.reality_exceptions import (
    AccountNotFoundError,
    AssetDuplicateError,
    AssetNotFoundError,
    AssetNotVerifiedError,
    AssetVerificationFailedError,
    CollectionExceedsBalanceError,
    EconomicEventInvalidStatusError,
    EconomicEventNotFoundError,
    EventAlreadyMappedError,
    MappingNotFoundError,
    PaymentExceedsBalanceError,
    RealityError,
    RealityErrorCode,
    RealityExceptionFactory,
    RealitySeverity,
    ValidationFailedError,
)


# ============================================================================
# Tests for Enums
# ============================================================================

class TestRealityErrorCode:
    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(RealityErrorCode, "EVENT_NOT_FOUND")
        assert hasattr(RealityErrorCode, "EVENT_INVALID_STATUS")
        assert hasattr(RealityErrorCode, "EVENT_ALREADY_MAPPED")
        assert hasattr(RealityErrorCode, "EVENT_ALREADY_POSTED")
        assert hasattr(RealityErrorCode, "EVENT_CANNOT_REVERSE")
        assert hasattr(RealityErrorCode, "VALIDATION_FAILED")
        assert hasattr(RealityErrorCode, "AMOUNT_INVALID")
        assert hasattr(RealityErrorCode, "DATE_INVALID")
        assert hasattr(RealityErrorCode, "CURRENCY_MISMATCH")
        assert hasattr(RealityErrorCode, "MISSING_REQUIRED_FIELD")
        assert hasattr(RealityErrorCode, "MAPPING_NOT_FOUND")
        assert hasattr(RealityErrorCode, "MAPPING_INCOMPLETE")
        assert hasattr(RealityErrorCode, "ACCOUNT_NOT_FOUND")
        assert hasattr(RealityErrorCode, "JOURNAL_CREATION_FAILED")
        assert hasattr(RealityErrorCode, "ASSET_NOT_FOUND")
        assert hasattr(RealityErrorCode, "ASSET_VERIFICATION_FAILED")
        assert hasattr(RealityErrorCode, "ASSET_DUPLICATE")
        assert hasattr(RealityErrorCode, "ASSET_NOT_VERIFIED")
        assert hasattr(RealityErrorCode, "OBLIGATION_NOT_FOUND")
        assert hasattr(RealityErrorCode, "ENTITLEMENT_NOT_FOUND")
        assert hasattr(RealityErrorCode, "PAYMENT_EXCEEDS_BALANCE")
        assert hasattr(RealityErrorCode, "COLLECTION_EXCEEDS_BALANCE")

    def test_enum_values_are_auto(self):
        """All enum values should be auto() generated."""
        assert isinstance(RealityErrorCode.EVENT_NOT_FOUND.value, int)


class TestRealitySeverity:
    def test_members_exist(self):
        assert hasattr(RealitySeverity, "CRITICAL")
        assert hasattr(RealitySeverity, "HIGH")
        assert hasattr(RealitySeverity, "MEDIUM")
        assert hasattr(RealitySeverity, "LOW")

    def test_severity_values(self):
        assert RealitySeverity.CRITICAL.value == 80
        assert RealitySeverity.HIGH.value == 60
        assert RealitySeverity.MEDIUM.value == 40
        assert RealitySeverity.LOW.value == 20


# ============================================================================
# Tests for Base RealityError
# ============================================================================

class TestRealityError:
    def test_construction(self):
        error = RealityError(
            message="Test error",
            error_code=RealityErrorCode.VALIDATION_FAILED,
            severity=RealitySeverity.CRITICAL,
            component="test_component",
            details={"key": "value"},
            cause=ValueError("Original error"),
        )
        assert error.error_code == RealityErrorCode.VALIDATION_FAILED
        assert error.severity == RealitySeverity.CRITICAL
        assert error.component == "test_component"
        assert error.details == {"key": "value"}
        assert error.cause is not None
        assert error.original_message == "Test error"
        # Full message includes severity, error_code, message, component
        assert "[CRITICAL][VALIDATION_FAILED] Test error" in str(error)

    def test_construction_defaults(self):
        error = RealityError(
            message="Test error",
            error_code=RealityErrorCode.EVENT_NOT_FOUND,
        )
        assert error.severity == RealitySeverity.MEDIUM  # default
        assert error.component is None
        assert error.details == {}
        assert error.cause is None

    def test_original_message_property(self):
        error = RealityError(
            message="Original message",
            error_code=RealityErrorCode.EVENT_NOT_FOUND,
        )
        assert error.original_message == "Original message"

    def test_to_dict(self):
        error = RealityError(
            message="Test",
            error_code=RealityErrorCode.ACCOUNT_NOT_FOUND,
            severity=RealitySeverity.CRITICAL,
            component="mapper",
            details={"account": "123"},
            cause=KeyError("missing"),
        )
        d = error.to_dict()
        assert d["type"] == "RealityError"
        assert d["error_code"] == "ACCOUNT_NOT_FOUND"
        assert d["severity"] == "CRITICAL"
        assert d["message"] == "Test"
        assert d["component"] == "mapper"
        assert d["details"] == {"account": "123"}
        assert "missing" in d["cause"]

    def test_is_critical(self):
        critical = RealityError(
            message="Critical", error_code=RealityErrorCode.EVENT_NOT_FOUND,
            severity=RealitySeverity.CRITICAL
        )
        assert critical.is_critical() is True
        medium = RealityError(
            message="Medium", error_code=RealityErrorCode.EVENT_NOT_FOUND,
            severity=RealitySeverity.MEDIUM
        )
        assert medium.is_critical() is False


# ============================================================================
# Tests for Concrete Exceptions
# ============================================================================

class TestEconomicEventNotFoundError:
    def test_construction(self):
        error = EconomicEventNotFoundError(event_id="evt-123")
        assert isinstance(error, RealityError)
        assert error.error_code == RealityErrorCode.EVENT_NOT_FOUND
        assert error.severity == RealitySeverity.HIGH
        assert error.component == "economic_event"
        assert error.event_id == "evt-123"
        assert "evt-123" in str(error)
        assert error.details == {"event_id": "evt-123"}


class TestEconomicEventInvalidStatusError:
    def test_construction(self):
        error = EconomicEventInvalidStatusError(
            event_id="evt-123",
            current_status="draft",
            required_status="verified",
        )
        assert error.error_code == RealityErrorCode.EVENT_INVALID_STATUS
        assert error.severity == RealitySeverity.HIGH
        assert error.event_id == "evt-123"
        assert error.details["current_status"] == "draft"
        assert error.details["required_status"] == "verified"
        assert "draft" in str(error)


class TestEventAlreadyMappedError:
    def test_construction(self):
        error = EventAlreadyMappedError(event_id="evt-123", journal_id="jrn-456")
        assert error.error_code == RealityErrorCode.EVENT_ALREADY_MAPPED
        assert error.severity == RealitySeverity.MEDIUM
        assert error.event_id == "evt-123"
        assert error.details["journal_id"] == "jrn-456"


class TestValidationFailedError:
    def test_construction(self):
        class Issue:
            field = "amount"
            message = "must be positive"
        issues = [Issue()]
        error = ValidationFailedError(message="Validation failed", issues=issues)
        assert error.error_code == RealityErrorCode.VALIDATION_FAILED
        assert error.severity == RealitySeverity.HIGH
        assert error.issues == issues
        assert error.details["issues"][0]["field"] == "amount"
        assert error.details["issues"][0]["message"] == "must be positive"

    def test_construction_with_issue_objects_no_field(self):
        class SimpleIssue:
            def __str__(self):
                return "issue message"
        issues = [SimpleIssue()]
        error = ValidationFailedError(message="Failed", issues=issues)
        assert error.details["issues"][0]["field"] == "unknown"
        assert error.details["issues"][0]["message"] == "issue message"


class TestMappingNotFoundError:
    def test_construction(self):
        error = MappingNotFoundError(event_type="purchase_invoice")
        assert error.error_code == RealityErrorCode.MAPPING_NOT_FOUND
        assert error.severity == RealitySeverity.CRITICAL
        assert error.component == "mapper"
        assert error.event_type == "purchase_invoice"
        assert "purchase_invoice" in str(error)


class TestAccountNotFoundError:
    def test_construction(self):
        error = AccountNotFoundError(account_code="12345")
        assert error.error_code == RealityErrorCode.ACCOUNT_NOT_FOUND
        assert error.severity == RealitySeverity.CRITICAL
        assert error.component == "mapper"
        assert error.account_code == "12345"
        assert "12345" in str(error)


class TestAssetNotFoundError:
    def test_construction(self):
        error = AssetNotFoundError(asset_id="ast-001")
        assert error.error_code == RealityErrorCode.ASSET_NOT_FOUND
        assert error.severity == RealitySeverity.HIGH
        assert error.component == "asset_validator"
        assert error.asset_id == "ast-001"
        assert "ast-001" in str(error)


class TestAssetVerificationFailedError:
    def test_construction(self):
        error = AssetVerificationFailedError(asset_id="ast-001", reason="Missing documents")
        assert error.error_code == RealityErrorCode.ASSET_VERIFICATION_FAILED
        assert error.severity == RealitySeverity.HIGH
        assert error.asset_id == "ast-001"
        assert error.details["reason"] == "Missing documents"
        assert "Missing documents" in str(error)


class TestAssetDuplicateError:
    def test_construction(self):
        error = AssetDuplicateError(asset_id="ast-001", existing_asset_id="ast-000")
        assert error.error_code == RealityErrorCode.ASSET_DUPLICATE
        assert error.severity == RealitySeverity.HIGH
        assert error.asset_id == "ast-001"
        assert error.details["existing_asset_id"] == "ast-000"


class TestAssetNotVerifiedError:
    def test_construction(self):
        error = AssetNotVerifiedError(asset_id="ast-001")
        assert error.error_code == RealityErrorCode.ASSET_NOT_VERIFIED
        assert error.severity == RealitySeverity.CRITICAL
        assert error.component == "asset_validator"
        assert error.asset_id == "ast-001"
        assert "not been verified" in str(error)


class TestPaymentExceedsBalanceError:
    def test_construction(self):
        error = PaymentExceedsBalanceError(
            obligation_id="obl-123",
            payment_amount="1000",
            outstanding_amount="500",
        )
        assert error.error_code == RealityErrorCode.PAYMENT_EXCEEDS_BALANCE
        assert error.severity == RealitySeverity.HIGH
        assert error.component == "obligation"
        assert error.obligation_id == "obl-123"
        assert error.details["payment_amount"] == "1000"
        assert error.details["outstanding_amount"] == "500"
        assert "exceeds" in str(error)


class TestCollectionExceedsBalanceError:
    def test_construction(self):
        error = CollectionExceedsBalanceError(
            entitlement_id="ent-456",
            collection_amount="2000",
            outstanding_amount="1500",
        )
        assert error.error_code == RealityErrorCode.COLLECTION_EXCEEDS_BALANCE
        assert error.severity == RealitySeverity.HIGH
        assert error.component == "entitlement"
        assert error.entitlement_id == "ent-456"
        assert error.details["collection_amount"] == "2000"
        assert error.details["outstanding_amount"] == "1500"


# ============================================================================
# Tests for RealityExceptionFactory
# ============================================================================

class TestRealityExceptionFactory:
    def test_event_not_found(self):
        error = RealityExceptionFactory.event_not_found(event_id="evt-123")
        assert isinstance(error, EconomicEventNotFoundError)
        assert error.event_id == "evt-123"

    def test_invalid_status(self):
        error = RealityExceptionFactory.invalid_status(
            event_id="evt-123", current="draft", required="posted"
        )
        assert isinstance(error, EconomicEventInvalidStatusError)
        assert error.event_id == "evt-123"
        assert error.details["current_status"] == "draft"
        assert error.details["required_status"] == "posted"

    def test_mapping_not_found(self):
        error = RealityExceptionFactory.mapping_not_found(event_type="purchase")
        assert isinstance(error, MappingNotFoundError)
        assert error.event_type == "purchase"

    def test_account_not_found(self):
        error = RealityExceptionFactory.account_not_found(account_code="12345")
        assert isinstance(error, AccountNotFoundError)
        assert error.account_code == "12345"

    def test_asset_not_found(self):
        error = RealityExceptionFactory.asset_not_found(asset_id="ast-001")
        assert isinstance(error, AssetNotFoundError)
        assert error.asset_id == "ast-001"

    def test_asset_verification_failed(self):
        error = RealityExceptionFactory.asset_verification_failed(
            asset_id="ast-001", reason="Invalid data"
        )
        assert isinstance(error, AssetVerificationFailedError)
        assert error.asset_id == "ast-001"
        assert error.details["reason"] == "Invalid data"

    def test_asset_not_verified(self):
        error = RealityExceptionFactory.asset_not_verified(asset_id="ast-001")
        assert isinstance(error, AssetNotVerifiedError)
        assert error.asset_id == "ast-001"

    def test_payment_exceeds_balance(self):
        error = RealityExceptionFactory.payment_exceeds_balance(
            obligation_id="obl-123", payment="1000", outstanding="500"
        )
        assert isinstance(error, PaymentExceedsBalanceError)
        assert error.obligation_id == "obl-123"
        assert error.details["payment_amount"] == "1000"
        assert error.details["outstanding_amount"] == "500"

    def test_collection_exceeds_balance(self):
        error = RealityExceptionFactory.collection_exceeds_balance(
            entitlement_id="ent-456", collection="2000", outstanding="1500"
        )
        assert isinstance(error, CollectionExceedsBalanceError)
        assert error.entitlement_id == "ent-456"
        assert error.details["collection_amount"] == "2000"
        assert error.details["outstanding_amount"] == "1500"

    def test_factory_passes_kwargs(self):
        """Test that factory methods pass additional kwargs to the exception."""
        error = RealityExceptionFactory.event_not_found(
            event_id="evt-123",
            details={"extra": "value"},
            component="custom",
        )
        assert error.component == "custom"
        assert error.details["event_id"] == "evt-123"
        assert error.details["extra"] == "value"


# ============================================================================
# Integration: Exception hierarchy and inheritance
# ============================================================================

class TestExceptionHierarchy:
    def test_all_exceptions_inherit_from_reality_error(self):
        """All concrete exceptions should inherit from RealityError."""
        exceptions = [
            EconomicEventNotFoundError("1"),
            EconomicEventInvalidStatusError("1", "draft", "posted"),
            EventAlreadyMappedError("1", "jrn"),
            ValidationFailedError("msg", []),
            MappingNotFoundError("type"),
            AccountNotFoundError("code"),
            AssetNotFoundError("id"),
            AssetVerificationFailedError("id", "reason"),
            AssetDuplicateError("id", "existing"),
            AssetNotVerifiedError("id"),
            PaymentExceedsBalanceError("obl", "100", "50"),
            CollectionExceedsBalanceError("ent", "200", "100"),
        ]
        for error in exceptions:
            assert isinstance(error, RealityError)

    def test_all_exceptions_are_value_errors(self):
        """All exceptions should inherit from ValueError (via RealityError)."""
        error = AssetNotFoundError("id")
        assert isinstance(error, ValueError)