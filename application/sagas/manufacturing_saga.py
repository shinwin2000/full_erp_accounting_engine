# manufacturing_saga.py - Complete implementation

#!/usr/bin/env python3
"""
Module: manufacturing_saga.py
Layer: Application / Sagas
Responsibility: Orchestrator untuk saga aliran biaya manufaktur.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from application.sagas.saga_orchestrator_base import SagaOrchestratorBase
from ports.primary.saga_state_store_port import SagaStateStorePort

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class ManufacturingSagaState:
    """State untuk manufacturing saga."""

    saga_id: UUID
    legal_entity_id: UUID
    period_start: date
    period_end: date
    work_order_ids: list[UUID] = field(default_factory=list)
    user_id: UUID | None = None
    correlation_id: str | None = None
    material_issued: bool = False
    labor_recorded: bool = False
    production_completed: bool = False
    journal_posted: bool = False
    status: str = "INITIATED"
    errors: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.updated_at = datetime.utcnow()


@dataclass(kw_only=True)
class ManufacturingSagaContext:
    """Context untuk manufacturing saga."""

    saga_id: UUID
    legal_entity_id: UUID
    period_start: date
    period_end: date
    work_order_ids: list[UUID]
    user_id: UUID | None = None
    correlation_id: str | None = None
    status: str = "started"
    material_issued: bool = False
    labor_recorded: bool = False
    production_completed: bool = False
    journal_posted: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)


class ManufacturingSagaOrchestrator(SagaOrchestratorBase[ManufacturingSagaState]):
    """
    Orchestrator untuk manufacturing cost flow saga.
    """

    def __init__(
        self,
        state_store: SagaStateStorePort,
        manufacturing_service: Any,
        journal_service: Any,
    ):
        super().__init__(state_store, "manufacturing_cost_flow")
        self._manufacturing = manufacturing_service
        self._journal = journal_service
        self._register_steps()

    def _register_steps(self):
        self.add_step(self._issue_materials, self._reverse_material_issue, "issue_materials")
        self.add_step(self._record_labor, self._reverse_labor, "record_labor")
        self.add_step(self._complete_production, self._reverse_production, "complete_production")
        self.add_step(self._post_journal, self._reverse_journal, "post_journal")

    async def _issue_materials(self, state: ManufacturingSagaState) -> ManufacturingSagaState:
        """Issue materials to work orders."""
        logger.info(f"Issuing materials for {len(state.work_order_ids)} work orders")

        for wo_id in state.work_order_ids:
            if hasattr(self._manufacturing, "issue_materials"):
                await self._manufacturing.issue_materials(wo_id)

        state.material_issued = True
        state.status = "MATERIALS_ISSUED"
        state.updated_at = datetime.utcnow()
        return state

    async def _reverse_material_issue(
        self, state: ManufacturingSagaState
    ) -> ManufacturingSagaState:
        """Reverse material issue."""
        logger.info(f"Reversing material issue for saga {state.saga_id}")

        if state.material_issued:
            for wo_id in state.work_order_ids:
                if hasattr(self._manufacturing, "reverse_material_issue"):
                    await self._manufacturing.reverse_material_issue(wo_id)

        state.material_issued = False
        state.updated_at = datetime.utcnow()
        return state

    async def _record_labor(self, state: ManufacturingSagaState) -> ManufacturingSagaState:
        """Record labor costs."""
        logger.info(f"Recording labor for {len(state.work_order_ids)} work orders")

        for wo_id in state.work_order_ids:
            if hasattr(self._manufacturing, "record_labor"):
                await self._manufacturing.record_labor(wo_id)

        state.labor_recorded = True
        state.status = "LABOR_RECORDED"
        state.updated_at = datetime.utcnow()
        return state

    async def _reverse_labor(self, state: ManufacturingSagaState) -> ManufacturingSagaState:
        """Reverse labor recording."""
        logger.info(f"Reversing labor for saga {state.saga_id}")

        if state.labor_recorded:
            for wo_id in state.work_order_ids:
                if hasattr(self._manufacturing, "reverse_labor"):
                    await self._manufacturing.reverse_labor(wo_id)

        state.labor_recorded = False
        state.updated_at = datetime.utcnow()
        return state

    async def _complete_production(self, state: ManufacturingSagaState) -> ManufacturingSagaState:
        """Complete production and receive finished goods."""
        logger.info(f"Completing production for {len(state.work_order_ids)} work orders")

        for wo_id in state.work_order_ids:
            if hasattr(self._manufacturing, "complete_production"):
                await self._manufacturing.complete_production(wo_id)

        state.production_completed = True
        state.status = "PRODUCTION_COMPLETED"
        state.updated_at = datetime.utcnow()
        return state

    async def _reverse_production(self, state: ManufacturingSagaState) -> ManufacturingSagaState:
        """Reverse production completion."""
        logger.info(f"Reversing production for saga {state.saga_id}")

        if state.production_completed:
            for wo_id in state.work_order_ids:
                if hasattr(self._manufacturing, "reverse_production"):
                    await self._manufacturing.reverse_production(wo_id)

        state.production_completed = False
        state.updated_at = datetime.utcnow()
        return state

    async def _post_journal(self, state: ManufacturingSagaState) -> ManufacturingSagaState:
        """Post journal entries for manufacturing costs."""
        logger.info("Posting journal for manufacturing costs")

        if hasattr(self._journal, "post_manufacturing_journal"):
            await self._journal.post_manufacturing_journal(
                legal_entity_id=state.legal_entity_id,
                period_start=state.period_start,
                period_end=state.period_end,
                work_order_ids=state.work_order_ids,
            )

        state.journal_posted = True
        state.status = "JOURNAL_POSTED"
        state.updated_at = datetime.utcnow()
        return state

    async def _reverse_journal(self, state: ManufacturingSagaState) -> ManufacturingSagaState:
        """Reverse journal entries."""
        logger.info(f"Reversing journal for saga {state.saga_id}")

        if state.journal_posted and hasattr(self._journal, "reverse_manufacturing_journal"):
            await self._journal.reverse_manufacturing_journal(
                legal_entity_id=state.legal_entity_id,
                period_start=state.period_start,
                period_end=state.period_end,
            )

        state.journal_posted = False
        state.updated_at = datetime.utcnow()
        return state

    async def start_manufacturing_cost_flow(
        self,
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
        work_order_ids: list[UUID] | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> ManufacturingSagaContext:
        """Start manufacturing cost flow saga."""
        saga_id = uuid4()

        initial_state = ManufacturingSagaState(
            saga_id=saga_id,
            legal_entity_id=legal_entity_id,
            period_start=period_start,
            period_end=period_end,
            work_order_ids=work_order_ids or [],
            user_id=user_id,
            correlation_id=correlation_id,
        )

        context = await self.start(initial_state)

        return ManufacturingSagaContext(
            saga_id=saga_id,
            legal_entity_id=legal_entity_id,
            period_start=period_start,
            period_end=period_end,
            work_order_ids=work_order_ids or [],
            user_id=user_id,
            correlation_id=correlation_id,
        )

    async def _serialize_data(self, data: ManufacturingSagaState) -> dict[str, Any]:
        return {
            "saga_id": str(data.saga_id),
            "legal_entity_id": str(data.legal_entity_id),
            "period_start": data.period_start.isoformat(),
            "period_end": data.period_end.isoformat(),
            "work_order_ids": [str(wid) for wid in data.work_order_ids],
            "user_id": str(data.user_id) if data.user_id else None,
            "correlation_id": data.correlation_id,
            "material_issued": data.material_issued,
            "labor_recorded": data.labor_recorded,
            "production_completed": data.production_completed,
            "journal_posted": data.journal_posted,
            "status": data.status,
            "errors": data.errors,
            "created_at": data.created_at.isoformat(),
            "updated_at": data.updated_at.isoformat(),
        }

    async def _deserialize_data(self, data_dict: dict[str, Any]) -> ManufacturingSagaState:
        return ManufacturingSagaState(
            saga_id=UUID(data_dict["saga_id"]),
            legal_entity_id=UUID(data_dict["legal_entity_id"]),
            period_start=date.fromisoformat(data_dict["period_start"]),
            period_end=date.fromisoformat(data_dict["period_end"]),
            work_order_ids=[UUID(wid) for wid in data_dict.get("work_order_ids", [])],
            user_id=UUID(data_dict["user_id"]) if data_dict.get("user_id") else None,
            correlation_id=data_dict.get("correlation_id"),
            material_issued=data_dict.get("material_issued", False),
            labor_recorded=data_dict.get("labor_recorded", False),
            production_completed=data_dict.get("production_completed", False),
            journal_posted=data_dict.get("journal_posted", False),
            status=data_dict.get("status", "INITIATED"),
            errors=data_dict.get("errors", []),
            created_at=datetime.fromisoformat(data_dict["created_at"]),
            updated_at=datetime.fromisoformat(data_dict["updated_at"]),
        )


__all__ = ["ManufacturingSagaContext", "ManufacturingSagaOrchestrator", "ManufacturingSagaState"]
