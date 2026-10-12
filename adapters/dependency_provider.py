"""
adapters/dependency_provider.py
================================
Clean Architecture Dependency Provider.

PERBAIKAN (2026-10-12):
- `_dependency` diubah jadi `async def` dan memakai `resolve_async` supaya
  berjalan di event loop FastAPI yang sudah berjalan (bukan membuat event
  loop baru per request seperti versi sync sebelumnya).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import Request

T = TypeVar("T")


def get_service(service_class: type[T]) -> Callable[[Request], Any]:
    """Factory dependency provider FastAPI (ASYNC VERSION)."""
    async def _dependency(request: Request) -> T:
        container = getattr(request.app.state, "container", None)
        if container is None:
            raise RuntimeError(
                "IoC Container belum diinisialisasi di app.state. "
                "Pastikan 'app.state.container = get_container()' "
                "dipanggil di dalam lifespan di app/main.py"
            )
        return await container.resolve_async(service_class)

    return _dependency


def get_service_by_key(service_key: str) -> Callable[[Request], Any]:
    """Versi alternatif jika container menggunakan string key."""
    async def _dependency(request: Request) -> Any:
        container = getattr(request.app.state, "container", None)
        if container is None:
            raise RuntimeError(
                "IoC Container belum diinisialisasi di app.state. "
                "Pastikan 'app.state.container = get_container()' "
                "dipanggil di dalam lifespan di app/main.py"
            )
        return await container.resolve_async(service_key)

    return _dependency
