#!/usr/bin/env python3
"""
Module: sqlalchemy_customer_repository_impl.py
Layer: Adapters / Secondary / Implementation
Responsibility: SQLAlchemy implementation of CustomerRepositoryPort.

Uses async SQLAlchemy 2.0 with PostgreSQL.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    delete,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.customer_supplier_repository_port import CustomerRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# SQLAlchemy ORM Model
# ============================================================================

Base = declarative_base()


class CustomerTable(Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index("idx_customer_legal_entity", "legal_entity_id"),
        Index("idx_customer_code", "customer_code", unique=True),
        Index("idx_customer_npwp", "npwp", unique=True),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    customer_code = Column(String(50), nullable=False, unique=True)
    customer_name = Column(String(200), nullable=False)
    npwp = Column(String(20), nullable=True, unique=True)
    email = Column(String(200), nullable=True)
    phone = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    province = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=True)
    country = Column(String(100), nullable=True, default="Indonesia")
    contact_person = Column(String(200), nullable=True)
    credit_limit = Column(Numeric(20, 2), nullable=False, default=0)
    credit_term_days = Column(Integer, nullable=False, default=30)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)


# ============================================================================
# Repository Implementation
# ============================================================================


class SQLAlchemyCustomerRepository(CustomerRepositoryPort):
    """SQLAlchemy implementation of CustomerRepositoryPort."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def _get_session(self) -> AsyncSession:
        return self._session_factory()

    async def save(self, customer) -> None:
        """Save or update a customer."""
        async with await self._get_session() as session, session.begin():
            # Check if exists
            stmt = select(CustomerTable).where(CustomerTable.id == customer.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                existing.customer_code = customer.customer_code
                existing.customer_name = customer.customer_name
                existing.npwp = customer.npwp
                existing.email = customer.email
                existing.phone = customer.phone
                existing.address = customer.address
                existing.city = customer.city
                existing.province = customer.province
                existing.postal_code = customer.postal_code
                existing.country = customer.country
                existing.contact_person = customer.contact_person
                existing.credit_limit = customer.credit_limit
                existing.credit_term_days = customer.credit_term_days
                existing.is_active = customer.is_active
                existing.updated_at = datetime.utcnow()
            else:
                # Insert new
                new_row = CustomerTable(
                    id=customer.id,
                    legal_entity_id=customer.legal_entity_id,
                    customer_code=customer.customer_code,
                    customer_name=customer.customer_name,
                    npwp=customer.npwp,
                    email=customer.email,
                    phone=customer.phone,
                    address=customer.address,
                    city=customer.city,
                    province=customer.province,
                    postal_code=customer.postal_code,
                    country=customer.country,
                    contact_person=customer.contact_person,
                    credit_limit=customer.credit_limit,
                    credit_term_days=customer.credit_term_days,
                    is_active=customer.is_active,
                    created_by=customer.created_by,
                )
                session.add(new_row)

    async def get_by_id(self, customer_id: UUID):
        """Get customer by ID."""
        async with await self._get_session() as session:
            stmt = select(CustomerTable).where(CustomerTable.id == customer_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return self._to_domain(row)

    async def get_by_code(self, customer_code: str, legal_entity_id: UUID):
        """Get customer by customer code within legal entity."""
        async with await self._get_session() as session:
            stmt = select(CustomerTable).where(
                CustomerTable.customer_code == customer_code,
                CustomerTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return self._to_domain(row)

    async def list_by_legal_entity(
        self, legal_entity_id: UUID, is_active: bool | None = None
    ) -> list:
        """List customers for a legal entity."""
        async with await self._get_session() as session:
            stmt = select(CustomerTable).where(CustomerTable.legal_entity_id == legal_entity_id)
            if is_active is not None:
                stmt = stmt.where(CustomerTable.is_active == is_active)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [self._to_domain(row) for row in rows]

    async def update_status(self, customer_id: UUID, is_active: bool) -> None:
        """Update customer active status."""
        async with await self._get_session() as session, session.begin():
            stmt = (
                update(CustomerTable)
                .where(CustomerTable.id == customer_id)
                .values(is_active=is_active, updated_at=datetime.utcnow())
            )
            await session.execute(stmt)

    async def delete(self, customer_id: UUID) -> None:
        """Delete a customer (soft delete? here hard delete)."""
        async with await self._get_session() as session, session.begin():
            await session.execute(delete(CustomerTable).where(CustomerTable.id == customer_id))

    async def get_by_npwp(self, npwp: str) -> Optional:
        """Get customer by NPWP."""
        async with await self._get_session() as session:
            stmt = select(CustomerTable).where(CustomerTable.npwp == npwp)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return self._to_domain(row)

    def _to_domain(self, row: CustomerTable):
        # Create a simple dict or domain object. Since we don't have the exact domain entity,
        # we return a dictionary. However, the port likely expects a domain entity.
        # We'll create a simple object with attributes.
        from types import SimpleNamespace

        return SimpleNamespace(
            id=row.id,
            legal_entity_id=row.legal_entity_id,
            customer_code=row.customer_code,
            customer_name=row.customer_name,
            npwp=row.npwp,
            email=row.email,
            phone=row.phone,
            address=row.address,
            city=row.city,
            province=row.province,
            postal_code=row.postal_code,
            country=row.country,
            contact_person=row.contact_person,
            credit_limit=row.credit_limit,
            credit_term_days=row.credit_term_days,
            is_active=row.is_active,
            created_by=row.created_by,
            created_at=row.created_at,
        )


__all__ = ["CustomerTable", "SQLAlchemyCustomerRepository"]
