#!/usr/bin/env python3
"""
Module: service_coa.py
Layer: Application / Service Layer
Responsibility:
    Service layer untuk Chart of Accounts (COA) — SATU-SATUNYA jalur baca/tulis
    tabel `account`, dipakai oleh fastapi_coa_router.py (REST API) dan oleh
    service lain yang butuh validasi akun (mis. service_journal.py) lewat
    ``get_account_by_code``.

CATATAN SEJARAH / KENAPA DITULIS ULANG:
    Versi sebelumnya punya DUA implementasi COA yang tidak sinkron:
      1. Jalur "aggregate" (create_account/update_account/deactivate_account/
         activate_account/lock_account/... lama) yang membungkus setiap akun
         ke dalam ``domain.coa.aggregate_root.ChartOfAccounts`` (alias
         ``AccountAggregate``) — padahal class itu adalah aggregate untuk
         BANYAK akun sekaligus (field ``accounts: dict[UUID, Account]``),
         BUKAN representasi satu akun. Setiap kali dipanggil, constructor-nya
         menerima kwargs satu-akun (``account_code=``, ``account_name=``, dst)
         yang tidak cocok dengan fieldnya sendiri -> selalu ``TypeError``.
      2. Jalur "direct table" (create_account_write/update_account_write/
         list_accounts) yang menjadi workaround, langsung query
         ``AccountTable`` lewat ``UnitOfWork``, dan ini yang sungguh berjalan.
      Selain itu, ``fastapi_coa_router.py`` memanggil banyak method
      (``get_account_by_id``, ``get_account_hierarchy``, ``get_account_balance``,
      ``get_account_usage``, ``validate_account_modification``,
      ``validate_account_code``, ``bulk_update_status``, ``bulk_update_parent``,
      ``export_coa``, ``import_coa``, ``get_account_history``,
      ``get_account_audit_trail``) yang SAMA SEKALI TIDAK ADA di service lama
      -> setiap endpoint itu selalu gagal dengan ``AttributeError`` / 500.

    Service ini menghapus jalur aggregate yang rusak dan menjadikan pola
    "direct table via UnitOfWork" sebagai satu-satunya implementasi COA,
    lengkap untuk SEMUA endpoint yang dipanggil router (lihat daftar method
    di bawah). Ini membuat COA benar-benar sinkron: DB <-> service <-> router
    <-> frontend memakai kontrak field yang sama persis.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import contextvars
import hashlib
import os

from sqlalchemy import func, or_, select, text

from ports.primary.account_repository_port import AccountRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Exceptions
# ============================================================================


class COAServiceError(Exception):
    pass


class AccountNotFoundError(COAServiceError):
    pass


class AccountCodeAlreadyExistsError(COAServiceError):
    pass


class InvalidParentAccountError(COAServiceError):
    pass


class AccountHasChildrenError(COAServiceError):
    pass


class PostingAccountCannotHaveChildrenError(COAServiceError):
    """Akun dengan allow_posting=True (akun transaksi/leaf) tidak boleh
    punya sub-akun; dan akun yang sudah punya sub-akun tidak boleh diubah
    menjadi allow_posting=True. Aturan ini JUGA ditegakkan di level
    database lewat trigger `trg_coa_leaf_node_rule` (lihat migration
    0048_coa_leaf_node_and_journal_snapshot.py) — validasi di sini hanya
    supaya pesan error yang diterima user jelas (422), bukan error database
    mentah (500), sebelum request sempat menyentuh trigger."""
    pass


class AccountHasTransactionsError(COAServiceError):
    pass


class AccountCycleDetectedError(COAServiceError):
    pass


class InvalidAccountTypeHierarchyError(COAServiceError):
    pass


class AccountCodeFormatError(COAServiceError):
    pass


class InvalidBulkImportDataError(COAServiceError):
    pass


class COAAuthorizationError(COAServiceError):
    """Aksi sensitif dicoba tanpa identitas pengguna (SoD / jejak audit wajib)."""


class COAApprovalRequiredError(COAServiceError):
    """Aksi ini wajib lewat permintaan perubahan + persetujuan orang lain (maker-checker)."""


class AccountLockedError(COAServiceError):
    pass


# ============================================================================
# DTOs
# ============================================================================
# Semua field di sini SENGAJA dibuat SAMA PERSIS dengan AccountResponseSchema
# di fastapi_coa_router.py supaya router bisa langsung mem-forward atribut
# tanpa mapping manual yang gampang meleset.


@dataclass(kw_only=True)
class AccountDTO:
    id: UUID
    account_code: str
    account_name: str
    account_name_en: str | None
    account_type: str
    account_group: str | None
    normal_balance: str
    parent_account_id: UUID | None
    parent_account_code: str | None
    level: int
    sort_order: int
    description: str | None
    status: str
    currency_code: str
    is_bank_account: bool
    is_cash_account: bool
    is_intercompany: bool
    is_header: bool
    allow_posting: bool
    budget_control: bool
    reconciliation_required: bool
    tax_code: str | None
    cashflow_type: str | None
    is_used_in_transaction: bool
    is_locked: bool
    lock_reason: str | None
    current_balance: Decimal
    opening_balance: Decimal
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None
    updated_by: UUID | None
    version: int
    children: list[AccountDTO] | None = None


@dataclass(kw_only=True)
class AccountListResult:
    items: list[AccountDTO]
    total: int


@dataclass(kw_only=True)
class AccountTreeResult:
    root_accounts: list[AccountDTO]
    flattened: list[AccountDTO]
    total_levels: int


@dataclass(kw_only=True)
class AccountBalanceDTO:
    account_code: str
    account_name: str
    balance: Decimal
    normal_balance: str
    is_debit_balance: bool
    opening_balance: Decimal
    debit_movement: Decimal
    credit_movement: Decimal


@dataclass(kw_only=True)
class AccountUsageDTO:
    account_code: str
    account_name: str
    journal_count: int
    last_used_at: datetime | None
    total_debit: Decimal
    total_credit: Decimal
    is_used_in_journal: bool
    is_used_in_budget: bool
    is_used_in_tax: bool


@dataclass(kw_only=True)
class ValidationResultDTO:
    is_valid: bool
    errors: list[str] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)
    suggestions: list[str] = dc_field(default_factory=list)


@dataclass(kw_only=True)
class BulkOperationResultDTO:
    total: int
    success_count: int
    failed_count: int
    failed_ids: list[UUID] = dc_field(default_factory=list)
    errors: list[str] = dc_field(default_factory=list)


@dataclass(kw_only=True)
class ImportExportResultDTO:
    success: bool
    message: str
    imported_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    errors: list[str] = dc_field(default_factory=list)


@dataclass(kw_only=True)
class AccountHistoryEntryDTO:
    timestamp: datetime
    action: str
    field: str
    old_value: Any
    new_value: Any
    actor_id: UUID
    actor_name: str | None
    reason: str | None


@dataclass(kw_only=True)
class AccountAuditEntryDTO:
    timestamp: datetime
    event_type: str
    event_data: dict[str, Any]
    actor_id: UUID
    actor_name: str | None
    version: int


ACCOUNT_TYPE_PREFIXES: dict[str, list[str]] = {
    "Asset": ["1"],
    "Liability": ["2"],
    "Equity": ["3"],
    "Revenue": ["4"],
    "Expense": ["5", "6"],
}

VALID_ACCOUNT_TYPES = (
    "Asset", "Liability", "Equity", "Revenue", "Expense",
    "ContraAsset", "ContraLiability", "ContraEquity",
)


# ============================================================================
# Main Service
# ============================================================================


# ============================================================================
# AUDIT TRAIL PERSISTEN (tabel `coa_audit_log` di database erp_db)
# ============================================================================
# Append-only: trigger database menolak UPDATE/DELETE/TRUNCATE sehingga jejak
# perubahan COA tidak bisa diubah/dihapus -- syarat umum audit eksternal
# (ISA 315/330 pengujian general IT control: integritas log perubahan master
# data). Setiap baris punya `row_hash` (SHA-256 atas isi baris) supaya
# manipulasi lewat akses langsung ke DB (mis. trigger dimatikan) bisa
# terdeteksi lewat `verify_audit_integrity()`. Tabel dibuat oleh migration
# `coa_audit_log_001`; DDL di bawah (IF NOT EXISTS) adalah pengaman supaya
# fitur tetap jalan walau migration belum sempat dijalankan.
_COA_CR_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS coa_change_request (
        id              UUID PRIMARY KEY,
        legal_entity_id UUID NOT NULL,
        account_id      UUID NOT NULL,
        account_code    VARCHAR(20) NOT NULL,
        action          VARCHAR(30) NOT NULL,
        reason          VARCHAR(500),
        status          VARCHAR(20) NOT NULL DEFAULT 'pending',
        requested_by    UUID NOT NULL,
        requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        decided_by      UUID,
        decided_at      TIMESTAMPTZ,
        decision_note   VARCHAR(500),
        CONSTRAINT ck_coa_cr_status CHECK (status IN ('pending','processing','approved','rejected','cancelled')),
        CONSTRAINT ck_coa_cr_action CHECK (action IN ('delete','unlock'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_coa_cr_status ON coa_change_request (legal_entity_id, status, requested_at DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_coa_cr_pending ON coa_change_request (account_id, action) "
    "WHERE status IN ('pending','processing')",
)

# Diset True hanya selama persetujuan dieksekusi (maker-checker).
_APPROVAL_EXEC: contextvars.ContextVar[bool] = contextvars.ContextVar("coa_approval_exec", default=False)

_COA_AUDIT_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS coa_audit_log (
        id            UUID PRIMARY KEY,
        legal_entity_id UUID NOT NULL,
        account_id    UUID,
        account_code  VARCHAR(20),
        action        VARCHAR(50) NOT NULL,
        field_name    VARCHAR(100),
        old_value     TEXT,
        new_value     TEXT,
        details       JSONB NOT NULL DEFAULT '{}'::jsonb,
        reason        VARCHAR(500),
        actor_id      UUID,
        occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        row_hash      CHAR(64) NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_coa_audit_account ON coa_audit_log (legal_entity_id, account_id, occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_coa_audit_code ON coa_audit_log (legal_entity_id, account_code)",
    """
    CREATE OR REPLACE FUNCTION coa_audit_log_immutable() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'coa_audit_log bersifat append-only: % tidak diizinkan', TG_OP;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS trg_coa_audit_log_no_change ON coa_audit_log",
    """
    CREATE TRIGGER trg_coa_audit_log_no_change
        BEFORE UPDATE OR DELETE ON coa_audit_log
        FOR EACH ROW EXECUTE FUNCTION coa_audit_log_immutable()
    """,
    "DROP TRIGGER IF EXISTS trg_coa_audit_log_no_truncate ON coa_audit_log",
    """
    CREATE TRIGGER trg_coa_audit_log_no_truncate
        BEFORE TRUNCATE ON coa_audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION coa_audit_log_immutable()
    """,
)


def _audit_row_hash(
    *, row_id: UUID, legal_entity_id: UUID, account_id: UUID | None, account_code: str | None,
    action: str, field_name: str | None, old_value: str | None, new_value: str | None,
    details_json: str, reason: str | None, actor_id: UUID | None, occurred_at: datetime,
) -> str:
    payload = "|".join([
        str(row_id), str(legal_entity_id), str(account_id or ""), account_code or "", action,
        field_name or "", old_value or "", new_value or "", details_json, reason or "",
        str(actor_id or ""), occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _audit_str(v: Any) -> str | None:
    if v is None:
        return None
    return v if isinstance(v, str) else json.dumps(v, default=str, ensure_ascii=False)


class COAService:
    """Service untuk Chart of Accounts (COA). Satu jalur implementasi, langsung
    ke ``AccountTable`` lewat ``UnitOfWork`` — lihat catatan modul di atas."""

    def __init__(
        self,
        account_repository: AccountRepositoryPort,
        uow: UnitOfWorkPort,
        event_publisher: EventPublisherPort | None = None,
    ):
        # account_repository dipertahankan di constructor demi kompatibilitas
        # wiring dependency-injection (bootstrap/dependency_container), tapi
        # TIDAK dipakai lagi untuk baca/tulis akun tunggal (lihat catatan
        # modul) — semua operasi CRUD lewat AccountTable langsung.
        self._account_repo = account_repository
        self._uow = uow
        self._event_publisher = event_publisher

        self._stats = {"accounts_created": 0, "accounts_updated": 0, "accounts_deactivated": 0}
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("COAService initialized")

    _audit_table_ready: bool = False  # per proses; DDL IF NOT EXISTS dijalankan sekali

    async def _audit_db(
        self,
        session: Any,
        *,
        legal_entity_id: UUID,
        action: str,
        account_id: UUID | None,
        account_code: str | None,
        actor_id: UUID | None,
        details: dict[str, Any] | None = None,
        field_name: str | None = None,
        old_value: Any = None,
        new_value: Any = None,
        reason: str | None = None,
    ) -> None:
        """Tulis satu baris ke `coa_audit_log` DI DALAM transaksi yang sama dengan
        perubahan akunnya (atomik: perubahan commit <=> jejak audit commit).
        Memakai savepoint; kegagalan menulis audit dicatat sebagai ERROR tapi
        tidak menjatuhkan operasi bisnis (mis. DB user tanpa hak DDL)."""
        try:
            async with session.begin_nested():
                if not COAService._audit_table_ready:
                    exists = (await session.execute(text("SELECT to_regclass('public.coa_audit_log')"))).scalar()
                    if exists is None:
                        for stmt in _COA_AUDIT_DDL:
                            await session.execute(text(stmt))
                row_id = uuid4()
                occurred_at = datetime.now(UTC)
                details_json = json.dumps(details or {}, default=str, ensure_ascii=False, sort_keys=True)
                old_s, new_s = _audit_str(old_value), _audit_str(new_value)
                row_hash = _audit_row_hash(
                    row_id=row_id, legal_entity_id=legal_entity_id, account_id=account_id,
                    account_code=account_code, action=action, field_name=field_name,
                    old_value=old_s, new_value=new_s, details_json=details_json,
                    reason=reason, actor_id=actor_id, occurred_at=occurred_at,
                )
                await session.execute(
                    text(
                        "INSERT INTO coa_audit_log (id, legal_entity_id, account_id, account_code, action, "
                        "field_name, old_value, new_value, details, reason, actor_id, occurred_at, row_hash) "
                        "VALUES (:id, :le, :acc, :code, :action, :field, :old, :new, CAST(:details AS jsonb), "
                        ":reason, :actor, :ts, :hash)"
                    ),
                    {
                        "id": row_id, "le": legal_entity_id, "acc": account_id, "code": account_code,
                        "action": action, "field": field_name, "old": old_s, "new": new_s,
                        "details": details_json, "reason": (reason or None) and reason[:500],
                        "actor": actor_id, "ts": occurred_at, "hash": row_hash,
                    },
                )
            COAService._audit_table_ready = True
        except Exception:
            logger.exception("GAGAL menulis coa_audit_log (action=%s account=%s)", action, account_code)

    async def _read_audit_rows(
        self, account_id: UUID, legal_entity_id: UUID, *, limit: int = 1000,
        start_date: datetime | None = None, end_date: datetime | None = None,
    ) -> list[Any] | None:
        """Baca jejak audit dari DB. None = tabel belum ada/gagal baca (pemanggil
        fallback ke jejak in-memory)."""
        conds = ["legal_entity_id = :le", "account_id = :acc"]
        params: dict[str, Any] = {"le": legal_entity_id, "acc": account_id, "lim": limit}
        if start_date:
            conds.append("occurred_at >= :s")
            params["s"] = start_date
        if end_date:
            conds.append("occurred_at <= :e")
            params["e"] = end_date
        try:
            async with self._uow:
                session = self._uow.session
                async with session.begin_nested():
                    res = await session.execute(
                        text(
                            "SELECT occurred_at, action, field_name, old_value, new_value, details, "
                            "reason, actor_id FROM coa_audit_log WHERE " + " AND ".join(conds) +
                            " ORDER BY occurred_at DESC LIMIT :lim"
                        ),
                        params,
                    )
                    return list(res.all())
        except Exception:
            logger.warning("coa_audit_log belum bisa dibaca; fallback ke jejak in-memory", exc_info=True)
            return None

    async def verify_audit_integrity(self, legal_entity_id: UUID, account_id: UUID | None = None) -> dict[str, Any]:
        """Hitung ulang SHA-256 tiap baris `coa_audit_log` dan laporkan baris yang
        hash-nya tidak cocok (indikasi data diubah di luar aplikasi)."""
        sql = (
            "SELECT id, legal_entity_id, account_id, account_code, action, field_name, old_value, "
            "new_value, details, reason, actor_id, occurred_at, row_hash FROM coa_audit_log "
            "WHERE legal_entity_id = :le" + (" AND account_id = :acc" if account_id else "")
        )
        params: dict[str, Any] = {"le": legal_entity_id}
        if account_id:
            params["acc"] = account_id
        checked, bad = 0, []
        async with self._uow:
            res = await self._uow.session.execute(text(sql), params)
            for r in res.all():
                checked += 1
                details_json = json.dumps(r.details or {}, default=str, ensure_ascii=False, sort_keys=True)
                expected = _audit_row_hash(
                    row_id=r.id, legal_entity_id=r.legal_entity_id, account_id=r.account_id,
                    account_code=r.account_code, action=r.action, field_name=r.field_name,
                    old_value=r.old_value, new_value=r.new_value, details_json=details_json,
                    reason=r.reason, actor_id=r.actor_id, occurred_at=r.occurred_at,
                )
                if expected != r.row_hash:
                    bad.append(str(r.id))
        return {"checked": checked, "tampered_count": len(bad), "tampered_ids": bad[:100], "ok": not bad}

    # ==================== AUTHORITY CHECK (SOD) ====================

    # Aksi yang wajib punya identitas pelaku (tidak boleh anonim/sistem) agar
    # jejak audit dan pemisahan tugas (SoD) bermakna. RBAC per-permission
    # ditegakkan di router lewat require_permission("coa:*"); di sini lapisan
    # kedua (defence in depth) untuk pemanggil non-HTTP (job, skrip, service lain).
    _ACTOR_REQUIRED = frozenset({
        "create_account", "update_account", "deactivate_account", "activate_account",
        "void_account", "lock_account", "unlock_account", "delete_account",
        "bulk_update_status", "bulk_update_parent", "import_coa",
    })

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if (user_id is None or user_id == UUID(int=0)) and permission in self._ACTOR_REQUIRED:
            raise COAAuthorizationError(
                f"Aksi '{permission}' membutuhkan identitas pengguna (jejak audit wajib)."
            )

    async def _actor_names(self, ids: set[UUID]) -> dict[UUID, str]:
        """Nama pelaku dari tabel iam_user (best effort; kosong jika gagal)."""
        ids = {i for i in ids if i and i != UUID(int=0)}
        if not ids:
            return {}
        try:
            async with self._uow:
                session = self._uow.session
                async with session.begin_nested():
                    res = await session.execute(
                        text("SELECT id, full_name, username FROM iam_user WHERE id = ANY(:ids)"),
                        {"ids": list(ids)},
                    )
                    return {r.id: (r.full_name or r.username) for r in res.all()}
        except Exception:
            logger.warning("Gagal membaca nama pelaku dari iam_user", exc_info=True)
            return {}

    # ==================== AUDIT TRAIL (in-memory, best effort) ====================
    # CATATAN: codebase ini tidak punya tabel audit khusus untuk COA yang siap
    # pakai (tabel `audit_events` yang ada memakai declarative Base terpisah
    # dan tidak ikut proses migrasi/metadata utama). Untuk menghindari
    # menambah lapisan yang berpotensi rusak lagi, audit trail COA disimpan
    # in-memory per proses (cukup untuk /accounts/{id}/history dan
    # /accounts/{id}/audit-trail selama proses backend hidup). Kalau butuh
    # riwayat permanen lintas restart, sambungkan ke tabel audit sungguhan
    # dan ganti dua method `_record_audit` / `get_account_*` di bawah ini.

    def _record_audit(
        self, action: str, account_id: UUID | None, actor_id: UUID | None,
        details: dict[str, Any] | None = None, field: str | None = None,
        old_value: Any = None, new_value: Any = None, reason: str | None = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now(UTC),
            "account_id": str(account_id) if account_id else None,
            "action": action,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "actor_id": str(actor_id) if actor_id else None,
            "reason": reason,
            "details": details or {},
            "version": len(self._audit_trail) + 1,
        }
        self._audit_trail.append(entry)
        if len(self._audit_trail) > 20000:
            self._audit_trail = self._audit_trail[-10000:]
        logger.info(f"AUDIT: {action} account={account_id} - {details}")

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()

    # ==================== INTERNAL HELPERS ====================

    def _row_to_dto(
        self,
        row: Any,
        parent_code_map: dict[UUID, str],
        usage_map: dict[str, tuple[bool, Decimal]] | None = None,
    ) -> AccountDTO:
        used, net_movement = (False, Decimal("0"))
        if usage_map is not None:
            used, net_movement = usage_map.get(row.account_code, (False, Decimal("0")))
        # usage_map menyimpan mutasi bersih mentah (debit - kredit). Saldo
        # berjalan harus: (a) memperhitungkan saldo awal dan (b) searah
        # saldo normal akun (akun credit-normal spt Kewajiban/Ekuitas/
        # Pendapatan positif kalau kreditnya lebih besar) -- sebelumnya
        # keduanya diabaikan sehingga saldo akun kredit tampil negatif dan
        # saldo awal tidak pernah ikut terhitung.
        movement = net_movement if str(row.normal_balance).lower() == "debit" else -net_movement
        balance = Decimal(row.opening_balance or 0) + movement
        return AccountDTO(
            id=row.id,
            account_code=row.account_code,
            account_name=row.account_name,
            account_name_en=row.account_name_en,
            account_type=row.account_type,
            account_group=row.account_group,
            normal_balance=row.normal_balance,
            parent_account_id=row.parent_account_id,
            parent_account_code=parent_code_map.get(row.parent_account_id),
            level=row.level,
            sort_order=row.sort_order,
            description=row.description,
            status=row.status,
            currency_code=row.currency_code,
            is_bank_account=row.is_bank_account,
            is_cash_account=row.is_cash_account,
            is_intercompany=row.is_intercompany,
            is_header=row.is_header,
            allow_posting=row.allow_posting,
            budget_control=row.budget_control,
            reconciliation_required=row.reconciliation_required,
            tax_code=row.tax_code,
            cashflow_type=row.cashflow_type,
            is_used_in_transaction=used,
            is_locked=row.is_locked,
            lock_reason=row.lock_reason,
            current_balance=balance,
            opening_balance=row.opening_balance,
            created_at=row.created_at,
            updated_at=row.updated_at or row.created_at,
            created_by=row.created_by or UUID(int=0),
            created_by_name=None,
            updated_by=row.updated_by,
            version=getattr(row, "version", 1),
        )

    async def _parent_code_map(self, session: Any, rows: list[Any]) -> dict[UUID, str]:
        from infrastructure.persistence_orm.account_table import AccountTable

        parent_ids = {r.parent_account_id for r in rows if r.parent_account_id}
        if not parent_ids:
            return {}
        result = await session.execute(
            select(AccountTable.id, AccountTable.account_code).where(AccountTable.id.in_(parent_ids))
        )
        return {pid: code for pid, code in result.all()}

    async def _usage_map_for_codes(
        self, session: Any, legal_entity_id: UUID, account_codes: list[str],
        statuses: tuple[str, ...] = ("posted", "reversed"),
    ) -> dict[str, tuple[bool, Decimal]]:
        """Hitung apakah tiap kode akun sudah dipakai jurnal (posted) dan
        saldo berjalannya, dalam SATU query agregat (hindari N+1)."""
        from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
        from infrastructure.persistence_orm.journal_line_table import JournalLineTable

        if not account_codes:
            return {}
        stmt = (
            select(
                JournalLineTable.account_code,
                func.count(JournalLineTable.id),
                func.coalesce(func.sum(JournalLineTable.debit_amount), 0),
                func.coalesce(func.sum(JournalLineTable.credit_amount), 0),
            )
            .join(JournalHeaderTable, JournalHeaderTable.id == JournalLineTable.journal_id)
            .where(
                JournalLineTable.legal_entity_id == legal_entity_id,
                JournalLineTable.account_code.in_(account_codes),
                # 'reversed' = jurnal asli yang sudah dibalik; jurnal pembaliknya
                # berstatus 'posted'. Keduanya HARUS dihitung, kalau tidak efek
                # pembalik tercatat sendirian dan saldo akun jadi salah.
                JournalHeaderTable.status.in_(statuses),
                JournalLineTable.deleted_at.is_(None),
            )
            .group_by(JournalLineTable.account_code)
        )
        result = await session.execute(stmt)
        usage: dict[str, tuple[bool, Decimal]] = {}
        for code, count, total_debit, total_credit in result.all():
            usage[code] = (count > 0, Decimal(total_debit) - Decimal(total_credit))
        return usage

    async def _get_row_or_raise(self, session: Any, account_id: UUID, legal_entity_id: UUID) -> Any:
        from infrastructure.persistence_orm.account_table import AccountTable

        result = await session.execute(
            select(AccountTable).where(
                AccountTable.id == account_id,
                AccountTable.legal_entity_id == legal_entity_id,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            raise AccountNotFoundError(f"Account {account_id} not found")
        return row

    async def _has_children(self, session: Any, account_id: UUID) -> bool:
        """Cek apakah akun punya sub-akun lewat query eksplisit.

        BUGFIX: JANGAN pernah akses `row.children` langsung (relationship
        SQLAlchemy) di sini — itu lazy-loaded, dan mengaksesnya secara
        "sync" di dalam AsyncSession melempar
        `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called`.
        Query eksplisit ini aman dipakai di context async manapun.
        """
        from infrastructure.persistence_orm.account_table import AccountTable

        result = await session.execute(
            select(func.count()).select_from(AccountTable).where(
                AccountTable.parent_account_id == account_id
            )
        )
        return result.scalar_one() > 0

    def _validate_account_code_format(self, account_code: str, account_type: str) -> None:
        if not account_code or len(account_code.strip()) < 1:
            raise AccountCodeFormatError("Account code is required")
        prefixes = ACCOUNT_TYPE_PREFIXES.get(account_type, [])
        if prefixes and account_code[0] not in prefixes:
            raise AccountCodeFormatError(
                f"Account code for {account_type} should start with {', '.join(prefixes)}"
            )

    # ==================== CREATE ====================

    @audit
    async def create_account_write(
        self,
        *,
        legal_entity_id: UUID,
        account_code: str,
        account_name: str,
        account_type: str,
        normal_balance: str,
        parent_account_code: str | None,
        description: str | None,
        currency_code: str | None,
        is_bank_account: bool,
        is_cash_account: bool,
        is_intercompany: bool,
        is_header: bool,
        level: int | None,
        opening_balance: Decimal | None,
        category: str | None = None,
        budget_control: bool = False,
        account_name_en: str | None = None,
        account_group: str | None = None,
        tax_code: str | None = None,
        cashflow_type: str | None = None,
        allow_posting: bool = True,
        reconciliation_required: bool = False,
        sort_order: int = 0,
        created_by: UUID,
    ) -> AccountDTO:
        """Buat akun baru. `category` adalah alias lama untuk `account_group`,
        tetap diterima untuk kompatibilitas mundur dengan frontend/klien lama."""
        from infrastructure.persistence_orm.account_table import AccountTable

        self._check_authority(created_by, "create_account")

        account_group = account_group or category
        account_code = (account_code or "").strip().upper()
        account_name = (account_name or "").strip()

        if not account_code:
            raise ValueError("account_code is required")
        if not account_name:
            raise ValueError("account_name is required")
        if account_type not in VALID_ACCOUNT_TYPES:
            raise ValueError(f"Invalid account_type '{account_type}'")
        if normal_balance not in ("debit", "credit"):
            raise ValueError("normal_balance must be 'debit' or 'credit'")

        async with self._uow:
            session = self._uow.session

            existing = await session.execute(
                select(AccountTable.id).where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.account_code == account_code,
                )
            )
            if existing.scalar_one_or_none():
                raise AccountCodeAlreadyExistsError(f"Account code '{account_code}' already exists")

            parent_id = None
            parent_level = -1
            if parent_account_code:
                presult = await session.execute(
                    select(
                        AccountTable.id, AccountTable.level, AccountTable.is_header, AccountTable.allow_posting
                    ).where(
                        AccountTable.legal_entity_id == legal_entity_id,
                        AccountTable.account_code == parent_account_code,
                    )
                )
                prow = presult.first()
                if not prow:
                    raise InvalidParentAccountError(f"Parent account '{parent_account_code}' not found")
                parent_id, parent_level, _parent_is_header, parent_allow_posting = prow
                if parent_allow_posting:
                    raise PostingAccountCannotHaveChildrenError(
                        f"Parent account '{parent_account_code}' is a posting account "
                        "(allow_posting=true) and cannot have child accounts. Set "
                        "allow_posting=false on it first, or choose a header account as parent."
                    )

            opening = opening_balance if opening_balance is not None else Decimal("0")
            if normal_balance == "debit":
                debit_amt = opening if opening >= 0 else Decimal("0")
                credit_amt = -opening if opening < 0 else Decimal("0")
            else:
                credit_amt = opening if opening >= 0 else Decimal("0")
                debit_amt = -opening if opening < 0 else Decimal("0")

            row = AccountTable(
                id=uuid4(),
                legal_entity_id=legal_entity_id,
                account_code=account_code,
                account_name=account_name,
                account_name_en=account_name_en,
                account_type=account_type,
                account_group=account_group,
                normal_balance=normal_balance,
                parent_account_id=parent_id,
                level=(parent_level + 1) if parent_id else max(level or 0, 0),
                sort_order=sort_order,
                description=description,
                currency_code=currency_code or "IDR",
                is_bank_account=is_bank_account,
                is_cash_account=is_cash_account,
                is_intercompany=is_intercompany,
                is_header=is_header,
                allow_posting=allow_posting and not is_header,
                budget_control=budget_control,
                reconciliation_required=reconciliation_required,
                tax_code=tax_code,
                cashflow_type=cashflow_type,
                opening_balance_debit=debit_amt,
                opening_balance_credit=credit_amt,
                status="active",
                is_active=True,
                is_locked=False,
                created_by=created_by,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)

            parent_code_map = {parent_id: parent_account_code} if parent_id else {}
            dto = self._row_to_dto(row, parent_code_map)
            await self._audit_db(
                session, legal_entity_id=legal_entity_id, action="create_account",
                account_id=row.id, account_code=account_code, actor_id=created_by,
                details={
                    "account_name": account_name, "account_type": account_type,
                    "normal_balance": normal_balance, "parent_account_code": parent_account_code,
                    "is_header": is_header, "allow_posting": row.allow_posting,
                    "opening_balance": str(opening), "currency_code": row.currency_code,
                },
            )
            await self._uow.commit()

        self._stats["accounts_created"] += 1
        self._record_audit("create_account", row.id, created_by, {"account_code": account_code})
        return dto

    # ==================== READ ====================

    async def get_account_by_id(self, account_id: UUID, legal_entity_id: UUID) -> AccountDTO | None:
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, account_id, legal_entity_id)
            except AccountNotFoundError:
                return None
            parent_code_map = await self._parent_code_map(session, [row])
            usage_map = await self._usage_map_for_codes(session, legal_entity_id, [row.account_code])
        return self._row_to_dto(row, parent_code_map, usage_map)

    # Alias historis (dipakai sebagian kode lama / test) — sama dengan get_account_by_id.
    get_account = get_account_by_id

    async def get_account_by_code(self, account_code: str, legal_entity_id: UUID) -> AccountDTO | None:
        from infrastructure.persistence_orm.account_table import AccountTable

        async with self._uow:
            session = self._uow.session
            result = await session.execute(
                select(AccountTable).where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.account_code == account_code.upper(),
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            parent_code_map = await self._parent_code_map(session, [row])
            usage_map = await self._usage_map_for_codes(session, legal_entity_id, [row.account_code])
        return self._row_to_dto(row, parent_code_map, usage_map)

    async def list_accounts_raw(
        self,
        legal_entity_id: UUID,
        account_type: str | None = None,
        status: str | None = None,
        include_inactive: bool = True,
    ) -> list[AccountDTO]:
        """Ambil SEMUA akun yang cocok filter, TANPA pagination — dipakai oleh
        use case internal (mis. post_closing_journal.py) yang butuh iterasi
        atas seluruh akun suatu tipe, bukan satu halaman."""
        result = await self.list_accounts(
            legal_entity_id=legal_entity_id,
            account_type=account_type,
            status=status,
            include_inactive=include_inactive,
            page=1,
            page_size=100_000,
        )
        return result.items

    async def list_accounts(
        self,
        legal_entity_id: UUID,
        account_type: str | None = None,
        status: str | None = None,
        parent_account_code: str | None = None,
        is_header: bool | None = None,
        allow_posting: bool | None = None,
        account_group: str | None = None,
        level: int | None = None,
        search: str | None = None,
        include_inactive: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> AccountListResult:
        """List akun dengan filter dan pagination. Dipakai oleh
        GET /coa/chart-of-accounts/accounts dan berbagai endpoint turunan
        (/active, /header, /posting, /by-type, /by-parent, /search)."""
        from infrastructure.persistence_orm.account_table import AccountTable

        page = max(page, 1)
        page_size = max(page_size, 1)

        async with self._uow:
            session = self._uow.session

            conditions = [
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            ]
            if account_type:
                # Perbandingan case-insensitive: beberapa pemanggil lama
                # (mis. use_cases/post_closing_journal.py) mengirim
                # "REVENUE"/"EXPENSE" huruf besar, sedangkan DB menyimpan
                # "Revenue"/"Expense". Strict == di sini akan diam-diam
                # mengembalikan 0 baris dan merusak proses closing period.
                conditions.append(func.lower(AccountTable.account_type) == account_type.lower())
            if status:
                conditions.append(func.lower(AccountTable.status) == status.lower())
            elif not include_inactive:
                conditions.append(AccountTable.status == "active")
            if parent_account_code:
                conditions.append(
                    AccountTable.parent_account_id.in_(
                        select(AccountTable.id).where(
                            AccountTable.account_code == parent_account_code,
                            AccountTable.legal_entity_id == legal_entity_id,
                        )
                    )
                )
            if is_header is not None:
                conditions.append(AccountTable.is_header == is_header)
            if allow_posting is not None:
                conditions.append(AccountTable.allow_posting == allow_posting)
            if account_group:
                conditions.append(AccountTable.account_group == account_group)
            if level is not None:
                conditions.append(AccountTable.level == level)
            if search:
                like = f"%{search}%"
                conditions.append(
                    or_(
                        AccountTable.account_code.ilike(like),
                        AccountTable.account_name.ilike(like),
                        AccountTable.account_name_en.ilike(like),
                    )
                )

            count_stmt = select(func.count()).select_from(AccountTable).where(*conditions)
            total = (await session.execute(count_stmt)).scalar_one()

            stmt = (
                select(AccountTable)
                .where(*conditions)
                .order_by(AccountTable.sort_order, AccountTable.account_code)
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
            rows = (await session.execute(stmt)).scalars().all()

            parent_code_map = await self._parent_code_map(session, rows)
            # BUGFIX: sebelumnya list_accounts tidak menghitung usage_map,
            # sehingga current_balance SELALU 0 dan is_used_in_transaction
            # SELALU False di daftar akun (Total Aset/Kewajiban/dst di layar
            # COA selalu Rp 0 walau jurnal sudah diposting).
            usage_map = await self._usage_map_for_codes(
                session, legal_entity_id, [r.account_code for r in rows]
            )

        items = [self._row_to_dto(r, parent_code_map, usage_map) for r in rows]
        return AccountListResult(items=items, total=total)

    async def get_account_hierarchy(
        self, legal_entity_id: UUID, include_inactive: bool = False
    ) -> AccountTreeResult:
        """Bangun tree lengkap dari SEMUA akun (untuk tampilan Tree View di
        frontend). Dipakai oleh GET /coa/chart-of-accounts/tree."""
        from infrastructure.persistence_orm.account_table import AccountTable

        async with self._uow:
            session = self._uow.session
            conditions = [
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.deleted_at.is_(None),
            ]
            if not include_inactive:
                conditions.append(AccountTable.status == "active")
            stmt = (
                select(AccountTable)
                .where(*conditions)
                .order_by(AccountTable.sort_order, AccountTable.account_code)
            )
            rows = (await session.execute(stmt)).scalars().all()
            parent_code_map = await self._parent_code_map(session, rows)
            usage_map = await self._usage_map_for_codes(
                session, legal_entity_id, [r.account_code for r in rows]
            )

        dto_by_id: dict[UUID, AccountDTO] = {}
        for r in rows:
            dto = self._row_to_dto(r, parent_code_map, usage_map)
            dto.children = []
            dto_by_id[dto.id] = dto

        roots: list[AccountDTO] = []
        max_level = 0
        for r in rows:
            dto = dto_by_id[r.id]
            max_level = max(max_level, dto.level)
            if r.parent_account_id and r.parent_account_id in dto_by_id:
                dto_by_id[r.parent_account_id].children.append(dto)
            else:
                roots.append(dto)

        flattened = list(dto_by_id.values())
        return AccountTreeResult(root_accounts=roots, flattened=flattened, total_levels=max_level + 1)

    async def get_account_balance(
        self, account_id: UUID, legal_entity_id: UUID, as_of_date: datetime
    ) -> AccountBalanceDTO | None:
        from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
        from infrastructure.persistence_orm.journal_line_table import JournalLineTable

        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, account_id, legal_entity_id)
            except AccountNotFoundError:
                return None

            stmt = (
                select(
                    func.coalesce(func.sum(JournalLineTable.debit_amount), 0),
                    func.coalesce(func.sum(JournalLineTable.credit_amount), 0),
                )
                .join(JournalHeaderTable, JournalHeaderTable.id == JournalLineTable.journal_id)
                .where(
                    JournalLineTable.legal_entity_id == legal_entity_id,
                    JournalLineTable.account_code == row.account_code,
                    JournalHeaderTable.status.in_(("posted", "reversed")),
                    JournalHeaderTable.journal_date <= as_of_date.date(),
                    JournalLineTable.deleted_at.is_(None),
                )
            )
            debit_movement, credit_movement = (await session.execute(stmt)).one()

        debit_movement = Decimal(debit_movement)
        credit_movement = Decimal(credit_movement)
        opening = row.opening_balance
        if row.normal_balance == "debit":
            balance = opening + debit_movement - credit_movement
        else:
            balance = opening + credit_movement - debit_movement

        return AccountBalanceDTO(
            account_code=row.account_code,
            account_name=row.account_name,
            balance=balance,
            normal_balance=row.normal_balance,
            is_debit_balance=balance >= 0 if row.normal_balance == "debit" else balance < 0,
            opening_balance=opening,
            debit_movement=debit_movement,
            credit_movement=credit_movement,
        )

    async def get_account_usage(self, account_id: UUID, legal_entity_id: UUID) -> AccountUsageDTO | None:
        from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
        from infrastructure.persistence_orm.journal_line_table import JournalLineTable

        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, account_id, legal_entity_id)
            except AccountNotFoundError:
                return None

            stmt = (
                select(
                    func.count(JournalLineTable.id),
                    func.max(JournalHeaderTable.journal_date),
                    func.coalesce(func.sum(JournalLineTable.debit_amount), 0),
                    func.coalesce(func.sum(JournalLineTable.credit_amount), 0),
                )
                .join(JournalHeaderTable, JournalHeaderTable.id == JournalLineTable.journal_id)
                .where(
                    JournalLineTable.legal_entity_id == legal_entity_id,
                    JournalLineTable.account_code == row.account_code,
                    JournalLineTable.deleted_at.is_(None),
                )
            )
            count, last_used, total_debit, total_credit = (await session.execute(stmt)).one()

        return AccountUsageDTO(
            account_code=row.account_code,
            account_name=row.account_name,
            journal_count=count or 0,
            last_used_at=datetime.combine(last_used, datetime.min.time()).replace(tzinfo=UTC) if last_used else None,
            total_debit=Decimal(total_debit),
            total_credit=Decimal(total_credit),
            is_used_in_journal=bool(count),
            is_used_in_budget=row.budget_control,
            is_used_in_tax=bool(row.tax_code),
        )

    # ==================== UPDATE ====================

    @audit
    async def update_account_write(
        self,
        *,
        account_id: UUID,
        legal_entity_id: UUID,
        account_name: str | None,
        description: str | None,
        status: str | None,
        parent_account_code: str | None,
        currency_code: str | None,
        is_bank_account: bool | None,
        is_cash_account: bool | None,
        is_intercompany: bool | None,
        category: str | None = None,
        budget_control: bool | None = None,
        account_name_en: str | None = None,
        account_group: str | None = None,
        tax_code: str | None = None,
        cashflow_type: str | None = None,
        allow_posting: bool | None = None,
        reconciliation_required: bool | None = None,
        sort_order: int | None = None,
        updated_by: UUID,
    ) -> AccountDTO:
        self._check_authority(updated_by, "update_account")
        account_group = account_group if account_group is not None else category

        from infrastructure.persistence_orm.account_table import AccountTable

        async with self._uow:
            session = self._uow.session
            row = await self._get_row_or_raise(session, account_id, legal_entity_id)

            if row.is_locked:
                raise AccountLockedError(f"Account {row.account_code} is locked: {row.lock_reason or ''}")

            changes: dict[str, Any] = {}

            def _apply(field_name: str, value: Any) -> None:
                if value is None:
                    return
                old = getattr(row, field_name)
                if old != value:
                    changes[field_name] = {"old": old, "new": value}
                    setattr(row, field_name, value)

            _apply("account_name", account_name)
            _apply("account_name_en", account_name_en)
            _apply("description", description)
            _apply("currency_code", currency_code)
            _apply("is_bank_account", is_bank_account)
            _apply("is_cash_account", is_cash_account)
            _apply("is_intercompany", is_intercompany)
            _apply("budget_control", budget_control)
            _apply("account_group", account_group)
            _apply("tax_code", tax_code)
            _apply("cashflow_type", cashflow_type)
            _apply("reconciliation_required", reconciliation_required)
            _apply("sort_order", sort_order)
            if allow_posting is not None and not row.is_header:
                if allow_posting is True:
                    child_count = (await session.execute(
                        select(func.count()).select_from(AccountTable).where(
                            AccountTable.parent_account_id == row.id
                        )
                    )).scalar_one()
                    if child_count > 0:
                        raise PostingAccountCannotHaveChildrenError(
                            f"Account {row.account_code} already has {child_count} child account(s); "
                            "cannot set allow_posting=true. Move or remove the children first."
                        )
                _apply("allow_posting", allow_posting)

            if status is not None and status != row.status:
                changes["status"] = {"old": row.status, "new": status}
                row.status = status
                row.is_active = status == "active"

            parent_code_map: dict[UUID, str] = {}
            if parent_account_code is not None:
                if parent_account_code == "":
                    if row.parent_account_id is not None:
                        changes["parent_account_id"] = {"old": row.parent_account_id, "new": None}
                        row.parent_account_id = None
                        row.level = 0
                        await self._relevel_descendants(session, row.id, 0)
                else:
                    presult = await session.execute(
                        select(AccountTable.id, AccountTable.level, AccountTable.allow_posting).where(
                            AccountTable.legal_entity_id == legal_entity_id,
                            AccountTable.account_code == parent_account_code,
                        )
                    )
                    prow = presult.first()
                    if not prow:
                        raise InvalidParentAccountError(f"Parent account '{parent_account_code}' not found")
                    if prow[0] == account_id:
                        raise AccountCycleDetectedError("Account cannot be its own parent")
                    if prow[2]:
                        raise PostingAccountCannotHaveChildrenError(
                            f"Parent account '{parent_account_code}' is a posting account "
                            "(allow_posting=true) and cannot have child accounts."
                        )
                    if await self._would_create_cycle(session, account_id, prow[0]):
                        raise AccountCycleDetectedError("Moving account would create a cycle")
                    changes["parent_account_id"] = {"old": row.parent_account_id, "new": prow[0]}
                    row.parent_account_id = prow[0]
                    row.level = prow[1] + 1
                    await self._relevel_descendants(session, row.id, row.level)
                    parent_code_map = {prow[0]: parent_account_code}

            if not changes:
                await self._uow.commit()
                full_parent_map = await self._parent_code_map(session, [row])
                return self._row_to_dto(row, full_parent_map)

            await session.flush()
            # updated_at pakai onupdate=func.now() (server-side), jadi
            # expired setelah flush() -- refresh sebelum diakses sync di
            # _row_to_dto, kalau tidak akan MissingGreenlet.
            await session.refresh(row)

            if row.parent_account_id and row.parent_account_id not in parent_code_map:
                full_parent_map = await self._parent_code_map(session, [row])
                parent_code_map.update(full_parent_map)

            dto = self._row_to_dto(row, parent_code_map)
            await self._audit_db(
                session, legal_entity_id=legal_entity_id, action="update_account",
                account_id=row.id, account_code=row.account_code, actor_id=updated_by,
                details={"changes": changes},
            )
            await self._uow.commit()

        self._stats["accounts_updated"] += 1
        self._record_audit("update_account", account_id, updated_by, {"changes": changes})
        return dto

    # Alias historis dipakai beberapa pemanggil lama.
    update_account = update_account_write

    async def _relevel_descendants(self, session: Any, account_id: UUID, level: int) -> None:
        """Hitung ulang `level` SEMUA keturunan (anak, cucu, dst) setelah sebuah
        akun dipindah induknya. Sebelumnya hanya akun yang dipindah yang
        di-update, sehingga sub-akunnya tetap memakai level lama (data hirarki
        tidak konsisten, filter level & ekspor salah)."""
        from infrastructure.persistence_orm.account_table import AccountTable

        frontier = [(account_id, level)]
        visited: set[UUID] = {account_id}
        while frontier:
            parent_id, parent_level = frontier.pop()
            result = await session.execute(
                select(AccountTable).where(AccountTable.parent_account_id == parent_id)
            )
            for child in result.scalars().all():
                if child.id in visited:
                    continue
                visited.add(child.id)
                child.level = parent_level + 1
                frontier.append((child.id, child.level))

    async def _would_create_cycle(self, session: Any, account_id: UUID, new_parent_id: UUID) -> bool:
        from infrastructure.persistence_orm.account_table import AccountTable

        if account_id == new_parent_id:
            return True
        current = new_parent_id
        visited: set[UUID] = set()
        while current and current not in visited:
            if current == account_id:
                return True
            visited.add(current)
            result = await session.execute(
                select(AccountTable.parent_account_id).where(AccountTable.id == current)
            )
            row = result.scalar_one_or_none()
            current = row
        return False

    # ==================== STATUS TRANSITIONS ====================

    async def _transition(
        self,
        account_id: UUID,
        user_id: UUID,
        legal_entity_id: UUID,
        *,
        new_status: str | None = None,
        lock: bool | None = None,
        reason: str | None = None,
        require_no_usage: bool = False,
        require_no_active_children: bool = False,
    ) -> AccountDTO | None:
        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, account_id, legal_entity_id)
            except AccountNotFoundError:
                return None

            if require_no_usage:
                usage = await self._usage_map_for_codes(session, legal_entity_id, [row.account_code])
                used, _ = usage.get(row.account_code, (False, Decimal("0")))
                if used:
                    raise AccountHasTransactionsError(
                        f"Account {row.account_code} sudah dipakai transaksi dan tidak bisa dihapus permanen"
                    )
                if await self._has_children(session, row.id):
                    raise AccountHasChildrenError(
                        f"Account {row.account_code} masih punya sub-akun, pindahkan/hapus dulu sub-akunnya"
                    )

            old_status, old_locked = row.status, row.is_locked
            if require_no_active_children:
                from infrastructure.persistence_orm.account_table import AccountTable

                active_children = (await session.execute(
                    select(func.count()).select_from(AccountTable).where(
                        AccountTable.parent_account_id == row.id,
                        AccountTable.status == "active",
                    )
                )).scalar_one()
                if active_children:
                    raise AccountHasChildrenError(
                        f"Account {row.account_code} masih punya {active_children} sub-akun aktif; "
                        "nonaktifkan/arsipkan sub-akunnya dulu"
                    )

            if new_status is not None:
                row.status = new_status
                row.is_active = new_status == "active"
            if lock is True:
                row.is_locked = True
                row.lock_reason = reason
            elif lock is False:
                row.is_locked = False
                row.lock_reason = None

            await session.flush()
            await session.refresh(row)
            parent_code_map = await self._parent_code_map(session, [row])
            dto = self._row_to_dto(row, parent_code_map)
            if lock is True:
                t_action = "lock_account"
            elif lock is False:
                t_action = "unlock_account"
            else:
                t_action = {
                    "archived": "void_account", "inactive": "deactivate_account", "active": "activate_account",
                }.get(new_status or "", "status_change")
            await self._audit_db(
                session, legal_entity_id=legal_entity_id, action=t_action,
                account_id=row.id, account_code=row.account_code, actor_id=user_id, reason=reason,
                field_name="is_locked" if lock is not None else "status",
                old_value=old_locked if lock is not None else old_status,
                new_value=row.is_locked if lock is not None else row.status,
                details={"reason": reason},
            )
            await self._uow.commit()
        return dto

    @audit
    async def deactivate_account(
        self, account_id: UUID, user_id: UUID, legal_entity_id: UUID, reason: str | None = None
    ) -> AccountDTO | None:
        self._check_authority(user_id, "deactivate_account")
        dto = await self._transition(account_id, user_id, legal_entity_id, new_status="inactive")
        if dto:
            self._stats["accounts_deactivated"] += 1
            self._record_audit("deactivate_account", account_id, user_id, {"reason": reason}, reason=reason)
        return dto

    @audit
    async def activate_account(self, account_id: UUID, user_id: UUID, legal_entity_id: UUID) -> AccountDTO | None:
        self._check_authority(user_id, "activate_account")
        dto = await self._transition(account_id, user_id, legal_entity_id, new_status="active")
        if dto:
            self._record_audit("activate_account", account_id, user_id, {})
        return dto

    @audit
    async def void_account(
        self, account_id: UUID, user_id: UUID, legal_entity_id: UUID, reason: str | None = None
    ) -> AccountDTO | None:
        """Nonaktifkan permanen (arsip). Ditolak kalau masih dipakai transaksi
        atau masih punya sub-akun — akun COA yang sudah dipakai TIDAK PERNAH
        benar-benar dihapus dari database, hanya diarsipkan (soft delete)."""
        self._check_authority(user_id, "void_account")
        self._require_approval_ctx("void_account")
        dto = await self._transition(
            account_id, user_id, legal_entity_id, new_status="archived", require_no_active_children=True
        )
        if dto:
            self._record_audit("void_account", account_id, user_id, {"reason": reason}, reason=reason)
        return dto

    @audit
    async def lock_account(
        self, account_id: UUID, user_id: UUID, legal_entity_id: UUID, reason: str | None = None
    ) -> AccountDTO | None:
        self._check_authority(user_id, "lock_account")
        dto = await self._transition(account_id, user_id, legal_entity_id, lock=True, reason=reason)
        if dto:
            self._record_audit("lock_account", account_id, user_id, {"reason": reason}, reason=reason)
        return dto

    @audit
    async def unlock_account(self, account_id: UUID, user_id: UUID, legal_entity_id: UUID) -> AccountDTO | None:
        self._check_authority(user_id, "unlock_account")
        self._require_approval_ctx("unlock_account")
        dto = await self._transition(account_id, user_id, legal_entity_id, lock=False)
        if dto:
            self._record_audit("unlock_account", account_id, user_id, {})
        return dto

    async def delete_account(
        self, account_id: UUID, user_id: UUID, legal_entity_id: UUID, reason: str | None = None
    ) -> bool:
        """Hard delete — HANYA berhasil jika akun belum pernah dipakai
        transaksi dan tidak punya sub-akun. Ini yang dipanggil dari endpoint
        DELETE ketika ?permanent=true DAN akun benar-benar 'bersih'; kalau
        tidak, router akan otomatis fallback ke void_account (arsip)."""

        self._check_authority(user_id, "delete_account")
        self._require_approval_ctx("delete_account")
        async with self._uow:
            session = self._uow.session
            row = await self._get_row_or_raise(session, account_id, legal_entity_id)
            # Hard delete juga harus ditolak kalau ada jurnal DRAFT/submitted/approved
            # yang memakai akun ini (bukan cuma yang sudah posted) -- kalau tidak,
            # baris jurnal itu jadi yatim / ditolak foreign key (error 500).
            usage = await self._usage_map_for_codes(
                session, legal_entity_id, [row.account_code],
                statuses=("draft", "submitted", "approved", "posted", "reversed"),
            )
            used, _ = usage.get(row.account_code, (False, Decimal("0")))
            if used:
                raise AccountHasTransactionsError(f"Account {row.account_code} sudah dipakai transaksi")
            if await self._has_children(session, row.id):
                raise AccountHasChildrenError(f"Account {row.account_code} masih punya sub-akun")
            await self._audit_db(
                session, legal_entity_id=legal_entity_id, action="delete_account",
                account_id=row.id, account_code=row.account_code, actor_id=user_id, reason=reason,
                details={
                    "account_name": row.account_name, "account_type": row.account_type,
                    "normal_balance": row.normal_balance, "reason": reason,
                },
            )
            await session.delete(row)
            await self._uow.commit()
        self._record_audit("delete_account", account_id, user_id, {"reason": reason}, reason=reason)
        return True

    # ==================== VALIDATION ====================

    async def validate_account_modification(
        self, account_id: UUID, legal_entity_id: UUID, action: str
    ) -> ValidationResultDTO:
        errors: list[str] = []
        warnings: list[str] = []
        suggestions: list[str] = []

        async with self._uow:
            session = self._uow.session
            try:
                row = await self._get_row_or_raise(session, account_id, legal_entity_id)
            except AccountNotFoundError:
                return ValidationResultDTO(is_valid=False, errors=["Account not found"])

            usage = await self._usage_map_for_codes(session, legal_entity_id, [row.account_code])
            used, balance = usage.get(row.account_code, (False, Decimal("0")))

            if row.is_locked:
                errors.append(f"Account is locked: {row.lock_reason or 'no reason given'}")

            if action == "delete":
                if used:
                    errors.append("Account has posted journal transactions and cannot be permanently deleted")
                    suggestions.append("Use deactivate instead of permanent delete")
                if await self._has_children(session, row.id):
                    errors.append("Account has child accounts; move or delete children first")
            elif action == "deactivate":
                if balance != 0:
                    warnings.append(f"Account still has a non-zero balance ({balance})")
            elif action == "update":
                if used:
                    warnings.append("Account already used in posted journals; changing type/normal balance is unsafe")

        return ValidationResultDTO(
            is_valid=len(errors) == 0, errors=errors, warnings=warnings, suggestions=suggestions
        )

    async def validate_account_code(self, account_code: str, legal_entity_id: UUID) -> ValidationResultDTO:
        from infrastructure.persistence_orm.account_table import AccountTable

        errors: list[str] = []
        warnings: list[str] = []
        suggestions: list[str] = []

        code = (account_code or "").strip().upper()
        if not code:
            errors.append("Account code is required")
        elif not code.replace("-", "").replace(".", "").isdigit():
            errors.append("Account code must contain digits and optional hyphens/periods")

        if not errors:
            async with self._uow:
                session = self._uow.session
                existing = await session.execute(
                    select(AccountTable.id).where(
                        AccountTable.legal_entity_id == legal_entity_id,
                        AccountTable.account_code == code,
                    )
                )
                if existing.scalar_one_or_none():
                    errors.append(f"Account code '{code}' already exists")

            first_digit = code[0] if code else ""
            matched_type = next(
                (t for t, prefixes in ACCOUNT_TYPE_PREFIXES.items() if first_digit in prefixes), None
            )
            if matched_type:
                suggestions.append(f"Suggested account type based on prefix: {matched_type}")
            else:
                warnings.append("Account code prefix does not match a known account type convention (1xxx-6xxx)")

        return ValidationResultDTO(
            is_valid=len(errors) == 0, errors=errors, warnings=warnings, suggestions=suggestions
        )

    # ==================== BULK OPERATIONS ====================

    async def bulk_update_status(
        self,
        account_ids: list[UUID],
        status: str,
        reason: str | None,
        updated_by: UUID,
        legal_entity_id: UUID,
    ) -> BulkOperationResultDTO:
        self._check_authority(updated_by, "bulk_update_status")
        success = 0
        failed_ids: list[UUID] = []
        errors: list[str] = []
        for account_id in account_ids:
            try:
                result = await self._transition(account_id, updated_by, legal_entity_id, new_status=status)
                if result is None:
                    raise AccountNotFoundError(str(account_id))
                success += 1
            except Exception as exc:
                failed_ids.append(account_id)
                errors.append(f"{account_id}: {exc}")
        self._record_audit(
            "bulk_update_status", None, updated_by,
            {"status": status, "reason": reason, "count": len(account_ids), "success": success},
        )
        return BulkOperationResultDTO(
            total=len(account_ids), success_count=success, failed_count=len(failed_ids),
            failed_ids=failed_ids, errors=errors,
        )

    async def bulk_update_parent(
        self,
        account_ids: list[UUID],
        parent_account_code: str | None,
        updated_by: UUID,
        legal_entity_id: UUID,
    ) -> BulkOperationResultDTO:
        self._check_authority(updated_by, "bulk_update_parent")
        success = 0
        failed_ids: list[UUID] = []
        errors: list[str] = []
        for account_id in account_ids:
            try:
                await self.update_account_write(
                    account_id=account_id,
                    legal_entity_id=legal_entity_id,
                    account_name=None,
                    description=None,
                    status=None,
                    parent_account_code=parent_account_code or "",
                    currency_code=None,
                    is_bank_account=None,
                    is_cash_account=None,
                    is_intercompany=None,
                    updated_by=updated_by,
                )
                success += 1
            except Exception as exc:
                failed_ids.append(account_id)
                errors.append(f"{account_id}: {exc}")
        self._record_audit(
            "bulk_update_parent", None, updated_by,
            {"parent_account_code": parent_account_code, "count": len(account_ids), "success": success},
        )
        return BulkOperationResultDTO(
            total=len(account_ids), success_count=success, failed_count=len(failed_ids),
            failed_ids=failed_ids, errors=errors,
        )

    # ==================== MAKER-CHECKER (PERSETUJUAN) ====================

    @property
    def maker_checker_enabled(self) -> bool:
        """Default AKTIF. Matikan hanya untuk deployment satu-pengguna: COA_MAKER_CHECKER=0."""
        return os.environ.get("COA_MAKER_CHECKER", "1").strip().lower() not in ("0", "false", "off", "no")

    def _require_approval_ctx(self, what: str) -> None:
        if self.maker_checker_enabled and not _APPROVAL_EXEC.get():
            raise COAApprovalRequiredError(
                f"Aksi '{what}' wajib diajukan sebagai permintaan perubahan dan disetujui pengguna lain."
            )

    async def _ensure_cr_table(self, session: Any) -> None:
        if COAService._cr_table_ready:
            return
        exists = (await session.execute(text("SELECT to_regclass('public.coa_change_request')"))).scalar()
        if exists is None:
            for stmt in _COA_CR_DDL:
                await session.execute(text(stmt))
        COAService._cr_table_ready = True

    _cr_table_ready: bool = False

    @staticmethod
    def _cr_dict(r: Any) -> dict[str, Any]:
        return {
            "id": str(r.id), "account_id": str(r.account_id), "account_code": r.account_code,
            "action": r.action, "reason": r.reason, "status": r.status,
            "requested_by": str(r.requested_by), "requested_at": r.requested_at,
            "decided_by": str(r.decided_by) if r.decided_by else None, "decided_at": r.decided_at,
            "decision_note": r.decision_note,
        }

    async def submit_change_request(
        self, action: str, account_id: UUID, legal_entity_id: UUID, user_id: UUID, reason: str | None = None
    ) -> dict[str, Any]:
        self._check_authority(user_id, "update_account")
        if action not in ("delete", "unlock"):
            raise ValueError(f"Aksi permintaan tidak dikenal: {action}")
        if action == "delete" and not (reason or "").strip():
            raise ValueError("Alasan wajib diisi untuk permintaan hapus/arsip akun.")
        async with self._uow:
            session = self._uow.session
            row = await self._get_row_or_raise(session, account_id, legal_entity_id)
            await self._ensure_cr_table(session)
            dup = (await session.execute(
                text("SELECT 1 FROM coa_change_request WHERE account_id=:a AND action=:ac "
                     "AND status IN ('pending','processing')"), {"a": account_id, "ac": action},
            )).first()
            if dup:
                raise ValueError(f"Sudah ada permintaan '{action}' yang menunggu persetujuan untuk akun ini.")
            rid = uuid4()
            res = await session.execute(
                text("INSERT INTO coa_change_request (id, legal_entity_id, account_id, account_code, action, "
                     "reason, requested_by) VALUES (:id,:le,:a,:c,:ac,:r,:u) RETURNING *"),
                {"id": rid, "le": legal_entity_id, "a": account_id, "c": row.account_code,
                 "ac": action, "r": (reason or "")[:500] or None, "u": user_id},
            )
            created = res.one()
            await self._audit_db(
                session, legal_entity_id=legal_entity_id, action="change_requested",
                account_id=account_id, account_code=row.account_code, actor_id=user_id, reason=reason,
                details={"request_id": str(rid), "requested_action": action},
            )
            await self._uow.commit()
            return self._cr_dict(created)

    async def list_change_requests(
        self, legal_entity_id: UUID, status: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        async with self._uow:
            session = self._uow.session
            await self._ensure_cr_table(session)
            sql = "SELECT * FROM coa_change_request WHERE legal_entity_id=:le"
            params: dict[str, Any] = {"le": legal_entity_id, "lim": min(max(limit, 1), 1000)}
            if status:
                sql += " AND status=:st"
                params["st"] = status
            sql += " ORDER BY requested_at DESC LIMIT :lim"
            out = [self._cr_dict(r) for r in (await session.execute(text(sql), params)).all()]
        names = await self._actor_names(
            {UUID(x[k]) for x in out for k in ("requested_by", "decided_by") if x.get(k)}
        )
        for x in out:
            x["requested_by_name"] = names.get(UUID(x["requested_by"])) if x.get("requested_by") else None
            x["decided_by_name"] = names.get(UUID(x["decided_by"])) if x.get("decided_by") else None
        return out

    async def _claim_cr(self, request_id: UUID, legal_entity_id: UUID, new_status: str, user_id: UUID,
                        note: str | None, require_other: bool, require_same: bool = False) -> Any:
        """Ubah status dari 'pending' secara atomik (cegah dua pemutus bersamaan)."""
        async with self._uow:
            session = self._uow.session
            await self._ensure_cr_table(session)
            cur = (await session.execute(
                text("SELECT * FROM coa_change_request WHERE id=:id AND legal_entity_id=:le FOR UPDATE"),
                {"id": request_id, "le": legal_entity_id},
            )).first()
            if cur is None:
                raise AccountNotFoundError(f"Permintaan {request_id} tidak ditemukan")
            if cur.status != "pending":
                raise ValueError(f"Permintaan sudah berstatus '{cur.status}'.")
            if require_other and cur.requested_by == user_id:
                raise COAAuthorizationError(
                    "Pemisahan tugas (SoD): pengaju tidak boleh memutuskan permintaannya sendiri."
                )
            if require_same and cur.requested_by != user_id:
                raise COAAuthorizationError("Hanya pengaju yang dapat membatalkan permintaannya.")
            await session.execute(
                text("UPDATE coa_change_request SET status=:st, decided_by=:u, decided_at=now(), "
                     "decision_note=:n WHERE id=:id"),
                {"st": new_status, "u": user_id, "n": (note or "")[:500] or None, "id": request_id},
            )
            if new_status in ("rejected", "cancelled"):
                await self._audit_db(
                    session, legal_entity_id=legal_entity_id, action=f"change_{new_status}",
                    account_id=cur.account_id, account_code=cur.account_code, actor_id=user_id, reason=note,
                    details={"request_id": str(request_id), "requested_action": cur.action,
                             "requested_by": str(cur.requested_by)},
                )
            await self._uow.commit()
            return cur

    async def reject_change_request(self, request_id: UUID, legal_entity_id: UUID, user_id: UUID,
                                    note: str | None = None) -> dict[str, Any]:
        self._check_authority(user_id, "update_account")
        await self._claim_cr(request_id, legal_entity_id, "rejected", user_id, note, require_other=True)
        return {"id": str(request_id), "status": "rejected"}

    async def cancel_change_request(self, request_id: UUID, legal_entity_id: UUID, user_id: UUID) -> dict[str, Any]:
        self._check_authority(user_id, "update_account")
        await self._claim_cr(request_id, legal_entity_id, "cancelled", user_id, None,
                             require_other=False, require_same=True)
        return {"id": str(request_id), "status": "cancelled"}

    async def approve_change_request(self, request_id: UUID, legal_entity_id: UUID, approver_id: UUID,
                                     note: str | None = None) -> dict[str, Any]:
        self._check_authority(approver_id, "update_account")
        cur = await self._claim_cr(request_id, legal_entity_id, "processing", approver_id, note, require_other=True)
        token = _APPROVAL_EXEC.set(True)
        outcome = ""
        try:
            if cur.action == "unlock":
                await self.unlock_account(cur.account_id, approver_id, legal_entity_id)
                outcome = "Akun dibuka kuncinya."
            else:
                try:
                    await self.delete_account(cur.account_id, approver_id, legal_entity_id, cur.reason)
                    outcome = "Akun dihapus permanen."
                except (AccountHasChildrenError, AccountHasTransactionsError):
                    await self.void_account(cur.account_id, approver_id, legal_entity_id, cur.reason)
                    outcome = "Akun sudah dipakai/punya sub-akun; diarsipkan (bukan dihapus permanen)."
        except Exception:
            # eksekusi gagal -> kembalikan ke pending supaya bisa diputuskan ulang
            async with self._uow:
                await self._uow.session.execute(
                    text("UPDATE coa_change_request SET status='pending', decided_by=NULL, decided_at=NULL "
                         "WHERE id=:id"), {"id": request_id})
                await self._uow.commit()
            raise
        finally:
            _APPROVAL_EXEC.reset(token)
        async with self._uow:
            session = self._uow.session
            await session.execute(
                text("UPDATE coa_change_request SET status='approved', decision_note=:n WHERE id=:id"),
                {"id": request_id, "n": (note or outcome)[:500]},
            )
            await self._audit_db(
                session, legal_entity_id=legal_entity_id, action="change_approved",
                account_id=cur.account_id, account_code=cur.account_code, actor_id=approver_id, reason=note,
                details={"request_id": str(request_id), "requested_action": cur.action,
                         "requested_by": str(cur.requested_by), "outcome": outcome},
            )
            await self._uow.commit()
        return {"id": str(request_id), "status": "approved", "message": outcome}

    # ==================== IMPORT / EXPORT ====================

    _EXPORT_COLUMNS = (
        "account_code", "account_name", "account_name_en", "account_type", "account_group",
        "normal_balance", "parent_account_code", "level", "description", "status",
        "currency_code", "is_header", "allow_posting", "budget_control", "tax_code",
        "cashflow_type", "opening_balance",
    )

    @staticmethod
    def _unguard(v: Any) -> Any:
        """Kebalikan guard formula-injection CSV: "'=abc" -> "=abc" (round-trip)."""
        if isinstance(v, str) and len(v) > 1 and v[0] == "'" and v[1] in ("=", "+", "-", "@", "\t", "\r"):
            return v[1:]
        return v

    async def export_coa(self, legal_entity_id: UUID, fmt: str, include_inactive: bool = False) -> bytes:
        fmt = (fmt or "").lower()
        if fmt not in ("json", "csv", "excel", "xlsx"):
            raise ValueError(f"Unsupported export format: {fmt}")
        items = await self.list_accounts_raw(legal_entity_id, include_inactive=include_inactive)
        cols = self._EXPORT_COLUMNS

        def _row(a: Any) -> dict[str, Any]:
            return {
                "account_code": a.account_code, "account_name": a.account_name,
                "account_name_en": a.account_name_en or "", "account_type": a.account_type,
                "account_group": a.account_group or "", "normal_balance": a.normal_balance,
                "parent_account_code": a.parent_account_code or "", "level": a.level,
                "description": a.description or "", "status": a.status,
                "currency_code": a.currency_code, "is_header": bool(a.is_header),
                "allow_posting": bool(a.allow_posting), "budget_control": bool(a.budget_control),
                "tax_code": a.tax_code or "", "cashflow_type": a.cashflow_type or "",
                "opening_balance": Decimal(str(a.opening_balance or 0)),
            }

        rows = [_row(a) for a in items]

        if fmt == "json":
            payload = [
                {**r, "opening_balance": str(r["opening_balance"]),
                 "account_name_en": r["account_name_en"] or None,
                 "parent_account_code": r["parent_account_code"] or None,
                 "description": r["description"] or None, "account_group": r["account_group"] or None,
                 "tax_code": r["tax_code"] or None, "cashflow_type": r["cashflow_type"] or None}
                for r in rows
            ]
            return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

        def _safe(v: Any) -> Any:
            """Cegah CSV/formula injection: sel teks yang diawali = + - @ (atau tab/CR)
            akan dieksekusi sebagai rumus oleh Excel. Diberi awalan apostrof."""
            if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
                return "'" + v
            return v

        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(cols)
            for r in rows:
                writer.writerow([
                    _safe(r[c]) if isinstance(r[c], str) else
                    (str(r[c]) if isinstance(r[c], Decimal) else r[c])
                    for c in cols
                ])
            return buf.getvalue().encode("utf-8-sig")

        # ---- Excel (.xlsx asli) ----
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = "Chart of Accounts"
        ws.append(list(cols))
        head_fill = PatternFill("solid", fgColor="1F3A5F")
        thin = Side(style="thin", color="D0D7E2")
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = head_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
        for r in rows:
            ws.append([
                float(r[c]) if isinstance(r[c], Decimal) else r[c]
                for c in cols
            ])
            row_idx = ws.max_row
            for ci, c in enumerate(cols, start=1):
                cell = ws.cell(row=row_idx, column=ci)
                cell.border = Border(bottom=thin)
                if isinstance(r[c], str) and r[c][:1] in ("=", "+", "-", "@", "\t", "\r"):
                    cell.value = r[c]
                    cell.data_type = "s"          # paksa teks, bukan rumus (setelah value!)
                if c == "opening_balance":
                    cell.number_format = "#,##0.00;[Red]-#,##0.00"
                    cell.alignment = Alignment(horizontal="right")
                if c == "account_code":
                    cell.number_format = "@"
                if r["is_header"]:
                    cell.font = Font(bold=True)
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = ws.dimensions
        for ci, c in enumerate(cols, start=1):
            longest = max([len(str(c))] + [len(str(r[c])) for r in rows[:500]])
            ws.column_dimensions[get_column_letter(ci)].width = min(max(longest + 3, 10), 50)
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    async def import_coa(
        self,
        legal_entity_id: UUID,
        file_content: str | bytes,
        file_format: str,
        mode: str,
        validate_only: bool,
        imported_by: UUID,
    ) -> ImportExportResultDTO:
        self._check_authority(imported_by, "import_coa")

        file_format = (file_format or "").lower().lstrip(".")
        if mode not in ("merge", "replace"):
            raise InvalidBulkImportDataError(f"Mode import tidak dikenal: {mode}")

        def _clean(v: Any) -> Any:
            if isinstance(v, bool) or v is None:
                return v
            if isinstance(v, float) and v.is_integer():
                return str(int(v))
            if isinstance(v, (int, float, Decimal)):
                return str(v)
            if isinstance(v, datetime):
                return v.isoformat()
            if isinstance(v, str):
                return self._unguard(v.strip())
            return str(v)

        def _norm_rows(raw: list[dict[Any, Any]]) -> list[dict[str, Any]]:
            out_rows = []
            for line_no, rec in enumerate(raw, start=2):   # baris 1 = header
                row = {str(k).strip().lower(): _clean(v) for k, v in rec.items() if k is not None}
                if any(v not in (None, "") for v in row.values()):
                    row["_line"] = line_no
                    out_rows.append(row)
            return out_rows

        try:
            if file_format == "json":
                text_in = file_content.decode("utf-8-sig") if isinstance(file_content, bytes) else file_content
                data = json.loads(text_in)
                if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
                    raise InvalidBulkImportDataError("JSON harus berupa array objek akun.")
                rows = _norm_rows(data)
            elif file_format == "csv":
                text_in = file_content.decode("utf-8-sig") if isinstance(file_content, bytes) else file_content
                rows = _norm_rows(list(csv.DictReader(io.StringIO(text_in))))
            elif file_format in ("xlsx", "excel"):
                from openpyxl import load_workbook
                raw_bytes = file_content if isinstance(file_content, bytes) else file_content.encode("latin-1")
                wb = load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
                ws = wb.worksheets[0]
                it = ws.iter_rows(values_only=True)
                header = next(it, None)
                if not header:
                    raise InvalidBulkImportDataError("File Excel kosong.")
                keys = [str(h).strip().lower() if h is not None else None for h in header]
                rows = _norm_rows([dict(zip(keys, rec)) for rec in it])
                wb.close()
            else:
                raise InvalidBulkImportDataError(
                    f"Format import tidak didukung: {file_format} (gunakan csv, xlsx, atau json)"
                )
        except InvalidBulkImportDataError:
            raise
        except Exception as exc:
            raise InvalidBulkImportDataError(f"Gagal membaca file {file_format}: {exc}") from exc

        if not rows:
            raise InvalidBulkImportDataError("File tidak berisi baris data.")
        if "account_code" not in rows[0]:
            raise InvalidBulkImportDataError("Kolom 'account_code' tidak ditemukan di header file.")
        if len(rows) > 20000:
            raise InvalidBulkImportDataError("Maksimal 20.000 baris per import.")

        imported = 0
        updated = 0
        skipped = 0
        errors: list[str] = []

        def _nz(v: Any) -> Any:
            """Sel kosong -> None (jangan menimpa nilai lama dengan "")."""
            if isinstance(v, str):
                v = v.strip()
            return v if v not in ("", None) else None

        _type_map = {t.lower().replace("_", "").replace(" ", ""): t for t in VALID_ACCOUNT_TYPES}

        def _code(r: dict[str, Any]) -> str:
            return str(r.get("account_code") or "").strip().upper()

        def _parent(r: dict[str, Any]) -> str:
            return str(_nz(r.get("parent_account_code")) or "").strip().upper()

        # Urutan: induk yang ada di file diproses sebelum anaknya (topologis),
        # tidak bergantung pada kolom level / panjang kode.
        by_code: dict[str, dict[str, Any]] = {}
        seen_dupe: set[str] = set()
        for r in rows:
            c = _code(r)
            if c in by_code:
                seen_dupe.add(c)
            by_code[c] = r
        ordered: list[dict[str, Any]] = []
        placed: set[str] = set()

        def _visit(r: dict[str, Any], stack: set[str]) -> None:
            c = _code(r)
            if c in placed or c in stack:
                return
            stack.add(c)
            par = _parent(r)
            if par and par in by_code and par != c:
                _visit(by_code[par], stack)
            stack.discard(c)
            placed.add(c)
            ordered.append(r)

        for r in rows:
            if _code(r):
                _visit(r, set())
        rows_sorted = ordered + [r for r in rows if not _code(r)]

        def _validate_row(r: dict[str, Any], existing: Any) -> str | None:
            """Validasi tanpa menulis apa pun. Return pesan error atau None."""
            code = _code(r)
            if code in seen_dupe:
                return "kode akun duplikat di dalam file"
            if existing is None or mode == "replace":
                if existing is None and not _nz(r.get("account_name")):
                    return "account_name wajib diisi"
            if existing is None:
                t = str(r.get("account_type") or "Asset").strip().replace("_", "").replace(" ", "").lower()
                if t not in _type_map:
                    return f"account_type tidak valid: {r.get('account_type')}"
                nb = str(r.get("normal_balance") or "debit").strip().lower()
                if nb not in ("debit", "credit"):
                    return f"normal_balance harus debit/credit, bukan '{nb}'"
            ob = _nz(r.get("opening_balance"))
            if ob is not None:
                try:
                    Decimal(str(ob).replace(",", ""))
                except Exception:
                    return f"opening_balance bukan angka: {ob}"
            par = _parent(r)
            if par:
                if par == code:
                    return "akun tidak boleh menjadi induk dirinya sendiri"
                if par not in by_code and par not in db_codes:
                    return f"akun induk {par} tidak ditemukan (di file maupun di database)"
            return None

        db_codes: set[str] = set()
        if validate_only:
            for a_ in await self.list_accounts_raw(legal_entity_id, include_inactive=True):
                db_codes.add(a_.account_code.upper())

        for idx, r in enumerate(rows_sorted, start=1):
            code = str(r.get("account_code") or "").strip().upper()
            if not code:
                skipped += 1
                errors.append(f"Baris {r.get('_line', idx)}: missing account_code")
                continue
            try:
                existing = await self.get_account_by_code(code, legal_entity_id)
                if validate_only:
                    problem = _validate_row(r, existing)
                    if problem:
                        skipped += 1
                        errors.append(f"Baris {r.get('_line', idx)} ({code}): {problem}")
                    elif not existing:
                        imported += 1
                    elif mode == "replace":
                        updated += 1
                    else:
                        skipped += 1
                    continue

                if existing:
                    if mode == "replace":
                        await self.update_account_write(
                            account_id=existing.id,
                            legal_entity_id=legal_entity_id,
                            account_name=r.get("account_name") or existing.account_name,
                            description=_nz(r.get("description")),
                            status=(_nz(r.get("status")) or "").lower() or None,
                            parent_account_code=(
                                str(_nz(r.get("parent_account_code")) or "").upper()
                                if r.get("parent_account_code") is not None else None
                            ),
                            currency_code=_nz(r.get("currency_code")),
                            is_bank_account=None,
                            is_cash_account=None,
                            is_intercompany=None,
                            account_group=_nz(r.get("account_group")),
                            tax_code=_nz(r.get("tax_code")),
                            cashflow_type=_nz(r.get("cashflow_type")),
                            updated_by=imported_by,
                        )
                        updated += 1
                    else:
                        skipped += 1
                else:
                    await self.create_account_write(
                        legal_entity_id=legal_entity_id,
                        account_code=code,
                        account_name=r.get("account_name") or code,
                        account_type=_type_map.get(
                            str(r.get("account_type") or "Asset").strip().replace("_", "").replace(" ", "").lower(),
                            r.get("account_type") or "Asset",
                        ),
                        normal_balance=str(r.get("normal_balance") or "debit").strip().lower(),
                        parent_account_code=(str(_nz(r.get("parent_account_code")) or "").upper() or None),
                        description=r.get("description"),
                        currency_code=r.get("currency_code") or "IDR",
                        is_bank_account=str(r.get("is_bank_account", "")).lower() in ("true", "1", "yes"),
                        is_cash_account=str(r.get("is_cash_account", "")).lower() in ("true", "1", "yes"),
                        is_intercompany=str(r.get("is_intercompany", "")).lower() in ("true", "1", "yes"),
                        is_header=str(r.get("is_header", "")).lower() in ("true", "1", "yes"),
                        # kolom allow_posting ada di file hasil Export; kalau tidak ada
                        # di file, default tetap True (seperti sebelumnya)
                        allow_posting=(
                            str(r.get("allow_posting")).strip().lower() in ("true", "1", "yes")
                            if _nz(r.get("allow_posting")) is not None else True
                        ),
                        budget_control=str(r.get("budget_control", "")).strip().lower() in ("true", "1", "yes"),
                        level=None,
                        opening_balance=Decimal(str(r.get("opening_balance") or "0").replace(",", "")),
                        account_group=_nz(r.get("account_group")),
                        tax_code=_nz(r.get("tax_code")),
                        cashflow_type=_nz(r.get("cashflow_type")),
                        created_by=imported_by,
                    )
                    imported += 1
            except Exception as exc:
                skipped += 1
                errors.append(f"Baris {r.get('_line', idx)} ({code}): {exc}")

        self._record_audit(
            "import_coa", None, imported_by,
            {"mode": mode, "validate_only": validate_only, "imported": imported, "updated": updated, "skipped": skipped},
        )

        return ImportExportResultDTO(
            success=len(errors) == 0,
            message=(
                "Validasi selesai" if validate_only else "Import selesai"
            ) + f" — {imported} baru, {updated} diperbarui, {skipped} dilewati.",
            imported_count=imported,
            updated_count=updated,
            skipped_count=skipped,
            errors=errors[:200],
        )

    # ==================== HISTORY / AUDIT TRAIL ====================

    async def get_account_history(
        self,
        account_id: UUID,
        legal_entity_id: UUID,
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> list[AccountHistoryEntryDTO]:
        rows = await self._read_audit_rows(
            account_id, legal_entity_id, start_date=start_date, end_date=end_date
        )
        if rows is not None:
            out: list[AccountHistoryEntryDTO] = []
            for r in rows:
                changes = (r.details or {}).get("changes") if isinstance(r.details, dict) else None
                if changes:
                    for fname, ch in changes.items():
                        out.append(AccountHistoryEntryDTO(
                            timestamp=r.occurred_at, action=r.action, field=fname,
                            old_value=ch.get("old") if isinstance(ch, dict) else None,
                            new_value=ch.get("new") if isinstance(ch, dict) else None,
                            actor_id=r.actor_id or UUID(int=0), actor_name=None, reason=r.reason,
                        ))
                else:
                    out.append(AccountHistoryEntryDTO(
                        timestamp=r.occurred_at, action=r.action, field=r.field_name or "-",
                        old_value=r.old_value, new_value=r.new_value,
                        actor_id=r.actor_id or UUID(int=0), actor_name=None, reason=r.reason,
                    ))
            return await self._with_actor_names(sorted(out, key=lambda h: h.timestamp, reverse=True))
        return await self._with_actor_names(self._memory_history(account_id, start_date, end_date))

    async def _with_actor_names(self, entries: list[Any]) -> list[Any]:
        names = await self._actor_names({e.actor_id for e in entries})
        for e in entries:
            e.actor_name = names.get(e.actor_id) or ("Sistem" if e.actor_id == UUID(int=0) else None)
        return entries

    def _memory_history(
        self, account_id: UUID, start_date: datetime | None, end_date: datetime | None
    ) -> list[AccountHistoryEntryDTO]:
        out: list[AccountHistoryEntryDTO] = []
        for entry in self._audit_trail:
            if entry.get("account_id") != str(account_id):
                continue
            ts = entry["timestamp"]
            if start_date and ts < start_date:
                continue
            if end_date and ts > end_date:
                continue
            for field_name, change in (entry.get("details", {}).get("changes") or {}).items():
                out.append(AccountHistoryEntryDTO(
                    timestamp=ts, action=entry["action"], field=field_name,
                    old_value=change.get("old") if isinstance(change, dict) else None,
                    new_value=change.get("new") if isinstance(change, dict) else None,
                    actor_id=UUID(entry["actor_id"]) if entry.get("actor_id") else UUID(int=0),
                    actor_name=None, reason=entry.get("reason"),
                ))
            if entry["action"] not in ("update_account",):
                out.append(AccountHistoryEntryDTO(
                    timestamp=ts, action=entry["action"], field=entry.get("field") or "-",
                    old_value=entry.get("old_value"), new_value=entry.get("new_value"),
                    actor_id=UUID(entry["actor_id"]) if entry.get("actor_id") else UUID(int=0),
                    actor_name=None, reason=entry.get("reason"),
                ))
        return sorted(out, key=lambda h: h.timestamp, reverse=True)

    async def get_account_audit_trail(
        self, account_id: UUID, legal_entity_id: UUID, limit: int = 100
    ) -> list[AccountAuditEntryDTO]:
        rows = await self._read_audit_rows(account_id, legal_entity_id, limit=limit)
        if rows is not None:
            return await self._with_actor_names([
                AccountAuditEntryDTO(
                    timestamp=r.occurred_at, event_type=r.action,
                    event_data=r.details if isinstance(r.details, dict) else {},
                    actor_id=r.actor_id or UUID(int=0), actor_name=None,
                    version=len(rows) - i,
                )
                for i, r in enumerate(rows)
            ])
        out = [
            AccountAuditEntryDTO(
                timestamp=entry["timestamp"], event_type=entry["action"],
                event_data=entry.get("details", {}),
                actor_id=UUID(entry["actor_id"]) if entry.get("actor_id") else UUID(int=0),
                actor_name=None, version=entry.get("version", 1),
            )
            for entry in self._audit_trail
            if entry.get("account_id") == str(account_id)
        ]
        out.sort(key=lambda a: a.timestamp, reverse=True)
        return await self._with_actor_names(out[:limit])

    # ==================== BULK IMPORT (CSV legacy helper) ====================

    async def bulk_import_accounts(
        self,
        legal_entity_id: UUID,
        csv_content: str,
        user_id: UUID,
        correlation_id: str | None = None,
        dry_run: bool = False,
    ) -> ImportExportResultDTO:
        """Kompatibilitas mundur untuk pemanggil lama yang memakai CSV
        mentah alih-alih endpoint /import — didelegasikan ke import_coa."""
        return await self.import_coa(
            legal_entity_id=legal_entity_id,
            file_content=csv_content,
            file_format="csv",
            mode="merge",
            validate_only=dry_run,
            imported_by=user_id,
        )


# ============================================================================
# Factory
# ============================================================================


async def create_coa_service(
    account_repository: AccountRepositoryPort,
    uow: UnitOfWorkPort,
    event_publisher: EventPublisherPort | None = None,
) -> COAService:
    return COAService(account_repository, uow, event_publisher)


__all__ = [
    "AccountAuditEntryDTO",
    "AccountBalanceDTO",
    "AccountCodeAlreadyExistsError",
    "AccountCodeFormatError",
    "AccountCycleDetectedError",
    "AccountDTO",
    "AccountHasChildrenError",
    "AccountHasTransactionsError",
    "AccountHistoryEntryDTO",
    "AccountListResult",
    "AccountLockedError",
    "AccountNotFoundError",
    "AccountTreeResult",
    "AccountUsageDTO",
    "BulkOperationResultDTO",
    "COAService",
    "COAServiceError",
    "ImportExportResultDTO",
    "InvalidAccountTypeHierarchyError",
    "InvalidBulkImportDataError",
    "InvalidParentAccountError",
    "PostingAccountCannotHaveChildrenError",
    "ValidationResultDTO",
    "create_coa_service",
]
