#!/usr/bin/env python3
"""
Module: routing_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port (abstract interface) untuk Manufacturing Routing.

Routing = urutan langkah produksi (RoutingStep) untuk membuat suatu produk.
Disimpan di dua tabel: `routing` (header) dan `routing_step` (detail).

Dependencies:
- Python standard library (abc, UUID, datetime, typing)
- domain.manufacturing.production_routing_entity (ProductionRoutingEntity, RoutingOperation)

Audit: This is a port, no direct audit logging here.

Changelog v1.1:
    - FIX: `save_routing` menerima parameter opsional `legal_entity_id`.
      Adapter registry bisa memberi instance repository yang berbeda
      setiap resolve, sehingga `set_legal_entity_id()` yang dipanggil
      sebelumnya bisa hilang. Passing eksplisit via argumen lebih robust.
"""

from __future__ import annotations

import abc
from typing import Protocol
from uuid import UUID

from domain.manufacturing.production_routing_entity import (
    ProductionRoutingEntity,
)


class RoutingRepositoryPort(abc.ABC):
    """Port (interface) untuk repository Routing."""

    @abc.abstractmethod
    async def save_routing(
        self,
        routing: ProductionRoutingEntity,
        legal_entity_id: UUID | None = None,
    ) -> None:
        """Simpan (insert atau update) routing beserta step-nya.

        Args:
            routing: Entity routing (header + steps).
            legal_entity_id: Opsional — kalau diberikan, set/override
                legal_entity_id di instance ini sebelum menyimpan.
                Kalau None, gunakan nilai yang sudah di-set via
                set_legal_entity_id() sebelumnya.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def get_routing_by_id(
        self, routing_id: UUID, legal_entity_id: UUID | None = None
    ) -> ProductionRoutingEntity | None:
        """Ambil routing berdasarkan ID (opsional filter legal entity)."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_routing_by_code(
        self, routing_code: str, legal_entity_id: UUID
    ) -> ProductionRoutingEntity | None:
        """Ambil routing berdasarkan kode unik dalam legal entity."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_routings(
        self,
        legal_entity_id: UUID,
        product_id: UUID | None = None,
        is_default: bool | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProductionRoutingEntity]:
        """List routing dengan filter umum."""
        raise NotImplementedError

    @abc.abstractmethod
    async def delete_routing(self, routing_id: UUID) -> None:
        """Hapus routing (soft delete jika kolom tersedia)."""
        raise NotImplementedError


class RoutingRepositoryPortProtocol(Protocol):
    """Protocol version of RoutingRepositoryPort."""

    async def save_routing(
        self,
        routing: ProductionRoutingEntity,
        legal_entity_id: UUID | None = None,
    ) -> None: ...
    async def get_routing_by_id(
        self, routing_id: UUID, legal_entity_id: UUID | None = None
    ) -> ProductionRoutingEntity | None: ...
    async def get_routing_by_code(
        self, routing_code: str, legal_entity_id: UUID
    ) -> ProductionRoutingEntity | None: ...
    async def list_routings(
        self,
        legal_entity_id: UUID,
        product_id: UUID | None = None,
        is_default: bool | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProductionRoutingEntity]: ...
    async def delete_routing(self, routing_id: UUID) -> None: ...


__all__ = [
    "RoutingRepositoryPort",
    "RoutingRepositoryPortProtocol",
]

