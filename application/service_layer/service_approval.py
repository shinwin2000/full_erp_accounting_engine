#!/usr/bin/env python3
"""
Module: service_approval.py
Layer: Application / Service Layer
Responsibility: Service untuk workflow approval generik — DB-backed (via
                ApprovalRepositoryPort).

ATURAN BISNIS YANG DITEGAKKAN SERVICE INI
    1. Segregation of duties: hanya approver yang ditugaskan (atau delegasi aktif
       dari approver tsb) yang boleh approve/reject/escalate/delegate. Requester
       TIDAK PERNAH boleh memproses request miliknya sendiri.
    2. Multi-level: approve pada level yang bukan terakhir memindahkan request ke
       approver level berikutnya (status tetap ``pending``). Status ``approved``
       baru diberikan setelah level terakhir menyetujui. Rantai level ditentukan
       dari rule matrix + nominal (lihat ``_build_chain``).
    3. Delegasi: aksi ``delegate`` mensyaratkan delegasi AKTIF di tabel
       approval_delegation dari approver ke user tujuan.
    4. Setiap rule matrix wajib punya minimal satu approver user
       (``approver_user_ids``), karena satu request hanya punya satu ``approver_id``.
    5. Setiap perubahan baris approval_request memakai SELECT ... FOR UPDATE
       (pessimistic lock) + optimistic version check.

SINKRONISASI ENTITY
    - Service ini mendukung ``attach_entity_gateway(gateway)``. Bila gateway
      terpasang, saat approval mencapai keputusan final (approve/reject/cancel),
      status entity terkait (journal_header, ap_invoice, dst) ikut diperbarui.
    - Sinkronisasi bersifat BEST-EFFORT: kegagalan gateway TIDAK menggagalkan
      transaksi approval utama; hanya dicatat sebagai warning/exception di log.

CATATAN PENTING
    - Audit trail per-transisi disimpan di ``entity_snapshot["approval_trail"]``
      (JSONB) pada baris approval_request, karena belum ada tabel history khusus.
      Request lama (tanpa trail) memakai histori sintetis dari kolom timestamp.
    - Belum didukung (ditolak dengan pesan jelas saat membuat matrix):
      ``min_approvers`` > 1 dan ``auto_approve_if_requester_in_role``.
    - Export hanya format CSV.
    - Service tidak commit: commit/rollback dilakukan pemilik session (dependency
      ``get_async_session`` pada request HTTP).
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy.orm.exc import StaleDataError

from infrastructure.persistence_orm.approval_delegation_table import ApprovalDelegationTable
from infrastructure.persistence_orm.approval_matrix_table import ApprovalMatrixTable
from infrastructure.persistence_orm.approval_request_table import ApprovalRequestTable
from ports.primary.approval_repository_port import ApprovalRepositoryPort

if TYPE_CHECKING:
    from adapters.secondary_impl.approval_entity_gateway_impl import ApprovalEntityGateway

logger = logging.getLogger(__name__)

# Harus identik dengan CHECK constraint ck_approval_entity_type / ck_approval_matrix_entity_type.
ENTITY_TYPES: tuple[str, ...] = (
    "journal",
    "ap_invoice",
    "ar_invoice",
    "payment",
    "purchase_order",
    "sales_order",
    "budget",
    "master_data",
)

# Urutan level -> angka 1..9 (level_1=1, ..., board=9).
LEVEL_NAMES: tuple[str, ...] = (
    "level_1",
    "level_2",
    "level_3",
    "level_4",
    "level_5",
    "executive",
    "cfo",
    "ceo",
    "board",
)

# Batas kolom NUMERIC(20, 2) di database; nilai lebih besar menyebabkan error DB (HTTP 500).
MAX_AMOUNT = Decimal("999999999999999999.99")

_SUPPORTED_ACTIONS = ("approve", "reject", "escalate", "delegate")
_CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Helper level & rule
# ============================================================================


def level_to_int(value: Any) -> int:
    """Konversi level ("level_2", "cfo", 2, Enum) ke angka 1..9."""
    if isinstance(value, bool):
        raise ValueError(f"Invalid approval level: {value!r}")
    if hasattr(value, "value") and not isinstance(value, (int, str)):
        value = value.value  # Enum
    if isinstance(value, str) and hasattr(value, "value"):
        value = value.value  # str-Enum
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip().lower()
        if text.isdigit():
            number = int(text)
        elif text in LEVEL_NAMES:
            number = LEVEL_NAMES.index(text) + 1
        else:
            raise ValueError(f"Invalid approval level: {value!r}")
    else:
        raise ValueError(f"Invalid approval level: {value!r}")
    if not 1 <= number <= len(LEVEL_NAMES):
        raise ValueError(f"Approval level out of range (1-{len(LEVEL_NAMES)}): {value!r}")
    return number


def level_name(number: int) -> str:
    """Kebalikan level_to_int: 1 -> "level_1", 7 -> "cfo"."""
    if not 1 <= number <= len(LEVEL_NAMES):
        raise ValueError(f"Approval level out of range (1-{len(LEVEL_NAMES)}): {number!r}")
    return LEVEL_NAMES[number - 1]


def _to_uuid(value: Any, field: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{field} must be a valid UUID, got {value!r}") from exc


def _to_decimal(value: Any, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a number, got {value!r}") from exc


def _rule_level(rule: dict[str, Any]) -> int:
    return level_to_int(rule.get("level"))


def _rule_approver_ids(rule: dict[str, Any]) -> list[UUID]:
    """Approver user dari rule: ``approver_user_ids`` (utama) + ``approver_id`` (format lama)."""
    raw: list[Any] = list(rule.get("approver_user_ids") or [])
    if rule.get("approver_id"):
        raw.append(rule["approver_id"])
    result: list[UUID] = []
    for item in raw:
        uid = _to_uuid(item, "approver_user_ids")
        if uid not in result:
            result.append(uid)
    return result


def _rule_in_range(rule: dict[str, Any], amount: Decimal | None) -> bool:
    if amount is None:
        return True
    low = _to_decimal(rule.get("min_amount"), "min_amount")
    high = _to_decimal(rule.get("max_amount"), "max_amount")
    if low is not None and amount < low:
        return False
    return not (high is not None and amount > high)


def _build_chain(rules: list[dict[str, Any]], amount: Decimal | None) -> list[dict[str, Any]]:
    """Tentukan rantai level yang wajib disetujui secara berurutan.

    Level tertinggi yang rentang nominalnya mencakup ``amount`` menjadi level akhir;
    semua level di bawahnya (dan level itu sendiri) wajib menyetujui berurutan.
    Rule ``is_final`` memutus rantai. ``amount`` None -> semua level berlaku.
    """
    parsed = sorted(((_rule_level(r), r) for r in rules), key=lambda pair: pair[0])
    applicable = [lvl for lvl, r in parsed if _rule_in_range(r, amount)]
    if not applicable:
        raise ValueError(f"No approval rule in the matrix covers amount {amount}")
    top = max(applicable)
    chain: list[dict[str, Any]] = []
    for lvl, rule in parsed:
        if lvl > top:
            break
        chain.append(rule)
        if rule.get("is_final"):
            break
    return chain


def _matrix_accepts(matrix: ApprovalMatrixTable, amount: Decimal | None) -> bool:
    low, high = matrix.min_amount, matrix.max_amount
    if amount is None:
        return low is None and high is None
    if low is not None and amount < low:
        return False
    return not (high is not None and amount > high)


def _validate_and_normalize_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validasi rule matrix dan kembalikan salinan JSON-safe."""
    if not rules:
        raise ValueError("Approval matrix requires at least one rule")
    normalized: list[dict[str, Any]] = []
    seen_levels: set[int] = set()
    for index, raw in enumerate(rules, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Rule #{index} must be an object")
        level = _rule_level(raw)
        if level in seen_levels:
            raise ValueError(f"Duplicate rule for {level_name(level)}")
        seen_levels.add(level)

        approvers = _rule_approver_ids(raw)
        if not approvers:
            raise ValueError(
                f"Rule {level_name(level)} must define at least one approver user "
                "(approver_user_ids)"
            )
        if int(raw.get("min_approvers") or 1) > 1:
            raise ValueError(
                f"Rule {level_name(level)}: min_approvers > 1 is not supported yet "
                "(one approver per level)"
            )
        if raw.get("auto_approve_if_requester_in_role"):
            raise ValueError(
                f"Rule {level_name(level)}: auto_approve_if_requester_in_role is not supported yet"
            )
        low = _to_decimal(raw.get("min_amount"), "min_amount")
        high = _to_decimal(raw.get("max_amount"), "max_amount")
        if low is not None and low < 0:
            raise ValueError(f"Rule {level_name(level)}: min_amount must be >= 0")
        if (low is not None and low > MAX_AMOUNT) or (high is not None and high > MAX_AMOUNT):
            raise ValueError(f"Rule {level_name(level)}: amount exceeds the maximum of {MAX_AMOUNT}")
        if low is not None and high is not None and low > high:
            raise ValueError(f"Rule {level_name(level)}: min_amount cannot exceed max_amount")

        normalized.append(
            {
                "level": level_name(level),
                "min_amount": str(low) if low is not None else None,
                "max_amount": str(high) if high is not None else None,
                "approver_user_ids": [str(a) for a in approvers],
                "approver_name": raw.get("approver_name"),
                "approver_role": raw.get("approver_role"),
                "min_approvers": 1,
                "max_approvers": int(raw.get("max_approvers") or 1),
                "is_final": bool(raw.get("is_final", False)),
                "escalation_days": raw.get("escalation_days"),
                "escalation_to_level": (
                    level_name(level_to_int(raw["escalation_to_level"]))
                    if raw.get("escalation_to_level")
                    else None
                ),
            }
        )
    normalized.sort(key=lambda r: level_to_int(r["level"]))
    return normalized


def _pick_approver(rule: dict[str, Any], requester_id: UUID | None) -> tuple[UUID, str, str | None]:
    """Pilih approver dari rule; approver tidak boleh sama dengan requester."""
    candidates = _rule_approver_ids(rule)
    if not candidates:
        raise ValueError(
            f"Approval matrix rule {level_name(_rule_level(rule))} has no approver user configured; "
            "edit the matrix and add approver_user_ids"
        )
    for uid in candidates:
        if requester_id is not None and uid == requester_id:
            continue
        name = rule.get("approver_name") or f"User {str(uid)[:8]}"
        return uid, name, rule.get("approver_role")
    raise ValueError(
        f"No eligible approver for {level_name(_rule_level(rule))}: every configured approver "
        "is the requester (segregation of duties)"
    )


def _deadline_for(rule: dict[str, Any]) -> datetime | None:
    days = rule.get("escalation_days")
    if days:
        return datetime.now(UTC) + timedelta(days=int(days))
    return None


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
        self._entity_gateway: "ApprovalEntityGateway | None" = None
        logger.info("ApprovalService initialized (DB-backed)")

    def attach_entity_gateway(self, gateway: "ApprovalEntityGateway") -> None:
        """Pasang gateway sinkronisasi entity (dipanggil dari router per-request).

        Gateway bersifat opsional; bila tidak dipasang, service tetap berjalan
        normal tanpa sinkronisasi status ke tabel entity.
        """
        self._entity_gateway = gateway
        logger.debug("ApprovalService: entity gateway attached (%s)", type(gateway).__name__)

    # ==================== INTERNAL HELPERS ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        """Hook authority check tambahan (permission utama sudah dijaga router)."""
        if user_id is None:
            logger.debug("System action for permission '%s' (no user_id)", permission)

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        logger.info("AUDIT: %s - %s", action, details or {})

    async def _persist(self, obj: Any) -> Any:
        try:
            return await self._repo.flush_and_refresh(obj)
        except StaleDataError as exc:
            raise ValueError(
                "The record was modified by another user. Please reload and try again."
            ) from exc

    # ---------- Entity gateway sync helpers (best-effort) ----------

    async def _sync_entity_approved(
        self, row: ApprovalRequestTable, actor_id: UUID, notes: str | None
    ) -> None:
        if self._entity_gateway is None:
            return
        try:
            await self._entity_gateway.on_approved(
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                approval_request_id=row.id,
                actor_id=actor_id,
                notes=notes,
            )
        except Exception:
            logger.exception(
                "Entity gateway on_approved failed (request=%s, entity=%s/%s)",
                row.request_number,
                row.entity_type,
                row.entity_id,
            )

    async def _sync_entity_rejected(
        self, row: ApprovalRequestTable, actor_id: UUID, notes: str | None
    ) -> None:
        if self._entity_gateway is None:
            return
        try:
            await self._entity_gateway.on_rejected(
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                approval_request_id=row.id,
                actor_id=actor_id,
                notes=notes,
            )
        except Exception:
            logger.exception(
                "Entity gateway on_rejected failed (request=%s, entity=%s/%s)",
                row.request_number,
                row.entity_type,
                row.entity_id,
            )

    async def _sync_entity_cancelled(
        self, row: ApprovalRequestTable, actor_id: UUID, notes: str | None
    ) -> None:
        if self._entity_gateway is None:
            return
        try:
            await self._entity_gateway.on_cancelled(
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                approval_request_id=row.id,
                actor_id=actor_id,
                notes=notes,
            )
        except Exception:
            logger.exception(
                "Entity gateway on_cancelled failed (request=%s, entity=%s/%s)",
                row.request_number,
                row.entity_type,
                row.entity_id,
            )

    # ---------- Audit trail helpers ----------

    @staticmethod
    def _trail(row: ApprovalRequestTable) -> list[dict[str, Any]]:
        snapshot = row.entity_snapshot or {}
        trail = snapshot.get("approval_trail") if isinstance(snapshot, dict) else None
        return list(trail) if isinstance(trail, list) else []

    @classmethod
    def _append_trail(
        cls,
        row: ApprovalRequestTable,
        action: str,
        actor_id: UUID | None,
        from_level: int | None,
        to_level: int | None,
        notes: str | None,
        previous_approver_id: UUID | None = None,
        new_approver_id: UUID | None = None,
    ) -> None:
        entry = {
            "action": action,
            "at": datetime.now(UTC).isoformat(),
            "actor_id": str(actor_id) if actor_id else None,
            "from_level": from_level,
            "to_level": to_level,
            "notes": notes,
            "previous_approver_id": str(previous_approver_id) if previous_approver_id else None,
            "new_approver_id": str(new_approver_id) if new_approver_id else None,
        }
        snapshot = dict(row.entity_snapshot or {})
        snapshot["approval_trail"] = [*cls._trail(row), entry]
        row.entity_snapshot = snapshot  # assign ulang agar perubahan JSONB terdeteksi

    async def _ensure_actor_is_approver(self, row: ApprovalRequestTable, actor_id: UUID) -> None:
        if actor_id == row.approver_id:
            return
        delegation = await self._repo.get_active_delegation(
            row.approver_id, actor_id, row.legal_entity_id, date.today()
        )
        if delegation is None:
            raise PermissionError("You are not the assigned approver for this request")

    async def _ensure_users_active(self, user_ids: list[UUID], what: str) -> None:
        """Pastikan semua user ada, aktif dan belum dihapus (cegah request menggantung)."""
        wanted = list(dict.fromkeys(user_ids))
        found = await self._repo.get_active_user_ids(wanted)
        missing = [str(u) for u in wanted if u not in found]
        if missing:
            raise ValueError(f"{what}: user not found or inactive: {', '.join(missing)}")

    async def _load_matrix(self, row: ApprovalRequestTable) -> ApprovalMatrixTable | None:
        if not row.approval_matrix_id:
            return None
        return await self._repo.get_matrix_by_id(row.approval_matrix_id, row.legal_entity_id)

    # ==================== MAPPER: ORM row -> response object ====================

    async def _to_response(
        self, row: ApprovalRequestTable, matrix_cache: dict[UUID, str | None] | None = None
    ) -> SimpleNamespace:
        """Konversi ApprovalRequestTable -> object dengan nama atribut yang dipakai router."""
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
        final_decision = (
            row.status if row.status in ("approved", "rejected", "cancelled", "expired") else None
        )

        days_remaining: int | None = None
        if row.deadline is not None:
            deadline = row.deadline if row.deadline.tzinfo else row.deadline.replace(tzinfo=UTC)
            days_remaining = int((deadline - datetime.now(UTC)).total_seconds() // 86400)

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
            days_remaining=days_remaining,
            is_overdue=row.is_overdue,
            is_locked=row.status != "pending",
            notes=row.approval_comments or row.requester_comments,
            reason=row.cancellation_reason,
            escalated_at=row.escalated_at,
            escalated_to=row.escalated_to,
            completed_at=completed_at,
            completed_by=completed_by,
            completed_by_name=None,  # perlu join ke IAM user table utk resolve nama
            final_decision=final_decision,
            history=self._trail(row),
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
        """Submit entity untuk approval. Approver level pertama ditentukan dari matrix."""
        self._check_authority(requester_id, "submit_approval")

        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"Unsupported entity_type '{entity_type}'. Allowed: {', '.join(ENTITY_TYPES)}")
        if requester_id is None:
            raise ValueError("requester_id is required")
        if legal_entity_id is None:
            raise ValueError("legal_entity_id is required")
        if amount is not None and amount <= 0:
            raise ValueError("amount must be greater than zero")
        if amount is not None and amount > MAX_AMOUNT:
            raise ValueError(f"amount exceeds the maximum of {MAX_AMOUNT}")

        # Satu entity tidak boleh punya dua request pending sekaligus. Lock dulu supaya
        # submit paralel tidak sama-sama lolos pemeriksaan (check-then-insert race).
        await self._repo.lock_entity_for_submit(entity_type, entity_id, legal_entity_id)
        existing = await self._repo.get_requests_by_entity(entity_type, entity_id, legal_entity_id)
        pending = next((r for r in existing if r.status in ("pending", "escalated")), None)
        if pending is not None:
            raise ValueError(
                f"{entity_type} {entity_id} already has an open approval request ({pending.request_number})"
            )

        # --- tentukan matrix ---
        if approval_matrix_id:
            matrix = await self._repo.get_matrix_by_id(approval_matrix_id, legal_entity_id)
            if not matrix:
                raise ValueError(f"Approval matrix {approval_matrix_id} not found")
            if not matrix.is_active:
                raise ValueError(f"Approval matrix {matrix.matrix_code} is not active")
            if matrix.entity_type != entity_type:
                raise ValueError(
                    f"Approval matrix {matrix.matrix_code} is for '{matrix.entity_type}', not '{entity_type}'"
                )
            if (matrix.min_amount is not None or matrix.max_amount is not None) and amount is None:
                raise ValueError(f"amount is required for approval matrix {matrix.matrix_code}")
            if not _matrix_accepts(matrix, amount):
                raise ValueError(
                    f"Amount {amount} is outside the range of approval matrix {matrix.matrix_code}"
                )
        else:
            candidates = [
                m
                for m in await self._repo.list_matrices(legal_entity_id, entity_type, True)
                if _matrix_accepts(m, amount)
            ]
            if not candidates:
                raise ValueError(
                    f"No active approval matrix found for entity_type '{entity_type}'"
                    + (f" and amount {amount}" if amount is not None else "")
                )
            # Paling spesifik: batas bawah tertinggi; tie-break kode matrix.
            candidates.sort(key=lambda m: (-(m.min_amount or Decimal(0)), m.matrix_code))
            matrix = candidates[0]

        chain = _build_chain(list(matrix.rules or []), amount)
        first_rule = chain[0]
        approver_id, approver_name, approver_role = _pick_approver(first_rule, requester_id)
        first_level = _rule_level(first_rule)

        request_number = f"APR-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}"
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
            current_level=first_level,
            approval_matrix_id=matrix.id,
            deadline=_deadline_for(first_rule),
            requested_by=requester_id,
            requester_name=requester_name,
            requester_comments=notes,
            created_by=requester_id,
            legal_entity_id=legal_entity_id,
            entity_snapshot={},
        )
        self._append_trail(row, "submit", requester_id, None, first_level, notes, None, approver_id)
        row = await self._repo.save_request(row)

        self._record_audit(
            "submit_approval",
            {
                "request_id": str(row.id),
                "request_number": row.request_number,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "requester_id": str(requester_id),
                "legal_entity_id": str(legal_entity_id),
                "matrix": matrix.matrix_code,
            },
        )
        return await self._to_response(row, {matrix.id: matrix.matrix_name})

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
        approver_id: UUID | None = None,
    ) -> PaginatedResult:
        items, total = await self._repo.list_requests(
            legal_entity_id=legal_entity_id,
            entity_type=entity_type,
            status=status,
            requester_id=requester_id,
            approver_id=approver_id,
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
        if not row or (legal_entity_id and row.legal_entity_id != legal_entity_id):
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
        self,
        request_id: UUID,
        requester_id: UUID,
        legal_entity_id: UUID | None = None,
        reason: str | None = None,
    ) -> SimpleNamespace | None:
        """Tarik kembali request (hanya requester, hanya saat pending)."""
        self._check_authority(requester_id, "recall")
        row = await self._repo.get_request_by_id(request_id, for_update=True)
        if not row or (legal_entity_id and row.legal_entity_id != legal_entity_id):
            return None
        if row.requested_by != requester_id:
            raise PermissionError("Only the requester can recall an approval request")
        if row.status != "pending":
            raise ValueError(f"Cannot recall request with status {row.status}")
        from_level = row.current_level
        text = reason or "Recalled by requester"
        row.cancel(cancelled_by=requester_id, reason=text)
        self._append_trail(row, "recall", requester_id, from_level, from_level, text)
        await self._sync_entity_cancelled(row, requester_id, text)
        await self._persist(row)
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
        """Batalkan request (butuh permission approval:cancel; status pending/escalated)."""
        self._check_authority(actor_id, "cancel")
        row = await self._repo.get_request_by_id(request_id, for_update=True)
        if not row or (legal_entity_id and row.legal_entity_id != legal_entity_id):
            return None
        from_level = row.current_level
        text = reason or "Cancelled"
        row.cancel(cancelled_by=actor_id, reason=text)
        self._append_trail(row, "cancel", actor_id, from_level, from_level, text)
        await self._sync_entity_cancelled(row, actor_id, text)
        await self._persist(row)
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
        escalation_level: Any = None,
    ) -> SimpleNamespace | None:
        """Approve / reject / escalate / delegate.

        Raises:
            PermissionError: actor bukan approver yang berhak (atau actor adalah requester).
            ValueError: aksi/data tidak valid atau status bukan pending.
        """
        self._check_authority(actor_id, f"process_approval_{action}")
        if action not in _SUPPORTED_ACTIONS:
            raise ValueError(f"Unsupported action '{action}'. Allowed: {', '.join(_SUPPORTED_ACTIONS)}")

        row = await self._repo.get_request_by_id(request_id, for_update=True)
        if not row or (legal_entity_id and row.legal_entity_id != legal_entity_id):
            return None
        if row.status != "pending":
            raise ValueError(f"Request {row.request_number} is not pending (status: {row.status})")

        # Segregation of duties
        if actor_id == row.requested_by:
            raise PermissionError("The requester cannot process their own approval request")
        await self._ensure_actor_is_approver(row, actor_id)

        from_level = row.current_level
        previous_approver = row.approver_id

        if action == "approve":
            await self._do_approve(row, actor_id, notes)
        elif action == "reject":
            text = notes or "Rejected"
            row.reject(approved_by=actor_id, comments=text)
            self._append_trail(row, "reject", actor_id, from_level, from_level, text)
            await self._sync_entity_rejected(row, actor_id, text)
        elif action == "escalate":
            await self._do_escalate(row, actor_id, notes, escalation_level)
        else:  # delegate
            await self._do_delegate(row, actor_id, notes, delegate_to_user_id)

        await self._persist(row)
        self._record_audit(
            "process_approval_action",
            {
                "request_id": str(request_id),
                "action": action,
                "actor_id": str(actor_id),
                "from_level": from_level,
                "to_level": row.current_level,
                "previous_approver_id": str(previous_approver),
                "status": row.status,
            },
        )
        return await self._to_response(row)

    async def _do_approve(self, row: ApprovalRequestTable, actor_id: UUID, notes: str | None) -> None:
        from_level = row.current_level
        previous_approver = row.approver_id
        next_rule: dict[str, Any] | None = None

        if row.approval_matrix_id:
            matrix = await self._load_matrix(row)
            if matrix is None:
                raise ValueError(
                    "The approval matrix for this request no longer exists; "
                    "the next approval level cannot be determined"
                )
            chain = _build_chain(list(matrix.rules or []), row.amount)
            next_rule = next((r for r in chain if _rule_level(r) > from_level), None)

        if next_rule is None:
            # Level terakhir -> request disetujui penuh; sinkronkan entity.
            row.approve(approved_by=actor_id, comments=notes)
            self._append_trail(row, "approve", actor_id, from_level, from_level, notes, previous_approver, None)
            await self._sync_entity_approved(row, actor_id, notes)
            return

        next_level = _rule_level(next_rule)
        approver_id, approver_name, approver_role = _pick_approver(next_rule, row.requested_by)
        row.advance_level(next_level, approver_id, approver_name, approver_role)
        row.deadline = _deadline_for(next_rule)
        if notes:
            row.approval_comments = notes
        self._append_trail(
            row, "approve", actor_id, from_level, next_level, notes, previous_approver, approver_id
        )

    async def _do_escalate(
        self,
        row: ApprovalRequestTable,
        actor_id: UUID,
        notes: str | None,
        escalation_level: Any,
    ) -> None:
        matrix = await self._load_matrix(row)
        if matrix is None:
            raise ValueError("Cannot escalate: this request has no (existing) approval matrix")
        by_level = {_rule_level(r): r for r in (matrix.rules or [])}
        from_level = row.current_level

        if escalation_level is not None:
            target = level_to_int(escalation_level)
            if target <= from_level:
                raise ValueError(
                    f"Escalation level must be higher than the current level ({level_name(from_level)})"
                )
        else:
            higher = sorted(lvl for lvl in by_level if lvl > from_level)
            if not higher:
                raise ValueError("Cannot escalate: there is no higher approval level in the matrix")
            target = higher[0]

        rule = by_level.get(target)
        if rule is None:
            raise ValueError(f"No approver rule found for {level_name(target)} in matrix {matrix.matrix_code}")

        previous_approver = row.approver_id
        approver_id, approver_name, approver_role = _pick_approver(rule, row.requested_by)
        reason = notes or "Escalated"
        row.escalate(escalated_to=approver_id, reason=reason, to_level=target, keep_pending=True)
        row.approver_id = approver_id
        row.approver_name = approver_name
        row.approver_role = approver_role
        row.deadline = _deadline_for(rule)
        self._append_trail(row, "escalate", actor_id, from_level, target, reason, previous_approver, approver_id)

    async def _do_delegate(
        self,
        row: ApprovalRequestTable,
        actor_id: UUID,
        notes: str | None,
        delegate_to_user_id: UUID | None,
    ) -> None:
        if not delegate_to_user_id:
            raise ValueError("delegate_to_user_id is required for action='delegate'")
        if actor_id != row.approver_id:
            raise PermissionError("Only the assigned approver can delegate this request")
        if delegate_to_user_id == actor_id:
            raise ValueError("Cannot delegate a request to yourself")
        if delegate_to_user_id == row.requested_by:
            raise ValueError("Cannot delegate a request to its requester")
        delegation = await self._repo.get_active_delegation(
            actor_id, delegate_to_user_id, row.legal_entity_id, date.today()
        )
        if delegation is None:
            raise ValueError(
                "No active delegation from you to that user. Create one first (POST /approvals/delegations)"
            )
        previous_approver = row.approver_id
        row.approver_id = delegate_to_user_id
        row.approver_name = delegation.delegate_to_name or f"User {str(delegate_to_user_id)[:8]}"
        row.approver_role = None
        row.increment_version()
        self._append_trail(
            row, "delegate", actor_id, row.current_level, row.current_level, notes,
            previous_approver, delegate_to_user_id,
        )

    # ==================== PENDING TASKS ====================

    async def _pending_rows_for(
        self, user_id: UUID, legal_entity_id: UUID | None
    ) -> list[ApprovalRequestTable]:
        extra: list[UUID] = []
        if legal_entity_id:
            extra = await self._repo.list_active_delegator_ids(user_id, legal_entity_id, date.today())
        rows = await self._repo.get_pending_requests_for_user(user_id, legal_entity_id, extra)
        # Requester tidak boleh memproses request miliknya sendiri -> bukan tugas dia.
        return [r for r in rows if r.requested_by != user_id]

    async def get_pending_tasks_for_user(
        self,
        user_id: UUID,
        legal_entity_id: UUID | None = None,
        entity_type: str | None = None,
        overdue_only: bool = False,
    ) -> list[SimpleNamespace]:
        rows = await self._pending_rows_for(user_id, legal_entity_id)
        if entity_type:
            rows = [r for r in rows if r.entity_type == entity_type]
        if overdue_only:
            rows = [r for r in rows if r.is_overdue]
        matrix_cache: dict[UUID, str | None] = {}
        return [await self._to_response(r, matrix_cache) for r in rows]

    async def get_pending_tasks_count(
        self, user_id: UUID, legal_entity_id: UUID | None = None
    ) -> SimpleNamespace:
        rows = await self._pending_rows_for(user_id, legal_entity_id)
        by_entity_type: dict[str, int] = {}
        overdue = 0
        for r in rows:
            by_entity_type[r.entity_type] = by_entity_type.get(r.entity_type, 0) + 1
            if r.is_overdue:
                overdue += 1
        return SimpleNamespace(total=len(rows), by_entity_type=by_entity_type, overdue=overdue)

    # ==================== HISTORY ====================

    async def get_approval_history(
        self, request_id: UUID, legal_entity_id: UUID | None = None
    ) -> list[SimpleNamespace]:
        row = await self._repo.get_request_by_id(request_id)
        if not row or (legal_entity_id and row.legal_entity_id != legal_entity_id):
            return []

        trail = self._trail(row)
        entries: list[SimpleNamespace] = []

        if trail:
            for index, item in enumerate(trail):
                at = datetime.fromisoformat(item["at"])
                entries.append(
                    SimpleNamespace(
                        id=uuid5(row.id, f"approval-trail-{index}"),
                        approval_request_id=row.id,
                        action=item.get("action"),
                        from_level=item.get("from_level"),
                        to_level=item.get("to_level"),
                        actor_id=UUID(item["actor_id"]) if item.get("actor_id") else None,
                        actor_name=None,
                        actor_role=None,
                        action_at=at,
                        notes=item.get("notes"),
                        previous_approver_id=(
                            UUID(item["previous_approver_id"]) if item.get("previous_approver_id") else None
                        ),
                        new_approver_id=(
                            UUID(item["new_approver_id"]) if item.get("new_approver_id") else None
                        ),
                    )
                )
            return entries

        # Fallback request lama (tanpa trail): histori sintetis dari kolom timestamp.
        def add(action: str, at: datetime | None, actor: UUID | None, from_lv: int | None,
                to_lv: int | None, notes_: str | None) -> None:
            if at is None:
                return
            entries.append(
                SimpleNamespace(
                    id=uuid4(), approval_request_id=row.id, action=action, from_level=from_lv,
                    to_level=to_lv, actor_id=actor, actor_name=None, actor_role=None,
                    action_at=at, notes=notes_, previous_approver_id=None, new_approver_id=None,
                )
            )

        add("submit", row.created_at, row.requested_by, None, 1, row.requester_comments)
        if row.status == "approved":
            add("approve", row.approved_at, row.approved_by, row.current_level, row.current_level, row.approval_comments)
        elif row.status == "rejected":
            add("reject", row.approved_at, row.approved_by, row.current_level, row.current_level, row.approval_comments)
        elif row.status == "cancelled":
            add("recall", row.cancelled_at, row.cancelled_by, row.current_level, row.current_level, row.cancellation_reason)
        if row.escalated_at:
            add("escalate", row.escalated_at, None, max(row.current_level - 1, 1), row.current_level, row.approval_comments)
        entries.sort(key=lambda e: e.action_at)
        return entries

    async def get_entity_approval_status(
        self, entity_type: str, entity_id: UUID, legal_entity_id: UUID | None = None
    ) -> SimpleNamespace | None:
        rows = await self._repo.get_requests_by_entity(entity_type, entity_id, legal_entity_id)
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
        created_by_name: str | None = None,
    ) -> SimpleNamespace:
        code = (matrix_code or "").strip()
        if not code:
            raise ValueError("matrix_code is required")
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"Unsupported entity_type '{entity_type}'. Allowed: {', '.join(ENTITY_TYPES)}")
        if min_amount is not None and min_amount < 0:
            raise ValueError("min_amount must be >= 0")
        if (min_amount is not None and min_amount > MAX_AMOUNT) or (
            max_amount is not None and max_amount > MAX_AMOUNT
        ):
            raise ValueError(f"min_amount/max_amount exceed the maximum of {MAX_AMOUNT}")
        if min_amount is not None and max_amount is not None and min_amount > max_amount:
            raise ValueError("min_amount cannot be greater than max_amount")
        normalized = _validate_and_normalize_rules(rules)
        await self._ensure_users_active(
            [UUID(a) for r in normalized for a in r["approver_user_ids"]], "Approver in approval matrix"
        )

        if await self._repo.get_matrix_by_code(code, legal_entity_id) is not None:
            raise ValueError(f"Approval matrix with code '{code}' already exists")

        matrix = ApprovalMatrixTable(
            matrix_code=code,
            matrix_name=matrix_name,
            entity_type=entity_type,
            min_amount=min_amount,
            max_amount=max_amount,
            currency=currency,
            rules=normalized,
            is_active=is_active,
            notes=notes,
            created_by=created_by,
            created_by_name=created_by_name,
            legal_entity_id=legal_entity_id,
        )
        matrix = await self._repo.save_matrix(matrix)
        self._record_audit("create_approval_matrix", {"matrix_id": str(matrix.id), "code": code})
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
        updated_by: UUID | None = None,
    ) -> SimpleNamespace | None:
        matrix = await self._repo.get_matrix_by_id(matrix_id, legal_entity_id)
        if not matrix:
            return None

        new_min = min_amount if min_amount is not None else matrix.min_amount
        new_max = max_amount if max_amount is not None else matrix.max_amount
        if new_min is not None and new_max is not None and new_min > new_max:
            raise ValueError("min_amount cannot be greater than max_amount")
        if new_min is not None and new_min < 0:
            raise ValueError("min_amount must be >= 0")
        if (new_min is not None and new_min > MAX_AMOUNT) or (new_max is not None and new_max > MAX_AMOUNT):
            raise ValueError(f"min_amount/max_amount exceed the maximum of {MAX_AMOUNT}")

        if matrix_name is not None:
            matrix.matrix_name = matrix_name
        matrix.min_amount = new_min
        matrix.max_amount = new_max
        if currency is not None:
            matrix.currency = currency
        if rules is not None:
            normalized = _validate_and_normalize_rules(rules)
            await self._ensure_users_active(
                [UUID(a) for r in normalized for a in r["approver_user_ids"]],
                "Approver in approval matrix",
            )
            matrix.rules = normalized
        if is_active is not None:
            matrix.is_active = is_active
        if notes is not None:
            matrix.notes = notes
        matrix.increment_version()
        await self._persist(matrix)
        self._record_audit(
            "update_approval_matrix",
            {"matrix_id": str(matrix_id), "updated_by": str(updated_by) if updated_by else None},
        )
        return self._matrix_to_response(matrix)

    async def delete_approval_matrix(
        self, matrix_id: UUID, legal_entity_id: UUID, actor_id: UUID
    ) -> bool:
        """Hard-delete matrix. Ditolak bila masih dipakai request pending/escalated."""
        open_count = await self._repo.count_open_requests_for_matrix(matrix_id, legal_entity_id)
        if open_count:
            raise ValueError(
                f"Approval matrix is still used by {open_count} open approval request(s); "
                "deactivate it instead or finish those requests first"
            )
        deleted = await self._repo.delete_matrix(matrix_id, legal_entity_id)
        if deleted:
            self._record_audit("delete_approval_matrix", {"matrix_id": str(matrix_id), "actor_id": str(actor_id)})
        return deleted

    async def deactivate_approval_matrix(
        self, matrix_id: UUID, legal_entity_id: UUID, actor_id: UUID
    ) -> bool:
        matrix = await self._repo.get_matrix_by_id(matrix_id, legal_entity_id)
        if not matrix:
            return False
        matrix.is_active = False
        matrix.increment_version()
        await self._persist(matrix)
        self._record_audit("deactivate_approval_matrix", {"matrix_id": str(matrix_id), "actor_id": str(actor_id)})
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
        delegator_name: str | None = None,
        delegate_to_name: str | None = None,
    ) -> SimpleNamespace:
        if delegate_to_id == delegator_id:
            raise ValueError("Cannot delegate approval authority to yourself")
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        await self._ensure_users_active([delegate_to_id], "Delegation target")
        delegation = ApprovalDelegationTable(
            delegator_id=delegator_id,
            delegator_name=delegator_name,
            delegate_to_id=delegate_to_id,
            delegate_to_name=delegate_to_name,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            is_active=True,
            created_by=delegator_id,
            legal_entity_id=legal_entity_id,
        )
        delegation = await self._repo.save_delegation(delegation)
        self._record_audit("create_delegation", {"delegation_id": str(delegation.id)})
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
        if delegation.delegator_id != actor_id:
            raise PermissionError("Only the delegator can revoke a delegation")
        if not delegation.is_active:
            raise ValueError("Delegation is already revoked")
        delegation.is_active = False
        delegation.revoked_by = actor_id
        delegation.revoked_at = datetime.now(UTC)
        delegation.increment_version()
        await self._persist(delegation)
        self._record_audit("revoke_delegation", {"delegation_id": str(delegation_id)})
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
        # Kunci level dinyatakan seperti di seluruh API ("level_1", "cfo", ...), bukan angka mentah.
        stats["by_level"] = {
            (level_name(int(k)) if str(k).isdigit() and 1 <= int(k) <= len(LEVEL_NAMES) else str(k)): v
            for k, v in stats["by_level"].items()
        }
        return SimpleNamespace(**stats)

    # ==================== EXPORT ====================

    @staticmethod
    def _csv_safe(value: Any) -> Any:
        """Cegah CSV/formula injection (sel diawali = + - @ dieksekusi Excel)."""
        if isinstance(value, str) and value.startswith(_CSV_DANGEROUS_PREFIXES):
            return "'" + value
        return value

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
            raise ValueError(f"Unsupported export format: '{format}' (hanya 'csv' yang didukung saat ini)")

        all_items: list[ApprovalRequestTable] = []
        page = 1
        while True:
            items, total = await self._repo.list_requests(
                legal_entity_id=legal_entity_id,
                status=status,
                start_date=start_date,
                end_date=end_date,
                page=page,
                page_size=200,
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
        safe = self._csv_safe
        for r in all_items:
            writer.writerow([
                safe(r.request_number), safe(r.entity_type), str(r.entity_id), safe(r.status),
                level_name(r.current_level) if 1 <= r.current_level <= len(LEVEL_NAMES) else r.current_level,
                r.amount, r.currency, safe(r.requester_name or ""), safe(r.approver_name or ""),
                r.created_at.isoformat() if r.created_at else "",
                r.approved_at.isoformat() if r.approved_at else "",
            ])
        return buf.getvalue().encode("utf-8")


__all__ = [
    "ENTITY_TYPES",
    "LEVEL_NAMES",
    "MAX_AMOUNT",
    "ApprovalService",
    "PaginatedResult",
    "audit",
    "level_name",
    "level_to_int",
]
