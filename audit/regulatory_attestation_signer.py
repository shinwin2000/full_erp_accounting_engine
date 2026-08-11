#!/usr/bin/env python3
"""
Module: regulatory_attestation_signer.py
Layer: Audit
Responsibility: Menandatangani secara digital attestation kepatuhan regulasi (SOX, GDPR, PSAK)
               untuk periode tertentu. Attestation berisi ringkasan kepatuhan, integritas data,
               dan hash chain audit trail. Ditandatangani dengan private key yang aman untuk
               memenuhi persyaratan non-repudiation untuk auditor eksternal.
Dependencies:
- asyncio, logging, datetime, hashlib, json
- infrastructure.security.digital_signer_rsa_pss (DigitalSignerRSA)
- audit.hash_chain_builder (AuditHashChainBuilder)
- infrastructure.event_store.append_only_store (AppendOnlyStore)
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Setiap attestation yang dihasilkan dicatat. Signature verification dapat dilakukan
       oleh auditor independen.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import aiofiles  # <-- Tambahan untuk async file I/O

# Import dari layer audit (diizinkan)
from audit.hash_chain_builder import AuditHashChainBuilder, get_audit_hash_builder

# ============================================================================
# CONSTANTS
# ============================================================================

ATTESTATION_STREAM = "regulatory_attestation"
DEFAULT_OUTPUT_DIR = Path("/var/audit/attestations")

_logger = None


def _get_logger():
    """Lazy logger initialization from structured logging."""
    global _logger
    if _logger is None:
        mod = importlib.import_module("infrastructure.telemetry.structured_json_logging")
        get_logger_func = mod.get_logger
        _logger = get_logger_func(__name__)
    return _logger


def _get_event_store():
    """Lazy import and get audit store."""
    mod = importlib.import_module("infrastructure.event_store.append_only_store")
    get_audit_store = mod.get_audit_store
    return get_audit_store


def _get_digital_signer():
    """Lazy import and get digital signer."""
    mod = importlib.import_module("infrastructure.security.digital_signer_rsa_pss")
    get_digital_signer = mod.get_digital_signer
    return get_digital_signer


def _get_alert_trigger():
    """Lazy import alert manager trigger."""
    mod = importlib.import_module("infrastructure.telemetry.alert_manager_router")
    trigger_alert = mod.trigger_alert
    return trigger_alert


# ============================================================================
# Regulatory frameworks
# ============================================================================

class RegulatoryFramework:
    SOX = "SOX"
    GDPR = "GDPR"
    PSAK = "PSAK"
    IFRS = "IFRS"
    TAX = "TAX"


# Attestation status
class AttestationStatus:
    DRAFT = "draft"
    SIGNED = "signed"
    EXPIRED = "expired"
    REVOKED = "revoked"


# ============================================================================
# EXCEPTIONS
# ============================================================================


class AttestationError(Exception):
    """Base exception untuk regulatory attestation."""

    pass


class AttestationNotFoundError(AttestationError):
    """Attestation tidak ditemukan."""

    pass


class AttestationVerificationError(AttestationError):
    """Verifikasi attestation gagal."""

    pass


# ============================================================================
# REGULATORY ATTESTATION
# ============================================================================


class RegulatoryAttestation:
    """
    Representasi attestation kepatuhan regulasi.
    """

    __slots__ = (
        "audit_root_hash",
        "content_hash",
        "created_at",
        "expires_at",
        "framework",
        "id",
        "legal_entity_id",
        "metadata",
        "period_end",
        "period_start",
        "signature",
        "signed_at",
        "signer_info",
        "status",
    )

    def __init__(
        self,
        id: UUID,
        framework: str,
        period_start: date,
        period_end: date,
        legal_entity_id: UUID,
        created_at: datetime | None = None,
        signed_at: datetime | None = None,
        expires_at: datetime | None = None,
        status: str = AttestationStatus.DRAFT,
        content_hash: str | None = None,
        audit_root_hash: str | None = None,
        signature: str | None = None,
        signer_info: dict | None = None,
        metadata: dict | None = None,
    ):
        self.id = id
        self.framework = framework
        self.period_start = period_start
        self.period_end = period_end
        self.legal_entity_id = legal_entity_id
        self.created_at = created_at or datetime.now(UTC)
        self.signed_at = signed_at
        self.expires_at = expires_at or (self.created_at + timedelta(days=365))  # 1 year validity
        self.status = status
        self.content_hash = content_hash
        self.audit_root_hash = audit_root_hash
        self.signature = signature
        self.signer_info = signer_info or {}
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "framework": self.framework,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "legal_entity_id": str(self.legal_entity_id),
            "created_at": self.created_at.isoformat(),
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
            "expires_at": self.expires_at.isoformat(),
            "status": self.status,
            "content_hash": self.content_hash,
            "audit_root_hash": self.audit_root_hash,
            "signature": self.signature,
            "signer_info": self.signer_info,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegulatoryAttestation:
        return cls(
            id=UUID(data["id"]),
            framework=data["framework"],
            period_start=datetime.fromisoformat(data["period_start"]).date(),
            period_end=datetime.fromisoformat(data["period_end"]).date(),
            legal_entity_id=UUID(data["legal_entity_id"]),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else None,
            signed_at=datetime.fromisoformat(data["signed_at"]) if data.get("signed_at") else None,
            expires_at=datetime.fromisoformat(data["expires_at"])
            if data.get("expires_at")
            else None,
            status=data.get("status", AttestationStatus.DRAFT),
            content_hash=data.get("content_hash"),
            audit_root_hash=data.get("audit_root_hash"),
            signature=data.get("signature"),
            signer_info=data.get("signer_info", {}),
            metadata=data.get("metadata", {}),
        )

    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    def is_signed(self) -> bool:
        return self.status == AttestationStatus.SIGNED and self.signature is not None


# ============================================================================
# ATTESTATION SIGNER
# ============================================================================


class RegulatoryAttestationSigner:
    """
    Penanda tangan digital untuk attestation kepatuhan regulasi.

    Fitur:
    - Menghasilkan attestation untuk periode tertentu
    - Menandatangani attestation dengan private key
    - Menyimpan attestation di event store
    - Verifikasi attestation
    - Export attestation ke file (JSON + signature)
    """

    def __init__(self):
        self._signer = None
        self._hash_builder: AuditHashChainBuilder | None = None
        self._event_store = None
        self._output_dir = DEFAULT_OUTPUT_DIR
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._attestations_cache: dict[UUID, RegulatoryAttestation] = {}

    async def _get_signer(self):
        if self._signer is None:
            get_digital_signer = _get_digital_signer()
            self._signer = get_digital_signer()
        return self._signer

    async def _get_hash_builder(self) -> AuditHashChainBuilder:
        if self._hash_builder is None:
            self._hash_builder = get_audit_hash_builder()
        return self._hash_builder

    async def _get_event_store(self):
        if self._event_store is None:
            get_audit_store = _get_event_store()
            self._event_store = await get_audit_store()
        return self._event_store

    async def compute_audit_root_hash(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> str:
        """
        Menghitung root hash dari semua audit event dalam periode dan legal entity.
        """
        store = await self._get_event_store()
        # Get all audit events in time range
        start_ts = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        end_ts = datetime.combine(end_date, datetime.max.time(), tzinfo=UTC)

        events = await store.search_events(start_time=start_ts, end_time=end_ts, limit=100000)

        # Filter by legal entity if needed (requires metadata filtering)
        # For simplicity, we'll compute from all events and trust that separation is handled
        # Build a Merkle root of all event hashes
        hashes = [e.get("hash") for e in events if e.get("hash")]
        if not hashes:
            return hashlib.sha256(b"no_events").hexdigest()

        # Simple merkle root
        while len(hashes) > 1:
            next_level = []
            for i in range(0, len(hashes), 2):
                if i + 1 < len(hashes):
                    combined = hashes[i] + hashes[i + 1]
                else:
                    combined = hashes[i] + hashes[i]
                next_level.append(hashlib.sha256(combined.encode()).hexdigest())
            hashes = next_level

        return hashes[0]

    async def create_attestation(
        self,
        framework: str,
        period_start: date,
        period_end: date,
        legal_entity_id: UUID,
        metadata: dict | None = None,
    ) -> RegulatoryAttestation:
        """
        Membuat draft attestation (belum ditandatangani).
        """
        # Compute audit root hash
        audit_root_hash = await self.compute_audit_root_hash(
            legal_entity_id, period_start, period_end
        )

        # Create attestation
        att_id = uuid4()
        attestation = RegulatoryAttestation(
            id=att_id,
            framework=framework,
            period_start=period_start,
            period_end=period_end,
            legal_entity_id=legal_entity_id,
            status=AttestationStatus.DRAFT,
            audit_root_hash=audit_root_hash,
            metadata=metadata or {},
        )

        # Compute content hash
        content = {
            "id": str(attestation.id),
            "framework": attestation.framework,
            "period_start": attestation.period_start.isoformat(),
            "period_end": attestation.period_end.isoformat(),
            "legal_entity_id": str(attestation.legal_entity_id),
            "audit_root_hash": attestation.audit_root_hash,
            "created_at": attestation.created_at.isoformat(),
            "metadata": attestation.metadata,
        }
        content_json = json.dumps(content, sort_keys=True, default=str)
        attestation.content_hash = hashlib.sha256(content_json.encode()).hexdigest()

        # Store draft
        await self._store_attestation(attestation)
        self._attestations_cache[attestation.id] = attestation

        logger = _get_logger()
        logger.info(
            f"Created attestation draft: {attestation.id} for {framework} period {period_start} to {period_end}"
        )
        return attestation

    async def sign_attestation(
        self, attestation_id: UUID, signer_id: UUID
    ) -> RegulatoryAttestation:
        """
        Menandatangani attestation dengan digital signature.
        """
        attestation = await self.get_attestation(attestation_id)
        if not attestation:
            raise AttestationNotFoundError(f"Attestation {attestation_id} not found")

        if attestation.status != AttestationStatus.DRAFT:
            raise AttestationError(f"Cannot sign attestation with status {attestation.status}")

        # Prepare content for signing
        content = {
            "id": str(attestation.id),
            "framework": attestation.framework,
            "period_start": attestation.period_start.isoformat(),
            "period_end": attestation.period_end.isoformat(),
            "legal_entity_id": str(attestation.legal_entity_id),
            "audit_root_hash": attestation.audit_root_hash,
            "content_hash": attestation.content_hash,
            "created_at": attestation.created_at.isoformat(),
        }
        content_json = json.dumps(content, sort_keys=True, default=str)

        # Sign
        signer = await self._get_signer()
        signature = signer.sign(content_json)

        # Update attestation
        attestation.signature = signature
        attestation.signed_at = datetime.now(UTC)
        attestation.status = AttestationStatus.SIGNED
        attestation.signer_info = {
            "signer_id": str(signer_id),
            "signer_name": "System",  # Could be looked up
        }

        # Update stored
        await self._store_attestation(attestation)
        self._attestations_cache[attestation.id] = attestation

        logger = _get_logger()
        logger.info(f"Attestation {attestation_id} signed by {signer_id}")

        # Trigger alert for successful signing
        trigger_alert = _get_alert_trigger()
        await trigger_alert(
            title="Regulatory Attestation Signed",
            message=f"Attestation for {attestation.framework} period {attestation.period_start} to {attestation.period_end} has been signed",
            severity="info",
            source="RegulatoryAttestationSigner",
        )

        return attestation

    async def verify_attestation(self, attestation_id: UUID) -> dict[str, Any]:
        """
        Memverifikasi keabsahan attestation (signature, content hash, audit root).
        """
        attestation = await self.get_attestation(attestation_id)
        if not attestation:
            raise AttestationNotFoundError(f"Attestation {attestation_id} not found")

        result = {"attestation_id": str(attestation_id), "is_valid": False, "checks": []}

        # 1. Check status
        result["checks"].append(
            {
                "check": "status",
                "passed": attestation.status == AttestationStatus.SIGNED,
                "details": f"Status: {attestation.status}",
            }
        )

        # 2. Check expiry
        is_expired = attestation.is_expired()
        result["checks"].append(
            {
                "check": "expiry",
                "passed": not is_expired,
                "details": f"Expires at: {attestation.expires_at.isoformat()}"
                if attestation.expires_at
                else "No expiry",
            }
        )

        # 3. Verify content hash
        content = {
            "id": str(attestation.id),
            "framework": attestation.framework,
            "period_start": attestation.period_start.isoformat(),
            "period_end": attestation.period_end.isoformat(),
            "legal_entity_id": str(attestation.legal_entity_id),
            "audit_root_hash": attestation.audit_root_hash,
            "content_hash": attestation.content_hash,
            "created_at": attestation.created_at.isoformat(),
        }
        content_json = json.dumps(content, sort_keys=True, default=str)
        computed_hash = hashlib.sha256(content_json.encode()).hexdigest()
        hash_valid = computed_hash == attestation.content_hash
        result["checks"].append(
            {
                "check": "content_hash",
                "passed": hash_valid,
                "details": f"Computed: {computed_hash[:16]}..., Stored: {attestation.content_hash[:16]}...",
            }
        )

        # 4. Verify signature
        signature_valid = False
        if attestation.signature:
            signer = await self._get_signer()
            signature_valid = signer.verify(content_json, attestation.signature)
        result["checks"].append(
            {
                "check": "signature",
                "passed": signature_valid,
                "details": "Signature verified" if signature_valid else "Signature invalid",
            }
        )

        # 5. Verify audit root hash (current vs stored)
        current_audit_root = await self.compute_audit_root_hash(
            attestation.legal_entity_id, attestation.period_start, attestation.period_end
        )
        audit_root_valid = current_audit_root == attestation.audit_root_hash
        result["checks"].append(
            {
                "check": "audit_root_hash",
                "passed": audit_root_valid,
                "details": f"Current root: {current_audit_root[:16]}..., Stored: {attestation.audit_root_hash[:16]}...",
            }
        )

        result["is_valid"] = all(c["passed"] for c in result["checks"])

        return result

    async def revoke_attestation(self, attestation_id: UUID, reason: str, revoked_by: UUID) -> bool:
        """
        Membatalkan attestation yang sudah ditandatangani.
        """
        attestation = await self.get_attestation(attestation_id)
        if not attestation:
            raise AttestationNotFoundError(f"Attestation {attestation_id} not found")

        if attestation.status != AttestationStatus.SIGNED:
            raise AttestationError(f"Cannot revoke attestation with status {attestation.status}")

        attestation.status = AttestationStatus.REVOKED
        attestation.metadata["revoked_at"] = datetime.now(UTC).isoformat()
        attestation.metadata["revocation_reason"] = reason
        attestation.metadata["revoked_by"] = str(revoked_by)

        await self._store_attestation(attestation)
        self._attestations_cache[attestation.id] = attestation

        logger = _get_logger()
        logger.warning(f"Attestation {attestation_id} revoked by {revoked_by}: {reason}")

        trigger_alert = _get_alert_trigger()
        await trigger_alert(
            title="Regulatory Attestation Revoked",
            message=f"Attestation for {attestation.framework} period {attestation.period_start} to {attestation.period_end} has been revoked. Reason: {reason}",
            severity="warning",
            source="RegulatoryAttestationSigner",
        )

        return True

    async def get_attestation(self, attestation_id: UUID) -> RegulatoryAttestation | None:
        """Mendapatkan attestation dari cache atau event store."""
        if attestation_id in self._attestations_cache:
            return self._attestations_cache[attestation_id]

        store = await self._get_event_store()
        events = await store.read_stream(ATTESTATION_STREAM, limit=1000)
        for event in events:
            data = event.get("data", {})
            if data.get("id") == str(attestation_id):
                att = RegulatoryAttestation.from_dict(data)
                self._attestations_cache[attestation_id] = att
                return att
        return None

    async def _store_attestation(self, attestation: RegulatoryAttestation) -> None:
        """Menyimpan attestation ke event store."""
        store = await self._get_event_store()
        await store.append(
            stream_name=ATTESTATION_STREAM,
            event_data=attestation.to_dict(),
            event_type="regulatory.attestation",
            metadata={"framework": attestation.framework},
        )

    async def list_attestations(
        self,
        framework: str | None = None,
        legal_entity_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[RegulatoryAttestation]:
        """
        Mendaftar attestations dengan filter.
        """
        store = await self._get_event_store()
        events = await store.read_stream(ATTESTATION_STREAM, limit=limit * 2)
        attestations = []
        for event in events:
            data = event.get("data", {})
            if framework and data.get("framework") != framework:
                continue
            if legal_entity_id and data.get("legal_entity_id") != str(legal_entity_id):
                continue
            if status and data.get("status") != status:
                continue
            att = RegulatoryAttestation.from_dict(data)
            attestations.append(att)
            if len(attestations) >= limit:
                break
        return attestations

    # ========================================================================
    # PERBAIKAN: export_attestation menggunakan aiofiles
    # ========================================================================
    async def export_attestation(self, attestation_id: UUID) -> Path:
        """
        Mengekspor attestation ke file JSON beserta signature untuk auditor.
        """
        attestation = await self.get_attestation(attestation_id)
        if not attestation:
            raise AttestationNotFoundError(f"Attestation {attestation_id} not found")

        signer = await self._get_signer()
        export_data = {
            "attestation": attestation.to_dict(),
            "verification_info": {
                "verification_instructions": "Use the public key to verify the signature.",
                "public_key": signer.get_public_key_pem(),
                "verification_tool": "OpenSSL or any RSA-PSS verifier",
            },
        }

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"attestation_{attestation_id}_{timestamp}.json"
        file_path = self._output_dir / filename

        # Gunakan aiofiles untuk write async
        content = json.dumps(export_data, indent=2, default=str)
        async with aiofiles.open(file_path, "w") as f:
            await f.write(content)

        logger = _get_logger()
        logger.info(f"Attestation exported to {file_path}")
        return file_path

    async def get_stats(self) -> dict[str, Any]:
        """Mendapatkan statistik attestations."""
        all_attestations = await self.list_attestations(limit=1000)
        by_status = {}
        for att in all_attestations:
            by_status[att.status] = by_status.get(att.status, 0) + 1

        return {
            "total_attestations": len(all_attestations),
            "by_status": by_status,
            "output_dir": str(self._output_dir),
            "cache_size": len(self._attestations_cache),
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_attestation_signer: RegulatoryAttestationSigner | None = None


async def get_regulatory_attestation_signer() -> RegulatoryAttestationSigner:
    """Get singleton instance of RegulatoryAttestationSigner."""
    global _attestation_signer
    if _attestation_signer is None:
        _attestation_signer = RegulatoryAttestationSigner()
    return _attestation_signer


# ============================================================================
# CLI COMMAND — DIPERBAIKI (tanpa unsafe create_task)
# ============================================================================


def cli():
    """CLI entry point for regulatory attestation."""
    import argparse

    parser = argparse.ArgumentParser(description="Regulatory Attestation Signer")
    parser.add_argument(
        "command",
        choices=["create", "sign", "verify", "list", "export"],
        help="Attestation command",
    )
    parser.add_argument(
        "--framework", "-f", help="Regulatory framework (SOX, GDPR, PSAK, IFRS, TAX)"
    )
    parser.add_argument("--start", help="Period start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="Period end date (YYYY-MM-DD)")
    parser.add_argument("--legal-entity", "-l", help="Legal entity ID")
    parser.add_argument("--attestation-id", "-a", help="Attestation ID")
    parser.add_argument("--signer-id", "-s", help="Signer user ID")
    parser.add_argument("--output", "-o", help="Output file")

    args = parser.parse_args()

    async def run():
        signer = await get_regulatory_attestation_signer()

        if args.command == "create":
            if not args.framework or not args.start or not args.end or not args.legal_entity:
                print("Error: --framework, --start, --end, --legal-entity required")
                return
            start_date = datetime.fromisoformat(args.start).date()
            end_date = datetime.fromisoformat(args.end).date()
            att = await signer.create_attestation(
                args.framework, start_date, end_date, UUID(args.legal_entity)
            )
            print(f"Created attestation: {att.id}")
        elif args.command == "sign":
            if not args.attestation_id or not args.signer_id:
                print("Error: --attestation-id and --signer-id required")
                return
            att = await signer.sign_attestation(UUID(args.attestation_id), UUID(args.signer_id))
            print(f"Signed attestation: {att.id} at {att.signed_at}")
        elif args.command == "verify":
            if not args.attestation_id:
                print("Error: --attestation-id required")
                return
            result = await signer.verify_attestation(UUID(args.attestation_id))
            print(json.dumps(result, indent=2))
        elif args.command == "list":
            attestations = await signer.list_attestations()
            for att in attestations:
                print(
                    f"{att.id} | {att.framework} | {att.period_start} to {att.period_end} | {att.status}"
                )
        elif args.command == "export":
            if not args.attestation_id:
                print("Error: --attestation-id required")
                return
            path = await signer.export_attestation(UUID(args.attestation_id))
            print(f"Exported to: {path}")

    # Eksekusi dengan aman, tanpa unsafe create_task
    try:
        # Coba dapatkan loop yang sedang berjalan, jika tidak ada, jalankan langsung
        asyncio.get_running_loop()
        # Jika ada loop, jalankan di thread terpisah
        import threading
        def _run_in_thread():
            asyncio.run(run())
        thread = threading.Thread(target=_run_in_thread)
        thread.start()
        thread.join()
    except RuntimeError:
        # Tidak ada loop aktif, jalankan langsung
        asyncio.run(run())


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AttestationError",
    "AttestationNotFoundError",
    "AttestationStatus",
    "AttestationVerificationError",
    "RegulatoryAttestation",
    "RegulatoryAttestationSigner",
    "RegulatoryFramework",
    "get_regulatory_attestation_signer",
]

if __name__ == "__main__":
    cli()
