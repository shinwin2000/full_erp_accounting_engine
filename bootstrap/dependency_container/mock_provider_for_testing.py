#!/usr/bin/env python3
"""
Module: mock_provider_for_testing.py
Layer: Bootstrap (Dependency Container)
Responsibility: Provider untuk mock objects dalam testing environment.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, TypeVar
from unittest.mock import AsyncMock, Mock

from bootstrap.dependency_container.ioc_container import IoCContainer, get_container

logger = logging.getLogger(__name__)

T = TypeVar("T")


class MockProviderError(Exception):
    """Base exception untuk mock provider."""
    pass


class MockProvider:
    """
    Provider untuk mock objects dalam testing.

    Method Standards:
    - create_mock() - Membuat async mock
    - create_sync_mock() - Membuat sync mock
    - register_mock() - Mendaftar mock
    - unregister_mock() - Menghapus mock
    - get_mock() - Mendapatkan mock
    - reset_all_mocks() - Reset semua mock
    - clear_all_mocks() - Hapus semua mock
    - mock_scope() - Context manager untuk mock
    """

    def __init__(self, container: IoCContainer | None = None):
        self._container = container or get_container()
        self._original_registrations: dict[type, Any] = {}
        self._mocks: dict[type, Any] = {}
        self._logger = logging.getLogger(f"{__name__}.MockProvider")

    def create_mock(self, interface: type[T], spec: bool = True) -> AsyncMock:
        """Create an async mock for an interface."""
        if spec:
            mock = AsyncMock(spec=interface)
        else:
            mock = AsyncMock()
        self._mocks[interface] = mock
        self._logger.debug(f"Created async mock for {interface.__name__}")
        return mock

    def create_sync_mock(self, interface: type[T], spec: bool = True) -> Mock:
        """Create a sync mock for an interface."""
        if spec:
            mock = Mock(spec=interface)
        else:
            mock = Mock()
        self._mocks[interface] = mock
        self._logger.debug(f"Created sync mock for {interface.__name__}")
        return mock

    def register_mock(self, interface: type[T], mock: Any) -> None:
        """Register a mock for an interface."""
        if not interface:
            raise ValueError("Interface cannot be None")
        if mock is None:
            raise ValueError("Mock cannot be None")

        if interface in self._container._registrations:
            self._original_registrations[interface] = self._container._registrations[interface]

        self._container.register_instance(interface, mock)
        self._mocks[interface] = mock
        self._logger.debug(f"Registered mock for {interface.__name__}")

    def unregister_mock(self, interface: type[T]) -> None:
        """Unregister mock and restore original."""
        if interface in self._original_registrations:
            original = self._original_registrations[interface]
            self._container._registrations[interface] = original
            del self._original_registrations[interface]

        if interface in self._mocks:
            del self._mocks[interface]

        self._logger.debug(f"Unregistered mock for {interface.__name__}")

    def get_mock(self, interface: type[T]) -> Any | None:
        """Get registered mock for interface."""
        return self._mocks.get(interface)

    def reset_all_mocks(self) -> None:
        """Reset all registered mocks."""
        for mock in self._mocks.values():
            mock.reset_mock()
        self._logger.debug("Reset all mocks")

    def clear_all_mocks(self) -> None:
        """Clear all mock registrations."""
        for interface in list(self._mocks.keys()):
            self.unregister_mock(interface)
        self._mocks.clear()
        self._original_registrations.clear()
        self._logger.debug("Cleared all mocks")

    @asynccontextmanager
    async def mock_scope(self):
        """Context manager for temporary mock registration."""
        try:
            yield self
        finally:
            self.clear_all_mocks()


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_mock_provider: MockProvider | None = None


def get_mock_provider() -> MockProvider:
    """Get singleton instance of MockProvider."""
    global _mock_provider
    if _mock_provider is None:
        _mock_provider = MockProvider()
    return _mock_provider


def patch_dependency(interface: type, mock: Any):
    """Decorator to patch a dependency for a test function."""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            provider = get_mock_provider()
            provider.register_mock(interface, mock)
            try:
                return await func(*args, **kwargs)
            finally:
                provider.unregister_mock(interface)

        return wrapper

    return decorator


__all__ = [
    "MockProvider",
    "MockProviderError",
    "get_mock_provider",
    "patch_dependency",
]