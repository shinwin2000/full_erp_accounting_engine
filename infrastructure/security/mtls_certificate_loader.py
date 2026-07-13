#!/usr/bin/env python3
"""
Module: mtls_certificate_loader.py
Layer: Infrastructure (Security)
Responsibility: Memuat dan mengelola sertifikat untuk mTLS (mutual TLS)
               komunikasi antar service. Mendukung loading certificate dari
               file, Vault, atau HSM. Juga menyediakan fungsi untuk reload
               certificate secara periodik (hot reload) tanpa restart service.
Dependencies:
- ssl, asyncio, logging, pathlib
- cryptography.x509
- infrastructure.security.securitykey_management_vault (optional)
- config.loader_yaml
- infrastructure.telemetry.alert_manager_router
Audit: Setiap loading certificate dicatat. Certificate expiry mendekati
       batas akan memicu alert.
"""

from __future__ import annotations

import asyncio
import ssl
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles  # <-- Tambahan untuk async file I/O
import cryptography.x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_CHECK_INTERVAL_HOURS = 24  # Check certificate expiry daily
EXPIRY_WARNING_DAYS = 30  # Alert when certificate expires in less than 30 days
EXPIRY_CRITICAL_DAYS = 7  # Critical alert when less than 7 days

# ============================================================================
# EXCEPTIONS
# ============================================================================


class CertificateLoadError(Exception):
    """Base exception untuk certificate loading."""

    pass


class CertificateNotFoundError(CertificateLoadError):
    """Certificate file tidak ditemukan."""

    pass


class CertificateExpiredError(CertificateLoadError):
    """Certificate sudah expired."""

    pass


# ============================================================================
# CERTIFICATE LOADER
# ============================================================================


class MTLSClientCertificateLoader:
    """
    Loader untuk mTLS certificate.

    Fitur:
    - Load certificate dari file (PEM)
    - Load dari Vault (optional)
    - Periodik check expiry
    - Hot reload certificate
    - Create SSL context untuk server/client
    """

    def __init__(self, config_path: str = "config_files/security_config.yaml"):
        self.config = self._load_config(config_path)
        self._cert_path: Path | None = None
        self._key_path: Path | None = None
        self._ca_cert_path: Path | None = None
        self._cert: cryptography.x509.Certificate | None = None
        self._private_key: Any | None = None
        self._ssl_context: ssl.SSLContext | None = None
        self._last_reload: datetime | None = None
        self._reload_task: asyncio.Task | None = None
        self._running = False
        self._load_paths()
        # Untuk menyimpan task alert agar tidak orphan
        self._alert_tasks: list[asyncio.Task] = []

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            return config.get("mtls", {})
        except Exception as e:
            logger.warning(f"Failed to load mTLS config, using defaults: {e}")
            return {}

    def _load_paths(self):
        """Load certificate file paths from config."""
        mtls_config = self.config
        cert_file = mtls_config.get("cert_file", "/secrets/mtls/client.crt")
        key_file = mtls_config.get("key_file", "/secrets/mtls/client.key")
        ca_cert_file = mtls_config.get("ca_cert_file", "/secrets/mtls/ca.crt")

        self._cert_path = Path(cert_file)
        self._key_path = Path(key_file)
        self._ca_cert_path = Path(ca_cert_file)

    # ========================================================================
    # PERBAIKAN: load_certificate menggunakan aiofiles
    # ========================================================================
    async def load_certificate(self, hot_reload: bool = False) -> tuple[bytes, bytes, bytes]:
        """
        Load certificate, private key, and CA certificate.

        Returns:
            Tuple of (cert_pem_bytes, key_pem_bytes, ca_pem_bytes)
        """
        try:
            # Load certificate dengan aiofiles
            if not self._cert_path.exists():
                raise CertificateNotFoundError(f"Certificate not found: {self._cert_path}")

            async with aiofiles.open(self._cert_path, "rb") as f:
                cert_pem = await f.read()

            # Load private key
            if not self._key_path.exists():
                raise CertificateNotFoundError(f"Private key not found: {self._key_path}")

            async with aiofiles.open(self._key_path, "rb") as f:
                key_pem = await f.read()

            # Load CA certificate
            ca_pem = b""
            if self._ca_cert_path and self._ca_cert_path.exists():
                async with aiofiles.open(self._ca_cert_path, "rb") as f:
                    ca_pem = await f.read()

            # Parse certificate (blocking cryptography, jalankan di thread pool)
            def _parse_sync(cert_data, key_data):
                cert = cryptography.x509.load_pem_x509_certificate(cert_data, default_backend())
                private_key = serialization.load_pem_private_key(
                    key_data, password=None, backend=default_backend()
                )
                return cert, private_key

            self._cert, self._private_key = await asyncio.to_thread(_parse_sync, cert_pem, key_pem)

            # Check expiry (async)
            await self._check_certificate_expiry()

            if hot_reload:
                self._last_reload = datetime.now(UTC)
                # Create SSL context (blocking, di-thread)
                self._ssl_context = await asyncio.to_thread(self._create_ssl_context_sync)
                logger.info("Certificate hot-reloaded")
            else:
                logger.info(f"Certificate loaded from {self._cert_path}")

            return cert_pem, key_pem, ca_pem

        except CertificateNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to load certificate: {e}")
            raise CertificateLoadError(f"Certificate loading failed: {e}") from e

    async def _check_certificate_expiry(self) -> None:
        """Check certificate expiry and trigger alerts if needed."""
        if not self._cert:
            return

        expiry_date = self._cert.not_valid_after_utc
        days_until_expiry = (expiry_date - datetime.now(UTC)).days

        logger.info(f"Certificate expires in {days_until_expiry} days")

        if days_until_expiry <= EXPIRY_CRITICAL_DAYS:
            task = asyncio.create_task(
                trigger_alert(
                    title="Certificate Expiring Critically",
                    message=f"mTLS certificate expires in {days_until_expiry} days on {expiry_date}",
                    severity="critical",
                    source="MTLSClientCertificateLoader",
                )
            )
            self._alert_tasks.append(task)
            # Clean up completed tasks periodically
            self._alert_tasks = [t for t in self._alert_tasks if not t.done()]

        elif days_until_expiry <= EXPIRY_WARNING_DAYS:
            task = asyncio.create_task(
                trigger_alert(
                    title="Certificate Expiring Soon",
                    message=f"mTLS certificate expires in {days_until_expiry} days on {expiry_date}",
                    severity="warning",
                    source="MTLSClientCertificateLoader",
                )
            )
            self._alert_tasks.append(task)
            self._alert_tasks = [t for t in self._alert_tasks if not t.done()]

        if days_until_expiry < 0:
            raise CertificateExpiredError(f"Certificate expired on {expiry_date}")

    def _create_ssl_context_sync(self) -> ssl.SSLContext:
        """Create SSL context for mTLS (synchronous, for thread pool)."""
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

        # Load certificate and key
        context.load_cert_chain(str(self._cert_path), str(self._key_path))

        # Load CA certificate for client verification
        if self._ca_cert_path and self._ca_cert_path.exists():
            context.load_verify_locations(str(self._ca_cert_path))
            context.verify_mode = ssl.CERT_REQUIRED

        return context

    async def get_ssl_context(self) -> ssl.SSLContext:
        """
        Get SSL context for mTLS.
        """
        if self._ssl_context is None:
            await self.load_certificate()
            self._ssl_context = await asyncio.to_thread(self._create_ssl_context_sync)
        return self._ssl_context

    def get_certificate_info(self) -> dict[str, Any]:
        """
        Get certificate information.
        """
        if not self._cert:
            return {"loaded": False}

        subject = self._cert.subject
        issuer = self._cert.issuer

        return {
            "loaded": True,
            "subject": str(subject),
            "issuer": str(issuer),
            "serial_number": hex(self._cert.serial_number),
            "not_valid_before": self._cert.not_valid_before_utc.isoformat(),
            "not_valid_after": self._cert.not_valid_after_utc.isoformat(),
            "days_until_expiry": (self._cert.not_valid_after_utc - datetime.now(UTC)).days,
            "last_reload": self._last_reload.isoformat() if self._last_reload else None,
        }

    async def start_expiry_checker(
        self, interval_hours: int = DEFAULT_CHECK_INTERVAL_HOURS
    ) -> None:
        """
        Start periodic certificate expiry checker.
        """
        if self._reload_task is not None:
            logger.warning("Expiry checker already running")
            return

        self._running = True
        self._reload_task = asyncio.create_task(self._expiry_check_loop(interval_hours))
        logger.info(f"Certificate expiry checker started (interval: {interval_hours}h)")

    async def _expiry_check_loop(self, interval_hours: int) -> None:
        """
        Background loop for certificate expiry checking.
        """
        while self._running:
            try:
                await asyncio.sleep(interval_hours * 3600)

                # Reload certificate to check expiry (using aiofiles)
                if self._cert_path and self._cert_path.exists():
                    async with aiofiles.open(self._cert_path, "rb") as f:
                        cert_pem = await f.read()

                    # Parse certificate (blocking, thread pool)
                    def _parse_sync(cert_data):
                        return cryptography.x509.load_pem_x509_certificate(cert_data, default_backend())

                    self._cert = await asyncio.to_thread(_parse_sync, cert_pem)
                    await self._check_certificate_expiry()

                    # If certificate was renewed, also reload SSL context
                    self._ssl_context = await asyncio.to_thread(self._create_ssl_context_sync)
                    self._last_reload = datetime.now(UTC)
                    logger.info("Certificate expiry check completed, context reloaded if needed")

            except asyncio.CancelledError:
                logger.debug("Certificate expiry checker loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in certificate expiry checker: {e}")

    async def stop_expiry_checker(self) -> None:
        """
        Stop periodic expiry checker.
        """
        self._running = False
        if self._reload_task:
            self._reload_task.cancel()
            try:
                await self._reload_task
            except asyncio.CancelledError:
                logger.debug("Certificate expiry checker task cancelled during stop")
                # Expected cancellation; continue
            self._reload_task = None
        logger.info("Certificate expiry checker stopped")

    async def reload(self) -> None:
        """
        Manually reload certificate (hot reload).
        """
        await self.load_certificate(hot_reload=True)
        logger.info("Certificate manually reloaded")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_certificate_loader: MTLSClientCertificateLoader | None = None


async def get_mtls_certificate_loader() -> MTLSClientCertificateLoader:
    """Get singleton instance of MTLSClientCertificateLoader."""
    global _certificate_loader
    if _certificate_loader is None:
        _certificate_loader = MTLSClientCertificateLoader()
    return _certificate_loader


async def start_certificate_expiry_checker() -> None:
    """Start certificate expiry checker."""
    loader = await get_mtls_certificate_loader()
    await loader.start_expiry_checker()


async def stop_certificate_expiry_checker() -> None:
    """Stop certificate expiry checker."""
    global _certificate_loader
    if _certificate_loader:
        await _certificate_loader.stop_expiry_checker()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CertificateExpiredError",
    "CertificateLoadError",
    "CertificateNotFoundError",
    "MTLSClientCertificateLoader",
    "get_mtls_certificate_loader",
    "start_certificate_expiry_checker",
    "stop_certificate_expiry_checker",
]
