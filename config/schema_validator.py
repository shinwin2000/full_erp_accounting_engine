#!/usr/bin/env python3
"""
Module: schema_validator.py
Layer: 3 - Bootstrap & Config / Configuration
Responsibility: Validasi skema konfigurasi menggunakan Pydantic (dengan fallback ke dict validation).
               Menjamin bahwa konfigurasi yang dimuat memenuhi struktur, tipe data,
               dan aturan bisnis yang dipersyaratkan sebelum digunakan.

Metode yang ditambahkan:
- Untuk SchemaValidator: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk PydanticSchemaValidator: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk convenience functions: tetap dipertahankan.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# === 1. CONSTANTS ===
CONFIG_SCHEMA: dict[str, tuple[type, bool, Callable | None]] = {
    "system.version": (str, True, None),
    "system.environment": (str, True, lambda v: v in ["development", "staging", "production"]),
    "system.debug": (bool, False, None),
    "database.host": (str, True, None),
    "database.port": (int, True, lambda v: 1 <= v <= 65535),
    "database.name": (str, True, None),
    "database.user": (str, True, None),
    "database.password": (str, True, None),
    "database.pool_min_size": (int, False, lambda v: v >= 0),
    "database.pool_max_size": (int, False, lambda v: v >= 1),
    "database.ssl_mode": (
        str,
        False,
        lambda v: v in ["disable", "require", "verify-ca", "verify-full"],
    ),
    "kafka.bootstrap_servers": (str, False, None),
    "kafka.group_id": (str, False, None),
    "kafka.topic_prefix": (str, False, None),
    "redis.host": (str, False, None),
    "redis.port": (int, False, lambda v: 1 <= v <= 65535),
    "redis.db": (int, False, lambda v: 0 <= v <= 15),
    "security.jwt_secret": (str, True, lambda v: len(v) >= 32),
    "security.jwt_expiry_minutes": (int, False, lambda v: v > 0),
    "security.encryption_key": (str, True, lambda v: len(v) >= 32),
    "security.allow_http": (bool, False, None),
    "api.host": (str, False, None),
    "api.port": (int, True, lambda v: 1 <= v <= 65535),
    "api.workers": (int, False, lambda v: v >= 1),
    "api.cors_origins": (list, False, None),
    "logging.level": (str, True, lambda v: v in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
    "logging.format": (str, False, None),
    "logging.file": (str, False, None),
    "audit.immutable_store_path": (str, True, None),
    "audit.retention_days": (int, True, lambda v: v >= 1),
    "audit.hash_algorithm": (str, False, lambda v: v in ["sha256", "sha3-256"]),
    "coretax.base_url": (str, True, None),
    "coretax.client_id": (str, True, None),
    "coretax.client_secret": (str, True, None),
    "coretax.timeout_seconds": (int, False, lambda v: v >= 1),
    "coretax.retry_count": (int, False, lambda v: v >= 0),
    "features.enable_manufacturing": (bool, False, None),
    "features.enable_coretax": (bool, False, None),
    "features.enable_consolidation": (bool, False, None),
    "features.enable_forex": (bool, False, None),
}


# === 2. SchemaValidator (dengan entity dasar) ===
class SchemaValidator:
    _instance: SchemaValidator | None = None
    _schema: dict[str, tuple[type, bool, Callable | None]]
    _version: int
    _audit_trail: list[dict[str, Any]]
    _snapshots: list[dict[str, Any]]
    _validator_id: str

    def __new__(cls) -> SchemaValidator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._schema = CONFIG_SCHEMA.copy()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._validator_id = str(uuid4())
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "validator_id": self._validator_id,
                "rules_count": len(self._schema),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "validator_id": self._validator_id,
                "details": details,
            }
        )

    # ==================== VALIDATION METHODS ====================
    def validate_config(self, config: dict[str, Any]) -> tuple[bool, dict[str, str]]:
        errors = {}
        for field_path, (expected_type, required, validator) in self._schema.items():
            value = self._get_nested_value(config, field_path)
            if required and value is None:
                errors[field_path] = "Required field missing"
                continue
            if value is None:
                continue
            if not self._check_type(value, expected_type):
                errors[field_path] = (
                    f"Expected type {expected_type.__name__}, got {type(value).__name__}"
                )
                continue
            if validator:
                try:
                    if not validator(value):
                        errors[field_path] = "Custom validation failed"
                except Exception as e:
                    errors[field_path] = f"Validator error: {e}"
        cross_errors = self._validate_cross_fields(config)
        errors.update(cross_errors)
        self._record_audit("VALIDATE_CONFIG", "system", {"is_valid": len(errors) == 0})
        return len(errors) == 0, errors

    def _get_nested_value(self, config: dict[str, Any], path: str) -> Any:
        keys = path.split(".")
        value = config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return None
            else:
                return None
        return value

    def _check_type(self, value: Any, expected_type: type) -> bool:
        if expected_type == list:
            return isinstance(value, list)
        elif expected_type == dict:
            return isinstance(value, dict)
        elif expected_type == str:
            return isinstance(value, str)
        elif expected_type == int:
            return isinstance(value, int) and not isinstance(value, bool)
        elif expected_type == bool:
            return isinstance(value, bool)
        elif expected_type == float:
            return isinstance(value, (int, float))
        else:
            return isinstance(value, expected_type)

    def _validate_cross_fields(self, config: dict[str, Any]) -> dict[str, str]:
        errors = {}
        ssl_mode = self._get_nested_value(config, "database.ssl_mode")
        if ssl_mode in ["verify-ca", "verify-full"]:
            ca_cert = self._get_nested_value(config, "database.ssl_ca")
            if not ca_cert:
                errors["database.ssl_ca"] = f"Required when ssl_mode is {ssl_mode}"
        env = self._get_nested_value(config, "system.environment")
        if env == "production":
            debug = self._get_nested_value(config, "system.debug")
            if debug is True:
                errors["system.debug"] = "Debug mode cannot be enabled in production"
            jwt_secret = self._get_nested_value(config, "security.jwt_secret")
            if jwt_secret and len(jwt_secret) < 32:
                errors["security.jwt_secret"] = "Must be at least 32 characters in production"
        return errors

    def validate_single_field(self, field_path: str, value: Any) -> tuple[bool, str | None]:
        if field_path not in self._schema:
            return True, None
        expected_type, required, validator = self._schema[field_path]
        if value is None:
            if required:
                return False, "Required field missing"
            return True, None
        if not self._check_type(value, expected_type):
            return False, f"Expected type {expected_type.__name__}, got {type(value).__name__}"
        if validator:
            try:
                if not validator(value):
                    return False, "Custom validation failed"
            except Exception as e:
                return False, f"Validator error: {e}"
        return True, None

    def add_rule(
        self,
        field_path: str,
        expected_type: type,
        required: bool,
        validator: Callable | None = None,
    ) -> None:
        self._schema[field_path] = (expected_type, required, validator)
        self._record_audit("ADD_RULE", "system", {"field_path": field_path})
        logger.info(f"Added validation rule for {field_path}")

    def remove_rule(self, field_path: str) -> bool:
        if field_path in self._schema:
            del self._schema[field_path]
            self._record_audit("REMOVE_RULE", "system", {"field_path": field_path})
            logger.info(f"Removed validation rule for {field_path}")
            return True
        return False

    def get_schema(self) -> dict[str, tuple[type, bool, Callable | None]]:
        return self._schema.copy()

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        for field_path, (exp_type, required, validator) in self._schema.items():
            if not field_path:
                errors.append("Empty field path in schema")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "validator_id": self._validator_id,
            "rules_count": len(self._schema),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SchemaValidator:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._validator_id = data.get("validator_id", str(uuid4()))
        return instance

    def clone(self) -> SchemaValidator:
        new = SchemaValidator()
        new._schema = self._schema.copy()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._validator_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "validator_id": self._validator_id,
            "rules_count": len(self._schema),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SchemaValidator:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._schema = CONFIG_SCHEMA.copy()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._validator_id = str(uuid4())
        self._record_audit("RESET", "system", {})


# === 3. PYDANTIC SCHEMA VALIDATOR (dengan entity dasar) ===
try:
    from pydantic import BaseModel, Field, ValidationError, create_model

    class DatabaseConfig(BaseModel):
        host: str
        port: int = Field(ge=1, le=65535)
        name: str
        user: str
        password: str
        pool_min_size: int = Field(default=1, ge=0)
        pool_max_size: int = Field(default=10, ge=1)
        ssl_mode: str = Field(default="disable")

    class SecurityConfig(BaseModel):
        jwt_secret: str = Field(min_length=32)
        jwt_expiry_minutes: int = Field(default=60, gt=0)
        encryption_key: str = Field(min_length=32)
        allow_http: bool = False

    class APIConfig(BaseModel):
        host: str = "0.0.0.0"
        port: int = Field(default=8000, ge=1, le=65535)
        workers: int = Field(default=1, ge=1)
        cors_origins: list[str] = Field(default_factory=list)

    class CoretaxConfig(BaseModel):
        base_url: str
        client_id: str
        client_secret: str
        timeout_seconds: int = Field(default=30, ge=1)
        retry_count: int = Field(default=3, ge=0)

    class SystemConfig(BaseModel):
        version: str = "1.0.0"
        environment: str = Field(default="development")
        debug: bool = False

    class LoggingConfig(BaseModel):
        level: str = Field(default="INFO")
        format: str = Field(default="json")
        file: str | None = None

    class AuditConfig(BaseModel):
        immutable_store_path: str
        retention_days: int = Field(default=365, ge=1)
        hash_algorithm: str = Field(default="sha3-256")

    class FeaturesConfig(BaseModel):
        enable_manufacturing: bool = False
        enable_coretax: bool = False
        enable_consolidation: bool = False
        enable_forex: bool = False

    class AppConfig(BaseModel):
        system: SystemConfig
        database: DatabaseConfig
        security: SecurityConfig
        api: APIConfig
        logging: LoggingConfig
        audit: AuditConfig
        coretax: CoretaxConfig | None = None
        features: FeaturesConfig = Field(default_factory=FeaturesConfig)

    PYDANTIC_AVAILABLE = True
    logger.info("Pydantic available for schema validation")

except ImportError:
    PYDANTIC_AVAILABLE = False
    logger.info("Pydantic not available, using manual validation")

    class AppConfig:
        pass


class PydanticSchemaValidator:
    """Pydantic-based schema validator (if available)."""

    def __init__(self):
        if not PYDANTIC_AVAILABLE:
            raise RuntimeError("Pydantic not installed")
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._validator_id = str(uuid4())
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "validator_id": self._validator_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "validator_id": self._validator_id,
                "details": details,
            }
        )

    def validate(self, config: dict[str, Any]) -> tuple[bool, dict[str, str]]:
        try:
            AppConfig(**config)
            self._record_audit("VALIDATE_SUCCESS", "system", {})
            return True, {}
        except ValidationError as e:
            errors = {}
            for error in e.errors():
                field = ".".join(str(loc) for loc in error["loc"])
                errors[field] = error["msg"]
            self._record_audit("VALIDATE_FAILED", "system", {"error_count": len(errors)})
            return False, errors

    # ==================== ENTITY DASAR METHODS ====================
    def validate_self(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {
            "validator_id": self._validator_id,
            "pydantic_available": PYDANTIC_AVAILABLE,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PydanticSchemaValidator:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._validator_id = data.get("validator_id", str(uuid4()))
        return instance

    def clone(self) -> PydanticSchemaValidator:
        new = PydanticSchemaValidator()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._validator_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "validator_id": self._validator_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PydanticSchemaValidator:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._validator_id = str(uuid4())
        self._record_audit("RESET", "system", {})


# === 4. SINGLETON ACCESSORS ===
_schema_validator_instance: SchemaValidator | None = None


def get_schema_validator() -> SchemaValidator:
    global _schema_validator_instance
    if _schema_validator_instance is None:
        _schema_validator_instance = SchemaValidator()
    return _schema_validator_instance


def get_pydantic_validator() -> PydanticSchemaValidator | None:
    if PYDANTIC_AVAILABLE:
        return PydanticSchemaValidator()
    return None


# === 5. CONVENIENCE FUNCTIONS ===
def validate_config(config: dict[str, Any]) -> tuple[bool, dict[str, str]]:
    validator = get_schema_validator()
    return validator.validate_config(config)


def validate_config_with_pydantic(config: dict[str, Any]) -> tuple[bool, dict[str, str]]:
    if PYDANTIC_AVAILABLE:
        pydantic_validator = get_pydantic_validator()
        return pydantic_validator.validate(config)
    else:
        return validate_config(config)


# === 6. ALIAS UNTUK KOMPATIBILITAS ===
ConfigSchemaValidator = SchemaValidator


# === 7. EXPORTS ===
__all__ = [
    "PYDANTIC_AVAILABLE",
    "ConfigSchemaValidator",
    "PydanticSchemaValidator",
    "SchemaValidator",
    "get_pydantic_validator",
    "get_schema_validator",
    "validate_config",
    "validate_config_with_pydantic",
]
