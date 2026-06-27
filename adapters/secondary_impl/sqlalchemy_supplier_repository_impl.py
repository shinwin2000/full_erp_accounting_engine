#!/usr/bin/env python3
"""
Module: sqlalchemy_supplier_repository_impl.py
SQLAlchemy implementation of SupplierRepositoryPort.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

# === TAMBAHAN: import port ===
from ports.primary.supplier_repository_port import SupplierRepositoryPort

logger = logging.getLogger(__name__)

Base = declarative_base()


class SupplierTable(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        Index("idx_supplier_legal_entity", "legal_entity_id"),
        Index("idx_supplier_code", "supplier_code", unique=True),
        Index("idx_supplier_npwp", "npwp"),
        Index("idx_supplier_category", "category"),
        Index("idx_supplier_status", "status"),
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
    category = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="ACTIVE")
    total_purchases = Column(Integer, nullable=False, default=0)
    last_purchase_date = Column(DateTime(timezone=True), nullable=True)
    blacklisted_reason = Column(Text, nullable=True)
    blacklisted_at = Column(DateTime(timezone=True), nullable=True)
    blacklisted_by = Column(PGUUID(as_uuid=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)


# === PERUBAHAN: warisi SupplierRepositoryPort ===
class SQLAlchemySupplierRepository(SupplierRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ==================== PORT METHODS ====================

    async def get_by_id(self, supplier_id: UUID) -> Any | None:
        session = await self._get_session()
        stmt = select(SupplierTable).where(SupplierTable.id == supplier_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_code(self, supplier_code: str, legal_entity_id: UUID) -> Any | None:
        session = await self._get_session()
        stmt = select(SupplierTable).where(
            SupplierTable.supplier_code == supplier_code,
            SupplierTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def is_active(self, supplier_id: UUID) -> bool:
        supplier = await self.get_by_id(supplier_id)
        return supplier is not None and getattr(supplier, 'is_active', False)

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
                existing.category = getattr(supplier, 'category', None)
                existing.status = getattr(supplier, 'status', 'ACTIVE')
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
                    category=getattr(supplier, 'category', None),
                    status="ACTIVE",
                    is_active=True,
                    created_by=supplier.created_by,
                )
                session.add(new)

    async def list_by_entity(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        session = await self._get_session()
        stmt = select(SupplierTable).where(
            SupplierTable.legal_entity_id == legal_entity_id
        ).order_by(SupplierTable.supplier_code).limit(limit).offset(offset)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    # ==================== EXTRA METHODS ====================

    async def add(self, supplier: Any) -> Any:
        session = await self._get_session()
        async with session.begin():
            stmt = select(SupplierTable).where(
                SupplierTable.supplier_code == supplier.supplier_code,
                SupplierTable.legal_entity_id == supplier.legal_entity_id,
            )
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                raise ValueError(f"Supplier with code {supplier.supplier_code} already exists")

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
                category=getattr(supplier, 'category', None),
                status="ACTIVE",
                is_active=True,
                created_by=supplier.created_by,
            )
            session.add(new)
            await session.flush()
            return self._to_domain(new)

    async def update(self, supplier: Any) -> Any:
        session = await self._get_session()
        async with session.begin():
            stmt = select(SupplierTable).where(
                SupplierTable.id == supplier.id,
                SupplierTable.legal_entity_id == supplier.legal_entity_id,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"Supplier {supplier.id} not found")

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
            existing.category = getattr(supplier, 'category', None)
            existing.is_active = getattr(supplier, 'is_active', True)
            existing.updated_at = datetime.utcnow()

            await session.flush()
            return self._to_domain(existing)

    async def delete(self, supplier_id: UUID, legal_entity_id: UUID, deleted_by: UUID | None = None) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = (
                update(SupplierTable)
                .where(
                    SupplierTable.id == supplier_id,
                    SupplierTable.legal_entity_id == legal_entity_id,
                )
                .values(
                    status="DELETED",
                    is_active=False,
                    updated_at=datetime.utcnow(),
                )
            )
            if deleted_by:
                stmt = stmt.values(deleted_by=deleted_by)
            await session.execute(stmt)

    async def get_by_npwp(self, npwp: str) -> Any | None:
        session = await self._get_session()
        stmt = select(SupplierTable).where(SupplierTable.npwp == npwp)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def find_by_name_contains(self, name: str, legal_entity_id: UUID, limit: int = 100) -> list[Any]:
        session = await self._get_session()
        stmt = (
            select(SupplierTable)
            .where(
                SupplierTable.supplier_name.ilike(f"%{name}%"),
                SupplierTable.legal_entity_id == legal_entity_id,
            )
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def find_active_for_po(self, legal_entity_id: UUID) -> list[Any]:
        session = await self._get_session()
        stmt = select(SupplierTable).where(
            SupplierTable.legal_entity_id == legal_entity_id,
            SupplierTable.status == "ACTIVE",
            SupplierTable.is_active == True,
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def find_by_category(self, category: str, legal_entity_id: UUID) -> list[Any]:
        session = await self._get_session()
        stmt = select(SupplierTable).where(
            SupplierTable.category == category,
            SupplierTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def add_purchase(self, supplier_id: UUID, purchase_order: Any) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = (
                update(SupplierTable)
                .where(SupplierTable.id == supplier_id)
                .values(
                    total_purchases=SupplierTable.total_purchases + 1,
                    last_purchase_date=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            await session.execute(stmt)

    async def blacklist(self, supplier_id: UUID, reason: str, blacklisted_by: str) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = (
                update(SupplierTable)
                .where(SupplierTable.id == supplier_id)
                .values(
                    status="BLACKLISTED",
                    is_active=False,
                    blacklisted_reason=reason,
                    blacklisted_by=UUID(blacklisted_by) if blacklisted_by else None,
                    blacklisted_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            await session.execute(stmt)

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        session = await self._get_session()
        stmt = select(SupplierTable).where(SupplierTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        rows = result.scalars().all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "legal_entity_id", "supplier_code", "supplier_name", "npwp",
            "email", "phone", "address", "city", "province", "postal_code",
            "country", "contact_person", "payment_term_days", "category",
            "status", "is_active", "created_at", "updated_at"
        ])
        for row in rows:
            writer.writerow([
                str(row.id), str(row.legal_entity_id), row.supplier_code,
                row.supplier_name, row.npwp or "", row.email or "", row.phone or "",
                row.address or "", row.city or "", row.province or "",
                row.postal_code or "", row.country or "", row.contact_person or "",
                row.payment_term_days, row.category or "", row.status,
                row.is_active, row.created_at.isoformat() if row.created_at else "",
                row.updated_at.isoformat() if row.updated_at else ""
            ])
        return output.getvalue()

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        session = await self._get_session()
        total_stmt = select(func.count()).select_from(SupplierTable).where(
            SupplierTable.legal_entity_id == legal_entity_id
        )
        total = await session.scalar(total_stmt) or 0

        active_stmt = select(func.count()).where(
            SupplierTable.legal_entity_id == legal_entity_id,
            SupplierTable.is_active == True,
        )
        active = await session.scalar(active_stmt) or 0

        category_stmt = select(
            SupplierTable.category, func.count()
        ).where(SupplierTable.legal_entity_id == legal_entity_id).group_by(SupplierTable.category)
        cat_result = await session.execute(category_stmt)
        categories = {cat: cnt for cat, cnt in cat_result.all()}

        status_stmt = select(
            SupplierTable.status, func.count()
        ).where(SupplierTable.legal_entity_id == legal_entity_id).group_by(SupplierTable.status)
        status_result = await session.execute(status_stmt)
        statuses = {st: cnt for st, cnt in status_result.all()}

        return {
            "total": total,
            "active": active,
            "inactive": total - active,
            "categories": categories,
            "statuses": statuses,
        }

    async def get_audit_log(self, supplier_id: UUID | None = None, limit: int = 100) -> list[dict]:
        if supplier_id:
            supplier = await self.get_by_id(supplier_id)
            if not supplier:
                return []
            return [{
                "timestamp": getattr(supplier, 'created_at', datetime.utcnow()).isoformat(),
                "action": "CREATE",
                "details": f"Supplier {supplier.supplier_name} created",
                "user": str(getattr(supplier, 'created_by', 'system'))
            }]
        return []

    async def health_check(self) -> dict[str, Any]:
        try:
            session = await self._get_session()
            await session.execute(text("SELECT 1"))
            return {
                "status": "healthy",
                "database": "connected",
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

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
            category=row.category,
            status=row.status,
            is_active=row.is_active,
            total_purchases=row.total_purchases,
            last_purchase_date=row.last_purchase_date,
            blacklisted_reason=row.blacklisted_reason,
            blacklisted_at=row.blacklisted_at,
            blacklisted_by=row.blacklisted_by,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


__all__ = ["SQLAlchemySupplierRepository", "SupplierTable"]
