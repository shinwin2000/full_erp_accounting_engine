#!/usr/bin/env python3
"""
Module: glacier_cold_storage_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Menyimpan dan mengambil arsip ke AWS Glacier (cold storage).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GlacierColdStorageAdapter:
    """
    Adapter untuk AWS Glacier.
    Stub, hanya logging.
    """

    async def archive(self, data: bytes, archive_name: str) -> dict[str, Any]:
        """Simpan data ke Glacier."""
        # SOLUSI: Mengubah f-string menjadi lazy logging format (%s) untuk meloloskan validasi scanner
        logger.info("Archiving %s (%s bytes) to Glacier", archive_name, len(data))
        return {"archive_id": f"glacier_{archive_name}", "success": True}

    async def retrieve(self, archive_id: str) -> bytes:
        """Ambil data dari Glacier (mungkin butuh waktu lama)."""
        # SOLUSI: Mengubah f-string menjadi lazy logging format (%s)
        logger.info("Retrieving archive %s from Glacier", archive_id)
        return b"mock_data_from_glacier"
