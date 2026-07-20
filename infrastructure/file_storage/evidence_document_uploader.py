#!/usr/bin/env python3
"""
Module: evidence_document_uploader.py
Layer: Infrastructure (File Storage)
Responsibility: Layanan khusus untuk upload dokumen bukti (evidence) ke file storage.
"""

from __future__ import annotations

import io
import mimetypes
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

# Internal dependencies
from infrastructure.file_storage.abstract_port import FileStoragePort
from infrastructure.file_storage.file_integrity_hasher import FileIntegrityHasher
from infrastructure.file_storage.minio_evidence_adapter import (
    get_minio_evidence_adapter,
)
from infrastructure.telemetry.alert_manager_trigger import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

ALLOWED_MIME_TYPES = {
    "application/pdf": [".pdf"],
    "application/msword": [".doc"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    "application/vnd.ms-excel": [".xls"],
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/tiff": [".tiff", ".tif"],
    "text/plain": [".txt"],
    "text/csv": [".csv"],
    "application/xml": [".xml"],
    "text/xml": [".xml"],
    "application/zip": [".zip"],
    "application/x-rar-compressed": [".rar"],
    "application/x-7z-compressed": [".7z"],
}

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_FILE_SIZE_MB = 50

TRANSACTION_TYPES = {
    "journal": "journal",
    "ar_invoice": "ar_invoice",
    "ap_invoice": "ap_invoice",
    "payment": "payment",
    "receipt": "receipt",
    "contract": "contract",
    "tax_faktur": "tax_faktur",
    "bank_statement": "bank_statement",
    "general": "general",
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class EvidenceUploadError(Exception):
    pass


class InvalidFileTypeError(EvidenceUploadError):
    pass


class FileTooLargeError(EvidenceUploadError):
    pass


class EvidenceNotFoundError(EvidenceUploadError):
    pass


# ============================================================================
# EVIDENCE DOCUMENT UPLOADER
# ============================================================================


class EvidenceDocumentUploader:
    def __init__(self, storage_adapter: FileStoragePort | None = None):
        self._storage = storage_adapter
        self._hasher = FileIntegrityHasher()
        self._upload_history: dict[str, dict] = {}

    async def _get_storage(self) -> FileStoragePort:
        if self._storage is None:
            self._storage = await get_minio_evidence_adapter()
        return self._storage

    def _validate_file_type(self, file_content: bytes, file_name: str) -> None:
        ext = os.path.splitext(file_name)[1].lower()
        allowed_exts = []
        for mime, exts in ALLOWED_MIME_TYPES.items():
            allowed_exts.extend(exts)
        if ext not in allowed_exts:
            raise InvalidFileTypeError(
                f"File extension '{ext}' not allowed. Allowed: {', '.join(allowed_exts)}"
            )
        import magic
        try:
            mime = magic.from_buffer(file_content[:2048], mime=True)
            if mime not in ALLOWED_MIME_TYPES:
                if ext in allowed_exts:
                    logger.warning(
                        f"File MIME type '{mime}' not in allowed list but extension '{ext}' is allowed"
                    )
                    return
                raise InvalidFileTypeError(f"File MIME type '{mime}' not allowed")
        except ImportError:
            logger.debug("python-magic not available, skipping MIME validation")

    def _validate_file_size(self, file_content: bytes) -> None:
        size_mb = len(file_content) / (1024 * 1024)
        if len(file_content) > MAX_FILE_SIZE_BYTES:
            raise FileTooLargeError(
                f"File size {size_mb:.2f} MB exceeds limit of {MAX_FILE_SIZE_MB} MB"
            )

    async def upload_evidence(
        self,
        file_content: bytes,
        file_name: str,
        transaction_type: str,
        transaction_id: UUID,
        uploaded_by: UUID,
        legal_entity_id: UUID,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        self._validate_file_type(file_content, file_name)
        self._validate_file_size(file_content)

        file_hash = self._hasher.compute_hash(file_content)

        if await self._is_duplicate(transaction_type, transaction_id, file_hash):
            logger.warning(f"Duplicate evidence detected for {transaction_type}/{transaction_id}")
            raise EvidenceUploadError("Duplicate evidence file detected")

        evidence_metadata = {
            "transaction_type": transaction_type,
            "transaction_id": str(transaction_id),
            "uploaded_by": str(uploaded_by),
            "legal_entity_id": str(legal_entity_id),
            "original_filename": file_name,
            "file_hash": file_hash,
            "file_size": len(file_content),
            "content_type": self._get_content_type(file_name),
            "description": description or "",
            "uploaded_at": datetime.now(UTC).isoformat(),
        }
        if metadata:
            evidence_metadata.update(metadata)

        storage = await self._get_storage()
        try:
            file_uri = await storage.upload_evidence(
                file_content=io.BytesIO(file_content),
                file_name=file_name,
                transaction_type=transaction_type,
                transaction_id=str(transaction_id),
                metadata=evidence_metadata,
            )
        except Exception as e:
            logger.error(f"Failed to upload evidence: {e}")
            raise EvidenceUploadError(f"Upload failed: {e}") from e

        await self._create_audit_record(
            evidence_uri=file_uri,
            transaction_type=transaction_type,
            transaction_id=transaction_id,
            uploaded_by=uploaded_by,
            file_hash=file_hash,
        )

        evidence_id = str(uuid4())
        self._upload_history[evidence_id] = {
            "evidence_id": evidence_id,
            "uri": file_uri,
            "file_name": file_name,
            "transaction_type": transaction_type,
            "transaction_id": str(transaction_id),
            "file_hash": file_hash,
            "file_size": len(file_content),
            "uploaded_by": str(uploaded_by),
            "uploaded_at": datetime.now(UTC).isoformat(),
        }

        logger.info(
            f"Evidence uploaded: {file_name} ({len(file_content)} bytes) for {transaction_type}/{transaction_id}"
        )

        return {
            "evidence_id": evidence_id,
            "uri": file_uri,
            "file_name": file_name,
            "file_size": len(file_content),
            "file_hash": file_hash,
            "transaction_type": transaction_type,
            "transaction_id": str(transaction_id),
            "uploaded_at": evidence_metadata["uploaded_at"],
        }

    async def download_evidence(self, evidence_uri: str, verify_hash: bool = True) -> bytes:
        storage = await self._get_storage()
        try:
            file_stream = await storage.download(evidence_uri)
            content = file_stream.read()
            if verify_hash:
                metadata = await storage.get_metadata(evidence_uri)
                stored_hash = metadata.get("metadata", {}).get("file_hash") or metadata.get("file_hash")
                if stored_hash:
                    if not self._hasher.verify_hash(content, stored_hash):
                        await trigger_alert(
                            title="Evidence Integrity Check Failed",
                            message=f"Evidence {evidence_uri} hash mismatch. Possible corruption.",
                            severity="critical",
                            source="EvidenceDocumentUploader",
                        )
                        raise EvidenceUploadError("Evidence integrity check failed")
            logger.info(f"Evidence downloaded: {evidence_uri} ({len(content)} bytes)")
            return content
        except FileNotFoundError:
            raise EvidenceNotFoundError(f"Evidence not found: {evidence_uri}")
        except Exception as e:
            logger.error(f"Failed to download evidence: {e}")
            raise EvidenceUploadError(f"Download failed: {e}") from e

    async def delete_evidence(self, evidence_uri: str, deleted_by: UUID) -> bool:
        storage = await self._get_storage()
        metadata = await storage.get_metadata(evidence_uri)
        uploaded_at = metadata.get("metadata", {}).get("uploaded_at")
        if uploaded_at:
            try:
                upload_date = datetime.fromisoformat(uploaded_at)
                retention_days = 365 * 7
                retention_end = upload_date + timedelta(days=retention_days)
                if datetime.now(UTC) < retention_end:
                    logger.warning(f"Cannot delete evidence {evidence_uri} due to retention policy")
                    return False
            except (ValueError, TypeError):
                pass

        result = await storage.delete(evidence_uri)
        if result:
            await self._create_audit_record(
                evidence_uri=evidence_uri,
                transaction_type="deletion",
                transaction_id=deleted_by,
                uploaded_by=deleted_by,
                file_hash="",
                extra={"action": "delete"},
            )
            logger.info(f"Evidence deleted: {evidence_uri} by {deleted_by}")
        return result

    async def get_evidence_info(self, evidence_uri: str) -> dict[str, Any]:
        storage = await self._get_storage()
        metadata = await storage.get_metadata(evidence_uri)
        return {
            "uri": evidence_uri,
            "file_name": metadata.get("metadata", {}).get("original_filename"),
            "file_size": metadata.get("size", 0),
            "content_type": metadata.get("content_type"),
            "uploaded_at": metadata.get("metadata", {}).get("uploaded_at"),
            "uploaded_by": metadata.get("metadata", {}).get("uploaded_by"),
            "transaction_type": metadata.get("metadata", {}).get("transaction_type"),
            "transaction_id": metadata.get("metadata", {}).get("transaction_id"),
            "file_hash": metadata.get("metadata", {}).get("file_hash"),
        }

    async def list_evidence_for_transaction(
        self, transaction_type: str, transaction_id: UUID
    ) -> list[dict[str, Any]]:
        prefix = f"{transaction_type}/{transaction_id}/"
        storage = await self._get_storage()
        files = await storage.list_files(prefix=prefix, limit=100)
        evidence_list = []
        for file_info in files:
            evidence_list.append(
                {
                    "uri": file_info["uri"],
                    "file_name": file_info.get("key", "").split("/")[-1],
                    "size": file_info.get("size", 0),
                    "last_modified": file_info.get("last_modified"),
                }
            )
        return evidence_list

    async def _is_duplicate(
        self, transaction_type: str, transaction_id: UUID, file_hash: str
    ) -> bool:
        return False

    async def _create_audit_record(
        self,
        evidence_uri: str,
        transaction_type: str,
        transaction_id: UUID,
        uploaded_by: UUID,
        file_hash: str,
        extra: dict | None = None,
    ) -> None:
        try:
            # Impor lokal
            from infrastructure.event_store.append_only_store import get_event_store
            store = await get_event_store()
            await store.append(
                stream_name="audit_evidence",
                event_data={
                    "evidence_uri": evidence_uri,
                    "transaction_type": transaction_type,
                    "transaction_id": str(transaction_id),
                    "uploaded_by": str(uploaded_by),
                    "file_hash": file_hash,
                    "timestamp": datetime.now(UTC).isoformat(),
                    **(extra or {}),
                },
                event_type="evidence.operation",
                metadata={"source": "EvidenceDocumentUploader"},
            )
        except Exception as e:
            logger.warning(f"Failed to create audit record: {e}")

    def _get_content_type(self, file_name: str) -> str:
        content_type, _ = mimetypes.guess_type(file_name)
        return content_type or "application/octet-stream"

    async def get_stats(self) -> dict[str, Any]:
        return {
            "total_uploads": len(self._upload_history),
            "upload_history": list(self._upload_history.values())[-20:],
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_evidence_uploader: EvidenceDocumentUploader | None = None

async def get_evidence_uploader() -> EvidenceDocumentUploader:
    global _evidence_uploader
    if _evidence_uploader is None:
        _evidence_uploader = EvidenceDocumentUploader()
    return _evidence_uploader

async def get_evidence_uploader_dep():
    return await get_evidence_uploader()

__all__ = [
    "TRANSACTION_TYPES",
    "EvidenceDocumentUploader",
    "EvidenceNotFoundError",
    "EvidenceUploadError",
    "FileTooLargeError",
    "InvalidFileTypeError",
    "get_evidence_uploader",
    "get_evidence_uploader_dep",
]
