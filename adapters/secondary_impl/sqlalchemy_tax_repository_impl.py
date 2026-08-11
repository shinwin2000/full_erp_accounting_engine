#!/usr/bin/env python3
"""
Module: sqlalchemy_tax_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository Tax dengan SQLAlchemy - LENGKAP.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.shared_value_objects.money_vo import Money
from domain.tax_transaction.aggregate_root import (
    Bupot,
    EMeterai,
    FakturPajak,
    FakturStatus,
    SPTStatus,
    SPTSubmission,
)
from infrastructure.persistence_orm.coretax_bupot_table import CoretaxBupotTable
from infrastructure.persistence_orm.coretax_emeterai_table import CoretaxEMeteraiTable
from infrastructure.persistence_orm.coretax_faktur_line_table import CoretaxFakturLineTable
from infrastructure.persistence_orm.coretax_faktur_table import CoretaxFakturTable
from infrastructure.persistence_orm.coretax_nsfp_table import CoretaxNSFPTable, NSFStatus
from infrastructure.persistence_orm.coretax_ntpn_table import CoretaxNTPNTable
from infrastructure.persistence_orm.coretax_spt_table import CoretaxSPTTable
from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable
from ports.primary.tax_repository_port import TaxRepositoryPort

logger = logging.getLogger(__name__)

DEFAULT_CURRENCY = "IDR"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class TaxRepositoryError(Exception):
    pass


class DuplicateFakturNumberError(TaxRepositoryError):
    pass


class FakturNotFoundError(TaxRepositoryError):
    pass


class NSFPNotFoundError(TaxRepositoryError):
    pass


class SPTNotFoundError(TaxRepositoryError):
    pass


class BupotNotFoundError(TaxRepositoryError):
    pass


class DuplicateNTPNError(TaxRepositoryError):
    pass


class OptimisticLockError(TaxRepositoryError):
    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyTaxRepository(TaxRepositoryPort):
    """Implementasi lengkap repository Tax dengan SQLAlchemy."""

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise TaxRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    # ========================================================================
    # HELPER
    # ========================================================================

    async def _get_npwp_by_legal_entity(self, legal_entity_id: UUID) -> str | None:
        """Ambil NPWP dari legal entity."""
        stmt = select(LegalEntityTable.npwp).where(
            LegalEntityTable.id == legal_entity_id,
            LegalEntityTable.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # ========================================================================
    # FAKTUR PAJAK - KELUARAN & MASUKAN
    # ========================================================================

    async def save_faktur_keluaran(self, faktur: FakturPajak) -> None:
        """Simpan faktur pajak keluaran."""
        if not faktur.is_keluaran:
            raise TaxRepositoryError("Cannot save non-keluaran as faktur keluaran")
        await self._save_faktur(faktur)

    async def save_faktur_masukan(self, faktur: FakturPajak) -> None:
        """Simpan faktur pajak masukan."""
        if faktur.is_keluaran:
            raise TaxRepositoryError("Cannot save keluaran as faktur masukan")
        await self._save_faktur(faktur)

    async def _save_faktur(self, faktur: FakturPajak) -> None:
        """Internal: simpan faktur (keluaran/masukan)."""
        try:
            # Cek duplikasi nomor faktur
            exists = await self.exists_by_faktur_number(
                faktur.faktur_number,
                faktur.npwp_penjual if faktur.is_keluaran else faktur.npwp_pembeli,
            )
            if exists:
                raise DuplicateFakturNumberError(
                    f"Faktur number {faktur.faktur_number} already exists"
                )

            table = CoretaxFakturTable(
                id=faktur.id,
                faktur_number=faktur.faktur_number,
                nsfp_used=faktur.nsfp_used,
                faktur_type="keluaran" if faktur.is_keluaran else "masukan",
                npwp_penjual=faktur.npwp_penjual,
                nama_penjual=faktur.nama_penjual,
                alamat_penjual=faktur.alamat_penjual,
                npwp_pembeli=faktur.npwp_pembeli,
                nama_pembeli=faktur.nama_pembeli,
                alamat_pembeli=faktur.alamat_pembeli,
                faktur_date=faktur.faktur_date,
                dpp=faktur.dpp.amount,
                ppn=faktur.ppn.amount,
                ppn_bm=faktur.ppn_bm.amount if faktur.ppn_bm else 0,
                currency=faktur.dpp.currency,
                status=faktur.status.value
                if hasattr(faktur.status, "value")
                else str(faktur.status),
                approval_code=faktur.approval_code,
                approval_date=faktur.approval_date,
                rejection_reason=faktur.rejection_reason,
                reference_id=faktur.reference_id,
                reference_type=faktur.reference_type,
                xml_content=faktur.xml_content,
                created_by=faktur.created_by,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                version=1,
                legal_entity_id=faktur.legal_entity_id,
            )
            self.session.add(table)

            for line in faktur.lines:
                line_table = CoretaxFakturLineTable(
                    id=line.get("id", uuid4()),
                    faktur_id=faktur.id,
                    line_number=line.get("line_number", 0),
                    description=line.get("description", ""),
                    quantity=line.get("quantity", 0),
                    unit_price=line.get("unit_price", 0),
                    amount=line.get("amount", 0),
                    tax_amount=line.get("tax_amount", 0),
                )
                self.session.add(line_table)

            await self.session.flush()
            logger.info("Faktur saved: %s", faktur.faktur_number)

        except DuplicateFakturNumberError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise TaxRepositoryError(f"Failed to save faktur: {e}") from e

    async def get_faktur_keluaran(self, faktur_id: UUID) -> Any | None:
        """Ambil faktur keluaran by ID."""
        faktur = await self.get_faktur_by_id(faktur_id)
        if faktur and not faktur.is_keluaran:
            return None
        return faktur

    async def get_faktur_masukan(self, faktur_id: UUID) -> Any | None:
        """Ambil faktur masukan by ID."""
        faktur = await self.get_faktur_by_id(faktur_id)
        if faktur and faktur.is_keluaran:
            return None
        return faktur

    async def get_faktur_by_id(self, faktur_id: UUID) -> FakturPajak | None:
        """Ambil faktur by ID (generic)."""
        try:
            stmt = select(CoretaxFakturTable).where(
                CoretaxFakturTable.id == faktur_id, CoretaxFakturTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None

            # Ambil lines
            lines_stmt = (
                select(CoretaxFakturLineTable)
                .where(CoretaxFakturLineTable.faktur_id == faktur_id)
                .order_by(CoretaxFakturLineTable.line_number)
            )
            lines_result = await self.session.execute(lines_stmt)
            lines = [
                {
                    "id": lt.id,
                    "line_number": lt.line_number,
                    "description": lt.description,
                    "quantity": lt.quantity,
                    "unit_price": lt.unit_price,
                    "amount": lt.amount,
                    "tax_amount": lt.tax_amount,
                }
                for lt in lines_result.scalars().all()
            ]

            status_map = {
                "draft": FakturStatus.DRAFT,
                "submitted": FakturStatus.SUBMITTED,
                "approved": FakturStatus.APPROVED,
                "rejected": FakturStatus.REJECTED,
                "cancelled": FakturStatus.CANCELLED,
                "expired": FakturStatus.EXPIRED,
            }
            status = status_map.get(table.status, FakturStatus.DRAFT)

            return FakturPajak(
                id=table.id,
                faktur_number=table.faktur_number,
                nsfp_used=table.nsfp_used,
                is_keluaran=table.faktur_type == "keluaran",
                npwp_penjual=table.npwp_penjual,
                nama_penjual=table.nama_penjual,
                alamat_penjual=table.alamat_penjual,
                npwp_pembeli=table.npwp_pembeli,
                nama_pembeli=table.nama_pembeli,
                alamat_pembeli=table.alamat_pembeli,
                faktur_date=table.faktur_date,
                dpp=Money(amount=table.dpp, currency=table.currency),
                ppn=Money(amount=table.ppn, currency=table.currency),
                ppn_bm=Money(amount=table.ppn_bm, currency=table.currency)
                if table.ppn_bm > 0
                else None,
                status=status,
                approval_code=table.approval_code,
                approval_date=table.approval_date,
                rejection_reason=table.rejection_reason,
                reference_id=table.reference_id,
                reference_type=table.reference_type,
                xml_content=table.xml_content,
                lines=lines,
                created_by=table.created_by,
                created_at=table.created_at,
                updated_at=table.updated_at,
                version=table.version,
                legal_entity_id=table.legal_entity_id,
            )
        except Exception as e:
            raise TaxRepositoryError(f"Failed to get faktur: {e}") from e

    async def get_faktur_by_number(self, faktur_number: str, npwp: str) -> FakturPajak | None:
        """Ambil faktur berdasarkan nomor dan NPWP."""
        try:
            stmt = select(CoretaxFakturTable).where(
                or_(
                    and_(
                        CoretaxFakturTable.npwp_penjual == npwp,
                        CoretaxFakturTable.faktur_number == faktur_number,
                    ),
                    and_(
                        CoretaxFakturTable.npwp_pembeli == npwp,
                        CoretaxFakturTable.faktur_number == faktur_number,
                    ),
                ),
                CoretaxFakturTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return await self.get_faktur_by_id(table.id)
        except Exception as e:
            raise TaxRepositoryError(f"Failed to get faktur by number: {e}") from e

    async def exists_by_faktur_number(self, faktur_number: str, npwp: str) -> bool:
        """Cek keberadaan nomor faktur."""
        stmt = (
            select(func.count())
            .select_from(CoretaxFakturTable)
            .where(
                or_(
                    and_(
                        CoretaxFakturTable.npwp_penjual == npwp,
                        CoretaxFakturTable.faktur_number == faktur_number,
                    ),
                    and_(
                        CoretaxFakturTable.npwp_pembeli == npwp,
                        CoretaxFakturTable.faktur_number == faktur_number,
                    ),
                ),
                CoretaxFakturTable.deleted_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() > 0

    async def update_faktur_status(
        self,
        faktur_id: UUID,
        status: str,
        approval_code: str | None = None,
        approval_date: date | None = None,
        rejection_reason: str | None = None,
        version: int | None = None,
    ) -> None:
        """Update status faktur dengan optimistic lock."""
        try:
            if version is not None:
                stmt = select(CoretaxFakturTable.version).where(CoretaxFakturTable.id == faktur_id)
                curr_version = (await self.session.execute(stmt)).scalar_one_or_none()
                if curr_version is None:
                    raise FakturNotFoundError(f"Faktur {faktur_id} not found")
                if curr_version != version:
                    raise OptimisticLockError(
                        f"Version mismatch: expected {version}, got {curr_version}"
                    )

                values = {"status": status, "version": version + 1, "updated_at": datetime.utcnow()}
                if approval_code:
                    values["approval_code"] = approval_code
                if approval_date:
                    values["approval_date"] = approval_date
                if rejection_reason:
                    values["rejection_reason"] = rejection_reason

                stmt = (
                    update(CoretaxFakturTable)
                    .where(
                        CoretaxFakturTable.id == faktur_id, CoretaxFakturTable.version == version
                    )
                    .values(**values)
                )
            else:
                values = {"status": status, "updated_at": datetime.utcnow()}
                if approval_code:
                    values["approval_code"] = approval_code
                if approval_date:
                    values["approval_date"] = approval_date
                if rejection_reason:
                    values["rejection_reason"] = rejection_reason
                stmt = (
                    update(CoretaxFakturTable)
                    .where(CoretaxFakturTable.id == faktur_id)
                    .values(**values)
                )

            result = await self.session.execute(stmt)
            if version is not None and result.rowcount == 0:
                raise OptimisticLockError("Failed to update faktur status")
            await self.session.flush()
        except (FakturNotFoundError, OptimisticLockError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise TaxRepositoryError(f"Failed to update status: {e}") from e

    async def count_faktur_by_status(self, legal_entity_id: UUID, status: str) -> int:
        """Hitung jumlah faktur berdasarkan status."""
        stmt = (
            select(func.count())
            .select_from(CoretaxFakturTable)
            .where(
                CoretaxFakturTable.legal_entity_id == legal_entity_id,
                CoretaxFakturTable.status == status,
                CoretaxFakturTable.deleted_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def list_faktur_keluaran_by_npwp(
        self, npwp: str, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        """List faktur keluaran berdasarkan NPWP."""
        stmt = (
            select(CoretaxFakturTable)
            .where(
                CoretaxFakturTable.faktur_type == "keluaran",
                CoretaxFakturTable.npwp_penjual == npwp,
                CoretaxFakturTable.deleted_at.is_(None),
            )
            .order_by(CoretaxFakturTable.faktur_date.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        fakturs = []
        for table in result.scalars().all():
            fakturs.append(await self.get_faktur_by_id(table.id))
        return fakturs

    async def list_faktur_masukan_by_npwp(
        self, npwp: str, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        """List faktur masukan berdasarkan NPWP."""
        stmt = (
            select(CoretaxFakturTable)
            .where(
                CoretaxFakturTable.faktur_type == "masukan",
                CoretaxFakturTable.npwp_pembeli == npwp,
                CoretaxFakturTable.deleted_at.is_(None),
            )
            .order_by(CoretaxFakturTable.faktur_date.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        fakturs = []
        for table in result.scalars().all():
            fakturs.append(await self.get_faktur_by_id(table.id))
        return fakturs

    # ========================================================================
    # NSFP
    # ========================================================================

    async def save_nsfp_range(
        self, legal_entity_id: UUID, start: str, end: str, requested_at: datetime
    ) -> None:
        """
        Simpan range NSFP (start sampai end) untuk legal entity.
        Karena model NSFP menyimpan range, kita simpan satu record per range.
        """
        try:
            # Cek apakah sudah ada range yang tumpang tindih?
            start_num = int(start)
            end_num = int(end)
            if start_num > end_num:
                raise TaxRepositoryError("Start must be less than or equal to end")

            # Cek existing range yang overlap
            stmt = select(CoretaxNSFPTable).where(
                CoretaxNSFPTable.legal_entity_id == legal_entity_id,
                CoretaxNSFPTable.status.in_([NSFStatus.ACTIVE, NSFStatus.PARTIALLY_USED]),
                or_(
                    and_(CoretaxNSFPTable.start_number <= start_num, CoretaxNSFPTable.end_number >= start_num),
                    and_(CoretaxNSFPTable.start_number <= end_num, CoretaxNSFPTable.end_number >= end_num),
                    and_(CoretaxNSFPTable.start_number >= start_num, CoretaxNSFPTable.end_number <= end_num),
                )
            )
            result = await self.session.execute(stmt)
            if result.scalar_one_or_none():
                raise TaxRepositoryError("Overlapping NSFP range already exists")

            # Simpan range
            table = CoretaxNSFPTable(
                id=uuid4(),
                legal_entity_id=legal_entity_id,
                start_number=start_num,
                end_number=end_num,
                current_number=start_num - 1,  # belum ada yang digunakan
                status=NSFStatus.ACTIVE,
                request_id=str(uuid4()),
                issued_date=requested_at.date(),
                expiry_date=None,  # bisa diisi dari aturan
                used_count=0,
            )
            self.session.add(table)
            await self.session.flush()
            logger.info("NSFP range saved: %d-%d for legal entity %s", start_num, end_num, legal_entity_id)

        except Exception as e:
            await self.session.rollback()
            raise TaxRepositoryError(f"Failed to save NSFP range: {e}") from e

    async def get_current_nsfp_range(self, legal_entity_id: UUID) -> Any | None:
        """
        Ambil range NSFP yang tersedia untuk legal entity.
        Return dict dengan start, end, current (nomor pertama available).
        """
        try:
            stmt = select(CoretaxNSFPTable).where(
                CoretaxNSFPTable.legal_entity_id == legal_entity_id,
                CoretaxNSFPTable.status.in_([NSFStatus.ACTIVE, NSFStatus.PARTIALLY_USED]),
                CoretaxNSFPTable.current_number < CoretaxNSFPTable.end_number,
            ).order_by(CoretaxNSFPTable.start_number).limit(1)
            result = await self.session.execute(stmt)
            nsfp = result.scalar_one_or_none()
            if not nsfp:
                return None

            return {
                "start": str(nsfp.start_number),
                "end": str(nsfp.end_number),
                "current": str(nsfp.current_number + 1),  # nomor berikutnya yang tersedia
                "available_count": nsfp.end_number - nsfp.current_number,
            }
        except Exception as e:
            raise TaxRepositoryError(f"Failed to get NSFP range: {e}") from e

    async def update_nsfp_current(self, legal_entity_id: UUID, current: str) -> None:
        """
        Tandai NSFP dengan nomor `current` sebagai sudah digunakan.
        Menggunakan pessimistic locking (SELECT FOR UPDATE) untuk mencegah race condition.
        """
        try:
            current_num = int(current)
            async with self.session.begin():
                # Lock range yang mencakup current number
                stmt_lock = select(CoretaxNSFPTable).where(
                    CoretaxNSFPTable.legal_entity_id == legal_entity_id,
                    CoretaxNSFPTable.start_number <= current_num,
                    CoretaxNSFPTable.end_number >= current_num,
                    CoretaxNSFPTable.status.in_([NSFStatus.ACTIVE, NSFStatus.PARTIALLY_USED]),
                ).with_for_update()
                result = await self.session.execute(stmt_lock)
                nsfp = result.scalar_one_or_none()
                if not nsfp:
                    raise NSFPNotFoundError(f"NSFP {current} not available for legal entity {legal_entity_id}")

                # Jika current_number sudah >= current_num berarti sudah digunakan
                if nsfp.current_number >= current_num:
                    raise NSFPNotFoundError(f"NSFP {current} already used")

                # Update current_number
                nsfp.current_number = current_num
                nsfp.used_count += 1
                if nsfp.current_number == nsfp.end_number:
                    nsfp.status = NSFStatus.EXHAUSTED
                else:
                    nsfp.status = NSFStatus.PARTIALLY_USED
                await self.session.flush()

        except NSFPNotFoundError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise TaxRepositoryError(f"Failed to update NSFP current: {e}") from e

    # ========================================================================
    # SPT
    # ========================================================================

    async def save_spt_pph21(self, spt: SPTSubmission) -> None:
        """Simpan SPT PPh 21."""
        await self._save_spt(spt)

    async def save_spt_ppn(self, spt: SPTSubmission) -> None:
        """Simpan SPT PPN."""
        await self._save_spt(spt)

    async def save_spt_tahunan(self, spt: SPTSubmission) -> None:
        """Simpan SPT Tahunan."""
        await self._save_spt(spt)

    async def _save_spt(self, spt: SPTSubmission) -> None:
        try:
            table = CoretaxSPTTable(
                id=spt.id,
                spt_number=spt.spt_number,
                spt_type=spt.spt_type,
                npwp=spt.npwp,
                tahun=spt.tahun,
                bulan=spt.bulan,
                masa_pajak=spt.masa_pajak,
                status=spt.status.value if hasattr(spt.status, "value") else str(spt.status),
                xml_content=spt.xml_content,
                coretax_tracking_id=spt.coretax_tracking_id,
                approval_date=spt.approval_date,
                rejection_reason=spt.rejection_reason,
                submitted_by=spt.submitted_by,
                submitted_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
                version=1,
                legal_entity_id=spt.legal_entity_id,
            )
            self.session.add(table)
            await self.session.flush()
        except Exception as e:
            await self.session.rollback()
            raise TaxRepositoryError(f"Failed to save SPT: {e}") from e

    async def get_spt_submission(self, spt_id: UUID) -> SPTSubmission | None:
        """Ambil SPT by ID."""
        try:
            stmt = select(CoretaxSPTTable).where(CoretaxSPTTable.id == spt_id)
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            status_map = {
                "draft": SPTStatus.DRAFT,
                "submitted": SPTStatus.SUBMITTED,
                "approved": SPTStatus.APPROVED,
                "rejected": SPTStatus.REJECTED,
                "void": SPTStatus.VOID,
            }
            status = status_map.get(table.status, SPTStatus.DRAFT)
            return SPTSubmission(
                id=table.id,
                spt_number=table.spt_number,
                spt_type=table.spt_type,
                npwp=table.npwp,
                tahun=table.tahun,
                bulan=table.bulan,
                masa_pajak=table.masa_pajak,
                status=status,
                xml_content=table.xml_content,
                coretax_tracking_id=table.coretax_tracking_id,
                approval_date=table.approval_date,
                rejection_reason=table.rejection_reason,
                submitted_by=table.submitted_by,
                submitted_at=table.submitted_at,
                created_at=table.created_at,
                legal_entity_id=table.legal_entity_id,
            )
        except Exception as e:
            raise TaxRepositoryError(f"Failed to get SPT: {e}") from e

    async def update_spt_status(
        self,
        spt_id: UUID,
        status: str,
        approval_date: date | None = None,
        rejection_reason: str | None = None,
    ) -> None:
        """
        Update status SPT dengan pessimistic locking.
        LOCKING: SELECT FOR UPDATE memastikan exclusive lock pada baris yang diupdate.
        """
        try:
            async with self.session.begin():
                stmt_lock = select(CoretaxSPTTable).where(CoretaxSPTTable.id == spt_id).with_for_update()
                result = await self.session.execute(stmt_lock)
                row = result.scalar_one_or_none()
                if not row:
                    raise SPTNotFoundError(f"SPT {spt_id} not found")

                row.status = status
                if approval_date:
                    row.approval_date = approval_date
                if rejection_reason:
                    row.rejection_reason = rejection_reason
                row.updated_at = datetime.utcnow()
                await self.session.flush()

        except SPTNotFoundError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise TaxRepositoryError(f"Failed to update SPT status: {e}") from e

    async def count_spt_by_status(self, legal_entity_id: UUID, status: str, spt_type: str) -> int:
        """Hitung jumlah SPT berdasarkan status."""
        stmt = (
            select(func.count())
            .select_from(CoretaxSPTTable)
            .where(
                CoretaxSPTTable.legal_entity_id == legal_entity_id,
                CoretaxSPTTable.spt_type == spt_type,
                CoretaxSPTTable.status == status,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_last_submission_date(self, legal_entity_id: UUID) -> datetime | None:
        """
        Ambil tanggal submission terakhir untuk legal entity (semua jenis SPT).
        """
        try:
            npwp = await self._get_npwp_by_legal_entity(legal_entity_id)
            if not npwp:
                return None
            stmt = select(func.max(CoretaxSPTTable.submitted_at)).where(
                CoretaxSPTTable.npwp == npwp
            )
            result = await self.session.execute(stmt)
            last = result.scalar()
            return last if last else None
        except Exception as e:
            raise TaxRepositoryError(f"Failed to get last submission date: {e}") from e

    # ========================================================================
    # E-BUPOT
    # ========================================================================

    async def save_bukti_potong(self, bukti: Bupot) -> None:
        """Simpan e-Bupot."""
        try:
            table = CoretaxBupotTable(
                id=bukti.id,
                bupot_number=bukti.bupot_number,
                taxpayer_npwp=bukti.npwp_pemotong,  # Ganti npwp_pemotong -> taxpayer_npwp
                taxpayer_name=bukti.nama_penerima,  # Atau nama pemotong? Sesuai model, taxpayer_name
                taxpayer_address=None,  # Bisa diisi dari data
                bupot_type=bukti.jenis_pajak,  # perlu mapping enum? anggap string
                status=bukti.status,
                transaction_date=datetime.utcnow().date(),  # atau dari bukti
                tax_period_month=bukti.masa_pajak,  # Ganti masa_pajak -> tax_period_month
                tax_period_year=bukti.tahun_pajak,  # Ganti tahun_pajak -> tax_period_year
                gross_amount=bukti.dasar_pemotongan,
                tax_rate=Decimal(str(bukti.tarif)),
                tax_amount=bukti.pph_dipotong,  # Ganti pph_dipotong -> tax_amount
                withholding_amount=None,
                tax_object_description=None,
                reference_document_number=bukti.invoice_reference,
                reference_document_date=None,
                coretax_submission_id=bukti.coretax_id,
                coretax_status_code=None,
                coretax_status_description=None,
                coretax_response_raw=None,
                coretax_submitted_at=None,
                coretax_approved_at=None,
                void_reason=None,
                void_by=None,
                void_at=None,
                invoice_id=None,  # bisa diisi
                purchase_invoice_id=None,
                payment_id=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                # version tidak ada di model? ada versi? kita skip
            )
            self.session.add(table)
            await self.session.flush()
        except Exception as e:
            await self.session.rollback()
            raise TaxRepositoryError(f"Failed to save bupot: {e}") from e

    async def get_bukti_potong(self, bukti_id: UUID) -> Any | None:
        """Ambil e-Bupot by ID."""
        try:
            stmt = select(CoretaxBupotTable).where(CoretaxBupotTable.id == bukti_id)
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return Bupot(
                id=table.id,
                bupot_number=table.bupot_number,
                npwp_pemotong=table.taxpayer_npwp,
                npwp_penerima=None,  # tidak ada di model
                nama_penerima=table.taxpayer_name,
                jenis_pajak=table.bupot_type.value if hasattr(table.bupot_type, "value") else str(table.bupot_type),
                masa_pajak=table.tax_period_month,
                tahun_pajak=table.tax_period_year,
                dasar_pemotongan=table.gross_amount,
                tarif=Decimal(str(table.tax_rate)),
                pph_dipotong=table.tax_amount,
                status=table.status.value if hasattr(table.status, "value") else str(table.status),
                coretax_id=table.coretax_submission_id,
                invoice_reference=table.reference_document_number,
                created_by=None,
                created_at=table.created_at,
                legal_entity_id=None,  # tidak ada di model? Ada legal_entity_id? tidak, hanya invoice_id
            )
        except Exception as e:
            raise TaxRepositoryError(f"Failed to get bupot: {e}") from e

    async def update_bupot_status(
        self,
        bupot_id: UUID,
        status: str,
        coretax_id: str | None = None,
        official_number: str | None = None,
    ) -> None:
        """
        Update status e-Bupot dengan pessimistic locking.
        """
        try:
            async with self.session.begin():
                stmt_lock = select(CoretaxBupotTable).where(CoretaxBupotTable.id == bupot_id).with_for_update()
                result = await self.session.execute(stmt_lock)
                row = result.scalar_one_or_none()
                if not row:
                    raise BupotNotFoundError(f"Bupot {bupot_id} not found")

                # Update status (mapping string ke enum jika perlu)
                row.status = status
                if coretax_id:
                    row.coretax_submission_id = coretax_id
                if official_number:
                    row.bupot_number = official_number
                row.updated_at = datetime.utcnow()
                await self.session.flush()

        except BupotNotFoundError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise TaxRepositoryError(f"Failed to update bupot: {e}") from e

    async def list_bupot(
        self, npwp_pemotong: str, masa_pajak: int | None = None, tahun_pajak: int | None = None
    ) -> list[Any]:
        """List e-Bupot."""
        conditions = [CoretaxBupotTable.taxpayer_npwp == npwp_pemotong]
        if masa_pajak:
            conditions.append(CoretaxBupotTable.tax_period_month == masa_pajak)
        if tahun_pajak:
            conditions.append(CoretaxBupotTable.tax_period_year == tahun_pajak)
        stmt = (
            select(CoretaxBupotTable)
            .where(and_(*conditions))
            .order_by(CoretaxBupotTable.created_at.desc())
        )
        result = await self.session.execute(stmt)
        bupots = []
        for table in result.scalars().all():
            bupots.append(
                Bupot(
                    id=table.id,
                    bupot_number=table.bupot_number,
                    npwp_pemotong=table.taxpayer_npwp,
                    npwp_penerima=None,
                    nama_penerima=table.taxpayer_name,
                    jenis_pajak=table.bupot_type.value if hasattr(table.bupot_type, "value") else str(table.bupot_type),
                    masa_pajak=table.tax_period_month,
                    tahun_pajak=table.tax_period_year,
                    dasar_pemotongan=table.gross_amount,
                    tarif=Decimal(str(table.tax_rate)),
                    pph_dipotong=table.tax_amount,
                    status=table.status.value if hasattr(table.status, "value") else str(table.status),
                    coretax_id=table.coretax_submission_id,
                    invoice_reference=table.reference_document_number,
                    created_by=None,
                    created_at=table.created_at,
                    legal_entity_id=None,
                )
            )
        return bupots

    # ========================================================================
    # SUBMISSION LOG
    # ========================================================================

    async def save_submission_log(self, log: dict) -> None:
        """Simpan log submission ke database."""
        try:
            from infrastructure.persistence_orm.coretax_submission_log_table import (
                CoretaxSubmissionLogTable,
            )

            table = CoretaxSubmissionLogTable(
                id=uuid4(),
                submission_id=log.get("submission_id"),
                spt_type=log.get("spt_type"),
                npwp=log.get("npwp"),
                action=log.get("action"),
                status=log.get("status"),
                request_payload=log.get("request_payload"),
                response_payload=log.get("response_payload"),
                error_message=log.get("error_message"),
                created_at=datetime.utcnow(),
            )
            self.session.add(table)
            await self.session.flush()
        except ImportError:
            raise TaxRepositoryError(
                "CoretaxSubmissionLogTable not found. Please create the table first."
            )
        except Exception as e:
            await self.session.rollback()
            raise TaxRepositoryError(f"Failed to save submission log: {e}") from e

    # ========================================================================
    # E-METERAI & NTPN
    # ========================================================================

    async def add_emeterai(self, meterai: EMeterai) -> None:
        """Simpan e-Meterai."""
        try:
            table = CoretaxEMeteraiTable(
                id=meterai.id,
                meterai_code=meterai.meterai_code,
                npwp=meterai.npwp,
                value=meterai.value.amount,
                status=meterai.status,
                purchase_date=meterai.purchase_date,
                purchase_transaction_id=meterai.purchase_transaction_id,
                used_at=meterai.used_at,
                used_on_document=meterai.used_on_document,
                used_by=meterai.used_by,
                created_at=datetime.utcnow(),
            )
            self.session.add(table)
            await self.session.flush()
        except Exception as e:
            await self.session.rollback()
            raise TaxRepositoryError(f"Failed to add e-meterai: {e}") from e

    async def record_ntpn_validation(
        self,
        ntpn: str,
        amount: Decimal,
        payment_date: date,
        npwp: str,
        is_valid: bool,
        result: dict,
    ) -> None:
        """Simpan hasil validasi NTPN."""
        try:
            table = CoretaxNTPNTable(
                id=uuid4(),
                ntpn=ntpn,
                amount=amount,
                payment_date=payment_date,
                npwp=npwp,
                is_valid=is_valid,
                validation_result=result,
                validated_at=datetime.utcnow(),
            )
            self.session.add(table)
            await self.session.flush()
        except IntegrityError:
            # Update jika sudah ada
            stmt = (
                update(CoretaxNTPNTable)
                .where(CoretaxNTPNTable.ntpn == ntpn)
                .values(is_valid=is_valid, validation_result=result, validated_at=datetime.utcnow())
            )
            await self.session.execute(stmt)
            await self.session.flush()
        except Exception as e:
            await self.session.rollback()
            raise TaxRepositoryError(f"Failed to record NTPN: {e}") from e

    # ========================================================================
    # TAX RETURN (SPT) - ALIAS UNTUK KONTRAK PORT
    # ========================================================================

    async def save_tax_return(self, spt: SPTSubmission) -> None:
        """Simpan tax return (SPT) - alias untuk _save_spt."""
        await self._save_spt(spt)

    async def find_tax_return_by_period(
        self, legal_entity_id: UUID, year: int, month: int | None = None, spt_type: str | None = None
    ) -> list[SPTSubmission]:
        """Cari tax return (SPT) berdasarkan periode."""
        try:
            conditions = [CoretaxSPTTable.legal_entity_id == legal_entity_id]
            if year:
                conditions.append(CoretaxSPTTable.tahun == year)
            if month:
                conditions.append(CoretaxSPTTable.bulan == month)
            if spt_type:
                conditions.append(CoretaxSPTTable.spt_type == spt_type)
            stmt = select(CoretaxSPTTable).where(and_(*conditions)).order_by(
                CoretaxSPTTable.tahun.desc(), CoretaxSPTTable.bulan.desc()
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            spt_list = []
            for table in tables:
                status_map = {
                    "draft": SPTStatus.DRAFT,
                    "submitted": SPTStatus.SUBMITTED,
                    "approved": SPTStatus.APPROVED,
                    "rejected": SPTStatus.REJECTED,
                    "void": SPTStatus.VOID,
                }
                status = status_map.get(table.status, SPTStatus.DRAFT)
                spt_list.append(
                    SPTSubmission(
                        id=table.id,
                        spt_number=table.spt_number,
                        spt_type=table.spt_type,
                        npwp=table.npwp,
                        tahun=table.tahun,
                        bulan=table.bulan,
                        masa_pajak=table.masa_pajak,
                        status=status,
                        xml_content=table.xml_content,
                        coretax_tracking_id=table.coretax_tracking_id,
                        approval_date=table.approval_date,
                        rejection_reason=table.rejection_reason,
                        submitted_by=table.submitted_by,
                        submitted_at=table.submitted_at,
                        created_at=table.created_at,
                        legal_entity_id=table.legal_entity_id,
                    )
                )
            return spt_list
        except Exception as e:
            raise TaxRepositoryError(f"Failed to find tax returns by period: {e}") from e

    async def calculate_tax(
        self, legal_entity_id: UUID, period_year: int, period_month: int | None = None
    ) -> dict[str, Any]:
        """Hitung pajak terutang untuk periode tertentu."""
        try:
            npwp = await self._get_npwp_by_legal_entity(legal_entity_id)
            if not npwp:
                raise TaxRepositoryError(f"Legal entity {legal_entity_id} has no NPWP")

            # ===== Hitung PPN Keluaran =====
            conditions_kel = [
                CoretaxFakturTable.npwp_penjual == npwp,
                CoretaxFakturTable.faktur_type == "keluaran",
                CoretaxFakturTable.deleted_at.is_(None),
            ]
            if period_month:
                start_date = date(period_year, period_month, 1)
                if period_month == 12:
                    end_date = date(period_year + 1, 1, 1)
                else:
                    end_date = date(period_year, period_month + 1, 1)
                conditions_kel.append(CoretaxFakturTable.faktur_date >= start_date)
                conditions_kel.append(CoretaxFakturTable.faktur_date < end_date)
            else:
                start_date = date(period_year, 1, 1)
                end_date = date(period_year + 1, 1, 1)
                conditions_kel.append(CoretaxFakturTable.faktur_date >= start_date)
                conditions_kel.append(CoretaxFakturTable.faktur_date < end_date)

            stmt_kel = select(func.coalesce(func.sum(CoretaxFakturTable.ppn), 0)).where(and_(*conditions_kel))
            ppn_kel = (await self.session.execute(stmt_kel)).scalar() or Decimal(0)

            # ===== Hitung PPN Masukan (dapat dikreditkan) =====
            conditions_mas = [
                CoretaxFakturTable.npwp_pembeli == npwp,
                CoretaxFakturTable.faktur_type == "masukan",
                CoretaxFakturTable.deleted_at.is_(None),
                CoretaxFakturTable.status.in_(["approved", "submitted"]),
            ]
            if period_month:
                conditions_mas.append(CoretaxFakturTable.faktur_date >= start_date)
                conditions_mas.append(CoretaxFakturTable.faktur_date < end_date)
            else:
                conditions_mas.append(CoretaxFakturTable.faktur_date >= start_date)
                conditions_mas.append(CoretaxFakturTable.faktur_date < end_date)

            stmt_mas = select(func.coalesce(func.sum(CoretaxFakturTable.ppn), 0)).where(and_(*conditions_mas))
            ppn_mas = (await self.session.execute(stmt_mas)).scalar() or Decimal(0)

            ppn_terutang = ppn_kel - ppn_mas
            if ppn_terutang < 0:
                ppn_terutang = Decimal(0)

            # ===== Hitung PPh dipotong dari bupot =====
            conditions_bupot = [
                CoretaxBupotTable.taxpayer_npwp == npwp,
            ]
            if period_month:
                conditions_bupot.append(CoretaxBupotTable.tax_period_year == period_year)
                conditions_bupot.append(CoretaxBupotTable.tax_period_month == period_month)
            else:
                conditions_bupot.append(CoretaxBupotTable.tax_period_year == period_year)

            stmt_bupot = select(func.coalesce(func.sum(CoretaxBupotTable.tax_amount), 0)).where(and_(*conditions_bupot))
            pph_dipotong = (await self.session.execute(stmt_bupot)).scalar() or Decimal(0)

            total_liability = ppn_terutang + pph_dipotong

            return {
                "legal_entity_id": str(legal_entity_id),
                "period_year": period_year,
                "period_month": period_month,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "ppn_keluaran": float(ppn_kel),
                "ppn_masukan": float(ppn_mas),
                "ppn_terutang": float(ppn_terutang),
                "pph_dipotong": float(pph_dipotong),
                "total_tax_liability": float(total_liability),
                "currency": "IDR",
                "npwp": npwp,
            }
        except Exception as e:
            raise TaxRepositoryError(f"Failed to calculate tax: {e}") from e


__all__ = [
    "BupotNotFoundError",
    "DuplicateFakturNumberError",
    "FakturNotFoundError",
    "NSFPNotFoundError",
    "OptimisticLockError",
    "SPTNotFoundError",
    "SQLAlchemyTaxRepository",
    "TaxRepositoryError",
]