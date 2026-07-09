#!/usr/bin/env python3
"""
Module: tax_authority_coretax_port.py
Layer: Ports (Primary)
Responsibility: Mendefinisikan port interface untuk komunikasi dengan Coretax DJP.
               Hanya berisi port interface dan data classes, tanpa implementasi.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class TaxSubmissionType(str, Enum):
    SPT_MASA_PPN = "spt_masa_ppn"
    SPT_MASA_PPH_21 = "spt_masa_pph21"
    SPT_MASA_PPH_23 = "spt_masa_pph23"
    SPT_TAHUNAN_BADAN = "spt_tahunan_badan"
    FAKTUR_PAJAK = "faktur_pajak"
    BUPOT = "bupot"
    SPT_PEMBETULAN = "spt_pembetulan"


class TaxStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    VOID = "void"


@dataclass
class SubmissionResponse:
    submission_id: str
    status: TaxStatus
    reference_number: str | None = None
    message: str | None = None
    timestamp: datetime | None = None
    additional_data: Any | None = None


class CoretaxEndpoint(Enum):
    NSFP = "/v2/nsfp"
    FAKTUR_OUT = "/v2/faktur/keluaran"
    FAKTUR_OUT_STATUS = "/v2/faktur/keluaran/{id}/status"
    FAKTUR_IN = "/v2/faktur/masukan"
    SPT_MASA_PPN = "/v2/spt/ppn/masa"
    SPT_MASA_PPH21 = "/v2/spt/pph21/masa"
    SPT_MASA_PPH23 = "/v2/spt/pph23/masa"
    SPT_TAHUNAN = "/v2/spt/tahunan"
    NTPN_VALIDATE = "/v2/ntpn/validate"
    HEALTH = "/v2/health"


class FakturStatus(Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOID = "VOID"
    EXPIRED = "EXPIRED"


class SPTStatus(Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISED = "REVISED"


@dataclass
class NSFPResponse:
    nsfp_list: list[str]
    tahun: int
    bulan: int
    jumlah: int
    sisa: int
    response_code: str
    response_message: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "nsfp_list": self.nsfp_list,
            "tahun": self.tahun,
            "bulan": self.bulan,
            "jumlah": self.jumlah,
            "sisa": self.sisa,
            "response_code": self.response_code,
            "response_message": self.response_message,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class FakturResponse:
    faktur_id: str
    status: FakturStatus
    approval_code: str | None
    rejection_reason: str | None
    qr_code_url: str | None
    response_code: str
    response_message: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "faktur_id": self.faktur_id,
            "status": self.status.value,
            "approval_code": self.approval_code,
            "rejection_reason": self.rejection_reason,
            "qr_code_url": self.qr_code_url,
            "response_code": self.response_code,
            "response_message": self.response_message,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SPTPResponse:
    spt_id: str
    status: SPTStatus
    bukti_penerimaan: str | None
    rejection_reason: str | None
    response_code: str
    response_message: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "spt_id": self.spt_id,
            "status": self.status.value,
            "bukti_penerimaan": self.bukti_penerimaan,
            "rejection_reason": self.rejection_reason,
            "response_code": self.response_code,
            "response_message": self.response_message,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class NTPNValidationResponse:
    ntpn: str
    valid: bool
    amount: Decimal
    payment_date: date
    taxpayer_name: str | None
    response_code: str
    response_message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ntpn": self.ntpn,
            "valid": self.valid,
            "amount": str(self.amount),
            "payment_date": self.payment_date.isoformat(),
            "taxpayer_name": self.taxpayer_name,
            "response_code": self.response_code,
            "response_message": self.response_message,
        }


@dataclass
class CoretaxRequestLog:
    id: UUID
    endpoint: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
    http_status: int
    success: bool
    error_message: str | None
    duration_ms: int
    request_id: str
    timestamp: datetime
    retry_count: int


# ============================================================================
# PORT INTERFACE (Abstract Base Class)
# ============================================================================

class TaxAuthorityCoretaxPort(ABC):
    @abstractmethod
    async def authenticate(self) -> bool:
        pass

    @abstractmethod
    async def submit_faktur_keluaran(self, faktur_data: dict[str, Any]) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_faktur_keluaran_status(self, faktur_id: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def submit_faktur_masukan(self, faktur_data: dict[str, Any]) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_faktur_masukan_status(self, faktur_id: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def generate_bupot(self, transaction_data: dict[str, Any]) -> dict[str, Any]:
        pass

    @abstractmethod
    async def submit_bupot_batch(self, bupot_list: list[dict[str, Any]]) -> dict[str, Any]:
        pass

    @abstractmethod
    async def request_nsfp(self, year: int, quantity: int) -> list[str]:
        pass

    @abstractmethod
    async def get_available_nsfp(self, year: int) -> list[str]:
        pass

    @abstractmethod
    async def validate_ntpn(self, ntpn: str, amount: Decimal, payment_date: date) -> bool:
        pass

    @abstractmethod
    async def submit_spt_masa_ppn(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def submit_spt_masa_pph21(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def submit_spt_masa_pph23(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def check_health(self) -> dict[str, Any]:
        pass


# Re-export CoretaxPort alias (if needed)
# from ports.primary.core_tax_port import CoreTaxPort
# CoretaxPort = CoreTaxPort
CoretaxPort = TaxAuthorityCoretaxPort

__all__ = [
    "CoretaxEndpoint",
    "CoretaxRequestLog",
    "FakturResponse",
    "FakturStatus",
    "NSFPResponse",
    "NTPNValidationResponse",
    "SPTPResponse",
    "SPTStatus",
    "SubmissionResponse",
    "TaxAuthorityCoretaxPort",
    "TaxStatus",
    "TaxSubmissionType",
    "CoretaxPort", 
]