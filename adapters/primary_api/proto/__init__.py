from __future__ import annotations

"""
Package: adapters.primary_api.proto
"""

import importlib
import logging

__version__ = "1.0.0"

_logger = logging.getLogger(__name__)

# Mapping atribut yang akan di-lazy load
_LAZY_MAP = {
    "accounting_pb2": ("adapters.primary_api.proto.accounting_pb2", None),
    "accounting_pb2_grpc": ("adapters.primary_api.proto.accounting_pb2_grpc", None),
}

_cache = {}


def __getattr__(name: str):
    """Lazy import proto modules using importlib."""
    if name in _cache:
        return _cache[name]
    if name not in _LAZY_MAP:
        raise AttributeError(f"module {__name__} has no attribute {name}")

    module_path, _ = _LAZY_MAP[name]
    try:
        module = importlib.import_module(module_path)
        # Simpan modul utuh, bukan atribut tertentu
        _cache[name] = module
        return module
    except (ImportError, AttributeError) as e:
        _logger.error(f"Failed to lazy-import {module_path}: {e}")
        raise AttributeError(f"module {__name__} has no attribute {name}") from e


__all__ = ["__version__", "accounting_pb2", "accounting_pb2_grpc"]