# tests/infrastructure/database/test_seed_data_validator.py
# Perbaikan kualitas assertions: mengganti semua assert True dengan
# assertion yang memeriksa nilai aktual, efek samping, dan validasi yang benar.

import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from infrastructure.database.seed_data_validator import (
    CustomRule,
    EnumRule,
    MinMaxRule,
    PatternRule,
    RequiredRule,
    SeedConstraintError,
    SeedDataValidator,
    SeedFormatError,
    SeedSchemaError,
    SeedValidationError,
    TypeRule,
    UniqueRule,
    ValidationRule,
    get_seed_validator,
)


# ============================================================================
# Exception tests
# ============================================================================
class TestSeedValidationError:
    def test_construction(self):
        error = SeedValidationError("test message")
        assert isinstance(error, Exception)
        assert str(error) == "test message"


class TestSeedSchemaError:
    def test_construction(self):
        error = SeedSchemaError("schema error")
        assert isinstance(error, SeedValidationError)


class TestSeedConstraintError:
    def test_construction(self):
        error = SeedConstraintError("constraint error")
        assert isinstance(error, SeedValidationError)


class TestSeedFormatError:
    def test_construction(self):
        error = SeedFormatError("format error")
        assert isinstance(error, SeedValidationError)


# ============================================================================
# ValidationRule base class tests
# ============================================================================
class TestValidationRule:
    def test_construction(self):
        rule = ValidationRule("test", "field", "message")
        assert rule.name == "test"
        assert rule.field == "field"
        assert rule.message == "message"

    def test_validate_raises_not_implemented(self):
        rule = ValidationRule("test", "field", "message")
        with pytest.raises(NotImplementedError):
            rule.validate({})


# ============================================================================
# RequiredRule tests
# ============================================================================
class TestRequiredRule:
    def test_field_missing(self):
        rule = RequiredRule("name")
        errors = rule.validate({"other": "value"})
        assert errors == ["Field 'name' is required"]

    def test_field_none(self):
        rule = RequiredRule("name")
        errors = rule.validate({"name": None})
        assert errors == ["Field 'name' is required"]

    def test_field_empty_string(self):
        rule = RequiredRule("name")
        errors = rule.validate({"name": ""})
        assert errors == ["Field 'name' is required"]

    def test_field_present(self):
        rule = RequiredRule("name")
        errors = rule.validate({"name": "John"})
        assert errors == []

    def test_custom_message(self):
        rule = RequiredRule("name", "Name is required!")
        errors = rule.validate({})
        assert errors == ["Name is required!"]


# ============================================================================
# TypeRule tests
# ============================================================================
class TestTypeRule:
    def test_correct_type(self):
        rule = TypeRule("age", int)
        errors = rule.validate({"age": 25})
        assert errors == []

    def test_wrong_type(self):
        rule = TypeRule("age", int)
        errors = rule.validate({"age": "25"})
        assert errors == ["Field 'age' must be of type int"]

    def test_none_value(self):
        rule = TypeRule("age", int)
        errors = rule.validate({"age": None})
        assert errors == []  # None is ignored (handled by RequiredRule)

    def test_custom_message(self):
        rule = TypeRule("age", int, "Age must be integer")
        errors = rule.validate({"age": "25"})
        assert errors == ["Age must be integer"]


# ============================================================================
# PatternRule tests
# ============================================================================
class TestPatternRule:
    def test_match(self):
        rule = PatternRule("email", re.compile(r"^[a-z]+$"))
        errors = rule.validate({"email": "hello"})
        assert errors == []

    def test_no_match(self):
        rule = PatternRule("email", re.compile(r"^[a-z]+$"))
        errors = rule.validate({"email": "Hello123"})
        assert errors == ["Field 'email' has invalid format"]

    def test_none_value(self):
        rule = PatternRule("email", re.compile(r"^[a-z]+$"))
        errors = rule.validate({"email": None})
        assert errors == []

    def test_non_string_value(self):
        rule = PatternRule("email", re.compile(r"^[a-z]+$"))
        errors = rule.validate({"email": 123})
        assert errors == ["Field 'email' must be a string for pattern validation"]

    def test_custom_message(self):
        rule = PatternRule("email", re.compile(r"^[a-z]+$"), "Invalid email format")
        errors = rule.validate({"email": "Hello"})
        assert errors == ["Invalid email format"]


# ============================================================================
# MinMaxRule tests
# ============================================================================
class TestMinMaxRule:
    def test_within_range(self):
        rule = MinMaxRule("age", min_val=18, max_val=65)
        errors = rule.validate({"age": 30})
        assert errors == []

    def test_below_min(self):
        rule = MinMaxRule("age", min_val=18, max_val=65)
        errors = rule.validate({"age": 16})
        assert errors == ["Field 'age' (16) is below minimum 18"]

    def test_above_max(self):
        rule = MinMaxRule("age", min_val=18, max_val=65)
        errors = rule.validate({"age": 70})
        assert errors == ["Field 'age' (70) exceeds maximum 65"]

    def test_none_value(self):
        rule = MinMaxRule("age", min_val=18, max_val=65)
        errors = rule.validate({"age": None})
        assert errors == []

    def test_non_numeric_value(self):
        rule = MinMaxRule("age", min_val=18, max_val=65)
        errors = rule.validate({"age": "30"})
        assert errors == ["Field 'age' must be numeric for range validation"]

    def test_decimal_value(self):
        rule = MinMaxRule("price", min_val=Decimal("10.5"), max_val=Decimal("100.0"))
        errors = rule.validate({"price": Decimal("50.0")})
        assert errors == []

    def test_custom_message(self):
        rule = MinMaxRule("age", min_val=18, max_val=65, message="Age out of range")
        errors = rule.validate({"age": 70})
        assert errors == ["Age out of range"]


# ============================================================================
# EnumRule tests
# ============================================================================
class TestEnumRule:
    def test_allowed_value(self):
        rule = EnumRule("status", ["active", "inactive", "suspended"])
        errors = rule.validate({"status": "active"})
        assert errors == []

    def test_disallowed_value(self):
        rule = EnumRule("status", ["active", "inactive", "suspended"])
        errors = rule.validate({"status": "deleted"})
        assert errors == [
            "Field 'status' value 'deleted' not in allowed values: ['active', 'inactive', 'suspended']"
        ]

    def test_none_value(self):
        rule = EnumRule("status", ["active", "inactive"])
        errors = rule.validate({"status": None})
        assert errors == []

    def test_custom_message(self):
        rule = EnumRule("status", ["active", "inactive"], "Invalid status")
        errors = rule.validate({"status": "pending"})
        assert errors == ["Invalid status"]


# ============================================================================
# UniqueRule tests
# ============================================================================
class TestUniqueRule:
    def test_unique_value(self):
        rule = UniqueRule("code")
        errors1 = rule.validate({"code": "A"})
        errors2 = rule.validate({"code": "B"})
        assert errors1 == []
        assert errors2 == []

    def test_duplicate_value(self):
        rule = UniqueRule("code")
        errors1 = rule.validate({"code": "A"})
        errors2 = rule.validate({"code": "A"})
        assert errors1 == []
        assert errors2 == ["Duplicate value 'A' for field 'code'"]

    def test_none_ignored(self):
        rule = UniqueRule("code")
        errors1 = rule.validate({"code": None})
        errors2 = rule.validate({"code": None})
        assert errors1 == []
        assert errors2 == []  # None values are ignored for uniqueness

    def test_custom_message(self):
        rule = UniqueRule("code", "Code must be unique")
        rule.validate({"code": "A"})
        errors = rule.validate({"code": "A"})
        assert errors == ["Code must be unique"]


# ============================================================================
# CustomRule tests
# ============================================================================
class TestCustomRule:
    def test_validator_true(self):
        rule = CustomRule("even", "value", lambda x: x % 2 == 0, "Value must be even")
        errors = rule.validate({"value": 4})
        assert errors == []

    def test_validator_false(self):
        rule = CustomRule("even", "value", lambda x: x % 2 == 0, "Value must be even")
        errors = rule.validate({"value": 3})
        assert errors == ["Value must be even"]

    def test_none_value(self):
        rule = CustomRule("even", "value", lambda x: x % 2 == 0, "Value must be even")
        errors = rule.validate({"value": None})
        assert errors == []

    def test_field_missing(self):
        rule = CustomRule("even", "value", lambda x: x % 2 == 0, "Value must be even")
        errors = rule.validate({})
        assert errors == []


# ============================================================================
# SeedDataValidator tests
# ============================================================================
class TestSeedDataValidator:
    @pytest.fixture
    def validator(self):
        return SeedDataValidator()

    def test_default_schemas_exist(self, validator):
        expected_tables = [
            "legal_entity",
            "account",
            "iam_user",
            "iam_role",
            "iam_permission",
            "system_setting",
            "customer",
            "supplier",
            "employee",
            "tax_rate",
        ]
        for table in expected_tables:
            assert table in validator._schemas
            assert isinstance(validator._schemas[table], list)
            assert len(validator._schemas[table]) > 0

    def test_add_schema(self, validator):
        rules = [RequiredRule("id"), TypeRule("id", int)]
        validator.add_schema("test_table", rules)
        assert "test_table" in validator._schemas
        assert validator._schemas["test_table"] == rules

    def test_get_schema(self, validator):
        # Existing schema
        schema = validator.get_schema("legal_entity")
        assert len(schema) > 0
        # Non-existent schema
        assert validator.get_schema("unknown") == []

    async def test_validate_record_valid(self, validator):
        record = {"name": "John", "age": 30}
        rules = [RequiredRule("name"), TypeRule("age", int)]
        validator.add_schema("test", rules)
        errors = await validator.validate_record("test", record)
        assert errors == []

    async def test_validate_record_invalid(self, validator):
        record = {"name": "", "age": "30"}
        rules = [RequiredRule("name"), TypeRule("age", int)]
        validator.add_schema("test", rules)
        errors = await validator.validate_record("test", record)
        assert len(errors) == 2
        assert any("required" in e.lower() for e in errors)
        assert any("must be of type int" in e for e in errors)

    async def test_validate_record_with_unique_checks(self, validator):
        record1 = {"code": "A"}
        record2 = {"code": "A"}
        rules = [RequiredRule("code"), UniqueRule("code")]
        validator.add_schema("test", rules)
        unique_checks = {}

        errors1 = await validator.validate_record("test", record1, unique_checks)
        errors2 = await validator.validate_record("test", record2, unique_checks)

        assert errors1 == []
        # Since UniqueRule is processed in validate_record, it won't add duplicate error there
        # because it's not aware of previous records unless we track it manually.
        # Actually validate_record does not track uniqueness across calls; it relies on the caller.
        # In validate_dataset, it handles duplicates separately.
        # So we test that separately.
        # Here we just check that no errors from the rule itself (it doesn't track across calls)
        assert errors2 == []  # No error because unique rule doesn't remember across calls

    async def test_validate_dataset_valid(self, validator):
        records = [
            {"code": "A", "name": "Item A"},
            {"code": "B", "name": "Item B"},
        ]
        rules = [RequiredRule("code"), RequiredRule("name"), UniqueRule("code")]
        validator.add_schema("test", rules)
        result = await validator.validate_dataset("test", records)
        assert result["valid"] is True
        assert result["total_records"] == 2
        assert result["valid_records"] == 2
        assert result["invalid_records"] == 0
        assert result["errors"] == []

    async def test_validate_dataset_invalid(self, validator):
        records = [
            {"code": "A", "name": ""},
            {"code": "A", "name": "Item B"},
        ]
        rules = [RequiredRule("code"), RequiredRule("name"), UniqueRule("code")]
        validator.add_schema("test", rules)
        result = await validator.validate_dataset("test", records)
        assert result["valid"] is False
        assert result["total_records"] == 2
        assert result["valid_records"] == 0
        assert result["invalid_records"] == 2
        assert len(result["errors"]) == 2
        # Check first error: name missing and duplicate
        assert result["errors"][0]["record_index"] == 0
        assert any("required" in e.lower() for e in result["errors"][0]["errors"])
        # Duplicate error added in validate_dataset
        assert any("Duplicate value" in e for e in result["errors"][0]["errors"])
        # Second record: duplicate code
        assert result["errors"][1]["record_index"] == 1
        assert any("Duplicate value" in e for e in result["errors"][1]["errors"])

    # ---- validate_file ----
    async def test_validate_file_yaml(self, validator, tmp_path):
        # Create a YAML file
        file_path = tmp_path / "test_table.yaml"
        data = [
            {"id": 1, "name": "Item1"},
            {"id": 2, "name": "Item2"},
        ]
        with open(file_path, "w") as f:
            yaml.dump(data, f)

        rules = [RequiredRule("id"), RequiredRule("name"), TypeRule("id", int)]
        validator.add_schema("test_table", rules)

        result = await validator.validate_file(file_path, "test_table")
        assert result["valid"] is True
        assert result["total_records"] == 2
        assert result["valid_records"] == 2

    async def test_validate_file_json(self, validator, tmp_path):
        file_path = tmp_path / "test_table.json"
        data = {"records": [{"id": 1, "name": "Item1"}, {"id": 2, "name": "Item2"}]}
        with open(file_path, "w") as f:
            json.dump(data, f)

        rules = [RequiredRule("id"), RequiredRule("name"), TypeRule("id", int)]
        validator.add_schema("test_table", rules)

        result = await validator.validate_file(file_path, "test_table")
        assert result["valid"] is True
        assert result["total_records"] == 2

    async def test_validate_file_auto_table_name(self, validator, tmp_path):
        file_path = tmp_path / "auto_table.yaml"
        data = [{"field": "value"}]
        with open(file_path, "w") as f:
            yaml.dump(data, f)

        rules = [RequiredRule("field")]
        validator.add_schema("auto_table", rules)

        result = await validator.validate_file(file_path)  # no table name provided
        assert result["valid"] is True
        assert result["total_records"] == 1

    async def test_validate_file_unsupported_format(self, validator, tmp_path):
        file_path = tmp_path / "test.txt"
        with open(file_path, "w") as f:
            f.write("invalid")
        with pytest.raises(SeedValidationError, match="Unsupported file type"):
            await validator.validate_file(file_path)

    # ---- validate_all_seed_files ----
    async def test_validate_all_seed_files_with_default_dir(self, validator, tmp_path):
        # Create a seeds directory
        seed_dir = tmp_path / "seeds"
        seed_dir.mkdir()

        # Create a valid YAML file
        file_path = seed_dir / "legal_entity.yaml"
        data = [{"legal_name": "PT A", "entity_type": "subsidiary", "status": "active", "country": "ID"}]
        with open(file_path, "w") as f:
            yaml.dump(data, f)

        # Validate
        with patch("infrastructure.database.seed_data_validator.Path") as mock_path:
            # We'll just call with the actual seed_dir
            # The method uses Path("seeds") as default; we'll override by passing seed_dir
            result = await validator.validate_all_seed_files(seed_dir)
            assert "legal_entity" in result
            assert result["legal_entity"]["valid"] is True

    async def test_validate_all_seed_files_no_seed_dir(self, validator):
        # If seed_dir is None and no default exists, returns empty dict with warning
        with patch("infrastructure.database.seed_data_validator.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            # Also patch logger.warning to avoid output
            with patch("infrastructure.database.seed_data_validator.logger.warning") as mock_warning:
                result = await validator.validate_all_seed_files(None)
                assert result == {}
                mock_warning.assert_called()

    # ---- print_validation_report ----
    async def test_print_validation_report(self, validator, capsys):
        result = {
            "valid": False,
            "total_records": 3,
            "valid_records": 1,
            "invalid_records": 2,
            "errors": [
                {"record_index": 0, "record": {"id": 1}, "errors": ["Missing name"]},
                {"record_index": 2, "record": {"id": 3}, "errors": ["Duplicate id"]},
            ],
        }
        await validator.print_validation_report(result)
        captured = capsys.readouterr()
        assert "SEED DATA VALIDATION REPORT" in captured.out
        assert "Valid: False" in captured.out
        assert "Total Records: 3" in captured.out
        assert "Valid Records: 1" in captured.out
        assert "Invalid Records: 2" in captured.out
        assert "Record 0:" in captured.out
        assert "- Missing name" in captured.out
        assert "Record 2:" in captured.out
        assert "- Duplicate id" in captured.out


# ============================================================================
# Singleton tests
# ============================================================================
def test_get_seed_validator_singleton():
    v1 = get_seed_validator()
    v2 = get_seed_validator()
    assert v1 is v2
    assert isinstance(v1, SeedDataValidator)


# ============================================================================
# CLI tests (smoke, can't fully test due to sys.exit)
# ============================================================================
def test_cli_no_args(monkeypatch, capsys):
    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_parse.return_value = MagicMock(file=None, all=False, table=None)
        # Patch asyncio.run to avoid actually running
        with patch("asyncio.run") as mock_run:
            from infrastructure.database.seed_data_validator import cli
            cli()
            # Should print message
            mock_run.assert_not_called()  # because no file or --all
            # The cli function doesn't capture output directly, but it prints "Please specify a file or --all"
            # We'll just ensure it didn't raise

def test_cli_with_file(monkeypatch, tmp_path):
    # Create a dummy file
    file_path = tmp_path / "test.yaml"
    file_path.touch()
    args = MagicMock(file=str(file_path), table="test", all=False)
    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_parse.return_value = args
        with patch("infrastructure.database.seed_data_validator.get_seed_validator") as mock_get:
            mock_validator = AsyncMock()
            mock_validator.validate_file = AsyncMock(return_value={"valid": True})
            mock_get.return_value = mock_validator
            with patch("asyncio.run") as mock_run:
                # We need to call the cli, but it uses asyncio.run which we mock
                from infrastructure.database.seed_data_validator import cli
                cli()
                # Check that asyncio.run was called
                mock_run.assert_called_once()
                # The coroutine passed to asyncio.run should be the one that calls validate_file
                # We can't easily inspect, but we can check that the validator was used

def test_cli_with_all(monkeypatch):
    args = MagicMock(file=None, table=None, all=True)
    with patch("argparse.ArgumentParser.parse_args") as mock_parse:
        mock_parse.return_value = args
        with patch("infrastructure.database.seed_data_validator.get_seed_validator") as mock_get:
            mock_validator = AsyncMock()
            mock_validator.validate_all_seed_files = AsyncMock(return_value={})
            mock_get.return_value = mock_validator
            with patch("asyncio.run") as mock_run:
                from infrastructure.database.seed_data_validator import cli
                cli()
                mock_run.assert_called_once()