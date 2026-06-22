# infrastructure/persistence_orm/sales_order_line_table.py
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import UUID as SQLUUID, Column, Date, DateTime, Integer, Numeric, String

from infrastructure.persistence_orm.base_model import Base


class SalesOrderLineTable(Base):
    __tablename__ = "sales_order_line"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    sales_order_id = Column(SQLUUID(as_uuid=True), nullable=False)
    line_number = Column(Integer, nullable=False)
    item_id = Column(SQLUUID(as_uuid=True), nullable=False)
    item_code = Column(String(30), nullable=False)
    item_name = Column(String(200), nullable=False)
    quantity = Column(Numeric(19, 4), nullable=False)
    shipped_quantity = Column(Numeric(19, 4), server_default="0")
    unit_price = Column(Numeric(19, 4), nullable=False)
    discount_percent = Column(Numeric(5, 2), server_default="0")
    tax_rate = Column(Numeric(5, 2), server_default="0")
    total_amount = Column(Numeric(19, 4), nullable=False)
    expected_ship_date = Column(Date, nullable=True)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    updated_by = Column(SQLUUID(as_uuid=True), nullable=True)
    version = Column(Integer, server_default="1")