# core/di_container.py
"""
DI Container untuk ERP Engine.
Menyediakan akses ke container dependency injection.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Coba import dari bootstrap
try:
    from bootstrap.dependency_container.ioc_container import get_container as _get_container
    _HAS_BOOTSTRAP = True
except ImportError:
    _HAS_BOOTSTRAP = False
    logger.warning("bootstrap.dependency_container.ioc_container tidak ditemukan, menggunakan dummy container")

# Dummy container fallback
class DummyContainer:
    def resolve(self, key: str) -> Any:
        logger.warning(f"DummyContainer.resolve({key}) called - returning None")
        return None

    def get(self, key: str) -> Any:
        logger.warning(f"DummyContainer.get({key}) called - returning None")
        return None

_container_instance = None

def get_container():
    """Dapatkan instance container (lazy initialization)."""
    global _container_instance
    if _container_instance is None:
        if _HAS_BOOTSTRAP:
            try:
                _container_instance = _get_container()
                logger.info("Container berhasil diinisialisasi dari bootstrap")
            except Exception as e:
                logger.error(f"Gagal menginisialisasi container dari bootstrap: {e}")
                _container_instance = DummyContainer()
        else:
            _container_instance = DummyContainer()
    return _container_instance

class Container:
    """Wrapper class untuk DI Container."""

    def __init__(self):
        self._container = get_container()

    def resolve(self, key: str) -> Any:
        return self._container.resolve(key)

    def get(self, key: str) -> Any:
        return self._container.get(key)

    def __getattr__(self, name: str) -> Any:
        # Delegasikan atribut yang tidak ditemukan ke container
        return getattr(self._container, name)

# Ekspor instance container untuk kemudahan akses
container = Container()

__all__ = ["Container", "container", "get_container"]
