"""
Module: payroll_detail_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM models untuk Payroll detail.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import UUID as SQLUUID
from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, Text

from infrastructure.persistence_orm.base_model import Base


class SalaryStructureTable(Base):
    __tablename__ = "salary_structure"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    structure_code = Column(String(30), nullable=False, unique=True)
    structure_name = Column(String(200), nullable=False)
    effective_date = Column(Date, nullable=False)
    expiry_date = Column(Date, nullable=True)
    is_active = Column(Integer, server_default="1")
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    updated_by = Column(SQLUUID(as_uuid=True), nullable=True)
    version = Column(Integer, server_default="1")


class PayrollDetailTable(Base):
    __tablename__ = "payroll_detail"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    payroll_run_id = Column(SQLUUID(as_uuid=True), nullable=False)
    employee_id = Column(SQLUUID(as_uuid=True), nullable=False)
    period = Column(String(7), nullable=False)
    component_code = Column(String(30), nullable=False)
    component_name = Column(String(200), nullable=False)
    component_type = Column(String(20), nullable=False)
    amount = Column(Numeric(19, 4), nullable=False)
    formula = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")


class PayrollAdjustmentTable(Base):
    __tablename__ = "payroll_adjustment"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    payroll_run_id = Column(SQLUUID(as_uuid=True), nullable=False)
    employee_id = Column(SQLUUID(as_uuid=True), nullable=False)
    adjustment_type = Column(String(20), nullable=False)
    amount = Column(Numeric(19, 4), nullable=False)
    reason = Column(Text, nullable=False)
    approved_by = Column(SQLUUID(as_uuid=True), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
