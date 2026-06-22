#!/usr/bin/env python3
"""
Module: sqlalchemy_customer_repository_impl.py
SQLAlchemy implementation of CustomerRepositoryPort.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, Column, DateTime, Index, Integer, Numeric, String, Text,
    select, update, delete,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

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


class SQLAlchemyCustomerRepository:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ---------- Port methods ----------
    async def save(self, customer: Any) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = select(CustomerTable).where(CustomerTable.id == customer.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
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
                new = CustomerTable(
                    id=customer.id or uuid4(),
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
                session.add(new)

    async def get_by_id(self, customer_id: UUID) -> Optional[Any]:
        session = await self._get_session()
        stmt = select(CustomerTable).where(CustomerTable.id == customer_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_code(self, customer_code: str, legal_entity_id: UUID) -> Optional[Any]:
        session = await self._get_session()
        stmt = select(CustomerTable).where(
            CustomerTable.customer_code == customer_code,
            CustomerTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_by_entity(self, legal_entity_id: UUID, is_active: bool | None = None) -> list[Any]:
        session = await self._get_session()
        stmt = select(CustomerTable).where(CustomerTable.legal_entity_id == legal_entity_id)
        if is_active is not None:
            stmt = stmt.where(CustomerTable.is_active == is_active)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def check_credit_limit(self, customer_id: UUID, amount: Decimal) -> bool:
        customer = await self.get_by_id(customer_id)
        if not customer:
            return False
        return customer.credit_limit >= amount

    async def is_active(self, customer_id: UUID) -> bool:
        customer = await self.get_by_id(customer_id)
        return customer is not None and customer.is_active

    async def update_status(self, customer_id: UUID, is_active: bool) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = (
                update(CustomerTable)
                .where(CustomerTable.id == customer_id)
                .values(is_active=is_active, updated_at=datetime.utcnow())
            )
            await session.execute(stmt)

    async def delete(self, customer_id: UUID) -> None:
        session = await self._get_session()
        async with session.begin():
            await session.execute(delete(CustomerTable).where(CustomerTable.id == customer_id))

    async def get_by_npwp(self, npwp: str) -> Optional[Any]:
        session = await self._get_session()
        stmt = select(CustomerTable).where(CustomerTable.npwp == npwp)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    def _to_domain(self, row: CustomerTable) -> Any:
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