#!/usr/bin/env python3
"""
Module: delivery_order_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM models untuk Delivery Order.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import UUID as SQLUUID
from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.sql import func

from infrastructure.persistence_orm.base_model import Base


class DeliveryOrderTable(Base):
    __tablename__ = "delivery_order"
    __table_args__ = {"extend_existing": True}

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    delivery_number = Column(String(50), nullable=False, unique=True)
    delivery_date = Column(Date, nullable=False)
    sales_order_id = Column(SQLUUID(as_uuid=True), nullable=True)
    customer_id = Column(SQLUUID(as_uuid=True), nullable=False)
    customer_name = Column(String(200), nullable=False)
    customer_address = Column(String(500), nullable=True)
    shipping_address = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, server_default="draft")
    shipped_by = Column(String(100), nullable=True)
    shipped_at = Column(DateTime(timezone=True), nullable=True)
    delivered_by = Column(String(100), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    received_by = Column(String(100), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    # ===== PERBAIKAN TIMESTAMP =====
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    updated_by = Column(SQLUUID(as_uuid=True), nullable=True)
    version = Column(Integer, server_default="1")

    def __repr__(self) -> str:
        return f"<DeliveryOrderTable {self.delivery_number}>"


class DeliveryOrderLineTable(Base):
    __tablename__ = "delivery_order_line"
    __table_args__ = {"extend_existing": True}

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    delivery_order_id = Column(SQLUUID(as_uuid=True), nullable=False)
    sales_order_line_id = Column(SQLUUID(as_uuid=True), nullable=True)
    line_number = Column(Integer, nullable=False)
    item_id = Column(SQLUUID(as_uuid=True), nullable=False)
    item_code = Column(String(30), nullable=False)
    item_name = Column(String(200), nullable=False)
    quantity_ordered = Column(Numeric(19, 4), nullable=False)
    quantity_shipped = Column(Numeric(19, 4), nullable=False)
    unit_price = Column(Numeric(19, 4), nullable=False)
    total_amount = Column(Numeric(19, 4), nullable=False)
    batch_number = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<DeliveryOrderLineTable id={self.id}>"
