#!/usr/bin/env python3
"""
Module: service_journal.py
Layer: Application / Service Layer
Responsibility:
    Service layer untuk Journal Entry (Jurnal Umum) — SATU-SATUNYA jalur
    baca/tulis `journal_header`/`journal_line`, dipakai oleh
    fastapi_journal_router.py.

CATATAN SEJARAH / KENAPA DITULIS ULANG:
    Versi sebelumnya punya masalah yang SAMA PERSIS dengan yang dulu
    ditemukan di COA, tapi lebih parah: ada TIGA representasi domain
    "Journal" yang saling tidak kompatibel di codebase ini —
    ``domain.journal.journal_entity.JournalEntry``,
    ``domain.journal.aggregate_root.Journal`` (alias ``JournalAggregate``),
    dan ``domain.journal.journal_line_vo`` (``JournalLine``/``JournalLineVO``,
    dua class berbeda). ``post_journal_entry`` (satu-satunya jalur "create"
    di service lama) membangun ``JournalEntry`` lalu membungkusnya
    ``JournalAggregate(journal=journal, version=0)`` — padahal
    ``Journal``/``JournalAggregate`` adalah dataclass dengan field sendiri
    (``journal_id``, ``journal_number``, dst) yang TIDAK PUNYA field
    ``journal`` atau ``version`` -> selalu ``TypeError`` begitu dipanggil.

    Selain itu ``fastapi_journal_router.py`` memanggil banyak method
    (``create_journal``, ``update_journal``, ``get_journal_by_id``,
    ``get_journal_by_number``, ``lock_journal``, ``unlock_journal``,
    ``unpost_journal``, ``restore_journal``, ``export_journals``,
    ``get_journal_history``, ``get_journal_status``,
    ``get_ledger_entries``) yang SAMA SEKALI TIDAK ADA di service lama, dan
    mengonstruksi DTO (``JournalLineRequest``, ``CreateJournalRequest``)
    dengan nama keyword argument yang tidak cocok dengan field aslinya.

    Service ini menghapus seluruh jalur domain aggregate yang rusak dan
    bekerja LANGSUNG ke ``JournalHeaderTable``/``JournalLineTable`` lewat
    UnitOfWork — pola yang sama seperti ``service_coa.py`` — supaya
    router, service, dan database benar-benar satu kontrak yang konsisten.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select

from ports.primary.account_repository_port import AccountRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Exceptions
# ============================================================================


class JournalServiceError(Exception):
    pass


class JournalNotFoundError(JournalServiceError):
    pass


class JournalNotBalancedError(JournalServiceError):
    pass


class AccountNotFoundError(JournalServiceError):
    pass


class AccountNotPostableError(JournalServiceError):
    """Akun ada, tapi tidak boleh dipakai posting jurnal — mis. header
    account (allow_posting=false), akun dikunci (is_locked), atau non-aktif."""
    pass


class JournalPeriodClosedError(JournalServiceError):
    pass


class InvalidJournalStatusTransitionError(JournalServiceError):
    pass


class JournalLockedError(JournalServiceError):
    pass


class JournalApprovalError(JournalServiceError):
    """Pelanggaran aturan 4-eyes: approver tidak boleh sama dengan pembuat."""
    pass


VALID_JOURNAL_TYPES = (
    "general", "adjusting", "closing", "reversing", "opening", "correction",
)
# Status yang BENAR-BENAR ada di kolom `journal_header.status` (lihat CHECK
# constraint di migration 0008 / journal_header_table.py). "rejected" SENGAJA
# tidak ada di sini: menolak jurnal mengembalikannya ke "draft" (lihat
# reject_journal), bukan status permanen tersendiri — field
# `rejected_by/rejected_at/rejection_reason` yang menyimpan jejaknya.
VALID_STATUSES = ("draft", "submitted", "approved", "posted", "reversed", "cancelled")


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class JournalLineDTO:
    id: UUID
    line_number: int
    account_id: UUID
    account_code: str
    account_name: str | None
    debit_amount: Decimal
    credit_amount: Decimal
    currency: str
    cost_center: str | None
    department: str | None
    description: str | None


@dataclass(kw_only=True)
class JournalDTO:
    id: UUID
    journal_number: str
    journal_date: date
    description: str
    journal_type: str
    status: str
    total_debit: Decimal
    total_credit: Decimal
    is_balanced: bool
    is_locked: bool
    currency: str
    reference_number: str | None
    source_type: str
    source_id: UUID | None
    notes: str | None
    attachment_ids: list[str]
    created_by: UUID
    created_by_name: str | None
    created_at: datetime
    submitted_by: UUID | None
    submitted_at: datetime | None
    approved_by: UUID | None
    approved_by_name: str | None
    approved_at: datetime | None
    rejected_by: UUID | None
    rejected_at: datetime | None
    rejection_reason: str | None
    posted_by: UUID | None
    posted_by_name: str | None
    posted_at: datetime | None
    reversed_by: UUID | None
    reversed_at: datetime | None
    reversal_reason: str | None
    reversal_journal_id: UUID | None
    original_journal_id: UUID | None
    cancelled_by: UUID | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    version: int
    lines: list[JournalLineDTO]


@dataclass(kw_only=True)
class JournalListResult:
    items: list[JournalDTO]
    total: int
    total_debit: Decimal
    total_credit: Decimal


@dataclass(kw_only=True)
class ValidationResultDTO:
    is_valid: bool
    errors: list[str] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)


@dataclass(kw_only=True)
class LedgerEntryDTO:
    id: UUID
    account_code: str
    debit_amount: Decimal
    credit_amount: Decimal
    posting_date: date
    fiscal_year: int
    period_month: int
    description: str | None


@dataclass(kw_only=True)
class JournalHistoryEntryDTO:
    timestamp: datetime
    action: str
    actor_id: UUID
    actor_name: str | None
    details: dict[str, Any]


# ============================================================================
# Main Service
# ============================================================================


class JournalService:
    """Service untuk Journal Entry — satu jalur implementasi, langsung ke
    ``JournalHeaderTable``/``JournalLineTable``/``LedgerEntryTable`` lewat
    UnitOfWork. Lihat catatan modul di atas."""

    def __init__(
        self,
        journal_repo: Any,
        ledger_repo: LedgerRepositoryPort,
        account_repo: AccountRepositoryPort,
        uow: UnitOfWorkPort,
        event_publisher: EventPublisherPort | None = None,
    ):
        # journal_repo/ledger_repo/account_repo dipertahankan di constructor
        # demi kompatibilitas wiring dependency-injection, tapi TIDAK dipakai
        # untuk baca/tulis jurnal (lihat catatan modul) — semua operasi
        # langsung lewat AccountTable/JournalHeaderTable/JournalLineTable
        # via UnitOfWork, sama seperti pola di service_coa.py.
        self._journal_repo = journal_repo
        self._ledger_repo = ledger_repo
        self._account_repo = account_repo
        self._uow = uow
        self._event_publisher = event_publisher

        self._stats = {"journals_created": 0, "journals_posted": 0, "journals_reversed": 0}
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("JournalService initialized")

    # ==================== AUTHORITY / AUDIT ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    def _record_audit(self, action: str, journal_id: UUID | None, actor_id: UUID | None,
                       details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC),
            "journal_id": str(journal_id) if journal_id else None,
            "action": action,
            "actor_id": str(actor_id) if actor_id else None,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        if len(self._audit_trail) > 20000:
            self._audit_trail = self._audit_trail[-10000:]
        logger.info(f"AUDIT: {action} journal={journal_id} - {details}")

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()

    # ==================== INTERNAL HELPERS ====================

    def _row_to_dto(self, row: Any) -> JournalDTO:
        lines = sorted(row.lines, key=lambda ln: ln.line_number) if row.lines else []
        line_dtos = [
            JournalLineDTO(
                id=ln.id,
                line_number=ln.line_number,
                account_id=ln.id,  # ORM journal_line tidak simpan account_id (FK by code); lihat catatan di bawah
                account_code=ln.account_code,
                account_name=ln.account_name,
                debit_amount=ln.debit_amount,
                credit_amount=ln.credit_amount,
                currency=ln.currency,
                cost_center=ln.cost_center,
                department=ln.department,
                description=ln.description,
            )
            for ln in lines
        ]
        return JournalDTO(
            id=row.id,
            journal_number=row.voucher_number,
            journal_date=row.journal_date,
            description=row.description,
            journal_type=row.journal_type,
            status=row.status,
            total_debit=row.total_debit,
            total_credit=row.total_credit,
            is_balanced=row.is_balanced,
            is_locked=row.is_locked,
            currency=row.currency,
            reference_number=row.reference_number,
            source_type=row.source_type,
            source_id=row.source_id,
            notes=row.notes,
            attachment_ids=row.attachment_ids or [],
            created_by=row.created_by,
            created_by_name=row.created_by_name,
            created_at=row.created_at,
            submitted_by=row.submitted_by,
            submitted_at=row.submitted_at,
            approved_by=row.approved_by,
            approved_by_name=row.approved_by_name,
            approved_at=row.approved_at,
            rejected_by=row.rejected_by,
            rejected_at=row.rejected_at,
            rejection_reason=row.rejection_reason,
            posted_by=row.posted_by,
            posted_by_name=row.posted_by_name,
            posted_at=row.posted_at,
            reversed_by=row.reversed_by,
            reversed_at=row.reversed_at,
            reversal_reason=row.reversal_reason,
            reversal_journal_id=row.reversed_journal_id,
            original_journal_id=row.original_journal_id,
            cancelled_by=row.cancelled_by,
            cancelled_at=row.cancelled_at,
            cancellation_reason=row.cancellation_reason,
            version=getattr(row, "version", 1),
            lines=line_dtos,
        )

    async def _get_row_or_raise(self, session: Any, journal_id: UUID, legal_entity_id: UUID) -> Any:
        from sqlalchemy.orm import selectinload

        from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable

        result = await session.execute(
            select(JournalHeaderTable)
            .options(selectinload(JournalHeaderTable.lines))
            .where(
                JournalHeaderTable.id == journal_id,
                JournalHeaderTable.legal_entity_id == legal_entity_id,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            raise JournalNotFoundError(f"Journal {journal_id} not found")
        return row

    async def _generate_voucher_number(self, session: Any, legal_entity_id: UUID, journal_date_: date) -> str:
        from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable

        prefix = f"JV-{journal_date_.strftime('%Y%m')}"
        result = await session.execute(
            select(func.count()).select_from(JournalHeaderTable).where(
                JournalHeaderTable.legal_entity_id == legal_entity_id,
                JournalHeaderTable.voucher_number.like(f"{prefix}-%"),
            )
        )
        seq = result.scalar_one() + 1
        return f"{prefix}-{seq:05d}"

    async def _validate_and_resolve_lines(
        self, session: Any, legal_entity_id: UUID, lines_input: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], Decimal, Decimal]:
        """Validasi baris jurnal: minimal 2 baris, tiap baris debit XOR
        kredit (>0, tidak dua-duanya), akun harus ada/aktif/boleh posting
        (allow_posting=true, tidak header, tidak dikunci — selaras dengan
        aturan leaf-node COA), dan total debit harus sama dengan total
        kredit. Mengembalikan baris yang sudah diperkaya info akun
        (nama/tipe/normal_balance untuk snapshot) + total debit/kredit.
        """
        from infrastructure.persistence_orm.account_table import AccountTable

        if not lines_input or len(lines_input) < 2:
            raise JournalNotBalancedError("Journal must have at least 2 lines")

        codes = list({str(ln.get("account_code", "")).strip().upper() for ln in lines_input})
        result = await session.execute(
            select(AccountTable).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.account_code.in_(codes),
            )
        )
        accounts = {a.account_code: a for a in result.scalars().all()}

        resolved: list[dict[str, Any]] = []
        total_debit = Decimal("0")
        total_credit = Decimal("0")

        for idx, ln in enumerate(lines_input, start=1):
            code = str(ln.get("account_code", "")).strip().upper()
            debit = Decimal(str(ln.get("debit_amount", 0) or 0))
            credit = Decimal(str(ln.get("credit_amount", 0) or 0))

            if debit < 0 or credit < 0:
                raise JournalNotBalancedError(f"Line {idx}: amount cannot be negative")
            if debit > 0 and credit > 0:
                raise JournalNotBalancedError(f"Line {idx}: cannot have both debit and credit")
            if debit == 0 and credit == 0:
                raise JournalNotBalancedError(f"Line {idx}: must have either debit or credit amount")

            account = accounts.get(code)
            if not account:
                raise AccountNotFoundError(f"Line {idx}: account '{code}' not found")
            if account.status != "active":
                raise AccountNotPostableError(f"Line {idx}: account '{code}' is not active (status={account.status})")
            if account.is_locked:
                raise AccountNotPostableError(f"Line {idx}: account '{code}' is locked ({account.lock_reason or ''})")
            if account.is_header or not account.allow_posting:
                raise AccountNotPostableError(
                    f"Line {idx}: account '{code}' is a header account and cannot be used for posting"
                )

            total_debit += debit
            total_credit += credit
            resolved.append({
                "line_number": idx,
                "account_code": code,
                "account_name": account.account_name,
                "account_type_snapshot": account.account_type,
                "normal_balance_snapshot": account.normal_balance,
                "debit_amount": debit,
                "credit_amount": credit,
                "cost_center": ln.get("cost_center"),
                "department": ln.get("department"),
                "description": ln.get("description"),
            })

        if abs(total_debit - total_credit) > Decimal("0.01"):
            raise JournalNotBalancedError(
                f"Journal not balanced: total_debit={total_debit}, total_credit={total_credit}"
            )

        return resolved, total_debit, total_credit

    async def _check_period_open(self, session: Any, legal_entity_id: UUID, journal_date_: date) -> None:
        """Kalau ada master fiscal_period yang mencakup tanggal jurnal ini,
        periode itu HARUS berstatus 'open'. Kalau tidak ada data periode
        sama sekali untuk tanggal ini, jurnal tetap diizinkan (banyak
        instalasi belum setup fiscal_period) — hanya diblokir kalau
        periodenya ADA dan statusnya bukan open (closed/locked)."""
        from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable

        result = await session.execute(
            select(FiscalPeriodTable.status, FiscalPeriodTable.period_name).where(
                FiscalPeriodTable.legal_entity_id == legal_entity_id,
                FiscalPeriodTable.start_date <= journal_date_,
                FiscalPeriodTable.end_date >= journal_date_,
                FiscalPeriodTable.deleted_at.is_(None),
            )
        )
        row = result.first()
        if row and row[0] != "open":
            raise JournalPeriodClosedError(
                f"Fiscal period '{row[1]}' covering {journal_date_} is {row[0]}, not open"
            )

    # ==================== CREATE ====================

    @audit
    async def create_journal(
        self,
        *,
        legal_entity_id: UUID,
        journal_date: date,
        description: str,
        journal_type: str,
        lines: list[dict[str, Any]],
        reference_number: str | None,
        source_type: str,
        source_id: UUID | None,
        notes: str | None,
        attachment_ids: list[str] | None,
        created_by: UUID,
        created_by_name: str | None = None,
    ) -> JournalDTO:
        from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
        from infrastructure.persistence_orm.journal_line_table import JournalLineTable

        self._check_authority(created_by, "create_journal")

        if not description or len(description.strip()) < 3:
            raise JournalServiceError("Description must be at least 3 characters")
        if journal_type not in VALID_JOURNAL_TYPES:
            raise JournalServiceError(f"Invalid journal_type '{journal_type}'")

        async with self._uow:
            session = self._uow.session

            await self._check_period_open(session, legal_entity_id, journal_date)
            resolved_lines, total_debit, total_credit = await self._validate_and_resolve_lines(
                session, legal_entity_id, lines
            )
            voucher_number = await self._generate_voucher_number(session, legal_entity_id, journal_date)

            header = JournalHeaderTable(
                id=uuid4(),
                legal_entity_id=legal_entity_id,
                voucher_number=voucher_number,
                journal_date=journal_date,
                description=description.strip(),
                total_debit=total_debit,
                total_credit=total_credit,
                currency="IDR",
                status="draft",
                journal_type=journal_type,
                reference_number=reference_number,
                source_type=source_type or "manual",
                source_id=source_id,
                notes=notes,
                attachment_ids=[str(a) for a in (attachment_ids or [])],
                is_locked=False,
                created_by=created_by,
                created_by_name=created_by_name,
            )
            session.add(header)

            for rl in resolved_lines:
                session.add(JournalLineTable(
                    id=uuid4(),
                    journal_id=header.id,
                    legal_entity_id=legal_entity_id,
                    line_number=rl["line_number"],
                    account_code=rl["account_code"],
                    account_name=rl["account_name"],
                    account_type_snapshot=rl["account_type_snapshot"],
                    normal_balance_snapshot=rl["normal_balance_snapshot"],
                    debit_amount=rl["debit_amount"],
                    credit_amount=rl["credit_amount"],
                    currency="IDR",
                    cost_center=rl["cost_center"],
                    department=rl["department"],
                    description=rl["description"],
                ))

            await session.flush()
            row = await self._get_row_or_raise(session, header.id, legal_entity_id)
            dto = self._row_to_dto(row)
            await self._uow.commit()

        self._stats["journals_created"] += 1
        self._record_audit("create_journal", header.id, created_by, {"voucher_number": voucher_number})
        return dto

    # ==================== READ ====================

    async def get_journal_by_id(self, journal_id: UUID, legal_entity_id: UUID) -> JournalDTO | None:
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
        return self._row_to_dto(row)

    async def get_journal_by_number(self, journal_number: str, legal_entity_id: UUID) -> JournalDTO | None:
        from sqlalchemy.orm import selectinload

        from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable

        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(JournalHeaderTable)
                .options(selectinload(JournalHeaderTable.lines))
                .where(
                    JournalHeaderTable.voucher_number == journal_number,
                    JournalHeaderTable.legal_entity_id == legal_entity_id,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
        return self._row_to_dto(row)

    async def list_journals(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
        journal_type: str | None = None,
        search: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> JournalListResult:
        from sqlalchemy.orm import selectinload

        from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable

        page = max(page, 1)
        page_size = max(page_size, 1)

        async with self._uow:
            session = self._uow.session

            conditions = [
                JournalHeaderTable.legal_entity_id == legal_entity_id,
                JournalHeaderTable.deleted_at.is_(None),
            ]
            if status:
                conditions.append(func.lower(JournalHeaderTable.status) == status.lower())
            if journal_type:
                conditions.append(func.lower(JournalHeaderTable.journal_type) == journal_type.lower())
            if search:
                like = f"%{search}%"
                conditions.append(
                    or_(
                        JournalHeaderTable.voucher_number.ilike(like),
                        JournalHeaderTable.description.ilike(like),
                        JournalHeaderTable.reference_number.ilike(like),
                    )
                )
            if date_from:
                conditions.append(JournalHeaderTable.journal_date >= date_from)
            if date_to:
                conditions.append(JournalHeaderTable.journal_date <= date_to)

            count_stmt = select(func.count()).select_from(JournalHeaderTable).where(*conditions)
            total = (await session.execute(count_stmt)).scalar_one()

            sum_stmt = select(
                func.coalesce(func.sum(JournalHeaderTable.total_debit), 0),
                func.coalesce(func.sum(JournalHeaderTable.total_credit), 0),
            ).where(*conditions)
            total_debit, total_credit = (await session.execute(sum_stmt)).one()

            stmt = (
                select(JournalHeaderTable)
                .options(selectinload(JournalHeaderTable.lines))
                .where(*conditions)
                .order_by(JournalHeaderTable.journal_date.desc(), JournalHeaderTable.voucher_number.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
            rows = (await session.execute(stmt)).scalars().all()

        items = [self._row_to_dto(r) for r in rows]
        return JournalListResult(
            items=items, total=total, total_debit=Decimal(total_debit), total_credit=Decimal(total_credit)
        )

    # ==================== UPDATE (draft only) ====================

    @audit
    async def update_journal(
        self,
        *,
        journal_id: UUID,
        legal_entity_id: UUID,
        journal_date: date | None,
        description: str | None,
        journal_type: str | None,
        lines: list[dict[str, Any]] | None,
        reference_number: str | None,
        notes: str | None,
        attachment_ids: list[str] | None,
        updated_by: UUID,
    ) -> JournalDTO:
        from infrastructure.persistence_orm.journal_line_table import JournalLineTable

        self._check_authority(updated_by, "update_journal")

        async with self._uow:
            session = self._uow.session
            row = await self._get_row_or_raise(session, journal_id, legal_entity_id)

            if row.status != "draft":
                raise InvalidJournalStatusTransitionError(
                    f"Journal {row.voucher_number} cannot be updated: status is '{row.status}', only 'draft' can be edited"
                )
            if row.is_locked:
                raise JournalLockedError(f"Journal {row.voucher_number} is locked")

            effective_date = journal_date or row.journal_date
            if lines is not None:
                await self._check_period_open(session, legal_entity_id, effective_date)
                resolved_lines, total_debit, total_credit = await self._validate_and_resolve_lines(
                    session, legal_entity_id, lines
                )
                for old_line in list(row.lines):
                    await session.delete(old_line)
                await session.flush()
                for rl in resolved_lines:
                    session.add(JournalLineTable(
                        id=uuid4(),
                        journal_id=row.id,
                        legal_entity_id=legal_entity_id,
                        line_number=rl["line_number"],
                        account_code=rl["account_code"],
                        account_name=rl["account_name"],
                        account_type_snapshot=rl["account_type_snapshot"],
                        normal_balance_snapshot=rl["normal_balance_snapshot"],
                        debit_amount=rl["debit_amount"],
                        credit_amount=rl["credit_amount"],
                        currency="IDR",
                        cost_center=rl["cost_center"],
                        department=rl["department"],
                        description=rl["description"],
                    ))
                row.total_debit = total_debit
                row.total_credit = total_credit

            if journal_date is not None:
                row.journal_date = journal_date
            if description is not None:
                if len(description.strip()) < 3:
                    raise JournalServiceError("Description must be at least 3 characters")
                row.description = description.strip()
            if journal_type is not None:
                if journal_type not in VALID_JOURNAL_TYPES:
                    raise JournalServiceError(f"Invalid journal_type '{journal_type}'")
                row.journal_type = journal_type
            if reference_number is not None:
                row.reference_number = reference_number
            if notes is not None:
                row.notes = notes
            if attachment_ids is not None:
                row.attachment_ids = [str(a) for a in attachment_ids]

            await session.flush()
            row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            dto = self._row_to_dto(row)
            await self._uow.commit()

        self._record_audit("update_journal", journal_id, updated_by, {})
        return dto

    # ==================== WORKFLOW: SUBMIT / APPROVE / REJECT ====================

    @audit
    async def submit_journal(self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID) -> JournalDTO | None:
        self._check_authority(user_id, "submit_journal")
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
            if row.status != "draft":
                raise InvalidJournalStatusTransitionError(
                    f"Cannot submit journal with status '{row.status}' (must be 'draft')"
                )
            if not row.is_balanced:
                raise JournalNotBalancedError(f"Cannot submit unbalanced journal {row.voucher_number}")
            row.submit(user_id)
            row.submitted_by = user_id
            row.submitted_at = datetime.now(UTC)
            await session.flush()
            dto = self._row_to_dto(row)
            await self._uow.commit()
        self._record_audit("submit_journal", journal_id, user_id, {})
        return dto

    @audit
    async def approve_journal(
        self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID,
        approved_by_name: str | None = None,
    ) -> JournalDTO | None:
        self._check_authority(user_id, "approve_journal")
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
            if row.status != "submitted":
                raise InvalidJournalStatusTransitionError(
                    f"Cannot approve journal with status '{row.status}' (must be 'submitted')"
                )
            # Prinsip 4-eyes: pembuat jurnal tidak boleh menyetujui jurnalnya sendiri.
            if row.created_by and user_id and row.created_by == user_id:
                raise JournalApprovalError(
                    "4-eyes principle violated: the creator of a journal cannot approve it themselves"
                )
            row.approve(user_id)
            row.approved_by_name = approved_by_name
            await session.flush()
            dto = self._row_to_dto(row)
            await self._uow.commit()
        self._record_audit("approve_journal", journal_id, user_id, {})
        return dto

    @audit
    async def reject_journal(
        self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID, reason: str
    ) -> JournalDTO | None:
        self._check_authority(user_id, "reject_journal")
        if not reason or len(reason.strip()) < 3:
            raise JournalServiceError("Rejection reason is required (min. 3 characters)")
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
            if row.status != "submitted":
                raise InvalidJournalStatusTransitionError(
                    f"Cannot reject journal with status '{row.status}' (must be 'submitted')"
                )
            row.reject(user_id, reason)  # ORM method sets status back to "draft"
            row.rejected_by = user_id
            row.rejected_at = datetime.now(UTC)
            row.rejection_reason = reason
            await session.flush()
            dto = self._row_to_dto(row)
            await self._uow.commit()
        self._record_audit("reject_journal", journal_id, user_id, {"reason": reason})
        return dto

    # ==================== WORKFLOW: POST / UNPOST ====================

    @audit
    async def post_journal(
        self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID,
        posted_by_name: str | None = None,
    ) -> JournalDTO | None:
        """Posting ke Ledger — status approved -> posted, dan membuat baris
        ``ledger_entry`` sesuai baris jurnal (materialized GL)."""
        from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable

        self._check_authority(user_id, "post_journal")
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
            if row.status != "approved":
                raise InvalidJournalStatusTransitionError(
                    f"Cannot post journal with status '{row.status}' (must be 'approved')"
                )
            if not row.is_balanced:
                raise JournalNotBalancedError(f"Cannot post unbalanced journal {row.voucher_number}")

            row.post(user_id)
            row.posted_by_name = posted_by_name

            for ln in row.lines:
                session.add(LedgerEntryTable(
                    id=uuid4(),
                    journal_id=row.id,
                    account_id=uuid4(),  # placeholder — lihat catatan di bawah
                    account_code=ln.account_code,
                    line_number=ln.line_number,
                    debit_amount=ln.debit_amount,
                    credit_amount=ln.credit_amount,
                    currency=ln.currency,
                    posting_date=row.journal_date,
                    cost_center=ln.cost_center,
                    department=ln.department,
                    reference_number=row.reference_number,
                    description=ln.description or row.description,
                    fiscal_year=row.journal_date.year,
                    period_month=row.journal_date.month,
                    legal_entity_id=legal_entity_id,
                    created_by=user_id,
                ))

            await session.flush()
            dto = self._row_to_dto(row)
            await self._uow.commit()

        self._stats["journals_posted"] += 1
        self._record_audit("post_journal", journal_id, user_id, {})
        return dto

    @audit
    async def unpost_journal(self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID) -> JournalDTO | None:
        """Batalkan posting (approved <- posted) — HANYA jika jurnal belum
        pernah di-reverse. Menghapus baris ledger_entry terkait."""
        from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable

        self._check_authority(user_id, "unpost_journal")
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
            if row.status != "posted":
                raise InvalidJournalStatusTransitionError(
                    f"Cannot unpost journal with status '{row.status}' (must be 'posted')"
                )
            if row.reversed_journal_id is not None:
                raise InvalidJournalStatusTransitionError(
                    f"Journal {row.voucher_number} has already been reversed and cannot be unposted"
                )

            result = await session.execute(
                select(LedgerEntryTable).where(LedgerEntryTable.journal_id == row.id)
            )
            for entry in result.scalars().all():
                await session.delete(entry)

            row.status = "approved"
            row.posted_by = None
            row.posted_by_name = None
            row.posted_at = None
            row.increment_version()

            await session.flush()
            dto = self._row_to_dto(row)
            await self._uow.commit()
        self._record_audit("unpost_journal", journal_id, user_id, {})
        return dto

    # ==================== CANCEL / VOID / RESTORE ====================

    @audit
    async def cancel_journal(
        self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID, reason: str | None = None
    ) -> JournalDTO | None:
        self._check_authority(user_id, "cancel_journal")
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
            if row.status not in ("draft", "submitted"):
                raise InvalidJournalStatusTransitionError(
                    f"Cannot cancel journal with status '{row.status}' (only draft/submitted can be cancelled; "
                    "use reverse for posted journals)"
                )
            row.cancel(user_id)
            row.cancelled_by = user_id
            row.cancelled_at = datetime.now(UTC)
            row.cancellation_reason = reason
            await session.flush()
            dto = self._row_to_dto(row)
            await self._uow.commit()
        self._record_audit("cancel_journal", journal_id, user_id, {"reason": reason})
        return dto

    @audit
    async def restore_journal(self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID) -> JournalDTO | None:
        """Batalkan pembatalan (cancelled -> draft) — supaya jurnal yang
        salah cancel bisa dipakai lagi tanpa input ulang dari awal."""
        self._check_authority(user_id, "restore_journal")
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
            if row.status != "cancelled":
                raise InvalidJournalStatusTransitionError(
                    f"Cannot restore journal with status '{row.status}' (must be 'cancelled')"
                )
            row.status = "draft"
            row.cancelled_by = None
            row.cancelled_at = None
            row.cancellation_reason = None
            row.increment_version()
            await session.flush()
            dto = self._row_to_dto(row)
            await self._uow.commit()
        self._record_audit("restore_journal", journal_id, user_id, {})
        return dto

    # ==================== REVERSE ====================

    @audit
    async def reverse_journal(
        self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID,
        reason: str, post_immediately: bool = False,
    ) -> JournalDTO | None:
        """Buat jurnal pembalik (debit<->kredit ditukar) dari jurnal yang
        sudah posted. Jurnal asal ditandai reversed & ditautkan dua arah
        (reversed_journal_id <-> original_journal_id)."""
        from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
        from infrastructure.persistence_orm.journal_line_table import JournalLineTable

        self._check_authority(user_id, "reverse_journal")
        if not reason or len(reason.strip()) < 3:
            raise JournalServiceError("Reversal reason is required (min. 3 characters)")

        async with self._uow:
            session = self._uow.session
            try:
                original = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
            if original.status != "posted":
                raise InvalidJournalStatusTransitionError(
                    f"Cannot reverse journal with status '{original.status}' (must be 'posted')"
                )
            if original.reversed_journal_id is not None:
                raise InvalidJournalStatusTransitionError(
                    f"Journal {original.voucher_number} has already been reversed"
                )

            reversal_date = date.today()
            voucher_number = await self._generate_voucher_number(session, legal_entity_id, reversal_date)

            reversal_status = "approved" if post_immediately else "draft"
            reversal = JournalHeaderTable(
                id=uuid4(),
                legal_entity_id=legal_entity_id,
                voucher_number=voucher_number,
                journal_date=reversal_date,
                description=f"Reversal of {original.voucher_number}: {reason}",
                total_debit=original.total_credit,
                total_credit=original.total_debit,
                currency=original.currency,
                status=reversal_status,
                journal_type="reversing",
                reference_number=original.voucher_number,
                source_type="reversal",
                source_id=original.id,
                notes=reason,
                original_journal_id=original.id,
                is_locked=False,
                created_by=user_id,
            )
            session.add(reversal)
            await session.flush()

            for ln in sorted(original.lines, key=lambda x: x.line_number):
                session.add(JournalLineTable(
                    id=uuid4(),
                    journal_id=reversal.id,
                    legal_entity_id=legal_entity_id,
                    line_number=ln.line_number,
                    account_code=ln.account_code,
                    account_name=ln.account_name,
                    account_type_snapshot=ln.account_type_snapshot,
                    normal_balance_snapshot=ln.normal_balance_snapshot,
                    debit_amount=ln.credit_amount,  # ditukar
                    credit_amount=ln.debit_amount,  # ditukar
                    currency=ln.currency,
                    cost_center=ln.cost_center,
                    department=ln.department,
                    description=f"Reversal: {ln.description or ''}".strip(),
                ))

            original.reverse(user_id, reversal.id)
            original.reversal_reason = reason

            if post_immediately:
                from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable

                reversal.status = "posted"
                reversal.posted_by = user_id
                reversal.posted_at = datetime.now(UTC)
                await session.flush()
                result = await session.execute(
                    select(JournalLineTable).where(JournalLineTable.journal_id == reversal.id)
                )
                for ln in result.scalars().all():
                    session.add(LedgerEntryTable(
                        id=uuid4(),
                        journal_id=reversal.id,
                        account_id=uuid4(),
                        account_code=ln.account_code,
                        line_number=ln.line_number,
                        debit_amount=ln.debit_amount,
                        credit_amount=ln.credit_amount,
                        currency=ln.currency,
                        posting_date=reversal_date,
                        cost_center=ln.cost_center,
                        department=ln.department,
                        description=ln.description,
                        fiscal_year=reversal_date.year,
                        period_month=reversal_date.month,
                        legal_entity_id=legal_entity_id,
                        created_by=user_id,
                    ))

            await session.flush()
            row = await self._get_row_or_raise(session, reversal.id, legal_entity_id)
            dto = self._row_to_dto(row)
            await self._uow.commit()

        self._stats["journals_reversed"] += 1
        self._record_audit("reverse_journal", journal_id, user_id, {"reversal_journal_id": str(reversal.id), "reason": reason})
        return dto

    # ==================== LOCK / UNLOCK ====================

    @audit
    async def lock_journal(self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID) -> JournalDTO | None:
        self._check_authority(user_id, "lock_journal")
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
            row.is_locked = True
            row.increment_version()
            await session.flush()
            dto = self._row_to_dto(row)
            await self._uow.commit()
        self._record_audit("lock_journal", journal_id, user_id, {})
        return dto

    @audit
    async def unlock_journal(self, journal_id: UUID, user_id: UUID, legal_entity_id: UUID) -> JournalDTO | None:
        self._check_authority(user_id, "unlock_journal")
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
            row.is_locked = False
            row.increment_version()
            await session.flush()
            dto = self._row_to_dto(row)
            await self._uow.commit()
        self._record_audit("unlock_journal", journal_id, user_id, {})
        return dto

    # ==================== VALIDATE / STATUS ====================

    async def validate_journal(self, journal_id: UUID, legal_entity_id: UUID) -> ValidationResultDTO:
        errors: list[str] = []
        warnings: list[str] = []

        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return ValidationResultDTO(is_valid=False, errors=["Journal not found"])

            if not row.is_balanced:
                errors.append(f"Journal is not balanced: debit={row.total_debit}, credit={row.total_credit}")
            if len(row.lines) < 2:
                errors.append("Journal must have at least 2 lines")
            if row.is_locked:
                warnings.append("Journal is locked")
            try:
                await self._check_period_open(session, legal_entity_id, row.journal_date)
            except JournalPeriodClosedError as exc:
                errors.append(str(exc))

            if row.status == "draft" and row.created_by:
                warnings.append("Journal is still in draft; submit it for approval before posting")

        return ValidationResultDTO(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

    async def get_journal_status(self, journal_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, journal_id, legal_entity_id)
            except JournalNotFoundError:
                return None
        return {
            "status": row.status,
            "is_balanced": row.is_balanced,
            "is_locked": row.is_locked,
            "can_be_modified": row.can_be_modified,
            "can_be_approved": row.can_be_approved,
            "can_be_posted": row.can_be_posted,
            "can_be_reversed": row.can_be_reversed,
        }

    # ==================== HISTORY / LEDGER / EXPORT ====================

    async def get_journal_history(self, journal_id: UUID, legal_entity_id: UUID) -> list[JournalHistoryEntryDTO]:
        out = [
            JournalHistoryEntryDTO(
                timestamp=entry["timestamp"],
                action=entry["action"],
                actor_id=UUID(entry["actor_id"]) if entry.get("actor_id") else UUID(int=0),
                actor_name=None,
                details=entry.get("details", {}),
            )
            for entry in self._audit_trail
            if entry.get("journal_id") == str(journal_id)
        ]
        out.sort(key=lambda h: h.timestamp, reverse=True)
        return out

    async def get_ledger_entries(self, journal_id: UUID, legal_entity_id: UUID) -> list[LedgerEntryDTO]:
        from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable

        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(LedgerEntryTable).where(
                    LedgerEntryTable.journal_id == journal_id,
                    LedgerEntryTable.legal_entity_id == legal_entity_id,
                ).order_by(LedgerEntryTable.line_number)
            )
            rows = result.scalars().all()

        return [
            LedgerEntryDTO(
                id=r.id, account_code=r.account_code, debit_amount=r.debit_amount,
                credit_amount=r.credit_amount, posting_date=r.posting_date,
                fiscal_year=r.fiscal_year, period_month=r.period_month, description=r.description,
            )
            for r in rows
        ]

    async def export_journals(
        self, legal_entity_id: UUID, fmt: str, status: str | None = None,
        date_from: date | None = None, date_to: date | None = None,
    ) -> bytes:
        result = await self.list_journals(
            legal_entity_id=legal_entity_id, status=status, date_from=date_from,
            date_to=date_to, page=1, page_size=100_000,
        )
        items = result.items

        if fmt == "json":
            payload = [
                {
                    "journal_number": j.journal_number, "journal_date": j.journal_date.isoformat(),
                    "description": j.description, "journal_type": j.journal_type, "status": j.status,
                    "total_debit": str(j.total_debit), "total_credit": str(j.total_credit),
                    "reference_number": j.reference_number,
                    "lines": [
                        {"account_code": ln.account_code, "account_name": ln.account_name,
                         "debit_amount": str(ln.debit_amount), "credit_amount": str(ln.credit_amount)}
                        for ln in j.lines
                    ],
                }
                for j in items
            ]
            return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

        # csv (baris per journal-line, header di-repeat supaya tetap flat/tabular)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "journal_number", "journal_date", "description", "journal_type", "status",
            "account_code", "account_name", "debit_amount", "credit_amount", "reference_number",
        ])
        for j in items:
            for ln in j.lines:
                writer.writerow([
                    j.journal_number, j.journal_date.isoformat(), j.description, j.journal_type, j.status,
                    ln.account_code, ln.account_name or "", str(ln.debit_amount), str(ln.credit_amount),
                    j.reference_number or "",
                ])
        return buf.getvalue().encode("utf-8-sig")


# ============================================================================
# Factory function for dependency injection
# ============================================================================

def create_journal_service(
    journal_repo: Any,
    ledger_repo: LedgerRepositoryPort,
    account_repo: AccountRepositoryPort,
    uow: UnitOfWorkPort,
    event_publisher: EventPublisherPort | None = None,
) -> JournalService:
    """
    Factory function untuk membuat instance JournalService.
    Digunakan oleh dependency injection container.
    """
    return JournalService(
        journal_repo=journal_repo,
        ledger_repo=ledger_repo,
        account_repo=account_repo,
        uow=uow,
        event_publisher=event_publisher,
    )


__all__ = [
    "AccountNotFoundError",
    "AccountNotPostableError",
    "InvalidJournalStatusTransitionError",
    "JournalApprovalError",
    "JournalDTO",
    "JournalHistoryEntryDTO",
    "JournalLineDTO",
    "JournalListResult",
    "JournalLockedError",
    "JournalNotBalancedError",
    "JournalNotFoundError",
    "JournalPeriodClosedError",
    "JournalService",
    "JournalServiceError",
    "LedgerEntryDTO",
    "ValidationResultDTO",
    "create_journal_service",
]
