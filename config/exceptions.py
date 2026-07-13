#!/usr/bin/env python3
"""
Module: exceptions.py
Layer: 3 - Bootstrap & Config / Configuration
Responsibility: Mendefinisikan exception khusus untuk layer config.
               Tidak bergantung pada bootstrap.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any


# === 1. Config Error Codes ===
class ConfigErrorCode(Enum):
    CONFIG_NOT_FOUND = auto()
    CONFIG_PARSE_ERROR = auto()
    CONFIG_VALIDATION_FAILED = auto()
    CONFIG_ENCRYPTION_FAILED = auto()
    CONFIG_ENV_RESOLVE_FAILED = auto()
    CONFIG_VERSION_NOT_FOUND = auto()
    CONFIG_VERSION_ROLLBACK_FAILED = auto()
    CONFIG_LOAD_FAILED = auto()
    UNKNOWN_ERROR = auto()

    def display_name(self) -> str:
        names = {
            ConfigErrorCode.CONFIG_NOT_FOUND: "Config Not Found",
            ConfigErrorCode.CONFIG_PARSE_ERROR: "Config Parse Error",
            ConfigErrorCode.CONFIG_VALIDATION_FAILED: "Config Validation Failed",
            ConfigErrorCode.CONFIG_ENCRYPTION_FAILED: "Config Encryption Failed",
            ConfigErrorCode.CONFIG_ENV_RESOLVE_FAILED: "Config Environment Resolve Failed",
            ConfigErrorCode.CONFIG_VERSION_NOT_FOUND: "Config Version Not Found",
            ConfigErrorCode.CONFIG_VERSION_ROLLBACK_FAILED: "Config Version Rollback Failed",
            ConfigErrorCode.CONFIG_LOAD_FAILED: "Config Load Failed",
            ConfigErrorCode.UNKNOWN_ERROR: "Unknown Config Error",
        }
        return names.get(self, self.name)


# === 2. Base Config Exception ===
class ConfigError(Exception):
    """Base exception untuk semua error konfigurasi."""

    def __init__(
        self,
        message: str,
        error_code: ConfigErrorCode | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or ConfigErrorCode.UNKNOWN_ERROR
        self.details = details or {}
        self.cause = cause

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "error_code": self.error_code.name,
            "message": self.message,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
        }


class ConfigNotFoundError(ConfigError):
    """Exception ketika file konfigurasi tidak ditemukan."""

    def __init__(self, file_path: str, **kwargs):
        super().__init__(
            message=f"Configuration file not found: {file_path}",
            error_code=ConfigErrorCode.CONFIG_NOT_FOUND,
            details={"file_path": file_path},
            **kwargs,
        )
        self.file_path = file_path


class ConfigValidationError(ConfigError):
    """Exception ketika validasi konfigurasi gagal."""

    def __init__(self, message: str, validation_errors: dict[str, str] | None = None, **kwargs):
        super().__init__(
            message=message,
            error_code=ConfigErrorCode.CONFIG_VALIDATION_FAILED,
            details={"validation_errors": validation_errors or {}},
            **kwargs,
        )
        self.validation_errors = validation_errors or {}


class ConfigEncryptionError(ConfigError):
    """Exception ketika enkripsi/dekripsi konfigurasi gagal."""

    def __init__(self, message: str, key_id: str | None = None, **kwargs):
        super().__init__(
            message=message,
            error_code=ConfigErrorCode.CONFIG_ENCRYPTION_FAILED,
            details={"key_id": key_id},
            **kwargs,
        )
        self.key_id = key_id


class ConfigEnvResolveError(ConfigError):
    """Exception ketika resolusi environment variable gagal."""

    def __init__(self, var_name: str, default: str | None = None, **kwargs):
        super().__init__(
            message=f"Environment variable {var_name} not found and no default provided",
            error_code=ConfigErrorCode.CONFIG_ENV_RESOLVE_FAILED,
            details={"var_name": var_name, "default": default},
            **kwargs,
        )
        self.var_name = var_name
        self.default = default


class ConfigVersionNotFoundError(ConfigError):
    """Exception ketika versi konfigurasi tidak ditemukan."""

    def __init__(self, version_id: str, **kwargs):
        super().__init__(
            message=f"Config version {version_id} not found",
            error_code=ConfigErrorCode.CONFIG_VERSION_NOT_FOUND,
            details={"version_id": version_id},
            **kwargs,
        )
        self.version_id = version_id


class ConfigVersionRollbackError(ConfigError):
    """Exception ketika rollback versi konfigurasi gagal."""

    def __init__(self, message: str, version_id: str | None = None, **kwargs):
        super().__init__(
            message=message,
            error_code=ConfigErrorCode.CONFIG_VERSION_ROLLBACK_FAILED,
            details={"version_id": version_id},
            **kwargs,
        )
        self.version_id = version_id


# === 3. Ekspor ===
__all__ = [
    "ConfigEncryptionError",
    "ConfigEnvResolveError",
    "ConfigError",
    "ConfigErrorCode",
    "ConfigNotFoundError",
    "ConfigValidationError",
    "ConfigVersionNotFoundError",
    "ConfigVersionRollbackError",
]
