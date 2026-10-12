#!/usr/bin/env python3
"""
Module: sqlalchemy_customer_repository_impl.py
Layer: Adapters (Secondary)
Responsibility: SQLAlchemy implementation of CustomerRepositoryPort.

PERBAIKAN BESAR (2026-10-12):
- TIDAK LAGI mendefinisikan CustomerTable sendiri. Menggunakan
  CustomerTable dari infrastructure/persistence_orm/customer_table.py
  (tabel `customer` singular + 8 tabel anak).
- Menghapus definisi tabel duplikat (`customers` plural).
- begin_nested() (SAVEPOINT) untuk menghindari nested transaction error.
- _get_session() memakai get_async_session_direct() (bukan
  get_async_session() yang merupakan async generator untuk FastAPI Depends).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.customer_table import CustomerTable
from ports.primary.customer_repository_port import CustomerRepositoryPort

logger = logging.getLogger(__name__)


class SQLAlchemyCustomerRepository(CustomerRepositoryPort):
    """
    SQLAlchemy-based implementation of CustomerRepositoryPort.
    Menggunakan CustomerTable dari infrastructure.persistence_orm.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: list[dict[str, Any]] = []

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import (
                get_async_session_direct,
            )
            self._session = await get_async_session_direct()
        return self._session

    async def _log_audit(
        self, action: str, customer_id: UUID, details: dict[str, Any]
    ) -> None:
        self._audit_log.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "customer_id": str(customer_id),
                "details": details,
            }
        )
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    def _to_domain(self, row: CustomerTable) -> Any:
        """Map ORM row -> domain object (SimpleNamespace)."""
        return SimpleNamespace(
            id=row.id,
            legal_entity_id=row.legal_entity_id,
            customer_code=row.customer_code,
            customer_name=row.customer_name,
            company_name=row.company_name,
            customer_type=row.customer_type,
            npwp=row.tax_id,
            tax_id=row.tax_id,
            tax_status=row.tax_status,
            is_taxable=row.is_taxable,
            email=row.email,
            phone=row.phone,
            mobile=row.mobile,
            address=row.address,
            city=row.city,
            province=row.province,
            district=row.district,
            postal_code=row.postal_code,
            country=row.country,
            contact_person=row.contact_person,
            contact_phone=row.contact_phone,
            contact_email=row.contact_email,
            credit_limit=row.credit_limit,
            credit_used=row.used_credit,
            used_credit=row.used_credit,
            opening_balance=row.opening_balance,
            current_balance=row.current_balance,
            currency=row.currency,
            payment_term_days=row.payment_term_days,
            credit_term_days=row.payment_term_days,
            discount_percent=row.discount_percent,
            category=row.category,
            price_group=row.price_group,
            status=row.status,
            is_active=row.is_active,
            is_blacklist=row.is_blacklist,
            blocked_reason=row.blocked_reason,
            created_by=row.created_by,
            updated_by=row.updated_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
            version=row.version,
        )

    # ==================== CORE PORT METHODS ====================

    async def get_by_id(self, customer_id: UUID) -> Any | None:
        session = await self._get_session()
        stmt = select(CustomerTable).where(
            CustomerTable.id == customer_id,
            CustomerTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_code(
        self, legal_entity_id: UUID, customer_code: str
    ) -> Any | None:
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
        customer = await self.get_by_id(customer_id)
        return customer is not None and getattr(customer, "is_active", False)

    async def check_credit_limit(
        self, customer_id: UUID, invoice_amount: Any
    ) -> bool:
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
        session = await self._get_session()
        async with session.begin_nested():
            stmt = select(CustomerTable).where(CustomerTable.id == customer.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            now = datetime.now(UTC)
            if existing:
                existing.customer_code = customer.customer_code
                existing.customer_name = customer.customer_name
                existing.company_name = getattr(customer, "company_name", None)
                existing.tax_id = getattr(customer, "tax_id", None) or getattr(
                    customer, "npwp", None
                )
                existing.email = customer.email
                existing.phone = customer.phone
                existing.mobile = getattr(customer, "mobile", None)
                existing.address = customer.address
                existing.city = customer.city
                existing.province = customer.province
                existing.postal_code = customer.postal_code
                existing.country = customer.country
                existing.contact_person = customer.contact_person
                existing.credit_limit = customer.credit_limit
                existing.payment_term_days = getattr(
                    customer, "payment_term_days", 30
                )
                existing.category = getattr(customer, "category", None)
                existing.status = getattr(customer, "status", "active")
                existing.is_active = getattr(customer, "is_active", True)
                existing.updated_at = now
            else:
                new = CustomerTable(
                    id=customer.id or uuid4(),
                    legal_entity_id=customer.legal_entity_id,
                    customer_code=customer.customer_code,
                    customer_name=customer.customer_name,
                    company_name=getattr(customer, "company_name", None),
                    customer_type=getattr(customer, "customer_type", "company"),
                    tax_id=getattr(customer, "tax_id", None)
                    or getattr(customer, "npwp", None),
                    email=customer.email,
                    phone=customer.phone,
                    mobile=getattr(customer, "mobile", None),
                    address=customer.address,
                    city=customer.city,
                    province=customer.province,
                    postal_code=customer.postal_code,
                    country=getattr(customer, "country", "ID"),
                    contact_person=customer.contact_person,
                    credit_limit=customer.credit_limit,
                    payment_term_days=getattr(customer, "payment_term_days", 30),
                    category=getattr(customer, "category", None),
                    status="active",
                    is_active=True,
                    created_by=getattr(customer, "created_by", None),
                    created_at=now,
                )
                session.add(new)
            await session.flush()
            await self._log_audit(
                "SAVE", customer.id, {"code": customer.customer_code}
            )

    async def list_by_entity(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        session = await self._get_session()
        stmt = (
            select(CustomerTable)
            .where(
                CustomerTable.legal_entity_id == legal_entity_id,
                CustomerTable.deleted_at.is_(None),
            )
            .order_by(CustomerTable.customer_code)
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    # ==================== EXTENDED METHODS ====================

    async def add(self, customer: Any) -> Any:
        session = await self._get_session()
        async with session.begin_nested():
            stmt = select(CustomerTable).where(
                CustomerTable.customer_code == customer.customer_code,
                CustomerTable.legal_entity_id == customer.legal_entity_id,
            )
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                raise ValueError(
                    f"Customer code {customer.customer_code} already exists"
                )
            now = datetime.now(UTC)
            new = CustomerTable(
                id=customer.id or uuid4(),
                legal_entity_id=customer.legal_entity_id,
                customer_code=customer.customer_code,
                customer_name=customer.customer_name,
                company_name=getattr(customer, "company_name", None),
                customer_type=getattr(customer, "customer_type", "company"),
                tax_id=getattr(customer, "tax_id", None)
                or getattr(customer, "npwp", None),
                email=customer.email,
                phone=customer.phone,
                mobile=getattr(customer, "mobile", None),
                address=customer.address,
                city=customer.city,
                province=customer.province,
                postal_code=customer.postal_code,
                country=getattr(customer, "country", "ID"),
                contact_person=customer.contact_person,
                credit_limit=customer.credit_limit,
                payment_term_days=getattr(customer, "payment_term_days", 30),
                category=getattr(customer, "category", None),
                status="active",
                is_active=True,
                created_by=getattr(customer, "created_by", None),
                created_at=now,
            )
            session.add(new)
            await session.flush()
            await self._log_audit("ADD", new.id, {"code": new.customer_code})
            return self._to_domain(new)

    async def update(self, customer: Any) -> Any:
        """Update dengan pessimistic lock via begin_nested (SAVEPOINT)."""
        session = await self._get_session()
        async with session.begin_nested():
            stmt = (
                select(CustomerTable)
                .where(
                    CustomerTable.id == customer.id,
                    CustomerTable.legal_entity_id == customer.legal_entity_id,
                    CustomerTable.deleted_at.is_(None),
                )
                .with_for_update()
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"Customer {customer.id} not found")

            now = datetime.now(UTC)
            existing.customer_code = customer.customer_code
            existing.customer_name = customer.customer_name
            existing.company_name = getattr(customer, "company_name", None)
            existing.tax_id = getattr(customer, "tax_id", None) or getattr(
                customer, "npwp", None
            )
            existing.email = customer.email
            existing.phone = customer.phone
            existing.mobile = getattr(customer, "mobile", None)
            existing.address = customer.address
            existing.city = customer.city
            existing.province = customer.province
            existing.postal_code = customer.postal_code
            existing.country = customer.country
            existing.contact_person = customer.contact_person
            existing.credit_limit = customer.credit_limit
            existing.used_credit = getattr(
                customer, "credit_used", existing.used_credit
            )
            existing.payment_term_days = getattr(customer, "payment_term_days", 30)
            existing.category = getattr(customer, "category", None)
            existing.is_active = getattr(customer, "is_active", True)
            existing.updated_at = now
            await session.flush()
            await self._log_audit(
                "UPDATE", existing.id, {"code": existing.customer_code}
            )
            return self._to_domain(existing)

    async def delete(
        self,
        customer_id: UUID,
        user_id: UUID | None = None,
        permanent: bool = False,
    ) -> bool:
        session = await self._get_session()
        async with session.begin_nested():
            stmt = (
                select(CustomerTable)
                .where(CustomerTable.id == customer_id)
                .with_for_update()
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return False

            if permanent:
                await session.delete(row)
                await session.flush()
                await self._log_audit(
                    "DELETE_PERMANENT",
                    customer_id,
                    {"user_id": str(user_id) if user_id else None},
                )
                return True

            now = datetime.now(UTC)
            row.deleted_at = now
            row.is_active = False
            row.status = "inactive"
            row.updated_at = now
            await session.flush()
            await self._log_audit(
                "DELETE_SOFT",
                customer_id,
                {"user_id": str(user_id) if user_id else None},
            )
            return True

    async def restore(
        self, customer_id: UUID, user_id: UUID | None = None
    ) -> bool:
        session = await self._get_session()
        async with session.begin_nested():
            stmt = select(CustomerTable).where(
                CustomerTable.id == customer_id,
                CustomerTable.deleted_at.is_not(None),
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return False
            now = datetime.now(UTC)
            row.deleted_at = None
            row.is_active = True
            row.status = "active"
            row.updated_at = now
            await session.flush()
            await self._log_audit(
                "RESTORE", customer_id, {"user_id": str(user_id) if user_id else None}
            )
            return True

    async def find_active(self, legal_entity_id: UUID) -> list[Any]:
        session = await self._get_session()
        stmt = (
            select(CustomerTable)
            .where(
                CustomerTable.legal_entity_id == legal_entity_id,
                CustomerTable.is_active.is_(True),
                CustomerTable.deleted_at.is_(None),
            )
            .order_by(CustomerTable.customer_code)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def find_by_category(
        self, category: str, legal_entity_id: UUID
    ) -> list[Any]:
        session = await self._get_session()
        stmt = (
            select(CustomerTable)
            .where(
                CustomerTable.category == category,
                CustomerTable.legal_entity_id == legal_entity_id,
                CustomerTable.deleted_at.is_(None),
            )
            .order_by(CustomerTable.customer_code)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def find_by_name_contains(
        self, name_fragment: str, legal_entity_id: UUID, limit: int = 100
    ) -> list[Any]:
        session = await self._get_session()
        stmt = (
            select(CustomerTable)
            .where(
                CustomerTable.customer_name.ilike(f"%{name_fragment}%"),
                CustomerTable.legal_entity_id == legal_entity_id,
                CustomerTable.deleted_at.is_(None),
            )
            .limit(limit)
            .order_by(CustomerTable.customer_name)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        customers = await self.list_by_entity(legal_entity_id, limit=10000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id", "customer_code", "customer_name", "tax_id", "email", "phone",
                "address", "city", "province", "postal_code", "country",
                "contact_person", "credit_limit", "used_credit", "payment_term_days",
                "category", "status", "is_active",
            ]
        )
        for c in customers:
            writer.writerow(
                [
                    str(c.id), c.customer_code, c.customer_name, c.tax_id or "",
                    c.email or "", c.phone or "", c.address or "", c.city or "",
                    c.province or "", c.postal_code or "", c.country or "",
                    c.contact_person or "", float(c.credit_limit),
                    float(c.credit_used), c.payment_term_days, c.category or "",
                    c.status, c.is_active,
                ]
            )
        return output.getvalue()

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        session = await self._get_session()
        total = (
            await session.scalar(
                select(func.count()).where(
                    CustomerTable.legal_entity_id == legal_entity_id,
                    CustomerTable.deleted_at.is_(None),
                )
            )
            or 0
        )
        active = (
            await session.scalar(
                select(func.count()).where(
                    CustomerTable.legal_entity_id == legal_entity_id,
                    CustomerTable.is_active.is_(True),
                    CustomerTable.deleted_at.is_(None),
                )
            )
            or 0
        )
        blacklisted = (
            await session.scalar(
                select(func.count()).where(
                    CustomerTable.legal_entity_id == legal_entity_id,
                    CustomerTable.is_blacklist.is_(True),
                    CustomerTable.deleted_at.is_(None),
                )
            )
            or 0
        )
        cat_result = await session.execute(
            select(CustomerTable.category, func.count())
            .where(
                CustomerTable.legal_entity_id == legal_entity_id,
                CustomerTable.deleted_at.is_(None),
            )
            .group_by(CustomerTable.category)
        )
        categories = {cat: cnt for cat, cnt in cat_result.all()}
        return {
            "total": total,
            "active": active,
            "inactive": total - active - blacklisted,
            "blacklisted": blacklisted,
            "categories": categories,
        }

    async def get_audit_log(
        self, customer_id: UUID | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        logs = self._audit_log
        if customer_id:
            logs = [entry for entry in logs if entry.get("customer_id") == str(customer_id)]
        return logs[-limit:]

    async def health_check(self) -> dict[str, Any]:
        try:
            session = await self._get_session()
            await session.execute(text("SELECT 1"))
            return {
                "status": "healthy",
                "database": "connected",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    async def blacklist(
        self, customer_id: UUID, reason: str, blacklisted_by: str
    ) -> bool:
        session = await self._get_session()
        async with session.begin_nested():
            stmt = select(CustomerTable).where(CustomerTable.id == customer_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return False
            now = datetime.now(UTC)
            row.status = "blacklisted"
            row.is_active = False
            row.is_blacklist = True
            row.blocked_reason = reason
            row.updated_at = now
            await session.flush()
            await self._log_audit(
                "BLACKLIST", customer_id, {"reason": reason, "by": blacklisted_by}
            )
            return True

    async def update_credit_usage(
        self, customer_id: UUID, amount_used: Decimal
    ) -> None:
        session = await self._get_session()
        async with session.begin_nested():
            stmt = (
                select(CustomerTable)
                .where(CustomerTable.id == customer_id)
                .with_for_update()
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                raise ValueError(f"Customer {customer_id} not found")
            row.used_credit += amount_used
            row.updated_at = datetime.now(UTC)
            await session.flush()
            await self._log_audit(
                "UPDATE_CREDIT", customer_id, {"amount": float(amount_used)}
            )


# Alias for backward compatibility
SQLAlchemyCustomerRepositoryImpl = SQLAlchemyCustomerRepository


__all__ = [
    "SQLAlchemyCustomerRepository",
    "SQLAlchemyCustomerRepositoryImpl",
]
