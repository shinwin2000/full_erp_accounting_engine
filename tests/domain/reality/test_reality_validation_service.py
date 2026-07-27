# tests/domain/reality/test_reality_validation_service.py
"""
Comprehensive tests for domain/reality/reality_validation_service.py
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from domain.reality.reality_validation_service import (
    RealityValidationService,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
    _get_current_user,
    get_reality_validation_service,
)


# ============================================================================
# Tests for helper function _get_current_user
# ============================================================================

def test_get_current_user_success():
    with patch("importlib.import_module") as mock_import:
        mock_mod = MagicMock()
        mock_mod.get_current_user = MagicMock(return_value="test_user")
        mock_import.return_value = mock_mod
        result = _get_current_user()
        assert result == "test_user"


def test_get_current_user_import_failure():
    with patch("importlib.import_module", side_effect=ImportError):
        result = _get_current_user()
        assert result is None


def test_get_current_user_function_missing():
    with patch("importlib.import_module") as mock_import:
        mock_mod = MagicMock()
        # No get_current_user attribute
        del mock_mod.get_current_user
        mock_import.return_value = mock_mod
        result = _get_current_user()
        assert result is None


# ============================================================================
# Tests for Enums
# ============================================================================

class TestValidationSeverity:
    def test_members_exist(self):
        assert hasattr(ValidationSeverity, "ERROR")
        assert hasattr(ValidationSeverity, "WARNING")
        assert hasattr(ValidationSeverity, "INFO")

    def test_member_is_instance(self):
        assert isinstance(ValidationSeverity.ERROR, ValidationSeverity)


# ============================================================================
# Tests for ValidationIssue
# ============================================================================

class TestValidationIssue:
    def test_construction(self):
        issue = ValidationIssue(
            field="amount",
            message="Amount must be positive",
            severity=ValidationSeverity.ERROR,
            code="AMOUNT_POSITIVE",
        )
        assert issue.field == "amount"
        assert issue.message == "Amount must be positive"
        assert issue.severity == ValidationSeverity.ERROR
        assert issue.code == "AMOUNT_POSITIVE"

    def test_to_dict(self):
        issue = ValidationIssue(
            field="amount",
            message="Amount must be positive",
            severity=ValidationSeverity.ERROR,
            code="AMOUNT_POSITIVE",
        )
        d = issue.to_dict()
        assert d["field"] == "amount"
        assert d["message"] == "Amount must be positive"
        assert d["severity"] == "error"
        assert d["code"] == "AMOUNT_POSITIVE"


# ============================================================================
# Tests for ValidationResult
# ============================================================================

class TestValidationResult:
    def test_initialization(self):
        result = ValidationResult(
            is_valid=True,
            issues=[],
            warnings=[],
            requires_approval=False,
            requires_dual_control=False,
            validated_by="user",
        )
        assert result.is_valid is True
        assert result.issues == []
        assert result.warnings == []
        assert result.requires_approval is False
        assert result.requires_dual_control is False
        assert result.validated_by == "user"
        assert result.validation_id is not None
        assert result.validated_at is not None

    def test_compute_hash(self):
        result = ValidationResult(
            is_valid=True,
            issues=[],
            warnings=[],
            requires_approval=False,
            requires_dual_control=False,
            validated_by="user",
        )
        h1 = result.compute_hash()
        h2 = result.compute_hash()
        assert h1 == h2

        # Changing state changes hash
        result.is_valid = False
        h3 = result.compute_hash()
        assert h1 != h3

    def test_hash_mismatch_raises(self):
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            ValidationResult(
                is_valid=True,
                issues=[],
                warnings=[],
                requires_approval=False,
                requires_dual_control=False,
                validated_by="user",
                cryptographic_hash="invalid_hash",
            )

    def test_to_dict(self):
        issue = ValidationIssue(
            field="amount",
            message="Amount must be positive",
            severity=ValidationSeverity.ERROR,
            code="AMOUNT_POSITIVE",
        )
        result = ValidationResult(
            is_valid=False,
            issues=[issue],
            warnings=[],
            requires_approval=True,
            requires_dual_control=True,
            validated_by="user",
        )
        d = result.to_dict()
        assert d["is_valid"] is False
        assert len(d["issues"]) == 1
        assert d["issues"][0]["field"] == "amount"
        assert d["requires_approval"] is True
        assert d["requires_dual_control"] is True
        assert d["validated_by"] == "user"
        assert "validation_id" in d
        assert "validated_at" in d


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_money():
    money = MagicMock()
    money.amount = Decimal("1000000")
    money.currency = "IDR"
    return money


@pytest.fixture
def mock_quantity():
    quantity = MagicMock()
    quantity.value = 10
    quantity.unit = "pcs"
    return quantity


@pytest.fixture
def mock_event(mock_money, mock_quantity):
    event = MagicMock()
    event.event_id = uuid4()
    event.event_type = "SALE_OF_GOODS"
    event.amount = mock_money
    event.quantity = mock_quantity
    event.event_date = datetime.now(UTC)
    event.description = "Sale of goods"
    event.counterparty_id = uuid4()
    event.source_document_ref = "INV-001"
    event.metadata = {}
    event.status = MagicMock()
    event.status.name = "DRAFT"
    event.legal_entity_id = uuid4()
    event.reversal_of = None
    return event


@pytest.fixture
def mock_event_service():
    service = MagicMock()
    service.get_event = MagicMock(return_value=None)
    service.get_events_by_type = MagicMock(return_value=[])
    return service


@pytest.fixture
def validation_service(mock_event_service):
    with patch("domain.reality.reality_validation_service.get_economic_event_service") as mock_get:
        mock_get.return_value = mock_event_service
        with patch("domain.reality.reality_validation_service.get_financial_obligation_service") as mock_ob:
            with patch("domain.reality.reality_validation_service.get_financial_entitlement_service") as mock_en:
                service = RealityValidationService()
                service._event_service = mock_event_service
                yield service


# ============================================================================
# Tests for RealityValidationService - _validate_basic
# ============================================================================

class TestValidateBasic:
    @pytest.mark.asyncio
    async def test_valid_event(self, validation_service, mock_event):
        issues, warnings = await validation_service._validate_basic(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 0

    @pytest.mark.asyncio
    async def test_amount_zero_raises_error(self, validation_service, mock_event):
        mock_event.amount.amount = Decimal("0")
        issues, warnings = await validation_service._validate_basic(mock_event)
        assert len(issues) == 1
        assert issues[0].field == "amount"
        assert "greater than 0" in issues[0].message
        assert issues[0].severity == ValidationSeverity.ERROR

    @pytest.mark.asyncio
    async def test_amount_negative_raises_error(self, validation_service, mock_event):
        mock_event.amount.amount = Decimal("-1000")
        issues, warnings = await validation_service._validate_basic(mock_event)
        assert len(issues) == 1
        assert issues[0].field == "amount"
        assert "greater than 0" in issues[0].message

    @pytest.mark.asyncio
    async def test_currency_missing_raises_error(self, validation_service, mock_event):
        mock_event.amount.currency = None
        issues, warnings = await validation_service._validate_basic(mock_event)
        assert len(issues) == 1
        assert issues[0].field == "currency"
        assert "Currency is required" in issues[0].message

    @pytest.mark.asyncio
    async def test_date_future_warning(self, validation_service, mock_event):
        mock_event.event_date = datetime.now(UTC) + timedelta(days=3)
        issues, warnings = await validation_service._validate_basic(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "event_date"
        assert "days in the future" in warnings[0].message

    @pytest.mark.asyncio
    async def test_date_future_exceeds_limit_error(self, validation_service, mock_event):
        mock_event.event_date = datetime.now(UTC) + timedelta(days=10)
        issues, warnings = await validation_service._validate_basic(mock_event)
        assert len(issues) == 1
        assert issues[0].field == "event_date"
        assert "10 days in the future" in issues[0].message

    @pytest.mark.asyncio
    async def test_description_missing(self, validation_service, mock_event):
        mock_event.description = ""
        issues, warnings = await validation_service._validate_basic(mock_event)
        assert len(issues) == 1
        assert issues[0].field == "description"
        assert "Description is required" in issues[0].message

    @pytest.mark.asyncio
    async def test_description_too_short(self, validation_service, mock_event):
        mock_event.description = "AB"
        issues, warnings = await validation_service._validate_basic(mock_event)
        assert len(issues) == 1
        assert issues[0].field == "description"
        assert "minimum 3 characters" in issues[0].message

    @pytest.mark.asyncio
    async def test_large_amount_source_doc_warning(self, validation_service, mock_event):
        mock_event.amount.amount = Decimal("20000000")  # > 10 juta
        mock_event.source_document_ref = None
        issues, warnings = await validation_service._validate_basic(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "source_document_ref"
        assert "Source document reference is recommended" in warnings[0].message

    @pytest.mark.asyncio
    async def test_counterparty_required(self, validation_service, mock_event):
        mock_event.counterparty_id = None
        mock_event.event_type = "PURCHASE_OF_GOODS"
        issues, warnings = await validation_service._validate_basic(mock_event)
        assert len(issues) == 1
        assert issues[0].field == "counterparty_id"
        assert "Counterparty is required" in issues[0].message


# ============================================================================
# Tests for RealityValidationService - _validate_business_rules
# ============================================================================

class TestValidateBusinessRules:
    @pytest.mark.asyncio
    async def test_sale_of_goods_no_quantity_warning(self, validation_service, mock_event):
        mock_event.event_type = "SALE_OF_GOODS"
        mock_event.quantity = None
        issues, warnings = await validation_service._validate_business_rules(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "quantity"
        assert "Quantity is recommended" in warnings[0].message

    @pytest.mark.asyncio
    async def test_sale_of_goods_high_unit_price_warning(self, validation_service, mock_event):
        mock_event.event_type = "SALE_OF_GOODS"
        mock_event.amount.amount = Decimal("1000000000")
        mock_event.quantity.value = 10
        issues, warnings = await validation_service._validate_business_rules(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "amount"
        assert "Unit price 100,000,000 is unusually high" in warnings[0].message

    @pytest.mark.asyncio
    async def test_purchase_of_goods_no_quantity_warning(self, validation_service, mock_event):
        mock_event.event_type = "PURCHASE_OF_GOODS"
        mock_event.quantity = None
        issues, warnings = await validation_service._validate_business_rules(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "quantity"
        assert "Quantity is recommended" in warnings[0].message

    @pytest.mark.asyncio
    async def test_asset_acquisition_no_asset_type_warning(self, validation_service, mock_event):
        mock_event.event_type = "ASSET_ACQUISITION"
        mock_event.metadata = {}
        issues, warnings = await validation_service._validate_business_rules(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "metadata.asset_type"
        assert "Asset type is recommended" in warnings[0].message

    @pytest.mark.asyncio
    async def test_salary_expense_no_employee_count_warning(self, validation_service, mock_event):
        mock_event.event_type = "SALARY_EXPENSE"
        mock_event.metadata = {}
        issues, warnings = await validation_service._validate_business_rules(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "metadata.employee_count"
        assert "Employee count is recommended" in warnings[0].message

    @pytest.mark.asyncio
    async def test_salary_expense_high_amount_warning(self, validation_service, mock_event):
        mock_event.event_type = "SALARY_EXPENSE"
        mock_event.amount.amount = Decimal("600000000")
        mock_event.metadata = {"employee_count": 10}
        issues, warnings = await validation_service._validate_business_rules(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "amount"
        assert "Salary expense 600,000,000 is unusually high" in warnings[0].message

    @pytest.mark.asyncio
    async def test_loan_drawdown_no_agreement_warning(self, validation_service, mock_event):
        mock_event.event_type = "LOAN_DRAWDOWN"
        mock_event.metadata = {}
        issues, warnings = await validation_service._validate_business_rules(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "metadata.loan_agreement_ref"
        assert "Loan agreement reference is recommended" in warnings[0].message


# ============================================================================
# Tests for RealityValidationService - _validate_consistency
# ============================================================================

class TestValidateConsistency:
    @pytest.mark.asyncio
    async def test_duplicate_source_doc_warning(self, validation_service, mock_event):
        existing = MagicMock()
        existing.event_id = uuid4()
        existing.source_document_ref = "INV-001"
        validation_service._event_service.get_events_by_type.return_value = [existing]

        issues, warnings = await validation_service._validate_consistency(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "source_document_ref"
        assert "Event with same source document already exists" in warnings[0].message

    @pytest.mark.asyncio
    async def test_duplicate_source_doc_same_event_ignored(self, validation_service, mock_event):
        # Same event ID should not trigger warning
        existing = MagicMock()
        existing.event_id = mock_event.event_id
        existing.source_document_ref = "INV-001"
        validation_service._event_service.get_events_by_type.return_value = [existing]

        issues, warnings = await validation_service._validate_consistency(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 0

    @pytest.mark.asyncio
    async def test_reversal_of_original_not_found_error(self, validation_service, mock_event):
        mock_event.reversal_of = uuid4()
        validation_service._event_service.get_event.return_value = None

        issues, warnings = await validation_service._validate_consistency(mock_event)
        assert len(issues) == 1
        assert issues[0].field == "reversal_of"
        assert "Original event" in issues[0].message
        assert "not found" in issues[0].message

    @pytest.mark.asyncio
    async def test_reversal_of_original_not_posted_error(self, validation_service, mock_event):
        original_id = uuid4()
        mock_event.reversal_of = original_id
        original = MagicMock()
        original.status = MagicMock()
        original.status.name = "DRAFT"
        validation_service._event_service.get_event.return_value = original

        issues, warnings = await validation_service._validate_consistency(mock_event)
        assert len(issues) == 1
        assert issues[0].field == "reversal_of"
        assert "status is DRAFT" in issues[0].message
        assert "must be POSTED" in issues[0].message


# ============================================================================
# Tests for RealityValidationService - _validate_compliance
# ============================================================================

class TestValidateCompliance:
    @pytest.mark.asyncio
    async def test_large_cash_transaction_aml_error(self, validation_service, mock_event):
        mock_event.amount.amount = Decimal("150000000")
        mock_event.metadata = {"payment_method": "CASH"}
        issues, warnings = await validation_service._validate_compliance(mock_event)
        assert len(issues) == 1
        assert issues[0].field == "payment_method"
        assert "Large cash transaction" in issues[0].message
        assert "enhanced due diligence" in issues[0].message

    @pytest.mark.asyncio
    async def test_large_cash_transaction_with_non_cash(self, validation_service, mock_event):
        mock_event.amount.amount = Decimal("150000000")
        mock_event.metadata = {"payment_method": "TRANSFER"}
        issues, warnings = await validation_service._validate_compliance(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 0

    @pytest.mark.asyncio
    async def test_related_party_no_arm_length_warning(self, validation_service, mock_event):
        mock_event.metadata = {"is_related_party": True}
        issues, warnings = await validation_service._validate_compliance(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "metadata.arm_length_price"
        assert "arm's length price documentation" in warnings[0].message

    @pytest.mark.asyncio
    async def test_related_party_large_amount_warning(self, validation_service, mock_event):
        mock_event.metadata = {"is_related_party": True, "arm_length_price": "Yes"}
        mock_event.amount.amount = Decimal("60000000")
        issues, warnings = await validation_service._validate_compliance(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "amount"
        assert "Large related party transaction" in warnings[0].message
        assert "may require board approval" in warnings[0].message

    @pytest.mark.asyncio
    async def test_cross_border_missing_exchange_rate_warning(self, validation_service, mock_event):
        mock_event.metadata = {"is_cross_border": True}
        issues, warnings = await validation_service._validate_compliance(mock_event)
        assert len(issues) == 0
        assert len(warnings) == 1
        assert warnings[0].field == "metadata.exchange_rate_used"
        assert "Exchange rate is required" in warnings[0].message


# ============================================================================
# Tests for RealityValidationService - _check_requires_approval
# ============================================================================

class TestCheckRequiresApproval:
    def test_large_amount_requires_approval(self, validation_service):
        event = MagicMock()
        event.amount = MagicMock()
        event.amount.amount = Decimal("60000000")
        event.event_type = "SALE_OF_GOODS"
        event.metadata = {}
        assert validation_service._check_requires_approval(event) is True

    def test_small_amount_no_approval(self, validation_service):
        event = MagicMock()
        event.amount = MagicMock()
        event.amount.amount = Decimal("10000000")
        event.event_type = "SALE_OF_GOODS"
        event.metadata = {}
        assert validation_service._check_requires_approval(event) is False

    def test_asset_disposal_requires_approval(self, validation_service):
        event = MagicMock()
        event.amount = MagicMock()
        event.amount.amount = Decimal("1000000")
        event.event_type = "ASSET_DISPOSAL"
        event.metadata = {}
        assert validation_service._check_requires_approval(event) is True

    def test_bad_debt_write_off_requires_approval(self, validation_service):
        event = MagicMock()
        event.amount = MagicMock()
        event.amount.amount = Decimal("1000000")
        event.event_type = "BAD_DEBT_WRITE_OFF"
        event.metadata = {}
        assert validation_service._check_requires_approval(event) is True

    def test_related_party_large_requires_approval(self, validation_service):
        event = MagicMock()
        event.amount = MagicMock()
        event.amount.amount = Decimal("30000000")
        event.event_type = "SALE_OF_GOODS"
        event.metadata = {"is_related_party": True}
        assert validation_service._check_requires_approval(event) is True

    def test_related_party_small_no_approval(self, validation_service):
        event = MagicMock()
        event.amount = MagicMock()
        event.amount.amount = Decimal("10000000")
        event.event_type = "SALE_OF_GOODS"
        event.metadata = {"is_related_party": True}
        assert validation_service._check_requires_approval(event) is False


# ============================================================================
# Tests for RealityValidationService - _check_requires_dual_control
# ============================================================================

class TestCheckRequiresDualControl:
    def test_very_large_amount_requires_dual_control(self, validation_service):
        event = MagicMock()
        event.amount = MagicMock()
        event.amount.amount = Decimal("2000000000")
        event.event_type = "SALE_OF_GOODS"
        event.metadata = {}
        assert validation_service._check_requires_dual_control(event) is True

    def test_asset_disposal_requires_dual_control(self, validation_service):
        event = MagicMock()
        event.amount = MagicMock()
        event.amount.amount = Decimal("1000000")
        event.event_type = "ASSET_DISPOSAL"
        event.metadata = {}
        assert validation_service._check_requires_dual_control(event) is True

    def test_period_close_requires_dual_control(self, validation_service):
        event = MagicMock()
        event.amount = MagicMock()
        event.amount.amount = Decimal("1000000")
        event.event_type = "PERIOD_CLOSE"
        event.metadata = {}
        assert validation_service._check_requires_dual_control(event) is True

    def test_small_amount_no_dual_control(self, validation_service):
        event = MagicMock()
        event.amount = MagicMock()
        event.amount.amount = Decimal("1000000")
        event.event_type = "SALE_OF_GOODS"
        event.metadata = {}
        assert validation_service._check_requires_dual_control(event) is False


# ============================================================================
# Tests for RealityValidationService - validate_event
# ============================================================================

class TestValidateEvent:
    @pytest.mark.asyncio
    async def test_valid_event_passes(self, validation_service, mock_event):
        with patch.object(validation_service, "_validate_basic", return_value=([], [])):
            with patch.object(validation_service, "_validate_business_rules", return_value=([], [])):
                with patch.object(validation_service, "_validate_consistency", return_value=([], [])):
                    with patch.object(validation_service, "_validate_compliance", return_value=([], [])):
                        with patch.object(validation_service, "_check_requires_approval", return_value=False):
                            with patch.object(validation_service, "_check_requires_dual_control", return_value=False):
                                result = await validation_service.validate_event(mock_event, "user")
                                assert result.is_valid is True
                                assert len(result.issues) == 0
                                assert len(result.warnings) == 0
                                assert result.validated_by == "user"
                                assert result.validation_id is not None

    @pytest.mark.asyncio
    async def test_event_with_errors(self, validation_service, mock_event):
        issue = ValidationIssue(
            field="amount",
            message="Amount must be positive",
            severity=ValidationSeverity.ERROR,
            code="AMOUNT_POSITIVE",
        )
        with patch.object(validation_service, "_validate_basic", return_value=([issue], [])):
            with patch.object(validation_service, "_validate_business_rules", return_value=([], [])):
                with patch.object(validation_service, "_validate_consistency", return_value=([], [])):
                    with patch.object(validation_service, "_validate_compliance", return_value=([], [])):
                        result = await validation_service.validate_event(mock_event, "user")
                        assert result.is_valid is False
                        assert len(result.issues) == 1
                        assert result.issues[0] is issue

    @pytest.mark.asyncio
    async def test_event_with_warnings_only_passes(self, validation_service, mock_event):
        warning = ValidationIssue(
            field="quantity",
            message="Quantity is recommended",
            severity=ValidationSeverity.WARNING,
            code="QUANTITY_RECOMMENDED",
        )
        with patch.object(validation_service, "_validate_basic", return_value=([], [warning])):
            with patch.object(validation_service, "_validate_business_rules", return_value=([], [])):
                with patch.object(validation_service, "_validate_consistency", return_value=([], [])):
                    with patch.object(validation_service, "_validate_compliance", return_value=([], [])):
                        result = await validation_service.validate_event(mock_event, "user")
                        assert result.is_valid is True
                        assert len(result.warnings) == 1
                        assert result.warnings[0] is warning

    @pytest.mark.asyncio
    async def test_requires_approval_and_dual_control(self, validation_service, mock_event):
        with patch.object(validation_service, "_validate_basic", return_value=([], [])):
            with patch.object(validation_service, "_validate_business_rules", return_value=([], [])):
                with patch.object(validation_service, "_validate_consistency", return_value=([], [])):
                    with patch.object(validation_service, "_validate_compliance", return_value=([], [])):
                        with patch.object(validation_service, "_check_requires_approval", return_value=True):
                            with patch.object(validation_service, "_check_requires_dual_control", return_value=True):
                                result = await validation_service.validate_event(mock_event, "user")
                                assert result.requires_approval is True
                                assert result.requires_dual_control is True

    @pytest.mark.asyncio
    async def test_user_fallback_to_unknown(self, validation_service, mock_event):
        with patch.object(validation_service, "_validate_basic", return_value=([], [])):
            with patch.object(validation_service, "_validate_business_rules", return_value=([], [])):
                with patch.object(validation_service, "_validate_consistency", return_value=([], [])):
                    with patch.object(validation_service, "_validate_compliance", return_value=([], [])):
                        with patch("domain.reality.reality_validation_service._get_current_user", return_value=None):
                            result = await validation_service.validate_event(mock_event, user_id=None)
                            assert result.validated_by == "unknown"


# ============================================================================
# Tests for RealityValidationService - validate_before_posting
# ============================================================================

class TestValidateBeforePosting:
    @pytest.mark.asyncio
    async def test_event_not_found(self, validation_service):
        event_id = uuid4()
        validation_service._event_service.get_event.return_value = None
        result = await validation_service.validate_before_posting(event_id, "user")
        assert result.is_valid is False
        assert len(result.issues) == 1
        assert result.issues[0].field == "event_id"
        assert f"Event {event_id} not found" in result.issues[0].message

    @pytest.mark.asyncio
    async def test_event_found_passes_to_validate_event(self, validation_service, mock_event):
        event_id = uuid4()
        mock_event.event_id = event_id
        validation_service._event_service.get_event.return_value = mock_event
        with patch.object(validation_service, "validate_event", return_value=ValidationResult(
            is_valid=True,
            issues=[],
            warnings=[],
            validated_by="user",
        )) as mock_validate:
            result = await validation_service.validate_before_posting(event_id, "user")
            mock_validate.assert_called_once_with(mock_event, "user")
            assert result.is_valid is True


# ============================================================================
# Tests for RealityValidationService - get_validation_history
# ============================================================================

class TestGetValidationHistory:
    def test_empty_history(self, validation_service):
        history = validation_service.get_validation_history()
        assert history == []

    def test_returns_limit(self, validation_service):
        for i in range(5):
            result = ValidationResult(is_valid=True, issues=[], warnings=[], validated_by="user")
            validation_service._validation_history.append(result)
        history = validation_service.get_validation_history(limit=3)
        assert len(history) == 3
        # Should return the latest
        assert history[-1] is validation_service._validation_history[-1]

    def test_filter_by_event_id_placeholder(self, validation_service):
        # Currently event_id filtering is a placeholder (no real filtering)
        result = ValidationResult(is_valid=True, issues=[], warnings=[], validated_by="user")
        validation_service._validation_history.append(result)
        history = validation_service.get_validation_history(event_id=uuid4())
        # As per implementation, it returns all results (no filtering)
        assert len(history) == 1

    def test_only_failed(self, validation_service):
        result1 = ValidationResult(is_valid=True, issues=[], warnings=[], validated_by="user")
        result2 = ValidationResult(is_valid=False, issues=[ValidationIssue(
            field="test", message="fail", severity=ValidationSeverity.ERROR, code="ERR"
        )], warnings=[], validated_by="user")
        validation_service._validation_history.extend([result1, result2])
        history = validation_service.get_validation_history(only_failed=True)
        assert len(history) == 1
        assert history[0] is result2


# ============================================================================
# Tests for RealityValidationService - get_statistics
# ============================================================================

class TestGetStatistics:
    def test_empty(self, validation_service):
        stats = validation_service.get_statistics()
        assert stats["total_validations"] == 0

    def test_with_data(self, validation_service):
        # Add some validation results
        for i in range(10):
            is_valid = i % 2 == 0
            issues = []
            warnings = []
            if not is_valid:
                issues.append(ValidationIssue(
                    field="test", message="fail", severity=ValidationSeverity.ERROR, code="ERR001"
                ))
            result = ValidationResult(
                is_valid=is_valid,
                issues=issues,
                warnings=warnings,
                requires_approval=(i % 3 == 0),
                requires_dual_control=(i % 5 == 0),
                validated_by="user",
            )
            validation_service._validation_history.append(result)

        stats = validation_service.get_statistics()
        assert stats["total_validations"] == 10
        assert stats["passed"] == 5
        assert stats["failed"] == 5
        assert stats["pass_rate"] == 0.5
        # issue_codes should have ERR001 count 5
        assert stats["issue_codes"]["ERR001"] == 5
        assert stats["requires_approval_count"] == 4  # 0,3,6,9 -> 4
        assert stats["requires_dual_control_count"] == 2  # 0,5 -> 2
        assert stats["latest_validation"] == validation_service._validation_history[-1].validated_at.isoformat()


# ============================================================================
# Tests for RealityValidationService - reset
# ============================================================================

def test_reset(validation_service):
    result = ValidationResult(is_valid=True, issues=[], warnings=[], validated_by="user")
    validation_service._validation_history.append(result)
    assert len(validation_service._validation_history) == 1
    validation_service.reset()
    assert len(validation_service._validation_history) == 0


# ============================================================================
# Tests for Singleton
# ============================================================================

def test_get_reality_validation_service():
    # Reset global
    import domain.reality.reality_validation_service as module
    module._reality_validation_service_instance = None
    s1 = get_reality_validation_service()
    s2 = get_reality_validation_service()
    assert s1 is s2
    assert isinstance(s1, RealityValidationService)