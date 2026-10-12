#!/usr/bin/env python3
"""
Module: sqlalchemy_supplier_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi SupplierRepositoryPort menggunakan SQLAlchemy.

PERBAIKAN (2026-10-12):
- Import `Supplier` DTO dari domain layer (bukan dari service layer)
  supaya tidak melanggar clean architecture (adapter -> application).
- Tambah method: add_attachment, list_attachments, delete_attachment,
  add_note, list_notes, delete_note.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.ap_invoice_table import APInvoiceTable
from infrastructure.persistence_orm.ap_payment_table import APPaymentTable
from infrastructure.persistence_orm.goods_receipt_note_table import (
    GoodsReceiptNoteTable,
)
from infrastructure.persistence_orm.purchase_order_table import PurchaseOrderTable
from infrastructure.persistence_orm.supplier_table import (
    SupplierAttachmentTable,
    SupplierNoteTable,
    SupplierTable,
)
from ports.primary.supplier_repository_port import SupplierRepositoryPort

logger = logging.getLogger(__name__)


# ============================================================================
# DTO Supplier — pindah dari service layer supaya adapter tidak import
# dari application layer (clean architecture).
# ============================================================================


from dataclasses import dataclass, field


@dataclass(kw_only=True)
class SupplierDTO:
    """
    Data Transfer Object untuk Supplier, dipakai oleh service layer
    (application) DAN adapter (infrastructure) tanpa circular import.

    Field-nya sengaja SAMA PERSIS dengan `Supplier` dataclass lama di
    service_supplier.py, supaya swap import tidak memutus backward
    compatibility dengan kode yang sudah ada.
    """
    id: UUID = field(default_factory=uuid4)
    legal_entity_id: UUID
    supplier_code: str
    name: str
    company_name: str | None = None
    supplier_type: str = "company"
    npwp: str | None = None
    tax_name: str | None = None
    address: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country: str = "ID"
    phone: str | None = None
    mobile: str | None = None
    email: str | None = None
    website: str | None = None
    contact_person: str | None = None
    payment_terms_days: int = 30
    credit_limit: Decimal = Decimal("0")
    opening_balance: Decimal = Decimal("0")
    opening_balance_date: Any = None  # date | None
    bank_name: str | None = None
    bank_account_number: str | None = None
    bank_account_name: str | None = None
    withholding_category: str = "none"
    remarks: str | None = None
    is_active: bool = True
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    version: int = 1


# Alias untuk backward-compat dengan service_supplier.py yang pakai `Supplier`
Supplier = SupplierDTO


# ============================================================================
# Repository
# ============================================================================


class SQLAlchemySupplierRepository(SupplierRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import (
                get_async_session_direct,
            )
            self._session = await get_async_session_direct()
        return self._session

    # ==================== MAPPING ====================

    def _to_domain(self, row: SupplierTable) -> SupplierDTO:
        return SupplierDTO(
            id=row.id,
            legal_entity_id=row.legal_entity_id,
            supplier_code=row.supplier_code,
            name=row.supplier_name,
            company_name=row.company_name,
            supplier_type=row.supplier_type,
            npwp=row.tax_id,
            tax_name=row.tax_name,
            address=row.address,
            city=row.city,
            province=row.province,
            postal_code=row.postal_code,
            country=row.country,
            phone=row.phone,
            mobile=row.mobile,
            email=row.email,
            website=row.website,
            contact_person=row.contact_person,
            payment_terms_days=row.payment_term_days,
            credit_limit=row.credit_limit
            if row.credit_limit is not None
            else Decimal("0"),
            opening_balance=row.opening_balance
            if row.opening_balance is not None
            else Decimal("0"),
            opening_balance_date=row.opening_balance_date,
            bank_name=row.bank_name,
            bank_account_number=row.bank_account_number,
            bank_account_name=row.bank_account_name,
            withholding_category=row.withholding_category,
            remarks=row.remarks,
            is_active=row.is_active,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=row.created_by,
            version=row.version,
        )

    def _apply_domain_to_row(
        self, row: SupplierTable, supplier: SupplierDTO
    ) -> None:
        row.supplier_code = supplier.supplier_code
        row.supplier_name = supplier.name
        row.company_name = supplier.company_name
        row.supplier_type = supplier.supplier_type
        row.tax_id = supplier.npwp
        row.tax_name = supplier.tax_name
        row.has_npwp = bool(supplier.npwp)
        row.address = supplier.address
        row.city = supplier.city
        row.province = supplier.province
        row.postal_code = supplier.postal_code
        row.country = supplier.country
        row.phone = supplier.phone
        row.mobile = supplier.mobile
        row.email = supplier.email
        row.website = supplier.website
        row.contact_person = supplier.contact_person
        row.payment_term_days = supplier.payment_terms_days
        row.credit_limit = supplier.credit_limit
        row.opening_balance = supplier.opening_balance
        row.opening_balance_date = supplier.opening_balance_date
        row.bank_name = supplier.bank_name
        row.bank_account_number = supplier.bank_account_number
        row.bank_account_name = supplier.bank_account_name
        row.withholding_category = supplier.withholding_category
        row.remarks = supplier.remarks
        row.is_active = supplier.is_active
        row.status = supplier.status

    # ==================== READ ====================

    async def get_by_id(
        self, supplier_id: UUID, legal_entity_id: UUID
    ) -> SupplierDTO | None:
        session = await self._get_session()
        stmt = select(SupplierTable).where(
            SupplierTable.id == supplier_id,
            SupplierTable.legal_entity_id == legal_entity_id,
            SupplierTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_code(
        self, legal_entity_id: UUID, supplier_code: str
    ) -> SupplierDTO | None:
        session = await self._get_session()
        stmt = select(SupplierTable).where(
            SupplierTable.supplier_code == supplier_code,
            SupplierTable.legal_entity_id == legal_entity_id,
            SupplierTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_tax_id(self, tax_id: str) -> SupplierDTO | None:
        session = await self._get_session()
        stmt = select(SupplierTable).where(
            SupplierTable.tax_id == tax_id,
            SupplierTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def is_active(self, supplier_id: UUID) -> bool:
        session = await self._get_session()
        stmt = select(SupplierTable.is_active, SupplierTable.status).where(
            SupplierTable.id == supplier_id
        )
        result = await session.execute(stmt)
        row = result.one_or_none()
        return bool(row and row[0] and row[1] == "active")

    async def list_by_entity(
        self,
        legal_entity_id: UUID,
        *,
        search: str | None = None,
        city: str | None = None,
        status: str | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[SupplierDTO], int]:
        session = await self._get_session()
        conditions = [
            SupplierTable.legal_entity_id == legal_entity_id,
            SupplierTable.deleted_at.is_(None),
        ]
        if search:
            like = f"%{search.strip()}%"
            conditions.append(
                or_(
                    SupplierTable.supplier_code.ilike(like),
                    SupplierTable.supplier_name.ilike(like),
                    SupplierTable.company_name.ilike(like),
                    SupplierTable.tax_id.ilike(like),
                    SupplierTable.email.ilike(like),
                    SupplierTable.contact_person.ilike(like),
                )
            )
        if city:
            conditions.append(SupplierTable.city.ilike(f"%{city}%"))
        if status:
            conditions.append(SupplierTable.status == status)
        if is_active is not None:
            conditions.append(SupplierTable.is_active == is_active)

        count_stmt = (
            select(func.count()).select_from(SupplierTable).where(and_(*conditions))
        )
        total = await session.scalar(count_stmt) or 0

        stmt = (
            select(SupplierTable)
            .where(and_(*conditions))
            .order_by(SupplierTable.supplier_code)
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows], total

    # ==================== WRITE ====================

    async def add(self, supplier: SupplierDTO) -> SupplierDTO:
        session = await self._get_session()
        try:
            dup_stmt = select(SupplierTable).where(
                SupplierTable.supplier_code == supplier.supplier_code,
                SupplierTable.legal_entity_id == supplier.legal_entity_id,
                SupplierTable.deleted_at.is_(None),
            )
            if (await session.execute(dup_stmt)).scalar_one_or_none():
                raise ValueError(
                    f"Supplier code {supplier.supplier_code} already exists"
                )

            if supplier.npwp:
                npwp_stmt = select(SupplierTable).where(
                    SupplierTable.tax_id == supplier.npwp
                )
                if (await session.execute(npwp_stmt)).scalar_one_or_none():
                    raise ValueError(
                        f"NPWP {supplier.npwp} already used by another supplier"
                    )

            row = SupplierTable(
                id=supplier.id or uuid4(),
                legal_entity_id=supplier.legal_entity_id,
                created_by=supplier.created_by,
            )
            self._apply_domain_to_row(row, supplier)
            session.add(row)
            await session.flush()
            supplier.id = row.id
            supplier.created_at = row.created_at
            supplier.updated_at = row.updated_at
            supplier.version = row.version
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return supplier

    async def update(self, supplier: SupplierDTO) -> SupplierDTO:
        session = await self._get_session()
        try:
            stmt = (
                select(SupplierTable)
                .where(
                    SupplierTable.id == supplier.id,
                    SupplierTable.legal_entity_id == supplier.legal_entity_id,
                )
                .with_for_update()
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                raise ValueError(f"Supplier {supplier.id} not found")

            if supplier.npwp and supplier.npwp != row.tax_id:
                npwp_stmt = select(SupplierTable).where(
                    SupplierTable.tax_id == supplier.npwp,
                    SupplierTable.id != row.id,
                )
                if (await session.execute(npwp_stmt)).scalar_one_or_none():
                    raise ValueError(
                        f"NPWP {supplier.npwp} already used by another supplier"
                    )

            self._apply_domain_to_row(row, supplier)
            row.updated_at = datetime.now(UTC)
            row.increment_version()
            await session.flush()
            supplier.updated_at = row.updated_at
            supplier.version = row.version
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return supplier

    async def save(self, supplier: SupplierDTO) -> SupplierDTO:
        existing = (
            await self.get_by_id(supplier.id, supplier.legal_entity_id)
            if supplier.id
            else None
        )
        if existing:
            return await self.update(supplier)
        return await self.add(supplier)

    async def soft_delete(
        self, supplier_id: UUID, legal_entity_id: UUID, deleted_by: UUID
    ) -> bool:
        if await self.has_transactions(supplier_id):
            logger.warning(
                f"Refusing to delete supplier {supplier_id}: existing transactions found."
            )
            return False

        session = await self._get_session()
        try:
            stmt = (
                select(SupplierTable)
                .where(
                    SupplierTable.id == supplier_id,
                    SupplierTable.legal_entity_id == legal_entity_id,
                )
                .with_for_update()
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                await session.rollback()
                return False
            row.status = "inactive"
            row.is_active = False
            row.deleted_at = datetime.now(UTC)
            row.updated_at = datetime.now(UTC)
            row.increment_version()
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return True

    async def has_transactions(self, supplier_id: UUID) -> bool:
        session = await self._get_session()
        for table, col in (
            (PurchaseOrderTable, PurchaseOrderTable.supplier_id),
            (GoodsReceiptNoteTable, GoodsReceiptNoteTable.supplier_id),
            (APInvoiceTable, APInvoiceTable.vendor_id),
            (APPaymentTable, APPaymentTable.supplier_id),
        ):
            stmt = select(func.count()).select_from(table).where(col == supplier_id)
            count = await session.scalar(stmt) or 0
            if count > 0:
                return True
        return False

    # ==================== LAPORAN & INTEGRASI ====================

    async def get_outstanding_balance(self, supplier_id: UUID) -> Decimal:
        session = await self._get_session()
        stmt = select(
            func.coalesce(
                func.sum(APInvoiceTable.total_amount - APInvoiceTable.paid_amount), 0
            )
        ).where(
            APInvoiceTable.vendor_id == supplier_id,
            APInvoiceTable.status.notin_(["cancelled", "written_off"]),
        )
        balance = await session.scalar(stmt)
        return Decimal(balance or 0)

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        session = await self._get_session()
        base = SupplierTable.legal_entity_id == legal_entity_id
        total = (
            await session.scalar(
                select(func.count())
                .select_from(SupplierTable)
                .where(base, SupplierTable.deleted_at.is_(None))
            )
            or 0
        )
        active = (
            await session.scalar(
                select(func.count()).where(
                    base,
                    SupplierTable.is_active.is_(True),
                    SupplierTable.deleted_at.is_(None),
                )
            )
            or 0
        )

        cat_stmt = (
            select(SupplierTable.category, func.count())
            .where(base, SupplierTable.deleted_at.is_(None))
            .group_by(SupplierTable.category)
        )
        categories = {
            cat or "Tanpa Kategori": cnt
            for cat, cnt in (await session.execute(cat_stmt)).all()
        }

        status_stmt = (
            select(SupplierTable.status, func.count())
            .where(base, SupplierTable.deleted_at.is_(None))
            .group_by(SupplierTable.status)
        )
        statuses = {
            st: cnt for st, cnt in (await session.execute(status_stmt)).all()
        }

        return {
            "total": total,
            "active": active,
            "inactive": total - active,
            "categories": categories,
            "statuses": statuses,
        }

    async def export_rows(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        rows, _ = await self.list_by_entity(legal_entity_id, limit=100000, offset=0)
        return [asdict(r) for r in rows]

    async def get_next_code(
        self, legal_entity_id: UUID, prefix: str = "SUP"
    ) -> str:
        session = await self._get_session()
        like_pattern = f"{prefix}-%"
        stmt = select(SupplierTable.supplier_code).where(
            SupplierTable.legal_entity_id == legal_entity_id,
            SupplierTable.supplier_code.ilike(like_pattern),
        )
        result = await session.execute(stmt)
        codes = [row[0] for row in result.all()]

        max_num = 0
        max_width = 3
        for code in codes:
            suffix = code[len(prefix) + 1 :]
            if suffix.isdigit():
                num = int(suffix)
                if num > max_num:
                    max_num = num
                max_width = max(max_width, len(suffix))

        next_num = max_num + 1
        width = max(max_width, len(str(next_num)))
        return f"{prefix}-{next_num:0{width}d}"

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        rows = await self.export_rows(legal_entity_id)
        output = io.StringIO()
        if not rows:
            return ""
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
        return output.getvalue()

    async def health_check(self) -> dict[str, Any]:
        try:
            session = await self._get_session()
            from sqlalchemy import text as _text

            await session.execute(_text("SELECT 1"))
            return {"status": "healthy", "database": "connected"}
        except Exception as e:
            return {
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
            }

    # ==================== ATTACHMENTS ====================

    async def add_attachment(self, supplier_id: UUID, **fields) -> dict[str, Any]:
        session = await self._get_session()
        try:
            row = SupplierAttachmentTable(supplier_id=supplier_id, **fields)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            data = row.to_dict()
            await session.commit()
            return data
        except Exception:
            await session.rollback()
            raise

    async def list_attachments(self, supplier_id: UUID) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = (
            select(SupplierAttachmentTable)
            .where(
                SupplierAttachmentTable.supplier_id == supplier_id,
                SupplierAttachmentTable.deleted_at.is_(None),
            )
            .order_by(SupplierAttachmentTable.created_at)
        )
        result = await session.execute(stmt)
        return [r.to_dict() for r in result.scalars().all()]

    async def delete_attachment(
        self, supplier_id: UUID, attachment_id: UUID
    ) -> bool:
        session = await self._get_session()
        try:
            stmt = select(SupplierAttachmentTable).where(
                SupplierAttachmentTable.id == attachment_id,
                SupplierAttachmentTable.supplier_id == supplier_id,
                SupplierAttachmentTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return False
            row.deleted_at = datetime.now(UTC)
            await session.flush()
            await session.commit()
            return True
        except Exception:
            await session.rollback()
            raise

    # ==================== NOTES ====================

    async def add_note(
        self, supplier_id: UUID, note: str, created_by: UUID | None = None
    ) -> dict[str, Any]:
        session = await self._get_session()
        try:
            row = SupplierNoteTable(
                supplier_id=supplier_id, note=note, created_by=created_by
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            data = row.to_dict()
            await session.commit()
            return data
        except Exception:
            await session.rollback()
            raise

    async def list_notes(self, supplier_id: UUID) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = (
            select(SupplierNoteTable)
            .where(SupplierNoteTable.supplier_id == supplier_id)
            .order_by(SupplierNoteTable.created_at.desc())
        )
        result = await session.execute(stmt)
        return [r.to_dict() for r in result.scalars().all()]

    async def delete_note(self, supplier_id: UUID, note_id: UUID) -> bool:
        session = await self._get_session()
        try:
            stmt = select(SupplierNoteTable).where(
                SupplierNoteTable.id == note_id,
                SupplierNoteTable.supplier_id == supplier_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return False
            await session.delete(row)
            await session.flush()
            await session.commit()
            return True
        except Exception:
            await session.rollback()
            raise


__all__ = [
    "SQLAlchemySupplierRepository",
    "SupplierDTO",
    "Supplier",
]
