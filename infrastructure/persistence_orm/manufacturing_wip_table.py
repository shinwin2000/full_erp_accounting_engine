"""
Module: manufacturing_wip_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM model untuk Work In Process (WIP).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import UUID as SQLUUID, Column, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.persistence_orm.base_model import Base


class WorkInProcessTable(Base):
    __tablename__ = "work_in_process"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    work_order_id = Column(SQLUUID(as_uuid=True), nullable=False)
    product_id = Column(SQLUUID(as_uuid=True), nullable=False)
    product_code = Column(String(50), nullable=False)
    product_name = Column(String(200), nullable=False)
    quantity_started = Column(Numeric(19, 4), nullable=False)
    quantity_completed = Column(Numeric(19, 4), server_default="0")
    quantity_scrap = Column(Numeric(19, 4), server_default="0")
    quantity_wip = Column(Numeric(19, 4), nullable=False)
    material_cost = Column(Numeric(19, 4), server_default="0")
    labor_cost = Column(Numeric(19, 4), server_default="0")
    overhead_cost = Column(Numeric(19, 4), server_default="0")
    total_cost = Column(Numeric(19, 4), server_default="0")
    completion_percent = Column(Numeric(5, 2), server_default="0")
    status = Column(String(20), nullable=False, server_default="in_progress")
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")