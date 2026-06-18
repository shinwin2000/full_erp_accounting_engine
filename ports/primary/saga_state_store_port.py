#!/usr/bin/env python3
"""
Module: saga_state_store_port.py
Layer: 7 - Ports / Primary Ports
Responsibility: Mendefinisikan port (interface abstrak) untuk Saga State Store.
               Digunakan oleh Saga Orchestrator untuk menyimpan state koordinasi
               transaksi terdistribusi (Saga Pattern) agar mendukung recovery.
Dependencies:
- abc (Standard Library)
- uuid (Standard Library)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID


class SagaStateStorePort(ABC):
    """
    Abstraksi Primary Port untuk menyimpan state Saga.
    Akan diimplementasikan oleh adapter di layer infrastructure.
    """

    @abstractmethod
    async def save(self, saga_type: str, saga_id: UUID, state: dict[str, Any]) -> None:
        """
        Menyimpan atau memperbarui snapshot state dari unit Saga yang sedang berjalan.
        """
        pass

    @abstractmethod
    async def get(self, saga_type: str, saga_id: UUID) -> dict[str, Any] | None:
        """
        Mengambil data state Saga yang tersimpan untuk keperluan resume atau audit trail.
        """
        pass


# === EXPORTS ===
__all__ = ["SagaStateStorePort"]
