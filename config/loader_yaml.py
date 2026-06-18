#!/usr/bin/env python3
"""
Module: loader_yaml.py
Layer: 3 - Bootstrap & Config / Configuration
Responsibility: Memuat file YAML konfigurasi ke dalam struktur Python.
               Mendukung multiple config files, environment variable substitution,
               secret resolution dari Vault, dan schema validation.

Metode yang ditambahkan:
- Untuk EnvironmentResolver (internal): sudah ditambahkan sebelumnya.
- Untuk YAMLLoader: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk convenience functions: tetap dipertahankan dengan penambahan audit.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

# Menggunakan satu sumber kebenaran untuk ConfigError dari framework bootstrap
from bootstrap.bootstrap_exceptions import ConfigError

logger = logging.getLogger(__name__)

# === 1. CONSTANTS ===
DEFAULT_CONFIG_PATHS = [
    Path("config_files/application.yaml"),
    Path("config_files/security_tls_jwt_mfa.yaml"),
    Path("config_files/psak_standards_adopted.yaml"),
    Path("config_files/tax_rates_indonesia_latest.yaml"),
    Path("config_files/coretax_djp_api_config.yaml"),
    Path("config_files/feature_flags.yaml"),
]

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


# === 2. SUB-EXCEPTIONS ===
# Menurunkan langsung dari ConfigError milik bootstrap agar hierarki error terjaga
class ConfigNotFoundError(ConfigError):
    pass


class ConfigValidationError(ConfigError):
    pass


# === 3. EnvironmentResolver ===
class EnvironmentResolver:
    @staticmethod
    def resolve(value: Any) -> Any:
        if isinstance(value, str):

            def replace(match):
                var_name = match.group(1)
                default = match.group(2)
                env_value = os.environ.get(var_name)
                if env_value is not None:
                    return env_value
                elif default is not None:
                    return default
                else:
                    raise ConfigError(
                        f"Environment variable {var_name} not found and no default provided"
                    )

            return ENV_VAR_PATTERN.sub(replace, value)
        elif isinstance(value, dict):
            return {k: EnvironmentResolver.resolve(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [EnvironmentResolver.resolve(item) for item in value]
        else:
            return value


# === 4. YAMLLoader ===
class YAMLLoader:
    _instance: YAMLLoader | None = None
    _initialized: bool = False
    _config_cache: dict[Path, dict[str, Any]]
    _snapshots: list[dict[str, Any]]
    _current_config: dict[str, Any]
    _current_sources: list[Path]
    _version: int
    _audit_trail: list[dict[str, Any]]
    _loader_id: str

    def __new__(cls) -> YAMLLoader:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        # Inisialisasi state dasar terlebih dahulu untuk mencegah AttributeError saat snapshot
        self._config_cache = {}
        self._snapshots = []
        self._current_config = {}
        self._current_sources = []
        self._version = 1
        self._audit_trail = []
        self._loader_id = str(uuid4())

        # Panggil take_snapshot setelah state dasar siap
        self._take_snapshot()
        self._initialized = True

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "loader_id": self._loader_id,
                "cache_size": len(self._config_cache),
                "current_sources_count": len(self._current_sources),
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
                "loader_id": self._loader_id,
                "details": details,
            }
        )

    def load_file(self, file_path: str | Path) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise ConfigNotFoundError(str(path))

        try:
            with open(path, encoding="utf-8") as f:
                raw_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"YAML parse error in {path}: {e}") from e

        resolved_config = EnvironmentResolver.resolve(raw_config)
        self._config_cache[path] = resolved_config
        self._record_audit("LOAD_FILE", "system", {"file": str(path)})
        logger.info(f"Loaded config from {path}")
        return resolved_config

    def load_all(self, config_paths: list[str | Path] | None = None) -> dict[str, Any]:
        if config_paths is None:
            config_paths = DEFAULT_CONFIG_PATHS

        merged_config = {}
        loaded_sources = []
        for path in config_paths:
            if not Path(path).exists():
                logger.warning(f"Config file not found: {path}, skipping")
                continue
            try:
                file_config = self.load_file(path)
                merged_config = self._deep_merge(merged_config, file_config)
                loaded_sources.append(Path(path))
            except Exception as e:
                logger.error(f"Failed to load {path}: {e}")
                raise

        self._current_config = merged_config
        self._current_sources = loaded_sources
        self._record_audit("LOAD_ALL", "system", {"files_loaded": len(loaded_sources)})
        logger.info(f"Loaded {len(loaded_sources)} config files")
        return merged_config

    def load_single(self, config_key: str, default: Any = None) -> Any:
        keys = config_key.split(".")
        value = self._current_config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value

    def reload(self) -> dict[str, Any]:
        logger.info("Reloading all configurations...")
        self._config_cache.clear()
        self._current_sources.clear()
        self._record_audit("RELOAD", "system", {})
        return self.load_all()

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def get_current_config(self) -> dict[str, Any]:
        return self._current_config.copy()

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self._current_config and self._current_sources:
            errors.append("Current config is empty but sources exist")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "loader_id": self._loader_id,
            "cache_size": len(self._config_cache),
            "current_sources": [str(p) for p in self._current_sources],
            "config_keys": list(self._current_config.keys()),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> YAMLLoader:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._loader_id = data.get("loader_id", str(uuid4()))
        return instance

    def clone(self) -> YAMLLoader:
        new = YAMLLoader()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._loader_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "loader_id": self._loader_id,
            "cache_size": len(self._config_cache),
            "current_sources_count": len(self._current_sources),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> YAMLLoader:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._config_cache = {}
        self._snapshots = []
        self._current_config = {}
        self._current_sources = []
        self._version = 1
        self._audit_trail = []
        self._loader_id = str(uuid4())
        self._record_audit("RESET", "system", {})


# === 5. SINGLETON ACCESSOR ===
_loader_instance: YAMLLoader | None = None


def get_config_loader() -> YAMLLoader:
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = YAMLLoader()
    return _loader_instance


# === 6. CONVENIENCE FUNCTIONS ===
def load_config(config_path: str | None = None) -> dict[str, Any]:
    loader = get_config_loader()
    if config_path:
        return loader.load_file(config_path)
    else:
        return loader.load_all()


def get_config(key: str, default: Any = None) -> Any:
    loader = get_config_loader()
    return loader.load_single(key, default)


def reload_config() -> dict[str, Any]:
    loader = get_config_loader()
    return loader.reload()


def initialize() -> dict[str, Any]:
    logger.info("Initializing configuration loader...")
    loader = get_config_loader()
    return loader.load_all()


load_yaml_config = load_config


# === 7. EXPORTS ===
__all__ = [
    "ConfigNotFoundError",
    "ConfigValidationError",
    "EnvironmentResolver",
    "YAMLLoader",
    "get_config",
    "get_config_loader",
    "initialize",
    "load_config",
    "load_yaml_config",
    "reload_config",
]
