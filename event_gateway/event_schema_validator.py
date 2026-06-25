#!/usr/bin/env python3
"""
Module: event_schema_validator.py
Layer: Event Gateway
Responsibility: Memvalidasi event yang masuk ke Event Gate terhadap skema.

Metode yang ditambahkan:
- validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import importlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema
from jsonschema import ValidationError as JSONSchemaValidationError

if TYPE_CHECKING:
    from event_gateway.event_envelope import EventEnvelope

logger = logging.getLogger(__name__)

SCHEMA_CACHE_PREFIX = "event_schema:"
SCHEMA_CACHE_TTL = 3600  # 1 hour
SCHEMA_DIR = Path("config_files/event_schemas")

# Built-in schemas for common event types
BUILTIN_SCHEMAS = {
    "JournalPosted": {
        "type": "object",
        "required": [
            "journal_id",
            "voucher_number",
            "journal_date",
            "total_debit",
            "total_credit",
            "posted_by",
        ],
        "properties": {
            "journal_id": {
                "type": "string",
                "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            },
            "voucher_number": {"type": "string", "minLength": 3, "maxLength": 50},
            "journal_date": {"type": "string", "format": "date"},
            "description": {"type": "string", "maxLength": 500},
            "total_debit": {"type": "number", "minimum": 0},
            "total_credit": {"type": "number", "minimum": 0},
            "posted_by": {
                "type": "string",
                "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            },
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["account_code", "debit_amount", "credit_amount"],
                    "properties": {
                        "account_code": {"type": "string", "minLength": 3, "maxLength": 20},
                        "debit_amount": {"type": "number", "minimum": 0},
                        "credit_amount": {"type": "number", "minimum": 0},
                    },
                },
            },
        },
    },
    "ARInvoiceCreated": {
        "type": "object",
        "required": ["invoice_id", "invoice_number", "customer_id", "total_amount", "invoice_date"],
        "properties": {
            "invoice_id": {
                "type": "string",
                "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            },
            "invoice_number": {"type": "string", "minLength": 3, "maxLength": 50},
            "customer_id": {
                "type": "string",
                "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            },
            "customer_name": {"type": "string", "maxLength": 200},
            "total_amount": {"type": "number", "minimum": 0},
            "invoice_date": {"type": "string", "format": "date"},
            "due_date": {"type": "string", "format": "date"},
        },
    },
    "APInvoiceCreated": {
        "type": "object",
        "required": [
            "invoice_id",
            "invoice_number",
            "vendor_id",
            "total_amount",
            "invoice_date",
            "due_date",
        ],
        "properties": {
            "invoice_id": {
                "type": "string",
                "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            },
            "invoice_number": {"type": "string", "minLength": 3, "maxLength": 50},
            "vendor_id": {
                "type": "string",
                "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            },
            "total_amount": {"type": "number", "minimum": 0},
            "invoice_date": {"type": "string", "format": "date"},
            "due_date": {"type": "string", "format": "date"},
        },
    },
    "PaymentReceived": {
        "type": "object",
        "required": ["payment_id", "invoice_id", "amount", "payment_date", "payment_method"],
        "properties": {
            "payment_id": {
                "type": "string",
                "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            },
            "invoice_id": {
                "type": "string",
                "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            },
            "amount": {"type": "number", "minimum": 0},
            "payment_date": {"type": "string", "format": "date"},
            "payment_method": {
                "type": "string",
                "enum": ["cash", "transfer", "credit_card", "giro", "other"],
            },
        },
    },
    "PeriodClosed": {
        "type": "object",
        "required": ["period_id", "fiscal_year", "period", "closed_by", "closed_at"],
        "properties": {
            "period_id": {
                "type": "string",
                "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            },
            "fiscal_year": {"type": "integer", "minimum": 2000, "maximum": 2100},
            "period": {"type": "integer", "minimum": 1, "maximum": 13},
            "closed_by": {
                "type": "string",
                "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            },
            "closed_at": {"type": "string", "format": "date-time"},
        },
    },
}


class SchemaValidationError(Exception):
    pass


class SchemaNotFoundError(SchemaValidationError):
    pass


class SchemaLoadError(Exception):
    pass


class EventSchemaValidator:
    def __init__(self):
        self._schema_cache: dict[str, dict[str, Any]] = {}
        self._redis = None
        self._load_builtin_schemas()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "cache_size": len(self._schema_cache),
                "timestamp": datetime.now().isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now().isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def _load_builtin_schemas(self) -> None:
        for event_type, schema in BUILTIN_SCHEMAS.items():
            self._schema_cache[event_type] = schema
        logger.info(f"Loaded {len(BUILTIN_SCHEMAS)} built-in event schemas")

    def _get_load_yaml_config(self):
        """Lazy import of config.loader_yaml.load_yaml_config."""
        mod = importlib.import_module("config.loader_yaml")
        return getattr(mod, "load_yaml_config")

    def _get_redis_client(self):
        """Lazy import of infrastructure.caching.redis_manager.get_redis_client."""
        mod = importlib.import_module("infrastructure.caching.redis_manager")
        return getattr(mod, "get_redis_client")

    async def _get_redis(self):
        if self._redis is None:
            get_redis = self._get_redis_client()
            self._redis = await get_redis()
        return self._redis

    async def _load_schema_from_file(self, event_type: str) -> dict[str, Any] | None:
        schema_path = SCHEMA_DIR / f"{event_type}.yaml"
        if not schema_path.exists():
            return None
        try:
            load_yaml_config = self._get_load_yaml_config()
            schema = load_yaml_config(str(schema_path))
            if "schema" in schema:
                return schema["schema"]
            return schema
        except Exception as e:
            logger.error(f"Failed to load schema for {event_type}: {e}")
            raise SchemaLoadError(f"Cannot load schema for {event_type}: {e}")

    async def _load_schema_from_redis(self, event_type: str) -> dict[str, Any] | None:
        try:
            redis = await self._get_redis()
            key = f"{SCHEMA_CACHE_PREFIX}{event_type}"
            cached = await redis.get(key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Failed to load schema from Redis: {e}")
        return None

    async def _cache_schema(self, event_type: str, schema: dict[str, Any]) -> None:
        try:
            redis = await self._get_redis()
            key = f"{SCHEMA_CACHE_PREFIX}{event_type}"
            await redis.setex(key, SCHEMA_CACHE_TTL, json.dumps(schema))
        except Exception as e:
            logger.warning(f"Failed to cache schema: {e}")

    async def get_schema(self, event_type: str) -> dict[str, Any] | None:
        if event_type in self._schema_cache:
            return self._schema_cache[event_type]

        schema = await self._load_schema_from_redis(event_type)
        if schema:
            self._schema_cache[event_type] = schema
            return schema

        schema = await self._load_schema_from_file(event_type)
        if schema:
            self._schema_cache[event_type] = schema
            await self._cache_schema(event_type, schema)
            return schema
        return None

    def _validate_date_format(self, value: str, format_type: str) -> bool:
        if format_type == "date":
            try:
                datetime.strptime(value, "%Y-%m-%d")
                return True
            except ValueError:
                return False
        elif format_type == "date-time":
            try:
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
                return True
            except ValueError:
                try:
                    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
                    return True
                except ValueError:
                    return False
        return True

    def _validate_custom_formats(
        self, payload: dict[str, Any], schema: dict[str, Any]
    ) -> list[str]:
        errors = []

        def validate_recursive(obj, sch, path=""):
            if not isinstance(obj, dict) or not isinstance(sch, dict):
                return
            properties = sch.get("properties", {})
            for prop_name, prop_schema in properties.items():
                if prop_name not in obj:
                    if prop_name in sch.get("required", []):
                        errors.append(f"{path}{prop_name}: required field missing")
                    continue
                prop_value = obj[prop_name]
                prop_path = f"{path}{prop_name}."
                prop_format = prop_schema.get("format")
                if prop_format and isinstance(prop_value, str):
                    if not self._validate_date_format(prop_value, prop_format):
                        errors.append(f"{prop_path} invalid {prop_format} format: {prop_value}")
                pattern = prop_schema.get("pattern")
                if pattern and isinstance(prop_value, str):
                    if not re.match(pattern, prop_value):
                        errors.append(f"{prop_path} does not match pattern {pattern}")
                enum_values = prop_schema.get("enum")
                if enum_values and prop_value not in enum_values:
                    errors.append(f"{prop_path} value {prop_value} not in enum {enum_values}")
                if isinstance(prop_value, (int, float)):
                    minimum = prop_schema.get("minimum")
                    if minimum is not None and prop_value < minimum:
                        errors.append(f"{prop_path} value {prop_value} is below minimum {minimum}")
                    maximum = prop_schema.get("maximum")
                    if maximum is not None and prop_value > maximum:
                        errors.append(f"{prop_path} value {prop_value} is above maximum {maximum}")
                if prop_schema.get("type") == "object" and isinstance(prop_value, dict):
                    validate_recursive(prop_value, prop_schema, prop_path)
                elif prop_schema.get("type") == "array" and isinstance(prop_value, list):
                    items_schema = prop_schema.get("items", {})
                    for i, item in enumerate(prop_value):
                        if isinstance(item, dict):
                            validate_recursive(item, items_schema, f"{prop_path}[{i}].")

        validate_recursive(payload, schema)
        return errors

    async def validate(self, envelope: EventEnvelope) -> None:
        schema = await self.get_schema(envelope.event_type)
        if schema is None:
            logger.warning(f"No schema found for event type: {envelope.event_type}")
            return
        try:
            jsonschema.validate(instance=envelope.payload, schema=schema)
            custom_errors = self._validate_custom_formats(envelope.payload, schema)
            if custom_errors:
                raise SchemaValidationError(
                    f"Custom validation failed for {envelope.event_type}", errors=custom_errors
                )
            logger.debug(f"Event {envelope.event_type} validated successfully")
        except JSONSchemaValidationError as e:
            error_message = f"Schema validation failed for {envelope.event_type}: {e.message}"
            logger.error(error_message)
            raise SchemaValidationError(error_message, errors=[str(e)])
        except SchemaValidationError:
            raise

    async def register_schema(self, event_type: str, schema: dict[str, Any]) -> None:
        try:
            jsonschema.Draft7Validator.check_schema(schema)
        except JSONSchemaValidationError as e:
            raise SchemaValidationError(f"Invalid schema definition: {e}")
        self._schema_cache[event_type] = schema
        await self._cache_schema(event_type, schema)
        self._record_audit("REGISTER_SCHEMA", "system", {"event_type": event_type})
        logger.info(f"Schema registered for event type: {event_type}")

    async def reload_schemas(self) -> None:
        self._schema_cache.clear()
        self._load_builtin_schemas()
        if SCHEMA_DIR.exists():
            for schema_file in SCHEMA_DIR.glob("*.yaml"):
                event_type = schema_file.stem
                try:
                    schema = await self._load_schema_from_file(event_type)
                    if schema:
                        self._schema_cache[event_type] = schema
                        await self._cache_schema(event_type, schema)
                except Exception as e:
                    logger.error(f"Failed to load schema from {schema_file}: {e}")
        self._record_audit("RELOAD_SCHEMAS", "system", {})
        logger.info(f"Schemas reloaded. Total: {len(self._schema_cache)}")

    # ==================== ENTITY DASAR METHODS ====================
    def validate_self(self) -> dict[str, Any]:
        errors = []
        if self._version < 1:
            errors.append("Version must be >= 1")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_size": len(self._schema_cache),
            "event_types": list(self._schema_cache.keys()),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventSchemaValidator:
        instance = cls()
        instance._version = data.get("version", 1)
        # Note: cache tidak dapat dipulihkan dari dict
        return instance

    def clone(self) -> EventSchemaValidator:
        new = EventSchemaValidator()
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "cache_size": len(self._schema_cache),
            "timestamp": datetime.now().isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EventSchemaValidator:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


__all__ = [
    "EventSchemaValidator",
    "SchemaLoadError",
    "SchemaNotFoundError",
    "SchemaValidationError",
]