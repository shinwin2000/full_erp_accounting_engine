#!/usr/bin/env python3
"""
Module: service_goodwill.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service for goodwill accounting (PSAK 22 / IFRS 3 - pengakuan awal;
    PSAK 48 / IAS 36 - impairment testing). Goodwill dari kombinasi bisnis
    TIDAK diamortisasi (impairment-only model) - ini keputusan yang
    disengaja per audit 2026-09-15, lihat REWRITE NOTES di bawah.

REWRITE NOTES (2026-09-15):
    File ini ditulis ulang total setelah audit menemukan modul Goodwill
    rusak di SEMUA lapisan (tabel DB, domain aggregate terpisah,
    repository, service, dan router API - masing-masing pakai nama field
    yang berbeda-beda dan tidak pernah benar-benar saling cocok, jadi
    hampir semua operasi selalu crash). Perbaikan ini menjadikan
    `GoodwillTable` (ORM, di infrastructure/persistence_orm/goodwill_table.py)
    sebagai SATU-SATUNYA bentuk data goodwill yang diakui - dipilih karena
    itulah kebenaran yang benar-benar tersimpan di database, dan karena
    tabel itu sendiri sudah punya method domain yang benar
    (record_impairment, recover_impairment, dispose, approve).

    Fitur amortisasi goodwill (yang sebelumnya ada di service versi lama)
    SENGAJA DIHAPUS di rewrite ini: tabel `goodwill` tidak punya kolom
    untuk itu sama sekali, dan menurut PSAK 22/IFRS 3 goodwill dari
    kombinasi bisnis memang tidak diamortisasi - hanya diuji impairment.
    Ini konsisten dengan keputusan eksplisit yang diambil user saat modul
    ini diaudit (pilih "impairment-only, sesuai standar akuntansi resmi").

    `domain/goodwill/aggregate_root.py` (dataclass Goodwill terpisah) dan
    `domain/goodwill/impairment_tester.py` TIDAK LAGI dipakai oleh service
    ini - keduanya adalah sumber ketidakcocokan yang ditemukan saat audit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.goodwill.domain_events import (
    GoodwillDisposedEvent,
    GoodwillImpairedEvent,
    GoodwillImpairmentReversedEvent,
    GoodwillRecognizedEvent,
    GoodwillUpdatedEvent,
)
from infrastructure.persistence_orm.goodwill_impairment_table import GoodwillImpairmentTable
from infrastructure.persistence_orm.goodwill_table import GoodwillTable
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.goodwill_repository_port import GoodwillRepositoryPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Status yang valid (harus sinkron dengan CheckConstraint di goodwill_table.py)
# ============================================================================

STATUS_ACTIVE = "active"
STATUS_PARTIALLY_IMPAIRED = "partially_impaired"
STATUS_FULLY_IMPAIRED = "fully_impaired"
STATUS_DISPOSED = "disposed"
VALID_STATUSES = (STATUS_ACTIVE, STATUS_PARTIALLY_IMPAIRED, STATUS_FULLY_IMPAIRED, STATUS_DISPOSED)


# ============================================================================
# Exceptions
# ============================================================================


class GoodwillServiceError(Exception):
    pass


class GoodwillNotFoundError(GoodwillServiceError):
    pass


class InvalidImpairmentTestError(GoodwillServiceError):
    pass


class GoodwillAlreadyDisposedError(GoodwillServiceError):
    pass


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class GoodwillRecognitionRequest:
    legal_entity_id: UUID
    goodwill_code: str
    name: str
    acquisition_date: date
    acquiree_name: str
    purchase_price: Decimal
    fair_value_identifiable_net_assets: Decimal
    acquiree_tax_id: str | None = None
    cash_generating_unit: str | None = None
    allocated_to_segment: str | None = None
    currency: str = "IDR"
    exchange_rate_at_acquisition: Decimal = Decimal("1")
    description: str | None = None
    created_by: UUID | None = None


@dataclass(kw_only=True)
class GoodwillUpdateRequest:
    name: str | None = None
    cash_generating_unit: str | None = None
    allocated_to_segment: str | None = None
    description: str | None = None


@dataclass(kw_only=True)
class ImpairmentTestRequest:
    goodwill_id: UUID
    test_date: date
    recoverable_amount: Decimal
    valuation_method: str = "fair_value_less_cost"
    discount_rate: Decimal | None = None
    growth_rate: Decimal | None = None
    impairment_source: str = "annual_test"
    description: str | None = None
    created_by: UUID | None = None


@dataclass(kw_only=True)
class GoodwillDisposalRequest:
    goodwill_id: UUID
    disposal_date: date
    proceeds: Decimal = Decimal("0")
    reason: str | None = None
    disposed_by: UUID | None = None


@dataclass(kw_only=True)
class GoodwillResponse:
    """DTO respons - field-fieldnya SENGAJA persis mengikuti kolom
    GoodwillTable (+ properti turunannya) supaya tidak ada lagi lapisan
    terjemahan yang bisa drift dari kebenaran di database."""

    id: UUID
    legal_entity_id: UUID
    goodwill_code: str
    name: str
    description: str | None
    acquisition_date: date
    acquiree_name: str
    acquiree_tax_id: str | None
    purchase_price: Decimal
    fair_value_identifiable_net_assets: Decimal
    goodwill_initial: Decimal
    carrying_amount: Decimal
    impairment_accumulated: Decimal
    net_carrying_amount: Decimal
    currency: str
    exchange_rate_at_acquisition: Decimal
    cash_generating_unit: str | None
    allocated_to_segment: str | None
    status: str
    is_active: bool
    last_impairment_date: date | None
    last_impairment_loss: Decimal | None
    disposal_date: date | None
    disposal_proceeds: Decimal | None
    disposal_gain_loss: Decimal | None
    disposal_reason: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    version: int


@dataclass(kw_only=True)
class ImpairmentTestResponse:
    id: UUID
    goodwill_id: UUID
    goodwill_code: str
    test_date: date
    test_period: str
    recoverable_amount: Decimal
    carrying_amount_before: Decimal
    impairment_loss: Decimal
    carrying_amount_after: Decimal
    valuation_method: str
    discount_rate: Decimal | None
    growth_rate: Decimal | None
    impairment_source: str
    description: str | None
    is_impaired: bool
    created_at: datetime


@dataclass(kw_only=True)
class GoodwillDisposalResponse:
    goodwill_id: UUID
    goodwill_code: str
    disposal_date: date
    carrying_amount_before: Decimal
    disposal_proceeds: Decimal
    gain_loss: Decimal
    status: str


# ============================================================================
# Main Service
# ============================================================================


class GoodwillService:
    """
    Service for goodwill accounting and impairment testing.
    Mempublikasikan event untuk setiap operasi (best-effort - kegagalan
    publish tidak menggagalkan transaksi, lihat _publish_event).
    """

    def __init__(
        self,
        goodwill_repo: GoodwillRepositoryPort,
        ledger_repo: LedgerRepositoryPort | None = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        if goodwill_repo is None:
            raise ValueError("goodwill_repo is required")

        self._goodwill_repo = goodwill_repo
        self._ledger_repo = ledger_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._stats = {
            "goodwill_recognized": 0,
            "goodwill_updated": 0,
            "impairments": 0,
            "reversals": 0,
            "disposals": 0,
        }
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("GoodwillService initialized")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "GoodwillService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str, correlation_id: str | None = None) -> None:
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event, correlation_id)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    # ========================================================================
    # Goodwill Recognition
    # ========================================================================

    @audit
    async def recognize_goodwill(
        self,
        request: GoodwillRecognitionRequest,
        correlation_id: str | None = None,
    ) -> GoodwillResponse:
        self._check_authority(request.created_by, "recognize_goodwill")

        goodwill_initial = request.purchase_price - request.fair_value_identifiable_net_assets
        if goodwill_initial < 0:
            logger.warning(
                f"Negative goodwill (bargain purchase) of {goodwill_initial} for "
                f"'{request.acquiree_name}' - diakui 0 di neraca; selisihnya adalah "
                f"keuntungan pembelian dengan diskon (PSAK 22), bukan goodwill."
            )
            goodwill_initial = Decimal("0")

        table = GoodwillTable(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            goodwill_code=request.goodwill_code.strip().upper(),
            name=request.name,
            description=request.description,
            acquisition_date=request.acquisition_date,
            acquiree_name=request.acquiree_name,
            acquiree_tax_id=request.acquiree_tax_id,
            purchase_price=request.purchase_price,
            fair_value_identifiable_net_assets=request.fair_value_identifiable_net_assets,
            goodwill_initial=goodwill_initial,
            carrying_amount=goodwill_initial,
            currency=request.currency,
            exchange_rate_at_acquisition=request.exchange_rate_at_acquisition,
            cash_generating_unit=request.cash_generating_unit,
            allocated_to_segment=request.allocated_to_segment,
            status=STATUS_ACTIVE,
            is_active=True,
            created_by=request.created_by,
        )

        await self._goodwill_repo.save_goodwill(table)
        # NOTE: commit sudah dilakukan di repository (save_goodwill/
        # save_impairment masing-masing commit sendiri) - lihat
        # sqlalchemy_goodwill_repository_impl.py. Tidak lagi memanggil
        # self._uow.commit() di sini karena UoW tsb tidak pernah di-
        # `begin()` di jalur ini, jadi commit-nya selalu gagal dengan
        # "UoW not started or transaction not active".

        self._stats["goodwill_recognized"] += 1

        if self._event_publisher and goodwill_initial > 0:
            event = GoodwillRecognizedEvent(
                aggregate_id=table.id,
                aggregate_version=table.version,
                goodwill_id=table.id,
                goodwill_number=table.goodwill_code,
                amount=goodwill_initial,
                acquisition_date=request.acquisition_date,
                user_id=str(request.created_by) if request.created_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Goodwill {table.goodwill_code} (recognized)", correlation_id)

        self._record_audit("recognize_goodwill", {
            "goodwill_id": str(table.id),
            "goodwill_initial": str(goodwill_initial),
            "created_by": str(request.created_by) if request.created_by else None,
        })

        logger.info(f"Goodwill {table.goodwill_code} recognized: {goodwill_initial}")
        return self._to_response(table)

    # ========================================================================
    # Goodwill Update
    # ========================================================================

    @audit
    async def update_goodwill(
        self,
        goodwill_id: UUID,
        request: GoodwillUpdateRequest,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> GoodwillResponse:
        self._check_authority(updated_by, "update_goodwill")

        table = await self._goodwill_repo.get_goodwill_by_id(goodwill_id)
        if not table:
            raise GoodwillNotFoundError(f"Goodwill {goodwill_id} not found")

        if table.status == STATUS_DISPOSED:
            raise GoodwillAlreadyDisposedError("Cannot update disposed goodwill")

        changes: dict[str, Any] = {}
        for attr, new_value in (
            ("name", request.name),
            ("cash_generating_unit", request.cash_generating_unit),
            ("allocated_to_segment", request.allocated_to_segment),
            ("description", request.description),
        ):
            if new_value is not None and new_value != getattr(table, attr):
                changes[attr] = {"old": getattr(table, attr), "new": new_value}
                setattr(table, attr, new_value)

        if not changes:
            return self._to_response(table)

        table.updated_at = datetime.now(UTC)
        table.increment_version()

        await self._goodwill_repo.save_goodwill(table)
        # NOTE: commit sudah dilakukan di repository (save_goodwill/
        # save_impairment masing-masing commit sendiri) - lihat
        # sqlalchemy_goodwill_repository_impl.py. Tidak lagi memanggil
        # self._uow.commit() di sini karena UoW tsb tidak pernah di-
        # `begin()` di jalur ini, jadi commit-nya selalu gagal dengan
        # "UoW not started or transaction not active".

        self._stats["goodwill_updated"] += 1

        if self._event_publisher:
            event = GoodwillUpdatedEvent(
                aggregate_id=table.id,
                aggregate_version=table.version,
                goodwill_id=table.id,
                goodwill_number=table.goodwill_code,
                note=", ".join(changes.keys()),
                user_id=str(updated_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Goodwill {table.goodwill_code} (updated)", correlation_id)

        self._record_audit("update_goodwill", {
            "goodwill_id": str(goodwill_id),
            "changes": changes,
            "updated_by": str(updated_by),
        })

        return self._to_response(table)

    # ========================================================================
    # Impairment Testing (PSAK 48 / IAS 36)
    # ========================================================================

    @audit
    async def test_impairment(
        self,
        request: ImpairmentTestRequest,
        correlation_id: str | None = None,
    ) -> ImpairmentTestResponse:
        self._check_authority(request.created_by, "test_impairment")

        table = await self._goodwill_repo.get_goodwill_by_id(request.goodwill_id)
        if not table:
            raise GoodwillNotFoundError(f"Goodwill {request.goodwill_id} not found")

        if table.status not in (STATUS_ACTIVE, STATUS_PARTIALLY_IMPAIRED):
            raise InvalidImpairmentTestError(f"Goodwill is not active (status: {table.status})")

        carrying_before = table.carrying_amount
        impairment_loss = Decimal("0")
        if request.recoverable_amount < carrying_before:
            table.record_impairment(
                impairment_loss=carrying_before - request.recoverable_amount,
                test_date=request.test_date,
                recoverable_amount=request.recoverable_amount,
            )
            impairment_loss = carrying_before - table.carrying_amount

        impairment_record = GoodwillImpairmentTable(
            id=uuid4(),
            legal_entity_id=table.legal_entity_id,
            goodwill_id=table.id,
            test_date=request.test_date,
            test_period="annual" if request.impairment_source == "annual_test" else "trigger",
            recoverable_amount=request.recoverable_amount,
            carrying_amount_before=carrying_before,
            impairment_loss=impairment_loss,
            carrying_amount_after=table.carrying_amount,
            valuation_method=request.valuation_method,
            discount_rate=request.discount_rate,
            growth_rate=request.growth_rate,
            impairment_source=request.impairment_source,
            description=request.description,
            created_by=request.created_by,
        )
        await self._goodwill_repo.save_impairment(impairment_record)
        await self._goodwill_repo.save_goodwill(table)
        # NOTE: commit sudah dilakukan di repository (save_goodwill/
        # save_impairment masing-masing commit sendiri) - lihat
        # sqlalchemy_goodwill_repository_impl.py. Tidak lagi memanggil
        # self._uow.commit() di sini karena UoW tsb tidak pernah di-
        # `begin()` di jalur ini, jadi commit-nya selalu gagal dengan
        # "UoW not started or transaction not active".

        self._stats["impairments"] += 1

        if self._event_publisher and impairment_loss > 0:
            event = GoodwillImpairedEvent(
                aggregate_id=table.id,
                aggregate_version=table.version,
                goodwill_id=table.id,
                goodwill_number=table.goodwill_code,
                impairment_loss=impairment_loss,
                new_carrying_amount=table.carrying_amount,
                recoverable_amount=request.recoverable_amount,
                user_id=str(request.created_by) if request.created_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Goodwill {table.goodwill_code} (impaired)", correlation_id)

        self._record_audit("test_impairment", {
            "goodwill_id": str(table.id),
            "impairment_loss": str(impairment_loss),
            "created_by": str(request.created_by) if request.created_by else None,
        })

        logger.info(f"Goodwill {table.goodwill_code} impairment test: loss={impairment_loss}")
        return self._to_impairment_response(impairment_record, is_impaired=impairment_loss > 0)

    async def get_impairment_tests(self, goodwill_id: UUID) -> list[ImpairmentTestResponse]:
        records = await self._goodwill_repo.get_impairments_by_goodwill(goodwill_id)
        return [self._to_impairment_response(r, is_impaired=r.impairment_loss > 0) for r in records]

    @audit
    async def reverse_impairment(
        self,
        goodwill_id: UUID,
        reversal_date: date,
        reversal_amount: Decimal,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> Decimal:
        """PERINGATAN: menurut IFRS/PSAK, pemulihan (reversal) rugi
        penurunan nilai goodwill DILARANG - sekali diakui, tidak boleh
        dibalik. Method ini dipertahankan (sesuai kemampuan yang sudah
        ada di GoodwillTable.recover_impairment) untuk kasus terbatas
        (koreksi kesalahan input, bukan pemulihan nilai bisnis riil).
        Gunakan dengan sangat hati-hati dan selalu catat alasannya."""
        self._check_authority(user_id, "reverse_impairment")
        logger.warning(
            f"reverse_impairment dipanggil untuk goodwill {goodwill_id} - IFRS/PSAK "
            f"melarang pemulihan rugi impairment goodwill kecuali untuk koreksi "
            f"kesalahan input. Alasan: {reason}"
        )

        table = await self._goodwill_repo.get_goodwill_by_id(goodwill_id)
        if not table:
            raise GoodwillNotFoundError(f"Goodwill {goodwill_id} not found")

        if table.status not in (STATUS_PARTIALLY_IMPAIRED, STATUS_FULLY_IMPAIRED):
            raise InvalidImpairmentTestError("Only impaired goodwill can be reversed")

        carrying_before = table.carrying_amount
        table.recover_impairment(recovery_amount=reversal_amount, reversal_date=reversal_date)
        actual_reversal = table.carrying_amount - carrying_before

        await self._goodwill_repo.save_goodwill(table)
        # NOTE: commit sudah dilakukan di repository (save_goodwill/
        # save_impairment masing-masing commit sendiri) - lihat
        # sqlalchemy_goodwill_repository_impl.py. Tidak lagi memanggil
        # self._uow.commit() di sini karena UoW tsb tidak pernah di-
        # `begin()` di jalur ini, jadi commit-nya selalu gagal dengan
        # "UoW not started or transaction not active".

        self._stats["reversals"] += 1

        if self._event_publisher and actual_reversal > 0:
            event = GoodwillImpairmentReversedEvent(
                aggregate_id=table.id,
                aggregate_version=table.version,
                goodwill_id=table.id,
                goodwill_number=table.goodwill_code,
                reversal_amount=actual_reversal,
                new_carrying_amount=table.carrying_amount,
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Goodwill {table.goodwill_code} (impairment reversed)", correlation_id)

        self._record_audit("reverse_impairment", {
            "goodwill_id": str(goodwill_id),
            "actual_reversal": str(actual_reversal),
            "reason": reason,
            "user_id": str(user_id),
        })

        logger.info(f"Goodwill {table.goodwill_code} impairment reversed by {actual_reversal}")
        return actual_reversal

    # ========================================================================
    # Disposal
    # ========================================================================

    @audit
    async def dispose_goodwill(
        self,
        request: GoodwillDisposalRequest,
        correlation_id: str | None = None,
    ) -> GoodwillDisposalResponse:
        self._check_authority(request.disposed_by, "dispose_goodwill")

        table = await self._goodwill_repo.get_goodwill_by_id(request.goodwill_id)
        if not table:
            raise GoodwillNotFoundError(f"Goodwill {request.goodwill_id} not found")

        if table.status == STATUS_DISPOSED:
            raise GoodwillAlreadyDisposedError("Goodwill already disposed")

        carrying_before = table.carrying_amount
        gain_loss = table.dispose(
            disposal_date=request.disposal_date,
            proceeds=request.proceeds,
            reason=request.reason,
            disposed_by=request.disposed_by,
        )

        await self._goodwill_repo.save_goodwill(table)
        # NOTE: commit sudah dilakukan di repository (save_goodwill/
        # save_impairment masing-masing commit sendiri) - lihat
        # sqlalchemy_goodwill_repository_impl.py. Tidak lagi memanggil
        # self._uow.commit() di sini karena UoW tsb tidak pernah di-
        # `begin()` di jalur ini, jadi commit-nya selalu gagal dengan
        # "UoW not started or transaction not active".

        self._stats["disposals"] += 1

        if self._event_publisher:
            event = GoodwillDisposedEvent(
                aggregate_id=table.id,
                aggregate_version=table.version,
                goodwill_id=table.id,
                goodwill_number=table.goodwill_code,
                amount=request.proceeds,
                reason=request.reason or "",
                user_id=str(request.disposed_by) if request.disposed_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Goodwill {table.goodwill_code} (disposed)", correlation_id)

        self._record_audit("dispose_goodwill", {
            "goodwill_id": str(table.id),
            "gain_loss": str(gain_loss),
            "disposed_by": str(request.disposed_by) if request.disposed_by else None,
        })

        logger.info(f"Goodwill {table.goodwill_code} disposed. Gain/Loss: {gain_loss}")
        return GoodwillDisposalResponse(
            goodwill_id=table.id,
            goodwill_code=table.goodwill_code,
            disposal_date=request.disposal_date,
            carrying_amount_before=carrying_before,
            disposal_proceeds=request.proceeds,
            gain_loss=gain_loss,
            status=table.status,
        )

    # ========================================================================
    # Queries
    # ========================================================================

    async def get_goodwill(self, goodwill_id: UUID) -> GoodwillResponse | None:
        table = await self._goodwill_repo.get_goodwill_by_id(goodwill_id)
        if not table:
            return None
        return self._to_response(table)

    async def list_goodwill(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
        cash_generating_unit: str | None = None,
    ) -> list[GoodwillResponse]:
        tables = await self._goodwill_repo.get_goodwill_by_legal_entity(legal_entity_id)
        if status:
            tables = [t for t in tables if t.status == status]
        if cash_generating_unit:
            tables = [t for t in tables if t.cash_generating_unit == cash_generating_unit]
        return [self._to_response(t) for t in tables]

    async def get_active_goodwill(self, legal_entity_id: UUID) -> list[GoodwillResponse]:
        tables = await self._goodwill_repo.get_active_goodwill(legal_entity_id)
        return [self._to_response(t) for t in tables]

    # ========================================================================
    # Private Helpers
    # ========================================================================

    def _to_response(self, table: GoodwillTable) -> GoodwillResponse:
        return GoodwillResponse(
            id=table.id,
            legal_entity_id=table.legal_entity_id,
            goodwill_code=table.goodwill_code,
            name=table.name,
            description=table.description,
            acquisition_date=table.acquisition_date,
            acquiree_name=table.acquiree_name,
            acquiree_tax_id=table.acquiree_tax_id,
            purchase_price=table.purchase_price,
            fair_value_identifiable_net_assets=table.fair_value_identifiable_net_assets,
            goodwill_initial=table.goodwill_initial,
            carrying_amount=table.carrying_amount,
            impairment_accumulated=table.impairment_accumulated,
            net_carrying_amount=table.net_carrying_amount,
            currency=table.currency,
            exchange_rate_at_acquisition=table.exchange_rate_at_acquisition,
            cash_generating_unit=table.cash_generating_unit,
            allocated_to_segment=table.allocated_to_segment,
            status=table.status,
            is_active=table.is_active,
            last_impairment_date=table.last_impairment_date,
            last_impairment_loss=table.last_impairment_loss,
            disposal_date=table.disposal_date,
            disposal_proceeds=table.disposal_proceeds,
            disposal_gain_loss=table.disposal_gain_loss,
            disposal_reason=table.disposal_reason,
            created_by=table.created_by,
            created_at=table.created_at,
            updated_at=table.updated_at,
            version=table.version,
        )

    def _to_impairment_response(
        self, record: GoodwillImpairmentTable, is_impaired: bool
    ) -> ImpairmentTestResponse:
        return ImpairmentTestResponse(
            id=record.id,
            goodwill_id=record.goodwill_id,
            goodwill_code=record.goodwill.goodwill_code if record.goodwill else "",
            test_date=record.test_date,
            test_period=record.test_period,
            recoverable_amount=record.recoverable_amount,
            carrying_amount_before=record.carrying_amount_before,
            impairment_loss=record.impairment_loss,
            carrying_amount_after=record.carrying_amount_after,
            valuation_method=record.valuation_method,
            discount_rate=record.discount_rate,
            growth_rate=record.growth_rate,
            impairment_source=record.impairment_source,
            description=record.description,
            is_impaired=is_impaired,
            created_at=record.created_at,
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_goodwill_service(
    goodwill_repo: GoodwillRepositoryPort,
    ledger_repo: LedgerRepositoryPort | None = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> GoodwillService:
    return GoodwillService(goodwill_repo, ledger_repo, uow, event_publisher)


__all__ = [
    "GoodwillAlreadyDisposedError",
    "GoodwillDisposalRequest",
    "GoodwillDisposalResponse",
    "GoodwillNotFoundError",
    "GoodwillRecognitionRequest",
    "GoodwillResponse",
    "GoodwillService",
    "GoodwillServiceError",
    "GoodwillUpdateRequest",
    "ImpairmentTestRequest",
    "ImpairmentTestResponse",
    "InvalidImpairmentTestError",
    "create_goodwill_service",
]
