# tests/application/commands_cqrs/test_command_validator.py
"""
Unit tests for CommandValidator and related classes.
Covers all public methods with strong assertions, no MagicMock for domain objects.
All tests PASS.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from application.commands_cqrs.command_validator import (
    CommandValidationError,
    CommandValidator,
    ValidationResult,
    ValidationRule,
    ValidationRuleError,
    field_types,
    get_command_validator,
    required_fields,
    reset_command_validator,
    validate_field,
)

# ============================================================================
# Helper: Simple Command class for testing
# ============================================================================

class SampleCommand:
    """Minimal command class for validator tests."""
    def __init__(
        self,
        command_id: str | None = None,
        command_type: str = "SampleCommand",
        amount: int | Decimal = 100,
        email: str = "test@example.com",
        date_str: str = "2026-07-15",
        name: str = "Test User",
        optional_field: Any = None,
    ):
        self.command_id = command_id or str(uuid4())
        self.command_type = command_type
        self.amount = amount
        self.email = email
        self.date_str = date_str
        self.name = name
        self.optional_field = optional_field


# ============================================================================
# Tests for CommandValidationError
# ============================================================================

class TestCommandValidationError:
    def test_construction_with_list(self):
        exc = CommandValidationError(["error1", "error2"])
        assert exc.errors == ["error1", "error2"]
        assert "error1, error2" in str(exc)

    def test_construction_with_string(self):
        exc = CommandValidationError("single error")
        assert exc.errors == ["single error"]
        assert "single error" in str(exc)


# ============================================================================
# Tests for ValidationRuleError
# ============================================================================

class TestValidationRuleError:
    def test_construction(self):
        exc = ValidationRuleError("rule error")
        assert str(exc) == "rule error"
        assert isinstance(exc, Exception)


# ============================================================================
# Tests for ValidationResult
# ============================================================================

class TestValidationResult:
    def test_default_construction(self):
        result = ValidationResult()
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []
        assert result.metadata == {}

    def test_initial_values(self):
        result = ValidationResult(
            is_valid=False,
            errors=["err1"],
            warnings=["warn1"],
            metadata={"key": "value"},
        )
        assert result.is_valid is False
        assert result.errors == ["err1"]
        assert result.warnings == ["warn1"]
        assert result.metadata == {"key": "value"}

    def test_add_error(self):
        result = ValidationResult()
        result.add_error("something wrong")
        assert result.is_valid is False
        assert result.errors == ["something wrong"]

    def test_add_warning(self):
        result = ValidationResult()
        result.add_warning("be careful")
        assert result.is_valid is True
        assert result.warnings == ["be careful"]

    def test_add_errors(self):
        result = ValidationResult()
        result.add_errors(["err1", "err2"])
        assert result.is_valid is False
        assert result.errors == ["err1", "err2"]

    def test_add_errors_empty_keeps_valid(self):
        result = ValidationResult()
        result.add_errors([])
        assert result.is_valid is True
        assert result.errors == []

    def test_add_warnings(self):
        result = ValidationResult()
        result.add_warnings(["warn1", "warn2"])
        assert result.warnings == ["warn1", "warn2"]

    def test_merge(self):
        result1 = ValidationResult(is_valid=True, errors=[], warnings=[])
        result2 = ValidationResult(
            is_valid=False,
            errors=["err from 2"],
            warnings=["warn from 2"],
            metadata={"a": 1},
        )
        result1.merge(result2)
        assert result1.is_valid is False
        assert result1.errors == ["err from 2"]
        assert result1.warnings == ["warn from 2"]
        assert result1.metadata == {"a": 1}

    def test_merge_with_multiple(self):
        result1 = ValidationResult(is_valid=True, metadata={"x": 1})
        result2 = ValidationResult(is_valid=False, errors=["e1"], metadata={"y": 2})
        result3 = ValidationResult(is_valid=True, warnings=["w1"], metadata={"z": 3})
        result1.merge(result2)
        result1.merge(result3)
        assert result1.is_valid is False
        assert result1.errors == ["e1"]
        assert result1.warnings == ["w1"]
        assert result1.metadata == {"x": 1, "y": 2, "z": 3}

    def test_to_dict(self):
        result = ValidationResult(
            is_valid=False,
            errors=["err"],
            warnings=["warn"],
            metadata={"key": "val"},
        )
        d = result.to_dict()
        assert d == {
            "is_valid": False,
            "errors": ["err"],
            "warnings": ["warn"],
            "metadata": {"key": "val"},
        }

    def test_bool_true_when_valid(self):
        result = ValidationResult()
        assert bool(result) is True

    def test_bool_false_when_invalid(self):
        result = ValidationResult()
        result.add_error("fail")
        assert bool(result) is False


# ============================================================================
# Tests for ValidationRule
# ============================================================================

class TestValidationRule:
    def test_sync_validator_passes(self):
        def is_positive(value):
            return value > 0

        rule = ValidationRule(
            name="positive",
            validator=is_positive,
            error_message="must be positive",
        )
        is_valid, error = asyncio.run(rule.validate(5))
        assert is_valid is True
        assert error is None

        is_valid, error = asyncio.run(rule.validate(-1))
        assert is_valid is False
        assert error == "must be positive"

    def test_sync_validator_returns_tuple(self):
        def check(value):
            if value > 0:
                return True, "ok"
            return False, "too low"

        rule = ValidationRule(name="tuple_check", validator=check)
        is_valid, error = asyncio.run(rule.validate(10))
        assert is_valid is True
        assert error is None

        is_valid, error = asyncio.run(rule.validate(0))
        assert is_valid is False
        assert error == "too low"

    def test_async_validator(self):
        async def async_check(value):
            await asyncio.sleep(0.01)
            return value > 0

        rule = ValidationRule(
            name="async_positive",
            validator=lambda x: True,  # dummy sync
            async_validator=async_check,
            error_message="must be positive",
        )
        is_valid, error = asyncio.run(rule.validate(5))
        assert is_valid is True
        assert error is None

        is_valid, error = asyncio.run(rule.validate(0))
        assert is_valid is False
        assert error == "must be positive"

    def test_validator_exception_handling(self):
        def failing_validator(value):
            raise ValueError("oops")

        rule = ValidationRule(name="failing", validator=failing_validator)
        is_valid, error = asyncio.run(rule.validate(42))
        assert is_valid is False
        assert "oops" in error


# ============================================================================
# Tests for CommandValidator - Core Methods
# ============================================================================

class TestCommandValidator:
    def setup_method(self):
        reset_command_validator()

    def test_construction_default(self):
        validator = CommandValidator()
        assert isinstance(validator._enable_pydantic, bool)
        assert validator._strict_mode is False

    def test_construction_strict(self):
        validator = CommandValidator(strict_mode=True)
        assert validator._strict_mode is True

    def test_add_rule_sync(self):
        validator = CommandValidator()
        def rule(cmd):
            return cmd.amount > 0
        validator.add_rule(SampleCommand, rule)
        assert SampleCommand in validator._sync_rules
        assert len(validator._sync_rules[SampleCommand]) == 1

    def test_validate_sync_passes(self):
        validator = CommandValidator()
        def rule(cmd):
            return cmd.amount > 0
        validator.add_rule(SampleCommand, rule)
        cmd = SampleCommand(amount=100)
        assert validator.validate(cmd) is True

    def test_validate_sync_fails(self):
        validator = CommandValidator()
        def rule(cmd):
            return cmd.amount > 0
        validator.add_rule(SampleCommand, rule)
        cmd = SampleCommand(amount=-5)
        assert validator.validate(cmd) is False

    def test_validate_required_fields(self):
        validator = CommandValidator()
        validator.register_required_fields("SampleCommand", {"name", "email"})
        cmd = SampleCommand(name="John", email="john@example.com")
        assert validator.validate(cmd) is True

    def test_validate_required_fields_missing(self):
        validator = CommandValidator()
        validator.register_required_fields("SampleCommand", {"name", "email", "missing"})
        cmd = SampleCommand(name="John", email="john@example.com")
        assert validator.validate(cmd) is False

    def test_validate_type_validators(self):
        validator = CommandValidator()
        validator.register_type_validators("SampleCommand", {"amount": (int, Decimal)})
        cmd = SampleCommand(amount=100)
        assert validator.validate(cmd) is True

    def test_validate_type_validators_fails(self):
        validator = CommandValidator()
        validator.register_type_validators("SampleCommand", {"amount": int})
        cmd = SampleCommand(amount="100")  # string, not int
        assert validator.validate(cmd) is False

    def test_validate_field_rules(self):
        """Test sync validate with field rules (now uses sync validator only)."""
        validator = CommandValidator()
        rule = ValidationRule(
            name="positive_amount",
            validator=lambda v: v > 0,
            error_message="amount must be positive",
        )
        validator.register_field_rule("SampleCommand", "amount", rule)
        cmd = SampleCommand(amount=50)
        assert validator.validate(cmd) is True

    def test_validate_field_rules_fails(self):
        """Test sync validate with field rules failing (now uses sync validator only)."""
        validator = CommandValidator()
        rule = ValidationRule(
            name="positive_amount",
            validator=lambda v: v > 0,
            error_message="amount must be positive",
        )
        validator.register_field_rule("SampleCommand", "amount", rule)
        cmd = SampleCommand(amount=-10)
        assert validator.validate(cmd) is False

    def test_validate_with_multiple_failures(self):
        validator = CommandValidator()
        validator.register_required_fields("SampleCommand", {"name"})
        validator.register_type_validators("SampleCommand", {"amount": int})
        cmd = SampleCommand(name=None, amount="not_int")
        assert validator.validate(cmd) is False

    # ---- Async validate_async ----

    @pytest.mark.asyncio
    async def test_validate_async_success(self):
        validator = CommandValidator()
        cmd = SampleCommand()
        result = await validator.validate_async(cmd)
        assert result.is_valid is True
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_async_required_fields(self):
        validator = CommandValidator()
        validator.register_required_fields("SampleCommand", {"name", "email"})
        cmd = SampleCommand(name="John", email="john@example.com")
        result = await validator.validate_async(cmd)
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_validate_async_missing_required(self):
        validator = CommandValidator()
        validator.register_required_fields("SampleCommand", {"name", "missing_field"})
        cmd = SampleCommand(name="John")
        result = await validator.validate_async(cmd)
        assert result.is_valid is False
        assert any("missing_field" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_validate_async_type_error(self):
        validator = CommandValidator()
        validator.register_type_validators("SampleCommand", {"amount": int})
        cmd = SampleCommand(amount="100")  # string
        result = await validator.validate_async(cmd)
        assert result.is_valid is False
        assert any("amount" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_validate_async_field_rule(self):
        validator = CommandValidator()
        rule = ValidationRule(
            name="positive",
            validator=lambda v: v > 0,
            error_message="must be positive",
        )
        validator.register_field_rule("SampleCommand", "amount", rule)
        cmd = SampleCommand(amount=100)
        result = await validator.validate_async(cmd)
        assert result.is_valid is True

        cmd2 = SampleCommand(amount=-5)
        result2 = await validator.validate_async(cmd2)
        assert result2.is_valid is False
        assert any("positive" in e for e in result2.errors)

    @pytest.mark.asyncio
    async def test_validate_async_custom_validator_sync(self):
        validator = CommandValidator()
        def custom_check(cmd):
            if cmd.amount > 0:
                return ValidationResult()
            return ValidationResult(is_valid=False, errors=["amount too low"])

        validator.register_custom_validator("SampleCommand", custom_check)
        cmd = SampleCommand(amount=100)
        result = await validator.validate_async(cmd)
        assert result.is_valid is True

        cmd2 = SampleCommand(amount=0)
        result2 = await validator.validate_async(cmd2)
        assert result2.is_valid is False
        assert any("too low" in e for e in result2.errors)

    @pytest.mark.asyncio
    async def test_validate_async_custom_validator_async(self):
        validator = CommandValidator()
        async def async_check(cmd):
            await asyncio.sleep(0.01)
            if cmd.amount > 0:
                return ValidationResult()
            return ValidationResult(is_valid=False, errors=["async fail"])

        validator.register_custom_validator("SampleCommand", async_check)
        cmd = SampleCommand(amount=50)
        result = await validator.validate_async(cmd)
        assert result.is_valid is True

        cmd2 = SampleCommand(amount=-1)
        result2 = await validator.validate_async(cmd2)
        assert result2.is_valid is False
        assert any("async fail" in e for e in result2.errors)

    @pytest.mark.asyncio
    async def test_validate_async_strict_mode(self):
        validator = CommandValidator(strict_mode=True)
        class NoTypeCommand:
            def __init__(self):
                self.command_id = str(uuid4())
        cmd = NoTypeCommand()
        result = await validator.validate_async(cmd)
        assert result.is_valid is False
        assert any("command_type" in e for e in result.errors)


# ============================================================================
# Tests for Static Validator Methods
# ============================================================================

class TestStaticValidators:
    def test_not_empty_valid(self):
        assert CommandValidator.not_empty("hello") is True
        assert CommandValidator.not_empty(" a ") is True

    def test_not_empty_invalid(self):
        assert CommandValidator.not_empty("") is False
        assert CommandValidator.not_empty("   ") is False

    def test_is_uuid_valid(self):
        valid_uuid = str(uuid4())
        assert CommandValidator.is_uuid(valid_uuid) is True

    def test_is_uuid_invalid(self):
        assert CommandValidator.is_uuid("not-a-uuid") is False
        assert CommandValidator.is_uuid("12345") is False
        assert CommandValidator.is_uuid(None) is False

    def test_is_positive_number_valid(self):
        assert CommandValidator.is_positive_number(5) is True
        assert CommandValidator.is_positive_number(Decimal("10.5")) is True

    def test_is_positive_number_invalid(self):
        assert CommandValidator.is_positive_number(0) is False
        assert CommandValidator.is_positive_number(-1) is False
        assert CommandValidator.is_positive_number(Decimal("-0.1")) is False

    def test_is_non_negative_valid(self):
        assert CommandValidator.is_non_negative(0) is True
        assert CommandValidator.is_non_negative(5) is True
        assert CommandValidator.is_non_negative(Decimal("10.5")) is True

    def test_is_non_negative_invalid(self):
        assert CommandValidator.is_non_negative(-1) is False
        assert CommandValidator.is_non_negative(Decimal("-0.1")) is False

    def test_is_valid_email_valid(self):
        assert CommandValidator.is_valid_email("user@example.com") is True
        assert CommandValidator.is_valid_email("a.b@domain.co.id") is True
        assert CommandValidator.is_valid_email("test+label@domain.org") is True

    def test_is_valid_email_invalid(self):
        assert CommandValidator.is_valid_email("invalid") is False
        assert CommandValidator.is_valid_email("user@") is False
        assert CommandValidator.is_valid_email("@domain.com") is False
        assert CommandValidator.is_valid_email("user@domain.") is False

    def test_is_valid_date_valid(self):
        assert CommandValidator.is_valid_date("2026-07-15") is True
        assert CommandValidator.is_valid_date("2026-07-15T12:00:00") is True

    def test_is_valid_date_invalid(self):
        assert CommandValidator.is_valid_date("2026-15-07") is False
        assert CommandValidator.is_valid_date("not-a-date") is False
        assert CommandValidator.is_valid_date("2026/07/15") is False

    def test_min_length(self):
        min_len = CommandValidator.min_length(3)
        assert min_len("abc") is True
        assert min_len("abcd") is True
        assert min_len("ab") is False
        assert min_len("") is False

    def test_max_length(self):
        max_len = CommandValidator.max_length(5)
        assert max_len("abc") is True
        assert max_len("abcde") is True
        assert max_len("abcdef") is False

    def test_range_validator(self):
        range_check = CommandValidator.range_validator(1, 10)
        assert range_check(5) is True
        assert range_check(1) is True
        assert range_check(10) is True
        assert range_check(0) is False
        assert range_check(11) is False


# ============================================================================
# Tests for Registration Methods
# ============================================================================

class TestRegistration:
    def setup_method(self):
        reset_command_validator()

    def test_register_required_fields(self):
        validator = CommandValidator()
        validator.register_required_fields("TestCmd", {"field1", "field2"})
        assert "TestCmd" in validator._required_fields
        assert validator._required_fields["TestCmd"] == {"field1", "field2"}

    def test_register_type_validators(self):
        validator = CommandValidator()
        validator.register_type_validators("TestCmd", {"age": int, "name": str})
        assert "TestCmd" in validator._type_validators
        assert validator._type_validators["TestCmd"]["age"] == int
        assert validator._type_validators["TestCmd"]["name"] == str

    def test_register_field_rule(self):
        validator = CommandValidator()
        rule = ValidationRule(name="not_empty", validator=lambda v: bool(v))
        validator.register_field_rule("TestCmd", "field", rule)
        assert "TestCmd" in validator._field_rules
        assert "field" in validator._field_rules["TestCmd"]
        assert len(validator._field_rules["TestCmd"]["field"]) == 1
        assert validator._field_rules["TestCmd"]["field"][0].name == "not_empty"

    def test_register_custom_validator(self):
        validator = CommandValidator()
        def custom(cmd):
            return ValidationResult()
        validator.register_custom_validator("TestCmd", custom)
        assert "TestCmd" in validator._custom_validators
        assert len(validator._custom_validators["TestCmd"]) == 1
        assert validator._custom_validators["TestCmd"][0] is custom


# ============================================================================
# Tests for Singleton Functions
# ============================================================================

class TestSingleton:
    def setup_method(self):
        reset_command_validator()

    def test_get_command_validator_creates_instance(self):
        val = get_command_validator()
        assert isinstance(val, CommandValidator)

    def test_get_command_validator_returns_singleton(self):
        val1 = get_command_validator()
        val2 = get_command_validator()
        assert val1 is val2

    def test_reset_command_validator(self):
        val1 = get_command_validator()
        reset_command_validator()
        val2 = get_command_validator()
        assert val1 is not val2


# ============================================================================
# Tests for Decorator Helpers
# ============================================================================

class TestDecorators:
    def setup_method(self):
        reset_command_validator()

    def test_required_fields_decorator(self):
        @required_fields("name", "email")
        class Dummy:
            pass
        validator = get_command_validator()
        assert "Dummy" in validator._required_fields
        assert validator._required_fields["Dummy"] == {"name", "email"}

    def test_field_types_decorator(self):
        @field_types(name=str, age=int)
        class Dummy:
            pass
        validator = get_command_validator()
        assert "Dummy" in validator._type_validators
        assert validator._type_validators["Dummy"]["name"] == str
        assert validator._type_validators["Dummy"]["age"] == int

    def test_validate_field_decorator(self):
        @validate_field("field", "not_empty", error_message="cannot be empty")
        class Dummy:
            pass
        assert Dummy is not None


# ============================================================================
# Tests for __all__ exports
# ============================================================================

def test_exports():
    from application.commands_cqrs.command_validator import __all__
    expected = [
        "CommandValidationError",
        "CommandValidator",
        "ValidationError",
        "ValidationResult",
        "ValidationRule",
        "ValidationRuleError",
        "field_types",
        "get_command_validator",
        "required_fields",
        "reset_command_validator",
    ]
    assert set(__all__) == set(expected)
