"""
Module: generated_report_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM model untuk metadata laporan yang di-generate lewat
    fastapi_report_router.py (list/get/status/history/delete report).

CATATAN ARSITEKTUR: sengaja dibuat sebagai tabel BARU (bukan menambah kolom
ke report_output_table yang sudah ada), karena report_output dirancang
untuk sistem penjadwalan laporan yang lebih kompleks (terhubung ke
report_definition via definition_id NOT NULL) - tidak cocok untuk alur
"generate ad-hoc lalu list/get/delete" yang lebih sederhana yang dipakai
router ini. Dua sistem ini independen; report_output/report_definition/
report_schedule tetap ada untuk fitur penjadwalan terpisah.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import UUID as SQLUUID
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text

from infrastructure.persistence_orm.base_model import Base


class GeneratedReportTable(Base):
    __tablename__ = "generated_report"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    report_number = Column(String(50), nullable=False, unique=True)
    report_type = Column(String(40), nullable=False)
    report_format = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    file_path = Column(Text, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    parameters = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    generated_at = Column(DateTime, nullable=False)
    generated_by = Column(SQLUUID(as_uuid=True), nullable=False)
    generated_by_name = Column(String(200), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(SQLUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, nullable=False)
