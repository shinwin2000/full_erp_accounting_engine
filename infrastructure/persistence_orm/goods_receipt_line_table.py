# infrastructure/persistence_orm/goods_receipt_line_table.py
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import UUID as SQLUUID
from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String

from infrastructure.persistence_orm.base_model import Base


class GoodsReceiptLineTable(Base):
    __tablename__ = "goods_receipt_line"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    goods_receipt_note_id = Column(SQLUUID(as_uuid=True), nullable=False)
    purchase_order_line_id = Column(SQLUUID(as_uuid=True), nullable=False)
    line_number = Column(Integer, nullable=False)
    item_id = Column(SQLUUID(as_uuid=True), nullable=False)
    item_code = Column(String(30), nullable=False)
    item_name = Column(String(200), nullable=False)
    quantity_received = Column(Numeric(19, 4), nullable=False)
    quantity_accepted = Column(Numeric(19, 4), nullable=False)
    quantity_rejected = Column(Numeric(19, 4), server_default="0")
    rejection_reason = Column(String(500), nullable=True)
    batch_number = Column(String(50), nullable=True)
    expiry_date = Column(Date, nullable=True)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    updated_by = Column(SQLUUID(as_uuid=True), nullable=True)
    version = Column(Integer, server_default="1")
