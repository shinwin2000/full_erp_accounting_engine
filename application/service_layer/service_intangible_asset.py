# service_intangible_asset.py - Complete rewrite with full implementation

from __future__ import annotations

"""
Service Layer untuk Intangible Asset Management
Menangani:
- Pencatatan aset tidak berwujud (lisensi, paten, software, dll)
- Amortisasi bulanan/tahunan
- Impairment testing
- Revaluasi (jika diizinkan standar)
- Penghentian/penjualan aset
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from application.dto_objects.intangible_asset_request import (
    DisposeAssetRequest,
    ImpairmentTestRequest,
)
from domain.intangible_asset.amortization_schedule_engine import AmortizationScheduleEngine
from domain.intangible_asset.asset_entity import IntangibleAssetEntity, IntangibleAssetStatus
from ports.primary.cache_port import CachePort
from ports.primary.intangible_asset_repository_port import IntangibleAssetRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class AmortizationMethod(str, Enum):
    """Metode amortisasi aset tidak berwujud."""

    STRAIGHT_LINE = "STRAIGHT_LINE"
    DECLINING_BALANCE = "DECLINING_BALANCE"
    DOUBLE_DECLINING = "DOUBLE_DECLINING"
    SUM_OF_YEARS = "SUM_OF_YEARS"


class IntangibleAssetType(str, Enum):
    """Jenis aset tidak berwujud."""

    PATENT = "PATENT"
    LICENSE = "LICENSE"
    SOFTWARE = "SOFTWARE"
    GOODWILL = "GOODWILL"
    TRADEMARK = "TRADEMARK"
    COPYRIGHT = "COPYRIGHT"
    FRANCHISE = "FRANCHISE"


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class CreateIntangibleAssetRequestDTO:
    """Request DTO untuk membuat intangible asset baru."""

    legal_entity_id: UUID
    asset_code: str
    asset_name: str
    asset_type: str
    acquisition_date: date
    acquisition_cost: Decimal
    residual_value: Decimal = Decimal("0")
    useful_life_years: int = 5
    amortization_method: str = "STRAIGHT_LINE"
    description: str | None = None
    supplier_id: UUID | None = None
    is_active: bool = True


@dataclass(kw_only=True)
class IntangibleAssetResponse:
    """Response DTO untuk intangible asset."""

    id: UUID
    asset_code: str
    asset_name: str
    asset_type: str
    acquisition_date: date
    acquisition_cost: Decimal
    residual_value: Decimal
    useful_life_years: int
    amortization_method: str
    accumulated_amortization: Decimal
    carrying_amount: Decimal
    status: str
    is_active: bool
    created_at: datetime
    impairment_loss: Decimal = Decimal("0")
    revaluation_surplus: Decimal = Decimal("0")


@dataclass(kw_only=True)
class AmortizationEntry:
    """Entry amortisasi untuk satu periode."""

    period: str
    amount: Decimal
    accumulated_after: Decimal
    carrying_after: Decimal


@dataclass(kw_only=True)
class AmortizationRunResult:
    """Hasil run amortisasi."""

    asset_id: UUID
    period: str
    amount: Decimal
    success: bool
    error: str | None = None
    journal_id: UUID | None = None


@dataclass(kw_only=True)
class DisposalResult:
    """Hasil disposal aset."""

    asset_id: UUID
    asset_code: str
    disposal_amount: Decimal
    carrying_amount: Decimal
    gain_loss: Decimal
    gain_loss_type: str  # GAIN or LOSS
    journal_id: UUID | None = None


# ============================================================================
# Exceptions
# ============================================================================


class IntangibleAssetServiceError(Exception):
    pass


class AssetNotFoundError(IntangibleAssetServiceError):
    pass


class AssetAlreadyDisposedError(IntangibleAssetServiceError):
    pass


class InvalidAmortizationMethodError(IntangibleAssetServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class IntangibleAssetService:
    """Layanan untuk aset tidak berwujud."""

    def __init__(
        self,
        asset_repo: IntangibleAssetRepositoryPort,
        uow: UnitOfWorkPort,
        cache: CachePort | None = None,
    ):
        if asset_repo is None:
            raise ValueError("asset_repo is required")
        if uow is None:
            raise ValueError("uow is required")

        self.asset_repo = asset_repo
        self.uow = uow
        self.cache = cache
        self._stats = {"assets_created": 0, "amortizations": 0, "impairments": 0, "disposals": 0}

        logger.info("IntangibleAssetService initialized")

    # ========================== CRUD ASET ==========================

    async def create_asset(
        self, request: CreateIntangibleAssetRequestDTO, created_by: UUID | None = None
    ) -> IntangibleAssetResponse:
        """Buat aset tidak berwujud baru."""
        # Validasi
        if request.acquisition_cost <= 0:
            raise ValueError("Acquisition cost must be positive")
        if request.useful_life_years <= 0:
            raise ValueError("Useful life must be > 0 tahun")
        if request.residual_value < 0:
            raise ValueError("Residual value cannot be negative")
        if request.residual_value > request.acquisition_cost:
            raise ValueError("Residual value cannot exceed acquisition cost")

        # Validasi amortization method
        valid_methods = [m.value for m in AmortizationMethod]
        if request.amortization_method.upper() not in valid_methods:
            raise InvalidAmortizationMethodError(
                f"Invalid amortization method: {request.amortization_method}"
            )

        # Validasi asset type
        valid_types = [t.value for t in IntangibleAssetType]
        if request.asset_type.upper() not in valid_types:
            raise ValueError(f"Invalid asset type: {request.asset_type}")

        asset = IntangibleAssetEntity(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            asset_code=request.asset_code,
            asset_name=request.asset_name,
            asset_type=request.asset_type,
            acquisition_date=request.acquisition_date,
            acquisition_cost=request.acquisition_cost,
            residual_value=request.residual_value,
            useful_life_years=request.useful_life_years,
            amortization_method=request.amortization_method,
            description=request.description,
            created_by=created_by,
            created_at=datetime.now(UTC),
            status=IntangibleAssetStatus.ACTIVE,
            is_active=request.is_active,
        )

        # Hitung carrying amount awal
        asset.carrying_amount = request.acquisition_cost
        asset.accumulated_amortization = Decimal(0)
        asset.amortizable_amount = request.acquisition_cost - request.residual_value

        await self.asset_repo.save(asset)
        await self.uow.commit()

        # Generate jadwal amortisasi untuk seluruh masa manfaat
        engine = AmortizationScheduleEngine(asset)
        schedules = engine.generate_schedule()
        await self.asset_repo.save_schedules(asset.id, schedules)
        await self.uow.commit()

        # Invalidate cache
        if self.cache:
            await self.cache.delete(f"intangible_asset:{asset.id}")

        self._stats["assets_created"] += 1
        logger.info(f"Intangible asset {asset.asset_code} created")

        return self._to_response(asset)

    async def get_asset(self, asset_id: UUID) -> IntangibleAssetResponse | None:
        """Dapatkan aset berdasarkan ID, dengan cache."""
        if self.cache:
            cached = await self.cache.get(f"intangible_asset:{asset_id}")
            if cached:
                import json

                data = json.loads(cached)
                return IntangibleAssetResponse(**data)

        asset = await self.asset_repo.get_by_id(asset_id)
        if asset and self.cache:
            await self.cache.set(f"intangible_asset:{asset_id}", asset.to_json(), ttl=3600)

        return self._to_response(asset) if asset else None

    async def list_assets_by_legal_entity(
        self, legal_entity_id: UUID, include_inactive: bool = False
    ) -> list[IntangibleAssetResponse]:
        """Daftar aset untuk suatu entitas legal."""
        assets = await self.asset_repo.list_by_legal_entity(legal_entity_id, include_inactive)
        return [self._to_response(a) for a in assets]

    # ========================== AMORTISASI ==========================

    async def run_monthly_amortization(
        self, legal_entity_id: UUID, period_date: date, period_id: UUID, user_id: UUID | None = None
    ) -> list[AmortizationRunResult]:
        """
        Jalankan amortisasi bulanan untuk semua aset tidak berwujud yang aktif.
        Returns list of results per asset.
        """
        assets = await self.asset_repo.get_active_assets_for_amortization(
            legal_entity_id, period_date
        )
        results = []

        for asset in assets:
            try:
                result = await self.amortize_asset(asset.id, period_date, period_id, user_id)
                results.append(result)
                self._stats["amortizations"] += 1
            except Exception as e:
                logger.error(f"Amortization failed for asset {asset.id}: {e}")
                results.append(
                    AmortizationRunResult(
                        asset_id=asset.id,
                        period=f"{period_date.year}-{period_date.month:02d}",
                        amount=Decimal("0"),
                        success=False,
                        error=str(e),
                    )
                )

        await self.uow.commit()
        return results

    async def amortize_asset(
        self, asset_id: UUID, period_date: date, period_id: UUID, user_id: UUID | None = None
    ) -> AmortizationRunResult:
        """
        Hitung dan catat amortisasi untuk satu aset pada periode tertentu.
        """
        asset = await self.asset_repo.get_by_id(asset_id)
        if not asset:
            raise AssetNotFoundError(f"Asset {asset_id} not found")

        if not asset.is_active:
            raise AssetAlreadyDisposedError(f"Asset {asset_id} is already disposed/inactive")

        if asset.last_amortization_date and asset.last_amortization_date >= period_date:
            raise ValueError(f"Amortization already done for {period_date}")

        engine = AmortizationScheduleEngine(asset)
        amount = engine.calculate_period_amortization(period_date)

        if amount <= 0:
            return AmortizationRunResult(
                asset_id=asset_id,
                period=f"{period_date.year}-{period_date.month:02d}",
                amount=Decimal("0"),
                success=True,
            )

        # Catat amortisasi
        asset.accumulated_amortization += amount
        asset.carrying_amount = (
            asset.acquisition_cost - asset.accumulated_amortization - asset.impairment_loss
        )
        asset.last_amortization_date = period_date

        await self.asset_repo.update(asset)

        # Buat jurnal amortisasi (placeholder untuk service journal)
        journal_id = None  # Akan diisi dengan pemanggilan service_journal

        # Simpan schedule
        await self.asset_repo.record_amortization_schedule(
            asset_id=asset_id,
            period_date=period_date,
            planned_amount=amount,
            actual_amount=amount,
            journal_id=journal_id,
            period_id=period_id,
        )
        await self.uow.commit()

        # Invalidate cache
        if self.cache:
            await self.cache.delete(f"intangible_asset:{asset_id}")

        return AmortizationRunResult(
            asset_id=asset_id,
            period=f"{period_date.year}-{period_date.month:02d}",
            amount=amount,
            success=True,
            journal_id=journal_id,
        )

    # ========================== IMPAIRMENT ==========================

    async def test_impairment(
        self, request: ImpairmentTestRequest, user_id: UUID | None = None
    ) -> dict:
        """
        Lakukan impairment test pada aset.
        Jika recoverable amount < carrying amount, catat impairment loss.
        """
        asset = await self.asset_repo.get_by_id(request.asset_id)
        if not asset:
            raise AssetNotFoundError("Asset not found")

        recoverable_amount = request.recoverable_amount
        carrying_before = asset.carrying_amount

        if recoverable_amount < carrying_before:
            loss = carrying_before - recoverable_amount
            asset.impairment_loss += loss
            asset.carrying_amount = recoverable_amount
            asset.impairment_date = request.test_date
            asset.impairment_reason = request.reason
            await self.asset_repo.update(asset)
            await self.uow.commit()

            self._stats["impairments"] += 1

            # Invalidate cache
            if self.cache:
                await self.cache.delete(f"intangible_asset:{asset.id}")

            return {
                "impairment_recognized": True,
                "loss_amount": loss,
                "new_carrying_amount": asset.carrying_amount,
            }
        else:
            return {
                "impairment_recognized": False,
                "loss_amount": Decimal(0),
                "new_carrying_amount": carrying_before,
            }

    # ========================== REVALUASI ==========================

    async def revalue_asset(
        self,
        asset_id: UUID,
        new_fair_value: Decimal,
        revaluation_date: date,
        approved_by: UUID | None = None,
    ) -> dict:
        """
        Revaluasi aset (jika standar mengizinkan).
        Selisih dicatat ke revaluation surplus (ekuitas).
        """
        asset = await self.asset_repo.get_by_id(asset_id)
        if not asset:
            raise AssetNotFoundError("Asset not found")

        old_carrying = asset.carrying_amount
        surplus = new_fair_value - old_carrying

        if surplus == 0:
            return {"revaluation_performed": False, "surplus": Decimal(0)}

        asset.carrying_amount = new_fair_value
        asset.revaluation_surplus += surplus
        asset.last_revaluation_date = revaluation_date
        asset.last_revaluation_by = approved_by

        await self.asset_repo.update(asset)
        await self.uow.commit()

        # Catat revaluation event
        await self.asset_repo.record_revaluation(
            asset_id=asset_id,
            old_amount=old_carrying,
            new_amount=new_fair_value,
            surplus=surplus,
            date=revaluation_date,
            approved_by=approved_by,
        )

        if self.cache:
            await self.cache.delete(f"intangible_asset:{asset_id}")

        return {
            "revaluation_performed": True,
            "surplus": surplus,
            "new_carrying_amount": new_fair_value,
        }

    # ========================== DISPOSAL ==========================

    async def dispose_asset(
        self, request: DisposeAssetRequest, user_id: UUID | None = None
    ) -> DisposalResult:
        """
        Hentikan aset (dijual, dihapus, atau tidak digunakan lagi).
        Menghasilkan gain/loss disposal.
        """
        asset = await self.asset_repo.get_by_id(request.asset_id)
        if not asset:
            raise AssetNotFoundError("Asset not found")

        if not asset.is_active:
            raise AssetAlreadyDisposedError("Asset already disposed")

        # Hitung gain/loss
        net_book_value = asset.carrying_amount
        disposal_amount = request.disposal_amount

        if disposal_amount > net_book_value:
            gain_loss_type = "GAIN"
            gain_loss = disposal_amount - net_book_value
        else:
            gain_loss_type = "LOSS"
            gain_loss = net_book_value - disposal_amount

        asset.is_active = False
        asset.status = IntangibleAssetStatus.DISPOSED
        asset.disposed_date = request.disposal_date
        asset.disposal_amount = disposal_amount
        asset.disposal_reason = request.reason
        asset.disposal_gain_loss = gain_loss_type
        asset.disposal_gain_loss_amount = gain_loss

        await self.asset_repo.update(asset)
        await self.uow.commit()

        self._stats["disposals"] += 1

        if self.cache:
            await self.cache.delete(f"intangible_asset:{asset.id}")

        # Buat jurnal disposal (placeholder)
        journal_id = None

        return DisposalResult(
            asset_id=asset.id,
            asset_code=asset.asset_code,
            disposal_amount=disposal_amount,
            carrying_amount=net_book_value,
            gain_loss=gain_loss,
            gain_loss_type=gain_loss_type,
            journal_id=journal_id,
        )

    # ========================== SCHEDULE ==========================

    async def get_amortization_schedule(
        self, asset_id: UUID, from_date: date | None = None, to_date: date | None = None
    ) -> list[AmortizationEntry]:
        """Dapatkan jadwal amortisasi aset."""
        schedules = await self.asset_repo.get_schedules(asset_id, from_date, to_date)
        return [
            AmortizationEntry(
                period=f"{s.period_year}-{s.period_month:02d}",
                amount=s.amount,
                accumulated_after=s.accumulated_after,
                carrying_after=s.carrying_after,
            )
            for s in schedules
        ]

    # ========================== PRIVATE HELPERS ==========================

    def _to_response(self, asset: IntangibleAssetEntity) -> IntangibleAssetResponse:
        return IntangibleAssetResponse(
            id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_type=asset.asset_type,
            acquisition_date=asset.acquisition_date,
            acquisition_cost=asset.acquisition_cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            amortization_method=asset.amortization_method,
            accumulated_amortization=asset.accumulated_amortization,
            carrying_amount=asset.carrying_amount,
            status=asset.status.value,
            is_active=asset.is_active,
            created_at=asset.created_at,
            impairment_loss=asset.impairment_loss,
            revaluation_surplus=asset.revaluation_surplus,
        )

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_intangible_asset_service(
    asset_repo: IntangibleAssetRepositoryPort,
    uow: UnitOfWorkPort,
    cache: CachePort | None = None,
) -> IntangibleAssetService:
    return IntangibleAssetService(asset_repo, uow, cache)


__all__ = [
    "AmortizationEntry",
    "AmortizationMethod",
    "AmortizationRunResult",
    "AssetAlreadyDisposedError",
    "AssetNotFoundError",
    "CreateIntangibleAssetRequestDTO",
    "DisposalResult",
    "IntangibleAssetResponse",
    "IntangibleAssetService",
    "IntangibleAssetServiceError",
    "IntangibleAssetType",
    "InvalidAmortizationMethodError",
    "create_intangible_asset_service",
]
