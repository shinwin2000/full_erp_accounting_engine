"""
Module: delivery_order_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM models untuk Delivery Order.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import UUID as SQLUUID, Column, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.persistence_orm.base_model import Base


class DeliveryOrderTable(Base):
    __tablename__ = "delivery_order"

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
    shipped_at = Column(DateTime, nullable=True)
    delivered_by = Column(String(100), nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    received_by = Column(String(100), nullable=True)
    received_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    updated_by = Column(SQLUUID(as_uuid=True), nullable=True)
    version = Column(Integer, server_default="1")


class DeliveryOrderLineTable(Base):
    __tablename__ = "delivery_order_line"

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
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")