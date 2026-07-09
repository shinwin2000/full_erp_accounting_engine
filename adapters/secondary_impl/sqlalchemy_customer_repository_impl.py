#!/usr/bin/env python3
"""
Module: sqlalchemy_customer_repository_impl.py
SQLAlchemy implementation of CustomerRepositoryPort.

This adapter implements the CustomerRepositoryPort interface defined in
ports/primary/customer_supplier_repository_port.py.

Big-4 Audit Grade: Full implementation with proper type hints, error handling,
logging, and audit trail.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
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
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.customer_repository_port import CustomerRepositoryPort

logger = logging.getLogger(__name__)

Base = declarative_base()


class CustomerTable(Base):
    """ORM model for customers table."""
    __tablename__ = "customers"
    __table_args__ = (
        Index("idx_customer_legal_entity", "legal_entity_id"),
        Index("idx_customer_code", "customer_code", unique=True),
        Index("idx_customer_npwp", "npwp", unique=True),
        Index("idx_customer_category", "category"),
        Index("idx_customer_status", "status"),
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
    credit_used = Column(Numeric(20, 2), nullable=False, default=0)
    credit_term_days = Column(Integer, nullable=False, default=30)
    category = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="ACTIVE")
    total_orders = Column(Integer, nullable=False, default=0)
    last_order_date = Column(DateTime(timezone=True), nullable=True)
    blacklisted_reason = Column(Text, nullable=True)
    blacklisted_at = Column(DateTime(timezone=True), nullable=True)
    blacklisted_by = Column(PGUUID(as_uuid=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class SQLAlchemyCustomerRepository(CustomerRepositoryPort):
    """
    SQLAlchemy-based implementation of CustomerRepositoryPort.

    This adapter provides full CRUD and business operations for Customer aggregate.
    """

    def __init__(self, session: Optional[AsyncSession] = None):
        self._session = session
        self._audit_log: list[dict] = []

    async def _get_session(self) -> AsyncSession:
        """Get or create an async session."""
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def _log_audit(self, action: str, customer_id: UUID, details: dict[str, Any]) -> None:
        """Log audit trail for customer operations."""
        self._audit_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "customer_id": str(customer_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    def _to_domain(self, row: CustomerTable) -> Any:
        """Convert ORM row to domain object (SimpleNamespace for demo)."""
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
            credit_used=row.credit_used,
            credit_term_days=row.credit_term_days,
            category=row.category,
            status=row.status,
            total_orders=row.total_orders,
            last_order_date=row.last_order_date,
            blacklisted_reason=row.blacklisted_reason,
            blacklisted_at=row.blacklisted_at,
            blacklisted_by=row.blacklisted_by,
            is_active=row.is_active,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
        )

    # ==================== CORE PORT METHODS ====================

    async def get_by_id(self, customer_id: UUID) -> Any | None:
        """Retrieve a customer by ID."""
        session = await self._get_session()
        stmt = select(CustomerTable).where(
            CustomerTable.id == customer_id,
            CustomerTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_code(self, legal_entity_id: UUID, customer_code: str) -> Any | None:
        """Retrieve a customer by entity and code."""
        session = await self._get_session()
        stmt = select(CustomerTable).where(
            CustomerTable.customer_code == customer_code,
            CustomerTable.legal_entity_id == legal_entity_id,
            CustomerTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def is_active(self, customer_id: UUID) -> bool:
        """Check if a customer is active."""
        customer = await self.get_by_id(customer_id)
        return customer is not None and getattr(customer, 'is_active', False)

    async def check_credit_limit(self, customer_id: UUID, invoice_amount: Any) -> bool:
        """Check if invoice amount is within customer's credit limit."""
        customer = await self.get_by_id(customer_id)
        if not customer:
            return False
        try:
            amount = Decimal(str(invoice_amount))
        except (ValueError, TypeError):
            return False
        available = customer.credit_limit - customer.credit_used
        return available >= amount

    async def save(self, customer: Any) -> None:
        """Save or update a customer."""
        session = await self._get_session()
        async with session.begin():
            stmt = select(CustomerTable).where(CustomerTable.id == customer.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            now = datetime.now(timezone.utc)
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
                existing.category = getattr(customer, 'category', None)
                existing.status = getattr(customer, 'status', 'ACTIVE')
                existing.is_active = getattr(customer, 'is_active', True)
                existing.updated_at = now
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
                    category=getattr(customer, 'category', None),
                    status="ACTIVE",
                    is_active=True,
                    created_by=getattr(customer, 'created_by', None),
                    created_at=now,
                )
                session.add(new)
            await session.flush()
            await self._log_audit("SAVE", customer.id, {"code": customer.customer_code})

    async def list_by_entity(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        """List customers by entity with pagination."""
        session = await self._get_session()
        stmt = select(CustomerTable).where(
            CustomerTable.legal_entity_id == legal_entity_id,
            CustomerTable.deleted_at.is_(None),
        ).order_by(CustomerTable.customer_code).limit(limit).offset(offset)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def add(self, customer: Any) -> Any:
        """Add a new customer."""
        session = await self._get_session()
        async with session.begin():
            stmt = select(CustomerTable).where(
                CustomerTable.customer_code == customer.customer_code,
                CustomerTable.legal_entity_id == customer.legal_entity_id,
            )
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                raise ValueError(f"Customer code {customer.customer_code} already exists")
            now = datetime.now(timezone.utc)
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
                category=getattr(customer, 'category', None),
                status="ACTIVE",
                is_active=True,
                created_by=getattr(customer, 'created_by', None),
                created_at=now,
            )
            session.add(new)
            await session.flush()
            await self._log_audit("ADD", new.id, {"code": new.customer_code})
            return self._to_domain(new)

    async def update(self, customer: Any) -> Any:
        """
        Update an existing customer with pessimistic locking.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # --- PESSIMISTIC LOCK: SELECT FOR UPDATE ---
            stmt = select(CustomerTable).where(
                CustomerTable.id == customer.id,
                CustomerTable.legal_entity_id == customer.legal_entity_id,
                CustomerTable.deleted_at.is_(None),
            ).with_for_update()

            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"Customer {customer.id} not found")

            now = datetime.now(timezone.utc)
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
            existing.credit_used = getattr(customer, 'credit_used', existing.credit_used)
            existing.credit_term_days = customer.credit_term_days
            existing.category = getattr(customer, 'category', None)
            existing.is_active = getattr(customer, 'is_active', True)
            existing.updated_at = now
            await session.flush()
            await self._log_audit("UPDATE", existing.id, {"code": existing.customer_code})
            return self._to_domain(existing)

    async def delete(self, customer_id: UUID, user_id: UUID | None = None, permanent: bool = False) -> bool:
        """
        Delete a customer (soft or hard delete) with pessimistic locking.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # --- PESSIMISTIC LOCK: SELECT FOR UPDATE ---
            stmt = select(CustomerTable).where(CustomerTable.id == customer_id).with_for_update()
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return False

            if permanent:
                await session.delete(row)
                await session.flush()
                await self._log_audit("DELETE_PERMANENT", customer_id, {"user_id": str(user_id) if user_id else None})
                return True
            else:
                now = datetime.now(timezone.utc)
                row.deleted_at = now
                row.is_active = False
                row.status = "INACTIVE"
                row.updated_at = now
                await session.flush()
                await self._log_audit("DELETE_SOFT", customer_id, {"user_id": str(user_id) if user_id else None})
                return True

    async def restore(self, customer_id: UUID, user_id: UUID | None = None) -> bool:
        """Restore a soft-deleted customer."""
        session = await self._get_session()
        async with session.begin():
            stmt = select(CustomerTable).where(
                CustomerTable.id == customer_id,
                CustomerTable.deleted_at.is_not(None),
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return False
            now = datetime.now(timezone.utc)
            row.deleted_at = None
            row.is_active = True
            row.status = "ACTIVE"
            row.updated_at = now
            await session.flush()
            await self._log_audit("RESTORE", customer_id, {"user_id": str(user_id) if user_id else None})
            return True

    async def find_active(self, legal_entity_id: UUID) -> list[Any]:
        """Find all active customers for an entity."""
        session = await self._get_session()
        stmt = select(CustomerTable).where(
            CustomerTable.legal_entity_id == legal_entity_id,
            CustomerTable.is_active == True,
            CustomerTable.deleted_at.is_(None),
        ).order_by(CustomerTable.customer_code)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def find_by_category(self, category: str, legal_entity_id: UUID) -> list[Any]:
        """Find customers by category."""
        session = await self._get_session()
        stmt = select(CustomerTable).where(
            CustomerTable.category == category,
            CustomerTable.legal_entity_id == legal_entity_id,
            CustomerTable.deleted_at.is_(None),
        ).order_by(CustomerTable.customer_code)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def find_by_name_contains(self, name_fragment: str, legal_entity_id: UUID, limit: int = 100) -> list[Any]:
        """Find customers by name fragment (case-insensitive)."""
        session = await self._get_session()
        stmt = select(CustomerTable).where(
            CustomerTable.customer_name.ilike(f"%{name_fragment}%"),
            CustomerTable.legal_entity_id == legal_entity_id,
            CustomerTable.deleted_at.is_(None),
        ).limit(limit).order_by(CustomerTable.customer_name)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        """Export customers to CSV format."""
        customers = await self.list_by_entity(legal_entity_id, limit=10000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "customer_code", "customer_name", "npwp", "email", "phone",
            "address", "city", "province", "postal_code", "country",
            "contact_person", "credit_limit", "credit_used", "credit_term_days",
            "category", "status", "is_active", "total_orders", "last_order_date"
        ])
        for c in customers:
            writer.writerow([
                str(c.id), c.customer_code, c.customer_name, c.npwp or "", c.email or "",
                c.phone or "", c.address or "", c.city or "", c.province or "",
                c.postal_code or "", c.country or "", c.contact_person or "",
                float(c.credit_limit), float(c.credit_used), c.credit_term_days,
                c.category or "", c.status, c.is_active, c.total_orders,
                c.last_order_date.isoformat() if c.last_order_date else ""
            ])
        return output.getvalue()

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Get statistics for customers under an entity."""
        session = await self._get_session()
        total = await session.scalar(
            select(func.count()).where(
                CustomerTable.legal_entity_id == legal_entity_id,
                CustomerTable.deleted_at.is_(None),
            )
        ) or 0

        active = await session.scalar(
            select(func.count()).where(
                CustomerTable.legal_entity_id == legal_entity_id,
                CustomerTable.is_active == True,
                CustomerTable.deleted_at.is_(None),
            )
        ) or 0

        blacklisted = await session.scalar(
            select(func.count()).where(
                CustomerTable.legal_entity_id == legal_entity_id,
                CustomerTable.status == "BLACKLISTED",
                CustomerTable.deleted_at.is_(None),
            )
        ) or 0

        cat_result = await session.execute(
            select(
                CustomerTable.category, func.count()
            ).where(
                CustomerTable.legal_entity_id == legal_entity_id,
                CustomerTable.deleted_at.is_(None),
            ).group_by(CustomerTable.category)
        )
        categories = {cat: cnt for cat, cnt in cat_result.all()}

        return {
            "total": total,
            "active": active,
            "inactive": total - active - blacklisted,
            "blacklisted": blacklisted,
            "categories": categories,
        }

    async def get_audit_log(self, customer_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Retrieve audit log for customer operations."""
        logs = self._audit_log
        if customer_id:
            logs = [l for l in logs if l.get("customer_id") == str(customer_id)]
        return logs[-limit:]

    async def health_check(self) -> dict[str, Any]:
        """Check database connectivity health."""
        try:
            session = await self._get_session()
            await session.execute(text("SELECT 1"))
            return {"status": "healthy", "database": "connected", "timestamp": datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            return {"status": "unhealthy", "database": "disconnected", "error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}

    async def add_order(self, customer_id: UUID, order: Any) -> None:
        """Increment order count for a customer."""
        session = await self._get_session()
        async with session.begin():
            now = datetime.now(timezone.utc)
            stmt = (
                update(CustomerTable)
                .where(CustomerTable.id == customer_id)
                .values(
                    total_orders=CustomerTable.total_orders + 1,
                    last_order_date=now,
                    updated_at=now,
                )
            )
            await session.execute(stmt)
            await self._log_audit("ADD_ORDER", customer_id, {"order_id": str(order.id) if hasattr(order, 'id') else None})

    async def blacklist(self, customer_id: UUID, reason: str, blacklisted_by: str) -> bool:
        """Blacklist a customer."""
        session = await self._get_session()
        async with session.begin():
            stmt = select(CustomerTable).where(CustomerTable.id == customer_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return False
            now = datetime.now(timezone.utc)
            row.status = "BLACKLISTED"
            row.is_active = False
            row.blacklisted_reason = reason
            row.blacklisted_by = UUID(blacklisted_by) if blacklisted_by else None
            row.blacklisted_at = now
            row.updated_at = now
            await session.flush()
            await self._log_audit("BLACKLIST", customer_id, {"reason": reason, "by": blacklisted_by})
            return True

    async def update_credit_usage(self, customer_id: UUID, amount_used: Decimal) -> None:
        """
        Update credit usage with pessimistic locking.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # --- PESSIMISTIC LOCK: SELECT FOR UPDATE ---
            stmt = select(CustomerTable).where(CustomerTable.id == customer_id).with_for_update()
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                raise ValueError(f"Customer {customer_id} not found")

            row.credit_used += amount_used
            row.updated_at = datetime.now(timezone.utc)
            await session.flush()
            await self._log_audit("UPDATE_CREDIT", customer_id, {"amount": float(amount_used)})


# Alias for backward compatibility
SQLAlchemyCustomerRepositoryImpl = SQLAlchemyCustomerRepository


__all__ = [
    "CustomerTable",
    "SQLAlchemyCustomerRepository",
    "SQLAlchemyCustomerRepositoryImpl",
]