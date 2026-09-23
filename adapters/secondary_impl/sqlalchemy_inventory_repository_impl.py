#!/usr/bin/env python3
"""
Module: sqlalchemy_inventory_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository Inventory dengan SQLAlchemy.
Perbaikan:
  - [FIX] InventoryFIFOLayerTable.layer_date → purchase_date
  - [FIX] InventoryFIFOLayerTable.warehouse_id dihapus (tidak ada di model)
  - [FIX] WarehouseTable.code → warehouse_code
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.inventory.aggregate_root import InventoryItemAggregate, StockMovement, StockMovementType
from domain.inventory.item_entity import Item, ItemStatus, ItemType, UnitOfMeasure, ValuationMethod
from domain.inventory.movement_entity import MovementEntity, MovementStatus, MovementType
from domain.inventory.stock_opname_entity import DiscrepancyType, OpnameItem, OpnameStatus, StockOpname
from domain.inventory.inter_warehouse_transfer_entity import (
    InterWarehouseTransfer,
    TransferItem,
    TransferPriority,
    TransferStatus,
)
from infrastructure.persistence_orm.inter_warehouse_transfer_table import (
    InterWarehouseTransferLineTable,
    InterWarehouseTransferTable,
)
from domain.inventory.valuation_method import FIFOLayer
from domain.shared_value_objects.money_vo import Money
from domain.shared_value_objects.quantity_vo import Quantity
from infrastructure.persistence_orm.inventory_fifo_layer_table import InventoryFIFOLayerTable
from infrastructure.persistence_orm.inventory_item_table import InventoryItemTable
from infrastructure.persistence_orm.inventory_movement_table import InventoryMovementTable
from infrastructure.persistence_orm.stock_opname_table import StockOpnameTable
from infrastructure.persistence_orm.stock_opname_line_table import StockOpnameLineTable
from infrastructure.persistence_orm.warehouse_table import WarehouseTable
from ports.primary.inventory_repository_port import InventoryRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPTIONS
# ============================================================================

class InventoryRepositoryError(Exception):
    pass

class DuplicateItemCodeError(InventoryRepositoryError):
    pass

class ItemNotFoundError(InventoryRepositoryError):
    pass

class InsufficientStockError(InventoryRepositoryError):
    pass

class FIFOLayerNotFoundError(InventoryRepositoryError):
    pass

class OptimisticLockError(InventoryRepositoryError):
    pass

class NegativeStockNotAllowedError(InventoryRepositoryError):
    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================

class SQLAlchemyInventoryRepository(InventoryRepositoryPort):
    """
    Implementasi InventoryRepositoryPort dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id
        self._audit_log: list[dict[str, Any]] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            # Lazy-init: sebelumnya repo ini SELALU dibuat tanpa session oleh
            # IoC container (auto-wiring adapter_registry tidak menyuntikkan
            # AsyncSession), jadi setiap panggilan repo di seluruh modul
            # Inventory gagal dengan "Session not set". Perbaikan: buat
            # session sendiri di sini, sama seperti pola yang sudah dipakai
            # (dan terbukti jalan) di SQLAlchemySupplierRepository dkk.
            from infrastructure.database.session_factory_sqlalchemy import get_session_factory_sync

            factory = get_session_factory_sync()
            session_maker = factory.get_session_factory()
            if session_maker is None:
                raise InventoryRepositoryError("Session factory not available")
            self._session = session_maker()
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    async def _flush_and_commit(self) -> None:
        """Flush + COMMIT perubahan ke database.

        FIX BUG KRITIS ("data gudang/barang tersimpan tapi tidak benar-benar
        ada di database"): seluruh method tulis di repository ini dulunya
        hanya memanggil ``session.flush()``. flush() cuma mengirim SQL
        INSERT/UPDATE ke dalam transaksi yang masih terbuka - datanya
        terlihat oleh query di session yang sama (jadi endpoint balas
        201 Created dan record sempat muncul), TAPI tidak pernah
        di-COMMIT. Repository ini membuat session-nya sendiri secara
        lazy (lihat property ``session`` di atas) dan tidak berada di
        bawah dependency ``get_async_session()`` FastAPI yang biasanya
        melakukan commit otomatis, sehingga transaksinya tidak pernah
        ditutup dan seluruh perubahan hilang begitu koneksi dilepas.
        Semua operasi tulis sekarang memanggil helper ini.
        """
        await self.session.flush()
        await self.session.commit()

    def _get_legal_entity_id(self, provided: UUID | None = None) -> UUID:
        if provided is not None:
            return provided
        if self._legal_entity_id is not None:
            return self._legal_entity_id
        raise ValueError("legal_entity_id is required but not provided and not set in repository")

    # ========================================================================
    # HELPER MAPPING
    # ========================================================================

    def _to_domain_item(self, table: InventoryItemTable) -> InventoryItemAggregate:
        """Konversi baris ORM InventoryItemTable -> InventoryAggregate.

        CATATAN: versi sebelumnya memanggil InventoryAggregate(item_code=...,
        item_name=..., reorder_point=Quantity(...), ...) - constructor asli
        InventoryAggregate hanya menerima (id, legal_entity_id, version), dan
        semua field lain di atas tidak pernah jadi bagian domain Item asli
        (yang pakai Decimal polos, bukan value object Quantity/Money). Ini
        akan selalu TypeError kalau benar-benar dieksekusi. Ditulis ulang
        supaya membangun domain Item yang benar lalu membungkusnya ke
        aggregate lewat _item (sama seperti yang dilakukan InventoryAggregate.create()).
        """
        try:
            item_type = ItemType(table.item_type)
        except ValueError:
            item_type = ItemType.TRADING
        try:
            uom = UnitOfMeasure(table.unit_of_measure)
        except ValueError:
            uom = UnitOfMeasure.PCS

        item = Item(
            id=table.id,
            legal_entity_id=table.legal_entity_id,
            sku=table.item_code,
            name=table.item_name,
            description=table.description,
            item_type=item_type,
            unit_of_measure=uom,
            current_stock=table.current_stock or Decimal("0"),
            current_stock_value=(table.current_stock or Decimal("0")) * (table.average_cost or Decimal("0")),
            average_cost=table.average_cost or Decimal("0"),
            last_cost=table.last_cost or Decimal("0"),
            reorder_point=table.reorder_point or Decimal("0"),
            safety_stock=table.safety_stock or Decimal("0"),
            maximum_stock=table.maximum_stock,
            minimum_stock=table.minimum_stock,
            status=ItemStatus.ACTIVE if table.is_active else ItemStatus.INACTIVE,
            standard_cost=table.standard_cost or Decimal("0"),
            selling_price=table.selling_price or Decimal("0"),
            category=table.category,
            # FIX BUG: sebelumnya di-hardcode None saat memuat item dari
            # database, sehingga setiap kali form Barang/Item dibuka lagi,
            # gudang default terlihat "belum pernah diisi" walau sudah
            # pernah disimpan (karena memang tidak pernah benar-benar
            # tersimpan - lihat catatan di _to_orm_item()).
            warehouse_id=table.warehouse_id,
            created_by=table.created_by,
            created_at=table.created_at,
            updated_at=table.updated_at,
            updated_by=table.updated_by,
            brand=table.brand,
            reorder_quantity=table.reorder_quantity or Decimal("0"),
            valuation_method=table.valuation_method,
            weight_gram=table.weight,
            version=table.version,
        )
        aggregate = InventoryItemAggregate(id=table.id, legal_entity_id=table.legal_entity_id, version=table.version)
        aggregate._item = item
        return aggregate

    async def _to_orm_item(self, aggregate: InventoryItemAggregate) -> InventoryItemTable:
        """Konversi InventoryAggregate -> baris ORM InventoryItemTable.

        CATATAN: versi sebelumnya menganggap semua field numerik aggregate
        adalah value object (punya .value/.amount/.currency) - itu tidak
        pernah cocok dengan domain Item aktual (semua field numeriknya
        Decimal polos). Sudah ditulis ulang untuk mengambil semuanya dari
        aggregate.item (domain Item asli) secara langsung.
        """
        item = aggregate.item
        return InventoryItemTable(
            id=item.id,
            item_code=item.sku,
            sku=item.sku,
            item_name=item.name,
            item_type=item.item_type.value if hasattr(item.item_type, "value") else str(item.item_type),
            unit_of_measure=item.unit_of_measure.value if hasattr(item.unit_of_measure, "value") else str(item.unit_of_measure),
            category=item.category,
            brand=getattr(item, "brand", None),
            reorder_point=item.reorder_point or Decimal("0"),
            reorder_quantity=getattr(item, "reorder_quantity", None) or Decimal("0"),
            standard_cost=item.standard_cost or Decimal("0"),
            selling_price=item.selling_price or Decimal("0"),
            valuation_method=getattr(item, "valuation_method", None) or "FIFO",
            is_active=item.is_active,
            current_stock=item.current_stock or Decimal("0"),
            average_cost=item.average_cost or Decimal("0"),
            last_cost=item.last_cost or Decimal("0"),
            # FIX BUG: sebelumnya di-hardcode None sehingga pilihan gudang
            # default di form Barang/Item TIDAK PERNAH benar-benar tersimpan
            # (kolom FK warehouse_id selalu ditimpa NULL setiap update/create).
            warehouse_id=getattr(item, "warehouse_id", None),
            minimum_stock=getattr(item, "minimum_stock", None),
            min_stock=getattr(item, "minimum_stock", None),
            maximum_stock=getattr(item, "maximum_stock", None),
            max_stock=getattr(item, "maximum_stock", None),
            safety_stock=item.safety_stock or Decimal("0"),
            description=item.description,
            tax_rate_purchase=getattr(item, "tax_rate_purchase", None) or Decimal("11"),
            tax_rate_sales=getattr(item, "tax_rate_sales", None) or Decimal("11"),
            currency_code="IDR",
            created_at=item.created_at,
            updated_at=datetime.utcnow(),
            created_by=getattr(item, "created_by", None),
            version=getattr(item, "version", 1),
            legal_entity_id=item.legal_entity_id,
        )

    def _to_domain_movement(self, table: InventoryMovementTable) -> StockMovement:
        movement_type_map = {
            "IN": StockMovementType.IN,
            "OUT": StockMovementType.OUT,
            "ADJUSTMENT": StockMovementType.ADJUSTMENT,
            "TRANSFER_IN": StockMovementType.TRANSFER_IN,
            "TRANSFER_OUT": StockMovementType.TRANSFER_OUT,
        }
        return StockMovement(
            id=table.id,
            movement_number=table.movement_number,
            item_id=table.item_id,
            movement_type=movement_type_map.get(table.movement_type, StockMovementType.IN),
            quantity=Quantity(value=table.quantity, uom=table.uom),
            unit_cost=Money(amount=table.unit_cost, currency=table.currency or "IDR"),
            total_cost=Money(amount=table.total_cost, currency=table.currency or "IDR"),
            movement_date=table.movement_date,
            reference_type=table.reference_type,
            reference_id=table.reference_id,
            warehouse_id=table.warehouse_id,
            to_warehouse_id=table.to_warehouse_id,
            batch_number=table.batch_number,
            expiry_date=table.expiry_date,
            notes=table.notes,
            created_at=table.created_at,
            created_by=table.created_by,
        )

    # FIX BUG KRITIS: kolom `inventory_movement.movement_type` dibatasi
    # CHECK CONSTRAINT `ck_inventory_movement_type` yang HANYA mengizinkan
    # 5 nilai flat huruf besar: 'IN', 'OUT', 'ADJUSTMENT', 'TRANSFER_IN',
    # 'TRANSFER_OUT' (lihat migrations/versions/0013_inventory_item_and_movement.py
    # dan infrastructure/persistence_orm/inventory_movement_table.py).
    # Domain MovementType enum (movement_entity.py) punya 17 nilai granular
    # huruf kecil (purchase_receipt, adjustment_in, sales_issue, dst) yang
    # TIDAK SATU PUN cocok persis dengan 5 nilai yang diizinkan itu - bahkan
    # transfer_in/transfer_out pun beda huruf besar/kecil. Akibatnya SETIAP
    # mutasi stok jenis apa pun SELALU gagal dengan CheckViolationError sejak
    # awal (bukan cuma tipe tertentu). Mapping ini menerjemahkan nilai
    # granular ke salah satu dari 5 nilai yang benar-benar diizinkan
    # database HANYA pada saat disimpan ke kolom ini - logika bisnis lain
    # (arah stok masuk/keluar via is_inbound(), dst) tetap memakai enum
    # granular aslinya di memori, tidak terpengaruh.
    _DB_MOVEMENT_TYPE_MAP = {
        MovementType.PURCHASE_RECEIPT: "IN",
        MovementType.PRODUCTION_COMPLETION: "IN",
        MovementType.RETURN_FROM_CUSTOMER: "IN",
        MovementType.INITIAL_STOCK: "IN",
        MovementType.ADJUSTMENT_IN: "ADJUSTMENT",
        MovementType.ADJUSTMENT_OUT: "ADJUSTMENT",
        MovementType.PURCHASE_RETURN: "OUT",
        MovementType.PRODUCTION_ISSUE: "OUT",
        MovementType.SALES_ISSUE: "OUT",
        MovementType.SALES_RETURN: "OUT",
        MovementType.RETURN_TO_SUPPLIER: "OUT",
        MovementType.DAMAGED: "OUT",
        MovementType.EXPIRED: "OUT",
        MovementType.SAMPLE_ISSUE: "OUT",
        MovementType.DONATION: "OUT",
        MovementType.WRITE_OFF: "OUT",
        MovementType.TRANSFER_IN: "TRANSFER_IN",
        MovementType.TRANSFER_OUT: "TRANSFER_OUT",
    }

    @classmethod
    def _db_movement_type(cls, movement_type: Any) -> str:
        """Terjemahkan MovementType granular ke salah satu dari 5 nilai
        yang diizinkan CHECK CONSTRAINT ck_inventory_movement_type."""
        if isinstance(movement_type, MovementType):
            mapped = cls._DB_MOVEMENT_TYPE_MAP.get(movement_type)
            if mapped:
                return mapped
            return "ADJUSTMENT"
        raw = str(getattr(movement_type, "value", movement_type)).upper()
        allowed = {"IN", "OUT", "ADJUSTMENT", "TRANSFER_IN", "TRANSFER_OUT"}
        return raw if raw in allowed else "ADJUSTMENT"

    async def _to_orm_movement(self, movement: StockMovement) -> InventoryMovementTable:
        movement_type_str = self._db_movement_type(movement.movement_type)
        return InventoryMovementTable(
            id=movement.id,
            movement_number=movement.movement_number,
            item_id=movement.item_id,
            movement_type=movement_type_str,
            quantity=movement.quantity.value,
            uom=movement.quantity.uom,
            unit_cost=movement.unit_cost.amount,
            total_cost=movement.total_cost.amount,
            currency=movement.unit_cost.currency,
            movement_date=movement.movement_date,
            reference_type=movement.reference_type,
            reference_id=movement.reference_id,
            warehouse_id=movement.warehouse_id,
            to_warehouse_id=movement.to_warehouse_id,
            batch_number=movement.batch_number,
            expiry_date=movement.expiry_date,
            notes=movement.notes,
            created_at=movement.created_at,
            created_by=movement.created_by,
        )

    # ========================================================================
    # MOVEMENT ENTITY (canonical) - dipakai save_movement/get_movement_by_id/
    # list_movements/get_movements_by_item/get_movements_by_reference.
    # Model kanonik untuk Stock Movement adalah domain.inventory.movement_entity.MovementEntity
    # (BUKAN domain.inventory.aggregate_root.StockMovement di atas, yang hanya
    # dipertahankan untuk method lama record_movement() demi kompatibilitas port).
    # ========================================================================

    def _to_domain_movement_entity(self, table: InventoryMovementTable) -> MovementEntity:
        return MovementEntity(
            movement_id=table.id,
            movement_number=table.movement_number,
            movement_type=MovementType(table.movement_type),
            item_id=table.item_id,
            item_sku="",  # diisi oleh pemanggil (list_movements) via join, kosong di sini
            item_name="",
            warehouse_id=table.warehouse_id,
            quantity=table.quantity,
            unit_cost=table.unit_cost,
            total_cost=table.total_cost,
            movement_date=table.movement_date,
            status=MovementStatus(table.status) if getattr(table, "status", None) else MovementStatus.CONFIRMED,
            reference_document_type=table.reference_type,
            reference_document_id=table.reference_id,
            reference_document_number=None,
            created_by=str(table.created_by) if table.created_by else "",
            created_at=table.created_at,
            updated_at=table.updated_at,
            version=getattr(table, "version", 1),
            legal_entity_id=table.legal_entity_id,
            warehouse_code=None,
            notes=table.notes,
            batch_number=table.batch_number,
            expiry_date=table.expiry_date,
            serial_number=getattr(table, "serial_number", None),
            to_warehouse_id=table.to_warehouse_id,
            reversed_at=getattr(table, "reversed_at", None),
            reversed_by=getattr(table, "reversed_by", None),
        )

    def _to_orm_movement_entity(self, movement: MovementEntity) -> InventoryMovementTable:
        return InventoryMovementTable(
            id=movement.movement_id,
            movement_number=movement.movement_number,
            item_id=movement.item_id,
            movement_type=self._db_movement_type(movement.movement_type),
            quantity=movement.quantity,
            uom="PCS",  # UoM sudah dikelola di level item, tidak dobel disimpan per-movement
            unit_cost=movement.unit_cost,
            total_cost=movement.total_cost,
            currency="IDR",
            movement_date=movement.movement_date,
            reference_type=movement.reference_document_type or "MANUAL",
            reference_id=movement.reference_document_id,
            warehouse_id=movement.warehouse_id,
            to_warehouse_id=movement.to_warehouse_id,
            batch_number=movement.batch_number,
            expiry_date=movement.expiry_date,
            notes=movement.notes,
            created_by=movement.created_by if isinstance(movement.created_by, UUID) else None,
            legal_entity_id=movement.legal_entity_id,
            status=movement.status.value,
            serial_number=movement.serial_number,
            reversed_at=movement.reversed_at,
            reversed_by=movement.reversed_by,
        )

    async def save_movement(self, movement: MovementEntity) -> MovementEntity:
        """Simpan movement (MovementEntity - model kanonik). Upsert by id."""
        try:
            existing = await self.session.get(InventoryMovementTable, movement.movement_id)
            if existing is not None:
                existing.status = movement.status.value
                existing.reversed_at = movement.reversed_at
                existing.reversed_by = movement.reversed_by
                existing.notes = movement.notes
                existing.version = movement.version
                await self._flush_and_commit()
                return movement
            table = self._to_orm_movement_entity(movement)
            self.session.add(table)
            await self._flush_and_commit()
            return movement
        except Exception as e:
            # FIX BUG KRITIS: sebelumnya tidak melakukan rollback saat gagal -
            # sesi database dibiarkan dalam status "pending rollback" dan
            # SEMUA request berikutnya yang memakai sesi yang sama (list item,
            # list gudang, update gudang, dst) ikut gagal terus dengan
            # PendingRollbackError sampai backend di-restart manual.
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to save movement: {e}") from e

    async def get_movement_by_id(
        self, movement_id: UUID, legal_entity_id: UUID | None = None
    ) -> MovementEntity | None:
        try:
            conditions = [InventoryMovementTable.id == movement_id]
            if legal_entity_id is not None:
                conditions.append(InventoryMovementTable.legal_entity_id == legal_entity_id)
            stmt = select(InventoryMovementTable, InventoryItemTable, WarehouseTable).join(
                InventoryItemTable, InventoryItemTable.id == InventoryMovementTable.item_id
            ).outerjoin(
                WarehouseTable, WarehouseTable.id == InventoryMovementTable.warehouse_id
            ).where(*conditions)
            result = await self.session.execute(stmt)
            row = result.first()
            if row is None:
                return None
            mov_table, item_table, _wh_table = row
            entity = self._to_domain_movement_entity(mov_table)
            entity.item_sku = item_table.item_code if hasattr(item_table, "item_code") else getattr(item_table, "sku", "")
            entity.item_name = item_table.item_name if hasattr(item_table, "item_name") else getattr(item_table, "name", "")
            return entity
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get movement by id: {e}") from e

    async def list_movements(
        self,
        legal_entity_id: UUID,
        item_id: UUID | None = None,
        movement_type: str | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[MovementEntity], int]:
        try:
            conditions = [InventoryMovementTable.legal_entity_id == legal_entity_id]
            if item_id is not None:
                conditions.append(InventoryMovementTable.item_id == item_id)
            if movement_type:
                conditions.append(InventoryMovementTable.movement_type == movement_type)
            if status:
                conditions.append(InventoryMovementTable.status == status)
            if start_date is not None:
                conditions.append(InventoryMovementTable.movement_date >= start_date)
            if end_date is not None:
                conditions.append(InventoryMovementTable.movement_date <= end_date)

            count_stmt = select(func.count()).select_from(InventoryMovementTable).where(*conditions)
            total = (await self.session.execute(count_stmt)).scalar_one()

            stmt = (
                select(InventoryMovementTable, InventoryItemTable)
                .join(InventoryItemTable, InventoryItemTable.id == InventoryMovementTable.item_id)
                .where(*conditions)
                .order_by(InventoryMovementTable.movement_date.desc(), InventoryMovementTable.created_at.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
            result = await self.session.execute(stmt)
            rows = result.all()
            entities = []
            for mov_table, item_table in rows:
                entity = self._to_domain_movement_entity(mov_table)
                entity.item_sku = getattr(item_table, "item_code", None) or getattr(item_table, "sku", "")
                entity.item_name = getattr(item_table, "item_name", None) or getattr(item_table, "name", "")
                entities.append(entity)
            return entities, total
        except Exception as e:
            # FIX BUG KRITIS: method baca ini sebelumnya tidak punya try/except
            # sama sekali. Kalau sesi database sudah dalam status rusak akibat
            # error SEBELUMNYA yang tidak sempat di-rollback (mis. dari
            # save_movement), setiap panggilan list_movements berikutnya ikut
            # gagal dengan PendingRollbackError tanpa penjelasan, dan status
            # rusak itu tidak pernah dibersihkan. Rollback di sini aman untuk
            # method baca (tidak ada perubahan data yang bisa hilang).
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to list movements: {e}") from e

    def _to_domain_fifo_layer(self, table: InventoryFIFOLayerTable) -> FIFOLayer:
        # FIX: use purchase_date instead of layer_date, remove warehouse_id
        return FIFOLayer(
            id=table.id,
            item_id=table.item_id,
            quantity=Quantity(value=table.quantity, uom=table.uom),
            cost_per_unit=Money(amount=table.unit_cost, currency=table.currency or "IDR"),
            layer_date=table.purchase_date,  # changed from layer_date
            remaining_quantity=Quantity(value=table.remaining_quantity, uom=table.uom),
            created_at=table.created_at,
        )

    # ========================================================================
    # AUDIT LOG
    # ========================================================================

    async def _log_audit(self, action: str, item_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "item_id": str(item_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # ITEM METHODS
    # ========================================================================

    async def add_item(self, item: InventoryItemAggregate) -> None:
        try:
            item_code = item.item.sku
            exists = await self.exists_by_item_code(item_code, item.legal_entity_id)
            if exists:
                raise DuplicateItemCodeError(f"Item code {item_code} already exists")
            table = await self._to_orm_item(item)
            self.session.add(table)
            await self._flush_and_commit()
            await self._log_audit("ADD", item.id, {"item_code": item_code})
            logger.info("Item added: %s", item_code)
        except DuplicateItemCodeError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to add item: {e}") from e

    async def get_item_by_id(self, item_id: UUID) -> InventoryItemAggregate | None:
        try:
            stmt = select(InventoryItemTable).where(InventoryItemTable.id == item_id, InventoryItemTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain_item(table) if table else None
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get item: {e}") from e

    async def get_item_by_sku(self, sku: str, legal_entity_id: UUID) -> InventoryItemAggregate | None:
        try:
            stmt = select(InventoryItemTable).where(
                InventoryItemTable.item_code == sku,
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain_item(table) if table else None
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get item by sku: {e}") from e

    async def update_item(self, item: InventoryItemAggregate) -> None:
        try:
            # FIX BUG KRITIS #3: InventoryItemTable memakai VersionMixin
            # (infrastructure/persistence_orm/base_model.py) yang mendaftarkan
            # `version_id_col` bawaan SQLAlchemy - artinya SQLAlchemy SENDIRI
            # sudah otomatis mengecek dan menaikkan kolom version setiap kali
            # baris diupdate, TANPA perlu (dan TIDAK BOLEH) disentuh manual.
            # v7 menambahkan `table.version = current_version + 1` lalu
            # `session.merge(table)` pada objek LEPAS (detached) - kombinasi
            # inilah yang menyebabkan error baru "Version id '9' ... does not
            # match existing version '8' - leave the version attribute unset
            # when merging". Pola yang benar (sudah dipakai & didokumentasikan
            # di sqlalchemy_bank_cash_repository_impl.py._update_cash_book:
            # "version TIDAK disentuh manual - version_id_col yang urus
            # otomatis") adalah: ambil baris yang SUDAH melekat (attached) ke
            # session lewat select(), ubah field-fieldnya langsung di objek
            # itu, lalu flush - JANGAN membangun objek baru lalu session.merge().
            stmt = select(InventoryItemTable).where(InventoryItemTable.id == item.id)
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if table is None:
                raise ItemNotFoundError(f"Item {item.id} not found")
            if table.version != item.version:
                raise OptimisticLockError(f"Version mismatch: expected {item.version}, got {table.version}")

            fresh = await self._to_orm_item(item)
            skip_columns = {"id", "version", "created_at", "created_by"}
            # FIX BUG KRITIS #4 (v9 keliru): sebelumnya loop di atas memakai
            # `InventoryItemTable.__table__.columns.keys()` - yaitu SEMUA
            # kolom fisik tabel (ternyata >100 kolom, dipakai bersama oleh
            # modul lain: manufacturing/BOM, purchasing, dsb - lihat
            # serial_required, cost_price, bom_required, dst di error
            # NotNullViolationError yang dilaporkan user). `_to_orm_item()`
            # hanya mengisi SEBAGIAN kecil kolom yang relevan untuk item
            # master sederhana ini; kolom lain yang TIDAK diisi otomatis
            # bernilai None pada objek `fresh` (transient/belum pernah
            # disimpan). Loop lama menyalin None itu ke SEMUA kolom lain
            # yang tidak disentuh - menimpa nilai asli di database jadi
            # NULL, melanggar constraint NOT NULL di kolom seperti
            # serial_required. Diperbaiki: HANYA salin atribut yang benar-
            # benar di-set eksplisit oleh _to_orm_item() (dicek lewat
            # vars(fresh), bukan daftar lengkap semua kolom tabel).
            explicitly_set = {
                k: v for k, v in vars(fresh).items()
                if k != "_sa_instance_state" and k not in skip_columns
            }
            for column, value in explicitly_set.items():
                setattr(table, column, value)
            table.updated_at = datetime.utcnow()
            # version TIDAK disentuh manual - version_id_col yang urus otomatis.
            await self._flush_and_commit()
            item_code = item.item.sku
            await self._log_audit("UPDATE", item.id, {"item_code": item_code})
            logger.info("Item updated: %s", item_code)
        except (ItemNotFoundError, OptimisticLockError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to update item: {e}") from e

    async def find_items_by_category(self, category: str, legal_entity_id: UUID | None = None) -> list[InventoryItemAggregate]:
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        try:
            stmt = select(InventoryItemTable).where(
                InventoryItemTable.category == category,
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            ).order_by(InventoryItemTable.item_code)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_item(t) for t in tables]
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to find items by category: {e}") from e

    async def get_current_stock(self, item_id: UUID, warehouse_id: UUID | None = None) -> Decimal:
        try:
            if warehouse_id is None:
                stmt = select(InventoryItemTable.current_stock).where(InventoryItemTable.id == item_id)
                result = await self.session.execute(stmt)
                stock = result.scalar_one_or_none()
                return Decimal(str(stock)) if stock else Decimal(0)
            else:
                # Compute from movements for specific warehouse
                stmt = select(
                    func.coalesce(
                        func.sum(
                            func.case(
                                (InventoryMovementTable.movement_type.in_(['IN', 'TRANSFER_IN']), InventoryMovementTable.quantity),
                                else_= -InventoryMovementTable.quantity
                            )
                        ), 0
                    )
                ).where(
                    InventoryMovementTable.item_id == item_id,
                    InventoryMovementTable.warehouse_id == warehouse_id,
                )
                result = await self.session.execute(stmt)
                stock = result.scalar() or Decimal(0)
                return Decimal(str(stock))
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get current stock: {e}") from e

    async def get_all_items(
        self, legal_entity_id: UUID | None = None, limit: int = 100, offset: int = 0
    ) -> list[InventoryItemAggregate]:
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        try:
            stmt = select(InventoryItemTable).where(
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            ).order_by(InventoryItemTable.item_code).limit(limit).offset(offset)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_item(t) for t in tables]
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get all items: {e}") from e

    # ========================================================================
    # MOVEMENT
    # ========================================================================

    async def record_movement(self, movement: StockMovement) -> None:
        try:
            # Validate sufficient stock for out movements
            if movement.movement_type in (StockMovementType.OUT, StockMovementType.TRANSFER_OUT):
                current = await self.get_current_stock(movement.item_id, movement.warehouse_id)
                if current < movement.quantity.value:
                    raise InsufficientStockError(
                        f"Insufficient stock: available {current}, required {movement.quantity.value}"
                    )
            table = await self._to_orm_movement(movement)
            self.session.add(table)
            await self._flush_and_commit()
            await self._log_audit("MOVEMENT", movement.item_id, {"movement_number": movement.movement_number})
            logger.info("Movement added: %s", movement.movement_number)
        except (InsufficientStockError, ItemNotFoundError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to record movement: {e}") from e

    async def get_movements_by_item(
        self, item_id: UUID, start_date: date | None = None, end_date: date | None = None, limit: int = 100
    ) -> list[MovementEntity]:
        try:
            conditions = [InventoryMovementTable.item_id == item_id]
            if start_date is not None:
                conditions.append(InventoryMovementTable.movement_date >= start_date)
            if end_date is not None:
                conditions.append(InventoryMovementTable.movement_date <= end_date)
            stmt = select(InventoryMovementTable).where(*conditions).order_by(
                InventoryMovementTable.movement_date.desc()
            ).limit(limit)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_movement_entity(t) for t in tables]
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get movements: {e}") from e

    async def get_movements_by_reference(self, reference_type: str, reference_id: UUID) -> list[MovementEntity]:
        try:
            stmt = select(InventoryMovementTable).where(
                InventoryMovementTable.reference_type == reference_type,
                InventoryMovementTable.reference_id == reference_id,
            ).order_by(InventoryMovementTable.movement_date)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_movement_entity(t) for t in tables]
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get movements by reference: {e}") from e

    # ========================================================================
    # VALUATION
    # ========================================================================

    async def get_inventory_value(
        self, legal_entity_id: UUID, as_of_date: date, valuation_method: str = "AVERAGE"
    ) -> Decimal:
        try:
            # For simplicity, compute from current stock * average_cost
            stmt = select(
                func.coalesce(func.sum(InventoryItemTable.current_stock * InventoryItemTable.average_cost), 0)
            ).where(
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
                InventoryItemTable.is_active == True,
            )
            result = await self.session.execute(stmt)
            value = result.scalar()
            return Decimal(str(value)) if value else Decimal(0)
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get inventory value: {e}") from e

    async def get_fifo_layers(self, item_id: UUID, warehouse_id: UUID) -> list[FIFOLayer]:
        """
        Get FIFO layers for an item.
        FIX: remove warehouse_id filter because InventoryFIFOLayerTable does not have warehouse_id.
        """
        try:
            # Removed warehouse_id condition; now filters only by item_id.
            stmt = select(InventoryFIFOLayerTable).where(
                InventoryFIFOLayerTable.item_id == item_id,
                InventoryFIFOLayerTable.remaining_quantity > 0,
            ).order_by(InventoryFIFOLayerTable.purchase_date)  # order by purchase_date
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_fifo_layer(t) for t in tables]
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get FIFO layers: {e}") from e

    # ========================================================================
    # REORDER
    # ========================================================================

    async def get_items_below_reorder_point(self, legal_entity_id: UUID) -> list[InventoryItemAggregate]:
        conditions = [
            InventoryItemTable.legal_entity_id == legal_entity_id,
            InventoryItemTable.deleted_at.is_(None),
            InventoryItemTable.current_stock <= InventoryItemTable.reorder_point,
        ]
        try:
            stmt = select(InventoryItemTable).where(and_(*conditions)).order_by(InventoryItemTable.current_stock)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_item(t) for t in tables]
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get items below reorder point: {e}") from e

    async def get_recommended_po_items(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        items = await self.get_items_below_reorder_point(legal_entity_id)
        result = []
        for item in items:
            shortage = item.reorder_point.value - item.current_stock.value
            if shortage > 0:
                result.append({
                    "item_id": str(item.id),
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "current_stock": str(item.current_stock.value),
                    "reorder_point": str(item.reorder_point.value),
                    "reorder_quantity": str(item.reorder_quantity.value) if item.reorder_quantity else "0",
                    "shortage": str(shortage),
                    "recommended_po": str(max(shortage, item.reorder_quantity.value or 0)),
                    "unit_cost": str(item.standard_cost.amount),
                })
        return result

    # ========================================================================
    # STOCK OPNAME
    # ========================================================================

    async def create_stock_opname(
        self,
        warehouse_id: UUID,
        created_by: UUID,
        notes: str | None = None,
        items_data: list[dict] | None = None,  # [{"item_id": UUID, "physical_count": Decimal}]
    ) -> UUID:
        """
        Create a new stock opname.
        If items_data is provided, compare system stock vs physical stock for each item.
        """
        try:
            opname_id = uuid4()
            opname_number = f"OPN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            opname = StockOpnameTable(
                id=opname_id,
                opname_number=opname_number,
                warehouse_id=warehouse_id,
                opname_date=datetime.utcnow().date(),
                status="draft",
                lines=[],
                total_adjustments=0,
                adjustment_value=0,
                created_at=datetime.utcnow(),
                created_by=created_by,
            )

            # ===== SYSTEM vs PHYSICAL COMPARISON =====
            if items_data:
                comparisons = []
                for item_data in items_data:
                    item_id = item_data["item_id"]
                    physical = Decimal(str(item_data["physical_count"]))
                    system = await self.get_current_stock(item_id, warehouse_id)
                    diff = physical - system
                    comparisons.append({
                        "item_id": str(item_id),
                        "system_count": str(system),
                        "physical_count": str(physical),
                        "difference": str(diff),
                    })
                    logger.info(
                        f"Opname comparison: item={item_id}, system={system}, physical={physical}, diff={diff}"
                    )
                # Store comparison in notes or separate field
                opname.notes = (notes or "") + f" | Comparisons: {comparisons}"

            self.session.add(opname)
            await self._flush_and_commit()
            await self._log_audit("CREATE_OPNAME", opname_id, {
                "warehouse_id": str(warehouse_id),
                "items_count": len(items_data) if items_data else 0,
            })
            return opname_id
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to create stock opname: {e}") from e

    async def record_opname_item(
        self, opname_id: UUID, item_id: UUID, physical_count: Decimal, system_count: Decimal, notes: str | None = None
    ) -> None:
        try:
            stmt = select(StockOpnameTable).where(StockOpnameTable.id == opname_id).with_for_update()
            result = await self.session.execute(stmt)
            opname_table = result.scalar_one_or_none()
            if not opname_table:
                raise InventoryRepositoryError(f"Opname {opname_id} not found")
            if opname_table.status != "draft":
                raise InventoryRepositoryError("Opname already completed")

            diff = physical_count - system_count
            lines = opname_table.lines or []
            lines.append({
                "item_id": str(item_id),
                "physical_count": str(physical_count),
                "system_count": str(system_count),
                "difference": str(diff),
                "notes": notes,
                "recorded_at": datetime.utcnow().isoformat(),
            })
            total_adj = sum(Decimal(str(l["difference"])) for l in lines)
            stmt_update = update(StockOpnameTable).where(StockOpnameTable.id == opname_id).values(
                lines=lines,
                total_adjustments=total_adj,
                updated_at=datetime.utcnow(),
            )
            await self.session.execute(stmt_update)
            await self._flush_and_commit()
            await self._log_audit("RECORD_OPNAME_ITEM", item_id, {
                "opname_id": str(opname_id),
                "system": str(system_count),
                "physical": str(physical_count),
                "difference": str(diff)
            })
            logger.info("Opname item recorded: system=%s, physical=%s, diff=%s", system_count, physical_count, diff)
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to record opname item: {e}") from e

    async def complete_stock_opname(self, opname_id: UUID, closed_by: UUID, auto_adjust: bool = True) -> dict[str, Any]:
        try:
            stmt = select(StockOpnameTable).where(StockOpnameTable.id == opname_id).with_for_update()
            result = await self.session.execute(stmt)
            opname_table = result.scalar_one_or_none()
            if not opname_table:
                raise InventoryRepositoryError(f"Opname {opname_id} not found")
            if opname_table.status != "draft":
                raise InventoryRepositoryError("Opname already completed")

            adjustments = []
            total_system = Decimal(0)
            total_physical = Decimal(0)
            total_diff = Decimal(0)

            for line in opname_table.lines or []:
                system = Decimal(str(line.get("system_count", 0)))
                physical = Decimal(str(line.get("physical_count", 0)))
                diff = physical - system
                total_system += system
                total_physical += physical
                total_diff += diff

                if diff != 0 and auto_adjust:
                    item_id = UUID(line["item_id"])
                    # Create adjustment movement
                    movement = StockMovement(
                        id=uuid4(),
                        movement_number=await self.get_next_movement_number("ADJ"),
                        item_id=item_id,
                        movement_type=StockMovementType.ADJUSTMENT,
                        quantity=Quantity(value=abs(diff), uom="PCS"),  # need proper uom
                        unit_cost=Money(amount=Decimal(0), currency="IDR"),  # will be set later
                        total_cost=Money(amount=Decimal(0), currency="IDR"),
                        movement_date=datetime.utcnow().date(),
                        reference_type="STOCK_OPNAME",
                        reference_id=opname_id,
                        warehouse_id=opname_table.warehouse_id,
                        notes=f"Adjustment from opname {opname_id}",
                        created_by=closed_by,
                    )
                    # We need to adjust stock; simplified: use update_stock directly
                    item = await self.get_item_by_id(item_id)
                    if item:
                        # Update item stock
                        item.current_stock = Quantity(value=item.current_stock.value + diff, uom=item.unit_of_measure)
                        # FIX: version TIDAK di-pre-increment manual di sini - update_item()
                        # sendiri yang mengecek versi lama sama dengan yang di database, dan
                        # membiarkan SQLAlchemy version_id_col menaikkannya otomatis saat flush.
                        # Pre-increment manual seperti sebelumnya membuat update_item() SELALU
                        # menolak dengan OptimisticLockError (versi yang dikirim jadi tidak
                        # pernah cocok dengan versi asli di database).
                        await self.update_item(item)
                        adjustments.append({
                            "item_id": str(item_id),
                            "system": str(system),
                            "physical": str(physical),
                            "difference": str(diff),
                        })

            stmt_update = update(StockOpnameTable).where(StockOpnameTable.id == opname_id).values(
                status="completed",
                approved_by=closed_by,
                approved_at=datetime.utcnow(),
                adjustments_applied=auto_adjust,
            )
            await self.session.execute(stmt_update)
            await self._flush_and_commit()
            await self._log_audit("COMPLETE_OPNAME", opname_id, {
                "auto_adjust": auto_adjust,
                "adjustments": len(adjustments),
                "summary": {"total_system": str(total_system), "total_physical": str(total_physical), "total_difference": str(total_diff)}
            })

            return {
                "opname_id": str(opname_id),
                "adjustments": adjustments,
                "summary": {"total_system": str(total_system), "total_physical": str(total_physical), "total_difference": str(total_diff)}
            }
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to complete stock opname: {e}") from e

    # ========================================================================
    # STOCK OPNAME (model kanonik) - dipakai create_stock_opname/approve_stock_opname
    # di service_inventory.py. Model kanonik adalah StockOpnameEntity (header + lines)
    # dari domain.inventory.stock_opname_entity - BUKAN parameter mentah yang
    # dipakai create_stock_opname()/complete_stock_opname() di atas, yang
    # dipertahankan untuk endpoint lain yang memakai alur berbeda.
    # ========================================================================

    async def save_opname(self, opname: StockOpname) -> StockOpname:
        """Simpan StockOpnameEntity (header + lines). Upsert by id."""
        try:
            existing = await self.session.get(StockOpnameTable, opname.opname_id)
            total_expected = sum((i.system_quantity * i.unit_cost for i in opname.items), Decimal("0"))
            total_counted = sum((i.physical_quantity * i.unit_cost for i in opname.items), Decimal("0"))
            total_variance = sum((i.discrepancy_value for i in opname.items), Decimal("0"))

            if existing is not None:
                existing.status = opname.status.value
                existing.approved_by = opname.approved_by
                existing.approved_at = opname.approved_at
                existing.completed_by = opname.completed_by if hasattr(opname, "completed_by") else existing.completed_by
                existing.total_expected_value = total_expected
                existing.total_counted_value = total_counted
                existing.total_variance_value = total_variance
                existing.version = opname.version
                # Sinkronkan ulang lines (hapus lama, tulis baru - jumlah baris kecil, aman)
                await self.session.execute(
                    text("DELETE FROM stock_opname_line WHERE stock_opname_id = :oid"),
                    {"oid": opname.opname_id},
                )
                for it in opname.items:
                    self.session.add(StockOpnameLineTable(
                        stock_opname_id=opname.opname_id,
                        product_id=it.item_id,
                        product_code=it.item_sku,
                        product_name=it.item_name,
                        warehouse_id=opname.warehouse_id or existing.warehouse_id,
                        system_quantity=it.system_quantity,
                        physical_quantity=it.physical_quantity,
                        difference_quantity=it.discrepancy,
                        unit_cost=it.unit_cost,
                        difference_value=it.discrepancy_value,
                        notes=it.notes,
                    ))
                await self._flush_and_commit()
                return opname

            table = StockOpnameTable(
                id=opname.opname_id,
                legal_entity_id=opname.legal_entity_id,
                opname_number=opname.opname_number,
                opname_date=opname.opname_date,
                warehouse_id=opname.warehouse_id,
                description=opname.notes,
                status=opname.status.value,
                total_expected_value=total_expected,
                total_counted_value=total_counted,
                total_variance_value=total_variance,
                created_by=opname.created_by,
            )
            self.session.add(table)
            for it in opname.items:
                self.session.add(StockOpnameLineTable(
                    stock_opname_id=opname.opname_id,
                    product_id=it.item_id,
                    product_code=it.item_sku,
                    product_name=it.item_name,
                    warehouse_id=opname.warehouse_id,
                    system_quantity=it.system_quantity,
                    physical_quantity=it.physical_quantity,
                    difference_quantity=it.discrepancy,
                    unit_cost=it.unit_cost,
                    difference_value=it.discrepancy_value,
                    notes=it.notes,
                ))
            await self._flush_and_commit()
            return opname
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to save opname: {e}") from e

    async def list_opnames(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
        warehouse_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Daftar header stock opname (ringkas, tanpa lines) untuk ditampilkan
        di dropdown/tabel frontend - dipakai supaya user memilih opname yang
        mau di-approve/dibatalkan dari daftar nyata, bukan mengetik UUID
        secara manual (sebelumnya tidak ada endpoint list sama sekali, jadi
        satu-satunya cara mendapatkan opname_id adalah menyalinnya sendiri
        dari respons saat membuat opname)."""
        try:
            conditions = [StockOpnameTable.legal_entity_id == legal_entity_id]
            if status:
                conditions.append(StockOpnameTable.status == status)
            if warehouse_id:
                conditions.append(StockOpnameTable.warehouse_id == warehouse_id)

            count_stmt = select(func.count()).select_from(StockOpnameTable).where(*conditions)
            total = (await self.session.execute(count_stmt)).scalar_one()

            stmt = (
                select(StockOpnameTable)
                .where(*conditions)
                .order_by(StockOpnameTable.opname_date.desc(), StockOpnameTable.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = (await self.session.execute(stmt)).scalars().all()

            items = [
                {
                    "id": row.id,
                    "opname_number": row.opname_number,
                    "opname_date": row.opname_date,
                    "warehouse_id": row.warehouse_id,
                    "status": row.status,
                    "description": row.description,
                    "total_expected_value": row.total_expected_value,
                    "total_counted_value": row.total_counted_value,
                    "total_variance_value": row.total_variance_value,
                    "created_by": row.created_by,
                    "approved_by": row.approved_by,
                    "approved_at": row.approved_at,
                }
                for row in rows
            ]
            return items, total
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to list stock opnames: {e}") from e

    async def get_opname_by_id(self, opname_id: UUID) -> StockOpname | None:
        try:
            header = await self.session.get(StockOpnameTable, opname_id)
            if header is None:
                return None
            stmt = select(StockOpnameLineTable).where(StockOpnameLineTable.stock_opname_id == opname_id)
            result = await self.session.execute(stmt)
            lines = result.scalars().all()

            items = [
                OpnameItem(
                    item_id=line.product_id,
                    item_sku=line.product_code,
                    item_name=line.product_name,
                    system_quantity=line.system_quantity,
                    physical_quantity=line.physical_quantity,
                    discrepancy=line.difference_quantity,
                    discrepancy_type=(
                        DiscrepancyType.SURPLUS if line.difference_quantity > 0
                        else DiscrepancyType.SHORTAGE if line.difference_quantity < 0
                        else DiscrepancyType.NONE
                    ),
                    unit_cost=line.unit_cost,
                    notes=line.notes or "",
                )
                for line in lines
            ]
            return StockOpname(
                opname_id=header.id,
                opname_number=header.opname_number,
                warehouse_id=header.warehouse_id,
                warehouse_name="",
                opname_date=header.opname_date,
                status=OpnameStatus.from_string(header.status),
                items=items,
                performed_by=header.created_by or UUID(int=0),
                approved_by=header.approved_by,
                approved_at=header.approved_at,
                notes=header.description or "",
                created_by=header.created_by or UUID(int=0),
                legal_entity_id=header.legal_entity_id,
                version=header.version,
            )
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get opname: {e}") from e

    async def get_outbound_movements(
        self, legal_entity_id: UUID, from_date: date | None = None, to_date: date | None = None
    ) -> list[MovementEntity]:
        """Ambil semua movement outbound (dipakai calculate_cogs).

        FIX: sebelumnya memfilter movement_type.in_([nilai granular seperti
        "adjustment_out", "sales_issue", ...]) - nilai itu TIDAK PERNAH cocok
        dengan apa yang benar-benar tersimpan di kolom database (yang sejak
        perbaikan _db_movement_type() di atas hanya berisi salah satu dari 5
        nilai: IN/OUT/ADJUSTMENT/TRANSFER_IN/TRANSFER_OUT). Query lama ini
        akan SELALU mengembalikan list kosong sejak awal (movement_type di
        kolom database tidak pernah berupa string granular), yang berarti
        perhitungan COGS berbasis method ini tidak pernah mendapat data.
        Filter diperbaiki memakai nilai yang benar-benar tersimpan.
        Catatan: kolom "ADJUSTMENT" tidak membawa informasi arah
        (masuk/keluar) - hanya "OUT" dan "TRANSFER_OUT" yang pasti berarti
        stok keluar, jadi disitulah batas informasi yang tersedia dari
        skema tabel yang ada tanpa migrasi tambahan.
        """
        outbound_db_values = ["OUT", "TRANSFER_OUT"]
        try:
            conditions = [
                InventoryMovementTable.legal_entity_id == legal_entity_id,
                InventoryMovementTable.movement_type.in_(outbound_db_values),
            ]
            if from_date is not None:
                conditions.append(InventoryMovementTable.movement_date >= from_date)
            if to_date is not None:
                conditions.append(InventoryMovementTable.movement_date <= to_date)
            stmt = select(InventoryMovementTable, InventoryItemTable).join(
                InventoryItemTable, InventoryItemTable.id == InventoryMovementTable.item_id
            ).where(*conditions).order_by(InventoryMovementTable.movement_date)
            result = await self.session.execute(stmt)
            rows = result.all()
            entities = []
            for mov_table, item_table in rows:
                entity = self._to_domain_movement_entity(mov_table)
                entity.item_sku = getattr(item_table, "item_code", None) or getattr(item_table, "sku", "")
                entity.item_name = getattr(item_table, "item_name", None) or getattr(item_table, "name", "")
                entities.append(entity)
            return entities
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get outbound movements: {e}") from e

    # ========================================================================
    # TRANSFER
    # ========================================================================

    async def transfer_stock(
        self,
        item_id: UUID,
        from_warehouse_id: UUID,
        to_warehouse_id: UUID,
        quantity: Decimal,
        user_id: UUID,
        reference_type: str,
        reference_id: UUID,
        unit_cost: Decimal | None = None,
    ) -> tuple[UUID, UUID]:
        if from_warehouse_id == to_warehouse_id:
            raise ValueError("Source and destination warehouses are the same")

        item = await self.get_item_by_id(item_id)
        if not item:
            raise ItemNotFoundError(f"Item {item_id} not found")

        source_stock = await self.get_current_stock(item_id, from_warehouse_id)
        if quantity > source_stock:
            raise InsufficientStockError(f"Insufficient stock in source: available {source_stock}, requested {quantity}")

        cost = unit_cost if unit_cost is not None else item.average_cost.amount

        # Movement out
        mov_out = StockMovement(
            id=uuid4(),
            movement_number=await self.get_next_movement_number("TRF_OUT"),
            item_id=item_id,
            movement_type=StockMovementType.TRANSFER_OUT,
            quantity=Quantity(value=quantity, uom=item.unit_of_measure),
            unit_cost=Money(amount=cost, currency=item.average_cost.currency),
            total_cost=Money(amount=cost * quantity, currency=item.average_cost.currency),
            movement_date=datetime.utcnow().date(),
            reference_type=reference_type,
            reference_id=reference_id,
            warehouse_id=from_warehouse_id,
            to_warehouse_id=to_warehouse_id,
            notes=f"Transfer out to {to_warehouse_id} - IN_TRANSIT",
            created_by=user_id,
        )
        await self.record_movement(mov_out)

        # Movement in
        mov_in = StockMovement(
            id=uuid4(),
            movement_number=await self.get_next_movement_number("TRF_IN"),
            item_id=item_id,
            movement_type=StockMovementType.TRANSFER_IN,
            quantity=Quantity(value=quantity, uom=item.unit_of_measure),
            unit_cost=Money(amount=cost, currency=item.average_cost.currency),
            total_cost=Money(amount=cost * quantity, currency=item.average_cost.currency),
            movement_date=datetime.utcnow().date(),
            reference_type=reference_type,
            reference_id=reference_id,
            warehouse_id=to_warehouse_id,
            to_warehouse_id=from_warehouse_id,
            notes=f"Transfer in from {from_warehouse_id} - RECEIVED",
            created_by=user_id,
        )
        await self.record_movement(mov_in)

        await self._log_audit("TRANSFER", item_id, {
            "from": str(from_warehouse_id),
            "to": str(to_warehouse_id),
            "qty": str(quantity),
            "status": "COMPLETED",
            "out_movement": str(mov_out.id),
            "in_movement": str(mov_in.id),
        })
        logger.info("Stock transferred: %s from %s to %s", item_id, from_warehouse_id, to_warehouse_id)
        return mov_out.id, mov_in.id

    # ========================================================================
    # INTER-WAREHOUSE TRANSFER (model kanonik) - dipakai create_transfer/
    # complete_transfer di service_inventory.py. Model kanonik adalah
    # InterWarehouseTransferEntity (header + lines) dari
    # domain.inventory.inter_warehouse_transfer_entity - BUKAN transfer_stock()
    # di atas, yang dipertahankan sebagai alur lama/tidak dipakai lagi.
    # ========================================================================

    async def save_transfer(self, transfer: InterWarehouseTransfer) -> InterWarehouseTransfer:
        """Simpan InterWarehouseTransferEntity (header + lines). Upsert by id."""
        try:
            existing = await self.session.get(InterWarehouseTransferTable, transfer.transfer_id)
            if existing is not None:
                existing.status = transfer.status.value
                existing.approved_by = transfer.approved_by
                existing.approved_at = transfer.approved_at
                existing.shipped_by = transfer.shipped_by
                existing.shipped_at = transfer.shipped_at
                existing.received_by = transfer.received_by
                existing.received_at = transfer.received_at
                existing.completed_by = transfer.completed_by
                existing.completed_at = transfer.completed_at
                existing.notes = transfer.notes
                existing.quantity = transfer.quantity
                existing.unit_cost = transfer.unit_cost
                existing.total_value = transfer.total_value
                existing.version = transfer.version
                await self._flush_and_commit()
                return transfer

            table = InterWarehouseTransferTable(
                id=transfer.transfer_id,
                legal_entity_id=transfer.legal_entity_id,
                transfer_number=transfer.transfer_number,
                source_warehouse_id=transfer.source_warehouse_id,
                source_warehouse_name=transfer.source_warehouse_name,
                destination_warehouse_id=transfer.destination_warehouse_id,
                destination_warehouse_name=transfer.destination_warehouse_name,
                transfer_date=transfer.transfer_date,
                priority=transfer.priority.value,
                status=transfer.status.value,
                quantity=transfer.quantity,
                unit_cost=transfer.unit_cost,
                total_value=transfer.total_value,
                notes=transfer.notes,
                requested_by=transfer.requested_by,
                requested_at=transfer.requested_at,
                created_by=transfer.requested_by,
            )
            self.session.add(table)
            for it in transfer.items:
                self.session.add(InterWarehouseTransferLineTable(
                    transfer_id=transfer.transfer_id,
                    item_id=it.item_id,
                    item_sku=it.item_sku,
                    item_name=it.item_name,
                    quantity=it.quantity,
                    unit_cost=it.unit_cost,
                    total_value=it.total_value,
                    batch_number=getattr(it, "batch_number", None),
                    expiry_date=getattr(it, "expiry_date", None),
                ))
            await self._flush_and_commit()
            return transfer
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to save transfer: {e}") from e

    async def get_transfer_by_id(self, transfer_id: UUID) -> InterWarehouseTransfer | None:
        try:
            header = await self.session.get(InterWarehouseTransferTable, transfer_id)
            if header is None:
                return None
            stmt = select(InterWarehouseTransferLineTable).where(
                InterWarehouseTransferLineTable.transfer_id == transfer_id
            )
            result = await self.session.execute(stmt)
            lines = result.scalars().all()
            items = [
                TransferItem(
                    item_id=line.item_id,
                    item_sku=line.item_sku,
                    item_name=line.item_name,
                    quantity=line.quantity,
                    unit_cost=line.unit_cost,
                    total_value=line.total_value,
                    batch_number=line.batch_number,
                    expiry_date=line.expiry_date,
                )
                for line in lines
            ]
            return InterWarehouseTransfer(
                transfer_id=header.id,
                transfer_number=header.transfer_number,
                source_warehouse_id=header.source_warehouse_id,
                source_warehouse_name=header.source_warehouse_name,
                destination_warehouse_id=header.destination_warehouse_id,
                destination_warehouse_name=header.destination_warehouse_name,
                transfer_date=header.transfer_date,
                priority=TransferPriority(header.priority),
                status=TransferStatus(header.status),
                items=items,
                notes=header.notes or "",
                requested_by=header.requested_by or UUID(int=0),
                requested_at=header.requested_at,
                approved_by=header.approved_by,
                approved_at=header.approved_at,
                shipped_by=header.shipped_by,
                shipped_at=header.shipped_at,
                received_by=header.received_by,
                received_at=header.received_at,
                completed_by=header.completed_by,
                completed_at=header.completed_at,
                legal_entity_id=header.legal_entity_id,
                version=header.version,
            )
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get transfer: {e}") from e

    # ========================================================================
    # EXPORT / IMPORT
    # ========================================================================

    async def export_items_to_csv(self, legal_entity_id: UUID | None = None) -> str:
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        items = await self.get_all_items(legal_entity_id, limit=10000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "item_code", "item_name", "category", "item_type", "unit_of_measure",
            "current_stock", "reorder_point", "reorder_quantity", "standard_cost",
            "selling_price", "valuation_method", "warehouse_id", "is_active"
        ])
        for item in items:
            writer.writerow([
                item.item_code,
                item.item_name,
                item.category or "",
                item.item_type.value,
                item.unit_of_measure,
                str(item.current_stock.value),
                str(item.reorder_point.value) if item.reorder_point else "0",
                str(item.reorder_quantity.value) if item.reorder_quantity else "0",
                str(item.standard_cost.amount),
                str(item.selling_price.amount),
                item.valuation_method.value,
                str(item.warehouse_id) if item.warehouse_id else "",
                "1" if item.is_active else "0",
            ])
        return output.getvalue()

    async def import_items_from_csv(self, csv_content: str, legal_entity_id: UUID, created_by: UUID) -> int:
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                item = InventoryItemAggregate(
                    id=uuid4(),
                    item_code=row["item_code"],
                    item_name=row["item_name"],
                    category=row.get("category"),
                    item_type=ItemType(row.get("item_type", "trading")),
                    unit_of_measure=row.get("unit_of_measure", "PCS"),
                    current_stock=Quantity(value=Decimal(row.get("current_stock", "0")), uom=row.get("unit_of_measure", "PCS")),
                    reorder_point=Quantity(value=Decimal(row.get("reorder_point", "0")), uom=row.get("unit_of_measure", "PCS")),
                    reorder_quantity=Quantity(value=Decimal(row.get("reorder_quantity", "0")), uom=row.get("unit_of_measure", "PCS")),
                    standard_cost=Money(amount=Decimal(row.get("standard_cost", "0")), currency="IDR"),
                    selling_price=Money(amount=Decimal(row.get("selling_price", "0")), currency="IDR"),
                    valuation_method=ValuationMethod(row.get("valuation_method", "FIFO")),
                    warehouse_id=UUID(row["warehouse_id"]) if row.get("warehouse_id") else None,
                    is_active=row.get("is_active", "1") == "1",
                    legal_entity_id=legal_entity_id,
                    created_by=created_by,
                )
                await self.add_item(item)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import row: {e}")
        return count

    # ========================================================================
    # STATISTICS & AUDIT
    # ========================================================================

    async def get_statistics(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        try:
            total = await self.session.scalar(
                select(func.count()).where(
                    InventoryItemTable.legal_entity_id == legal_entity_id,
                    InventoryItemTable.deleted_at.is_(None),
                )
            ) or 0
            active = await self.session.scalar(
                select(func.count()).where(
                    InventoryItemTable.legal_entity_id == legal_entity_id,
                    InventoryItemTable.is_active == True,
                    InventoryItemTable.deleted_at.is_(None),
                )
            ) or 0
            total_value = await self.get_inventory_value(legal_entity_id, date.today())
            low_stock = len(await self.get_items_below_reorder_point(legal_entity_id))
            movements = await self.session.scalar(
                select(func.count()).select_from(InventoryMovementTable)
            ) or 0
            return {
                "total_items": total,
                "active_items": active,
                "inactive_items": total - active,
                "total_inventory_value": str(total_value),
                "low_stock_items": low_stock,
                "total_movements": movements,
            }
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to get statistics: {e}") from e

    async def get_audit_log(self, item_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        logs = self._audit_log
        if item_id:
            logs = [l for l in logs if l.get("item_id") == str(item_id)]
        return logs[-limit:]

    async def health_check(self) -> dict[str, Any]:
        try:
            await self.session.execute(text("SELECT 1"))
            return {"status": "healthy", "repository": "InventoryRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "InventoryRepository", "error": str(e)}

    # ========================================================================
    # HELPER: EXISTS BY ITEM CODE
    # ========================================================================

    async def exists_by_item_code(self, item_code: str, legal_entity_id: UUID) -> bool:
        try:
            stmt = select(func.count()).select_from(InventoryItemTable).where(
                InventoryItemTable.item_code == item_code,
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to check item code: {e}") from e

    # ========================================================================
    # HELPER: GENERATE MOVEMENT NUMBER
    # ========================================================================

    async def get_next_movement_number(self, prefix: str = "MOV", year: int = None) -> str:
        if year is None:
            year = date.today().year
        try:
            pattern = f"{prefix}-{year}-%"
            stmt = select(InventoryMovementTable.movement_number).where(
                InventoryMovementTable.movement_number.like(pattern)
            ).order_by(InventoryMovementTable.movement_number.desc()).limit(1)
            result = await self.session.execute(stmt)
            last_number = result.scalar_one_or_none()
            seq = int(last_number.split("-")[-1]) + 1 if last_number else 1
            return f"{prefix}-{year}-{seq:06d}"
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to generate movement number: {e}") from e

    # ========================================================================
    # EXTRA: DELETE ITEM (opsional, tidak ada di port)
    # ========================================================================

    async def delete_item(self, item_id: UUID) -> bool:
        """Soft-delete item (extra method, not in port)."""
        try:
            stmt = select(InventoryItemTable).where(
                InventoryItemTable.id == item_id,
                InventoryItemTable.deleted_at.is_(None)
            ).with_for_update()
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return False
            table.deleted_at = datetime.utcnow()
            table.is_active = False
            # version TIDAK disentuh manual - version_id_col yang urus otomatis.
            await self._flush_and_commit()
            await self._log_audit("DELETE", item_id, {})
            logger.info("Item %s soft deleted", item_id)
            return True
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to delete item: {e}") from e

    # ========================================================================
    # WAREHOUSE VALIDATION (for checker compliance)
    # ========================================================================

    async def get_warehouse_by_code(self, warehouse_code: str, legal_entity_id: UUID) -> bool:
        """Check if warehouse exists by code."""
        try:
            stmt = select(WarehouseTable).where(
                WarehouseTable.warehouse_code == warehouse_code,  # FIX: code -> warehouse_code
                WarehouseTable.legal_entity_id == legal_entity_id,
                WarehouseTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none() is not None
        except Exception:
            return False

    async def get_warehouse_by_id(self, warehouse_id: UUID) -> bool:
        """Check if warehouse exists by ID."""
        try:
            stmt = select(WarehouseTable).where(
                WarehouseTable.id == warehouse_id,
                WarehouseTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none() is not None
        except Exception:
            return False

    async def list_warehouses(
        self, legal_entity_id: UUID, is_active: bool | None = None
    ) -> list[dict[str, Any]]:
        """List semua warehouse milik satu legal entity (dipakai endpoint GET /warehouses)."""
        try:
            conditions = [
                WarehouseTable.legal_entity_id == legal_entity_id,
                WarehouseTable.deleted_at.is_(None),
            ]
            if is_active is not None:
                conditions.append(WarehouseTable.is_active == is_active)
            stmt = select(WarehouseTable).where(*conditions).order_by(WarehouseTable.warehouse_code)
            result = await self.session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "id": w.id,
                    "warehouse_code": w.warehouse_code,
                    "name": w.name,
                    "location_code": w.location_code,
                    "is_active": w.is_active,
                    "is_default": w.is_default,
                    "notes": w.notes,
                    "created_at": w.created_at,
                    "created_by": w.created_by,
                    "version": w.version,
                }
                for w in rows
            ]
        except Exception as e:
            # FIX BUG KRITIS: method baca ini sebelumnya tidak punya try/except
            # sama sekali - kalau sesi database sudah rusak akibat error
            # SEBELUMNYA di request lain yang tidak sempat di-rollback, setiap
            # panggilan list_warehouses berikutnya ikut gagal terus dengan
            # PendingRollbackError tanpa pernah pulih sampai backend direstart.
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to list warehouses: {e}") from e

    async def get_warehouse_name_by_id(self, warehouse_id: UUID) -> str | None:
        """Lookup nama warehouse langsung dari ID (dipakai untuk enrich response movement)."""
        try:
            stmt = select(WarehouseTable.name).where(WarehouseTable.id == warehouse_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception:
            return None

    @staticmethod
    def _warehouse_to_dict(w: WarehouseTable) -> dict[str, Any]:
        return {
            "id": w.id,
            "warehouse_code": w.warehouse_code,
            "name": w.name,
            "location_code": w.location_code,
            "is_active": w.is_active,
            "is_default": w.is_default,
            "notes": w.notes,
            "created_at": w.created_at,
            "created_by": w.created_by,
            "version": w.version,
        }

    async def create_warehouse(
        self,
        legal_entity_id: UUID,
        warehouse_code: str,
        name: str,
        location_code: str | None = None,
        is_active: bool = True,
        is_default: bool = False,
        notes: str | None = None,
        created_by: UUID | None = None,
    ) -> dict[str, Any]:
        """Buat warehouse/gudang baru (dipakai endpoint POST /warehouses)."""
        try:
            table = WarehouseTable(
                id=uuid4(),
                legal_entity_id=legal_entity_id,
                warehouse_code=warehouse_code,
                name=name,
                location_code=location_code,
                is_active=is_active,
                status="active" if is_active else "inactive",
                is_default=is_default,
                notes=notes,
                created_by=created_by,
            )
            self.session.add(table)
            await self._flush_and_commit()
            await self._log_audit("CREATE_WAREHOUSE", table.id, {"warehouse_code": warehouse_code})
            logger.info("Warehouse %s created", warehouse_code)
            return self._warehouse_to_dict(table)
        except IntegrityError as e:
            await self.session.rollback()
            raise InventoryRepositoryError(
                f"Failed to create warehouse (kode/nama mungkin sudah dipakai): {e}"
            ) from e
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to create warehouse: {e}") from e

    async def update_warehouse(
        self,
        warehouse_id: UUID,
        legal_entity_id: UUID,
        name: str | None = None,
        location_code: str | None = None,
        is_active: bool | None = None,
        is_default: bool | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        """Update warehouse/gudang yang sudah ada. Return None kalau tidak ditemukan."""
        try:
            stmt = select(WarehouseTable).where(
                WarehouseTable.id == warehouse_id,
                WarehouseTable.legal_entity_id == legal_entity_id,
                WarehouseTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            if name is not None:
                table.name = name
            if location_code is not None:
                table.location_code = location_code
            if is_active is not None:
                table.is_active = is_active
                table.status = "active" if is_active else "inactive"
            if is_default is not None:
                table.is_default = is_default
            if notes is not None:
                table.notes = notes
            # FIX: WarehouseTable pakai VersionMixin (version_id_col bawaan
            # SQLAlchemy) - version TIDAK disentuh manual, SQLAlchemy sendiri
            # yang mengecek & menaikkan kolom version saat flush (lihat
            # catatan panjang di InventoryRepository.update_item() untuk
            # detail bug yang sama pernah terjadi di tabel item).
            await self._flush_and_commit()
            await self._log_audit("UPDATE_WAREHOUSE", warehouse_id, {})
            logger.info("Warehouse %s updated", table.warehouse_code)
            return self._warehouse_to_dict(table)
        except IntegrityError as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to update warehouse: {e}") from e
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to update warehouse: {e}") from e

    async def delete_warehouse(self, warehouse_id: UUID, legal_entity_id: UUID) -> bool:
        """Soft-delete (nonaktifkan) warehouse/gudang."""
        try:
            stmt = select(WarehouseTable).where(
                WarehouseTable.id == warehouse_id,
                WarehouseTable.legal_entity_id == legal_entity_id,
                WarehouseTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return False
            table.deleted_at = datetime.utcnow()
            table.is_active = False
            table.status = "inactive"
            # version TIDAK disentuh manual - version_id_col yang urus otomatis.
            await self._flush_and_commit()
            await self._log_audit("DELETE_WAREHOUSE", warehouse_id, {})
            logger.info("Warehouse %s soft deleted", warehouse_id)
            return True
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to delete warehouse: {e}") from e

    # ========================================================================
    # METHODS REQUIRED BY CONTRACT (save_item, find_item_by_id, adjust_stock)
    # ========================================================================

    async def save_item(self, item: InventoryItemAggregate) -> None:
        """
        Alias for add_item if new, else update_item — required by InventoryRepositoryPort.
        """
        existing = await self.get_item_by_id(item.id)
        if existing:
            await self.update_item(item)
        else:
            await self.add_item(item)

    async def find_item_by_id(self, item_id: UUID) -> InventoryItemAggregate | None:
        """
        Alias for get_item_by_id — required by InventoryRepositoryPort.
        """
        return await self.get_item_by_id(item_id)

    async def adjust_stock(
        self,
        item_id: UUID,
        quantity: Decimal,
        warehouse_id: UUID,
        reference_type: str,
        reference_id: UUID,
        user_id: UUID,
        reason: str | None = None,
    ) -> None:
        """
        Adjust stock by creating a movement of type ADJUSTMENT.
        Required by InventoryRepositoryPort.
        """
        item = await self.get_item_by_id(item_id)
        if not item:
            raise ItemNotFoundError(f"Item {item_id} not found")

        # Determine if positive or negative adjustment
        movement_type = StockMovementType.ADJUSTMENT  # we'll use ADJUSTMENT type
        # Create movement with signed quantity
        movement = StockMovement(
            id=uuid4(),
            movement_number=await self.get_next_movement_number("ADJ"),
            item_id=item_id,
            movement_type=movement_type,
            quantity=Quantity(value=abs(quantity), uom=item.unit_of_measure),
            unit_cost=Money(amount=item.average_cost.amount, currency=item.average_cost.currency),
            total_cost=Money(
                amount=abs(quantity) * item.average_cost.amount,
                currency=item.average_cost.currency
            ),
            movement_date=datetime.utcnow().date(),
            reference_type=reference_type,
            reference_id=reference_id,
            warehouse_id=warehouse_id,
            notes=reason or f"Stock adjustment via {reference_type}",
            created_by=user_id,
        )
        # For negative adjustments, we need to handle sign in the movement logic.
        # Since we use ADJUSTMENT type, we'll store the signed quantity in the movement.
        # But our StockMovement domain object uses Quantity (abs) and we need to know sign.
        # We'll store the sign in extra field? Alternatively, we can create two movements
        # but simplest: just record a movement with positive quantity, and if negative,
        # we subtract from stock. But the contract expects adjust_stock with signed quantity.
        # We'll set movement.quantity to abs(quantity) and store sign in notes.
        if quantity < 0:
            movement.notes = f"Negative adjustment: {reason or 'N/A'}"
            # The record_movement will check stock if OUT, but ADJUSTMENT does not check stock.
            # We'll let it proceed.
        await self.record_movement(movement)
        # Optionally, we could also update item's current_stock directly, but record_movement will
        # not update item stock automatically. We need to update item stock.
        # We'll update item stock after movement.
        item.current_stock = Quantity(value=item.current_stock.value + quantity, uom=item.unit_of_measure)
        # version TIDAK di-pre-increment manual - lihat catatan di update_item().
        await self.update_item(item)


# ============================================================================
# ALIAS
# ============================================================================

SQLAlchemyInventoryRepositoryImpl = SQLAlchemyInventoryRepository

__all__ = [
    "DuplicateItemCodeError",
    "FIFOLayerNotFoundError",
    "InsufficientStockError",
    "InventoryRepositoryError",
    "ItemNotFoundError",
    "NegativeStockNotAllowedError",
    "OptimisticLockError",
    "SQLAlchemyInventoryRepository",
    "SQLAlchemyInventoryRepositoryImpl",
]
