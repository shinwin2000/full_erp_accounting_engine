#!/usr/bin/env python3
"""
Module: sqlalchemy_employee_repository_impl.py
Layer: Adapters / Secondary / Implementation
Responsibility: SQLAlchemy implementation of EmployeeRepositoryPort.

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

from ports.primary.employee_repository_port import EmployeeRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# SQLAlchemy ORM Model
# ============================================================================

Base = declarative_base()


class EmployeeTable(Base):
    __tablename__ = "employees"
    __table_args__ = (
        Index("idx_employee_legal_entity", "legal_entity_id"),
        Index("idx_employee_code", "employee_code", unique=True),
        Index("idx_employee_npwp", "npwp"),
        Index("idx_employee_email", "email"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    employee_code = Column(String(50), nullable=False, unique=True)
    employee_name = Column(String(200), nullable=False)
    npwp = Column(String(20), nullable=True)
    email = Column(String(200), nullable=True)
    phone = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    province = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=True)
    country = Column(String(100), nullable=True, default="Indonesia")
    position = Column(String(100), nullable=True)
    department = Column(String(100), nullable=True)
    hourly_rate = Column(Numeric(20, 2), nullable=False, default=0)
    monthly_salary = Column(Numeric(20, 2), nullable=False, default=0)
    bank_account = Column(String(50), nullable=True)
    bank_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)


# ============================================================================
# Repository Implementation
# ============================================================================


class SQLAlchemyEmployeeRepository(EmployeeRepositoryPort):
    """SQLAlchemy implementation of EmployeeRepositoryPort."""

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def save(self, employee) -> None:
        """Save or update an employee."""
        session = await self._get_session()
        async with session.begin():
            stmt = select(EmployeeTable).where(EmployeeTable.id == employee.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                existing.employee_code = employee.employee_code
                existing.employee_name = employee.employee_name
                existing.npwp = employee.npwp
                existing.email = employee.email
                existing.phone = employee.phone
                existing.address = employee.address
                existing.city = employee.city
                existing.province = employee.province
                existing.postal_code = employee.postal_code
                existing.country = employee.country
                existing.position = employee.position
                existing.department = employee.department
                existing.hourly_rate = employee.hourly_rate
                existing.monthly_salary = employee.monthly_salary
                existing.bank_account = employee.bank_account
                existing.bank_name = employee.bank_name
                existing.is_active = employee.is_active
                existing.updated_at = datetime.utcnow()
            else:
                # Insert new
                new_row = EmployeeTable(
                    id=employee.id,
                    legal_entity_id=employee.legal_entity_id,
                    employee_code=employee.employee_code,
                    employee_name=employee.employee_name,
                    npwp=employee.npwp,
                    email=employee.email,
                    phone=employee.phone,
                    address=employee.address,
                    city=employee.city,
                    province=employee.province,
                    postal_code=employee.postal_code,
                    country=employee.country,
                    position=employee.position,
                    department=employee.department,
                    hourly_rate=employee.hourly_rate,
                    monthly_salary=employee.monthly_salary,
                    bank_account=employee.bank_account,
                    bank_name=employee.bank_name,
                    is_active=employee.is_active,
                    created_by=employee.created_by,
                )
                session.add(new_row)

    async def get_by_id(self, employee_id: UUID):
        """Get employee by ID."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(EmployeeTable.id == employee_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._to_domain(row)

    async def get_by_code(self, employee_code: str, legal_entity_id: UUID):
        """Get employee by code within legal entity."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.employee_code == employee_code,
            EmployeeTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._to_domain(row)

    async def list_by_legal_entity(
        self, legal_entity_id: UUID, is_active: bool | None = None
    ) -> list:
        """List employees for a legal entity."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(EmployeeTable.legal_entity_id == legal_entity_id)
        if is_active is not None:
            stmt = stmt.where(EmployeeTable.is_active == is_active)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def update_status(self, employee_id: UUID, is_active: bool) -> None:
        """Update employee active status."""
        session = await self._get_session()
        async with session.begin():
            stmt = (
                update(EmployeeTable)
                .where(EmployeeTable.id == employee_id)
                .values(is_active=is_active, updated_at=datetime.utcnow())
            )
            await session.execute(stmt)

    async def delete(self, employee_id: UUID) -> None:
        """Delete an employee (hard delete)."""
        session = await self._get_session()
        async with session.begin():
            await session.execute(delete(EmployeeTable).where(EmployeeTable.id == employee_id))

    async def get_by_email(self, email: str) -> Optional:
        """Get employee by email."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(EmployeeTable.email == email)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._to_domain(row)

    def _to_domain(self, row: EmployeeTable):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=row.id,
            legal_entity_id=row.legal_entity_id,
            employee_code=row.employee_code,
            employee_name=row.employee_name,
            npwp=row.npwp,
            email=row.email,
            phone=row.phone,
            address=row.address,
            city=row.city,
            province=row.province,
            postal_code=row.postal_code,
            country=row.country,
            position=row.position,
            department=row.department,
            hourly_rate=row.hourly_rate,
            monthly_salary=row.monthly_salary,
            bank_account=row.bank_account,
            bank_name=row.bank_name,
            is_active=row.is_active,
            created_by=row.created_by,
            created_at=row.created_at,
        )


__all__ = ["EmployeeTable", "SQLAlchemyEmployeeRepository"]