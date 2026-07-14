#!/usr/bin/env python3
"""
Module: evidence_document_retriever.py
Layer: Infrastructure (File Storage)
Responsibility: Layanan untuk mengambil (retrieve) dokumen bukti dari file storage
               dengan caching dan presigned URL generation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from infrastructure.caching.redis_manager import RedisManager, get_redis_manager

# Internal dependencies
from infrastructure.file_storage.abstract_port import FileNotFoundError, FileStoragePort
from infrastructure.file_storage.glacier_cold_storage_adapter import (
    GlacierColdStorageAdapter,
    get_glacier_cold_storage_adapter,
)
from infrastructure.file_storage.minio_evidence_adapter import (
    get_minio_evidence_adapter,
)
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PRESIGNED_URL_CACHE_TTL = 300  # 5 minutes
MAX_BATCH_SIZE = 50

# ============================================================================
# EXCEPTIONS
# ============================================================================


class EvidenceRetrievalError(Exception):
    pass


class EvidenceNotFoundError(EvidenceRetrievalError):
    pass


class BatchRetrievalError(EvidenceRetrievalError):
    pass


# ============================================================================
# EVIDENCE RETRIEVER
# ============================================================================


class EvidenceDocumentRetriever:
    def __init__(
        self,
        hot_storage: FileStoragePort | None = None,
        cold_storage: GlacierColdStorageAdapter | None = None,
    ):
        self._hot_storage = hot_storage
        self._cold_storage = cold_storage
        self._redis_manager: RedisManager | None = None
        self._presigned_url_cache: dict[str, dict] = {}
        self._retrieval_jobs: dict[str, dict] = {}

    async def _get_hot_storage(self) -> FileStoragePort:
        if self._hot_storage is None:
            self._hot_storage = await get_minio_evidence_adapter()
        return self._hot_storage

    async def _get_cold_storage(self) -> GlacierColdStorageAdapter:
        if self._cold_storage is None:
            self._cold_storage = await get_glacier_cold_storage_adapter()
        return self._cold_storage

    async def _get_redis(self) -> RedisManager:
        if self._redis_manager is None:
            self._redis_manager = await get_redis_manager()
        return self._redis_manager

    def _is_hot_uri(self, uri: str) -> bool:
        return uri.startswith("minio://") or uri.startswith("s3://")

    def _is_cold_uri(self, uri: str) -> bool:
        return uri.startswith("glacier://")

    async def retrieve_evidence(
        self, evidence_uri: str, verify_hash: bool = True, use_cache: bool = True
    ) -> bytes:
        cache_key = f"evidence:content:{evidence_uri}"
        if use_cache:
            redis = await self._get_redis()
            cached = await redis.get(cache_key)
            if cached:
                import base64
                content = base64.b64decode(cached)
                logger.debug(f"Evidence retrieved from cache: {evidence_uri}")
                await self._audit_access(evidence_uri, "cache_hit")
                return content

        try:
            if self._is_hot_uri(evidence_uri):
                content = await self._retrieve_from_hot(evidence_uri, verify_hash)
            elif self._is_cold_uri(evidence_uri):
                content = await self._retrieve_from_cold(evidence_uri, verify_hash)
            else:
                raise EvidenceRetrievalError(f"Unknown URI scheme: {evidence_uri}")

            if use_cache and len(content) < 10 * 1024 * 1024:
                redis = await self._get_redis()
                import base64
                await redis.setex(cache_key, 3600, base64.b64encode(content).decode("ascii"))

            await self._audit_access(evidence_uri, "success")
            return content

        except FileNotFoundError:
            await self._audit_access(evidence_uri, "not_found")
            raise EvidenceNotFoundError(f"Evidence not found: {evidence_uri}")
        except Exception as e:
            await self._audit_access(evidence_uri, "error", error=str(e))
            raise EvidenceRetrievalError(f"Failed to retrieve evidence: {e}") from e

    async def _retrieve_from_hot(self, evidence_uri: str, verify_hash: bool) -> bytes:
        storage = await self._get_hot_storage()
        file_stream = await storage.download(evidence_uri)
        content = file_stream.read()
        if verify_hash:
            metadata = await storage.get_metadata(evidence_uri)
            stored_hash = metadata.get("metadata", {}).get("content_hash") or metadata.get("file_hash")
            if stored_hash:
                from infrastructure.file_storage.file_integrity_hasher import FileIntegrityHasher
                hasher = FileIntegrityHasher()
                if not hasher.verify_hash(content, stored_hash):
                    await trigger_alert(
                        title="Evidence Integrity Check Failed",
                        message=f"Evidence {evidence_uri} hash mismatch",
                        severity="critical",
                        source="EvidenceDocumentRetriever",
                    )
                    raise EvidenceRetrievalError("Integrity check failed")
        return content

    async def _retrieve_from_cold(self, evidence_uri: str, verify_hash: bool) -> bytes:
        storage = await self._get_cold_storage()
        archive_id = evidence_uri.split("/")[-1]
        job_status = await storage.get_job_status(archive_id)
        if job_status and job_status.get("status") == "Succeeded":
            return await storage.download(evidence_uri)
        elif job_status and job_status.get("status") == "InProgress":
            raise EvidenceRetrievalError(
                f"Retrieval in progress for {evidence_uri}. "
                f"Estimated completion: {job_status.get('estimated_completion')}"
            )
        else:
            await storage.download(evidence_uri)
            raise EvidenceRetrievalError(
                f"Retrieval initiated for {evidence_uri}. Please retry later."
            )

    async def get_presigned_url(
        self, evidence_uri: str, expiration_seconds: int = 3600, force_refresh: bool = False
    ) -> str:
        cache_key = f"evidence:presigned:{evidence_uri}:{expiration_seconds}"
        if not force_refresh and cache_key in self._presigned_url_cache:
            cached = self._presigned_url_cache[cache_key]
            if cached["expires_at"] > datetime.now(UTC):
                logger.debug(f"Presigned URL served from cache for {evidence_uri}")
                await self._audit_access(evidence_uri, "presigned_cache")
                return cached["url"]

        try:
            if self._is_hot_uri(evidence_uri):
                storage = await self._get_hot_storage()
                url = await storage.generate_presigned_url(evidence_uri, expiration_seconds)
            elif self._is_cold_uri(evidence_uri):
                raise EvidenceRetrievalError("Presigned URLs not supported for Glacier storage")
            else:
                raise EvidenceRetrievalError(f"Unknown URI scheme: {evidence_uri}")

            self._presigned_url_cache[cache_key] = {
                "url": url,
                "expires_at": datetime.now(UTC) + timedelta(seconds=expiration_seconds),
            }
            await self._audit_access(evidence_uri, "presigned_generated")
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise EvidenceRetrievalError(f"Presigned URL generation failed: {e}") from e

    async def batch_retrieve(
        self, evidence_uris: list[str], verify_hash: bool = True
    ) -> dict[str, bytes]:
        if len(evidence_uris) > MAX_BATCH_SIZE:
            raise BatchRetrievalError(
                f"Batch size exceeds limit: {len(evidence_uris)} > {MAX_BATCH_SIZE}"
            )
        results = {}
        errors = {}

        async def retrieve_one(uri: str):
            try:
                content = await self.retrieve_evidence(uri, verify_hash, use_cache=True)
                results[uri] = content
            except Exception as e:
                errors[uri] = str(e)

        tasks = [retrieve_one(uri) for uri in evidence_uris]
        await asyncio.gather(*tasks, return_exceptions=True)
        if errors:
            logger.warning(f"Batch retrieval completed with {len(errors)} errors: {errors}")
        return results

    async def get_evidence_metadata(self, evidence_uri: str) -> dict[str, Any]:
        try:
            if self._is_hot_uri(evidence_uri):
                storage = await self._get_hot_storage()
                metadata = await storage.get_metadata(evidence_uri)
            elif self._is_cold_uri(evidence_uri):
                storage = await self._get_cold_storage()
                metadata = await storage.get_metadata(evidence_uri)
            else:
                raise EvidenceRetrievalError(f"Unknown URI scheme: {evidence_uri}")
            return {
                "uri": evidence_uri,
                "size": metadata.get("size", 0),
                "content_type": metadata.get("content_type"),
                "last_modified": metadata.get("last_modified"),
                "metadata": metadata.get("metadata", {}),
            }
        except FileNotFoundError:
            raise EvidenceNotFoundError(f"Evidence not found: {evidence_uri}")

    async def check_availability(self, evidence_uri: str) -> dict[str, Any]:
        try:
            if self._is_hot_uri(evidence_uri):
                storage = await self._get_hot_storage()
                exists = await storage.exists(evidence_uri)
                return {
                    "available": exists,
                    "storage_tier": "hot",
                    "estimated_retrieval_seconds": 0 if exists else None,
                }
            elif self._is_cold_uri(evidence_uri):
                storage = await self._get_cold_storage()
                archive_id = evidence_uri.split("/")[-1]
                exists = await storage.exists(evidence_uri)
                job_status = await storage.get_job_status(archive_id)
                if job_status and job_status.get("status") == "Succeeded":
                    return {
                        "available": True,
                        "storage_tier": "cold",
                        "retrieved": True,
                        "estimated_retrieval_seconds": 0,
                    }
                elif job_status and job_status.get("status") == "InProgress":
                    return {
                        "available": False,
                        "storage_tier": "cold",
                        "retrieval_in_progress": True,
                        "estimated_completion": job_status.get("estimated_completion"),
                        "estimated_retrieval_seconds": max(
                            0,
                            (
                                job_status.get("estimated_completion") - datetime.now(UTC)
                            ).total_seconds(),
                        ),
                    }
                else:
                    return {
                        "available": False,
                        "storage_tier": "cold",
                        "retrieval_not_started": True,
                        "estimated_retrieval_seconds": 360,
                    }
            else:
                return {"available": False, "error": "Unknown URI scheme"}
        except Exception as e:
            return {"available": False, "error": str(e)}

    async def _audit_access(
        self, evidence_uri: str, access_type: str, error: str | None = None
    ) -> None:
        try:
            # Impor lokal untuk menghindari circular import
            from infrastructure.event_store.append_only_store import get_event_store
            store = await get_event_store()
            await store.append(
                stream_name="audit_evidence_access",
                event_data={
                    "evidence_uri": evidence_uri,
                    "access_type": access_type,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "error": error,
                },
                event_type="evidence.access",
                metadata={"source": "EvidenceDocumentRetriever"},
            )
        except Exception as e:
            logger.warning(f"Failed to create audit record: {e}")

    async def clear_cache(self) -> None:
        self._presigned_url_cache.clear()
        redis = await self._get_redis()
        pattern = "evidence:presigned:*"
        keys = await redis.keys(pattern)
        if keys:
            await redis.delete(*keys)
        logger.info("Evidence presigned URL cache cleared")

    async def get_stats(self) -> dict[str, Any]:
        return {
            "presigned_url_cache_size": len(self._presigned_url_cache),
            "active_retrieval_jobs": len(self._retrieval_jobs),
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_evidence_retriever: EvidenceDocumentRetriever | None = None

async def get_evidence_retriever() -> EvidenceDocumentRetriever:
    global _evidence_retriever
    if _evidence_retriever is None:
        _evidence_retriever = EvidenceDocumentRetriever()
    return _evidence_retriever

async def get_evidence_retriever_dep():
    return await get_evidence_retriever()

__all__ = [
    "BatchRetrievalError",
    "EvidenceDocumentRetriever",
    "EvidenceNotFoundError",
    "EvidenceRetrievalError",
    "get_evidence_retriever",
    "get_evidence_retriever_dep",
]