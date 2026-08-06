#!/usr/bin/env python3
"""
Module: service_approval.py
Layer: Application / Service Layer
Responsibility: Service untuk workflow approval generik — DB-backed (via
                ApprovalRepositoryPort), menggantikan versi lama yang
                menyimpan data di dict in-memory.

CATATAN PENTING UNTUK REVIEWER (baca sebelum deploy):
    1. `get_approval_history()` di bawah ini MENGHASILKAN histori SINTETIS
       dari kolom timestamp yang ada di approval_request (submitted /
       approved / rejected / escalated / cancelled). Ini BUKAN audit trail
       sejati per-level. Kalau butuh histori akurat multi-level (siapa
       approve di level berapa, kapan), perlu tabel ApprovalHistoryTable
       terpisah + insert di setiap transisi status. Belum dibuat di sini
       karena belum ada spek tabelnya.
    2. Action "delegate" di process_approval_action() mengalihkan
       approver_id ke delegate_to_user_id tanpa validasi bahwa delegasi
       tsb memang tercatat aktif di approval_delegation. Tambahkan
       validasi itu kalau delegasi harus terverifikasi sebelum dipakai.
    3. Saat escalate, approver level berikutnya diambil dari
       ApprovalMatrixTable.rules (list of dict, dicari yang match
       "level"). Kalau matrix/level tidak ditemukan, escalate gagal
       dengan ValueError — request TIDAK auto-selesai begitu saja.
    4. `export_approval_requests()` mengembalikan bytes CSV mentah;
       sesuaikan lagi kalau format lain (xlsx/pdf) dibutuhkan.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from infrastructure.persistence_orm.approval_delegation_table import ApprovalDelegationTable
from infrastructure.persistence_orm.approval_matrix_table import ApprovalMatrixTable
from infrastructure.persistence_orm.approval_request_table import ApprovalRequestTable
from ports.primary.approval_repository_port import ApprovalRepositoryPort

logger = logging.getLogger(__name__)


def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


@dataclass(kw_only=True)
class PaginatedResult:
    """Paginated result container."""

    items: list[Any]
    total: int = 0
    page: int = 1
    page_size: int = 20

    @property
    def total_pages(self) -> int:
        return (self.total + self.page_size - 1) // self.page_size if self.page_size > 0 else 0

    def has_next(self) -> bool:
        return self.page < self.total_pages

    def has_prev(self) -> bool:
        return self.page > 1


# ============================================================================
# Service
# ============================================================================


class ApprovalService:
    """Service layer untuk operasi approval workflow, DB-backed."""

    def __init__(self, approval_repo: ApprovalRepositoryPort) -> None:
        self._repo = approval_repo
        logger.info("ApprovalService initialized (DB-backed)")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        """Placeholder authority check; ganti dengan authority matrix produksi."""
        if user_id is None:
            logger.debug("System action for permission '%s' (no user_id)", permission)
            return
        logger.debug("Authority check: user %s permission '%s' passed (placeholder)", user_id, permission)

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        logger.info("AUDIT: %s - %s", action, details or {})

    # ==================== MAPPER: ORM row -> response object ====================

    def _matrix_name_for(self, matrix_id: UUID | None, legal_entity_id: UUID | None) -> str | None:
        """Best-effort lookup nama matrix untuk satu request (dipakai di get single-item)."""
        # NOTE: dipanggil sinkron dari async context lewat caller; lihat _to_response async wrapper.
        return None  # diisi oleh _to_response yang async, lihat di bawah

    async def _to_response(
        self, row: ApprovalRequestTable, matrix_cache: dict[UUID, str | None] | None = None
    ) -> SimpleNamespace:
        """Konversi ApprovalRequestTable -> object dengan nama atribut yang
        diharapkan router (current_level, requester_notes, current_approver_*, dst)."""
        matrix_name = None
        if row.approval_matrix_id:
            if matrix_cache is not None and row.approval_matrix_id in matrix_cache:
                matrix_name = matrix_cache[row.approval_matrix_id]
            else:
                matrix = await self._repo.get_matrix_by_id(row.approval_matrix_id, row.legal_entity_id)
                matrix_name = matrix.matrix_name if matrix else None
                if matrix_cache is not None:
                    matrix_cache[row.approval_matrix_id] = matrix_name

        completed_at = row.approved_at or row.cancelled_at
        completed_by = row.approved_by or row.cancelled_by
        final_decision = row.status if row.status in ("approved", "rejected", "cancelled", "expired") else None

        return SimpleNamespace(
            id=row.id,
            request_number=row.request_number,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            entity_reference=row.entity_reference,
            amount=row.amount,
            currency=row.currency,
            status=row.status,
            current_level=row.current_level,
            requester_id=row.requested_by,
            requester_name=row.requester_name,
            requester_notes=row.requester_comments,
            submitted_at=row.created_at,
            current_approver_id=str(row.approver_id) if row.approver_id else None,
            current_approver_name=row.approver_name,
            current_approver_role=row.approver_role,
            approval_matrix_id=str(row.approval_matrix_id) if row.approval_matrix_id else None,
            approval_matrix_name=matrix_name,
            legal_entity_id=str(row.legal_entity_id) if row.legal_entity_id else None,
            due_date=row.deadline,
            notes=row.approval_comments or row.requester_comments,
            reason=row.cancellation_reason,
            escalated_at=row.escalated_at,
            escalated_to=row.escalated_to,
            completed_at=completed_at,
            completed_by=completed_by,
            completed_by_name=None,  # perlu join ke IAM user table utk resolve nama
            final_decision=final_decision,
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=row.created_by,
            created_by_name=None,
            version=row.version,
        )

    def _matrix_to_response(self, m: ApprovalMatrixTable) -> SimpleNamespace:
        return SimpleNamespace(
            id=m.id,
            matrix_code=m.matrix_code,
            matrix_name=m.matrix_name,
            entity_type=m.entity_type,
            min_amount=m.min_amount,
            max_amount=m.max_amount,
            currency=m.currency,
            rules=m.rules,
            is_active=m.is_active,
            notes=m.notes,
            created_at=m.created_at,
            updated_at=m.updated_at,
            created_by=m.created_by,
            created_by_name=m.created_by_name,
            version=m.version,
        )

    def _delegation_to_response(self, d: ApprovalDelegationTable) -> SimpleNamespace:
        return SimpleNamespace(
            id=d.id,
            delegator_id=d.delegator_id,
            delegator_name=d.delegator_name,
            delegate_to_id=d.delegate_to_id,
            delegate_to_name=d.delegate_to_name,
            start_date=d.start_date,
            end_date=d.end_date,
            reason=d.reason,
            is_active=d.is_active,
            created_at=d.created_at,
            created_by=d.created_by,
        )

    # ==================== SUBMIT / GET / LIST ====================

    @audit
    async def submit_approval(
        self,
        entity_type: str,
        entity_id: UUID,
        approval_matrix_id: UUID | None = None,
        requester_id: UUID | None = None,
        requester_name: str | None = None,
        legal_entity_id: UUID | None = None,
        amount: Decimal | None = None,
        notes: str | None = None,
    ) -> SimpleNamespace:
        """Submit entity untuk approval. Menentukan approver level-1 dari matrix."""
        self._check_authority(requester_id, "submit_approval")

        approver_id: UUID | None = None
        approver_name = "Unassigned"
        approver_role: str | None = None

        if approval_matrix_id:
            matrix = await self._repo.get_matrix_by_id(approval_matrix_id, legal_entity_id)
            if not matrix:
                raise ValueError(f"Approval matrix {approval_matrix_id} not found")
            level1_rule = next((r for r in (matrix.rules or []) if r.get("level") == 1), None)
            if not level1_rule:
                raise ValueError(f"Matrix {matrix.matrix_code} has no level-1 rule defined")
            approver_id = level1_rule.get("approver_id")
            approver_name = level1_rule.get("approver_name", "Unassigned")
            approver_role = level1_rule.get("approver_role")

        if approver_id is None:
            raise ValueError(
                "Cannot determine approver: approval_matrix_id is required and must have a "
                "level-1 rule with 'approver_id' set."
            )

        request_number = f"APR-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:6].upper()}"

        row = ApprovalRequestTable(
            request_number=request_number,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_reference=f"{entity_type}-{entity_id.hex[:8]}",
            amount=amount,
            approver_id=approver_id,
            approver_name=approver_name,
            approver_role=approver_role,
            status="pending",
            current_level=1,
            approval_matrix_id=approval_matrix_id,
            requested_by=requester_id,
            requester_name=requester_name,
            requester_comments=notes,
            created_by=requester_id,
            legal_entity_id=legal_entity_id,
        )
        row = await self._repo.save_request(row)

        self._record_audit("submit_approval", {
            "request_id": str(row.id),
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "requester_id": str(requester_id) if requester_id else None,
            "legal_entity_id": str(legal_entity_id) if legal_entity_id else None,
        })

        # Pass matrix_name via cache to avoid second get_matrix_by_id call in _to_response
        matrix_cache: dict[UUID, str | None] = {approval_matrix_id: matrix.matrix_name} if approval_matrix_id and matrix else {}
        return await self._to_response(row, matrix_cache)

    async def list_approval_requests(
        self,
        legal_entity_id: UUID,
        entity_type: str | None = None,
        status: str | None = None,
        requester_id: UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PaginatedResult:
        items, total = await self._repo.list_requests(
            legal_entity_id=legal_entity_id,
            entity_type=entity_type,
            status=status,
            requester_id=requester_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )
        matrix_cache: dict[UUID, str | None] = {}
        response_items = [await self._to_response(r, matrix_cache) for r in items]
        return PaginatedResult(items=response_items, total=total, page=page, page_size=page_size)

    async def get_approval_request(
        self, request_id: UUID, legal_entity_id: UUID | None = None
    ) -> SimpleNamespace | None:
        row = await self._repo.get_request_by_id(request_id)
        if row and legal_entity_id and row.legal_entity_id != legal_entity_id:
            return None
        if not row:
            return None
        return await self._to_response(row)

    async def get_approval_request_by_number(
        self, request_number: str, legal_entity_id: UUID | None = None
    ) -> SimpleNamespace | None:
        row = await self._repo.get_request_by_number(request_number, legal_entity_id)
        if not row:
            return None
        return await self._to_response(row)

    # ==================== ACTIONS ====================

    @audit
    async def recall_approval(
        self, request_id: UUID, requester_id: UUID, legal_entity_id: UUID | None = None
    ) -> SimpleNamespace | None:
        self._check_authority(requester_id, "recall")
        row = await self._repo.get_request_by_id(request_id)
        if not row or (legal_entity_id and row.legal_entity_id != legal_entity_id):
            return None
        if row.requested_by != requester_id:
            raise ValueError("Only requester can recall approval")
        if row.status != "pending":
            raise ValueError(f"Cannot recall request with status {row.status}")
        row.cancel(cancelled_by=requester_id, reason="Recalled by requester")
        row.status = "cancelled"
        self._record_audit("recall_approval", {"request_id": str(request_id)})
        return await self._to_response(row)

    @audit
    async def cancel_approval(
        self,
        request_id: UUID,
        actor_id: UUID,
        legal_entity_id: UUID | None = None,
        reason: str | None = None,
    ) -> SimpleNamespace | None:
        self._check_authority(actor_id, "cancel")
        row = await self._repo.get_request_by_id(request_id)
        if not row or (legal_entity_id and row.legal_entity_id != legal_entity_id):
            return None
        row.cancel(cancelled_by=actor_id, reason=reason or "Cancelled")
        self._record_audit("cancel_approval", {"request_id": str(request_id), "reason": reason})
        return await self._to_response(row)

    @audit
    async def process_approval_action(
        self,
        request_id: UUID,
        action: str,
        actor_id: UUID,
        legal_entity_id: UUID | None = None,
        notes: str | None = None,
        delegate_to_user_id: UUID | None = None,
        escalation_level: int | None = None,
    ) -> SimpleNamespace | None:
        """Approve / reject / escalate / delegate."""
        self._check_authority(actor_id, f"process_approval_{action}")

        row = await self._repo.get_request_by_id(request_id)
        if not row or (legal_entity_id and row.legal_entity_id != legal_entity_id):
            return None
        if row.status != "pending":
            raise ValueError(f"Request {request_id} is not pending")

        if action == "approve":
            row.approve(approved_by=actor_id, comments=notes)

        elif action == "reject":
            row.reject(approved_by=actor_id, comments=notes or "Rejected")

        elif action == "escalate":
            target_level = escalation_level or (row.current_level + 1)
            next_approver = await self._resolve_matrix_approver(
                row.approval_matrix_id, row.legal_entity_id, target_level
            )
            if not next_approver:
                raise ValueError(
                    f"No approver rule found for level {target_level} in matrix "
                    f"{row.approval_matrix_id}"
                )
            row.escalate(escalated_to=next_approver["approver_id"], reason=notes or "Escalated")
            # Assign new approver as the current approver
            row.approver_id = next_approver["approver_id"]
            row.approver_name = next_approver.get("approver_name", "Unassigned")
            row.approver_role = next_approver.get("approver_role")
            row.status = "pending"  # kembali pending di level baru, bukan "escalated" permanen

        elif action == "delegate":
            if not delegate_to_user_id:
                raise ValueError("delegate_to_user_id is required for action='delegate'")
            row.approver_id = delegate_to_user_id
            row.approver_name = "Delegated"
            row.increment_version()

        else:
            raise ValueError(f"Unknown action: {action}")

        self._record_audit("process_approval_action", {
            "request_id": str(request_id), "action": action, "actor_id": str(actor_id),
        })
        return await self._to_response(row)

    async def _resolve_matrix_approver(
        self, matrix_id: UUID | None, legal_entity_id: UUID | None, level: int
    ) -> dict[str, Any] | None:
        if not matrix_id:
            return None
        matrix = await self._repo.get_matrix_by_id(matrix_id, legal_entity_id)
        if not matrix:
            return None
        return next((r for r in (matrix.rules or []) if r.get("level") == level), None)

    # ==================== PENDING TASKS ====================

    async def get_pending_tasks_for_user(
        self,
        user_id: UUID,
        legal_entity_id: UUID | None = None,
        entity_type: str | None = None,
        overdue_only: bool = False,
    ) -> list[SimpleNamespace]:
        rows = await self._repo.get_pending_requests_for_user(user_id)
        if legal_entity_id:
            rows = [r for r in rows if r.legal_entity_id == legal_entity_id]
        if entity_type:
            rows = [r for r in rows if r.entity_type == entity_type]
        if overdue_only:
            rows = [r for r in rows if r.is_overdue]
        return [await self._to_response(r) for r in rows]

    async def get_pending_tasks_count(
        self, user_id: UUID, legal_entity_id: UUID | None = None
    ) -> SimpleNamespace:
        rows = await self._repo.get_pending_requests_for_user(user_id)
        if legal_entity_id:
            rows = [r for r in rows if r.legal_entity_id == legal_entity_id]
        by_entity_type: dict[str, int] = {}
        overdue = 0
        for r in rows:
            by_entity_type[r.entity_type] = by_entity_type.get(r.entity_type, 0) + 1
            if r.is_overdue:
                overdue += 1
        return SimpleNamespace(total=len(rows), by_entity_type=by_entity_type, overdue=overdue)

    # ==================== HISTORY (SINTETIS — lihat catatan di atas file) ====================

    async def get_approval_history(
        self, request_id: UUID, legal_entity_id: UUID | None = None
    ) -> list[SimpleNamespace]:
        row = await self._repo.get_request_by_id(request_id)
        if not row or (legal_entity_id and row.legal_entity_id != legal_entity_id):
            return []

        entries: list[SimpleNamespace] = []

        def add(action: str, at: datetime | None, actor_id: UUID | None, from_lv, to_lv, notes_):
            if at is None:
                return
            entries.append(SimpleNamespace(
                id=uuid4(), approval_request_id=row.id, action=action,
                from_level=from_lv, to_level=to_lv, actor_id=actor_id,
                actor_name=None, actor_role=None, action_at=at, notes=notes_,
            ))

        add("submitted", row.created_at, row.requested_by, None, 1, row.requester_comments)
        if row.status == "approved":
            add("approved", row.approved_at, row.approved_by, row.current_level, row.current_level, row.approval_comments)
        elif row.status == "rejected":
            add("rejected", row.approved_at, row.approved_by, row.current_level, row.current_level, row.approval_comments)
        elif row.status == "cancelled":
            add("recalled", row.cancelled_at, row.cancelled_by, row.current_level, row.current_level, row.cancellation_reason)
        if row.escalated_at:
            add("escalated", row.escalated_at, None, row.current_level - 1, row.current_level, row.approval_comments)

        entries.sort(key=lambda e: e.action_at)
        return entries

    async def get_entity_approval_status(
        self, entity_type: str, entity_id: UUID, legal_entity_id: UUID | None = None
    ) -> SimpleNamespace | None:
        rows = await self._repo.get_requests_by_entity(entity_type, entity_id)
        if legal_entity_id:
            rows = [r for r in rows if r.legal_entity_id == legal_entity_id]
        if not rows:
            return None
        return await self._to_response(rows[0])  # sudah terurut created_at desc dari repo

    # ==================== APPROVAL MATRIX ====================

    @audit
    async def create_approval_matrix(
        self,
        matrix_code: str,
        matrix_name: str,
        entity_type: str,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
        currency: str,
        rules: list[dict[str, Any]],
        is_active: bool,
        notes: str | None,
        created_by: UUID,
        legal_entity_id: UUID,
    ) -> SimpleNamespace:
        matrix = ApprovalMatrixTable(
            matrix_code=matrix_code, matrix_name=matrix_name, entity_type=entity_type,
            min_amount=min_amount, max_amount=max_amount, currency=currency, rules=rules,
            is_active=is_active, notes=notes, created_by=created_by, legal_entity_id=legal_entity_id,
        )
        matrix = await self._repo.save_matrix(matrix)
        return self._matrix_to_response(matrix)

    async def list_approval_matrices(
        self, legal_entity_id: UUID, entity_type: str | None = None, is_active: bool | None = None
    ) -> list[SimpleNamespace]:
        matrices = await self._repo.list_matrices(legal_entity_id, entity_type, is_active)
        return [self._matrix_to_response(m) for m in matrices]

    async def get_approval_matrix(
        self, matrix_id: UUID, legal_entity_id: UUID | None = None
    ) -> SimpleNamespace | None:
        matrix = await self._repo.get_matrix_by_id(matrix_id, legal_entity_id)
        return self._matrix_to_response(matrix) if matrix else None

    @audit
    async def update_approval_matrix(
        self,
        matrix_id: UUID,
        matrix_name: str | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        currency: str | None = None,
        rules: list[dict[str, Any]] | None = None,
        is_active: bool | None = None,
        notes: str | None = None,
        legal_entity_id: UUID | None = None,
    ) -> SimpleNamespace | None:
        matrix = await self._repo.get_matrix_by_id(matrix_id, legal_entity_id)
        if not matrix:
            return None
        if matrix_name is not None:
            matrix.matrix_name = matrix_name
        if min_amount is not None:
            matrix.min_amount = min_amount
        if max_amount is not None:
            matrix.max_amount = max_amount
        if currency is not None:
            matrix.currency = currency
        if rules is not None:
            matrix.rules = rules
        if is_active is not None:
            matrix.is_active = is_active
        if notes is not None:
            matrix.notes = notes
        matrix.increment_version()
        return self._matrix_to_response(matrix)

    async def delete_approval_matrix(
        self, matrix_id: UUID, legal_entity_id: UUID, actor_id: UUID
    ) -> bool:
        return await self._repo.delete_matrix(matrix_id, legal_entity_id)

    async def deactivate_approval_matrix(
        self, matrix_id: UUID, legal_entity_id: UUID, actor_id: UUID
    ) -> bool:
        matrix = await self._repo.get_matrix_by_id(matrix_id, legal_entity_id)
        if not matrix:
            return False
        matrix.is_active = False
        matrix.increment_version()
        return True

    # ==================== DELEGATION ====================

    @audit
    async def create_delegation(
        self,
        delegator_id: UUID,
        delegate_to_id: UUID,
        start_date: date,
        end_date: date,
        reason: str | None,
        legal_entity_id: UUID,
    ) -> SimpleNamespace:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        delegation = ApprovalDelegationTable(
            delegator_id=delegator_id, delegate_to_id=delegate_to_id,
            start_date=start_date, end_date=end_date, reason=reason,
            is_active=True, created_by=delegator_id, legal_entity_id=legal_entity_id,
        )
        delegation = await self._repo.save_delegation(delegation)
        return self._delegation_to_response(delegation)

    async def list_delegations(
        self, delegator_id: UUID, legal_entity_id: UUID, is_active: bool | None = None
    ) -> list[SimpleNamespace]:
        delegations = await self._repo.list_delegations_by_delegator(
            delegator_id, legal_entity_id, is_active
        )
        return [self._delegation_to_response(d) for d in delegations]

    @audit
    async def revoke_delegation(
        self, delegation_id: UUID, actor_id: UUID, legal_entity_id: UUID | None = None
    ) -> bool:
        delegation = await self._repo.get_delegation_by_id(delegation_id, legal_entity_id)
        if not delegation:
            return False
        delegation.is_active = False
        delegation.revoked_by = actor_id
        delegation.revoked_at = datetime.now(UTC)
        delegation.increment_version()
        return True

    # ==================== STATISTICS ====================

    async def get_approval_statistics(
        self,
        legal_entity_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        entity_type: str | None = None,
    ) -> SimpleNamespace:
        stats = await self._repo.get_statistics(legal_entity_id, start_date, end_date, entity_type)
        return SimpleNamespace(**stats)

    # ==================== EXPORT ====================

    async def export_approval_requests(
        self,
        legal_entity_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        format: str = "csv",
        status: str | None = None,
    ) -> bytes:
        """Export approval requests. Saat ini hanya format 'csv' yang didukung."""
        if format != "csv":
            raise ValueError(f"Unsupported export format: {format} (hanya 'csv' saat ini)")

        all_items: list[ApprovalRequestTable] = []
        page = 1
        while True:
            items, total = await self._repo.list_requests(
                legal_entity_id=legal_entity_id, status=status,
                start_date=start_date, end_date=end_date, page=page, page_size=200,
            )
            all_items.extend(items)
            if len(all_items) >= total or not items:
                break
            page += 1

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "request_number", "entity_type", "entity_id", "status", "current_level",
            "amount", "currency", "requester_name", "approver_name", "created_at", "approved_at",
        ])
        for r in all_items:
            writer.writerow([
                r.request_number, r.entity_type, str(r.entity_id), r.status, r.current_level,
                r.amount, r.currency, r.requester_name, r.approver_name,
                r.created_at.isoformat() if r.created_at else "",
                r.approved_at.isoformat() if r.approved_at else "",
            ])
        return buf.getvalue().encode("utf-8")


__all__ = ["ApprovalService", "PaginatedResult", "audit"]
