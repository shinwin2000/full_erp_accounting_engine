#!/usr/bin/env python3
"""
Module: hash_chain_service_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory hash chain service untuk tamper-proof audit trail.
               Mendukung multiple chain types (event store, audit log, journal batch, tax submission),
               cryptographic hashing (SHA3-256), digital signing (simulasi RSA-PSS),
               timestamp notary integration, chain verification, gap detection,
               export/import chain in JSON, integrity monitoring, dan alerting.
Audit: Setiap penambahan entri, verifikasi, dan operasi signing tercatat.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class ChainType(Enum):
    """Jenis hash chain yang didukung."""

    EVENT_STORE = "event_store"
    AUDIT_LOG = "audit_log"
    JOURNAL_BATCH = "journal_batch"
    TAX_SUBMISSION = "tax_submission"
    PERIOD_CLOSE = "period_close"
    CONSENT = "consent"


class ChainStatus(Enum):
    """Status integritas chain."""

    VALID = "valid"
    CORRUPTED = "corrupted"
    PARTIAL = "partial"
    NOT_VERIFIED = "not_verified"


class SignatureAlgorithm(Enum):
    """Algoritma digital signature."""

    RSA_PSS = "rsa_pss"
    ECDSA = "ecdsa"
    NONE = "none"


@dataclass
class HashChainEntry:
    """Entri dalam hash chain."""

    sequence: int
    prev_hash: str | None
    current_hash: str
    payload_hash: str
    payload_type: str  # "event", "audit", "journal", "tax", dll
    payload_ref_id: UUID | None  # ID dari objek asli (event_id, journal_id, dll)
    timestamp: datetime
    created_by: UUID
    signature: str | None = None
    signature_algorithm: SignatureAlgorithm = SignatureAlgorithm.NONE
    signer_cert_fingerprint: str | None = None
    timestamp_token: str | None = None  # dari timestamp notary
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "prev_hash": self.prev_hash,
            "current_hash": self.current_hash,
            "payload_hash": self.payload_hash,
            "payload_type": self.payload_type,
            "payload_ref_id": str(self.payload_ref_id) if self.payload_ref_id else None,
            "timestamp": self.timestamp.isoformat(),
            "created_by": str(self.created_by),
            "signature": self.signature,
            "signature_algorithm": self.signature_algorithm.value,
            "signer_cert_fingerprint": self.signer_cert_fingerprint,
            "timestamp_token": self.timestamp_token,
            "metadata": self.metadata,
        }


@dataclass
class IntegrityCheckResult:
    """Hasil verifikasi integritas chain."""

    chain_type: ChainType
    chain_id: UUID
    status: ChainStatus
    total_entries: int
    valid_entries: int
    invalid_entries: int
    first_invalid_sequence: int | None
    error_message: str | None
    checked_at: datetime
    duration_ms: int


class HashChainServicePort:
    """
    In-memory hash chain service dengan fitur enterprise.
    """

    def __init__(self):
        self._chains: dict[ChainType, dict[UUID, list[HashChainEntry]]] = {}
        self._hash_index: dict[
            str, tuple[ChainType, UUID, int]
        ] = {}  # current_hash -> (chain_type, chain_id, sequence)
        self._integrity_results: list[IntegrityCheckResult] = []
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._monitor_task: asyncio.Task | None = None
        self._monitoring = False

        # Inisialisasi dummy keys untuk signing (development)
        self._private_key_pem: str | None = None
        self._public_key_pem: str | None = None
        self._init_dummy_keys()

    # ==================== INISIALISASI ====================

    def _init_dummy_keys(self):
        """Generate dummy RSA key pair untuk development (simulasi)."""
        # Di production, gunakan HSM atau Vault. Untuk development, generate simulasi.
        self._private_key_pem = "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC...\n-----END PRIVATE KEY-----"
        self._public_key_pem = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----"
        logger.info("Hash chain service initialized with dummy keys for development")

    # ==================== AUDIT LOG ====================

    async def _log_audit(
        self,
        action: str,
        chain_type: ChainType,
        chain_id: UUID,
        user_id: UUID,
        details: dict[str, Any],
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "chain_type": chain_type.value,
            "chain_id": str(chain_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"HASH CHAIN AUDIT: {action} on {chain_type.value}/{chain_id} by {user_id}")

    # ==================== HASH COMPUTATION ====================

    @staticmethod
    async def compute_hash(data: dict[str, Any], prev_hash: str | None = None) -> str:
        """
        Menghitung hash SHA3-256 dari data dictionary + prev_hash.
        Menggunakan JSON serialization dengan sort_keys=True untuk konsistensi.
        """
        json_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
        if prev_hash:
            combined = prev_hash + json_str
        else:
            combined = json_str
        return hashlib.sha3_256(combined.encode("utf-8")).hexdigest()

    @staticmethod
    async def compute_payload_hash(payload: dict[str, Any]) -> str:
        """Hash dari payload data (tanpa prev_hash)."""
        return hashlib.sha3_256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    # ==================== DIGITAL SIGNATURE ====================

    async def sign_hash(self, hash_value: str, key_id: str | None = None) -> str:
        """
        Menandatangani hash dengan private key (simulasi RSA-PSS).
        Di production, gunakan HSM atau key vault.
        """
        # Simulasi: signature = "sig:" + hash_value[:16] + ":" + secrets.token_hex(32)
        signature = f"sig:{hash_value[:16]}:{secrets.token_hex(32)}"
        return signature

    async def verify_signature(
        self, hash_value: str, signature: str, cert_fingerprint: str | None = None
    ) -> bool:
        """Verifikasi signature (simulasi)."""
        # Simulasi: signature must start with "sig:" and contain hash prefix
        if not signature.startswith("sig:"):
            return False
        parts = signature.split(":")
        if len(parts) < 3:
            return False
        expected_prefix = hash_value[:16]
        return parts[1] == expected_prefix

    # ==================== APPEND TO CHAIN ====================

    async def append(
        self,
        chain_type: ChainType,
        chain_id: UUID,
        payload: dict[str, Any],
        payload_type: str,
        payload_ref_id: UUID | None,
        created_by: UUID,
        metadata: dict[str, Any] | None = None,
        sign: bool = True,
        timestamp_token: str | None = None,
    ) -> HashChainEntry:
        """
        Menambahkan entri baru ke hash chain.
        Menghitung payload_hash, lalu current_hash dari prev_hash + payload_hash.
        Opsional: sign dan attach timestamp token.
        """
        # Inisialisasi chain storage jika belum ada
        if chain_type not in self._chains:
            self._chains[chain_type] = {}
        if chain_id not in self._chains[chain_type]:
            self._chains[chain_type][chain_id] = []

        chain = self._chains[chain_type][chain_id]
        sequence = len(chain) + 1
        prev_hash = chain[-1].current_hash if chain else None

        # Hitung hash payload
        payload_hash = await self.compute_payload_hash(payload)

        # Hitung current hash
        current_hash = await self.compute_hash({"payload_hash": payload_hash}, prev_hash)

        # Tanda tangan
        signature = None
        sig_alg = SignatureAlgorithm.NONE
        cert_fp = None
        if sign:
            signature = await self.sign_hash(current_hash)
            sig_alg = SignatureAlgorithm.RSA_PSS
            cert_fp = "dev_cert_fingerprint_dummy"

        entry = HashChainEntry(
            sequence=sequence,
            prev_hash=prev_hash,
            current_hash=current_hash,
            payload_hash=payload_hash,
            payload_type=payload_type,
            payload_ref_id=payload_ref_id,
            timestamp=datetime.now(UTC),
            created_by=created_by,
            signature=signature,
            signature_algorithm=sig_alg,
            signer_cert_fingerprint=cert_fp,
            timestamp_token=timestamp_token,
            metadata=metadata or {},
        )
        async with self._lock:
            chain.append(entry)
            self._hash_index[current_hash] = (chain_type, chain_id, sequence)

        await self._log_audit(
            "APPEND",
            chain_type,
            chain_id,
            created_by,
            {
                "sequence": sequence,
                "payload_type": payload_type,
                "payload_hash": payload_hash[:16],
                "current_hash": current_hash[:16],
                "signed": sign,
            },
        )
        return entry

    # ==================== VERIFY CHAIN INTEGRITY ====================

    async def verify_chain(
        self,
        chain_type: ChainType,
        chain_id: UUID,
        deep_verify: bool = True,
        check_signatures: bool = True,
    ) -> IntegrityCheckResult:
        """
        Memverifikasi integritas seluruh rantai.
        - Memeriksa konsistensi hash berantai.
        - Opsional memeriksa signature digital.
        - Mendeteksi gap atau korupsi.
        """
        start_time = time.perf_counter()
        chain = self._chains.get(chain_type, {}).get(chain_id, [])
        if not chain:
            return IntegrityCheckResult(
                chain_type=chain_type,
                chain_id=chain_id,
                status=ChainStatus.CORRUPTED,
                total_entries=0,
                valid_entries=0,
                invalid_entries=0,
                first_invalid_sequence=None,
                error_message="Chain not found",
                checked_at=datetime.now(UTC),
                duration_ms=0,
            )

        prev_hash_calc = None
        invalid_sequences = []
        for idx, entry in enumerate(chain):
            # Verify hash chain
            combined = {"payload_hash": entry.payload_hash}
            expected_hash = await self.compute_hash(combined, prev_hash_calc)
            if expected_hash != entry.current_hash:
                invalid_sequences.append(entry.sequence)
                continue

            # Verify signature jika diminta
            if (
                check_signatures
                and entry.signature
                and entry.signature_algorithm != SignatureAlgorithm.NONE
            ):
                sig_valid = await self.verify_signature(
                    entry.current_hash, entry.signature, entry.signer_cert_fingerprint
                )
                if not sig_valid:
                    invalid_sequences.append(entry.sequence)
                    continue

            prev_hash_calc = entry.current_hash

        valid_entries = len(chain) - len(invalid_sequences)
        status = (
            ChainStatus.VALID
            if not invalid_sequences
            else (ChainStatus.PARTIAL if valid_entries > 0 else ChainStatus.CORRUPTED)
        )
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        result = IntegrityCheckResult(
            chain_type=chain_type,
            chain_id=chain_id,
            status=status,
            total_entries=len(chain),
            valid_entries=valid_entries,
            invalid_entries=len(invalid_sequences),
            first_invalid_sequence=invalid_sequences[0] if invalid_sequences else None,
            error_message=None
            if valid_entries == len(chain)
            else f"Invalid at sequences: {invalid_sequences[:5]}",
            checked_at=datetime.now(UTC),
            duration_ms=duration_ms,
        )
        self._integrity_results.append(result)

        await self._log_audit(
            "VERIFY",
            chain_type,
            chain_id,
            UUID(int=0),
            {
                "status": status.value,
                "valid": valid_entries,
                "invalid": len(invalid_sequences),
                "duration_ms": duration_ms,
            },
        )
        return result

    async def verify_all_chains(
        self, check_signatures: bool = True
    ) -> dict[ChainType, dict[UUID, IntegrityCheckResult]]:
        """Verifikasi semua chain yang ada."""
        results = {}
        for chain_type, chains in self._chains.items():
            results[chain_type] = {}
            for chain_id in chains.keys():
                results[chain_type][chain_id] = await self.verify_chain(
                    chain_type, chain_id, check_signatures=check_signatures
                )
        return results

    # ==================== GETTERS ====================

    async def get_last_hash(self, chain_type: ChainType, chain_id: UUID) -> str | None:
        chain = self._chains.get(chain_type, {}).get(chain_id, [])
        if not chain:
            return None
        return chain[-1].current_hash

    async def get_chain_entries(
        self,
        chain_type: ChainType,
        chain_id: UUID,
        limit: int = 1000,
        offset: int = 0,
        include_payload: bool = False,
    ) -> list[HashChainEntry]:
        chain = self._chains.get(chain_type, {}).get(chain_id, [])
        if not chain:
            return []
        # offset dari awal, atau bisa juga dari akhir? Default dari awal.
        return chain[offset : offset + limit]

    async def get_chain_length(self, chain_type: ChainType, chain_id: UUID) -> int:
        return len(self._chains.get(chain_type, {}).get(chain_id, []))

    async def get_entry_by_hash(self, current_hash: str) -> HashChainEntry | None:
        info = self._hash_index.get(current_hash)
        if not info:
            return None
        chain_type, chain_id, sequence = info
        chain = self._chains.get(chain_type, {}).get(chain_id, [])
        if sequence <= len(chain):
            return chain[sequence - 1]
        return None

    async def get_entry_by_sequence(
        self, chain_type: ChainType, chain_id: UUID, sequence: int
    ) -> HashChainEntry | None:
        chain = self._chains.get(chain_type, {}).get(chain_id, [])
        if 1 <= sequence <= len(chain):
            return chain[sequence - 1]
        return None

    # ==================== GAP DETECTION ====================

    async def detect_gaps(self, chain_type: ChainType, chain_id: UUID) -> list[int]:
        """
        Mendeteksi missing sequences dalam chain (jika ada gap karena kegagalan penyimpanan).
        """
        chain = self._chains.get(chain_type, {}).get(chain_id, [])
        if not chain:
            return []
        max_seq = chain[-1].sequence
        existing_seqs = {e.sequence for e in chain}
        missing = [seq for seq in range(1, max_seq + 1) if seq not in existing_seqs]
        return missing

    async def repair_gap(
        self,
        chain_type: ChainType,
        chain_id: UUID,
        missing_sequence: int,
        payload: dict[str, Any],
        payload_type: str,
        payload_ref_id: UUID | None,
        created_by: UUID,
        metadata: dict[str, Any] | None = None,
    ) -> HashChainEntry | None:
        """
        Mengisi gap pada sequence tertentu (hanya jika belum ada). Hati-hati: ini bisa merusak chain.
        Gunakan hanya untuk recovery yang terkontrol.
        """
        chain = self._chains.get(chain_type, {}).get(chain_id, [])
        existing = [e for e in chain if e.sequence == missing_sequence]
        if existing:
            logger.warning(
                f"Sequence {missing_sequence} already exists in chain {chain_type}/{chain_id}"
            )
            return None
        # Cari prev_hash dari entry sebelumnya
        prev_entry = None
        for e in chain:
            if e.sequence == missing_sequence - 1:
                prev_entry = e
                break
        prev_hash = prev_entry.current_hash if prev_entry else None
        payload_hash = await self.compute_payload_hash(payload)
        current_hash = await self.compute_hash({"payload_hash": payload_hash}, prev_hash)
        new_entry = HashChainEntry(
            sequence=missing_sequence,
            prev_hash=prev_hash,
            current_hash=current_hash,
            payload_hash=payload_hash,
            payload_type=payload_type,
            payload_ref_id=payload_ref_id,
            timestamp=datetime.now(UTC),
            created_by=created_by,
            signature=None,
            signature_algorithm=SignatureAlgorithm.NONE,
            metadata=metadata or {},
        )
        async with self._lock:
            # Masukkan ke posisi yang benar (urut berdasarkan sequence)
            chain.append(new_entry)
            chain.sort(key=lambda x: x.sequence)
            self._hash_index[current_hash] = (chain_type, chain_id, missing_sequence)
        await self._log_audit(
            "REPAIR_GAP", chain_type, chain_id, created_by, {"sequence": missing_sequence}
        )
        return new_entry

    # ==================== INTEGRITY MONITORING ====================

    async def start_monitoring(
        self, interval_seconds: int = 3600, alert_callback: callable | None = None
    ):
        """Mulai background task untuk verifikasi periodik semua chain."""
        if self._monitoring:
            logger.warning("Monitoring already running")
            return
        self._monitoring = True

        async def _monitor_loop():
            while self._monitoring:
                await asyncio.sleep(interval_seconds)
                try:
                    results = await self.verify_all_chains(check_signatures=False)
                    for chain_type, chains in results.items():
                        for chain_id, result in chains.items():
                            if result.status != ChainStatus.VALID:
                                logger.warning(
                                    f"Chain {chain_type.value}/{chain_id} is {result.status.value}"
                                )
                                if alert_callback:
                                    await alert_callback(result)
                except Exception as e:
                    logger.error(f"Monitoring error: {e}")

        self._monitor_task = asyncio.create_task(_monitor_loop())
        logger.info(f"Hash chain monitoring started with interval {interval_seconds}s")

    async def stop_monitoring(self):
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        logger.info("Hash chain monitoring stopped")

    # ==================== EXPORT/IMPORT ====================

    async def export_chain(
        self, chain_type: ChainType, chain_id: UUID, include_payload: bool = False
    ) -> str:
        """Ekspor seluruh chain ke format JSON (untuk backup/audit)."""
        chain = self._chains.get(chain_type, {}).get(chain_id, [])
        data = {
            "chain_type": chain_type.value,
            "chain_id": str(chain_id),
            "exported_at": datetime.now(UTC).isoformat(),
            "entries": [e.to_dict() for e in chain],
        }
        if include_payload:
            # Payload tidak disimpan di HashChainEntry, perlu diambil dari sumber lain.
            # Untuk export sederhana, kita hanya export metadata.
            pass
        return json.dumps(data, indent=2)

    async def import_chain(
        self, chain_json: str, overwrite: bool = False
    ) -> tuple[ChainType, UUID]:
        """Impor chain dari JSON. Hati-hati: bisa merusak integritas jika tidak divalidasi."""
        data = json.loads(chain_json)
        chain_type = ChainType(data["chain_type"])
        chain_id = UUID(data["chain_id"])
        imported_entries = []
        for entry_data in data["entries"]:
            entry = HashChainEntry(
                sequence=entry_data["sequence"],
                prev_hash=entry_data["prev_hash"],
                current_hash=entry_data["current_hash"],
                payload_hash=entry_data["payload_hash"],
                payload_type=entry_data["payload_type"],
                payload_ref_id=UUID(entry_data["payload_ref_id"])
                if entry_data["payload_ref_id"]
                else None,
                timestamp=datetime.fromisoformat(entry_data["timestamp"]),
                created_by=UUID(entry_data["created_by"]),
                signature=entry_data["signature"],
                signature_algorithm=SignatureAlgorithm(entry_data["signature_algorithm"]),
                signer_cert_fingerprint=entry_data["signer_cert_fingerprint"],
                timestamp_token=entry_data["timestamp_token"],
                metadata=entry_data.get("metadata", {}),
            )
            imported_entries.append(entry)
        async with self._lock:
            if chain_type not in self._chains:
                self._chains[chain_type] = {}
            if chain_id in self._chains[chain_type] and not overwrite:
                raise ValueError(f"Chain {chain_type.value}/{chain_id} already exists")
            self._chains[chain_type][chain_id] = imported_entries
            # Rebuild hash index
            for entry in imported_entries:
                self._hash_index[entry.current_hash] = (chain_type, chain_id, entry.sequence)
        await self._log_audit(
            "IMPORT", chain_type, chain_id, UUID(int=0), {"entries": len(imported_entries)}
        )
        return chain_type, chain_id

    # ==================== STATISTICS & HEALTH ====================

    async def get_statistics(self) -> dict[str, Any]:
        total_chains = sum(len(chains) for chains in self._chains.values())
        total_entries = sum(
            len(entry) for chains in self._chains.values() for entry in chains.values()
        )
        total_verified = len(self._integrity_results)
        valid_chains = sum(1 for res in self._integrity_results if res.status == ChainStatus.VALID)
        return {
            "total_chains": total_chains,
            "total_entries": total_entries,
            "total_verifications": total_verified,
            "valid_chains": valid_chains,
            "corrupted_chains": total_chains - valid_chains,
            "by_type": {ct.value: len(chains) for ct, chains in self._chains.items()},
            "audit_log_size": len(self._audit_log),
            "monitoring_active": self._monitoring,
        }

    async def get_integrity_history(self, limit: int = 50) -> list[IntegrityCheckResult]:
        return self._integrity_results[-limit:]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_chains": sum(len(chains) for chains in self._chains.values()),
            "total_entries": sum(
                len(entry) for chains in self._chains.values() for entry in chains.values()
            ),
            "hash_index_size": len(self._hash_index),
            "monitoring_running": self._monitoring,
            "audit_log_size": len(self._audit_log),
        }

    # ==================== MERKLE TREE (optional extension) ====================

    async def build_merkle_root(self, chain_type: ChainType, chain_id: UUID) -> str | None:
        """Bangun Merkle root dari seluruh hash di chain (untuk verifikasi cepat)."""
        chain = self._chains.get(chain_type, {}).get(chain_id, [])
        if not chain:
            return None
        hashes = [entry.current_hash for entry in chain]
        while len(hashes) > 1:
            if len(hashes) % 2 == 1:
                hashes.append(hashes[-1])
            new_hashes = []
            for i in range(0, len(hashes), 2):
                combined = hashes[i] + hashes[i + 1]
                new_hashes.append(hashlib.sha3_256(combined.encode()).hexdigest())
            hashes = new_hashes
        return hashes[0]

    # ==================== TIMESTAMP INTEGRATION ====================

    async def attach_timestamp_token(
        self,
        chain_type: ChainType,
        chain_id: UUID,
        sequence: int,
        timestamp_token: str,
        user_id: UUID,
    ) -> bool:
        """Attach timestamp token dari notary ke entry tertentu."""
        chain = self._chains.get(chain_type, {}).get(chain_id, [])
        if sequence > len(chain):
            return False
        entry = chain[sequence - 1]
        entry.timestamp_token = timestamp_token
        entry.metadata["timestamp_attached_at"] = datetime.now(UTC).isoformat()
        entry.metadata["timestamp_attached_by"] = str(user_id)
        await self._log_audit(
            "ATTACH_TIMESTAMP", chain_type, chain_id, user_id, {"sequence": sequence}
        )
        return True
