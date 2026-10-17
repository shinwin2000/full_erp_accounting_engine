#!/usr/bin/env python3
"""
Module: sqlalchemy_routing_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi RoutingRepositoryPort menggunakan SQLAlchemy ORM.

Mapping ORM <-> domain:
- RoutingTable (header) + RoutingStepTable (detail)
  -> ProductionRoutingEntity (frozen dataclass) + list[RoutingOperation]

Konversi waktu:
- ORM menyimpan setup_time_minutes/run_time_minutes (int menit)
  -> domain menyimpan setup_time_hours/run_time_per_unit_hours (Decimal jam)

Status mapping:
- ORM: 'draft' | 'active' | 'obsolete'
- Domain: RoutingStatus.DRAFT / ACTIVE / OBSOLETE
"""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.manufacturing.production_routing_entity import (
    ProductionRoutingEntity,
    RoutingOperation,
    RoutingStatus,
)
from infrastructure.persistence_orm.manufacturing_routing_table import RoutingTable
from infrastructure.persistence_orm.routing_step_table import RoutingStepTable
from ports.primary.routing_repository_port import RoutingRepositoryPort

logger = logging.getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================

_MINUTES_PER_HOUR = Decimal("60")


def _status_to_str(status: RoutingStatus | str) -> str:
    if isinstance(status, RoutingStatus):
        return status.value
    return str(status)


def _status_from_str(value: str | None) -> RoutingStatus:
    if not value:
        return RoutingStatus.DRAFT
    try:
        return RoutingStatus(value.lower())
    except ValueError:
        return RoutingStatus.DRAFT


def _minutes_to_hours(minutes: int | float | None) -> Decimal:
    if not minutes:
        return Decimal("0")
    return (Decimal(str(minutes)) / _MINUTES_PER_HOUR).quantize(Decimal("0.0001"))


def _hours_to_minutes(hours: Decimal | float | None) -> int:
    if not hours:
        return 0
    return int((Decimal(str(hours)) * _MINUTES_PER_HOUR).to_integral_value())


# ============================================================================
# Repository
# ============================================================================


class SQLAlchemyRoutingRepository(RoutingRepositoryPort):
    """
    Implementasi RoutingRepositoryPort dengan SQLAlchemy.

    Session lazy: kalau belum di-set, ambil dari session factory global.
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        legal_entity_id: UUID | None = None,
    ):
        self._session = session
        self._legal_entity_id = legal_entity_id

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import (
                get_async_session_direct,
            )
            self._session = await get_async_session_direct()
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in routing repository")
        return self._legal_entity_id

    # ------------------------------------------------------------------------
    # ORM -> Domain
    # ------------------------------------------------------------------------

    def _step_to_domain(self, step: RoutingStepTable) -> RoutingOperation:
        return RoutingOperation(
            operation_id=step.id,
            operation_code=step.operation_code,
            operation_name=step.operation_name,
            sequence=step.step_sequence,
            work_center_id=step.work_center_id or uuid4(),  # fallback kalau nullable
            work_center_name=step.operation_name,  # ORM tidak simpan work_center_name
            setup_time_hours=_minutes_to_hours(step.setup_time_minutes),
            run_time_per_unit_hours=_minutes_to_hours(step.run_time_minutes),
            labor_cost_per_hour=Decimal(str(step.labor_cost_rate or 0)),
            machine_cost_per_hour=Decimal(str(step.machine_cost_rate or 0)),
            fixed_cost=Decimal("0"),
            description=step.description or "",
        )

    def _to_domain(self, table: RoutingTable) -> ProductionRoutingEntity:
        steps = sorted(getattr(table, "steps", []) or [], key=lambda s: s.step_sequence)
        return ProductionRoutingEntity(
            routing_id=table.id,
            routing_code=table.routing_code,
            product_id=table.product_id or uuid4(),
            product_code="",  # ORM tidak simpan product_code
            product_name="",  # ORM tidak simpan product_name
            version=1,
            operations=[self._step_to_domain(s) for s in steps],
            status=_status_from_str(table.status),
            effective_date=table.created_at,
            expiry_date=None,
            notes=table.description or "",
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=str(table.created_by) if table.created_by else "system",
            version_counter=table.version or 1,
        )

    # ------------------------------------------------------------------------
    # Domain -> ORM
    # ------------------------------------------------------------------------

    def _apply_header_from_domain(
        self, table: RoutingTable, routing: ProductionRoutingEntity
    ) -> None:
        table.legal_entity_id = self._get_legal_entity_id()
        table.routing_code = routing.routing_code
        table.routing_name = routing.routing_code  # ORM butuh routing_name
        table.product_id = routing.product_id
        table.description = routing.notes or None
        table.status = _status_to_str(routing.status)
        table.is_default = False  # domain tidak punya is_default
        table.updated_by = None

    def _make_step_from_operation(
        self, routing_id: UUID, op: RoutingOperation
    ) -> RoutingStepTable:
        return RoutingStepTable(
            id=op.operation_id if op.operation_id else uuid4(),
            routing_id=routing_id,
            step_sequence=op.sequence,
            operation_code=op.operation_code,
            operation_name=op.operation_name,
            description=op.description or None,
            work_center_id=op.work_center_id,
            machine_id=None,
            setup_time_minutes=_hours_to_minutes(op.setup_time_hours),
            run_time_minutes=_hours_to_minutes(op.run_time_per_unit_hours),
            queue_time_minutes=0,
            wait_time_minutes=0,
            move_time_minutes=0,
            total_time_minutes=(
                _hours_to_minutes(op.setup_time_hours)
                + _hours_to_minutes(op.run_time_per_unit_hours)
            ),
            labor_cost_rate=float(op.labor_cost_per_hour),
            machine_cost_rate=float(op.machine_cost_per_hour),
            overhead_rate=0.0,
        )

    # ------------------------------------------------------------------------
    # Port implementation
    # ------------------------------------------------------------------------

    async def save_routing(
        self,
        routing: ProductionRoutingEntity,
        legal_entity_id: UUID | None = None,
    ) -> None:
        """
        Simpan routing beserta step-nya.

        Args:
            routing: Entity routing.
            legal_entity_id: Opsional — set/override legal_entity_id instance.
                Dibutuhkan karena adapter registry bisa resolve instance baru
                setiap request, jadi set_legal_entity_id() yang dipanggil
                sebelumnya tidak selalu persist.
        """
        # FIX: terima legal_entity_id via argumen
        if legal_entity_id is not None:
            self._legal_entity_id = legal_entity_id
        if self._legal_entity_id is None:
            raise ValueError(
                "legal_entity_id tidak tersedia; pass sebagai argumen "
                "save_routing(routing, legal_entity_id=...)"
            )

        session = await self._get_session()
        existing = await session.get(RoutingTable, routing.routing_id)

        if existing is None:
            table = RoutingTable(id=routing.routing_id)
            self._apply_header_from_domain(table, routing)
            session.add(table)
            for op in routing.operations:
                step = self._make_step_from_operation(routing.routing_id, op)
                session.add(step)
        else:
            self._apply_header_from_domain(existing, routing)
            # Delete step lama, insert ulang (entity immutable)
            old_steps = (
                await session.execute(
                    select(RoutingStepTable).where(
                        RoutingStepTable.routing_id == routing.routing_id
                    )
                )
            ).scalars().all()
            for s in old_steps:
                await session.delete(s)
            for op in routing.operations:
                step = self._make_step_from_operation(routing.routing_id, op)
                session.add(step)

        await session.flush()
        try:
            await session.commit()
        except Exception as e:
            logger.warning(f"commit failed: {e}")
            await session.rollback()
            raise

    async def get_routing_by_id(
        self, routing_id: UUID, legal_entity_id: UUID | None = None
    ) -> ProductionRoutingEntity | None:
        session = await self._get_session()
        stmt = select(RoutingTable).where(RoutingTable.id == routing_id)
        if legal_entity_id is not None:
            stmt = stmt.where(RoutingTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._to_domain(table)

    async def get_routing_by_code(
        self, routing_code: str, legal_entity_id: UUID
    ) -> ProductionRoutingEntity | None:
        session = await self._get_session()
        stmt = select(RoutingTable).where(
            RoutingTable.routing_code == routing_code,
            RoutingTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._to_domain(table)

    async def list_routings(
        self,
        legal_entity_id: UUID,
        product_id: UUID | None = None,
        is_default: bool | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProductionRoutingEntity]:
        session = await self._get_session()
        conditions = [RoutingTable.legal_entity_id == legal_entity_id]
        if product_id is not None:
            conditions.append(RoutingTable.product_id == product_id)
        if is_default is not None:
            conditions.append(RoutingTable.is_default == is_default)
        if status is not None:
            conditions.append(RoutingTable.status == status)
        stmt = (
            select(RoutingTable)
            .where(*conditions)
            .order_by(RoutingTable.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    async def delete_routing(self, routing_id: UUID) -> None:
        session = await self._get_session()
        table = await session.get(RoutingTable, routing_id)
        if table is None:
            return
        await session.delete(table)
        await session.flush()
        try:
            await session.commit()
        except Exception as e:
            logger.warning(f"commit failed: {e}")
            await session.rollback()
            raise

# ============================================================================
# Alias
# ============================================================================

SQLAlchemyRoutingRepositoryImpl = SQLAlchemyRoutingRepository

__all__ = [
    "SQLAlchemyRoutingRepository",
    "SQLAlchemyRoutingRepositoryImpl",
]
