#!/usr/bin/env python3
"""
Module: outbox_message_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Alias untuk OutboxTable (forward compatibility).
"""

from __future__ import annotations

from infrastructure.persistence_orm.outbox_table import OutboxRecord, OutboxStatus
from infrastructure.persistence_orm.outbox_table import OutboxTable as OutboxMessageTable

__all__ = ["OutboxMessageTable", "OutboxRecord", "OutboxStatus"]
