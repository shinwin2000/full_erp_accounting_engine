#!/usr/bin/env python3
"""
Adapter: Customer & Supplier Repository
Layer: Adapters (Secondary Implementation)

Adapter untuk repository customer dan supplier menggunakan SQLAlchemy.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from adapters.secondary_impl.sqlalchemy_customer_repository_impl import SQLAlchemyCustomerRepository
from adapters.secondary_impl.sqlalchemy_supplier_repository_impl import SQLAlchemySupplierRepository
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

class CustomerSupplierRepositoryAdapter:
    """
    Adapter yang menyediakan akses ke customer dan supplier repository.
    """
    def __init__(self, session: Any = None):
        self.customer_repo = SQLAlchemyCustomerRepository(session)
        self.supplier_repo = SQLAlchemySupplierRepository(session)

    # Delegasikan semua metode ke masing-masing repository
    async def add_customer(self, customer) -> None:
        return await self.customer_repo.add(customer)

    async def get_customer_by_id(self, customer_id: UUID):
        return await self.customer_repo.get_by_id(customer_id)

    async def update_customer(self, customer) -> None:
        return await self.customer_repo.update(customer)

    async def delete_customer(self, customer_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        return await self.customer_repo.delete(customer_id, user_id, permanent)

    async def find_customers(self, **filters):
        return await self.customer_repo.find(**filters)

    # Supplier methods
    async def add_supplier(self, supplier) -> None:
        return await self.supplier_repo.add(supplier)

    async def get_supplier_by_id(self, supplier_id: UUID):
        return await self.supplier_repo.get_by_id(supplier_id)

    async def update_supplier(self, supplier) -> None:
        return await self.supplier_repo.update(supplier)

    async def delete_supplier(self, supplier_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        return await self.supplier_repo.delete(supplier_id, user_id, permanent)

    async def find_suppliers(self, **filters):
        return await self.supplier_repo.find(**filters)

__all__ = ["CustomerSupplierRepositoryAdapter"]
