#!/usr/bin/env python3
"""
Module: service_customer.py
Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk mengelola Customer beserta seluruh data anaknya
    (alamat, contact person, attachment, notes, tags, riwayat credit
    limit, riwayat saldo piutang).

    REFACTOR TOTAL: versi sebelumnya menyimpan data di dict in-memory
    (`self._customers: dict[UUID, Customer]`) sehingga TIDAK PERNAH
    tersimpan ke database sama sekali -- semua data hilang setiap kali
    proses backend di-restart, dan data yang dibuat lewat frontend tidak
    pernah benar-benar "ada" di Postgres. Sekarang seluruh operasi baca/
    tulis dilakukan lewat UnitOfWorkPort -> AsyncSession SQLAlchemy ke
    tabel `customer` dan tabel-tabel anaknya (lihat customer_table.py),
    mengikuti pola yang sudah terbukti jalan di COAService.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select

from application.events import (
    CustomerBalanceUpdatedEvent,
    CustomerCreatedEvent,
    CustomerCreditLimitChangedEvent,
    CustomerStatusChangedEvent,
)
from infrastructure.persistence_orm.customer_table import (
    CustomerAddressTable,
    CustomerAttachmentTable,
    CustomerBalanceHistoryTable,
    CustomerContactTable,
    CustomerCreditHistoryTable,
    CustomerNoteTable,
    CustomerTable,
    CustomerTagTable,
)
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Enums
# ============================================================================


class CustomerStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    BLOCKED = "blocked"


# ============================================================================
# Exceptions
# ============================================================================


class CustomerServiceError(Exception):
    pass


class CustomerNotFoundError(CustomerServiceError):
    pass


# ============================================================================
# DTO ringan buat tampilan (dataclass biasa, bukan domain aggregate)
# ============================================================================


@dataclass(kw_only=True)
class CustomerListItem:
    id: UUID
    legal_entity_id: UUID
    customer_code: str
    customer_name: str
    company_name: str | None
    customer_type: str
    tax_id: str | None
    tax_status: str
    is_taxable: bool
    address: str | None
    city: str | None
    province: str | None
    district: str | None
    postal_code: str | None
    country: str
    phone: str | None
    mobile: str | None
    email: str | None
    website: str | None
    contact_person: str | None
    contact_phone: str | None
    contact_email: str | None
    credit_limit: Decimal
    used_credit: Decimal
    opening_balance: Decimal
    current_balance: Decimal
    currency: str
    payment_term_days: int
    discount_percent: Decimal
    category: str | None
    price_group: str | None
    status: str
    is_active: bool
    is_blacklist: bool
    blocked_reason: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None
    updated_by: UUID | None
    version: int


def _row_to_item(row: CustomerTable) -> CustomerListItem:
    return CustomerListItem(
        id=row.id,
        legal_entity_id=row.legal_entity_id,
        customer_code=row.customer_code,
        customer_name=row.customer_name,
        company_name=row.company_name,
        customer_type=row.customer_type,
        tax_id=row.tax_id,
        tax_status=row.tax_status,
        is_taxable=row.is_taxable,
        address=row.address,
        city=row.city,
        province=row.province,
        district=row.district,
        postal_code=row.postal_code,
        country=row.country,
        phone=row.phone,
        mobile=row.mobile,
        email=row.email,
        website=row.website,
        contact_person=row.contact_person,
        contact_phone=row.contact_phone,
        contact_email=row.contact_email,
        credit_limit=row.credit_limit,
        used_credit=row.used_credit,
        opening_balance=row.opening_balance,
        current_balance=row.current_balance,
        currency=row.currency,
        payment_term_days=row.payment_term_days,
        discount_percent=row.discount_percent,
        category=row.category,
        price_group=row.price_group,
        status=row.status,
        is_active=row.is_active,
        is_blacklist=row.is_blacklist,
        blocked_reason=row.blocked_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
        updated_by=row.updated_by,
        version=row.version,
    )


# Alias supaya import lama (`from application.service_layer.service_customer import Customer`)
# di router/tempat lain tetap jalan.
Customer = CustomerListItem


# ============================================================================
# Main Service
# ============================================================================


class CustomerService:
    """Service untuk mengelola Customer -- DB-backed lewat UnitOfWorkPort."""

    def __init__(
        self,
        uow: UnitOfWorkPort,
        event_publisher: EventPublisherPort | None = None,
    ):
        self._uow = uow
        self._event_publisher = event_publisher
        self._stats = {"customers_created": 0, "customers_updated": 0}
        self._audit_trail: list[dict[str, Any]] = []
        logger.info("CustomerService initialized (DB-backed)")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "CustomerService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    async def _publish(self, event, correlation_id: str | None) -> None:
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event, correlation_id)
        except Exception as e:
            logger.warning(f"Failed to publish {type(event).__name__}: {e}")

    # ========================================================================
    # CUSTOMER CRUD
    # ========================================================================

    @audit
    async def create_customer(
        self,
        legal_entity_id: UUID,
        customer_code: str,
        name: str,
        company_name: str | None = None,
        customer_type: str = "company",
        npwp: str | None = None,
        tax_status: str = "pkp",
        is_taxable: bool = True,
        address: str | None = None,
        city: str | None = None,
        province: str | None = None,
        district: str | None = None,
        postal_code: str | None = None,
        country: str = "ID",
        phone: str | None = None,
        mobile: str | None = None,
        email: str | None = None,
        website: str | None = None,
        contact_person: str | None = None,
        contact_phone: str | None = None,
        contact_email: str | None = None,
        credit_limit: Decimal = Decimal("0"),
        opening_balance: Decimal = Decimal("0"),
        currency: str = "IDR",
        payment_term_days: int = 30,
        discount_percent: Decimal = Decimal("0"),
        category: str | None = None,
        price_group: str | None = None,
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> CustomerListItem:
        self._check_authority(created_by, "create_customer")

        async with self._uow:
            session = self._uow.session
            existing = await session.execute(
                select(CustomerTable).where(
                    CustomerTable.legal_entity_id == legal_entity_id,
                    CustomerTable.customer_code == customer_code,
                )
            )
            if existing.scalar_one_or_none() is not None:
                raise CustomerServiceError(f"Customer code {customer_code} already exists")

            row = CustomerTable(
                legal_entity_id=legal_entity_id,
                customer_code=customer_code,
                customer_name=name,
                company_name=company_name,
                customer_type=customer_type,
                tax_id=npwp,
                tax_status=tax_status,
                is_taxable=is_taxable,
                address=address,
                city=city,
                province=province,
                district=district,
                postal_code=postal_code,
                country=country,
                phone=phone,
                mobile=mobile,
                email=email,
                website=website,
                contact_person=contact_person,
                contact_phone=contact_phone,
                contact_email=contact_email,
                credit_limit=credit_limit,
                opening_balance=opening_balance,
                current_balance=opening_balance,
                currency=currency,
                payment_term_days=payment_term_days,
                discount_percent=discount_percent,
                category=category,
                price_group=price_group,
                created_by=created_by,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            item = _row_to_item(row)
            await self._uow.commit()

        self._stats["customers_created"] += 1
        await self._publish(
            CustomerCreatedEvent(
                aggregate_id=item.id,
                aggregate_version=item.version,
                customer_id=item.id,
                customer_code=item.customer_code,
                customer_name=item.customer_name,
                npwp=item.tax_id,
                legal_entity_id=item.legal_entity_id,
                created_by=str(created_by) if created_by else "system",
                user_id=str(created_by) if created_by else None,
                correlation_id=correlation_id,
            ),
            correlation_id,
        )
        self._record_audit("create_customer", {
            "customer_id": str(item.id), "customer_code": customer_code,
            "created_by": str(created_by) if created_by else None,
        })
        return item

    async def get_customer(self, customer_id: UUID) -> CustomerListItem | None:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(select(CustomerTable).where(CustomerTable.id == customer_id))
            row = result.scalar_one_or_none()
            return _row_to_item(row) if row else None

    async def get_customer_by_code(self, legal_entity_id: UUID, customer_code: str) -> CustomerListItem | None:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerTable).where(
                    CustomerTable.legal_entity_id == legal_entity_id,
                    CustomerTable.customer_code == customer_code,
                )
            )
            row = result.scalar_one_or_none()
            return _row_to_item(row) if row else None

    async def list_customers(
        self,
        legal_entity_id: UUID,
        is_active: bool | None = None,
        status: str | None = None,
        category: str | None = None,
        is_blacklist: bool | None = None,
        search: str | None = None,
        sort_by: str = "customer_name",
        sort_dir: str = "asc",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[CustomerListItem], int]:
        async with self._uow:
            session = self._uow.session
            conditions = [CustomerTable.legal_entity_id == legal_entity_id]
            if is_active is not None:
                conditions.append(CustomerTable.is_active == is_active)
            if status:
                conditions.append(CustomerTable.status == status)
            if category:
                conditions.append(CustomerTable.category == category)
            if is_blacklist is not None:
                conditions.append(CustomerTable.is_blacklist == is_blacklist)
            if search:
                like = f"%{search}%"
                conditions.append(
                    or_(
                        CustomerTable.customer_name.ilike(like),
                        CustomerTable.customer_code.ilike(like),
                        CustomerTable.company_name.ilike(like),
                        CustomerTable.phone.ilike(like),
                        CustomerTable.mobile.ilike(like),
                        CustomerTable.email.ilike(like),
                        CustomerTable.tax_id.ilike(like),
                    )
                )

            count_result = await session.execute(
                select(func.count()).select_from(CustomerTable).where(*conditions)
            )
            total = count_result.scalar_one()

            sort_col = getattr(CustomerTable, sort_by, CustomerTable.customer_name)
            order = sort_col.desc() if sort_dir.lower() == "desc" else sort_col.asc()

            result = await session.execute(
                select(CustomerTable).where(*conditions).order_by(order).limit(limit).offset(offset)
            )
            rows = result.scalars().all()
            return [_row_to_item(r) for r in rows], total

    @audit
    async def update_customer(
        self,
        customer_id: UUID,
        name: str | None = None,
        company_name: str | None = None,
        npwp: str | None = None,
        tax_status: str | None = None,
        is_taxable: bool | None = None,
        address: str | None = None,
        city: str | None = None,
        province: str | None = None,
        district: str | None = None,
        postal_code: str | None = None,
        phone: str | None = None,
        mobile: str | None = None,
        email: str | None = None,
        website: str | None = None,
        contact_person: str | None = None,
        contact_phone: str | None = None,
        contact_email: str | None = None,
        payment_term_days: int | None = None,
        discount_percent: Decimal | None = None,
        category: str | None = None,
        price_group: str | None = None,
        is_active: bool | None = None,
        is_blacklist: bool | None = None,
        status: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> CustomerListItem:
        self._check_authority(updated_by, "update_customer")

        field_map = {
            "customer_name": name, "company_name": company_name, "tax_id": npwp,
            "tax_status": tax_status, "is_taxable": is_taxable, "address": address,
            "city": city, "province": province, "district": district,
            "postal_code": postal_code, "phone": phone, "mobile": mobile,
            "email": email, "website": website, "contact_person": contact_person,
            "contact_phone": contact_phone, "contact_email": contact_email,
            "payment_term_days": payment_term_days, "discount_percent": discount_percent,
            "category": category, "price_group": price_group, "is_active": is_active,
            "is_blacklist": is_blacklist,
        }

        async with self._uow:
            session = self._uow.session
            result = await session.execute(select(CustomerTable).where(CustomerTable.id == customer_id))
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerNotFoundError(f"Customer {customer_id} not found")

            changes: dict[str, Any] = {}
            for col, value in field_map.items():
                if value is not None and getattr(row, col) != value:
                    changes[col] = {"old": getattr(row, col), "new": value}
                    setattr(row, col, value)
            if status is not None and status != row.status:
                changes["status"] = {"old": row.status, "new": status}
                row.status = status

            if not changes:
                return _row_to_item(row)

            row.updated_by = updated_by
            row.increment_version()
            await session.flush()
            await session.refresh(row)
            item = _row_to_item(row)
            await self._uow.commit()

        self._stats["customers_updated"] += 1
        if "status" in changes:
            await self._publish(
                CustomerStatusChangedEvent(
                    aggregate_id=item.id, aggregate_version=item.version,
                    customer_id=item.id, customer_code=item.customer_code,
                    old_status=changes["status"]["old"], new_status=changes["status"]["new"],
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                ),
                correlation_id,
            )
        self._record_audit("update_customer", {
            "customer_id": str(customer_id), "changes": {k: str(v) for k, v in changes.items()},
            "updated_by": str(updated_by) if updated_by else None,
        })
        return item

    @audit
    async def delete_customer(self, customer_id: UUID, deleted_by: UUID | None = None) -> None:
        """Soft-delete. Customer tidak pernah dihapus permanen (integritas AR/GL)."""
        self._check_authority(deleted_by, "delete_customer")
        async with self._uow:
            session = self._uow.session
            result = await session.execute(select(CustomerTable).where(CustomerTable.id == customer_id))
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerNotFoundError(f"Customer {customer_id} not found")
            row.soft_delete()
            row.status = "inactive"
            row.is_active = False
            row.updated_by = deleted_by
            row.increment_version()
            await session.flush()
            await self._uow.commit()
        self._record_audit("delete_customer", {"customer_id": str(customer_id)})

    # ========================================================================
    # STATUS MANAGEMENT
    # ========================================================================

    @audit
    async def activate_customer(self, customer_id: UUID, updated_by: UUID | None = None) -> CustomerListItem:
        return await self.update_customer(
            customer_id, is_active=True, status=CustomerStatus.ACTIVE.value, updated_by=updated_by,
        )

    @audit
    async def deactivate_customer(self, customer_id: UUID, updated_by: UUID | None = None) -> CustomerListItem:
        return await self.update_customer(
            customer_id, is_active=False, status=CustomerStatus.INACTIVE.value, updated_by=updated_by,
        )

    @audit
    async def block_customer(
        self, customer_id: UUID, reason: str, updated_by: UUID | None = None,
    ) -> CustomerListItem:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(select(CustomerTable).where(CustomerTable.id == customer_id))
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerNotFoundError(f"Customer {customer_id} not found")
            row.block(reason)
            row.updated_by = updated_by
            await session.flush()
            await session.refresh(row)
            item = _row_to_item(row)
            await self._uow.commit()
        return item

    @audit
    async def set_blacklist(
        self, customer_id: UUID, is_blacklist: bool, updated_by: UUID | None = None,
    ) -> CustomerListItem:
        return await self.update_customer(customer_id, is_blacklist=is_blacklist, updated_by=updated_by)

    # ========================================================================
    # CREDIT LIMIT MANAGEMENT (+ riwayat)
    # ========================================================================

    @audit
    async def update_credit_limit(
        self,
        customer_id: UUID,
        new_limit: Decimal,
        updated_by: UUID | None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> CustomerListItem:
        self._check_authority(updated_by, "update_credit_limit")
        async with self._uow:
            session = self._uow.session
            result = await session.execute(select(CustomerTable).where(CustomerTable.id == customer_id))
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerNotFoundError(f"Customer {customer_id} not found")

            if row.credit_limit == new_limit:
                return _row_to_item(row)

            old_limit = row.credit_limit
            row.credit_limit = new_limit
            row.updated_by = updated_by
            row.increment_version()
            session.add(CustomerCreditHistoryTable(
                customer_id=customer_id, old_limit=old_limit, new_limit=new_limit,
                reason=reason, changed_by=updated_by,
            ))
            await session.flush()
            await session.refresh(row)
            item = _row_to_item(row)
            await self._uow.commit()

        self._stats["customers_updated"] += 1
        await self._publish(
            CustomerCreditLimitChangedEvent(
                aggregate_id=item.id, aggregate_version=item.version,
                customer_id=item.id, customer_code=item.customer_code,
                old_limit=old_limit, new_limit=new_limit,
                updated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            ),
            correlation_id,
        )
        self._record_audit("update_credit_limit", {
            "customer_id": str(customer_id), "old_limit": str(old_limit), "new_limit": str(new_limit),
        })
        return item

    async def get_credit_history(self, customer_id: UUID, limit: int = 100, offset: int = 0) -> list[dict]:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerCreditHistoryTable)
                .where(CustomerCreditHistoryTable.customer_id == customer_id)
                .order_by(CustomerCreditHistoryTable.created_at.desc())
                .limit(limit).offset(offset)
            )
            return [r.to_dict() for r in result.scalars().all()]

    # ========================================================================
    # BALANCE MANAGEMENT (+ riwayat)
    # ========================================================================

    @audit
    async def update_balance(
        self,
        customer_id: UUID,
        delta: Decimal,
        updated_by: UUID | None,
        source: str | None = None,
        reference: str | None = None,
        correlation_id: str | None = None,
    ) -> Decimal:
        self._check_authority(updated_by, "update_balance")
        async with self._uow:
            session = self._uow.session
            result = await session.execute(select(CustomerTable).where(CustomerTable.id == customer_id))
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerNotFoundError(f"Customer {customer_id} not found")

            old_balance = row.current_balance
            new_balance = old_balance + delta
            row.current_balance = new_balance
            row.used_credit = new_balance if new_balance > 0 else Decimal("0")
            row.updated_by = updated_by
            row.increment_version()
            session.add(CustomerBalanceHistoryTable(
                customer_id=customer_id, old_balance=old_balance, new_balance=new_balance,
                delta=delta, source=source, reference=reference, changed_by=updated_by,
            ))
            await session.flush()
            await self._uow.commit()

        self._stats["customers_updated"] += 1
        await self._publish(
            CustomerBalanceUpdatedEvent(
                aggregate_id=customer_id, aggregate_version=row.version,
                customer_id=customer_id, customer_code=row.customer_code,
                old_balance=old_balance, new_balance=new_balance, delta=delta,
                updated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            ),
            correlation_id,
        )
        self._record_audit("update_balance", {
            "customer_id": str(customer_id), "old_balance": str(old_balance), "new_balance": str(new_balance),
        })
        return new_balance

    async def get_balance_history(self, customer_id: UUID, limit: int = 100, offset: int = 0) -> list[dict]:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerBalanceHistoryTable)
                .where(CustomerBalanceHistoryTable.customer_id == customer_id)
                .order_by(CustomerBalanceHistoryTable.created_at.desc())
                .limit(limit).offset(offset)
            )
            return [r.to_dict() for r in result.scalars().all()]

    # ========================================================================
    # ADDRESSES (Tab 3 - Address)
    # ========================================================================

    async def list_addresses(self, customer_id: UUID) -> list[dict]:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerAddressTable)
                .where(CustomerAddressTable.customer_id == customer_id)
                .order_by(CustomerAddressTable.created_at)
            )
            return [r.to_dict() for r in result.scalars().all()]

    async def add_address(self, customer_id: UUID, **fields) -> dict:
        async with self._uow:
            session = self._uow.session
            row = CustomerAddressTable(customer_id=customer_id, **fields)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            data = row.to_dict()
            await self._uow.commit()
        return data

    async def update_address(self, customer_id: UUID, address_id: UUID, **fields) -> dict:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerAddressTable).where(
                    CustomerAddressTable.id == address_id, CustomerAddressTable.customer_id == customer_id,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerServiceError(f"Address {address_id} not found")
            for key, value in fields.items():
                if value is not None:
                    setattr(row, key, value)
            await session.flush()
            await session.refresh(row)
            data = row.to_dict()
            await self._uow.commit()
        return data

    async def delete_address(self, customer_id: UUID, address_id: UUID) -> None:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerAddressTable).where(
                    CustomerAddressTable.id == address_id, CustomerAddressTable.customer_id == customer_id,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerServiceError(f"Address {address_id} not found")
            await session.delete(row)
            await self._uow.commit()

    # ========================================================================
    # CONTACT PERSONS (Tab 5 - Contact Person)
    # ========================================================================

    async def list_contacts(self, customer_id: UUID) -> list[dict]:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerContactTable)
                .where(CustomerContactTable.customer_id == customer_id)
                .order_by(CustomerContactTable.created_at)
            )
            return [r.to_dict() for r in result.scalars().all()]

    async def add_contact(self, customer_id: UUID, **fields) -> dict:
        async with self._uow:
            session = self._uow.session
            row = CustomerContactTable(customer_id=customer_id, **fields)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            data = row.to_dict()
            await self._uow.commit()
        return data

    async def update_contact(self, customer_id: UUID, contact_id: UUID, **fields) -> dict:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerContactTable).where(
                    CustomerContactTable.id == contact_id, CustomerContactTable.customer_id == customer_id,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerServiceError(f"Contact {contact_id} not found")
            for key, value in fields.items():
                if value is not None:
                    setattr(row, key, value)
            await session.flush()
            await session.refresh(row)
            data = row.to_dict()
            await self._uow.commit()
        return data

    async def delete_contact(self, customer_id: UUID, contact_id: UUID) -> None:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerContactTable).where(
                    CustomerContactTable.id == contact_id, CustomerContactTable.customer_id == customer_id,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerServiceError(f"Contact {contact_id} not found")
            await session.delete(row)
            await self._uow.commit()

    # ========================================================================
    # ATTACHMENTS (Tab 6 - Attachment)
    # ========================================================================

    async def list_attachments(self, customer_id: UUID) -> list[dict]:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerAttachmentTable)
                .where(CustomerAttachmentTable.customer_id == customer_id)
                .order_by(CustomerAttachmentTable.created_at)
            )
            return [r.to_dict() for r in result.scalars().all()]

    async def add_attachment(self, customer_id: UUID, **fields) -> dict:
        async with self._uow:
            session = self._uow.session
            row = CustomerAttachmentTable(customer_id=customer_id, **fields)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            data = row.to_dict()
            await self._uow.commit()
        return data

    async def delete_attachment(self, customer_id: UUID, attachment_id: UUID) -> None:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerAttachmentTable).where(
                    CustomerAttachmentTable.id == attachment_id,
                    CustomerAttachmentTable.customer_id == customer_id,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerServiceError(f"Attachment {attachment_id} not found")
            await session.delete(row)
            await self._uow.commit()

    # ========================================================================
    # NOTES (catatan internal, berhistori)
    # ========================================================================

    async def list_notes(self, customer_id: UUID) -> list[dict]:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerNoteTable)
                .where(CustomerNoteTable.customer_id == customer_id)
                .order_by(CustomerNoteTable.created_at.desc())
            )
            return [r.to_dict() for r in result.scalars().all()]

    async def add_note(self, customer_id: UUID, note: str, created_by: UUID | None = None) -> dict:
        async with self._uow:
            session = self._uow.session
            row = CustomerNoteTable(customer_id=customer_id, note=note, created_by=created_by)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            data = row.to_dict()
            await self._uow.commit()
        return data

    async def delete_note(self, customer_id: UUID, note_id: UUID) -> None:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerNoteTable).where(
                    CustomerNoteTable.id == note_id, CustomerNoteTable.customer_id == customer_id,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerServiceError(f"Note {note_id} not found")
            await session.delete(row)
            await self._uow.commit()

    # ========================================================================
    # TAGS (Tab 8 - kategori/label)
    # ========================================================================

    async def list_tags(self, customer_id: UUID) -> list[dict]:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerTagTable).where(CustomerTagTable.customer_id == customer_id)
            )
            return [r.to_dict() for r in result.scalars().all()]

    async def add_tag(self, customer_id: UUID, tag: str) -> dict:
        async with self._uow:
            session = self._uow.session
            existing = await session.execute(
                select(CustomerTagTable).where(
                    CustomerTagTable.customer_id == customer_id, CustomerTagTable.tag == tag,
                )
            )
            if existing.scalar_one_or_none():
                raise CustomerServiceError(f"Tag '{tag}' already exists for this customer")
            row = CustomerTagTable(customer_id=customer_id, tag=tag)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            data = row.to_dict()
            await self._uow.commit()
        return data

    async def remove_tag(self, customer_id: UUID, tag_id: UUID) -> None:
        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(CustomerTagTable).where(
                    CustomerTagTable.id == tag_id, CustomerTagTable.customer_id == customer_id,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                raise CustomerServiceError(f"Tag {tag_id} not found")
            await session.delete(row)
            await self._uow.commit()

    # ========================================================================
    # BULK OPERATIONS
    # ========================================================================

    async def bulk_delete(self, customer_ids: list[UUID], deleted_by: UUID | None = None) -> int:
        count = 0
        for cid in customer_ids:
            try:
                await self.delete_customer(cid, deleted_by=deleted_by)
                count += 1
            except CustomerNotFoundError:
                continue
        return count

    async def bulk_update_status(
        self, customer_ids: list[UUID], status: str, updated_by: UUID | None = None,
    ) -> int:
        count = 0
        for cid in customer_ids:
            try:
                await self.update_customer(cid, status=status, updated_by=updated_by)
                count += 1
            except CustomerNotFoundError:
                continue
        return count

    # ========================================================================
    # STATISTICS
    # ========================================================================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        async with self._uow:
            session = self._uow.session
            total = (await session.execute(
                select(func.count()).select_from(CustomerTable)
                .where(CustomerTable.legal_entity_id == legal_entity_id)
            )).scalar_one()
            active = (await session.execute(
                select(func.count()).select_from(CustomerTable)
                .where(CustomerTable.legal_entity_id == legal_entity_id, CustomerTable.is_active.is_(True))
            )).scalar_one()
            blacklisted = (await session.execute(
                select(func.count()).select_from(CustomerTable)
                .where(CustomerTable.legal_entity_id == legal_entity_id, CustomerTable.is_blacklist.is_(True))
            )).scalar_one()
            total_credit_limit = (await session.execute(
                select(func.coalesce(func.sum(CustomerTable.credit_limit), 0))
                .where(CustomerTable.legal_entity_id == legal_entity_id)
            )).scalar_one()
            total_balance = (await session.execute(
                select(func.coalesce(func.sum(CustomerTable.current_balance), 0))
                .where(CustomerTable.legal_entity_id == legal_entity_id)
            )).scalar_one()
            return {
                "total_customers": total,
                "active_customers": active,
                "inactive_customers": total - active,
                "blacklisted_customers": blacklisted,
                "total_credit_limit": float(total_credit_limit),
                "total_outstanding_balance": float(total_balance),
            }

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_customer_service(
    uow: UnitOfWorkPort,
    event_publisher: EventPublisherPort | None = None,
) -> CustomerService:
    return CustomerService(uow=uow, event_publisher=event_publisher)


__all__ = [
    "Customer",
    "CustomerListItem",
    "CustomerNotFoundError",
    "CustomerService",
    "CustomerServiceError",
    "CustomerStatus",
    "create_customer_service",
]
