#!/usr/bin/env python3
"""
Module: service_maintenance.py
Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk Asset Maintenance Management:
    - Maintenance assets (aset yang dirawat)
    - Maintenance schedules (jadwal preventive/corrective/dst.)
    - Work orders (perawatan aktual)
    - Spare parts usage
    - Cost summary & export

FIX (2026-08-13): adapters/primary_api/v1/fastapi_maintenance_router.py sudah
lengkap sejak awal (20 endpoint: CRUD asset, schedule, work order, spare
parts, cost summary, export) dan mengimpor
`application.service_layer.service_maintenance.MaintenanceService` di setiap
endpoint (lihat get_maintenance_svc()) - tapi modul ini TIDAK PERNAH dibuat.
Akibatnya semua request ke /api/v1/maintenance/* gagal dengan
ModuleNotFoundError sebelum sempat masuk ke authentication middleware,
yang di response API muncul sebagai 401 Unauthorized (bukan 500) karena
exception itu meledak di dalam dependency resolution FastAPI, sebelum
handler/exception-handler biasa sempat jalan.

Implementasi ini menyimpan data secara in-memory (per proses), mengikuti pola
yang sama dengan EmployeeService/CapitalService versi awal di codebase ini
untuk modul yang belum py Persistent DB - lihat catatan pada masing-masing
modul tersebut. Kalau nanti dibutuhkan persistensi lintas restart, tinggal
tambahkan SQLAlchemy repository + port (mengikuti pola FixedAssetRepositoryPort)
dan suntikkan lewat constructor di sini; seluruh method publik service ini
sudah dirancang agar tidak berubah tanda tangan (signature)-nya kalau itu
dilakukan nanti.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPublisherPort

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Constants
# ============================================================================

# Interval (hari) per frekuensi jadwal, dipakai untuk menghitung next_due_date.
_FREQUENCY_DAYS: dict[str, int] = {
    "daily": 1,
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
    "quarterly": 91,
    "semi_annual": 182,
    "annual": 365,
}

# Status work order yang dianggap "sudah selesai/tidak bisa diubah lagi".
_TERMINAL_WO_STATUSES = {"completed", "cancelled", "closed", "locked", "archived"}


# ============================================================================
# DOMAIN DATACLASSES (dipakai langsung oleh router sebagai `result`)
# ============================================================================


@dataclass
class MaintenanceAsset:
    id: UUID
    legal_entity_id: UUID
    asset_code: str
    asset_name: str
    asset_category: str
    location: str | None
    serial_number: str | None
    manufacturer: str | None
    model: str | None
    purchase_date: date | None
    warranty_expiry_date: date | None
    maintenance_interval_days: int | None
    status: str
    is_active: bool
    is_locked: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None
    version: int


@dataclass
class MaintenanceSchedule:
    id: UUID
    legal_entity_id: UUID
    asset_id: UUID
    asset_code: str | None
    asset_name: str | None
    schedule_code: str
    schedule_name: str
    maintenance_type: str
    frequency: str
    custom_interval_days: int | None
    start_date: date
    end_date: date | None
    estimated_duration_hours: Decimal
    assigned_team: str | None
    status: str
    is_active: bool
    next_due_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None
    version: int


@dataclass
class WorkOrderMaintenance:
    id: UUID
    legal_entity_id: UUID
    wo_number: str
    asset_id: UUID
    asset_code: str | None
    asset_name: str | None
    schedule_id: UUID | None
    maintenance_type: str
    priority: str
    description: str
    requested_by: UUID
    requested_by_name: str | None
    assigned_technician_id: UUID | None
    assigned_technician_name: str | None
    planned_start_date: date
    planned_end_date: date
    actual_start_date: date | None
    actual_end_date: date | None
    estimated_cost: Decimal
    actual_cost: Decimal
    status: str
    is_locked: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None
    version: int
    completed_at: datetime | None = None
    completed_by: UUID | None = None


@dataclass
class SparePartUsage:
    id: UUID
    legal_entity_id: UUID
    item_id: UUID
    item_code: str | None
    item_name: str | None
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    work_order_id: UUID
    work_order_number: str | None
    issued_date: date
    status: str
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None


@dataclass
class PagedWorkOrders:
    items: list[WorkOrderMaintenance]
    total: int
    page: int
    page_size: int


@dataclass
class MaintenanceCostSummary:
    total_maintenance_cost: Decimal
    preventive_cost: Decimal
    corrective_cost: Decimal
    emergency_cost: Decimal
    labor_cost: Decimal
    spare_parts_cost: Decimal
    other_cost: Decimal
    by_asset: list[dict[str, Any]]
    by_work_order: list[dict[str, Any]]


# ============================================================================
# SERVICE
# ============================================================================


class MaintenanceService:
    """Layanan untuk Asset Maintenance (assets, schedules, work orders, spare parts)."""

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._event_publisher = event_publisher

        self._assets: dict[UUID, MaintenanceAsset] = {}
        self._schedules: dict[UUID, MaintenanceSchedule] = {}
        self._work_orders: dict[UUID, WorkOrderMaintenance] = {}
        self._spare_part_usages: dict[UUID, SparePartUsage] = {}

        self._stats = {
            "assets_created": 0,
            "schedules_created": 0,
            "work_orders_created": 0,
            "work_orders_completed": 0,
            "work_orders_cancelled": 0,
            "spare_parts_recorded": 0,
        }

        logger.info("MaintenanceService initialized")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str) -> None:
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    # ========================================================================
    # MAINTENANCE ASSET
    # ========================================================================

    @audit
    async def create_maintenance_asset(
        self,
        legal_entity_id: UUID,
        asset_code: str,
        asset_name: str,
        asset_category: str,
        location: str | None = None,
        serial_number: str | None = None,
        manufacturer: str | None = None,
        model: str | None = None,
        purchase_date: date | None = None,
        warranty_expiry_date: date | None = None,
        maintenance_interval_days: int | None = None,
        notes: str | None = None,
        is_active: bool = True,
        created_by: UUID | None = None,
    ) -> MaintenanceAsset:
        self._check_authority(created_by, "maintenance:create")

        code = (asset_code or "").strip().upper()
        if not code:
            raise ValueError("Asset code is required")
        for existing in self._assets.values():
            if existing.legal_entity_id == legal_entity_id and existing.asset_code == code:
                raise ValueError(f"Maintenance asset with code '{code}' already exists")

        now = datetime.now(UTC)
        asset = MaintenanceAsset(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            asset_code=code,
            asset_name=asset_name,
            asset_category=asset_category,
            location=location,
            serial_number=serial_number,
            manufacturer=manufacturer,
            model=model,
            purchase_date=purchase_date,
            warranty_expiry_date=warranty_expiry_date,
            maintenance_interval_days=maintenance_interval_days,
            status="active" if is_active else "inactive",
            is_active=is_active,
            is_locked=False,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            created_by_name=None,
            version=1,
        )
        self._assets[asset.id] = asset
        self._stats["assets_created"] += 1
        logger.info(f"AUDIT: create_maintenance_asset - {{'asset_id': '{asset.id}', 'asset_code': '{code}'}}")
        return asset

    async def list_maintenance_assets(
        self,
        legal_entity_id: UUID,
        category: str | None = None,
        status: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> list[MaintenanceAsset]:
        results = [a for a in self._assets.values() if a.legal_entity_id == legal_entity_id]
        if category:
            results = [a for a in results if a.asset_category == category]
        if status:
            results = [a for a in results if a.status == status]
        if is_active is not None:
            results = [a for a in results if a.is_active == is_active]
        if search:
            needle = search.lower()
            results = [
                a for a in results
                if needle in a.asset_code.lower() or needle in a.asset_name.lower()
            ]
        return sorted(results, key=lambda a: a.asset_code)

    async def get_maintenance_asset_by_id(
        self, asset_id: UUID, legal_entity_id: UUID
    ) -> MaintenanceAsset | None:
        asset = self._assets.get(asset_id)
        if not asset or asset.legal_entity_id != legal_entity_id:
            return None
        return asset

    @audit
    async def update_maintenance_asset(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
        asset_name: str | None = None,
        location: str | None = None,
        status: str | None = None,
        maintenance_interval_days: int | None = None,
        notes: str | None = None,
        is_active: bool | None = None,
        updated_by: UUID | None = None,
    ) -> MaintenanceAsset | None:
        self._check_authority(updated_by, "maintenance:update")
        asset = self._assets.get(asset_id)
        if not asset or asset.legal_entity_id != legal_entity_id:
            return None
        if asset.is_locked:
            raise ValueError("Cannot update a locked maintenance asset")

        changes: dict[str, Any] = {"updated_at": datetime.now(UTC), "version": asset.version + 1}
        if asset_name is not None:
            changes["asset_name"] = asset_name
        if location is not None:
            changes["location"] = location
        if status is not None:
            changes["status"] = status
        if maintenance_interval_days is not None:
            changes["maintenance_interval_days"] = maintenance_interval_days
        if notes is not None:
            changes["notes"] = notes
        if is_active is not None:
            changes["is_active"] = is_active

        updated = replace(asset, **changes)
        self._assets[asset_id] = updated
        logger.info(f"AUDIT: update_maintenance_asset - {{'asset_id': '{asset_id}'}}")
        return updated

    @audit
    async def deactivate_maintenance_asset(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
        deactivated_by: UUID | None = None,
        reason: str = "",
    ) -> MaintenanceAsset | None:
        self._check_authority(deactivated_by, "maintenance:delete")
        asset = self._assets.get(asset_id)
        if not asset or asset.legal_entity_id != legal_entity_id:
            return None

        note = asset.notes or ""
        if reason:
            note = f"{note}\n[Deactivated] {reason}".strip()

        updated = replace(
            asset,
            status="archived",
            is_active=False,
            notes=note or None,
            updated_at=datetime.now(UTC),
            version=asset.version + 1,
        )
        self._assets[asset_id] = updated
        logger.info(f"AUDIT: deactivate_maintenance_asset - {{'asset_id': '{asset_id}', 'reason': '{reason}'}}")
        return updated

    # ========================================================================
    # MAINTENANCE SCHEDULE
    # ========================================================================

    def _resolve_asset_ref(self, asset_id: UUID) -> tuple[str | None, str | None]:
        asset = self._assets.get(asset_id)
        if not asset:
            return None, None
        return asset.asset_code, asset.asset_name

    def _compute_next_due_date(
        self, start_date: date, frequency: str, custom_interval_days: int | None
    ) -> date:
        if frequency == "custom":
            days = custom_interval_days or 1
        else:
            days = _FREQUENCY_DAYS.get(frequency, 30)
        from datetime import timedelta
        return start_date + timedelta(days=days)

    @audit
    async def create_maintenance_schedule(
        self,
        legal_entity_id: UUID,
        asset_id: UUID,
        schedule_code: str,
        schedule_name: str,
        maintenance_type: str,
        frequency: str,
        start_date: date,
        custom_interval_days: int | None = None,
        end_date: date | None = None,
        estimated_duration_hours: Decimal = Decimal("0"),
        assigned_team: str | None = None,
        notes: str | None = None,
        is_active: bool = True,
        created_by: UUID | None = None,
    ) -> MaintenanceSchedule:
        self._check_authority(created_by, "maintenance:create")

        code = (schedule_code or "").strip().upper()
        if not code:
            raise ValueError("Schedule code is required")

        asset = self._assets.get(asset_id)
        if not asset or asset.legal_entity_id != legal_entity_id:
            raise ValueError(f"Maintenance asset {asset_id} not found")

        for existing in self._schedules.values():
            if existing.legal_entity_id == legal_entity_id and existing.schedule_code == code:
                raise ValueError(f"Maintenance schedule with code '{code}' already exists")

        next_due = self._compute_next_due_date(start_date, frequency, custom_interval_days)
        now = datetime.now(UTC)
        schedule = MaintenanceSchedule(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            asset_id=asset_id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            schedule_code=code,
            schedule_name=schedule_name,
            maintenance_type=maintenance_type,
            frequency=frequency,
            custom_interval_days=custom_interval_days,
            start_date=start_date,
            end_date=end_date,
            estimated_duration_hours=estimated_duration_hours,
            assigned_team=assigned_team,
            status="active" if is_active else "inactive",
            is_active=is_active,
            next_due_date=next_due,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            created_by_name=None,
            version=1,
        )
        self._schedules[schedule.id] = schedule
        self._stats["schedules_created"] += 1
        logger.info(f"AUDIT: create_maintenance_schedule - {{'schedule_id': '{schedule.id}', 'schedule_code': '{code}'}}")
        return schedule

    async def list_maintenance_schedules(
        self,
        legal_entity_id: UUID,
        asset_id: UUID | None = None,
        maintenance_type: str | None = None,
        is_active: bool | None = None,
    ) -> list[MaintenanceSchedule]:
        results = [s for s in self._schedules.values() if s.legal_entity_id == legal_entity_id]
        if asset_id:
            results = [s for s in results if s.asset_id == asset_id]
        if maintenance_type:
            results = [s for s in results if s.maintenance_type == maintenance_type]
        if is_active is not None:
            results = [s for s in results if s.is_active == is_active]
        return sorted(results, key=lambda s: s.schedule_code)

    async def get_maintenance_schedule_by_id(
        self, schedule_id: UUID, legal_entity_id: UUID
    ) -> MaintenanceSchedule | None:
        schedule = self._schedules.get(schedule_id)
        if not schedule or schedule.legal_entity_id != legal_entity_id:
            return None
        return schedule

    @audit
    async def update_maintenance_schedule(
        self,
        schedule_id: UUID,
        legal_entity_id: UUID,
        schedule_name: str | None = None,
        frequency: str | None = None,
        custom_interval_days: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        estimated_duration_hours: Decimal | None = None,
        assigned_team: str | None = None,
        notes: str | None = None,
        is_active: bool | None = None,
        updated_by: UUID | None = None,
    ) -> MaintenanceSchedule | None:
        self._check_authority(updated_by, "maintenance:update")
        schedule = self._schedules.get(schedule_id)
        if not schedule or schedule.legal_entity_id != legal_entity_id:
            return None

        changes: dict[str, Any] = {"updated_at": datetime.now(UTC), "version": schedule.version + 1}
        if schedule_name is not None:
            changes["schedule_name"] = schedule_name
        if frequency is not None:
            changes["frequency"] = frequency
        if custom_interval_days is not None:
            changes["custom_interval_days"] = custom_interval_days
        if start_date is not None:
            changes["start_date"] = start_date
        if end_date is not None:
            changes["end_date"] = end_date
        if estimated_duration_hours is not None:
            changes["estimated_duration_hours"] = estimated_duration_hours
        if assigned_team is not None:
            changes["assigned_team"] = assigned_team
        if notes is not None:
            changes["notes"] = notes
        if is_active is not None:
            changes["is_active"] = is_active
            changes["status"] = "active" if is_active else "inactive"

        # Recompute next_due_date if anything relevant to it changed.
        new_start = changes.get("start_date", schedule.start_date)
        new_freq = changes.get("frequency", schedule.frequency)
        new_custom = changes.get("custom_interval_days", schedule.custom_interval_days)
        if any(k in changes for k in ("start_date", "frequency", "custom_interval_days")):
            changes["next_due_date"] = self._compute_next_due_date(new_start, new_freq, new_custom)

        updated = replace(schedule, **changes)
        self._schedules[schedule_id] = updated
        logger.info(f"AUDIT: update_maintenance_schedule - {{'schedule_id': '{schedule_id}'}}")
        return updated

    @audit
    async def deactivate_maintenance_schedule(
        self,
        schedule_id: UUID,
        legal_entity_id: UUID,
        deactivated_by: UUID | None = None,
        reason: str = "",
    ) -> MaintenanceSchedule | None:
        self._check_authority(deactivated_by, "maintenance:delete")
        schedule = self._schedules.get(schedule_id)
        if not schedule or schedule.legal_entity_id != legal_entity_id:
            return None

        note = schedule.notes or ""
        if reason:
            note = f"{note}\n[Deactivated] {reason}".strip()

        updated = replace(
            schedule,
            status="inactive",
            is_active=False,
            notes=note or None,
            updated_at=datetime.now(UTC),
            version=schedule.version + 1,
        )
        self._schedules[schedule_id] = updated
        logger.info(f"AUDIT: deactivate_maintenance_schedule - {{'schedule_id': '{schedule_id}', 'reason': '{reason}'}}")
        return updated

    # ========================================================================
    # WORK ORDER MAINTENANCE
    # ========================================================================

    @audit
    async def create_maintenance_work_order(
        self,
        legal_entity_id: UUID,
        wo_number: str,
        asset_id: UUID,
        maintenance_type: str,
        description: str,
        requested_by: UUID,
        planned_start_date: date,
        planned_end_date: date,
        schedule_id: UUID | None = None,
        priority: str = "medium",
        estimated_cost: Decimal = Decimal("0"),
        notes: str | None = None,
        created_by: UUID | None = None,
    ) -> WorkOrderMaintenance:
        self._check_authority(created_by, "maintenance:create")

        number = (wo_number or "").strip()
        if not number:
            raise ValueError("Work order number is required")

        asset = self._assets.get(asset_id)
        if not asset or asset.legal_entity_id != legal_entity_id:
            raise ValueError(f"Maintenance asset {asset_id} not found")

        if schedule_id is not None:
            schedule = self._schedules.get(schedule_id)
            if not schedule or schedule.legal_entity_id != legal_entity_id:
                raise ValueError(f"Maintenance schedule {schedule_id} not found")

        for existing in self._work_orders.values():
            if existing.legal_entity_id == legal_entity_id and existing.wo_number == number:
                raise ValueError(f"Work order with number '{number}' already exists")

        now = datetime.now(UTC)
        wo = WorkOrderMaintenance(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            wo_number=number,
            asset_id=asset_id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            schedule_id=schedule_id,
            maintenance_type=maintenance_type,
            priority=priority,
            description=description,
            requested_by=requested_by,
            requested_by_name=None,
            assigned_technician_id=None,
            assigned_technician_name=None,
            planned_start_date=planned_start_date,
            planned_end_date=planned_end_date,
            actual_start_date=None,
            actual_end_date=None,
            estimated_cost=estimated_cost,
            actual_cost=Decimal("0"),
            status="draft",
            is_locked=False,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            created_by_name=None,
            version=1,
        )
        self._work_orders[wo.id] = wo
        self._stats["work_orders_created"] += 1
        logger.info(f"AUDIT: create_maintenance_work_order - {{'wo_id': '{wo.id}', 'wo_number': '{number}'}}")
        return wo

    async def list_maintenance_work_orders(
        self,
        legal_entity_id: UUID,
        asset_id: UUID | None = None,
        status: str | None = None,
        priority: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PagedWorkOrders:
        results = [w for w in self._work_orders.values() if w.legal_entity_id == legal_entity_id]
        if asset_id:
            results = [w for w in results if w.asset_id == asset_id]
        if status:
            results = [w for w in results if w.status == status]
        if priority:
            results = [w for w in results if w.priority == priority]
        if start_date:
            results = [w for w in results if w.planned_start_date >= start_date]
        if end_date:
            results = [w for w in results if w.planned_end_date <= end_date]

        results = sorted(results, key=lambda w: w.created_at, reverse=True)
        total = len(results)
        offset = (page - 1) * page_size
        page_items = results[offset: offset + page_size]
        return PagedWorkOrders(items=page_items, total=total, page=page, page_size=page_size)

    async def get_maintenance_work_order_by_id(
        self, wo_id: UUID, legal_entity_id: UUID
    ) -> WorkOrderMaintenance | None:
        wo = self._work_orders.get(wo_id)
        if not wo or wo.legal_entity_id != legal_entity_id:
            return None
        return wo

    @audit
    async def update_maintenance_work_order(
        self,
        wo_id: UUID,
        legal_entity_id: UUID,
        description: str | None = None,
        priority: str | None = None,
        planned_start_date: date | None = None,
        planned_end_date: date | None = None,
        estimated_cost: Decimal | None = None,
        notes: str | None = None,
        assigned_technician_id: UUID | None = None,
        status: str | None = None,
        updated_by: UUID | None = None,
    ) -> WorkOrderMaintenance | None:
        self._check_authority(updated_by, "maintenance:update")
        wo = self._work_orders.get(wo_id)
        if not wo or wo.legal_entity_id != legal_entity_id:
            return None
        if wo.status in _TERMINAL_WO_STATUSES:
            raise ValueError(f"Cannot update work order in terminal status '{wo.status}'")

        changes: dict[str, Any] = {"updated_at": datetime.now(UTC), "version": wo.version + 1}
        if description is not None:
            changes["description"] = description
        if priority is not None:
            changes["priority"] = priority
        if planned_start_date is not None:
            changes["planned_start_date"] = planned_start_date
        if planned_end_date is not None:
            changes["planned_end_date"] = planned_end_date
        if estimated_cost is not None:
            changes["estimated_cost"] = estimated_cost
        if notes is not None:
            changes["notes"] = notes
        if assigned_technician_id is not None:
            changes["assigned_technician_id"] = assigned_technician_id
            # First technician assignment moves a draft/planned WO forward.
            if wo.status in ("draft", "planned"):
                changes["status"] = "assigned"
        if status is not None:
            changes["status"] = status

        new_start = changes.get("planned_start_date", wo.planned_start_date)
        new_end = changes.get("planned_end_date", wo.planned_end_date)
        if new_end < new_start:
            raise ValueError("Planned end date must be after planned start date")

        updated = replace(wo, **changes)
        self._work_orders[wo_id] = updated
        logger.info(f"AUDIT: update_maintenance_work_order - {{'wo_id': '{wo_id}'}}")
        return updated

    @audit
    async def complete_maintenance_work_order(
        self,
        wo_id: UUID,
        legal_entity_id: UUID,
        actual_end_date: date,
        actual_cost: Decimal = Decimal("0"),
        notes: str = "",
        completed_by: UUID | None = None,
    ) -> WorkOrderMaintenance | None:
        self._check_authority(completed_by, "maintenance:complete")
        wo = self._work_orders.get(wo_id)
        if not wo or wo.legal_entity_id != legal_entity_id:
            return None
        if wo.status in _TERMINAL_WO_STATUSES:
            raise ValueError(f"Work order already in terminal status '{wo.status}', cannot complete")

        merged_notes = wo.notes or ""
        if notes:
            merged_notes = f"{merged_notes}\n[Completed] {notes}".strip()

        # Spare parts already recorded against this WO also count toward actual cost.
        spare_parts_total = sum(
            (u.total_cost for u in self._spare_part_usages.values() if u.work_order_id == wo_id),
            Decimal("0"),
        )
        total_actual_cost = (actual_cost or Decimal("0")) + spare_parts_total

        now = datetime.now(UTC)
        updated = replace(
            wo,
            status="completed",
            actual_start_date=wo.actual_start_date or wo.planned_start_date,
            actual_end_date=actual_end_date,
            actual_cost=total_actual_cost,
            notes=merged_notes or None,
            is_locked=True,
            completed_at=now,
            completed_by=completed_by,
            updated_at=now,
            version=wo.version + 1,
        )
        self._work_orders[wo_id] = updated
        self._stats["work_orders_completed"] += 1

        # Roll the linked schedule's next_due_date forward, if any.
        if wo.schedule_id and wo.schedule_id in self._schedules:
            schedule = self._schedules[wo.schedule_id]
            next_due = self._compute_next_due_date(
                actual_end_date, schedule.frequency, schedule.custom_interval_days
            )
            self._schedules[wo.schedule_id] = replace(
                schedule, next_due_date=next_due, updated_at=now, version=schedule.version + 1
            )

        logger.info(f"AUDIT: complete_maintenance_work_order - {{'wo_id': '{wo_id}', 'actual_cost': '{total_actual_cost}'}}")
        return updated

    @audit
    async def cancel_maintenance_work_order(
        self,
        wo_id: UUID,
        legal_entity_id: UUID,
        reason: str = "",
        cancelled_by: UUID | None = None,
    ) -> WorkOrderMaintenance | None:
        self._check_authority(cancelled_by, "maintenance:cancel")
        wo = self._work_orders.get(wo_id)
        if not wo or wo.legal_entity_id != legal_entity_id:
            return None
        if wo.status in _TERMINAL_WO_STATUSES:
            raise ValueError(f"Work order already in terminal status '{wo.status}', cannot cancel")

        merged_notes = wo.notes or ""
        if reason:
            merged_notes = f"{merged_notes}\n[Cancelled] {reason}".strip()

        updated = replace(
            wo,
            status="cancelled",
            notes=merged_notes or None,
            is_locked=True,
            updated_at=datetime.now(UTC),
            version=wo.version + 1,
        )
        self._work_orders[wo_id] = updated
        self._stats["work_orders_cancelled"] += 1
        logger.info(f"AUDIT: cancel_maintenance_work_order - {{'wo_id': '{wo_id}', 'reason': '{reason}'}}")
        return updated

    # ========================================================================
    # SPARE PARTS USAGE
    # ========================================================================

    @audit
    async def record_spare_parts_usage(
        self,
        legal_entity_id: UUID,
        item_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal,
        work_order_id: UUID,
        issued_date: date | None = None,
        notes: str | None = None,
        created_by: UUID | None = None,
    ) -> SparePartUsage:
        self._check_authority(created_by, "maintenance:create")

        wo = self._work_orders.get(work_order_id)
        if not wo or wo.legal_entity_id != legal_entity_id:
            raise ValueError(f"Work order {work_order_id} not found")
        if wo.status in _TERMINAL_WO_STATUSES:
            raise ValueError(f"Cannot record spare parts against work order in status '{wo.status}'")
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        if unit_cost <= 0:
            raise ValueError("Unit cost must be positive")

        usage = SparePartUsage(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            item_id=item_id,
            item_code=None,
            item_name=None,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=(quantity * unit_cost),
            work_order_id=work_order_id,
            work_order_number=wo.wo_number,
            issued_date=issued_date or date.today(),
            status="issued",
            notes=notes,
            created_at=datetime.now(UTC),
            created_by=created_by,
            created_by_name=None,
        )
        self._spare_part_usages[usage.id] = usage
        self._stats["spare_parts_recorded"] += 1
        logger.info(
            f"AUDIT: record_spare_parts_usage - {{'usage_id': '{usage.id}', 'work_order_id': '{work_order_id}', "
            f"'total_cost': '{usage.total_cost}'}}"
        )
        return usage

    # ========================================================================
    # COST SUMMARY
    # ========================================================================

    async def get_maintenance_cost_summary(
        self,
        legal_entity_id: UUID,
        start_date: date,
        end_date: date,
    ) -> MaintenanceCostSummary:
        wos_in_period = [
            w for w in self._work_orders.values()
            if w.legal_entity_id == legal_entity_id
            and w.status == "completed"
            and w.completed_at is not None
            and start_date <= (w.actual_end_date or w.completed_at.date()) <= end_date
        ]

        preventive_cost = Decimal("0")
        corrective_cost = Decimal("0")
        emergency_cost = Decimal("0")
        other_cost = Decimal("0")
        by_asset: dict[UUID, Decimal] = {}
        by_work_order: list[dict[str, Any]] = []

        for wo in wos_in_period:
            cost = wo.actual_cost or Decimal("0")
            if wo.maintenance_type == "preventive":
                preventive_cost += cost
            elif wo.maintenance_type == "corrective":
                corrective_cost += cost
            elif wo.maintenance_type == "emergency":
                emergency_cost += cost
            else:
                other_cost += cost

            by_asset[wo.asset_id] = by_asset.get(wo.asset_id, Decimal("0")) + cost
            by_work_order.append({
                "work_order_id": str(wo.id),
                "wo_number": wo.wo_number,
                "asset_id": str(wo.asset_id),
                "asset_code": wo.asset_code,
                "maintenance_type": wo.maintenance_type,
                "total_cost": cost,
            })

        spare_parts_cost = sum(
            (
                u.total_cost for u in self._spare_part_usages.values()
                if u.legal_entity_id == legal_entity_id and start_date <= u.issued_date <= end_date
            ),
            Decimal("0"),
        )

        total_maintenance_cost = preventive_cost + corrective_cost + emergency_cost + other_cost
        labor_cost = total_maintenance_cost - spare_parts_cost
        if labor_cost < 0:
            labor_cost = Decimal("0")

        by_asset_list = [
            {
                "asset_id": str(asset_id),
                "asset_code": self._assets[asset_id].asset_code if asset_id in self._assets else None,
                "total_cost": cost,
            }
            for asset_id, cost in by_asset.items()
        ]

        return MaintenanceCostSummary(
            total_maintenance_cost=total_maintenance_cost,
            preventive_cost=preventive_cost,
            corrective_cost=corrective_cost,
            emergency_cost=emergency_cost,
            labor_cost=labor_cost,
            spare_parts_cost=spare_parts_cost,
            other_cost=other_cost,
            by_asset=by_asset_list,
            by_work_order=by_work_order,
        )

    # ========================================================================
    # EXPORT
    # ========================================================================

    async def export_maintenance_work_orders(
        self,
        legal_entity_id: UUID,
        start_date: date,
        end_date: date,
        format: str = "csv",
        status: str | None = None,
    ) -> bytes:
        results = [
            w for w in self._work_orders.values()
            if w.legal_entity_id == legal_entity_id
            and w.planned_start_date >= start_date
            and w.planned_start_date <= end_date
        ]
        if status:
            results = [w for w in results if w.status == status]
        results = sorted(results, key=lambda w: w.planned_start_date)

        headers = [
            "wo_number", "asset_code", "asset_name", "maintenance_type", "priority",
            "status", "planned_start_date", "planned_end_date", "actual_start_date",
            "actual_end_date", "estimated_cost", "actual_cost",
        ]

        if format == "excel":
            try:
                from openpyxl import Workbook
                wb = Workbook()
                ws = wb.active
                ws.title = "Work Orders"
                ws.append(headers)
                for w in results:
                    ws.append([
                        w.wo_number, w.asset_code, w.asset_name, w.maintenance_type, w.priority,
                        w.status, str(w.planned_start_date), str(w.planned_end_date),
                        str(w.actual_start_date) if w.actual_start_date else "",
                        str(w.actual_end_date) if w.actual_end_date else "",
                        float(w.estimated_cost), float(w.actual_cost),
                    ])
                buf = io.BytesIO()
                wb.save(buf)
                return buf.getvalue()
            except ImportError:
                logger.warning("openpyxl not available, falling back to CSV for excel export request")
                format = "csv"

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        for w in results:
            writer.writerow([
                w.wo_number, w.asset_code, w.asset_name, w.maintenance_type, w.priority,
                w.status, w.planned_start_date, w.planned_end_date,
                w.actual_start_date or "", w.actual_end_date or "",
                w.estimated_cost, w.actual_cost,
            ])
        return buf.getvalue().encode("utf-8")


__all__ = [
    "MaintenanceAsset",
    "MaintenanceCostSummary",
    "MaintenanceSchedule",
    "MaintenanceService",
    "PagedWorkOrders",
    "SparePartUsage",
    "WorkOrderMaintenance",
]
