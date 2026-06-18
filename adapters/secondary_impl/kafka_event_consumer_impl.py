#!/usr/bin/env python3
"""
Module: kafka_event_consumer_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Consumer Kafka untuk membaca event dan memicu handler.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class KafkaEventConsumer:
    """
    Consumer Kafka sederhana (stub).
    """

    def __init__(self, bootstrap_servers: str = "localhost:9092", group_id: str = "erp-group"):
        self.bootstrap = bootstrap_servers
        self.group_id = group_id
        self._running = False

    async def start(self, topics: list[str], handler: Callable[[dict[str, Any]], None]) -> None:
        """Mulai consumer dan polling."""
        logger.info(f"Starting Kafka consumer for topics {topics}")
        self._running = True
        while self._running:
            await asyncio.sleep(1)
            # Stub: tidak ada pesan nyata

    async def stop(self) -> None:
        self._running = False
        logger.info("Kafka consumer stopped")
