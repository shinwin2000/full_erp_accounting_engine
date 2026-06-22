"""
Module: saga_orchestration_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM models untuk Saga orchestration tables.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UUID as SQLUUID, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.persistence_orm.base_model import Base


class SagaInstanceTable(Base):
    __tablename__ = "saga_instance"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    saga_type = Column(String(100), nullable=False)
    correlation_id = Column(String(200), nullable=False)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    status = Column(String(30), nullable=False, server_default="STARTED")
    current_step = Column(Integer, nullable=False, server_default="0")
    total_steps = Column(Integer, nullable=False)
    saga_data = Column(JSONB, nullable=False, server_default="{}")
    compensation_data = Column(JSONB, nullable=True)
    started_at = Column(DateTime, server_default="now()")
    last_heartbeat_at = Column(DateTime, server_default="now()")
    completed_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    timeout_at = Column(DateTime, nullable=True)
    version = Column(Integer, server_default="1")
    created_by = Column(SQLUUID(as_uuid=True), nullable=False)
    updated_by = Column(SQLUUID(as_uuid=True), nullable=False)


class SagaStepLogTable(Base):
    __tablename__ = "saga_step_log"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    saga_id = Column(SQLUUID(as_uuid=True), nullable=False)
    step_index = Column(Integer, nullable=False)
    step_name = Column(String(100), nullable=False)
    status = Column(String(30), nullable=False)
    started_at = Column(DateTime, server_default="now()")
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    step_data = Column(JSONB, nullable=True)
    compensation_data = Column(JSONB, nullable=True)


class SagaLockTable(Base):
    __tablename__ = "saga_lock"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    saga_type = Column(String(100), nullable=False)
    correlation_id = Column(String(200), nullable=False)
    locked_by = Column(String(100), nullable=False)
    locked_at = Column(DateTime, server_default="now()")
    expires_at = Column(DateTime, nullable=False)
    released_at = Column(DateTime, nullable=True)


class SagaEventTable(Base):
    __tablename__ = "saga_event"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    saga_id = Column(SQLUUID(as_uuid=True), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    event_version = Column(Integer, server_default="1")
    created_at = Column(DateTime, server_default="now()")
    processed_at = Column(DateTime, nullable=True)