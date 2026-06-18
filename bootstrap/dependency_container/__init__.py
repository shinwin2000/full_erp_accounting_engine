from __future__ import annotations

"""
Package: bootstrap.dependency_container
IoC container, service registry, adapter registry, repository registry,
factory provider, lifecycle hooks, scoped context, and health probes for
the ERP system.

This is the Composition Root (top-level) and may import from any layer.
"""

from bootstrap.dependency_container.ioc_container import IoCContainer, build_container

__all__ = [
    "IoCContainer",
    "build_container",
]