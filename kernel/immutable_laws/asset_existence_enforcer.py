#!/usr/bin/env python3
"""
Module: asset_existence_enforcer.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Hukum: aset yang dicatat harus ada secara fisik (verifikasi).
               Memastikan bahwa aset tetap, persediaan, dan aset berwujud lainnya
               yang dicatat dalam neraca benar-benar ada dan dapat diverifikasi.
               Mencegah pencatatan aset fiktif.

Dependencies:
- standard library (hashlib, logging, dataclass, datetime, decimal, enum, typing, uuid, threading)
- kernel.context_holder (get_current_user)
- kernel.immutable_laws.law_violation_exceptions (ImmutableLawViolationError, AssetExistenceViolation)

Audit: Setiap aset baru harus melalui verifikasi keberadaan.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    AssetExistenceViolation,
    LawViolationSeverity,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REPOSITORIES (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackAssetRepository:
    """Fallback asset repository jika infrastructure belum tersedia."""

    def __init__(self):
        self._assets: dict[UUID, dict[str, Any]] = {}
        self._verifications: dict[UUID, list[dict[str, Any]]] = {}
        self._physical_counts: list[dict[str, Any]] = []

    async def get_by_id(self, asset_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        asset = self._assets.get(asset_id)
        if asset and asset.get("legal_entity_id") == legal_entity_id:
            return asset
        return None

    async def get_last_physical_count_date(self, legal_entity_id: UUID) -> datetime | None:
        counts = [c for c in self._physical_counts if c.get("legal_entity_id") == legal_entity_id]
        if counts:
            latest = max(counts, key=lambda x: x.get("counted_at", datetime.min))
            return latest.get("counted_at")
        return None

    async def record_physical_count(
        self,
        legal_entity_id: UUID,
        counted_by: str,
        counted_at: datetime,
        location: str,
        discrepancies: dict[str, Any],
    ) -> UUID:
        count_id = uuid4()
        self._physical_counts.append(
            {
                "count_id": count_id,
                "legal_entity_id": legal_entity_id,
                "counted_by": counted_by,
                "counted_at": counted_at,
                "location": location,
                "discrepancies": discrepancies,
            }
        )
        return count_id

    async def record_verification(
        self,
        asset_id: UUID,
        asset_type: str,
        legal_entity_id: UUID,
        verification_method: str,
        verification_document: str,
        verified_by: str,
        verified_at: datetime,
    ) -> None:
        if asset_id not in self._verifications:
            self._verifications[asset_id] = []
        self._verifications[asset_id].append(
            {
                "asset_type": asset_type,
                "legal_entity_id": legal_entity_id,
                "verification_method": verification_method,
                "verification_document": verification_document,
                "verified_by": verified_by,
                "verified_at": verified_at,
            }
        )

    async def get_last_verification(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
    ) -> dict[str, Any] | None:
        verifications = self._verifications.get(asset_id, [])
        for v in reversed(verifications):
            if v.get("legal_entity_id") == legal_entity_id:
                return v
        return None

    def add_asset(
        self, asset_id: UUID, legal_entity_id: UUID, asset_code: str, asset_type: str
    ) -> None:
        self._assets[asset_id] = {
            "asset_id": asset_id,
            "legal_entity_id": legal_entity_id,
            "asset_code": asset_code,
            "asset_type": asset_type,
            "is_active": True,
        }


class _FallbackInventoryRepository:
    """Fallback inventory repository jika infrastructure belum tersedia."""

    def __init__(self):
        self._items: dict[UUID, dict[str, Any]] = {}

    async def get_by_id(self, item_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        item = self._items.get(item_id)
        if item and item.get("legal_entity_id") == legal_entity_id:
            return item
        return None

    def add_item(self, item_id: UUID, legal_entity_id: UUID, item_code: str) -> None:
        self._items[item_id] = {
            "item_id": item_id,
            "legal_entity_id": legal_entity_id,
            "item_code": item_code,
        }


# === 2. CONSTANTS & ENUMS ===


class AssetType(Enum):
    """Jenis aset."""

    FIXED_ASSET = "fixed_asset"
    INVENTORY = "inventory"
    INTANGIBLE = "intangible"
    FINANCIAL = "financial"
    BIOLOGICAL = "biological"


class VerificationMethod(Enum):
    """Metode verifikasi keberadaan aset."""

    PHYSICAL_INSPECTION = "physical_inspection"
    DOCUMENT_VERIFICATION = "document_verification"
    THIRD_PARTY_CONFIRMATION = "third_party_confirmation"
    VALUATION_REPORT = "valuation_report"
    LEGAL_TITLE = "legal_title"
    SAMPLE_TESTING = "sample_testing"
    CYCLE_COUNT = "cycle_count"


class VerificationStatus(Enum):
    """Status verifikasi aset."""

    NOT_VERIFIED = "not_verified"
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    DISCREPANCY_FOUND = "discrepancy_found"
    RESOLVED = "resolved"


@dataclass
class VerificationRecord:
    """Rekaman verifikasi aset."""

    record_id: UUID
    asset_id: UUID
    asset_type: AssetType
    legal_entity_id: UUID
    verification_method: VerificationMethod
    verification_document: str
    verified_by: str
    verified_at: datetime
    status: VerificationStatus
    notes: str | None = None
    discrepancy_amount: Decimal | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.record_id}|{self.asset_id}|{self.asset_type.value}|{self.legal_entity_id}|"
            f"{self.verification_method.value}|{self.verification_document}|{self.verified_by}|"
            f"{self.verified_at.isoformat()}|{self.status.value}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": str(self.record_id),
            "asset_id": str(self.asset_id),
            "asset_type": self.asset_type.value,
            "legal_entity_id": str(self.legal_entity_id),
            "verification_method": self.verification_method.value,
            "verification_document": self.verification_document,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at.isoformat(),
            "status": self.status.value,
            "notes": self.notes[:100] if self.notes else None,
        }


@dataclass
class PhysicalCountRecord:
    """Rekaman stock opname / physical count."""

    count_id: UUID
    legal_entity_id: UUID
    counted_by: str
    counted_at: datetime
    location: str
    discrepancies: dict[str, Any]
    is_adjusted: bool = False
    adjusted_at: datetime | None = None
    adjusted_by: str | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.count_id}|{self.legal_entity_id}|{self.counted_by}|"
            f"{self.counted_at.isoformat()}|{self.location}|{json.dumps(self.discrepancies, sort_keys=True)[:200]}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")


# === 3. ASSET EXISTENCE ENFORCER ===


class AssetExistenceEnforcer:
    """
    Enforcer untuk hukum asset existence.

    Business context: Mencegah fraud pencatatan aset fiktif dengan
    memastikan setiap aset yang dicatat memiliki bukti keberadaan.
    """

    DEFAULT_VERIFICATION_THRESHOLD = Decimal("50000000")  # 50 juta IDR
    PHYSICAL_COUNT_REQUIRED_DAYS = 365

    def __init__(
        self,
        asset_repository: Any | None = None,
        inventory_repository: Any | None = None,
    ):
        self._asset_repo = asset_repository or _FallbackAssetRepository()
        self._inventory_repo = inventory_repository or _FallbackInventoryRepository()
        self._verification_threshold = self.DEFAULT_VERIFICATION_THRESHOLD
        self._verification_records: list[VerificationRecord] = []
        self._physical_counts: list[PhysicalCountRecord] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True

    def enable(self, enabled: bool = True) -> None:
        self._enabled = enabled
        logger.info(f"Asset existence enforcer enabled: {enabled}")

    def set_verification_threshold(self, threshold: Decimal) -> None:
        self._verification_threshold = threshold
        logger.info(f"Asset verification threshold set to {threshold}")

    async def enforce_asset_existence(
        self,
        asset_id: UUID,
        asset_type: AssetType,
        legal_entity_id: UUID,
        amount: Decimal,
        verification_method: VerificationMethod,
        verification_document: str,
        user_id: str | None = None,
        notes: str | None = None,
    ) -> VerificationRecord:
        if not self._enabled:
            raise AssetExistenceViolation(
                message="Asset existence enforcer is disabled",
                asset_id=str(asset_id),
                asset_type=asset_type.value,
                severity=LawViolationSeverity.MEDIUM,
            )

        if user_id is None:
            user_id = get_current_user() or "unknown"

        required_methods = self._get_required_methods(asset_type, amount)
        if verification_method not in required_methods:
            raise AssetExistenceViolation(
                message=(
                    f"Asset {asset_id} value {amount} requires verification method in "
                    f"{[m.value for m in required_methods]}. Got {verification_method.value}"
                ),
                asset_id=str(asset_id),
                asset_type=asset_type.value,
                severity=LawViolationSeverity.HIGH,
                details={
                    "amount": str(amount),
                    "required_methods": [m.value for m in required_methods],
                    "provided_method": verification_method.value,
                },
            )

        if amount >= self._verification_threshold * 2:
            if verification_method not in [
                VerificationMethod.PHYSICAL_INSPECTION,
                VerificationMethod.THIRD_PARTY_CONFIRMATION,
                VerificationMethod.VALUATION_REPORT,
            ]:
                raise AssetExistenceViolation(
                    message=(
                        f"High-value asset {asset_id} ({amount}) requires physical inspection "
                        "or third-party confirmation"
                    ),
                    asset_id=str(asset_id),
                    asset_type=asset_type.value,
                    severity=LawViolationSeverity.HIGH,
                    details={"amount": str(amount)},
                )

        if not verification_document:
            raise AssetExistenceViolation(
                message=f"Asset {asset_id} requires verification document reference",
                asset_id=str(asset_id),
                asset_type=asset_type.value,
                severity=LawViolationSeverity.HIGH,
            )

        record = VerificationRecord(
            record_id=uuid4(),
            asset_id=asset_id,
            asset_type=asset_type,
            legal_entity_id=legal_entity_id,
            verification_method=verification_method,
            verification_document=verification_document,
            verified_by=user_id,
            verified_at=datetime.now(UTC),
            status=VerificationStatus.VERIFIED,
            notes=notes,
            cryptographic_hash="",
        )
        record.cryptographic_hash = record.compute_hash()

        with self._lock:
            self._verification_records.append(record)
            if len(self._verification_records) > self._max_history:
                self._verification_records = self._verification_records[-self._max_history :]

        await self._asset_repo.record_verification(
            asset_id=asset_id,
            asset_type=asset_type.value,
            legal_entity_id=legal_entity_id,
            verification_method=verification_method.value,
            verification_document=verification_document,
            verified_by=user_id,
            verified_at=datetime.now(UTC),
        )

        logger.info(
            f"Asset {asset_id} existence verified via {verification_method.value} by {user_id}"
        )
        return record

    def _get_required_methods(
        self, asset_type: AssetType, amount: Decimal
    ) -> list[VerificationMethod]:
        base_methods = {
            AssetType.FIXED_ASSET: [
                VerificationMethod.PHYSICAL_INSPECTION,
                VerificationMethod.LEGAL_TITLE,
                VerificationMethod.VALUATION_REPORT,
            ],
            AssetType.INVENTORY: [
                VerificationMethod.PHYSICAL_INSPECTION,
                VerificationMethod.SAMPLE_TESTING,
                VerificationMethod.CYCLE_COUNT,
                VerificationMethod.DOCUMENT_VERIFICATION,
            ],
            AssetType.INTANGIBLE: [
                VerificationMethod.LEGAL_TITLE,
                VerificationMethod.VALUATION_REPORT,
                VerificationMethod.THIRD_PARTY_CONFIRMATION,
            ],
            AssetType.FINANCIAL: [
                VerificationMethod.THIRD_PARTY_CONFIRMATION,
                VerificationMethod.DOCUMENT_VERIFICATION,
            ],
            AssetType.BIOLOGICAL: [
                VerificationMethod.PHYSICAL_INSPECTION,
                VerificationMethod.VALUATION_REPORT,
            ],
        }
        methods = base_methods.get(asset_type, [VerificationMethod.DOCUMENT_VERIFICATION])

        if amount >= self._verification_threshold:
            strong_methods = [
                VerificationMethod.PHYSICAL_INSPECTION,
                VerificationMethod.THIRD_PARTY_CONFIRMATION,
            ]
            methods = [m for m in methods if m in strong_methods] or methods

        return methods

    async def enforce_periodic_verification(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        user_id: str | None = None,
    ) -> None:
        if not self._enabled:
            return

        last_count_date = await self._asset_repo.get_last_physical_count_date(legal_entity_id)
        now = datetime.now(UTC)

        if last_count_date:
            days_since = (now - last_count_date).days
            if days_since > self.PHYSICAL_COUNT_REQUIRED_DAYS:
                raise AssetExistenceViolation(
                    message=(
                        f"No physical asset verification performed in the last "
                        f"{self.PHYSICAL_COUNT_REQUIRED_DAYS} days (last: {last_count_date.date()})"
                    ),
                    asset_id=str(legal_entity_id),
                    asset_type="ENTITY",
                    severity=LawViolationSeverity.HIGH,
                    details={
                        "legal_entity_id": str(legal_entity_id),
                        "last_physical_count": last_count_date.isoformat(),
                        "days_since": days_since,
                        "required_days": self.PHYSICAL_COUNT_REQUIRED_DAYS,
                    },
                )
        else:
            logger.warning(f"No physical count ever recorded for entity {legal_entity_id}")

    async def record_physical_count(
        self,
        legal_entity_id: UUID,
        counted_by: str,
        location: str,
        discrepancies: dict[str, Any],
        user_id: str | None = None,
    ) -> PhysicalCountRecord:
        if user_id is None:
            user_id = get_current_user() or "unknown"

        record = PhysicalCountRecord(
            count_id=uuid4(),
            legal_entity_id=legal_entity_id,
            counted_by=counted_by,
            counted_at=datetime.now(UTC),
            location=location,
            discrepancies=discrepancies,
            is_adjusted=False,
            cryptographic_hash="",
        )
        record.cryptographic_hash = record.compute_hash()

        with self._lock:
            self._physical_counts.append(record)
            if len(self._physical_counts) > self._max_history:
                self._physical_counts = self._physical_counts[-self._max_history :]

        await self._asset_repo.record_physical_count(
            legal_entity_id=legal_entity_id,
            counted_by=counted_by,
            counted_at=datetime.now(UTC),
            location=location,
            discrepancies=discrepancies,
        )

        logger.info(
            f"Physical count {record.count_id} recorded for entity {legal_entity_id} by {counted_by}"
        )
        return record

    async def get_asset_verification_status(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
    ) -> dict[str, Any]:
        verification = await self._asset_repo.get_last_verification(asset_id, legal_entity_id)
        if not verification:
            return {
                "asset_id": str(asset_id),
                "is_verified": False,
                "message": "No verification record found",
            }
        return {
            "asset_id": str(asset_id),
            "is_verified": True,
            "verification_method": verification.get("verification_method"),
            "verified_by": verification.get("verified_by"),
            "verified_at": verification.get("verified_at"),
            "document_ref": verification.get("verification_document"),
        }

    def get_verification_history(
        self,
        asset_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        limit: int = 100,
    ) -> list[VerificationRecord]:
        with self._lock:
            result = self._verification_records[-limit:]
        if asset_id:
            result = [r for r in result if r.asset_id == asset_id]
        if legal_entity_id:
            result = [r for r in result if r.legal_entity_id == legal_entity_id]
        return result

    def get_physical_count_history(
        self,
        legal_entity_id: UUID | None = None,
        limit: int = 100,
    ) -> list[PhysicalCountRecord]:
        with self._lock:
            result = self._physical_counts[-limit:]
        if legal_entity_id:
            result = [r for r in result if r.legal_entity_id == legal_entity_id]
        return result

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_verifications = len(self._verification_records)
            total_physical_counts = len(self._physical_counts)
            if total_verifications == 0 and total_physical_counts == 0:
                return {
                    "total_verifications": 0,
                    "total_physical_counts": 0,
                    "enabled": self._enabled,
                }

            by_asset_type = {}
            for r in self._verification_records:
                at = r.asset_type.value
                by_asset_type[at] = by_asset_type.get(at, 0) + 1

            by_method = {}
            for r in self._verification_records:
                vm = r.verification_method.value
                by_method[vm] = by_method.get(vm, 0) + 1

            return {
                "total_verifications": total_verifications,
                "total_physical_counts": total_physical_counts,
                "by_asset_type": by_asset_type,
                "by_verification_method": by_method,
                "verification_threshold": str(self._verification_threshold),
                "physical_count_required_days": self.PHYSICAL_COUNT_REQUIRED_DAYS,
                "enabled": self._enabled,
                "latest_verification": self._verification_records[-1].verified_at.isoformat()
                if self._verification_records
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._verification_records = []
            self._physical_counts = []
            self._enabled = True


# === 4. SINGLETON ACCESSOR ===

_asset_existence_enforcer_instance: AssetExistenceEnforcer | None = None
_lock_instance = threading.Lock()


def get_asset_existence_enforcer() -> AssetExistenceEnforcer:
    global _asset_existence_enforcer_instance
    if _asset_existence_enforcer_instance is None:
        with _lock_instance:
            if _asset_existence_enforcer_instance is None:
                _asset_existence_enforcer_instance = AssetExistenceEnforcer()
    return _asset_existence_enforcer_instance


# === 5. EXPORTS ===

__all__ = [
    "AssetExistenceEnforcer",
    "AssetType",
    "PhysicalCountRecord",
    "VerificationMethod",
    "VerificationRecord",
    "VerificationStatus",
    "get_asset_existence_enforcer",
]
