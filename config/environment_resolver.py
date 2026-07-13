#!/usr/bin/env python3
"""
Module: environment_resolver.py
Layer: 3 - Bootstrap & Config / Configuration
Responsibility: Resolver variabel lingkungan dalam konfigurasi.
               Mendukung sintaks ${VAR_NAME} dan ${VAR_NAME:default_value}
               untuk substitusi nilai dari environment variables ke dalam
               konfigurasi YAML. Juga mendukung nested references.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from config.exceptions import ConfigEnvResolveError, ConfigError, ConfigErrorCode

logger = logging.getLogger(__name__)

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")
NESTED_REF_PATTERN = re.compile(r"\$\{config:([^}]+)\}")
SECRET_REF_PATTERN = re.compile(r"\$\{secret:([^}]+)\}")


@dataclass(kw_only=True)
class EnvironmentResolver:
    _instance: Any = field(default=None, init=False, repr=False)
    _resolved_cache: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _mask_sensitive: bool = field(default=True, init=False, repr=False)
    _version: int = field(default=1, init=False, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _resolver_id: str = field(default_factory=lambda: str(uuid4()), init=False, repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if self._mask_sensitive not in (True, False):
            raise ValueError("_mask_sensitive must be boolean")

    def _take_snapshot(self):
        self._snapshots.append({
            "version": self._version,
            "resolver_id": self._resolver_id,
            "mask_sensitive": self._mask_sensitive,
            "cache_size": len(self._resolved_cache),
            "timestamp": datetime.now(UTC).isoformat(),
        })
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append({
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
            "resolver_id": self._resolver_id,
            "details": details,
        })

    def __new__(cls) -> EnvironmentResolver:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._resolved_cache = {}
        self._mask_sensitive = True
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._resolver_id = str(uuid4())
        self._take_snapshot()

    def resolve(self, value: Any, config_context: dict[str, Any] | None = None) -> Any:
        if isinstance(value, str):
            return self._resolve_string(value, config_context)
        elif isinstance(value, dict):
            return {k: self.resolve(v, config_context) for k, v in value.items()}
        elif isinstance(value, list):
            return [self.resolve(item, config_context) for item in value]
        else:
            return value

    def _resolve_string(self, value: str, config_context: dict[str, Any] | None = None) -> str:
        result = value
        if config_context:
            result = self._resolve_nested_refs(result, config_context)
        result = self._resolve_secret_refs(result)

        def replace_env(match):
            var_name = match.group(1)
            default = match.group(2)
            env_value = os.environ.get(var_name)
            if env_value is not None:
                if self._mask_sensitive and self._is_sensitive_var(var_name):
                    logger.debug(f"Resolved env var {var_name} (masked)")
                else:
                    logger.debug(f"Resolved env var {var_name}")
                return env_value
            elif default is not None:
                logger.debug(f"Using default for {var_name}: {default}")
                return default
            else:
                raise ConfigEnvResolveError(var_name)

        result = ENV_VAR_PATTERN.sub(replace_env, result)
        return result

    def _resolve_nested_refs(self, value: str, config_context: dict[str, Any]) -> str:
        def replace_nested(match):
            path = match.group(1)
            resolved = self._get_nested_value(config_context, path)
            if resolved is None:
                raise ConfigError(
                    f"Nested config reference {path} not found",
                    error_code=ConfigErrorCode.CONFIG_PARSE_ERROR,
                )
            return str(resolved)

        return NESTED_REF_PATTERN.sub(replace_nested, value)

    def _resolve_secret_refs(self, value: str) -> str:
        def replace_secret(match):
            ref_path = match.group(1)
            env_var = ref_path.upper().replace(".", "_")
            env_value = os.environ.get(env_var)
            if env_value:
                return env_value
            logger.warning("External reference not resolved via environment")
            return f"{{SECRET:{ref_path}}}"

        return SECRET_REF_PATTERN.sub(replace_secret, value)

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

    def _is_sensitive_var(self, var_name: str) -> bool:
        sensitive_patterns = ["PASSWORD", "SECRET", "KEY", "TOKEN", "AUTH"]
        var_upper = var_name.upper()
        return any(pattern in var_upper for pattern in sensitive_patterns)

    def resolve_file(self, file_path: str | Path) -> dict[str, Any]:
        import yaml
        path = Path(file_path)
        if not path.exists():
            raise ConfigError(f"File not found: {path}", error_code=ConfigErrorCode.CONFIG_NOT_FOUND)
        with open(path, encoding="utf-8") as f:
            raw_config = yaml.safe_load(f) or {}
        self._record_audit("RESOLVE_FILE", "system", {"file": str(path)})
        return self.resolve(raw_config)

    def resolve_env_file(self, env_file_path: str | Path) -> dict[str, str]:
        path = Path(env_file_path)
        if not path.exists():
            return {}
        env_vars = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    value = self._resolve_string(value.strip(), None)
                    env_vars[key.strip()] = value
                    os.environ[key.strip()] = value
        self._record_audit("RESOLVE_ENV_FILE", "system", {"file": str(path), "count": len(env_vars)})
        logger.info(f"Loaded {len(env_vars)} variables from {env_file_path}")
        return env_vars

    def get_env(self, key: str, default: str | None = None) -> str | None:
        return os.environ.get(key, default)

    def set_env(self, key: str, value: str) -> None:
        os.environ[key] = value
        self._record_audit("SET_ENV", "system", {"key": key})

    def get_all_env(self) -> dict[str, str]:
        result = {}
        for key, value in os.environ.items():
            if self._mask_sensitive and self._is_sensitive_var(key):
                result[key] = "***MASKED***"
            else:
                result[key] = value
        return result

    def clear_cache(self) -> None:
        self._resolved_cache.clear()
        self._record_audit("CLEAR_CACHE", "system", {})

    def set_mask_sensitive(self, mask: bool) -> None:
        self._mask_sensitive = mask
        self._record_audit("SET_MASK_SENSITIVE", "system", {"mask": mask})

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolver_id": self._resolver_id,
            "mask_sensitive": self._mask_sensitive,
            "cache_size": len(self._resolved_cache),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnvironmentResolver:
        instance = cls()
        instance._mask_sensitive = data.get("mask_sensitive", True)
        instance._version = data.get("version", 1)
        instance._resolver_id = data.get("resolver_id", str(uuid4()))
        return instance

    def clone(self) -> EnvironmentResolver:
        new = EnvironmentResolver()
        new._mask_sensitive = self._mask_sensitive
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._resolver_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "resolver_id": self._resolver_id,
            "mask_sensitive": self._mask_sensitive,
            "cache_size": len(self._resolved_cache),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EnvironmentResolver:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._resolved_cache.clear()
        self._mask_sensitive = True
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._resolver_id = str(uuid4())
        self._record_audit("RESET", "system", {})


_environment_resolver_instance: EnvironmentResolver | None = None

def get_environment_resolver() -> EnvironmentResolver:
    global _environment_resolver_instance
    if _environment_resolver_instance is None:
        _environment_resolver_instance = EnvironmentResolver()
    return _environment_resolver_instance

def resolve_env(value: Any, config_context: dict[str, Any] | None = None) -> Any:
    return get_environment_resolver().resolve(value, config_context)

def load_env_file(env_file_path: str | Path) -> dict[str, str]:
    return get_environment_resolver().resolve_env_file(env_file_path)

def get_env_var(key: str, default: str | None = None) -> str | None:
    return get_environment_resolver().get_env(key, default)

__all__ = [
    "EnvironmentResolver",
    "get_env_var",
    "get_environment_resolver",
    "load_env_file",
    "resolve_env",
]
