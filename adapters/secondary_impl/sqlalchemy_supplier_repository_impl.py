#!/usr/bin/env python3
"""
Module: sqlalchemy_supplier_repository_impl.py
SQLAlchemy implementation of SupplierRepositoryPort.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, Column, DateTime, Index, Integer, String, Text,
    select, update, delete,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()


class SupplierTable(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        Index("idx_supplier_legal_entity", "legal_entity_id"),
        Index("idx_supplier_code", "supplier_code", unique=True),
        Index("idx_supplier_npwp", "npwp"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    supplier_code = Column(String(50), nullable=False, unique=True)
    supplier_name = Column(String(200), nullable=False)
    npwp = Column(String(20), nullable=True)
    email = Column(String(200), nullable=True)
    phone = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    province = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=True)
    country = Column(String(100), nullable=True, default="Indonesia")
    contact_person = Column(String(200), nullable=True)
    payment_term_days = Column(Integer, nullable=False, default=30)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)


class SQLAlchemySupplierRepository:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def save(self, supplier: Any) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = select(SupplierTable).where(SupplierTable.id == supplier.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                existing.supplier_code = supplier.supplier_code
                existing.supplier_name = supplier.supplier_name
                existing.npwp = supplier.npwp
                existing.email = supplier.email
                existing.phone = supplier.phone
                existing.address = supplier.address
                existing.city = supplier.city
                existing.province = supplier.province
                existing.postal_code = supplier.postal_code
                existing.country = supplier.country
                existing.contact_person = supplier.contact_person
                existing.payment_term_days = supplier.payment_term_days
                existing.is_active = supplier.is_active
                existing.updated_at = datetime.utcnow()
            else:
                new = SupplierTable(
                    id=supplier.id or uuid4(),
                    legal_entity_id=supplier.legal_entity_id,
                    supplier_code=supplier.supplier_code,
                    supplier_name=supplier.supplier_name,
                    npwp=supplier.npwp,
                    email=supplier.email,
                    phone=supplier.phone,
                    address=supplier.address,
                    city=supplier.city,
                    province=supplier.province,
                    postal_code=supplier.postal_code,
                    country=supplier.country,
                    contact_person=supplier.contact_person,
                    payment_term_days=supplier.payment_term_days,
                    is_active=supplier.is_active,
                    created_by=supplier.created_by,
                )
                session.add(new)

    async def get_by_id(self, supplier_id: UUID) -> Optional[Any]:
        session = await self._get_session()
        stmt = select(SupplierTable).where(SupplierTable.id == supplier_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_code(self, supplier_code: str, legal_entity_id: UUID) -> Optional[Any]:
        session = await self._get_session()
        stmt = select(SupplierTable).where(
            SupplierTable.supplier_code == supplier_code,
            SupplierTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_by_entity(self, legal_entity_id: UUID, is_active: bool | None = None) -> list[Any]:
        session = await self._get_session()
        stmt = select(SupplierTable).where(SupplierTable.legal_entity_id == legal_entity_id)
        if is_active is not None:
            stmt = stmt.where(SupplierTable.is_active == is_active)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def is_active(self, supplier_id: UUID) -> bool:
        supplier = await self.get_by_id(supplier_id)
        return supplier is not None and supplier.is_active

    async def update_status(self, supplier_id: UUID, is_active: bool) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = (
                update(SupplierTable)
                .where(SupplierTable.id == supplier_id)
                .values(is_active=is_active, updated_at=datetime.utcnow())
            )
            await session.execute(stmt)

    async def delete(self, supplier_id: UUID) -> None:
        session = await self._get_session()
        async with session.begin():
            await session.execute(delete(SupplierTable).where(SupplierTable.id == supplier_id))

    async def get_by_npwp(self, npwp: str) -> Optional[Any]:
        session = await self._get_session()
        stmt = select(SupplierTable).where(SupplierTable.npwp == npwp)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    def _to_domain(self, row: SupplierTable) -> Any:
        from types import SimpleNamespace
        return SimpleNamespace(
            id=row.id,
            legal_entity_id=row.legal_entity_id,
            supplier_code=row.supplier_code,
            supplier_name=row.supplier_name,
            npwp=row.npwp,
            email=row.email,
            phone=row.phone,
            address=row.address,
            city=row.city,
            province=row.province,
            postal_code=row.postal_code,
            country=row.country,
            contact_person=row.contact_person,
            payment_term_days=row.payment_term_days,
            is_active=row.is_active,
            created_by=row.created_by,
            created_at=row.created_at,
        )


__all__ = ["SupplierTable", "SQLAlchemySupplierRepository"]