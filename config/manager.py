#!/usr/bin/env python3
"""
Module: config/manager.py
Layer: 2 - Configuration / Manager
Responsibility: Singleton configuration manager yang memuat semua file YAML
               dari direktori config_files/ secara paralel, menyediakan akses
               terpusat, dan mendukung reload.

Metode:
- load_all() → dict: memuat semua file YAML (sekali) dan mengembalikan merged config.
- get(key, default=None) → value: mengambil nilai konfigurasi berdasarkan key.
- get_section(section) → dict: mengambil seluruh section (misal 'database').
- reload() → None: mengosongkan cache dan memuat ulang.
- get_loaded_files() → list: mengembalikan daftar file yang telah dimuat.
- get_metadata() → dict: informasi tentang proses load (jumlah file, waktu, dll).
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

from config.environment_resolver import get_environment_resolver

# Coba gunakan CLoader jika tersedia (lebih cepat)
try:
    from yaml import CLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader

logger = logging.getLogger(__name__)


class ConfigManager:
    """Singleton configuration manager."""

    _instance: ConfigManager | None = None
    _lock = None
    _config: dict[str, Any] = {}
    _loaded_files: list[str] = []
    _load_time_ms: float = 0.0
    _loaded: bool = False
    _config_dir: Path | None = None

    def __new__(cls) -> ConfigManager:
        if cls._instance is None:
            import threading
            cls._lock = threading.Lock()
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # Inisialisasi hanya sekali
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self._config_dir = Path(__file__).parent.parent / "config_files"

    def load_all(self, config_dir: str | None = None, force_reload: bool = False) -> dict[str, Any]:
        """
        Memuat semua file YAML dari direktori konfigurasi.

        Args:
            config_dir: Path ke direktori (default: project_root/config_files)
            force_reload: Jika True, memuat ulang meskipun sudah dimuat.

        Returns:
            Dictionary gabungan dari semua file YAML.
        """
        if self._loaded and not force_reload:
            logger.debug("Config already loaded, returning cached version")
            return self._config

        if config_dir:
            self._config_dir = Path(config_dir)

        if not self._config_dir or not self._config_dir.exists():
            raise FileNotFoundError(f"Config directory not found: {self._config_dir}")

        start = time.perf_counter()

        # Cari semua file .yaml dan .yml
        yaml_files = sorted(self._config_dir.glob("*.yaml")) + sorted(self._config_dir.glob("*.yml"))
        if not yaml_files:
            raise FileNotFoundError(f"No YAML files found in {self._config_dir}")

        logger.info(f"Loading {len(yaml_files)} config files from {self._config_dir}...")

        # Muat file secara paralel menggunakan ThreadPoolExecutor
        loaded_data: dict[str, dict] = {}
        failed_files: list[str] = []

        with ThreadPoolExecutor(max_workers=min(8, len(yaml_files))) as executor:
            future_to_file = {
                executor.submit(self._load_single_file, file_path): file_path
                for file_path in yaml_files
            }

            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    file_name, data = future.result()
                    if data is not None:
                        loaded_data[file_name] = data
                        logger.debug(f"Loaded {file_name} with {len(data)} top-level keys")
                    else:
                        failed_files.append(file_name)
                except Exception as e:
                    file_name = file_path.name
                    logger.error(f"Failed to load {file_name}: {e}")
                    failed_files.append(file_name)

        if not loaded_data:
            raise RuntimeError(f"No config data loaded from {len(yaml_files)} files")

        # Merge semua data
        merged = {}
        for file_name, data in loaded_data.items():
            # Simpan sumber untuk traceability
            merged.setdefault("_sources", {})[file_name] = list(data.keys())
            # Merge dengan prioritas file terakhir (sesuai urutan sort)
            merged.update(data)

        self._config = merged
        self._loaded_files = list(loaded_data.keys())
        self._load_time_ms = (time.perf_counter() - start) * 1000
        self._loaded = True

        if failed_files:
            logger.warning(f"Failed to load {len(failed_files)} files: {failed_files}")

        logger.info(
            f"Config loaded: {len(merged)} top-level keys from {len(loaded_data)} files "
            f"in {self._load_time_ms:.2f}ms"
        )
        return self._config

    def _load_single_file(self, file_path: Path) -> tuple[str, dict | None]:
        """Muat satu file YAML dan kembalikan (nama_file, data)."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.load(f, Loader=SafeLoader)
                if data is None:
                    data = {}
                # Resolusi placeholder ${VAR} / ${VAR:default} agar tidak
                # bocor sebagai string literal ke konsumen config (mis. Kafka,
                # Redis, DB), yang menyebabkan error seperti
                # "invalid literal for int(): '9092}'"
                data = get_environment_resolver().resolve(data)
                return file_path.name, data
        except Exception as e:
            logger.error(f"Error loading {file_path.name}: {e}")
            return file_path.name, None

    def get(self, key: str, default: Any = None) -> Any:
        """Ambil nilai konfigurasi berdasarkan key (mendukung dot notation)."""
        if not self._loaded:
            self.load_all()
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def get_section(self, section: str) -> dict[str, Any]:
        """Ambil seluruh section (misal 'database', 'kafka', dll)."""
        if not self._loaded:
            self.load_all()
        return self._config.get(section, {})

    def reload(self) -> None:
        """Kosongkan cache dan muat ulang semua file."""
        logger.info("Reloading configuration...")
        self._loaded = False
        self._config = {}
        self._loaded_files = []
        self._load_time_ms = 0.0
        self.load_all(force_reload=True)

    def get_loaded_files(self) -> list[str]:
        """Daftar file yang berhasil dimuat."""
        if not self._loaded:
            self.load_all()
        return self._loaded_files.copy()

    def get_metadata(self) -> dict[str, Any]:
        """Metadata tentang proses load."""
        if not self._loaded:
            self.load_all()
        return {
            "loaded": self._loaded,
            "file_count": len(self._loaded_files),
            "load_time_ms": self._load_time_ms,
            "config_keys_count": len(self._config),
            "config_dir": str(self._config_dir) if self._config_dir else None,
            "files": self._loaded_files,
        }

    def to_dict(self) -> dict[str, Any]:
        """Kembalikan seluruh konfigurasi (hati-hati dengan data sensitif)."""
        if not self._loaded:
            self.load_all()
        # Hindari return reference langsung agar tidak termodifikasi
        return self._config.copy()


# === Singleton accessor ===
_config_manager: ConfigManager | None = None


def get_config_manager() -> ConfigManager:
    """Get singleton ConfigManager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


__all__ = [
    "ConfigManager",
    "get_config_manager",
]