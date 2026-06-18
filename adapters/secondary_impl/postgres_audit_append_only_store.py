#!/usr/bin/env python3
"""
Module: postgres_audit_append_only_store.py
Layer: Adapters (Secondary Implementation)
Responsibility: Menyimpan audit trail ke PostgreSQL secara append-only.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class PostgresAuditAppendOnlyStore:
    """
    Append-only store untuk audit trail menggunakan PostgreSQL.
    Stub, tidak melakukan insert nyata.
    """

    async def append(self, stream: str, event_data: dict[str, Any]) -> None:
        """Tambahkan event ke audit log."""
        logger.info(f"Appending audit event to stream {stream}: {json.dumps(event_data)}")
