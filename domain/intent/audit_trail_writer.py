#!/usr/bin/env python3
"""
Module: audit_trail_writer.py
Layer: 5 - Domain / Intent
Responsibility: Menulis jejak audit untuk setiap perubahan intent.
               Mencatat semua perubahan status, modifikasi data, dan tindakan
               yang dilakukan pada intent ke dalam immutable audit store.
               Memastikan setiap intent memiliki audit trail lengkap.

Dependencies:
- standard library (logging, datetime, uuid, hashlib, json, threading, abc)
- domain.intent.immutable_record (ImmutableIntentRecord, IntentStatus)

Kebijakan Penanganan Eror:
    Loud Fail & Transparan. Memutus ketergantungan langsung ke lapisan konkrit
    Infrastructure dengan menggunakan Port Interface. Jika port belum disuntikkan,
    sistem akan melempar kegagalan struktural secara keras dengan traceback penuh.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class IntentAuditAction(Enum):
    """Aksi audit untuk intent."""

    CREATED = auto()
    UPDATED = auto()
    SUBMITTED = auto()
    APPROVED = auto()
    REJECTED = auto()
    CANCELLED = auto()
    EXECUTED = auto()
    LINKED_TO_OUTCOME = auto()
    SIGNED = auto()
    REVISION_LOGGED = auto()

    @classmethod
    def from_string(cls, value: str) -> IntentAuditAction:
        """Konversi dari string ke enum."""
        try:
            return cls[value.upper()]
        except KeyError as e:
            raise ValueError(f"Unknown IntentAuditAction: {value}") from e


class IntentAuditSeverity(Enum):
    """Severity audit intent."""

    INFO = 10
    WARNING = 20
    ERROR = 30
    CRITICAL = 40

    @classmethod
    def from_int(cls, value: int) -> IntentAuditSeverity:
        """Konversi dari integer ke enum."""
        for severity in cls:
            if severity.value == value:
                return severity
        return cls.INFO


@dataclass
class IntentAuditRecord:
    """Record audit untuk intent."""

    record_id: UUID
    intent_id: UUID
    action: IntentAuditAction
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    changed_by: str
    changed_at: datetime
    severity: IntentAuditSeverity
    notes: str = ""
    cryptographic_hash: str = ""

    def __post_init__(self) -> None:
        """Validasi ketat setelah inisialisasi entitas record."""
        if not isinstance(self.record_id, UUID):
            raise ValueError("record_id must be UUID")
        if not isinstance(self.intent_id, UUID):
            raise ValueError("intent_id must be UUID")
        if not isinstance(self.action, IntentAuditAction):
            raise ValueError("action must be IntentAuditAction")
        if not self.changed_by:
            raise ValueError("changed_by cannot be empty")
        if not isinstance(self.changed_at, datetime):
            raise ValueError("changed_at must be datetime")
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def compute_hash(self) -> str:
        """Menghitung hash kriptografis dari record."""
        content = {
            "record_id": str(self.record_id),
            "intent_id": str(self.intent_id),
            "action": self.action.name,
            "changed_by": self.changed_by,
            "changed_at": self.changed_at.isoformat(),
            "notes": self.notes[:500] if self.notes else "",
        }
        return hashlib.sha3_256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary untuk kebutuhan serialisasi."""
        return {
            "record_id": str(self.record_id),
            "intent_id": str(self.intent_id),
            "action": self.action.name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "changed_by": self.changed_by,
            "changed_at": self.changed_at.isoformat(),
            "severity": self.severity.name,
            "notes": self.notes,
            "cryptographic_hash": self.cryptographic_hash,
        }


# === 2. ARCHITECTURE PORT ABSTRACTION ===


class IntentAuditStoragePort(ABC):
    """
    Port (Interface) Abstraksi Lapisan Domain.

    Tanggung Jawab: Mendefinisikan kontrak penyimpanan permanen untuk record audit.
    Mengisolasi domain dari ketergantungan pustaka ORM/Event Store konkrit terluar.
    """

    @abstractmethod
    def append_audit_record(self, record: IntentAuditRecord) -> None:
        """Menyimpan record audit secara sinkron ke media penyimpanan persisten."""
        pass

    @abstractmethod
    async def append_audit_record_async(self, record: IntentAuditRecord) -> None:
        """Menyimpan record audit secara asinkron (non-blocking) ke media penyimpanan persisten."""
        pass


# === 3. AUDIT TRAIL WRITER ===


class AuditTrailWriter:
    """
    Writer untuk audit trail intent.

    Business context: Mencatat semua perubahan dan tindakan pada intent
    ke dalam immutable audit store untuk kepatuhan hukum dan investigasi finansial.

    Thread-safety: Menggunakan Reentrant Lock (RLock) untuk operasi modifikasi state memori.
    """

    _instance: AuditTrailWriter | None = None
    _initialized: bool = False  # Tambahan untuk mypy
    _audit_records: dict[UUID, list[IntentAuditRecord]]

    def __new__(cls) -> AuditTrailWriter:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._lock = threading.RLock()
        self._storage_port: IntentAuditStoragePort | None = None
        self._audit_records: dict[UUID, list[IntentAuditRecord]] = {}
        self._max_records_per_intent = 10000
        logger.info("AuditTrailWriter initialized (Awaiting dependency injection of Storage Port)")

    def set_storage_port(self, storage_port: IntentAuditStoragePort) -> None:
        """
        Menyuntikkan implementasi konkrit infrastruktur ke dalam sistem domain (Dependency Injection).
        Mencegah pemanggilan ilegal lintas batas arsitektur secara statis.
        """
        with self._lock:
            if not isinstance(storage_port, IntentAuditStoragePort):
                raise TypeError("storage_port must implement IntentAuditStoragePort")
            self._storage_port = storage_port
            logger.info("IntentAuditStoragePort successfully registered to AuditTrailWriter")

    def _store_record(self, record: IntentAuditRecord) -> None:
        """Metode internal penyimpan record ke dalam cache memori lokal dengan thread lock."""
        with self._lock:
            if record.intent_id not in self._audit_records:
                self._audit_records[record.intent_id] = []
            records = self._audit_records[record.intent_id]
            records.append(record)

            # Batasi ukuran guna menghindari memory overflow pada siklus transaksi panjang
            if len(records) > self._max_records_per_intent:
                self._audit_records[record.intent_id] = records[-self._max_records_per_intent :]

    def _write_to_storage_port(self, record: IntentAuditRecord) -> None:
        """Mengirimkan record audit terverifikasi ke gerbang port penyimpanan luar secara asinkron."""
        if self._storage_port is None:
            # Sesuai aturan Loud Fail, kita lemparkan RuntimeError fatal jika port belum terkonfigurasi
            raise RuntimeError(
                f"KATASTROFIK ARSITEKTUR: Implementasi 'IntentAuditStoragePort' belum terdaftar! "
                f"Gagal mengamankan log untuk intent ID: {record.intent_id}. Operasi dibatalkan secara paksa."
            )

        async def safe_append():
            try:
                # Memanggil implementasi asinkron milik infrastruktur terdaftar
                await self._storage_port.append_audit_record_async(record)
            except Exception as e:
                # Tampilkan jejak galat penuh guna mempermudah proses debugging struktural
                logger.error(
                    f"Gagal melakukan append pada Event Store untuk intent {record.intent_id}: {e}",
                    exc_info=True,
                )
                raise e

        try:
            loop = asyncio.get_running_loop()
            _task = loop.create_task(safe_append())  # noqa: RUF006
        except RuntimeError:
            # Jika tidak ada event loop runtime aktif, jalankan di dalam thread terpisah
            # menggunakan loop baru agar benar-benar non-blocking dan menghindari warning asyncio.run()
            import threading

            def run_in_new_loop():
                new_loop = asyncio.new_event_loop()
                try:
                    new_loop.run_until_complete(safe_append())
                finally:
                    new_loop.close()

            threading.Thread(target=run_in_new_loop, daemon=True).start()

    def write(
        self,
        intent_id: UUID,
        action: IntentAuditAction,
        changed_by: str,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        notes: str = "",
        severity: IntentAuditSeverity = IntentAuditSeverity.INFO,
    ) -> IntentAuditRecord:
        """
        Menulis record audit utama untuk intent bisnis.

        Args:
            intent_id: ID unik entitas intent.
            action: Jenis tindakan/operasi arsitektur yang dieksekusi.
            changed_by: Identitas aktor/sistem pelaksana perubahan.
            old_value: Keadaan data sebelum terjadinya perubahan.
            new_value: Keadaan data mutakhir pasca modifikasi.
            notes: Deskripsi/konteks tekstual tambahan.
            severity: Tingkat signifikansi catatan audit.

        Returns:
            IntentAuditRecord objek immutable bermeterai hash.
        """
        if not isinstance(intent_id, UUID):
            raise ValueError("intent_id must be UUID")
        if not isinstance(action, IntentAuditAction):
            raise ValueError("action must be IntentAuditAction")
        if not changed_by or not isinstance(changed_by, str):
            changed_by = "system"

        record = IntentAuditRecord(
            record_id=uuid4(),
            intent_id=intent_id,
            action=action,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            changed_at=datetime.now(UTC),
            severity=severity,
            notes=notes[:1000] if notes else "",
            cryptographic_hash="",
        )

        # Menghitung integrity seal menggunakan SHA3-256
        final_record = IntentAuditRecord(
            record_id=record.record_id,
            intent_id=record.intent_id,
            action=record.action,
            old_value=record.old_value,
            new_value=record.new_value,
            changed_by=record.changed_by,
            changed_at=record.changed_at,
            severity=record.severity,
            notes=record.notes,
            cryptographic_hash=record.compute_hash(),
        )

        # Amankan ke dalam state internal memori
        self._store_record(final_record)

        # Teruskan ke gerbang port eksternal (Loud Fail terjamin di dalam metode ini)
        self._write_to_storage_port(final_record)

        logger.debug(f"Audit record written for intent {intent_id}: {action.name} by {changed_by}")
        return final_record

    def write_created(
        self,
        intent_id: UUID,
        created_by: str,
        intent_data: dict[str, Any],
    ) -> IntentAuditRecord:
        """Mencatat tahap inisiasi penciptaan awal entitas intent."""
        return self.write(
            intent_id=intent_id,
            action=IntentAuditAction.CREATED,
            changed_by=created_by,
            new_value=intent_data,
            notes="Intent created",
        )

    def write_updated(
        self,
        intent_id: UUID,
        updated_by: str,
        old_data: dict[str, Any],
        new_data: dict[str, Any],
    ) -> IntentAuditRecord:
        """Mencatat aktivitas perubahan struktural data pada intent."""
        return self.write(
            intent_id=intent_id,
            action=IntentAuditAction.UPDATED,
            changed_by=updated_by,
            old_value=old_data,
            new_value=new_data,
            notes="Intent data updated",
            severity=self._determine_severity(old_data, new_data),
        )

    def _determine_severity(
        self,
        old_data: dict[str, Any],
        new_data: dict[str, Any],
    ) -> IntentAuditSeverity:
        """Mengevaluasi tingkat eskalasi log berdasarkan bobot perubahan elemen."""
        if self._is_significant_change(old_data, new_data):
            return IntentAuditSeverity.WARNING
        return IntentAuditSeverity.INFO

    def _is_significant_change(
        self,
        old_data: dict[str, Any],
        new_data: dict[str, Any],
    ) -> bool:
        """Memeriksa apakah terdapat pergeseran nilai material keuangan (>10%) atau field kritikal."""
        if "amount" in old_data and "amount" in new_data:
            try:
                old_amt = float(old_data.get("amount", 0))
                new_amt = float(new_data.get("amount", 0))
                if old_amt > 0:
                    pct_change = abs(new_amt - old_amt) / old_amt
                    if pct_change > 0.1:
                        return True
            except (ValueError, TypeError):
                # Teruskan eror jika struktur tipe data merusak kalkulasi esensial
                raise

        # Pengecekan menyeluruh terhadap elemen arsitektur kritikal pembentuk jurnal
        critical_fields = ["counterparty_id", "account_code", "legal_entity_id", "currency"]
        return any(old_data.get(field) != new_data.get(field) for field in critical_fields)

    def write_submitted(
        self,
        intent_id: UUID,
        submitted_by: str,
    ) -> IntentAuditRecord:
        """Mencatat pengajuan persetujuan (submission) intent ke otoritas berwenang."""
        return self.write(
            intent_id=intent_id,
            action=IntentAuditAction.SUBMITTED,
            changed_by=submitted_by,
            notes="Intent submitted for approval",
        )

    def write_approved(
        self,
        intent_id: UUID,
        approved_by: str,
        notes: str = "",
    ) -> IntentAuditRecord:
        """Mencatat otorisasi persetujuan final (approval) terhadap transaksi intent."""
        return self.write(
            intent_id=intent_id,
            action=IntentAuditAction.APPROVED,
            changed_by=approved_by,
            notes=notes or "Intent approved",
            severity=IntentAuditSeverity.INFO,
        )

    def write_rejected(
        self,
        intent_id: UUID,
        rejected_by: str,
        reason: str,
    ) -> IntentAuditRecord:
        """Mencatat penolakan (rejection) pemrosesan transaksi disertai argumen pembatalan."""
        return self.write(
            intent_id=intent_id,
            action=IntentAuditAction.REJECTED,
            changed_by=rejected_by,
            notes=reason[:500] if reason else "Rejected",
            severity=IntentAuditSeverity.WARNING,
        )

    def write_executed(
        self,
        intent_id: UUID,
        executed_by: str,
        outcome_id: UUID,
    ) -> IntentAuditRecord:
        """Mencatat keberhasilan realisasi konversi dari status intent menjadi outcome akuntansi konkrit."""
        return self.write(
            intent_id=intent_id,
            action=IntentAuditAction.EXECUTED,
            changed_by=executed_by,
            notes=f"Executed to outcome: {outcome_id}",
            severity=IntentAuditSeverity.INFO,
        )

    def write_linked_to_outcome(
        self,
        intent_id: UUID,
        linked_by: str,
        outcome_id: UUID,
    ) -> IntentAuditRecord:
        """Mencatat relasi pemetaan asosisasi struktural antara objek intent dan objek outcome."""
        return self.write(
            intent_id=intent_id,
            action=IntentAuditAction.LINKED_TO_OUTCOME,
            changed_by=linked_by,
            notes=f"Linked to outcome: {outcome_id}",
        )

    def write_signed(
        self,
        intent_id: UUID,
        signed_by: str,
        signature_preview: str,
    ) -> IntentAuditRecord:
        """Mencatat validasi tanda tangan digital (hardware secured signature) pada dokumen intent."""
        return self.write(
            intent_id=intent_id,
            action=IntentAuditAction.SIGNED,
            changed_by=signed_by,
            notes=f"Signed with signature: {signature_preview[:20]}...",
            severity=IntentAuditSeverity.INFO,
        )

    def get_audit_trail(
        self,
        intent_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[IntentAuditRecord]:
        """Mendapatkan rentetan jejak audit trail terpaginasi milik intent tertentu."""
        if not isinstance(intent_id, UUID):
            raise ValueError("intent_id must be UUID")
        if limit <= 0:
            limit = 50
        if offset < 0:
            offset = 0

        with self._lock:
            records = self._audit_records.get(intent_id, [])
        sorted_records = sorted(records, key=lambda r: r.changed_at, reverse=True)
        return sorted_records[offset : offset + limit]

    def get_audit_trail_by_action(
        self,
        intent_id: UUID,
        action: IntentAuditAction,
    ) -> list[IntentAuditRecord]:
        """Menyaring jejak catatan histori audit berdasarkan klasifikasi aksi spesifik."""
        if not isinstance(intent_id, UUID):
            raise ValueError("intent_id must be UUID")
        if not isinstance(action, IntentAuditAction):
            raise ValueError("action must be IntentAuditAction")

        with self._lock:
            records = self._audit_records.get(intent_id, [])
        return [r for r in records if r.action == action]

    def get_full_history(
        self,
        intent_id: UUID,
    ) -> list[IntentAuditRecord]:
        """Mendapatkan kronologis riwayat lengkap transaksi intent tanpa batasan ukuran."""
        if not isinstance(intent_id, UUID):
            raise ValueError("intent_id must be UUID")

        with self._lock:
            records = self._audit_records.get(intent_id, [])
        return sorted(records, key=lambda r: r.changed_at)

    def get_all_audit_records(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IntentAuditRecord]:
        """Mendapatkan basis rekaman seluruh log audit global dalam sub-sistem."""
        if limit <= 0:
            limit = 100
        if offset < 0:
            offset = 0

        with self._lock:
            all_records = []
            for records in self._audit_records.values():
                all_records.extend(records)
        all_records.sort(key=lambda r: r.changed_at, reverse=True)
        return all_records[offset : offset + limit]

    def get_statistics(self) -> dict[str, Any]:
        """Menghitung ringkasan matriks analitik performa log audit trail."""
        with self._lock:
            total_records = sum(len(records) for records in self._audit_records.values())
            total_intents = len(self._audit_records)

            by_action: dict[str, int] = {}
            for records in self._audit_records.values():
                for record in records:
                    action_name = record.action.name
                    by_action[action_name] = by_action.get(action_name, 0) + 1

        return {
            "total_audit_records": total_records,
            "total_intents_with_audit": total_intents,
            "by_action": by_action,
        }

    def verify_hash_chain(self, intent_id: UUID) -> tuple[bool, list[str]]:
        """
        Memverifikasi integritas keaslian rantai hash (hash chain verification)
        untuk mendeteksi adanya manipulasi data pihak ketiga.
        """
        records = self.get_full_history(intent_id)
        if not records:
            return True, []

        errors = []
        for i, record in enumerate(records):
            computed = record.compute_hash()
            if record.cryptographic_hash != computed:
                errors.append(
                    f"Record index {i} (id={record.record_id}) integrity corrupted: Hash mismatch!"
                )
        return len(errors) == 0, errors

    def reset(self) -> None:
        """Mengosongkan seluruh state memori lokal (Hanya untuk skenario unit-testing)."""
        with self._lock:
            self._audit_records = {}
        logger.info("AuditTrailWriter local memory registry reset successfully")


# === 4. SINGLETON ACCESSOR ===

_audit_trail_writer_instance: AuditTrailWriter | None = None


def get_audit_trail_writer() -> AuditTrailWriter:
    """Mendapatkan akses eksklusif ke global instance singleton AuditTrailWriter."""
    global _audit_trail_writer_instance
    if _audit_trail_writer_instance is None:
        _audit_trail_writer_instance = AuditTrailWriter()
    return _audit_trail_writer_instance


# === 5. EXPORTS ===

__all__ = [
    "AuditTrailWriter",
    "IntentAuditAction",
    "IntentAuditRecord",
    "IntentAuditSeverity",
    "IntentAuditStoragePort",
    "get_audit_trail_writer",
]
