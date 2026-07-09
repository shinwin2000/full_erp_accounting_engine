#!/usr/bin/env python3
"""
Module: customer_category_repository_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk manajemen kategori customer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID


class CustomerCategoryRepositoryPort(ABC):
    """
    Port untuk repository kategori customer.
    """

    @abstractmethod
    async def get_categories(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        """Ambil semua kategori aktif untuk legal entity."""
        pass

    @abstractmethod
    async def get_category_by_code(self, code: str, legal_entity_id: UUID) -> dict[str, Any] | None:
        """Ambil kategori berdasarkan kode."""
        pass

    @abstractmethod
    async def create_category(self, data: dict[str, Any]) -> dict[str, Any]:
        """Buat kategori baru."""
        pass

    @abstractmethod
    async def update_category(self, category_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
        """Update kategori."""
        pass

    @abstractmethod
    async def delete_category(self, category_id: UUID) -> bool:
        """Hapus kategori (permanent)."""
        pass

    @abstractmethod
    async def deactivate_category(self, category_id: UUID) -> bool:
        """Non-aktifkan kategori (soft delete)."""
        pass


__all__ = ["CustomerCategoryRepositoryPort"]