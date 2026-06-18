#!/usr/bin/env python3
"""
Module: conftest.py (pytest configuration)
Layer: Governance & Architecture Enforcement

Responsibility:
    Menyediakan konfigurasi dan fixture untuk test arsitektur.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Tambahkan root proyek ke Python path agar modul dapat diimpor
ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Juga tambahkan path ke direktori full_erp_accounting_engine (parent dari architecture)
PROJECT_ROOT = ROOT_DIR.parent
if PROJECT_ROOT.exists():
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Mengembalikan path ke root proyek."""
    return ROOT_DIR


@pytest.fixture(scope="session")
def architecture_root() -> Path:
    """Mengembalikan path ke folder architecture."""
    return Path(__file__).parent


def pytest_configure(config):
    """Konfigurasi tambahan untuk pytest."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")


def pytest_collection_modifyitems(config, items):
    """Modifikasi koleksi test (misal: skip certain tests on CI)."""
    for _item in items:
        # Tambahan: bisa skip test tertentu jika environment variable tertentu tidak ada
        pass
