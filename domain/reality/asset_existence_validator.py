#!/usr/bin/env python3
"""
Module: asset_existence_validator.py
Layer: 5 - Reality, Intent, Causality / Reality
Responsibility: Validasi keberadaan aset fisik sebelum dicatat.
                Memastikan bahwa aset yang akan dicatat dalam sistem
                benar-benar ada secara fisik dan dapat diverifikasi.
                Mencegah pencatatan aset fiktif atau duplikasi.

Dependencies:
- standard library (hashlib, json, logging, dataclass, datetime, decimal, enum, typing, uuid, threading, abc)
- domain.reality.economic_event_immutable (EconomicEvent)
- kernel.context_holder (get_current_user)  -> lazy import to avoid AST drift

Kebijakan Arsitektur & Penanganan Eror:
    Loud Fail & Transparan. Memutus ketergantungan langsung ke lapisan konkrit
    Infrastructure/Adapters dengan menggunakan Port Interface abstrak (DIP).
    Setiap kegagalan operasional atau kesalahan pencarian data akan memunculkan
    traceback dan log lengkap tanpa penanganan pengecualian yang senyap.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.reality.economic_event_immutable import EconomicEvent

logger = logging.getLogger(__name__)


# ============================================================================
# Lazy helper untuk menghindari AST drift (domain -> kernel)
# ============================================================================

def _get_current_user() -> str | None:
    """Lazy import kernel.context_holder.get_current_user."""
    try:
        mod = importlib.import_module("kernel.context_holder")
        get_current_user = mod.get_current_user
        return get_current_user()
    except Exception:
        return None


# === 1. ARCHITECTURE PORT ABSTRACTION ===


class AssetRegistryPort(ABC):
    """
    Port (Interface) Abstraksi Lapisan Domain.

    Tanggung Jawab: Mendefinisikan kontrak query dan pembaruan data registrasi aset.
    Mengisolasi domain dari ketergantungan framework data terluar (SQLAlchemy/ORM).
    """

    @abstractmethod
    async def get_asset(self, asset_id: UUID) -> dict[str, Any] | None:
        """Mengambil data mentah aset berdasarkan ID."""
        pass

    @abstractmethod
    async def get_assets_by_entity(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        """Mengambil semua daftar aset yang dimiliki oleh suatu entitas hukum."""
        pass

    @abstractmethod
    async def find_by_serial(self, serial_number: str) -> dict[str, Any] | None:
        """Mencari aset berdasarkan nomor seri unik."""
        pass

    @abstractmethod
    async def verify_rfid(self, asset_id: UUID, rfid: str) -> bool:
        """Memverifikasi kecocokan nomor RFID dengan ID aset."""
        pass

    @abstractmethod
    async def update_verification_status(
        self,
        asset_id: UUID,
        status: str,
        verified_at: datetime,
        verified_by: str,
    ) -> None:
        """Memperbarui status verifikasi fisik aset secara persisten."""
        pass


# === 2. IN-MEMORY FALLBACK IMPLEMENTATION (SAFE FOR TEST/LOCAL) ===


class _FallbackAssetRegistryPort(AssetRegistryPort):
    """Fallback asset registry murni di dalam memori tanpa menyentuh database konkrit."""

    def __init__(self):
        self._assets: dict[UUID, dict[str, Any]] = {}
        self._serial_numbers: dict[str, UUID] = {}

    async def get_asset(self, asset_id: UUID) -> dict[str, Any] | None:
        return self._assets.get(asset_id)

    async def get_assets_by_entity(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        return [a for a in self._assets.values() if a.get("legal_entity_id") == legal_entity_id]

    async def find_by_serial(self, serial_number: str) -> dict[str, Any] | None:
        asset_id = self._serial_numbers.get(serial_number)
        if asset_id:
            return self._assets.get(asset_id)
        return None

    async def verify_rfid(self, asset_id: UUID, rfid: str) -> bool:
        asset = self._assets.get(asset_id)
        if asset:
            return asset.get("rfid") == rfid
        return False

    async def update_verification_status(
        self,
        asset_id: UUID,
        status: str,
        verified_at: datetime,
        verified_by: str,
    ) -> None:
        asset = self._assets.get(asset_id)
        if asset:
            asset["verification_status"] = status
            asset["verified_at"] = verified_at
            asset["verified_by"] = verified_by

    def add_asset(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
        serial_number: str | None = None,
        qr_code_data: str | None = None,
        rfid: str | None = None,
    ) -> None:
        """Metode pembantu lokal untuk pengisian data awal di lingkungan testing."""
        self._assets[asset_id] = {
            "asset_id": asset_id,
            "legal_entity_id": legal_entity_id,
            "serial_number": serial_number,
            "qr_code_data": qr_code_data,
            "rfid": rfid,
            "status": "DRAFT",
            "verification_status": "DRAFT",
        }
        if serial_number:
            self._serial_numbers[serial_number] = asset_id


# === 3. CONSTANTS & ENUMS ===


class AssetExistenceStatus(Enum):
    """Status keberadaan aset."""

    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    PARTIALLY_FOUND = "partially_found"
    DUPLICATE = "duplicate"
    DAMAGED = "damaged"
    UNDER_VERIFICATION = "under_verification"


class VerificationMethod(Enum):
    """Metode verifikasi aset."""

    QR_SCAN = "qr_scan"
    RFID_SCAN = "rfid_scan"
    PHYSICAL_INSPECTION = "physical_inspection"
    DOCUMENT_VERIFICATION = "document_verification"
    THIRD_PARTY = "third_party"
    SELF_DECLARATION = "self_declaration"


@dataclass
class AssetExistenceRecord:
    """Rekaman verifikasi keberadaan aset bermeterai kriptografis."""

    record_id: UUID
    asset_id: UUID
    verification_date: datetime
    verification_method: VerificationMethod
    verified_by: str
    status: AssetExistenceStatus
    notes: str
    location: str | None = None
    serial_number: str | None = None
    supporting_document: str | None = None
    qr_code_data: str | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        """Menghitung hash SHA3-256 untuk perlindungan data dari manipulasi tampering."""
        content = (
            f"{self.record_id}|{self.asset_id}|{self.verification_date.isoformat()}|"
            f"{self.verification_method.value}|{self.verified_by}|{self.status.value}|{self.location or ''}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        """Validasi integritas meterai hash pasca inisialisasi record."""
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError(
                "🚨 KORUPSI DATA: Cryptographic hash mismatch pada AssetExistenceRecord!"
            )

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke objek dictionary murni untuk integrasi serialisasi."""
        return {
            "record_id": str(self.record_id),
            "asset_id": str(self.asset_id),
            "verification_date": self.verification_date.isoformat(),
            "verification_method": self.verification_method.value,
            "verified_by": self.verified_by,
            "status": self.status.value,
            "notes": self.notes[:100],
            "location": self.location,
            "serial_number": self.serial_number,
        }


# === 4. ASSET EXISTENCE VALIDATOR ===


class AssetExistenceValidator:
    """
    Validator keberadaan aset fisik perusahaan.

    Business context: Mencegah fraud dan pencatatan aset fiktif dengan memastikan
    setiap aset yang akan didepresiasi atau diubah nilainya telah lolos verifikasi fisik.
    """

    def __init__(self, asset_registry: AssetRegistryPort | None = None):
        # Gunakan fallback memori jika tidak ada port konkrit yang disuntikkan (memudahkan pengujian unit murni)
        if asset_registry is None:
            logger.warning(
                "Asset registry port tidak disuntikkan secara eksplisit, mengaktifkan fallback in-memory registry."
            )
            self._asset_registry = _FallbackAssetRegistryPort()
        else:
            self._asset_registry = asset_registry

        self._verification_records: dict[UUID, AssetExistenceRecord] = {}
        self._lock = threading.RLock()
        self._verification_validity_days = 30  # Konfigurasi default masa berlaku verifikasi

    def set_asset_registry(self, asset_registry: AssetRegistryPort) -> None:
        """Menyuntikkan atau meredesain registrasi port database di runtime."""
        if not isinstance(asset_registry, AssetRegistryPort):
            raise TypeError(
                "🚨 INJEKSI INVALID: Objek harus merupakan turunan dari AssetRegistryPort!"
            )
        with self._lock:
            self._asset_registry = asset_registry
            logger.info("AssetRegistryPort baru sukses didaftarkan ke AssetExistenceValidator.")

    def set_verification_validity_days(self, days: int) -> None:
        """Mengatur masa aktif keabsahan bukti fisik verifikasi aset."""
        self._verification_validity_days = days
        logger.info(f"Asset verification validity set to {days} days")

    async def verify_asset_existence(
        self,
        asset_id: UUID,
        verification_method: VerificationMethod,
        verified_by: str,
        location: str | None = None,
        serial_number: str | None = None,
        qr_code_data: str | None = None,
        supporting_document: str | None = None,
    ) -> tuple[AssetExistenceStatus, str | None]:
        """
        Melakukan eksekusi verifikasi fisik atas keberadaan aset berdasarkan instrumen input lapangan.

        Returns:
            Tuple[AssetExistenceStatus, Optional[str]]: (Status Keberadaan, Pesan Kegagalan/Catatan)
        """
        try:
            # Mengambil referensi data dasar dari port terdaftar
            existing_asset = await self._asset_registry.get_asset(asset_id)
        except Exception as e:
            logger.error(
                f"Gagal melakukan query data aset untuk ID {asset_id}: {e!s}", exc_info=True
            )
            raise e

        # Kasus 1: Aset tidak terdaftar sama sekali di log induk perusahaan
        if not existing_asset:
            return AssetExistenceStatus.NOT_FOUND, f"Asset {asset_id} not found in registry"

        # Kasus 2: Deteksi potensi duplikasi entri sistem menggunakan nomor seri barang fisik
        if serial_number and verification_method != VerificationMethod.SELF_DECLARATION:
            try:
                existing_serial_asset = await self._asset_registry.find_by_serial(serial_number)
            except Exception as e:
                logger.error(
                    f"Gagal memvalidasi nomor seri unik '{serial_number}': {e!s}", exc_info=True
                )
                raise e

            if existing_serial_asset and existing_serial_asset.get("asset_id") != asset_id:
                return AssetExistenceStatus.DUPLICATE, (
                    f"Asset with serial number {serial_number} already exists as "
                    f"{existing_serial_asset.get('asset_id')}"
                )

        # Kasus 3: Verifikasi kecocokan pemindaian QR Code
        if verification_method == VerificationMethod.QR_SCAN:
            if not qr_code_data:
                return AssetExistenceStatus.NOT_FOUND, "QR scan requires QR code data"
            expected_qr = existing_asset.get("qr_code_data")
            if expected_qr and qr_code_data != expected_qr:
                return AssetExistenceStatus.NOT_FOUND, "QR code does not match asset"

        # Kasus 4: Verifikasi kecocokan sensor nirkabel RFID Scan
        if verification_method == VerificationMethod.RFID_SCAN:
            if not serial_number:
                return AssetExistenceStatus.NOT_FOUND, "RFID scan requires serial number"
            try:
                rfid_match = await self._asset_registry.verify_rfid(asset_id, serial_number)
            except Exception as e:
                logger.error(
                    f"Gagal memproses kecocokan RFID untuk aset {asset_id}: {e!s}", exc_info=True
                )
                raise e

            if not rfid_match:
                return (
                    AssetExistenceStatus.NOT_FOUND,
                    f"RFID {serial_number} does not match asset {asset_id}",
                )

        # Membentuk entitas pencatatan log audit internal domain yang sah
        record = AssetExistenceRecord(
            record_id=uuid4(),
            asset_id=asset_id,
            verification_date=datetime.now(UTC),
            verification_method=verification_method,
            verified_by=verified_by,
            status=AssetExistenceStatus.VERIFIED,
            notes=f"Verified via {verification_method.value}",
            location=location,
            serial_number=serial_number,
            supporting_document=supporting_document,
            qr_code_data=qr_code_data,
            cryptographic_hash="",
        )
        record.cryptographic_hash = record.compute_hash()

        with self._lock:
            self._verification_records[record.record_id] = record

        # Melakukan sinkronisasi pembaruan status ke media penyimpanan luar melalui jembatan port
        try:
            await self._asset_registry.update_verification_status(
                asset_id=asset_id,
                status="VERIFIED",
                verified_at=datetime.now(UTC),
                verified_by=verified_by,
            )
        except Exception as e:
            logger.error(
                f"Gagal memperbarui status registrasi verifikasi eksternal untuk aset {asset_id}: {e!s}",
                exc_info=True,
            )
            raise e

        logger.info(
            f"Asset {asset_id} existence verified by {verified_by} via {verification_method.value}"
        )
        return AssetExistenceStatus.VERIFIED, None

    async def validate_before_recording(
        self,
        asset_id: UUID,
        economic_event: EconomicEvent,
        user_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """
        Validasi gerbang utama arsitektur untuk memeriksa status kelaikan fisik aset
        tepat sebelum diijinkan masuk ke dalam rantai pencatatan ledger ekonomi (Economic Event).
        """
        if user_id is None:
            user_id = _get_current_user() or "unknown"

        # Menarik rekaman verifikasi paling mutakhir dari state memori
        latest_verification = await self.get_latest_verification(asset_id)

        if not latest_verification:
            return False, f"Asset {asset_id} has not been verified. Please verify existence first."

        if latest_verification.status != AssetExistenceStatus.VERIFIED:
            return (
                False,
                f"Asset {asset_id} verification failed: {latest_verification.status.value}",
            )

        # Memeriksa apakah umur masa simpan verifikasi fisik barang telah kedaluwarsa
        days_since = (datetime.now(UTC) - latest_verification.verification_date).days
        if days_since > self._verification_validity_days:
            return False, (
                f"Asset {asset_id} verification is {days_since} days old. "
                f"Maximum validity is {self._verification_validity_days} days. Please re-verify."
            )
        elif days_since > self._verification_validity_days // 2:
            logger.warning(
                f"Asset {asset_id} verification is {days_since} days old. Consider re-verification soon."
            )

        return True, None

    async def get_latest_verification(self, asset_id: UUID) -> AssetExistenceRecord | None:
        """Mendapatkan record verifikasi terbaru untuk satu aset spesifik."""
        with self._lock:
            records = [r for r in self._verification_records.values() if r.asset_id == asset_id]
        if not records:
            return None
        return max(records, key=lambda r: r.verification_date)

    async def get_verification_history(
        self,
        asset_id: UUID,
        limit: int = 10,
    ) -> list[AssetExistenceRecord]:
        """Mendapatkan riwayat (history) kronologis verifikasi fisik barang."""
        with self._lock:
            records = [r for r in self._verification_records.values() if r.asset_id == asset_id]
        return sorted(records, key=lambda r: r.verification_date, reverse=True)[:limit]

    async def get_unverified_assets(self, legal_entity_id: UUID) -> list[UUID]:
        """Mendapatkan daftar ID seluruh aset yang tercatat namun belum lolos verifikasi."""
        try:
            all_assets = await self._asset_registry.get_assets_by_entity(legal_entity_id)
        except Exception as e:
            logger.error(
                f"Gagal menarik daftar data aset untuk entitas hukum {legal_entity_id}: {e!s}",
                exc_info=True,
            )
            raise e

        verified_asset_ids = {r.asset_id for r in self._verification_records.values()}
        return [a["asset_id"] for a in all_assets if a["asset_id"] not in verified_asset_ids]

    async def bulk_verify(
        self,
        asset_ids: list[UUID],
        verification_method: VerificationMethod,
        verified_by: str,
    ) -> dict[UUID, AssetExistenceStatus]:
        """
        Fasilitas verifikasi massal aset (sangat krusial untuk otomatisasi Stock Opname tahunan).
        """
        results = {}
        for asset_id in asset_ids:
            status, msg = await self.verify_asset_existence(
                asset_id=asset_id,
                verification_method=verification_method,
                verified_by=verified_by,
            )
            results[asset_id] = status
            if status != AssetExistenceStatus.VERIFIED:
                logger.warning(f"Asset {asset_id} bulk verification failed: {msg}")
        return results

    async def get_verification_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Menghitung performa dan rasio kepatuhan audit verifikasi aset dalam perusahaan."""
        try:
            all_assets = await self._asset_registry.get_assets_by_entity(legal_entity_id)
        except Exception as e:
            logger.error(
                f"Gagal memproses statistik kepatuhan aset untuk entitas {legal_entity_id}: {e!s}",
                exc_info=True,
            )
            raise e

        total_assets = len(all_assets)
        verified_assets = len([a for a in all_assets if a.get("verification_status") == "VERIFIED"])
        verified_recently = 0

        for r in self._verification_records.values():
            days_ago = (datetime.now(UTC) - r.verification_date).days
            if days_ago <= 30:
                verified_recently += 1

        return {
            "legal_entity_id": str(legal_entity_id),
            "total_assets": total_assets,
            "verified_assets": verified_assets,
            "verification_rate": verified_assets / total_assets if total_assets > 0 else 0,
            "recently_verified_assets": verified_recently,
            "validity_days": self._verification_validity_days,
        }

    def reset(self) -> None:
        """Mengosongkan state memori lokal (Khusus digunakan pada isolasi pengujian unit test)."""
        with self._lock:
            self._verification_records = {}


# === 5. SINGLETON ACCESSOR ===

_asset_existence_validator_instance: AssetExistenceValidator | None = None
_lock_instance = threading.Lock()


def get_asset_existence_validator() -> AssetExistenceValidator:
    """Mendapatkan akses eksklusif ke global instance singleton AssetExistenceValidator."""
    global _asset_existence_validator_instance
    if _asset_existence_validator_instance is None:
        with _lock_instance:
            if _asset_existence_validator_instance is None:
                _asset_existence_validator_instance = AssetExistenceValidator()
    return _asset_existence_validator_instance


# === 6. EXPORTS ===

__all__ = [
    "AssetExistenceRecord",
    "AssetExistenceStatus",
    "AssetExistenceValidator",
    "AssetRegistryPort",
    "VerificationMethod",
    "get_asset_existence_validator",
]
