#!/usr/bin/env python3
"""
Module: sqlalchemy_purchase_sales_repository_impl.py
Layer: Adapters / Secondary / Implementation
Responsibility: Persistensi Purchase Order & Sales Order ke database
                (tabel purchase_order/purchase_order_line dan
                sales_order/sales_order_line), menggantikan penyimpanan
                in-memory dict yang sebelumnya dipakai PurchaseSalesService.

CATATAN DESAIN:
Repository ini SENGAJA tidak memakai dataclass domain `PurchaseOrder`/
`SalesOrder` yang ada di service_purchase_sales.py, karena dataclass
tersebut ternyata tidak lengkap (tidak punya field seperti
`supplier_code`, `received_amount`, `outstanding_amount`, dll yang
sudah lama diharapkan oleh PurchaseOrderResponseSchema di
fastapi_purchase_sales_router.py). Sebagai gantinya, repository ini
mengembalikan objek `SimpleNamespace` yang atributnya PERSIS mengikuti
kontrak PurchaseOrderResponseSchema/SalesOrderResponseSchema, supaya
router tinggal pakai apa adanya tanpa konversi tambahan.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from infrastructure.persistence_orm.customer_table import CustomerTable
from infrastructure.persistence_orm.purchase_order_table import (
    PurchaseOrderLineTable,
    PurchaseOrderTable,
)
from infrastructure.persistence_orm.sales_order_line_table import SalesOrderLineTable
from infrastructure.persistence_orm.sales_order_table import SalesOrderTable
from infrastructure.persistence_orm.supplier_table import SupplierTable


class PagedResult:
    """Wrapper hasil list dengan pagination -- router mengakses `.items`."""

    def __init__(self, items: list[Any], total: int, page: int, page_size: int):
        self.items = items
        self.total = total
        self.page = page
        self.page_size = page_size


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _line_totals(quantity: Decimal, unit_price: Decimal, discount_percent: Decimal, tax_rate: Decimal) -> Decimal:
    """Rumus yang SAMA PERSIS dengan POLineSchema/SOLineSchema.total_amount
    di fastapi_purchase_sales_router.py -- supaya total yang tersimpan di
    DB konsisten dengan yang dihitung & ditampilkan frontend."""
    net = quantity * unit_price * (1 - discount_percent / 100)
    tax = net * tax_rate / 100
    return _quantize(net + tax)


class SQLAlchemyPurchaseSalesRepository:
    def __init__(self):
        # PENTING: sengaja TIDAK menyimpan AsyncSession sebagai atribut
        # instance yang di-cache selamanya. Repository ini didaftarkan
        # sebagai bagian dari PurchaseSalesService yang berstatus
        # singleton (lihat service_registry.py) -- kalau satu AsyncSession
        # dipakai bersama-sama oleh banyak request bersamaan, itu akan
        # menyebabkan korupsi data/error transaksi (AsyncSession TIDAK
        # aman dipakai concurrent). Setiap method di bawah membuka sesi
        # baru sendiri lewat _session_scope() dan selalu menutupnya.
        pass

    @asynccontextmanager
    async def _session_scope(self):
        from infrastructure.database.session_factory_sqlalchemy import (
            get_async_session_factory,
        )
        factory = await get_async_session_factory()
        session = factory()
        try:
            yield session
        finally:
            await session.close()

    # ========================================================================
    # PURCHASE ORDER
    # ========================================================================

    def _po_line_to_dict(self, line: PurchaseOrderLineTable) -> dict[str, Any]:
        return {
            "id": line.id,
            "line_number": line.line_number,
            "item_id": line.item_id,
            "item_code": line.item_code,
            "item_name": line.item_name,
            "quantity": line.quantity,
            "received_quantity": line.received_quantity,
            "unit_price": line.unit_price,
            "discount_percent": line.discount_percent,
            "tax_rate": line.tax_rate,
            "total_amount": line.total_amount,
            "expected_delivery_date": line.expected_delivery_date,
            "description": line.notes,
        }

    def _po_to_view(self, po: PurchaseOrderTable, supplier: SupplierTable | None) -> SimpleNamespace:
        return SimpleNamespace(
            id=po.id,
            po_number=po.po_number,
            po_date=po.po_date,
            supplier_id=po.supplier_id,
            supplier_name=supplier.supplier_name if supplier else None,
            supplier_code=supplier.supplier_code if supplier else None,
            total_amount=po.total_amount,
            received_amount=po.received_amount,
            invoiced_amount=po.invoiced_amount,
            paid_amount=po.paid_amount,
            outstanding_amount=po.total_amount - po.received_amount,
            status=po.status,
            expected_delivery_date=po.expected_delivery_date,
            actual_delivery_date=po.actual_delivery_date,
            delivery_term_days=po.delivery_term_days,
            payment_term_days=po.payment_term_days,
            incoterm=po.incoterm,
            order_type=po.order_type,
            reference_number=po.reference_number,
            notes=po.notes,
            lines=[self._po_line_to_dict(line) for line in sorted(po.lines, key=lambda l: l.line_number)],
            created_at=po.created_at,
            updated_at=po.updated_at,
            created_by=po.created_by,
            created_by_name=None,
            approved_at=po.approved_at,
            approved_by=po.approved_by,
            approved_by_name=None,
            rejected_at=po.rejected_at,
            rejected_by=po.rejected_by,
            rejection_reason=po.rejection_reason,
            cancelled_at=po.cancelled_at,
            cancelled_by=po.cancelled_by,
            closed_at=po.closed_at,
            is_locked=po.is_locked,
            version=po.version,
        )

    async def _load_po(self, session: AsyncSession, po_id: UUID, legal_entity_id: UUID) -> PurchaseOrderTable | None:
        stmt = (
            select(PurchaseOrderTable)
            .options(selectinload(PurchaseOrderTable.lines))
            .where(
                PurchaseOrderTable.id == po_id,
                PurchaseOrderTable.legal_entity_id == legal_entity_id,
                PurchaseOrderTable.deleted_at.is_(None),
            )
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def create_purchase_order(
        self,
        *,
        po_number: str,
        po_date: date,
        supplier_id: UUID,
        lines: list[dict[str, Any]],
        expected_delivery_date: date | None,
        delivery_term_days: int,
        payment_term_days: int,
        incoterm: str,
        order_type: str,
        reference_number: str | None,
        notes: str | None,
        created_by: UUID,
        legal_entity_id: UUID,
    ) -> SimpleNamespace:
        async with self._session_scope() as session:
            try:
                total_amount = Decimal("0")
                line_rows: list[PurchaseOrderLineTable] = []
                for idx, line in enumerate(lines, start=1):
                    qty = Decimal(str(line["quantity"]))
                    price = Decimal(str(line["unit_price"]))
                    discount = Decimal(str(line.get("discount_percent", 0)))
                    tax = Decimal(str(line.get("tax_rate", 0)))
                    line_total = _line_totals(qty, price, discount, tax)
                    total_amount += line_total
                    line_rows.append(
                        PurchaseOrderLineTable(
                            id=uuid4(),
                            line_number=idx,
                            item_id=UUID(str(line["item_id"])),
                            item_code=line.get("item_code", ""),
                            item_name=line.get("item_name", ""),
                            quantity=qty,
                            unit_price=price,
                            discount_percent=discount,
                            tax_rate=tax,
                            total_amount=line_total,
                            expected_delivery_date=line.get("expected_delivery_date"),
                            notes=line.get("description"),
                            legal_entity_id=legal_entity_id,
                        )
                    )

                po = PurchaseOrderTable(
                    id=uuid4(),
                    po_number=po_number,
                    po_date=po_date,
                    supplier_id=supplier_id,
                    total_amount=_quantize(total_amount),
                    expected_delivery_date=expected_delivery_date,
                    status="draft",
                    delivery_term_days=delivery_term_days,
                    payment_term_days=payment_term_days,
                    incoterm=incoterm,
                    order_type=order_type,
                    reference_number=reference_number,
                    notes=notes,
                    created_by=created_by,
                    legal_entity_id=legal_entity_id,
                    lines=line_rows,
                )
                session.add(po)
                await session.flush()

                supplier = (await session.execute(
                    select(SupplierTable).where(SupplierTable.id == supplier_id)
                )).scalar_one_or_none()

                await session.commit()
                await session.refresh(po, attribute_names=["lines"])
                return self._po_to_view(po, supplier)
            except Exception:
                await session.rollback()
                raise

    async def get_purchase_order_by_id(self, po_id: UUID, legal_entity_id: UUID) -> SimpleNamespace | None:
        async with self._session_scope() as session:
            po = await self._load_po(session, po_id, legal_entity_id)
            if po is None:
                return None
            supplier = (await session.execute(
                select(SupplierTable).where(SupplierTable.id == po.supplier_id)
            )).scalar_one_or_none()
            return self._po_to_view(po, supplier)

    async def get_purchase_order_by_number(self, po_number: str, legal_entity_id: UUID) -> SimpleNamespace | None:
        async with self._session_scope() as session:
            stmt = (
                select(PurchaseOrderTable)
                .options(selectinload(PurchaseOrderTable.lines))
                .where(
                    PurchaseOrderTable.po_number == po_number,
                    PurchaseOrderTable.legal_entity_id == legal_entity_id,
                    PurchaseOrderTable.deleted_at.is_(None),
                )
            )
            po = (await session.execute(stmt)).scalar_one_or_none()
            if po is None:
                return None
            supplier = (await session.execute(
                select(SupplierTable).where(SupplierTable.id == po.supplier_id)
            )).scalar_one_or_none()
            return self._po_to_view(po, supplier)

    async def list_purchase_orders(
        self,
        *,
        legal_entity_id: UUID,
        supplier_id: UUID | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PagedResult:
        async with self._session_scope() as session:
            conditions = [
                PurchaseOrderTable.legal_entity_id == legal_entity_id,
                PurchaseOrderTable.deleted_at.is_(None),
            ]
            if supplier_id:
                conditions.append(PurchaseOrderTable.supplier_id == supplier_id)
            if status:
                conditions.append(PurchaseOrderTable.status == status)
            if start_date:
                conditions.append(PurchaseOrderTable.po_date >= start_date)
            if end_date:
                conditions.append(PurchaseOrderTable.po_date <= end_date)

            total = (await session.execute(
                select(func.count()).select_from(PurchaseOrderTable).where(*conditions)
            )).scalar_one()

            stmt = (
                select(PurchaseOrderTable)
                .options(selectinload(PurchaseOrderTable.lines))
                .where(*conditions)
                .order_by(PurchaseOrderTable.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = (await session.execute(stmt)).scalars().all()

            supplier_ids = {row.supplier_id for row in rows}
            suppliers = {}
            if supplier_ids:
                sup_rows = (await session.execute(
                    select(SupplierTable).where(SupplierTable.id.in_(supplier_ids))
                )).scalars().all()
                suppliers = {s.id: s for s in sup_rows}

            items = [self._po_to_view(po, suppliers.get(po.supplier_id)) for po in rows]
            return PagedResult(items=items, total=total, page=page, page_size=page_size)

    async def submit_purchase_order(self, po_id: UUID, submitted_by: UUID, legal_entity_id: UUID) -> SimpleNamespace | None:
        async with self._session_scope() as session:
            try:
                po = await self._load_po(session, po_id, legal_entity_id)
                if po is None:
                    return None
                po.submit()
                await session.commit()
                supplier = (await session.execute(
                    select(SupplierTable).where(SupplierTable.id == po.supplier_id)
                )).scalar_one_or_none()
                return self._po_to_view(po, supplier)
            except ValueError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise

    async def approve_purchase_order(
        self, po_id: UUID, approved_by: UUID, legal_entity_id: UUID, notes: str | None = None
    ) -> SimpleNamespace | None:
        async with self._session_scope() as session:
            try:
                po = await self._load_po(session, po_id, legal_entity_id)
                if po is None:
                    return None
                po.approve(approved_by)
                if notes:
                    po.notes = f"{po.notes}\n{notes}" if po.notes else notes
                await session.commit()
                supplier = (await session.execute(
                    select(SupplierTable).where(SupplierTable.id == po.supplier_id)
                )).scalar_one_or_none()
                return self._po_to_view(po, supplier)
            except ValueError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise

    async def reject_purchase_order(
        self, po_id: UUID, rejected_by: UUID, legal_entity_id: UUID, reason: str
    ) -> SimpleNamespace | None:
        async with self._session_scope() as session:
            try:
                po = await self._load_po(session, po_id, legal_entity_id)
                if po is None:
                    return None
                po.reject(rejected_by=rejected_by, reason=reason)
                await session.commit()
                supplier = (await session.execute(
                    select(SupplierTable).where(SupplierTable.id == po.supplier_id)
                )).scalar_one_or_none()
                return self._po_to_view(po, supplier)
            except ValueError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise

    # ========================================================================
    # SALES ORDER
    # ========================================================================

    def _so_line_to_dict(self, line: SalesOrderLineTable) -> dict[str, Any]:
        return {
            "id": line.id,
            "line_number": line.line_number,
            "item_id": line.item_id,
            "item_code": line.item_code,
            "item_name": line.item_name,
            "quantity": line.quantity,
            "shipped_quantity": line.shipped_quantity,
            "unit_price": line.unit_price,
            "discount_percent": line.discount_percent,
            "tax_rate": line.tax_rate,
            "total_amount": line.total_amount,
            "expected_ship_date": line.expected_ship_date,
        }

    def _so_to_view(self, so: SalesOrderTable, lines: list[SalesOrderLineTable], customer: CustomerTable | None) -> SimpleNamespace:
        return SimpleNamespace(
            id=so.id,
            so_number=so.so_number,
            so_date=so.so_date,
            customer_id=so.customer_id,
            customer_name=customer.customer_name if customer else None,
            customer_code=customer.customer_code if customer else None,
            total_amount=so.total_amount,
            shipped_amount=so.shipped_amount,
            invoiced_amount=so.invoiced_amount,
            paid_amount=so.paid_amount,
            outstanding_amount=so.total_amount - so.shipped_amount,
            status=so.status,
            expected_ship_date=so.expected_ship_date,
            actual_ship_date=so.actual_ship_date,
            shipping_term_days=so.shipping_term_days,
            payment_term_days=so.payment_term_days,
            incoterm=so.incoterm,
            order_type=so.order_type,
            reference_number=so.reference_number,
            notes=so.notes,
            lines=[self._so_line_to_dict(line) for line in sorted(lines, key=lambda l: l.line_number)],
            created_at=so.created_at,
            updated_at=so.updated_at,
            created_by=so.created_by,
            created_by_name=None,
            approved_at=so.approved_at,
            approved_by=so.approved_by,
            approved_by_name=None,
            rejected_at=so.rejected_at,
            rejected_by=so.rejected_by,
            rejection_reason=so.rejection_reason,
            cancelled_at=so.cancelled_at,
            cancelled_by=so.cancelled_by,
            closed_at=so.closed_at,
            is_locked=so.is_locked,
            version=so.version,
        )

    async def _load_so_lines(self, session: AsyncSession, so_id: UUID) -> list[SalesOrderLineTable]:
        stmt = select(SalesOrderLineTable).where(SalesOrderLineTable.sales_order_id == so_id)
        return list((await session.execute(stmt)).scalars().all())

    async def _load_so(self, session: AsyncSession, so_id: UUID, legal_entity_id: UUID) -> SalesOrderTable | None:
        stmt = select(SalesOrderTable).where(
            SalesOrderTable.id == so_id,
            SalesOrderTable.legal_entity_id == legal_entity_id,
            SalesOrderTable.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def create_sales_order(
        self,
        *,
        so_number: str,
        so_date: date,
        customer_id: UUID,
        lines: list[dict[str, Any]],
        expected_ship_date: date | None,
        shipping_term_days: int,
        payment_term_days: int,
        incoterm: str,
        order_type: str,
        reference_number: str | None,
        notes: str | None,
        created_by: UUID,
        legal_entity_id: UUID,
    ) -> SimpleNamespace:
        async with self._session_scope() as session:
            try:
                total_amount = Decimal("0")
                line_rows: list[SalesOrderLineTable] = []
                for idx, line in enumerate(lines, start=1):
                    qty = Decimal(str(line["quantity"]))
                    price = Decimal(str(line["unit_price"]))
                    discount = Decimal(str(line.get("discount_percent", 0)))
                    tax = Decimal(str(line.get("tax_rate", 0)))
                    line_total = _line_totals(qty, price, discount, tax)
                    total_amount += line_total
                    line_rows.append(
                        SalesOrderLineTable(
                            id=uuid4(),
                            sales_order_id=None,  # diisi setelah SO ter-flush (butuh id)
                            line_number=idx,
                            item_id=UUID(str(line["item_id"])),
                            item_code=line.get("item_code", ""),
                            item_name=line.get("item_name", ""),
                            quantity=qty,
                            unit_price=price,
                            discount_percent=discount,
                            tax_rate=tax,
                            total_amount=line_total,
                            expected_ship_date=line.get("expected_ship_date"),
                            legal_entity_id=legal_entity_id,
                            created_by=created_by,
                        )
                    )

                so = SalesOrderTable(
                    id=uuid4(),
                    so_number=so_number,
                    so_date=so_date,
                    customer_id=customer_id,
                    total_amount=_quantize(total_amount),
                    expected_ship_date=expected_ship_date,
                    status="draft",
                    shipping_term_days=shipping_term_days,
                    payment_term_days=payment_term_days,
                    incoterm=incoterm,
                    order_type=order_type,
                    reference_number=reference_number,
                    notes=notes,
                    created_by=created_by,
                    legal_entity_id=legal_entity_id,
                )
                session.add(so)
                await session.flush()  # supaya so.id terisi

                for line_row in line_rows:
                    line_row.sales_order_id = so.id
                    session.add(line_row)

                customer = (await session.execute(
                    select(CustomerTable).where(CustomerTable.id == customer_id)
                )).scalar_one_or_none()

                await session.commit()
                return self._so_to_view(so, line_rows, customer)
            except Exception:
                await session.rollback()
                raise

    async def get_sales_order_by_id(self, so_id: UUID, legal_entity_id: UUID) -> SimpleNamespace | None:
        async with self._session_scope() as session:
            so = await self._load_so(session, so_id, legal_entity_id)
            if so is None:
                return None
            lines = await self._load_so_lines(session, so_id)
            customer = (await session.execute(
                select(CustomerTable).where(CustomerTable.id == so.customer_id)
            )).scalar_one_or_none()
            return self._so_to_view(so, lines, customer)

    async def get_sales_order_by_number(self, so_number: str, legal_entity_id: UUID) -> SimpleNamespace | None:
        async with self._session_scope() as session:
            stmt = select(SalesOrderTable).where(
                SalesOrderTable.so_number == so_number,
                SalesOrderTable.legal_entity_id == legal_entity_id,
                SalesOrderTable.deleted_at.is_(None),
            )
            so = (await session.execute(stmt)).scalar_one_or_none()
            if so is None:
                return None
            lines = await self._load_so_lines(session, so.id)
            customer = (await session.execute(
                select(CustomerTable).where(CustomerTable.id == so.customer_id)
            )).scalar_one_or_none()
            return self._so_to_view(so, lines, customer)

    async def list_sales_orders(
        self,
        *,
        legal_entity_id: UUID,
        customer_id: UUID | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PagedResult:
        async with self._session_scope() as session:
            conditions = [
                SalesOrderTable.legal_entity_id == legal_entity_id,
                SalesOrderTable.deleted_at.is_(None),
            ]
            if customer_id:
                conditions.append(SalesOrderTable.customer_id == customer_id)
            if status:
                conditions.append(SalesOrderTable.status == status)
            if start_date:
                conditions.append(SalesOrderTable.so_date >= start_date)
            if end_date:
                conditions.append(SalesOrderTable.so_date <= end_date)

            total = (await session.execute(
                select(func.count()).select_from(SalesOrderTable).where(*conditions)
            )).scalar_one()

            stmt = (
                select(SalesOrderTable)
                .where(*conditions)
                .order_by(SalesOrderTable.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = (await session.execute(stmt)).scalars().all()

            customer_ids = {row.customer_id for row in rows}
            customers = {}
            if customer_ids:
                cust_rows = (await session.execute(
                    select(CustomerTable).where(CustomerTable.id.in_(customer_ids))
                )).scalars().all()
                customers = {c.id: c for c in cust_rows}

            items = []
            for so in rows:
                lines = await self._load_so_lines(session, so.id)
                items.append(self._so_to_view(so, lines, customers.get(so.customer_id)))
            return PagedResult(items=items, total=total, page=page, page_size=page_size)

    async def submit_sales_order(self, so_id: UUID, submitted_by: UUID, legal_entity_id: UUID) -> SimpleNamespace | None:
        async with self._session_scope() as session:
            try:
                so = await self._load_so(session, so_id, legal_entity_id)
                if so is None:
                    return None
                so.submit()
                await session.commit()
                lines = await self._load_so_lines(session, so_id)
                customer = (await session.execute(
                    select(CustomerTable).where(CustomerTable.id == so.customer_id)
                )).scalar_one_or_none()
                return self._so_to_view(so, lines, customer)
            except ValueError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise

    async def approve_sales_order(
        self, so_id: UUID, approved_by: UUID, legal_entity_id: UUID, notes: str | None = None
    ) -> SimpleNamespace | None:
        async with self._session_scope() as session:
            try:
                so = await self._load_so(session, so_id, legal_entity_id)
                if so is None:
                    return None
                so.approve(approved_by)
                if notes:
                    so.notes = f"{so.notes}\n{notes}" if so.notes else notes
                await session.commit()
                lines = await self._load_so_lines(session, so_id)
                customer = (await session.execute(
                    select(CustomerTable).where(CustomerTable.id == so.customer_id)
                )).scalar_one_or_none()
                return self._so_to_view(so, lines, customer)
            except ValueError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise

    async def reject_sales_order(
        self, so_id: UUID, rejected_by: UUID, legal_entity_id: UUID, reason: str
    ) -> SimpleNamespace | None:
        async with self._session_scope() as session:
            try:
                so = await self._load_so(session, so_id, legal_entity_id)
                if so is None:
                    return None
                so.reject(rejected_by=rejected_by, reason=reason)
                await session.commit()
                lines = await self._load_so_lines(session, so_id)
                customer = (await session.execute(
                    select(CustomerTable).where(CustomerTable.id == so.customer_id)
                )).scalar_one_or_none()
                return self._so_to_view(so, lines, customer)
            except ValueError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise


__all__ = ["SQLAlchemyPurchaseSalesRepository", "PagedResult"]
