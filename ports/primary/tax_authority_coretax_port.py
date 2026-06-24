#!/usr/bin/env python3
"""
Module: tax_authority_coretax_port.py
Layer: Ports (Primary)
Responsibility: Mendefinisikan port interface untuk komunikasi dengan Coretax DJP,
               serta menyediakan implementasi in-memory untuk testing/development.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES (shared between port and implementations)
# ============================================================================

class TaxSubmissionType(str, Enum):
    """Jenis submission ke Coretax DJP."""
    SPT_MASA_PPN = "spt_masa_ppn"
    SPT_MASA_PPH_21 = "spt_masa_pph21"
    SPT_MASA_PPH_23 = "spt_masa_pph23"
    SPT_TAHUNAN_BADAN = "spt_tahunan_badan"
    FAKTUR_PAJAK = "faktur_pajak"
    BUPOT = "bupot"
    SPT_PEMBETULAN = "spt_pembetulan"
    # Tambahkan sesuai kebutuhan


class TaxStatus(str, Enum):
    """Status submission di Coretax."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    VOID = "void"


@dataclass
class SubmissionResponse:
    """Response standar untuk submission ke Coretax."""
    submission_id: str
    status: TaxStatus
    reference_number: Optional[str] = None
    message: Optional[str] = None
    timestamp: Optional[datetime] = None
    additional_data: Optional[Any] = None


class CoretaxEndpoint(Enum):
    """Endpoint Coretax DJP."""

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
    """Status faktur pajak."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOID = "VOID"
    EXPIRED = "EXPIRED"


class SPTStatus(Enum):
    """Status SPT."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISED = "REVISED"


@dataclass
class NSFPResponse:
    """Response NSFP dari DJP."""

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
    """Response submit faktur pajak."""

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
    """Response submit SPT."""

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
    """Response validasi NTPN."""

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
            "amount": float(self.amount),
            "payment_date": self.payment_date.isoformat(),
            "taxpayer_name": self.taxpayer_name,
            "response_code": self.response_code,
            "response_message": self.response_message,
        }


@dataclass
class CoretaxRequestLog:
    """Log request ke Coretax."""

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
    """
    Port interface untuk komunikasi dengan sistem Coretax DJP.
    Semua secondary adapter (implementasi) harus mengimplementasikan port ini.
    """

    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate ke Coretax API."""
        pass

    # ========== Faktur Pajak ==========

    @abstractmethod
    async def submit_faktur_keluaran(self, faktur_data: dict[str, Any]) -> dict[str, Any]:
        """Submit faktur keluaran (output tax invoice) ke Coretax."""
        pass

    @abstractmethod
    async def get_faktur_keluaran_status(self, faktur_id: str) -> dict[str, Any]:
        """Cek status faktur keluaran."""
        pass

    @abstractmethod
    async def submit_faktur_masukan(self, faktur_data: dict[str, Any]) -> dict[str, Any]:
        """Submit faktur masukan (input tax invoice) untuk dikreditkan."""
        pass

    @abstractmethod
    async def get_faktur_masukan_status(self, faktur_id: str) -> dict[str, Any]:
        """Cek status faktur masukan."""
        pass

    # ========== e-Bupot ==========

    @abstractmethod
    async def generate_bupot(self, transaction_data: dict[str, Any]) -> dict[str, Any]:
        """Generate Bukti Pemotongan (PPh 23/26)."""
        pass

    @abstractmethod
    async def submit_bupot_batch(self, bupot_list: list[dict[str, Any]]) -> dict[str, Any]:
        """Submit multiple bupot sekaligus."""
        pass

    # ========== NSFP Management ==========

    @abstractmethod
    async def request_nsfp(self, year: int, quantity: int) -> list[str]:
        """Request Nomor Seri Faktur Pajak dari DJP."""
        pass

    @abstractmethod
    async def get_available_nsfp(self, year: int) -> list[str]:
        """Get remaining available NSFP."""
        pass

    # ========== NTPN Validation ==========

    @abstractmethod
    async def validate_ntpn(self, ntpn: str, amount: Decimal, payment_date: date) -> bool:
        """Validate NTPN (Nomor Transaksi Penerimaan Negara)."""
        pass

    # ========== SPT Filing ==========

    @abstractmethod
    async def submit_spt_masa_ppn(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Submit SPT Masa PPN."""
        pass

    @abstractmethod
    async def submit_spt_masa_pph21(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Submit SPT Masa PPh 21."""
        pass

    @abstractmethod
    async def submit_spt_masa_pph23(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Submit SPT Masa PPh 23/26."""
        pass

    # ========== Health Check ==========

    @abstractmethod
    async def check_health(self) -> dict[str, Any]:
        """Check kesehatan koneksi ke Coretax."""
        pass


# ============================================================================
# IN-MEMORY IMPLEMENTATION (for testing/development)
# ============================================================================

class CoreTaxPort:
    """
    In-memory implementation of Coretax DJP API client with simulation.
    (This is a test double, not the primary port implementation.)
    """

    def __init__(
        self, api_key: str | None = None, base_url: str = "https://api.coretax.djp.go.id/v2"
    ):
        self._base_url = base_url
        self._api_key = api_key or "dev_coretax_api_key_dummy"
        self._nsfp_allocations: dict[
            tuple[int, int], dict[str, Any]
        ] = {}  # (tahun, bulan) -> {allocated, used, list}
        self._faktur_submissions: dict[str, dict[str, Any]] = {}  # faktur_id -> data
        self._spt_submissions: dict[str, dict[str, Any]] = {}  # spt_id -> data
        self._ntpn_cache: dict[str, dict[str, Any]] = {}  # ntpn -> data
        self._request_logs: list[CoretaxRequestLog] = []
        self._audit_log: list[dict[str, Any]] = []
        self._webhook_subscribers: dict[str, list[Callable[[dict[str, Any]], Awaitable[None]]]] = {}
        self._lock = asyncio.Lock()
        self._health_status = "healthy"
        self._simulated_delay_ms = 50  # simulate network latency
        self._failure_rate = 0.0  # 0-1, for testing

        # Initialize some dummy NTPNs for validation
        self._init_dummy_ntpn()

    def _init_dummy_ntpn(self):
        """Create dummy NTPN entries for validation."""
        dummy_ntpn = {
            "1234567890123456": {
                "valid": True,
                "amount": Decimal("1000000"),
                "payment_date": date.today() - timedelta(days=2),
                "taxpayer_name": "PT ACCOUNTING MAJU BERSAMA",
            },
            "9999999999999999": {
                "valid": False,
                "amount": Decimal("0"),
                "payment_date": date.today(),
                "taxpayer_name": None,
            },
        }
        for ntpn, data in dummy_ntpn.items():
            self._ntpn_cache[ntpn] = data

    # ==================== HELPER ====================

    async def _log_audit(
        self, action: str, endpoint: str, request_id: str, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "endpoint": endpoint,
            "request_id": request_id,
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"CORETAX AUDIT: {action} on {endpoint} (req_id={request_id})")

    async def _simulate_network(self):
        """Simulate network latency and random failure."""
        await asyncio.sleep(self._simulated_delay_ms / 1000.0)
        if self._failure_rate > 0 and secrets.randbelow(100) < (self._failure_rate * 100):
            raise Exception("Simulated Coretax API failure (network error)")

    def _generate_request_id(self) -> str:
        return f"REQ-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"

    async def _log_request(
        self,
        endpoint: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
        status: int,
        success: bool,
        error_msg: str | None,
        duration_ms: int,
        retry_count: int,
    ) -> CoretaxRequestLog:
        log = CoretaxRequestLog(
            id=uuid4(),
            endpoint=endpoint,
            request_payload=request_payload,
            response_payload=response_payload,
            http_status=status,
            success=success,
            error_message=error_msg,
            duration_ms=duration_ms,
            request_id=self._generate_request_id(),
            timestamp=datetime.now(UTC),
            retry_count=retry_count,
        )
        async with self._lock:
            self._request_logs.append(log)
        return log

    # ==================== NSFP ====================

    async def get_nsfp(
        self, amount: int, tahun: int, bulan: int, retry_count: int = 0
    ) -> NSFPResponse:
        """
        Mendapatkan Nomor Seri Faktur Pajak dari DJP.
        Format NSFP: 3 digit kode + 8 digit nomor urut (simulasi).
        """
        start_time = time.perf_counter()
        request_payload = {"amount": amount, "tahun": tahun, "bulan": bulan}
        response_payload = {}
        success = False
        error_msg = None
        http_status = 200

        try:
            await self._simulate_network()
            # Validasi
            if amount <= 0 or amount > 1000:
                raise ValueError("Amount must be between 1 and 1000")
            if tahun < 2020 or tahun > 2030:
                raise ValueError("Year must be between 2020 and 2030")
            if bulan < 1 or bulan > 12:
                raise ValueError("Month must be between 1 and 12")

            # Generate NSFP
            key = (tahun, bulan)
            if key not in self._nsfp_allocations:
                # Allocate initial pool
                prefix = f"{tahun % 100:02d}{bulan:02d}"
                base_number = 10000000
                allocated_list = [f"{prefix}{base_number + i}" for i in range(500)]
                self._nsfp_allocations[key] = {
                    "allocated": allocated_list,
                    "used": [],
                    "remaining": allocated_list.copy(),
                }
            pool = self._nsfp_allocations[key]
            available = pool["remaining"]
            if len(available) < amount:
                # Simulate request more from DJP
                last_num = int(available[-1][4:]) if available else 10000000
                new_nsfps = [f"{pool['allocated'][0][:4]}{last_num + i + 1}" for i in range(amount)]
                pool["allocated"].extend(new_nsfps)
                pool["remaining"].extend(new_nsfps)

            nsfp_list = pool["remaining"][:amount]
            # Mark as used
            pool["used"].extend(nsfp_list)
            pool["remaining"] = pool["remaining"][amount:]

            response_payload = {
                "nsfp_list": nsfp_list,
                "tahun": tahun,
                "bulan": bulan,
                "jumlah": amount,
                "sisa": len(pool["remaining"]),
            }
            success = True
            result = NSFPResponse(
                nsfp_list=nsfp_list,
                tahun=tahun,
                bulan=bulan,
                jumlah=amount,
                sisa=len(pool["remaining"]),
                response_code="00",
                response_message="SUCCESS",
                timestamp=datetime.now(UTC),
            )
        except Exception as e:
            error_msg = str(e)
            http_status = 500
            result = NSFPResponse(
                nsfp_list=[],
                tahun=tahun,
                bulan=bulan,
                jumlah=0,
                sisa=0,
                response_code="99",
                response_message=f"ERROR: {error_msg}",
                timestamp=datetime.now(UTC),
            )
        finally:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            await self._log_request(
                "/v2/nsfp",
                request_payload,
                response_payload,
                http_status,
                success,
                error_msg,
                duration_ms,
                retry_count,
            )
            await self._log_audit(
                "GET_NSFP",
                "/v2/nsfp",
                result.request_id if "result" in locals() else "unknown",
                {"amount": amount, "tahun": tahun, "bulan": bulan, "success": success},
            )
        return result

    # ==================== FAKTUR PAJAK ====================

    async def submit_faktur_pajak(
        self, faktur_data: dict[str, Any], retry_count: int = 0
    ) -> FakturResponse:
        """
        Mengirim faktur pajak keluaran ke Coretax.
        faktur_data harus memiliki: nsfp, tanggal, dpp, ppn, npwp_pembeli, nama_pembeli, dll.
        """
        start_time = time.perf_counter()
        request_payload = faktur_data.copy()
        response_payload = {}
        success = False
        error_msg = None
        http_status = 200

        try:
            await self._simulate_network()
            # Validasi minimal
            required_fields = ["nsfp", "tanggal", "dpp", "ppn", "npwp_pembeli", "nama_pembeli"]
            for field in required_fields:
                if field not in faktur_data:
                    raise ValueError(f"Missing required field: {field}")

            nsfp = faktur_data["nsfp"]
            # Generate approval code
            approval_code = f"APPR-{secrets.token_hex(8).upper()}"
            faktur_id = f"FK-{nsfp}-{int(time.time())}"
            # Simulasi reject jika tanggal lebih dari 15 hari setelah tanggal faktur? Tidak, always approve.
            status = FakturStatus.APPROVED
            rejection_reason = None
            qr_code = f"https://coretax.djp.go.id/qr/{faktur_id}"

            # Store submission
            submission_data = {
                "faktur_id": faktur_id,
                "status": status.value,
                "approval_code": approval_code,
                "data": faktur_data,
                "submitted_at": datetime.now(UTC),
            }
            self._faktur_submissions[faktur_id] = submission_data

            response_payload = {
                "faktur_id": faktur_id,
                "status": status.value,
                "approval_code": approval_code,
                "qr_code_url": qr_code,
            }
            success = True
            result = FakturResponse(
                faktur_id=faktur_id,
                status=status,
                approval_code=approval_code,
                rejection_reason=rejection_reason,
                qr_code_url=qr_code,
                response_code="00",
                response_message="FAKTUR_DITERIMA",
                timestamp=datetime.now(UTC),
            )
        except Exception as e:
            error_msg = str(e)
            http_status = 400
            result = FakturResponse(
                faktur_id="",
                status=FakturStatus.REJECTED,
                approval_code=None,
                rejection_reason=error_msg,
                qr_code_url=None,
                response_code="99",
                response_message=f"ERROR: {error_msg}",
                timestamp=datetime.now(UTC),
            )
        finally:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            await self._log_request(
                "/v2/faktur/keluaran",
                request_payload,
                response_payload,
                http_status,
                success,
                error_msg,
                duration_ms,
                retry_count,
            )
            await self._log_audit(
                "SUBMIT_FAKTUR",
                "/v2/faktur/keluaran",
                result.faktur_id if result else "unknown",
                {"nsfp": faktur_data.get("nsfp"), "success": success},
            )
        return result

    async def get_faktur_status(self, faktur_id: str, retry_count: int = 0) -> FakturResponse:
        """Cek status faktur pajak yang sudah disubmit."""
        start_time = time.perf_counter()
        request_payload = {"faktur_id": faktur_id}
        response_payload = {}
        success = False
        error_msg = None
        http_status = 200

        try:
            await self._simulate_network()
            submission = self._faktur_submissions.get(faktur_id)
            if not submission:
                raise ValueError(f"Faktur {faktur_id} not found")

            status = FakturStatus(submission["status"])
            approval_code = submission.get("approval_code")
            result = FakturResponse(
                faktur_id=faktur_id,
                status=status,
                approval_code=approval_code,
                rejection_reason=submission.get("rejection_reason"),
                qr_code_url=submission.get("qr_code_url"),
                response_code="00",
                response_message="OK",
                timestamp=datetime.now(UTC),
            )
            success = True
            response_payload = result.to_dict()
        except Exception as e:
            error_msg = str(e)
            http_status = 404
            result = FakturResponse(
                faktur_id=faktur_id,
                status=FakturStatus.REJECTED,
                approval_code=None,
                rejection_reason=error_msg,
                qr_code_url=None,
                response_code="99",
                response_message=f"NOT_FOUND: {error_msg}",
                timestamp=datetime.now(UTC),
            )
        finally:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            await self._log_request(
                f"/v2/faktur/keluaran/{faktur_id}/status",
                request_payload,
                response_payload,
                http_status,
                success,
                error_msg,
                duration_ms,
                retry_count,
            )
        return result

    async def void_faktur(
        self, faktur_id: str, reason: str, retry_count: int = 0
    ) -> FakturResponse:
        """Membatalkan faktur pajak yang sudah approved."""
        start_time = time.perf_counter()
        try:
            await self._simulate_network()
            submission = self._faktur_submissions.get(faktur_id)
            if not submission:
                raise ValueError("Faktur not found")
            if submission["status"] != FakturStatus.APPROVED.value:
                raise ValueError(f"Cannot void faktur with status {submission['status']}")
            submission["status"] = FakturStatus.VOID.value
            submission["void_reason"] = reason
            submission["voided_at"] = datetime.now(UTC).isoformat()

            result = FakturResponse(
                faktur_id=faktur_id,
                status=FakturStatus.VOID,
                approval_code=submission["approval_code"],
                rejection_reason=None,
                qr_code_url=None,
                response_code="00",
                response_message="FAKTUR_DIBATALKAN",
                timestamp=datetime.now(UTC),
            )
            return result
        except Exception as e:
            return FakturResponse(
                faktur_id=faktur_id,
                status=FakturStatus.REJECTED,
                approval_code=None,
                rejection_reason=str(e),
                qr_code_url=None,
                response_code="99",
                response_message=f"ERROR: {e!s}",
                timestamp=datetime.now(UTC),
            )
        finally:
            pass

    # ==================== NTPN VALIDATION ====================

    async def validate_ntpn(
        self, ntpn: str, amount: Decimal, payment_date: date, retry_count: int = 0
    ) -> NTPNValidationResponse:
        """Memvalidasi NTPN pembayaran pajak."""
        start_time = time.perf_counter()
        request_payload = {
            "ntpn": ntpn,
            "amount": float(amount),
            "payment_date": payment_date.isoformat(),
        }
        response_payload = {}
        success = False
        error_msg = None
        http_status = 200

        try:
            await self._simulate_network()
            data = self._ntpn_cache.get(ntpn)
            if not data:
                # Simulate validation with DJP
                # For demo, any NTPN starting with "1" and length 16 is valid
                if len(ntpn) == 16 and ntpn.startswith("1"):
                    data = {
                        "valid": True,
                        "amount": amount,
                        "payment_date": payment_date,
                        "taxpayer_name": "PT ACCOUNTING MAJU BERSAMA",
                    }
                    self._ntpn_cache[ntpn] = data
                else:
                    data = {
                        "valid": False,
                        "amount": Decimal(0),
                        "payment_date": payment_date,
                        "taxpayer_name": None,
                    }
            valid = data["valid"]
            if valid:
                # Optionally check amount and date matching
                if abs(data["amount"] - amount) > Decimal("0.01"):
                    valid = False
                if data["payment_date"] != payment_date:
                    valid = False

            result = NTPNValidationResponse(
                ntpn=ntpn,
                valid=valid,
                amount=data["amount"],
                payment_date=data["payment_date"],
                taxpayer_name=data.get("taxpayer_name"),
                response_code="00" if valid else "01",
                response_message="VALID" if valid else "INVALID",
            )
            success = True
            response_payload = result.to_dict()
        except Exception as e:
            error_msg = str(e)
            http_status = 500
            result = NTPNValidationResponse(
                ntpn=ntpn,
                valid=False,
                amount=Decimal(0),
                payment_date=payment_date,
                taxpayer_name=None,
                response_code="99",
                response_message=f"ERROR: {error_msg}",
            )
        finally:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            await self._log_request(
                "/v2/ntpn/validate",
                request_payload,
                response_payload,
                http_status,
                success,
                error_msg,
                duration_ms,
                retry_count,
            )
        return result

    # ==================== SPT SUBMISSION ====================

    async def submit_spt_masa(
        self, spt_data: dict[str, Any], jenis_spt: str, retry_count: int = 0
    ) -> SPTPResponse:
        """
        Mengirim SPT Masa (PPN, PPh 21, PPh 23) ke Coretax.
        jenis_spt: "PPN", "PPH21", "PPH23"
        """
        start_time = time.perf_counter()
        request_payload = spt_data.copy()
        response_payload = {}
        success = False
        error_msg = None
        http_status = 200
        endpoint = {
            "PPN": "/v2/spt/ppn/masa",
            "PPH21": "/v2/spt/pph21/masa",
            "PPH23": "/v2/spt/pph23/masa",
        }.get(jenis_spt, "/v2/spt/masa")

        try:
            await self._simulate_network()
            required_fields = (
                ["masa_pajak", "tahun_pajak", "jumlah_bruto", "ppn_terutang"]
                if jenis_spt == "PPN"
                else ["masa_pajak", "tahun_pajak", "jumlah_bruto"]
            )
            for field in required_fields:
                if field not in spt_data:
                    raise ValueError(f"Missing required field: {field}")

            spt_id = f"SPT-{jenis_spt}-{spt_data.get('masa_pajak')}-{spt_data.get('tahun_pajak')}-{secrets.token_hex(4)}"
            bukti_penerimaan = f"BPE-{spt_id[-12:]}"
            submission = {
                "spt_id": spt_id,
                "jenis": jenis_spt,
                "status": SPTStatus.APPROVED.value,
                "data": spt_data,
                "submitted_at": datetime.now(UTC),
                "bukti_penerimaan": bukti_penerimaan,
            }
            self._spt_submissions[spt_id] = submission

            result = SPTPResponse(
                spt_id=spt_id,
                status=SPTStatus.APPROVED,
                bukti_penerimaan=bukti_penerimaan,
                rejection_reason=None,
                response_code="00",
                response_message="SPT_DITERIMA",
                timestamp=datetime.now(UTC),
            )
            success = True
            response_payload = result.to_dict()
        except Exception as e:
            error_msg = str(e)
            http_status = 400
            result = SPTPResponse(
                spt_id="",
                status=SPTStatus.REJECTED,
                bukti_penerimaan=None,
                rejection_reason=error_msg,
                response_code="99",
                response_message=f"ERROR: {error_msg}",
                timestamp=datetime.now(UTC),
            )
        finally:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            await self._log_request(
                endpoint,
                request_payload,
                response_payload,
                http_status,
                success,
                error_msg,
                duration_ms,
                retry_count,
            )
        return result

    async def submit_spt_tahunan(
        self, spt_data: dict[str, Any], retry_count: int = 0
    ) -> SPTPResponse:
        """Mengirim SPT Tahunan Badan/OP."""
        start_time = time.perf_counter()
        try:
            await self._simulate_network()
            spt_id = f"SPT-TH-{spt_data.get('tahun_pajak')}-{secrets.token_hex(6)}"
            bukti_penerimaan = f"BPE-{spt_id[-12:]}"
            submission = {
                "spt_id": spt_id,
                "jenis": "TAHUNAN",
                "status": SPTStatus.APPROVED.value,
                "data": spt_data,
                "submitted_at": datetime.now(UTC),
                "bukti_penerimaan": bukti_penerimaan,
            }
            self._spt_submissions[spt_id] = submission
            result = SPTPResponse(
                spt_id=spt_id,
                status=SPTStatus.APPROVED,
                bukti_penerimaan=bukti_penerimaan,
                rejection_reason=None,
                response_code="00",
                response_message="SPT_DITERIMA",
                timestamp=datetime.now(UTC),
            )
            return result
        except Exception as e:
            return SPTPResponse(
                spt_id="",
                status=SPTStatus.REJECTED,
                bukti_penerimaan=None,
                rejection_reason=str(e),
                response_code="99",
                response_message=f"ERROR: {e!s}",
                timestamp=datetime.now(UTC),
            )
        finally:
            pass

    async def get_status_pelaporan(self, kode_identifikasi: str, retry_count: int = 0) -> str:
        """Cek status pelaporan (faktur atau SPT)."""
        try:
            await self._simulate_network()
            if kode_identifikasi.startswith("FK-"):
                faktur = self._faktur_submissions.get(kode_identifikasi)
                if faktur:
                    return faktur["status"]
                return "NOT_FOUND"
            elif kode_identifikasi.startswith("SPT-"):
                spt = self._spt_submissions.get(kode_identifikasi)
                if spt:
                    return spt["status"]
                return "NOT_FOUND"
            else:
                return "UNKNOWN"
        except Exception:
            return "ERROR"

    # ==================== WEBHOOK (INBOUND) ====================

    def register_webhook(
        self, event_type: str, callback: Callable[[dict[str, Any]], Awaitable[None]]
    ):
        """Register webhook handler for DJP callbacks (e.g., faktur approved, SPT approved)."""
        if event_type not in self._webhook_subscribers:
            self._webhook_subscribers[event_type] = []
        self._webhook_subscribers[event_type].append(callback)

    async def simulate_webhook(self, event_type: str, payload: dict[str, Any]):
        """Simulate incoming webhook from DJP."""
        if event_type in self._webhook_subscribers:
            for callback in self._webhook_subscribers[event_type]:
                try:
                    await callback(payload)
                except Exception as e:
                    logger.error(f"Webhook callback error: {e}")
        await self._log_audit(
            "WEBHOOK_RECEIVED", event_type, payload.get("id", "unknown"), {"payload": payload}
        )

    # ==================== BATCH SUBMISSION ====================

    async def batch_submit_faktur(self, faktur_list: list[dict[str, Any]]) -> list[FakturResponse]:
        """Submit multiple faktur in parallel (batch)."""
        tasks = [self.submit_faktur_pajak(f) for f in faktur_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        responses = []
        for r in results:
            if isinstance(r, Exception):
                responses.append(
                    FakturResponse(
                        faktur_id="",
                        status=FakturStatus.REJECTED,
                        approval_code=None,
                        rejection_reason=str(r),
                        qr_code_url=None,
                        response_code="99",
                        response_message=f"BATCH_ERROR: {r!s}",
                        timestamp=datetime.now(UTC),
                    )
                )
            else:
                responses.append(r)
        return responses

    # ==================== MONITORING & ADMIN ====================

    async def get_dashboard(self) -> dict[str, Any]:
        """Get monitoring dashboard data."""
        faktur_submitted = len(self._faktur_submissions)
        faktur_approved = sum(
            1
            for f in self._faktur_submissions.values()
            if f["status"] == FakturStatus.APPROVED.value
        )
        spt_submitted = len(self._spt_submissions)
        spt_approved = sum(
            1 for s in self._spt_submissions.values() if s["status"] == SPTStatus.APPROVED.value
        )
        total_requests = len(self._request_logs)
        success_requests = sum(1 for log in self._request_logs if log.success)
        return {
            "status": self._health_status,
            "faktur_submitted": faktur_submitted,
            "faktur_approved": faktur_approved,
            "spt_submitted": spt_submitted,
            "spt_approved": spt_approved,
            "total_api_requests": total_requests,
            "success_rate": (success_requests / total_requests * 100)
            if total_requests > 0
            else 100,
            "nsfp_pools": {
                f"{tahun:04d}-{bulan:02d}": len(pool["remaining"])
                for (tahun, bulan), pool in self._nsfp_allocations.items()
            },
            "webhook_subscribers": list(self._webhook_subscribers.keys()),
        }

    async def get_request_logs(self, limit: int = 100, offset: int = 0) -> list[CoretaxRequestLog]:
        return self._request_logs[offset : offset + limit]

    async def set_simulation_params(self, delay_ms: int = 50, failure_rate: float = 0.0):
        """Adjust simulation parameters for testing."""
        self._simulated_delay_ms = max(0, delay_ms)
        self._failure_rate = max(0.0, min(1.0, failure_rate))

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": self._health_status,
            "simulated_delay_ms": self._simulated_delay_ms,
            "failure_rate": self._failure_rate,
            "total_requests": len(self._request_logs),
            "base_url": self._base_url,
        }


# For backward compatibility, keep alias
CoretaxPort = CoreTaxPort


__all__ = [
    "CoreTaxPort",
    "CoretaxEndpoint",
    "CoretaxPort",
    "CoretaxRequestLog",
    "FakturResponse",
    "FakturStatus",
    "NSFPResponse",
    "NTPNValidationResponse",
    "SPTPResponse",
    "SPTStatus",
    "TaxAuthorityCoretaxPort",
    "TaxSubmissionType",     
    "TaxStatus",              
    "SubmissionResponse",
]