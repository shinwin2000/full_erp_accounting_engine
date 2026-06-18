#!/usr/bin/env python3
"""
Module: di_exceptions.py
Layer: Bootstrap (Dependency Container)
Responsibility: Mendefinisikan semua exception untuk dependency injection container.
"""

from __future__ import annotations


class ContainerError(Exception):
    """Base exception untuk IoC container."""
    pass


class DependencyNotFoundError(ContainerError):
    """Dependency tidak ditemukan."""
    pass


class CircularDependencyError(ContainerError):
    """Circular dependency terdeteksi."""
    pass


class RegistrationError(ContainerError):
    """Error saat registrasi dependency."""
    pass


class FactoryProviderError(Exception):
    """Base exception untuk factory provider."""
    pass


class FactoryNotFoundError(FactoryProviderError):
    """Factory tidak ditemukan."""
    pass


class FactoryExecutionError(FactoryProviderError):
    """Error saat mengeksekusi factory."""
    pass


class MockProviderError(Exception):
    """Base exception untuk mock provider."""
    pass


class DependencyGraphError(Exception):
    """Base exception untuk dependency graph."""
    pass


__all__ = [
    "CircularDependencyError",
    "ContainerError",
    "DependencyGraphError",
    "DependencyNotFoundError",
    "FactoryExecutionError",
    "FactoryNotFoundError",
    "FactoryProviderError",
    "MockProviderError",
    "RegistrationError",
]