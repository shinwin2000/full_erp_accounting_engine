#!/usr/bin/env python3
"""
Module: kafka_dead_letter_handler.py
Layer: Adapters (Secondary Implementation)
Responsibility: Menangani pesan yang gagal diproses (dead letter queue) dari Kafka.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class KafkaDeadLetterHandler:
    """
    Handler untuk dead letter Kafka.
    """

    async def handle(self, message: dict[str, Any], error: str) -> None:
        """Proses pesan dead letter (simpan ke file atau database)."""
        logger.error(f"Dead letter message: {json.dumps(message)} | Error: {error}")
        # Stub: bisa simpan ke database atau file
