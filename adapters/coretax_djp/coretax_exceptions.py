#!/usr/bin/env python3
"""
Module: coretax_exceptions.py
Layer: Adapters (Coretax DJP)
Responsibility: Mendefinisikan semua exception yang terkait dengan integrasi
               Coretax DJP. Exception dibagi dalam kategori: authentication,
               validation, network, rate limiting, business logic, dan system.
               Setiap exception membawa metadata (status code, request_id, retryable)
               untuk memudahkan penanganan dan retry logic.

Method Standards (ERP):
- Exception hierarchy sesuai dengan standar ERP
- Setiap exception memiliki metadata untuk debugging
- Support untuk exception chaining
- Method untuk menentukan apakah perlu retry
- Method untuk mendapatkan status code HTTP yang sesuai
- Method untuk serialisasi ke JSON untuk API response
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

# ============================================================================
# BASE EXCEPTION
# ============================================================================


class CoretaxException(Exception):
    """
    Base exception untuk semua error yang terkait Coretax.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        request_id: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        self.retryable = retryable
        self.details = details or {}
        self.cause = cause
        self.timestamp = datetime.now()

    def __str__(self) -> str:
        base = self.message
        if self.status_code:
            base = f"[HTTP {self.status_code}] {base}"
        if self.request_id:
            base = f"{base} (request_id: {self.request_id})"
        if self.cause:
            base = f"{base} - Caused by: {self.cause!s}"
        return base

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for JSON response."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "status_code": self.status_code,
            "request_id": self.request_id,
            "retryable": self.retryable,
            "details": self.details,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

    def should_retry(self) -> bool:
        """Determine if the operation should be retried."""
        return self.retryable

    def get_http_status(self) -> int:
        """Get HTTP status code for API response."""
        return self.status_code if self.status_code else 500


# ============================================================================
# AUTHENTICATION EXCEPTIONS
# ============================================================================


class CoretaxAuthError(CoretaxException):
    """Error autentikasi ke Coretax (invalid client_id/secret, token expired, dll)."""

    def __init__(self, message: str, status_code: int = 401, **kwargs):
        super().__init__(message, status_code=status_code, retryable=False, **kwargs)


class CoretaxTokenExpiredError(CoretaxAuthError):
    """Token Coretax sudah expired dan tidak dapat di-refresh."""

    def __init__(
        self, message: str = "Coretax token expired", token_expiry: float | None = None, **kwargs
    ):
        super().__init__(message, **kwargs)
        self.token_expiry = token_expiry
        self.details["token_expiry"] = token_expiry


class CoretaxInvalidCredentialsError(CoretaxAuthError):
    """Client ID atau secret tidak valid."""

    def __init__(self, message: str = "Invalid Coretax credentials", **kwargs):
        super().__init__(message, **kwargs)


class CoretaxTokenRefreshError(CoretaxAuthError):
    """Gagal merefresh token Coretax."""

    def __init__(
        self,
        message: str = "Failed to refresh Coretax token",
        original_error: str | None = None,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.original_error = original_error
        self.details["original_error"] = original_error


class CoretaxMissingCredentialsError(CoretaxAuthError):
    """Kredensial Coretax tidak ditemukan di konfigurasi."""

    def __init__(
        self,
        message: str = "Coretax credentials not configured",
        missing_fields: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.missing_fields = missing_fields or []
        self.details["missing_fields"] = self.missing_fields


# ============================================================================
# VALIDATION EXCEPTIONS
# ============================================================================


class CoretaxValidationError(CoretaxException):
    """Data yang dikirim ke Coretax tidak valid (schema validation failed)."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        validation_errors: list[dict[str, Any]] | None = None,
        **kwargs,
    ):
        super().__init__(message, status_code=422, retryable=False, **kwargs)
        self.field = field
        self.validation_errors = validation_errors or []
        self.details["field"] = field
        self.details["validation_errors"] = self.validation_errors


class CoretaxInvalidNPWPError(CoretaxValidationError):
    """Format NPWP tidak valid."""

    def __init__(self, npwp: str, **kwargs):
        super().__init__(f"Invalid NPWP format: {npwp}", field="npwp", **kwargs)
        self.npwp = npwp
        self.details["npwp"] = npwp


class CoretaxInvalidFakturXMLError(CoretaxValidationError):
    """XML faktur tidak sesuai skema DJP."""

    def __init__(self, message: str, xml_errors: list[str] | None = None, **kwargs):
        super().__init__(f"Invalid faktur XML: {message}", field="xml", **kwargs)
        self.xml_errors = xml_errors or []
        self.details["xml_errors"] = self.xml_errors


class CoretaxInvalidNTPNFormatError(CoretaxValidationError):
    """Format NTPN tidak valid (harus 16 digit)."""

    def __init__(self, ntpn: str, **kwargs):
        super().__init__(f"Invalid NTPN format: {ntpn}. Must be 16 digits.", field="ntpn", **kwargs)
        self.ntpn = ntpn
        self.details["ntpn"] = ntpn[:8] + "..." if ntpn else None


class CoretaxInvalidNSFPFormatError(CoretaxValidationError):
    """Format NSFP tidak valid (harus 8 digit)."""

    def __init__(self, nsfp: str, **kwargs):
        super().__init__(f"Invalid NSFP format: {nsfp}. Must be 8 digits.", field="nsfp", **kwargs)
        self.nsfp = nsfp
        self.details["nsfp"] = nsfp


class CoretaxInvalidDateRangeError(CoretaxValidationError):
    """Rentang tanggal tidak valid."""

    def __init__(
        self, message: str, start_date: str | None = None, end_date: str | None = None, **kwargs
    ):
        super().__init__(message, **kwargs)
        self.start_date = start_date
        self.end_date = end_date
        self.details["start_date"] = start_date
        self.details["end_date"] = end_date


class CoretaxMissingRequiredFieldError(CoretaxValidationError):
    """Field wajib tidak diisi."""

    def __init__(self, missing_fields: list[str], **kwargs):
        super().__init__(f"Missing required fields: {', '.join(missing_fields)}", **kwargs)
        self.missing_fields = missing_fields
        self.details["missing_fields"] = missing_fields


# ============================================================================
# NETWORK & RATE LIMITING EXCEPTIONS
# ============================================================================


class CoretaxNetworkError(CoretaxException):
    """Network error saat menghubungi Coretax API (timeout, connection refused)."""

    def __init__(self, message: str, original_error: str | None = None, **kwargs):
        super().__init__(message, retryable=True, **kwargs)
        self.original_error = original_error
        self.details["original_error"] = original_error


class CoretaxTimeoutError(CoretaxNetworkError):
    """Timeout saat memanggil Coretax API."""

    def __init__(
        self, message: str = "Coretax API timeout", timeout_seconds: float | None = None, **kwargs
    ):
        super().__init__(message, **kwargs)
        self.timeout_seconds = timeout_seconds
        self.details["timeout_seconds"] = timeout_seconds


class CoretaxConnectionError(CoretaxNetworkError):
    """Koneksi ke Coretax API gagal."""

    def __init__(
        self, message: str = "Failed to connect to Coretax API", url: str | None = None, **kwargs
    ):
        super().__init__(message, **kwargs)
        self.url = url
        self.details["url"] = url


class CoretaxRateLimitError(CoretaxException):
    """Rate limit Coretax terlampaui."""

    def __init__(
        self,
        message: str = "Coretax rate limit exceeded",
        retry_after: int | None = None,
        limit: int | None = None,
        remaining: int | None = None,
        **kwargs,
    ):
        super().__init__(message, status_code=429, retryable=True, **kwargs)
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining
        self.details["retry_after"] = retry_after
        self.details["limit"] = limit
        self.details["remaining"] = remaining

    def get_retry_delay(self) -> int:
        """Get recommended retry delay in seconds."""
        return self.retry_after or 60


class CoretaxServiceUnavailableError(CoretaxException):
    """Layanan Coretax sedang tidak tersedia."""

    def __init__(
        self, message: str = "Coretax service unavailable", retry_after: int | None = None, **kwargs
    ):
        super().__init__(message, status_code=503, retryable=True, **kwargs)
        self.retry_after = retry_after
        self.details["retry_after"] = retry_after


# ============================================================================
# BUSINESS LOGIC EXCEPTIONS
# ============================================================================


class CoretaxBusinessError(CoretaxException):
    """Error bisnis dari Coretax (faktur sudah approval, SPT sudah dilapor, dll)."""

    def __init__(
        self, message: str, status_code: int = 400, error_code: str | None = None, **kwargs
    ):
        super().__init__(message, status_code=status_code, retryable=False, **kwargs)
        self.error_code = error_code
        self.details["error_code"] = error_code


class CoretaxFakturAlreadyExistsError(CoretaxBusinessError):
    """Faktur dengan nomor yang sama sudah ada di Coretax."""

    def __init__(self, faktur_number: str, **kwargs):
        super().__init__(f"Faktur {faktur_number} already exists in Coretax", **kwargs)
        self.faktur_number = faktur_number
        self.details["faktur_number"] = faktur_number


class CoretaxFakturNotFoundError(CoretaxBusinessError):
    """Faktur tidak ditemukan di Coretax."""

    def __init__(self, faktur_number: str, **kwargs):
        super().__init__(f"Faktur {faktur_number} not found in Coretax", status_code=404, **kwargs)
        self.faktur_number = faktur_number
        self.details["faktur_number"] = faktur_number


class CoretaxFakturCannotCancelError(CoretaxBusinessError):
    """Faktur tidak dapat dibatalkan karena status tidak sesuai."""

    def __init__(
        self, faktur_number: str, current_status: str, required_status: str | None = None, **kwargs
    ):
        message = f"Faktur {faktur_number} with status {current_status} cannot be cancelled"
        if required_status:
            message += f". Status must be {required_status}"
        super().__init__(message, **kwargs)
        self.faktur_number = faktur_number
        self.current_status = current_status
        self.required_status = required_status
        self.details["faktur_number"] = faktur_number
        self.details["current_status"] = current_status
        self.details["required_status"] = required_status


class CoretaxFakturCannotApproveError(CoretaxBusinessError):
    """Faktur tidak dapat disetujui karena status tidak sesuai."""

    def __init__(self, faktur_number: str, current_status: str, **kwargs):
        super().__init__(
            f"Faktur {faktur_number} with status {current_status} cannot be approved", **kwargs
        )
        self.faktur_number = faktur_number
        self.current_status = current_status
        self.details["faktur_number"] = faktur_number
        self.details["current_status"] = current_status


class CoretaxSPTNotFoundError(CoretaxBusinessError):
    """SPT tidak ditemukan di Coretax."""

    def __init__(self, spt_number: str, tracking_id: str | None = None, **kwargs):
        identifier = spt_number or tracking_id or "unknown"
        super().__init__(f"SPT {identifier} not found", status_code=404, **kwargs)
        self.spt_number = spt_number
        self.tracking_id = tracking_id
        self.details["spt_number"] = spt_number
        self.details["tracking_id"] = tracking_id


class CoretaxSPTAlreadySubmittedError(CoretaxBusinessError):
    """SPT sudah pernah dikirim."""

    def __init__(self, spt_number: str, submission_date: str | None = None, **kwargs):
        super().__init__(f"SPT {spt_number} has already been submitted", **kwargs)
        self.spt_number = spt_number
        self.submission_date = submission_date
        self.details["spt_number"] = spt_number
        self.details["submission_date"] = submission_date


class CoretaxBupotNotFoundError(CoretaxBusinessError):
    """e-Bupot tidak ditemukan."""

    def __init__(self, bupot_number: str, coretax_id: str | None = None, **kwargs):
        identifier = bupot_number or coretax_id or "unknown"
        super().__init__(f"e-Bupot {identifier} not found", status_code=404, **kwargs)
        self.bupot_number = bupot_number
        self.coretax_id = coretax_id
        self.details["bupot_number"] = bupot_number
        self.details["coretax_id"] = coretax_id


class CoretaxBupotAlreadyExistsError(CoretaxBusinessError):
    """e-Bupot sudah ada."""

    def __init__(self, bupot_number: str, **kwargs):
        super().__init__(f"e-Bupot {bupot_number} already exists", **kwargs)
        self.bupot_number = bupot_number
        self.details["bupot_number"] = bupot_number


class CoretaxNSFPExhaustedError(CoretaxBusinessError):
    """NSFP habis untuk periode yang diminta."""

    def __init__(self, npwp: str, tahun: int, bulan: int, remaining: int = 0, **kwargs):
        super().__init__(
            f"NSFP exhausted for {npwp} {tahun}-{bulan:02d}. Remaining: {remaining}",
            status_code=422,
            **kwargs,
        )
        self.npwp = npwp
        self.tahun = tahun
        self.bulan = bulan
        self.remaining = remaining
        self.details["npwp"] = npwp
        self.details["tahun"] = tahun
        self.details["bulan"] = bulan
        self.details["remaining"] = remaining


class CoretaxNSFPNotFoundError(CoretaxBusinessError):
    """NSFP yang diminta tidak tersedia."""

    def __init__(self, nsfp: str, **kwargs):
        super().__init__(f"NSFP {nsfp} not found or already used", status_code=404, **kwargs)
        self.nsfp = nsfp
        self.details["nsfp"] = nsfp


class CoretaxNSFPAlreadyUsedError(CoretaxBusinessError):
    """NSFP sudah digunakan."""

    def __init__(self, nsfp: str, faktur_number: str | None = None, **kwargs):
        message = f"NSFP {nsfp} already used"
        if faktur_number:
            message += f" on faktur {faktur_number}"
        super().__init__(message, **kwargs)
        self.nsfp = nsfp
        self.faktur_number = faktur_number
        self.details["nsfp"] = nsfp
        self.details["faktur_number"] = faktur_number


class CoretaxEMeteraiInvalidError(CoretaxBusinessError):
    """e-Meterai tidak valid."""

    def __init__(self, meterai_code: str, reason: str, **kwargs):
        masked_code = meterai_code[:8] + "..." if len(meterai_code) > 8 else meterai_code
        super().__init__(f"e-Meterai {masked_code} invalid: {reason}", **kwargs)
        self.meterai_code = meterai_code
        self.reason = reason
        self.details["meterai_code"] = masked_code
        self.details["reason"] = reason


class CoretaxEMeteraiAlreadyUsedError(CoretaxBusinessError):
    """e-Meterai sudah digunakan."""

    def __init__(self, meterai_code: str, document_id: str | None = None, **kwargs):
        masked_code = meterai_code[:8] + "..." if len(meterai_code) > 8 else meterai_code
        message = f"e-Meterai {masked_code} already used"
        if document_id:
            message += f" on document {document_id}"
        super().__init__(message, **kwargs)
        self.meterai_code = meterai_code
        self.document_id = document_id
        self.details["meterai_code"] = masked_code
        self.details["document_id"] = document_id


class CoretaxEMeteraiExpiredError(CoretaxBusinessError):
    """e-Meterai sudah kadaluarsa."""

    def __init__(self, meterai_code: str, expiry_date: str | None = None, **kwargs):
        masked_code = meterai_code[:8] + "..." if len(meterai_code) > 8 else meterai_code
        message = f"e-Meterai {masked_code} has expired"
        if expiry_date:
            message += f" on {expiry_date}"
        super().__init__(message, **kwargs)
        self.meterai_code = meterai_code
        self.expiry_date = expiry_date
        self.details["meterai_code"] = masked_code
        self.details["expiry_date"] = expiry_date


class CoretaxNTPNNotFoundError(CoretaxBusinessError):
    """NTPN tidak ditemukan."""

    def __init__(self, ntpn: str, **kwargs):
        masked_ntpn = ntpn[:8] + "..." if len(ntpn) > 8 else ntpn
        super().__init__(f"NTPN {masked_ntpn} not found", status_code=404, **kwargs)
        self.ntpn = ntpn
        self.details["ntpn"] = masked_ntpn


class CoretaxNTPNAlreadyUsedError(CoretaxBusinessError):
    """NTPN sudah digunakan."""

    def __init__(self, ntpn: str, spt_number: str | None = None, **kwargs):
        masked_ntpn = ntpn[:8] + "..." if len(ntpn) > 8 else ntpn
        message = f"NTPN {masked_ntpn} already used"
        if spt_number:
            message += f" for SPT {spt_number}"
        super().__init__(message, **kwargs)
        self.ntpn = ntpn
        self.spt_number = spt_number
        self.details["ntpn"] = masked_ntpn
        self.details["spt_number"] = spt_number


class CoretaxNTPNAmountMismatchError(CoretaxBusinessError):
    """Jumlah pembayaran NTPN tidak sesuai."""

    def __init__(
        self,
        ntpn: str,
        expected_amount: Decimal,
        actual_amount: Decimal,
        **kwargs,
    ):
        masked_ntpn = ntpn[:8] + "..." if len(ntpn) > 8 else ntpn
        super().__init__(
            f"NTPN {masked_ntpn} amount mismatch: expected {expected_amount}, got {actual_amount}",
            **kwargs,
        )
        self.ntpn = ntpn
        self.expected_amount = expected_amount
        self.actual_amount = actual_amount
        self.details["ntpn"] = masked_ntpn
        self.details["expected_amount"] = str(expected_amount)
        self.details["actual_amount"] = str(actual_amount)


class CoretaxPeriodNotOpenError(CoretaxBusinessError):
    """Periode pajak belum dibuka atau sudah ditutup."""

    def __init__(self, tahun: int, bulan: int, status: str = "closed", **kwargs):
        super().__init__(f"Tax period {tahun}-{bulan:02d} is {status}", **kwargs)
        self.tahun = tahun
        self.bulan = bulan
        self.status = status
        self.details["tahun"] = tahun
        self.details["bulan"] = bulan
        self.details["status"] = status


class CoretaxDuplicateSubmissionError(CoretaxBusinessError):
    """Submisi duplikat terdeteksi."""

    def __init__(
        self, entity_type: str, entity_id: str, submission_id: str | None = None, **kwargs
    ):
        message = f"Duplicate {entity_type} submission detected for {entity_id}"
        if submission_id:
            message += f" (submission_id: {submission_id})"
        super().__init__(message, **kwargs)
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.submission_id = submission_id
        self.details["entity_type"] = entity_type
        self.details["entity_id"] = entity_id
        self.details["submission_id"] = submission_id


# ============================================================================
# SYSTEM EXCEPTIONS
# ============================================================================


class CoretaxSystemError(CoretaxException):
    """Error sistem internal Coretax DJP (bukan kesalahan client)."""

    def __init__(self, message: str, status_code: int = 500, error_id: str | None = None, **kwargs):
        super().__init__(message, status_code=status_code, retryable=True, **kwargs)
        self.error_id = error_id
        self.details["error_id"] = error_id


class CoretaxMaintenanceError(CoretaxSystemError):
    """Coretax sedang maintenance."""

    def __init__(
        self,
        message: str = "Coretax DJP is under maintenance",
        maintenance_until: str | None = None,
        **kwargs,
    ):
        super().__init__(message, status_code=503, **kwargs)
        self.maintenance_until = maintenance_until
        self.details["maintenance_until"] = maintenance_until


class CoretaxInternalServerError(CoretaxSystemError):
    """Internal server error dari Coretax."""

    def __init__(self, message: str = "Coretax internal server error", **kwargs):
        super().__init__(message, status_code=500, **kwargs)


class CoretaxBadGatewayError(CoretaxSystemError):
    """Bad gateway dari Coretax."""

    def __init__(self, message: str = "Coretax bad gateway", **kwargs):
        super().__init__(message, status_code=502, **kwargs)


class CoretaxGatewayTimeoutError(CoretaxSystemError):
    """Gateway timeout dari Coretax."""

    def __init__(self, message: str = "Coretax gateway timeout", **kwargs):
        super().__init__(message, status_code=504, **kwargs)


# ============================================================================
# DATA INTEGRITY EXCEPTIONS
# ============================================================================


class CoretaxDataIntegrityError(CoretaxException):
    """Error integritas data antara sistem internal dan Coretax."""

    def __init__(
        self,
        message: str,
        entity_type: str,
        entity_id: str,
        mismatch_details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, status_code=409, retryable=False, **kwargs)
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.mismatch_details = mismatch_details or {}
        self.details["entity_type"] = entity_type
        self.details["entity_id"] = entity_id
        self.details["mismatch_details"] = mismatch_details


class CoretaxHashMismatchError(CoretaxDataIntegrityError):
    """Hash mismatch antara data internal dan Coretax."""

    def __init__(
        self, entity_type: str, entity_id: str, expected_hash: str, actual_hash: str, **kwargs
    ):
        super().__init__(
            f"Hash mismatch for {entity_type} {entity_id}",
            entity_type=entity_type,
            entity_id=entity_id,
            mismatch_details={"expected_hash": expected_hash, "actual_hash": actual_hash},
            **kwargs,
        )
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        self.details["expected_hash"] = expected_hash[:16] + "..."
        self.details["actual_hash"] = actual_hash[:16] + "..."


# ============================================================================
# WEBHOOK EXCEPTIONS
# ============================================================================


class CoretaxWebhookError(CoretaxException):
    """Error saat memproses webhook dari Coretax."""

    def __init__(
        self, message: str, webhook_id: str | None = None, event_type: str | None = None, **kwargs
    ):
        super().__init__(message, **kwargs)
        self.webhook_id = webhook_id
        self.event_type = event_type
        self.details["webhook_id"] = webhook_id
        self.details["event_type"] = event_type


class CoretaxWebhookSignatureError(CoretaxWebhookError):
    """Signature webhook tidak valid."""

    def __init__(
        self, message: str = "Invalid webhook signature", webhook_id: str | None = None, **kwargs
    ):
        super().__init__(message, webhook_id=webhook_id, status_code=401, **kwargs)


class CoretaxWebhookIdempotencyError(CoretaxWebhookError):
    """Error idempotency webhook."""

    def __init__(
        self, message: str, webhook_id: str, already_processed_at: str | None = None, **kwargs
    ):
        super().__init__(message, webhook_id=webhook_id, **kwargs)
        self.already_processed_at = already_processed_at
        self.details["already_processed_at"] = already_processed_at


# ============================================================================
# EXCEPTION MAPPING
# ============================================================================


def map_http_status_to_exception(
    status_code: int,
    response_body: dict[str, Any],
    request_id: str | None = None,
) -> CoretaxException:
    """
    Memetakan HTTP status code dari Coretax ke exception yang sesuai.
    """
    message = response_body.get("message", response_body.get("error", "Unknown error"))
    error_code = response_body.get("code")
    details = response_body.get("details", {})

    if status_code == 400:
        field = details.get("field") or response_body.get("field")
        if "NPWP" in message or "npwp" in message:
            return CoretaxInvalidNPWPError(message, request_id=request_id, details=details)
        elif "faktur" in message.lower() and "already" in message.lower():
            return CoretaxFakturAlreadyExistsError(
                details.get("faktur_number", "unknown"),
                message=message,
                request_id=request_id,
                details=details,
            )
        elif "bupot" in message.lower() and "already" in message.lower():
            return CoretaxBupotAlreadyExistsError(
                details.get("bupot_number", "unknown"),
                message=message,
                request_id=request_id,
                details=details,
            )
        else:
            return CoretaxBusinessError(
                message,
                status_code=status_code,
                error_code=error_code,
                request_id=request_id,
                details=details,
            )

    elif status_code == 401:
        if "token" in message.lower() and "expired" in message.lower():
            return CoretaxTokenExpiredError(message, request_id=request_id, details=details)
        elif "invalid" in message.lower():
            return CoretaxInvalidCredentialsError(message, request_id=request_id, details=details)
        else:
            return CoretaxAuthError(
                message, status_code=status_code, request_id=request_id, details=details
            )

    elif status_code == 403:
        return CoretaxInvalidCredentialsError(message, request_id=request_id, details=details)

    elif status_code == 404:
        resource = details.get("resource") or response_body.get("resource", "")
        if "faktur" in resource.lower():
            return CoretaxFakturNotFoundError(
                details.get("faktur_number", ""), request_id=request_id, details=details
            )
        elif "spt" in resource.lower():
            return CoretaxSPTNotFoundError(
                details.get("spt_number", ""), request_id=request_id, details=details
            )
        elif "bupot" in resource.lower():
            return CoretaxBupotNotFoundError(
                details.get("bupot_number", ""), request_id=request_id, details=details
            )
        elif "nsfp" in resource.lower():
            return CoretaxNSFPNotFoundError(
                details.get("nsfp", ""), request_id=request_id, details=details
            )
        elif "ntpn" in resource.lower():
            return CoretaxNTPNNotFoundError(
                details.get("ntpn", ""), request_id=request_id, details=details
            )
        else:
            return CoretaxBusinessError(
                message, status_code=status_code, request_id=request_id, details=details
            )

    elif status_code == 409:
        return CoretaxDuplicateSubmissionError(
            details.get("entity_type", "unknown"),
            details.get("entity_id", "unknown"),
            request_id=request_id,
            details=details,
        )

    elif status_code == 422:
        field = details.get("field") or response_body.get("field")
        validation_errors = details.get("validation_errors", [])
        return CoretaxValidationError(
            message,
            field=field,
            validation_errors=validation_errors,
            request_id=request_id,
            details=details,
        )

    elif status_code == 429:
        retry_after = details.get("retry_after") or response_body.get("retry_after")
        limit = details.get("limit") or response_body.get("limit")
        remaining = details.get("remaining") or response_body.get("remaining")
        return CoretaxRateLimitError(
            message,
            retry_after=retry_after,
            limit=limit,
            remaining=remaining,
            request_id=request_id,
            details=details,
        )

    elif status_code == 500:
        return CoretaxInternalServerError(message, request_id=request_id, details=details)

    elif status_code == 502:
        return CoretaxBadGatewayError(message, request_id=request_id, details=details)

    elif status_code == 503:
        if "maintenance" in message.lower():
            return CoretaxMaintenanceError(message, request_id=request_id, details=details)
        return CoretaxServiceUnavailableError(message, request_id=request_id, details=details)

    elif status_code == 504:
        return CoretaxGatewayTimeoutError(message, request_id=request_id, details=details)

    elif 500 <= status_code < 600:
        return CoretaxSystemError(
            message, status_code=status_code, request_id=request_id, details=details
        )

    else:
        return CoretaxException(
            message,
            status_code=status_code,
            retryable=status_code >= 500,
            request_id=request_id,
            details=details,
        )


def is_retryable_exception(exception: Exception) -> bool:
    """Check if exception is retryable."""
    if isinstance(exception, CoretaxException):
        return exception.retryable
    return isinstance(exception, httpx.RequestError | asyncio.TimeoutError)


def get_retry_delay(exception: Exception, attempt: int, base_delay: float = 1.0) -> float:
    """Get retry delay based on exception type."""
    if isinstance(exception, CoretaxRateLimitError):
        return float(exception.retry_after) if exception.retry_after else base_delay * (2**attempt)
    if isinstance(exception, CoretaxServiceUnavailableError):
        return float(exception.retry_after) if exception.retry_after else base_delay * (2**attempt)
    return base_delay * (2**attempt)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CoretaxAuthError",
    "CoretaxBadGatewayError",
    "CoretaxBupotAlreadyExistsError",
    "CoretaxBupotNotFoundError",
    "CoretaxBusinessError",
    "CoretaxConnectionError",
    "CoretaxDataIntegrityError",
    "CoretaxDuplicateSubmissionError",
    "CoretaxEMeteraiAlreadyUsedError",
    "CoretaxEMeteraiExpiredError",
    "CoretaxEMeteraiInvalidError",
    "CoretaxException",
    "CoretaxFakturAlreadyExistsError",
    "CoretaxFakturCannotApproveError",
    "CoretaxFakturCannotCancelError",
    "CoretaxFakturNotFoundError",
    "CoretaxGatewayTimeoutError",
    "CoretaxHashMismatchError",
    "CoretaxInternalServerError",
    "CoretaxInvalidCredentialsError",
    "CoretaxInvalidDateRangeError",
    "CoretaxInvalidFakturXMLError",
    "CoretaxInvalidNPWPError",
    "CoretaxInvalidNSFPFormatError",
    "CoretaxInvalidNTPNFormatError",
    "CoretaxMaintenanceError",
    "CoretaxMissingCredentialsError",
    "CoretaxMissingRequiredFieldError",
    "CoretaxNSFPAlreadyUsedError",
    "CoretaxNSFPExhaustedError",
    "CoretaxNSFPNotFoundError",
    "CoretaxNTPNAlreadyUsedError",
    "CoretaxNTPNAmountMismatchError",
    "CoretaxNTPNNotFoundError",
    "CoretaxNetworkError",
    "CoretaxPeriodNotOpenError",
    "CoretaxRateLimitError",
    "CoretaxSPTAlreadySubmittedError",
    "CoretaxSPTNotFoundError",
    "CoretaxServiceUnavailableError",
    "CoretaxSystemError",
    "CoretaxTimeoutError",
    "CoretaxTokenExpiredError",
    "CoretaxTokenRefreshError",
    "CoretaxValidationError",
    "CoretaxWebhookError",
    "CoretaxWebhookIdempotencyError",
    "CoretaxWebhookSignatureError",
    "get_retry_delay",
    "is_retryable_exception",
    "map_http_status_to_exception",
]
