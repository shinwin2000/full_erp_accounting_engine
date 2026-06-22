#!/usr/bin/env python3
"""
Module: s3_file_storage_adapter_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Menyimpan file ke AWS S3.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class S3FileStorageAdapter:
    """
    Adapter untuk AWS S3.
    Stub, hanya log.
    """

    def __init__(self, bucket: str | None = None, region: str | None = None):
        self.bucket = bucket or os.getenv("S3_BUCKET", "default-bucket")
        self.region = region or os.getenv("S3_REGION", "ap-southeast-1")

    async def upload(self, key: str, data: bytes, metadata: dict | None = None) -> str:
        logger.info(f"Uploading {key} to S3 bucket {self.bucket} ({len(data)} bytes)")
        return f"s3://{self.bucket}/{key}"

    async def download(self, key: str) -> bytes:
        logger.info(f"Downloading {key} from S3")
        return b"mock_s3_content"

    async def delete(self, key: str) -> bool:
        logger.info(f"Deleting {key} from S3")
        return True


S3FileStorageAdapterImpl = S3FileStorageAdapter

__all__ = ["S3FileStorageAdapter", "S3FileStorageAdapterImpl"]