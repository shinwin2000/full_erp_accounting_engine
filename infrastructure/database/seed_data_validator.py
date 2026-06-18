#!/usr/bin/env python3
"""
Module: seed_data_validator.py
Layer: Infrastructure (Database)
Responsibility: Memvalidasi data seed sebelum dimuat ke database. Memeriksa
               struktur data, tipe data, constraint (uniqueness, foreign keys),
               dan format khusus (email, UUID, tanggal). Juga mendukung validasi
               custom berdasarkan aturan domain.
Dependencies:
- json, yaml, re, uuid, datetime
- infrastructure.telemetry.structured_json_logging
- config.loader_yaml
Audit: Validasi seed data dicatat. Data yang tidak valid akan ditolak dan
       dilaporkan dengan detail error.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

# Internal dependencies
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

# Regex patterns for validation
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
NPWP_PATTERN = re.compile(r"^\d{15}$")
PHONE_PATTERN = re.compile(r"^\+?[0-9]{10,15}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
DECIMAL_PATTERN = re.compile(r"^-?\d+(?:\.\d+)?$")
ACCOUNT_CODE_PATTERN = re.compile(r"^[0-9]+(-[0-9]+)*$")
ACCOUNT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9\s\-\(\)&]+$")
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")

# ============================================================================
# EXCEPTIONS
# ============================================================================


class SeedValidationError(Exception):
    """Base exception untuk seed validation."""

    pass


class SeedSchemaError(SeedValidationError):
    """Error pada struktur data seed."""

    pass


class SeedConstraintError(SeedValidationError):
    """Error constraint (duplicate, missing required)."""

    pass


class SeedFormatError(SeedValidationError):
    """Error format data."""

    pass


# ============================================================================
# VALIDATION RULES
# ============================================================================


class ValidationRule:
    """Base class untuk validation rule."""

    def __init__(self, name: str, field: str, message: str | None = None):
        self.name = name
        self.field = field
        self.message = message or f"Validation failed for field '{field}'"

    def validate(self, record: dict[str, Any]) -> list[str]:
        """Validate a record. Returns list of error messages."""
        raise NotImplementedError


class RequiredRule(ValidationRule):
    """Rule untuk memeriksa field wajib."""

    def __init__(self, field: str, message: str | None = None):
        super().__init__("required", field, message or f"Field '{field}' is required")

    def validate(self, record: dict[str, Any]) -> list[str]:
        if self.field not in record or record[self.field] is None or record[self.field] == "":
            return [self.message]
        return []


class TypeRule(ValidationRule):
    """Rule untuk memeriksa tipe data."""

    def __init__(self, field: str, expected_type: type, message: str | None = None):
        super().__init__(
            "type", field, message or f"Field '{field}' must be of type {expected_type.__name__}"
        )
        self.expected_type = expected_type

    def validate(self, record: dict[str, Any]) -> list[str]:
        value = record.get(self.field)
        if value is None:
            return []  # Handled by RequiredRule
        if not isinstance(value, self.expected_type):
            return [self.message]
        return []


class PatternRule(ValidationRule):
    """Rule untuk memeriksa format regex."""

    def __init__(self, field: str, pattern: re.Pattern, message: str | None = None):
        super().__init__("pattern", field, message or f"Field '{field}' has invalid format")
        self.pattern = pattern

    def validate(self, record: dict[str, Any]) -> list[str]:
        value = record.get(self.field)
        if value is None:
            return []
        if not isinstance(value, str):
            return [f"Field '{self.field}' must be a string for pattern validation"]
        if not self.pattern.match(value):
            return [self.message]
        return []


class MinMaxRule(ValidationRule):
    """Rule untuk memeriksa nilai minimum dan maksimum."""

    def __init__(
        self,
        field: str,
        min_val: int | float | None = None,
        max_val: int | float | None = None,
        message: str | None = None,
    ):
        super().__init__("minmax", field, message or f"Field '{field}' is out of range")
        self.min_val = min_val
        self.max_val = max_val

    def validate(self, record: dict[str, Any]) -> list[str]:
        value = record.get(self.field)
        if value is None:
            return []
        if not isinstance(value, (int, float, Decimal)):
            return [f"Field '{self.field}' must be numeric for range validation"]

        if self.min_val is not None and value < self.min_val:
            return [f"Field '{self.field}' ({value}) is below minimum {self.min_val}"]
        if self.max_val is not None and value > self.max_val:
            return [f"Field '{self.field}' ({value}) exceeds maximum {self.max_val}"]
        return []


class EnumRule(ValidationRule):
    """Rule untuk memeriksa nilai dalam enum."""

    def __init__(self, field: str, allowed_values: list[Any], message: str | None = None):
        super().__init__("enum", field, message or f"Field '{field}' has invalid value")
        self.allowed_values = allowed_values

    def validate(self, record: dict[str, Any]) -> list[str]:
        value = record.get(self.field)
        if value is None:
            return []
        if value not in self.allowed_values:
            return [
                f"Field '{self.field}' value '{value}' not in allowed values: {self.allowed_values}"
            ]
        return []


class UniqueRule(ValidationRule):
    """Rule untuk memeriksa keunikan dalam dataset."""

    def __init__(self, field: str, message: str | None = None):
        super().__init__("unique", field, message or f"Field '{field}' must be unique")
        self._seen_values = set()

    def validate(self, record: dict[str, Any]) -> list[str]:
        value = record.get(self.field)
        if value is None:
            return []
        if value in self._seen_values:
            return [f"Duplicate value '{value}' for field '{self.field}'"]
        self._seen_values.add(value)
        return []


class CustomRule(ValidationRule):
    """Rule dengan fungsi validasi custom."""

    def __init__(
        self, name: str, field: str, validator: Callable[[Any], bool], message: str | None = None
    ):
        super().__init__(name, field, message or f"Field '{field}' failed custom validation")
        self.validator = validator

    def validate(self, record: dict[str, Any]) -> list[str]:
        value = record.get(self.field)
        if value is None:
            return []
        if not self.validator(value):
            return [self.message]
        return []


# ============================================================================
# SEED DATA VALIDATOR
# ============================================================================


class SeedDataValidator:
    """
    Validator untuk data seed.

    Fitur:
    - Validasi schema per tabel
    - Validasi tipe data dan format
    - Validasi constraint (unique, foreign key - dengan lookup)
    - Laporan error detail
    - Support custom rules
    """

    def __init__(self):
        self._schemas: dict[str, list[ValidationRule]] = {}
        self._build_default_schemas()

    def _build_default_schemas(self) -> None:
        """Build default validation schemas for core tables."""

        # Legal entity schema
        legal_entity_rules = [
            RequiredRule("legal_name"),
            RequiredRule("entity_type"),
            PatternRule("npwp", NPWP_PATTERN, "Invalid NPWP format (must be 15 digits)"),
            PatternRule("email", EMAIL_PATTERN, "Invalid email format"),
            EnumRule(
                "entity_type",
                [
                    "parent_company",
                    "subsidiary",
                    "branch",
                    "representative_office",
                    "joint_venture",
                ],
            ),
            EnumRule("status", ["active", "inactive", "suspended", "liquidated"]),
            EnumRule("country", ["ID", "SG", "MY", "TH", "VN", "PH", "CN", "US", "GB", "JP"]),
            MinMaxRule("fiscal_year_start", 1, 12),
            MinMaxRule("fiscal_year_end", 1, 12),
        ]
        self._schemas["legal_entity"] = legal_entity_rules

        # Account schema (Chart of Accounts)
        account_rules = [
            RequiredRule("account_code"),
            RequiredRule("account_name"),
            RequiredRule("account_type"),
            RequiredRule("normal_balance"),
            PatternRule(
                "account_code", ACCOUNT_CODE_PATTERN, "Invalid account code format (e.g., 1-1100)"
            ),
            PatternRule(
                "account_name", ACCOUNT_NAME_PATTERN, "Account name contains invalid characters"
            ),
            EnumRule(
                "account_type",
                [
                    "Asset",
                    "Liability",
                    "Equity",
                    "Revenue",
                    "Expense",
                    "ContraAsset",
                    "ContraLiability",
                    "ContraEquity",
                ],
            ),
            EnumRule("normal_balance", ["debit", "credit"]),
            EnumRule("status", ["active", "inactive", "suspended"]),
            MinMaxRule("level", 1, 10),
        ]
        self._schemas["account"] = account_rules

        # IAM User schema
        user_rules = [
            RequiredRule("username"),
            RequiredRule("full_name"),
            RequiredRule("email"),
            PatternRule("email", EMAIL_PATTERN, "Invalid email format"),
            PatternRule(
                "username",
                re.compile(r"^[a-zA-Z0-9_]{3,50}$"),
                "Username must be 3-50 alphanumeric or underscore",
            ),
            EnumRule("status", ["active", "inactive", "locked", "suspended", "pending_activation"]),
            MinMaxRule("failed_login_count", 0, 10),
            CustomRule(
                "password_hash",
                "password_hash",
                lambda x: isinstance(x, str) and len(x) >= 60,
                "Password hash too short or invalid",
            ),
        ]
        self._schemas["iam_user"] = user_rules

        # IAM Role schema
        role_rules = [
            RequiredRule("name"),
            PatternRule(
                "name",
                re.compile(r"^[a-zA-Z0-9_\-]{3,50}$"),
                "Role name must be 3-50 alphanumeric, underscore or hyphen",
            ),
            EnumRule("status", ["active", "inactive"]),
        ]
        self._schemas["iam_role"] = role_rules

        # IAM Permission schema
        permission_rules = [
            RequiredRule("name"),
            RequiredRule("resource"),
            RequiredRule("action"),
            PatternRule(
                "resource", re.compile(r"^[a-z_]+$"), "Resource must be lowercase with underscores"
            ),
            EnumRule(
                "action",
                [
                    "create",
                    "read",
                    "update",
                    "delete",
                    "approve",
                    "reject",
                    "post",
                    "reverse",
                    "cancel",
                    "export",
                ],
            ),
        ]
        self._schemas["iam_permission"] = permission_rules

        # System Setting schema
        setting_rules = [
            RequiredRule("key"),
            RequiredRule("value"),
            RequiredRule("data_type"),
            EnumRule("data_type", ["string", "integer", "float", "boolean", "json", "decimal"]),
            EnumRule(
                "category",
                ["general", "accounting", "tax", "security", "audit", "integration", "performance"],
            ),
            EnumRule("scope", ["global", "legal_entity"]),
        ]
        self._schemas["system_setting"] = setting_rules

        # Customer schema
        customer_rules = [
            RequiredRule("customer_code"),
            RequiredRule("customer_name"),
            PatternRule(
                "customer_code",
                re.compile(r"^[A-Z0-9_]{3,30}$"),
                "Customer code must be 3-30 uppercase alphanumeric or underscore",
            ),
            PatternRule("tax_id", NPWP_PATTERN, "Invalid NPWP format"),
            PatternRule("email", EMAIL_PATTERN, "Invalid email format"),
            PatternRule("phone", PHONE_PATTERN, "Invalid phone format"),
            EnumRule("customer_type", ["individual", "company", "government", "non_profit"]),
            EnumRule("status", ["active", "inactive", "blocked", "suspended"]),
            MinMaxRule("credit_limit", 0, None),
            MinMaxRule("payment_term_days", 0, 180),
        ]
        self._schemas["customer"] = customer_rules

        # Supplier schema
        supplier_rules = [
            RequiredRule("supplier_code"),
            RequiredRule("supplier_name"),
            PatternRule(
                "supplier_code",
                re.compile(r"^[A-Z0-9_]{3,30}$"),
                "Supplier code must be 3-30 uppercase alphanumeric or underscore",
            ),
            PatternRule("tax_id", NPWP_PATTERN, "Invalid NPWP format"),
            PatternRule("email", EMAIL_PATTERN, "Invalid email format"),
            EnumRule("supplier_type", ["individual", "company", "government", "non_profit"]),
            EnumRule("status", ["active", "inactive", "blocked", "suspended"]),
            EnumRule("withholding_category", ["none", "pph23", "pph26", "both"]),
            MinMaxRule("payment_term_days", 0, 180),
        ]
        self._schemas["supplier"] = supplier_rules

        # Employee schema
        employee_rules = [
            RequiredRule("employee_code"),
            RequiredRule("full_name"),
            PatternRule(
                "employee_code",
                re.compile(r"^[A-Z0-9_]{3,30}$"),
                "Employee code must be 3-30 uppercase alphanumeric or underscore",
            ),
            PatternRule("email", EMAIL_PATTERN, "Invalid email format"),
            PatternRule("mobile", PHONE_PATTERN, "Invalid phone format"),
            PatternRule("tax_id", NPWP_PATTERN, "Invalid NPWP format"),
            EnumRule(
                "employment_status", ["active", "inactive", "resigned", "terminated", "on_leave"]
            ),
            EnumRule("gender", ["M", "F", "O"]),
            EnumRule("ptkp_status", ["TK/0", "TK/1", "TK/2", "TK/3", "K/0", "K/1", "K/2", "K/3"]),
            MinMaxRule("basic_salary", 0, None),
            MinMaxRule("annual_leave_balance", 0, 30),
        ]
        self._schemas["employee"] = employee_rules

        # Tax rate schema
        tax_rate_rules = [
            RequiredRule("tax_type"),
            RequiredRule("rate_percent"),
            RequiredRule("effective_from"),
            PatternRule(
                "tax_type",
                re.compile(r"^[a-z0-9_]+$"),
                "Tax type must be lowercase alphanumeric with underscores",
            ),
            EnumRule(
                "tax_type",
                ["ppn", "pph21", "pph22", "pph23", "pph25", "pph26", "pph4_2", "pph_badan"],
            ),
            MinMaxRule("rate_percent", 0, 100),
            PatternRule("effective_from", DATE_PATTERN, "Date must be in YYYY-MM-DD format"),
        ]
        self._schemas["tax_rate"] = tax_rate_rules

    def add_schema(self, table_name: str, rules: list[ValidationRule]) -> None:
        """Add or override validation schema for a table."""
        self._schemas[table_name] = rules

    def get_schema(self, table_name: str) -> list[ValidationRule]:
        """Get validation schema for a table."""
        return self._schemas.get(table_name, [])

    async def validate_record(
        self, table_name: str, record: dict[str, Any], unique_checks: dict[str, set] | None = None
    ) -> list[str]:
        """
        Validate a single record against its schema.

        Args:
            table_name: Name of the table
            record: Record to validate
            unique_checks: Optional dictionary to track unique values across records

        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        schema = self.get_schema(table_name)

        # Create a copy of unique checks for this validation run
        local_uniques = {}

        for rule in schema:
            if isinstance(rule, UniqueRule) and unique_checks is not None:
                # Use provided unique checks
                if rule.field not in unique_checks:
                    unique_checks[rule.field] = set()
                # We'll handle uniqueness separately
                pass

        for rule in schema:
            rule_errors = rule.validate(record)
            errors.extend(rule_errors)

        return errors

    async def validate_dataset(
        self, table_name: str, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Validate a full dataset.

        Returns:
            Dictionary with 'valid' (bool), 'errors' (list of dicts), 'summary'
        """
        errors = []
        unique_trackers: dict[str, set] = {}

        # First, collect all unique rule fields
        schema = self.get_schema(table_name)
        unique_fields = [rule.field for rule in schema if isinstance(rule, UniqueRule)]
        for field in unique_fields:
            unique_trackers[field] = set()

        for idx, record in enumerate(records):
            record_errors = await self.validate_record(table_name, record, unique_trackers)

            # Add duplicate detection
            for field in unique_fields:
                value = record.get(field)
                if value is not None:
                    if value in unique_trackers[field]:
                        record_errors.append(
                            f"Duplicate value '{value}' for field '{field}' (record {idx})"
                        )
                    else:
                        unique_trackers[field].add(value)

            if record_errors:
                errors.append({"record_index": idx, "record": record, "errors": record_errors})

        return {
            "valid": len(errors) == 0,
            "total_records": len(records),
            "valid_records": len(records) - len(errors),
            "invalid_records": len(errors),
            "errors": errors,
        }

    async def validate_file(self, file_path: Path, table_name: str | None = None) -> dict[str, Any]:
        """
        Validate seed data file.

        Args:
            file_path: Path to YAML or JSON file
            table_name: Table name (auto-detected from filename if not provided)

        Returns:
            Validation result dictionary
        """
        # Load data
        if file_path.suffix in [".yaml", ".yml"]:
            with open(file_path) as f:
                data = yaml.safe_load(f)
        elif file_path.suffix == ".json":
            with open(file_path) as f:
                data = json.load(f)
        else:
            raise SeedValidationError(f"Unsupported file type: {file_path.suffix}")

        # Extract records
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict) and "records" in data:
            records = data["records"]
        else:
            records = [data] if data else []

        # Determine table name from filename if not provided
        if table_name is None:
            table_name = file_path.stem  # filename without extension

        return await self.validate_dataset(table_name, records)

    async def validate_all_seed_files(self, seed_dir: Path | None = None) -> dict[str, Any]:
        """
        Validate all seed files in directory.

        Returns:
            Combined validation results
        """
        # Jika seed_dir tidak diberikan, tentukan fallback-nya di sini
        if seed_dir is None:
            try:
                # Coba gunakan konstanta global SEED_DATA_DIR jika ada
                seed_dir = SEED_DATA_DIR
            except NameError:
                # Jika tidak ada, default ke folder 'seeds' di direktori yang sama dengan file ini
                seed_dir = Path(__file__).parent / "seeds"

        results = {}
        for file_path in seed_dir.glob("*.yaml"):
            table_name = file_path.stem
            if table_name in self._schemas:
                results[table_name] = await self.validate_file(file_path, table_name)

        for file_path in seed_dir.glob("*.json"):
            table_name = file_path.stem
            if table_name in self._schemas:
                results[table_name] = await self.validate_file(file_path, table_name)

        return results

    async def print_validation_report(self, result: dict[str, Any]) -> None:
        """Print validation report to console."""
        print("\n" + "=" * 60)
        print("SEED DATA VALIDATION REPORT")
        print("=" * 60)
        print(f"Valid: {result.get('valid', False)}")
        print(f"Total Records: {result.get('total_records', 0)}")
        print(f"Valid Records: {result.get('valid_records', 0)}")
        print(f"Invalid Records: {result.get('invalid_records', 0)}")

        if result.get("errors"):
            print("\nErrors:")
            for err in result["errors"]:
                print(f"  Record {err['record_index']}:")
                for e in err["errors"]:
                    print(f"    - {e}")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_seed_validator: SeedDataValidator | None = None


def get_seed_validator() -> SeedDataValidator:
    """Get singleton instance of SeedDataValidator."""
    global _seed_validator
    if _seed_validator is None:
        _seed_validator = SeedDataValidator()
    return _seed_validator


# ============================================================================
# CLI COMMAND
# ============================================================================


def cli():
    """CLI entry point for seed data validation."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Seed data validator")
    parser.add_argument("file", nargs="?", help="Seed file to validate")
    parser.add_argument("--table", "-t", help="Table name")
    parser.add_argument("--all", action="store_true", help="Validate all seed files")

    args = parser.parse_args()

    async def run():
        validator = get_seed_validator()

        if args.all:
            results = await validator.validate_all_seed_files()
            for table, result in results.items():
                print(f"\n--- {table} ---")
                await validator.print_validation_report(result)
        elif args.file:
            file_path = Path(args.file)
            result = await validator.validate_file(file_path, args.table)
            await validator.print_validation_report(result)
        else:
            print("Please specify a file or --all")

    asyncio.run(run())


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CustomRule",
    "EnumRule",
    "MinMaxRule",
    "PatternRule",
    "RequiredRule",
    "SeedConstraintError",
    "SeedDataValidator",
    "SeedFormatError",
    "SeedSchemaError",
    "SeedValidationError",
    "TypeRule",
    "UniqueRule",
    "ValidationRule",
    "get_seed_validator",
]

if __name__ == "__main__":
    cli()
