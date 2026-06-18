#!/usr/bin/env python3
"""
Module: postgres_read_replica_router.py
Layer: Adapters (Secondary Implementation)
Responsibility: Routing query baca ke read replica, tulis ke primary.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PostgresReadReplicaRouter:
    """
    Router sederhana untuk read replica.
    Stub, selalu menggunakan primary.
    """

    def __init__(self, primary_url: str, replica_urls: list[str]):
        self.primary = primary_url
        self.replicas = replica_urls

    def get_read_connection(self) -> str:
        """Dapatkan URL untuk read (pilih replica secara round-robin)."""
        if self.replicas:
            return self.replicas[0]
        return self.primary

    def get_write_connection(self) -> str:
        return self.primary
