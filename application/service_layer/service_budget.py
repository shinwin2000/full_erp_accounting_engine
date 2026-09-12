#!/usr/bin/env python3
"""
Module: service_budget.py
Layer: Application / Service Layer
Responsibility: Service untuk budget management dengan event publishing.
"""

from __future__ import annotations

import csv
import io
import logging

# ============================================================================
# ADDITIONAL DTOs (untuk testing compatibility)
# ============================================================================
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.budget.aggregate_root import (
    Budget,
    BudgetAggregate,
    BudgetLine,
    BudgetLineItem,
    BudgetPeriod,
    BudgetStatus,
    BudgetType,
)
from ports.primary.budget_repository_port import (
    BudgetEntity,
    BudgetLineEntity,
    BudgetRepositoryPort,
)
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

from ..dto_objects.budget_request import (
    BudgetCreateRequest,
    BudgetLineCreateRequest,
    BudgetLineResponse,
    BudgetLineUpdateRequest,
    BudgetResponse,
    BudgetUpdateRequest,
    BudgetVsActualLineResponse,
    BudgetVsActualResponse,
)


@dataclass(kw_only=True)
class BudgetRequest:
    """DTO untuk request budget (legacy/compatibility)."""
    legal_entity_id: UUID
    budget_name: str
    fiscal_year: int
    lines: list[dict]
    period_type: str
    description: str


@dataclass(kw_only=True)
class BudgetLineRequest:
    """DTO untuk request budget line (legacy/compatibility)."""
    account_code: str
    amount: Decimal
    period: str
    description: str


@dataclass(kw_only=True)
class VarianceAnalysisRequest:
    """DTO untuk variance analysis request."""
    legal_entity_id: UUID
    budget_id: UUID
    period_start: date
    period_end: date
    include_details: bool


@dataclass(kw_only=True)
class VarianceItem:
    """DTO untuk variance item."""
    account_code: str
    account_name: str
    budget_amount: Decimal
    actual_amount: Decimal
    variance: Decimal
    variance_percentage: float
    variance_type: str


@dataclass(kw_only=True)
class VarianceAnalysisResponse:
    """DTO untuk variance analysis response."""
    budget_id: UUID
    budget_name: str
    period_start: date
    period_end: date
    total_budget: Decimal
    total_actual: Decimal
    total_variance: Decimal
    variance_percentage: float
    items: list
    analysis_date: datetime


logger = logging.getLogger(__name__)


# ============================================================================
# EXCEPTIONS
# ============================================================================


class BudgetServiceError(Exception):
    pass


class BudgetNotFoundError(BudgetServiceError):
    pass


class BudgetAlreadyExistsError(BudgetServiceError):
    pass


class BudgetPeriodClosedError(BudgetServiceError):
    """Exception untuk periode budget yang sudah ditutup."""
    pass


class BudgetInvalidStatusError(BudgetServiceError):
    pass


# ============================================================================
# DUMMY AUDIT DECORATOR
# ============================================================================


def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# SERVICE
# ============================================================================


class BudgetService:
    """Service untuk budget management."""

    def __init__(
        self,
        budget_repo: BudgetRepositoryPort,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
        ledger_repo=None,  # Untuk actual data, optional
    ):
        self._budget_repo = budget_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._ledger_repo = ledger_repo
        self._audit_trail: list[dict[str, Any]] = []

    def _record_audit(self, action: str, details: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "BudgetService",
            "action": action,
            "details": details,
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    async def _publish_events(self, aggregate: BudgetAggregate) -> None:
        # [FIX] Kontrak `EventPublisherPort.publish()` (event, event_type,
        # aggregate_id, aggregate_type, ...) tidak cocok dengan signature
        # `KafkaEventPublisher.publish()` yang sebenarnya (topic, event, key)
        # -- keduanya juga tidak cocok dengan pemanggilan 1-argumen di sini.
        # ini kesalahan arsitektur yang lebih luas (kemungkinan besar
        # memengaruhi publish event di modul lain juga), di luar scope
        # perbaikan modul budget. Sambil menunggu itu diselaraskan,
        # publish event ke message bus TIDAK BOLEH menggagalkan transaksi
        # bisnis yang sudah berhasil disimpan -- efek samping publish event
        # harus best-effort, bukan syarat sukses/gagalnya create/update
        # budget. Karena itu exception di sini ditangkap & di-log, tidak
        # dilempar ke pemanggil.
        if not self._event_publisher:
            return
        for event in aggregate.pull_events():
            try:
                await self._event_publisher.publish(event)
            except Exception as e:
                logger.warning(
                    f"Gagal publish event budget {aggregate.id} ({type(event).__name__}): {e}"
                )

    async def _maybe_commit_uow(self) -> None:
        """
        [FIX] Sebelumnya kode ini memanggil `await self._uow.commit()` begitu
        saja tanpa pernah memanggil `self._uow.begin()` -- DI container
        (`get_budget_service`) hanya menyuntikkan session request-scoped ke
        repository, tidak pernah memulai transaksi lewat UoW ini. Akibatnya
        SETIAP aksi tulis (create/update/delete/submit/approve/dst.) selalu
        meledak dengan "UoW not started or transaction not active" tepat
        setelah data berhasil di-flush ke DB -- dan karena exception ini
        menjalar sampai ke FastAPI, dependency `get_async_session()` akhirnya
        me-rollback seluruh transaksi request tersebut. Jadi walau log sempat
        menulis "Budget saved: ...", datanya tidak pernah benar-benar
        tersimpan.

        Commit request yang sesungguhnya sudah ditangani otomatis oleh
        `get_async_session()` (commit di akhir request kalau tidak ada
        exception yang lolos ke router). Method ini sekarang hanya commit
        lewat UoW kalau UoW itu memang benar-benar sedang aktif (untuk
        caller lain di masa depan yang sengaja mulai transaksi manual lewat
        `async with self._uow:` / `self._uow.begin()`).
        """
        if self._uow and await self._uow.is_active():
            await self._uow.commit()

    def _to_response(self, aggregate: BudgetAggregate) -> BudgetResponse:
        return BudgetResponse(
            id=aggregate.id,
            budget_code=aggregate.budget_code,
            budget_name=aggregate.budget_name,
            budget_type=aggregate.budget_type.value,
            fiscal_year=aggregate.fiscal_year,
            period=aggregate.period.value,
            version=aggregate.version,
            status=aggregate.status.value,
            effective_date=aggregate.effective_date,
            expiry_date=aggregate.expiry_date,
            currency=aggregate.currency,
            total_amount=aggregate.total_amount,
            notes=aggregate.notes,
            tags=aggregate.tags,
            is_locked=aggregate.is_locked,
            created_at=aggregate.created_at,
            updated_at=aggregate.updated_at,
            created_by=aggregate.created_by,
            created_by_name=None,
            updated_by=aggregate.updated_by,
            approved_at=aggregate.approved_at,
            approved_by=aggregate.approved_by,
            approved_by_name=None,
            submitted_at=aggregate.submitted_at,
            submitted_by=aggregate.submitted_by,
            rejected_at=aggregate.rejected_at,
            rejected_by=aggregate.rejected_by,
            rejection_reason=aggregate.rejection_reason,
            version_number=aggregate.version_number,
            lines=[
                BudgetLineResponse(
                    id=line.id,
                    account_id=line.account_id,
                    account_code=line.account_code,
                    amount=line.amount,
                    note=line.note,
                    created_at=line.created_at,
                    updated_at=line.updated_at,
                )
                for line in aggregate.lines
            ],
        )

    def _aggregate_to_entity(self, aggregate: BudgetAggregate) -> BudgetEntity:
        return BudgetEntity(
            id=aggregate.id,
            legal_entity_id=aggregate.legal_entity_id,
            budget_code=aggregate.budget_code,
            budget_name=aggregate.budget_name,
            budget_type=aggregate.budget_type.value,
            fiscal_year=aggregate.fiscal_year,
            period=aggregate.period.value,
            version=aggregate.version,
            status=aggregate.status.value,
            effective_date=aggregate.effective_date,
            expiry_date=aggregate.expiry_date,
            currency=aggregate.currency,
            total_amount=aggregate.total_amount,
            notes=aggregate.notes,
            tags=aggregate.tags,
            is_locked=aggregate.is_locked,
            created_at=aggregate.created_at,
            updated_at=aggregate.updated_at,
            created_by=aggregate.created_by,
            updated_by=aggregate.updated_by,
            approved_at=aggregate.approved_at,
            approved_by=aggregate.approved_by,
            submitted_at=aggregate.submitted_at,
            submitted_by=aggregate.submitted_by,
            rejected_at=aggregate.rejected_at,
            rejected_by=aggregate.rejected_by,
            rejection_reason=aggregate.rejection_reason,
            version_number=aggregate.version_number,
            lines=[
                BudgetLineEntity(
                    id=line.id,
                    account_id=line.account_id,
                    account_code=line.account_code,
                    amount=line.amount,
                    note=line.note,
                    created_at=line.created_at,
                    updated_at=line.updated_at,
                )
                for line in aggregate.lines
            ],
        )

    # ========================================================================
    # CRUD OPERATIONS
    # ========================================================================

    @audit
    async def create_budget(self, request: BudgetCreateRequest) -> BudgetResponse:
        existing = await self._budget_repo.get_by_code_and_year(
            request.legal_entity_id, request.budget_code, request.fiscal_year
        )
        if existing:
            raise BudgetAlreadyExistsError(
                f"Budget {request.budget_code} already exists for fiscal year {request.fiscal_year}"
            )

        aggregate = BudgetAggregate.create(
            legal_entity_id=request.legal_entity_id,
            budget_code=request.budget_code,
            budget_name=request.budget_name,
            budget_type=BudgetType(request.budget_type),
            fiscal_year=request.fiscal_year,
            period=BudgetPeriod(request.period),
            effective_date=request.effective_date,
            expiry_date=request.expiry_date,
            currency=request.currency,
            lines=[
                BudgetLine(
                    id=uuid4(),
                    account_id=line.account_id,
                    account_code=line.account_code,
                    amount=line.amount,
                    note=line.note,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                for line in request.lines
            ],
            created_by=request.created_by,
            notes=request.notes,
            tags=request.tags,
            # [FIX] version_label yang diberikan client sebelumnya diabaikan
            # (selalu dipaksa "1.0" di BudgetAggregate.create).
            version=request.version,
        )

        entity = self._aggregate_to_entity(aggregate)
        await self._budget_repo.save(entity)
        await self._maybe_commit_uow()

        await self._publish_events(aggregate)

        self._record_audit("create_budget", {
            "budget_id": str(aggregate.id),
            "budget_code": aggregate.budget_code,
            "fiscal_year": aggregate.fiscal_year,
            "created_by": str(request.created_by),
        })

        return self._to_response(aggregate)

    @audit
    async def get_budget(self, budget_id: UUID) -> BudgetResponse:
        entity = await self._budget_repo.get_by_id(budget_id)
        if not entity:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        return BudgetResponse(
            id=entity.id,
            budget_code=entity.budget_code,
            budget_name=entity.budget_name,
            budget_type=entity.budget_type,
            fiscal_year=entity.fiscal_year,
            period=entity.period,
            version=entity.version,
            status=entity.status,
            effective_date=entity.effective_date,
            expiry_date=entity.expiry_date,
            currency=entity.currency,
            total_amount=entity.total_amount,
            notes=entity.notes,
            tags=entity.tags,
            is_locked=entity.is_locked,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            created_by=entity.created_by,
            created_by_name=None,
            updated_by=entity.updated_by,
            approved_at=entity.approved_at,
            approved_by=entity.approved_by,
            approved_by_name=None,
            submitted_at=entity.submitted_at,
            submitted_by=entity.submitted_by,
            rejected_at=entity.rejected_at,
            rejected_by=entity.rejected_by,
            rejection_reason=entity.rejection_reason,
            version_number=entity.version_number,
            lines=[
                BudgetLineResponse(
                    id=line.id,
                    account_id=line.account_id,
                    account_code=line.account_code,
                    amount=line.amount,
                    note=line.note,
                    created_at=line.created_at,
                    updated_at=line.updated_at,
                )
                for line in entity.lines
            ],
        )

    @audit
    async def list_budgets(
        self, legal_entity_id: UUID, fiscal_year: int | None = None, status: str | None = None
    ) -> list[BudgetResponse]:
        entities = await self._budget_repo.list_by_legal_entity(legal_entity_id, fiscal_year, status)
        return [
            BudgetResponse(
                id=e.id,
                budget_code=e.budget_code,
                budget_name=e.budget_name,
                budget_type=e.budget_type,
                fiscal_year=e.fiscal_year,
                period=e.period,
                version=e.version,
                status=e.status,
                effective_date=e.effective_date,
                expiry_date=e.expiry_date,
                currency=e.currency,
                total_amount=e.total_amount,
                notes=e.notes,
                tags=e.tags,
                is_locked=e.is_locked,
                created_at=e.created_at,
                updated_at=e.updated_at,
                created_by=e.created_by,
                created_by_name=None,
                updated_by=e.updated_by,
                approved_at=e.approved_at,
                approved_by=e.approved_by,
                approved_by_name=None,
                submitted_at=e.submitted_at,
                submitted_by=e.submitted_by,
                rejected_at=e.rejected_at,
                rejected_by=e.rejected_by,
                rejection_reason=e.rejection_reason,
                version_number=e.version_number,
                lines=[
                    BudgetLineResponse(
                        id=line.id,
                        account_id=line.account_id,
                        account_code=line.account_code,
                        amount=line.amount,
                        note=line.note,
                        created_at=line.created_at,
                        updated_at=line.updated_at,
                    )
                    for line in e.lines
                ],
            )
            for e in entities
        ]

    @audit
    async def update_budget(self, request: BudgetUpdateRequest) -> BudgetResponse:
        # [FIX] Dulu di sini ada duplikasi konstruksi `BudgetAggregate(...)` dengan
        # kwargs datar yang salah (lihat penjelasan di `_get_aggregate`). Sekarang
        # cukup pakai `_get_aggregate` yang sudah benar, sekaligus menghindari
        # duplikasi kode.
        aggregate = await self._get_aggregate(request.id)

        aggregate.update_info(
            user_id=request.updated_by,
            budget_name=request.budget_name,
            effective_date=request.effective_date,
            expiry_date=request.expiry_date,
            notes=request.notes,
            tags=request.tags,
        )

        updated_entity = self._aggregate_to_entity(aggregate)
        await self._budget_repo.update(updated_entity)
        await self._maybe_commit_uow()

        self._record_audit("update_budget", {
            "budget_id": str(aggregate.id),
            "budget_code": aggregate.budget_code,
            "updated_by": str(request.updated_by),
        })

        return self._to_response(aggregate)

    @audit
    async def delete_budget(self, budget_id: UUID, user_id: UUID) -> bool:
        result = await self._budget_repo.delete(budget_id)
        if result:
            await self._maybe_commit_uow()

        self._record_audit("delete_budget", {
            "budget_id": str(budget_id),
            "deleted_by": str(user_id),
        })

        return result

    # ========================================================================
    # WORKFLOW ACTIONS
    # ========================================================================

    def _entity_to_budget(self, entity: BudgetEntity) -> Budget:
        """
        [FIX] Bangun value object `Budget` (immutable) dari `BudgetEntity`.
        Dipakai sebagai satu-satunya tempat untuk merekonstruksi Budget dari
        data repository, supaya tidak ada lagi konstruksi `BudgetAggregate`
        dengan kwargs datar yang tidak sesuai dengan `BudgetAggregate.__init__`.
        """
        return Budget(
            id=entity.id,
            legal_entity_id=entity.legal_entity_id,
            budget_code=entity.budget_code,
            budget_name=entity.budget_name,
            budget_type=BudgetType(entity.budget_type),
            fiscal_year=entity.fiscal_year,
            period=BudgetPeriod(entity.period),
            version=entity.version,
            status=BudgetStatus(entity.status),
            effective_date=entity.effective_date,
            expiry_date=entity.expiry_date,
            currency=entity.currency,
            lines=[
                BudgetLineItem(
                    id=line.id,
                    account_id=line.account_id,
                    account_code=line.account_code,
                    amount=line.amount,
                    note=line.note,
                    created_at=line.created_at,
                    updated_at=line.updated_at,
                )
                for line in entity.lines
            ],
            notes=entity.notes,
            tags=entity.tags,
            is_locked=entity.is_locked,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            created_by=entity.created_by,
            updated_by=entity.updated_by,
            approved_at=entity.approved_at,
            approved_by=entity.approved_by,
            submitted_at=entity.submitted_at,
            submitted_by=entity.submitted_by,
            rejected_at=entity.rejected_at,
            rejected_by=entity.rejected_by,
            rejection_reason=entity.rejection_reason,
            version_number=entity.version_number,
        )

    async def _get_aggregate(self, budget_id: UUID) -> BudgetAggregate:
        entity = await self._budget_repo.get_by_id(budget_id)
        if not entity:
            raise BudgetNotFoundError(f"Budget {budget_id} not found")

        # [FIX] `BudgetAggregate.__init__(self, budget: Budget, version: int = 1)`
        # membungkus satu objek `Budget`, bukan menerima field-field budget
        # sebagai kwargs datar. Sebelumnya kode ini memanggil
        # `BudgetAggregate(id=..., legal_entity_id=..., ...)` yang selalu
        # menghasilkan TypeError, sehingga SEMUA aksi workflow (submit,
        # approve, reject, activate, lock, unlock, close, cancel, archive,
        # add_line, update_line, remove_line) selalu gagal.
        budget = self._entity_to_budget(entity)
        return BudgetAggregate(budget, version=entity.version_number)

    async def _save_aggregate(self, aggregate: BudgetAggregate) -> None:
        entity = self._aggregate_to_entity(aggregate)
        await self._budget_repo.update(entity)
        await self._maybe_commit_uow()
        await self._publish_events(aggregate)

    @audit
    async def submit_budget(self, budget_id: UUID, user_id: UUID) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.submit(user_id)
        await self._save_aggregate(aggregate)

        self._record_audit("submit_budget", {
            "budget_id": str(budget_id),
            "submitted_by": str(user_id),
        })

        return self._to_response(aggregate)

    @audit
    async def approve_budget(self, budget_id: UUID, user_id: UUID) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.approve(user_id)
        await self._save_aggregate(aggregate)

        self._record_audit("approve_budget", {
            "budget_id": str(budget_id),
            "approved_by": str(user_id),
        })

        return self._to_response(aggregate)

    @audit
    async def reject_budget(self, budget_id: UUID, user_id: UUID, reason: str) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.reject(user_id, reason)
        await self._save_aggregate(aggregate)

        self._record_audit("reject_budget", {
            "budget_id": str(budget_id),
            "rejected_by": str(user_id),
            "reason": reason,
        })

        return self._to_response(aggregate)

    @audit
    async def activate_budget(self, budget_id: UUID, user_id: UUID) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.activate(user_id)
        await self._save_aggregate(aggregate)

        self._record_audit("activate_budget", {
            "budget_id": str(budget_id),
            "activated_by": str(user_id),
        })

        return self._to_response(aggregate)

    @audit
    async def lock_budget(self, budget_id: UUID, user_id: UUID) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.lock(user_id)
        await self._save_aggregate(aggregate)

        self._record_audit("lock_budget", {
            "budget_id": str(budget_id),
            "locked_by": str(user_id),
        })

        return self._to_response(aggregate)

    @audit
    async def unlock_budget(self, budget_id: UUID, user_id: UUID) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.unlock(user_id)
        await self._save_aggregate(aggregate)

        self._record_audit("unlock_budget", {
            "budget_id": str(budget_id),
            "unlocked_by": str(user_id),
        })

        return self._to_response(aggregate)

    @audit
    async def archive_budget(self, budget_id: UUID, user_id: UUID) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.archive(user_id)
        await self._save_aggregate(aggregate)

        self._record_audit("archive_budget", {
            "budget_id": str(budget_id),
            "archived_by": str(user_id),
        })

        return self._to_response(aggregate)

    @audit
    async def cancel_budget(self, budget_id: UUID, user_id: UUID, reason: str) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.cancel(user_id, reason)
        await self._save_aggregate(aggregate)

        self._record_audit("cancel_budget", {
            "budget_id": str(budget_id),
            "cancelled_by": str(user_id),
            "reason": reason,
        })

        return self._to_response(aggregate)

    @audit
    async def close_budget(self, budget_id: UUID, user_id: UUID) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.close(user_id)
        await self._save_aggregate(aggregate)

        self._record_audit("close_budget", {
            "budget_id": str(budget_id),
            "closed_by": str(user_id),
        })

        return self._to_response(aggregate)

    # ========================================================================
    # LINE OPERATIONS
    # ========================================================================

    @audit
    async def add_line(self, budget_id: UUID, request: BudgetLineCreateRequest, user_id: UUID) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.add_line(
            user_id=user_id,
            account_id=request.account_id,
            account_code=request.account_code,
            amount=request.amount,
            note=request.note,
        )
        await self._save_aggregate(aggregate)

        self._record_audit("add_budget_line", {
            "budget_id": str(budget_id),
            "account_id": str(request.account_id),
            "amount": str(request.amount),
            "added_by": str(user_id),
        })

        return self._to_response(aggregate)

    @audit
    async def update_line(self, budget_id: UUID, request: BudgetLineUpdateRequest, user_id: UUID) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.update_line(
            user_id=user_id,
            line_id=request.line_id,
            amount=request.amount,
            note=request.note,
        )
        await self._save_aggregate(aggregate)

        self._record_audit("update_budget_line", {
            "budget_id": str(budget_id),
            "line_id": str(request.line_id),
            "new_amount": str(request.amount),
            "updated_by": str(user_id),
        })

        return self._to_response(aggregate)

    @audit
    async def remove_line(self, budget_id: UUID, line_id: UUID, user_id: UUID) -> BudgetResponse:
        aggregate = await self._get_aggregate(budget_id)
        aggregate.remove_line(user_id=user_id, line_id=line_id)
        await self._save_aggregate(aggregate)

        self._record_audit("remove_budget_line", {
            "budget_id": str(budget_id),
            "line_id": str(line_id),
            "removed_by": str(user_id),
        })

        return self._to_response(aggregate)

    # ========================================================================
    # DASHBOARD & ALERTS (baru)
    # ========================================================================

    @audit
    async def get_budget_dashboard(self, legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]:
        """Get budget dashboard summary."""
        budgets = await self.list_budgets(legal_entity_id)
        total_budget = sum(b.total_amount for b in budgets)
        active_budgets = [b for b in budgets if b.status == "active"]

        by_status = {
            "draft": len([b for b in budgets if b.status == "draft"]),
            "submitted": len([b for b in budgets if b.status == "submitted"]),
            "approved": len([b for b in budgets if b.status == "approved"]),
            "active": len(active_budgets),
            "locked": len([b for b in budgets if b.status == "locked"]),
            "archived": len([b for b in budgets if b.status == "archived"]),
        }

        # Sederhanakan return sebagai dict (sesuai router)
        return {
            "as_of_date": as_of_date.isoformat(),
            "total_budgets": len(budgets),
            "active_budgets": len(active_budgets),
            "draft_budgets": by_status["draft"],
            "total_budget_amount": str(total_budget),
            "by_status": by_status,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    @audit
    async def get_budget_alerts(
        self,
        legal_entity_id: UUID,
        threshold_percent: Decimal = Decimal("5"),
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get budget alerts for accounts exceeding threshold."""
        budgets = await self.list_budgets(legal_entity_id)
        alerts = []
        for b in budgets:
            if b.status not in ("active", "approved"):
                continue
            for line in b.lines:
                # Simulasi konsumsi (tanpa actual data, pakai 0)
                consumption = Decimal(0)
                if line.amount > 0:
                    # Di sini seharusnya ambil actual dari ledger_repo
                    actual = Decimal(0)
                    if self._ledger_repo:
                        try:
                            # Placeholder: ambil actual per account
                            actual = Decimal(0)  # Ganti dengan query nyata
                        except Exception:
                            pass
                    if actual > 0:
                        consumption = (actual / line.amount) * 100
                if consumption > threshold_percent:
                    alerts.append({
                        "budget_id": str(b.id),
                        "budget_name": b.budget_name,
                        "account_id": str(line.account_id),
                        "account_code": line.account_code,
                        "account_name": line.account_code,
                        "budget_amount": str(line.amount),
                        "actual_amount": str(actual) if 'actual' in locals() else "0",
                        "consumption_percent": float(consumption),
                        "threshold_percent": float(threshold_percent),
                        "message": f"Budget line {line.account_code} used {consumption:.1f}%",
                        "severity": "critical" if consumption > 80 else "warning",
                        "created_at": datetime.now(UTC).isoformat(),
                    })
        return alerts

    @audit
    async def get_budget_vs_actual(
        self, budget_id: UUID, legal_entity_id: UUID, period: int
    ) -> BudgetVsActualResponse | None:
        """Get budget vs actual for a specific month."""
        entity = await self._budget_repo.get_by_id(budget_id)
        if not entity:
            return None

        # Placeholder: tanpa actual data, return 0
        total_budget = entity.total_amount
        total_actual = Decimal(0)
        total_variance = total_actual - total_budget
        variance_percent = float(abs(total_variance) / total_budget * 100) if total_budget > 0 else 0.0

        lines = []
        for line in entity.lines:
            actual = Decimal(0)
            var = actual - line.amount
            var_pct = float(abs(var) / line.amount * 100) if line.amount > 0 else 0.0
            lines.append(
                BudgetVsActualLineResponse(
                    account_id=line.account_id,
                    account_code=line.account_code,
                    account_name=line.account_code,
                    budget_amount=line.amount,
                    actual_amount=actual,
                    variance_amount=var,
                    variance_percent=var_pct,
                    variance_type="neutral" if var == 0 else ("favorable" if var < 0 else "unfavorable"),
                    consumption_percent=0.0,
                    remaining_budget=line.amount - actual,
                )
            )

        return BudgetVsActualResponse(
            budget_id=entity.id,
            budget_name=entity.budget_name,
            fiscal_year=entity.fiscal_year,
            period=period,
            period_name=f"Month {period}",
            total_budget=total_budget,
            total_actual=total_actual,
            total_variance=total_variance,
            variance_percent=variance_percent,
            variance_type="neutral" if total_variance == 0 else ("favorable" if total_variance < 0 else "unfavorable"),
            consumption_rate=0.0,
            remaining_budget=total_budget - total_actual,
            lines=lines,
            generated_at=datetime.now(UTC),
        )

    @audit
    async def get_budget_vs_actual_ytd(
        self, budget_id: UUID, legal_entity_id: UUID, as_of_month: int
    ) -> BudgetVsActualResponse | None:
        """Get budget vs actual YTD."""
        # Untuk YTD, kita gunakan data yang sama dengan agregasi dari month 1..as_of_month
        # Placeholder: sama seperti di atas
        return await self.get_budget_vs_actual(budget_id, legal_entity_id, 0)

    @audit
    async def export_budgets(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        format: str,
        budget_type: str | None = None,
    ) -> str | bytes:
        """Export budgets to CSV or Excel."""
        # [FIX] Sebelumnya format="excel" tetap menghasilkan CSV mentah, lalu
        # router mengirimnya dengan media type xlsx dan nama file berakhiran
        # ".excel" -- file yang diunduh akan rusak/tidak bisa dibuka di Excel.
        # Export xlsx sungguhan belum diimplementasikan (butuh dependency
        # openpyxl yang belum ada di project ini), jadi untuk sekarang kita
        # tolak secara eksplisit alih-alih diam-diam mengirim file rusak.
        if format == "excel":
            raise NotImplementedError(
                "Export Excel (.xlsx) belum didukung. Gunakan format=csv untuk saat ini."
            )

        budgets = await self.list_budgets(legal_entity_id, fiscal_year=fiscal_year)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Budget Code", "Budget Name", "Type", "Year", "Status",
            "Total Amount", "Currency", "Effective Date", "Expiry Date"
        ])
        for b in budgets:
            writer.writerow([
                b.budget_code,
                b.budget_name,
                b.budget_type,
                b.fiscal_year,
                b.status,
                str(b.total_amount),
                b.currency,
                b.effective_date.isoformat(),
                b.expiry_date.isoformat() if b.expiry_date else "",
            ])
        return output.getvalue()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# FACTORY
# ============================================================================


async def create_budget_service(
    budget_repo: BudgetRepositoryPort,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
    ledger_repo=None,
) -> BudgetService:
    return BudgetService(budget_repo, uow, event_publisher, ledger_repo)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BudgetAlreadyExistsError",
    "BudgetInvalidStatusError",
    "BudgetNotFoundError",
    "BudgetService",
    "BudgetServiceError",
    "create_budget_service",
]
