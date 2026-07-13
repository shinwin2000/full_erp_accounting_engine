#!/usr/bin/env python3
"""
Module: mtls_certificate_renewer.py
Layer: Infrastructure (Security)
Responsibility: Memperbarui (renew) sertifikat mTLS secara otomatis sebelum
               masa berlaku habis. Mendukung renewal dengan menggunakan CSR
               (Certificate Signing Request) ke internal CA atau API eksternal.
               Juga mendukung integration dengan Vault PKI atau cert-manager.
Dependencies:
- asyncio, logging, subprocess, cryptography
- infrastructure.security.mtls_certificate_loader (MTLSClientCertificateLoader)
- infrastructure.telemetry.alert_manager_router
- config.loader_yaml
Audit: Setiap renewal certificate dicatat. Kegagalan renewal memicu alert critical.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiofiles
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from config.loader_yaml import load_yaml_config

# Internal dependencies
from infrastructure.security.mtls_certificate_loader import (
    MTLSClientCertificateLoader,
    get_mtls_certificate_loader,
)
from infrastructure.security.securitykey_management_vault import (
    get_key_management_vault,
)
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_RENEWAL_DAYS_BEFORE_EXPIRY = 14  # Renew 14 days before expiry
DEFAULT_CSR_CONFIG = {
    "country": "ID",
    "state": "Jakarta",
    "locality": "Jakarta Selatan",
    "organization": "ERP Accounting Engine",
    "common_name": "erp.internal",
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class CertificateRenewalError(Exception):
    """Base exception untuk certificate renewal."""

    pass


class CSRGenerationError(CertificateRenewalError):
    """Gagal generate CSR."""

    pass


class CARequestError(CertificateRenewalError):
    """Error saat request ke CA."""

    pass


# ============================================================================
# CERTIFICATE RENEWER
# ============================================================================


class MTLSClientCertificateRenewer:
    """
    Renewer untuk mTLS certificate.

    Fitur:
    - Check certificate expiry dan trigger renewal
    - Generate CSR (Certificate Signing Request)
    - Submit CSR ke CA (internal atau eksternal)
    - Replace certificate file setelah renewal
    - Trigger hot reload setelah renewal
    """

    def __init__(self, config_path: str = "config_files/security_config.yaml"):
        self.config = self._load_config(config_path)
        self._loader: MTLSClientCertificateLoader | None = None
        self._renewal_task: asyncio.Task | None = None
        self._running = False
        self._renewal_count = 0
        self._last_renewal: datetime | None = None

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            return config.get("mtls_renewer", {})
        except Exception as e:
            logger.warning(f"Failed to load mTLS renewer config, using defaults: {e}")
            return {
                "enabled": True,
                "renewal_days_before_expiry": DEFAULT_RENEWAL_DAYS_BEFORE_EXPIRY,
                "ca_type": "internal",  # internal, vault, acme
                "ca_endpoint": None,
                "ca_cert_path": "/secrets/mtls/ca.crt",
                "ca_key_path": "/secrets/mtls/ca.key",
            }

    async def _get_loader(self) -> MTLSClientCertificateLoader:
        if self._loader is None:
            self._loader = await get_mtls_certificate_loader()
        return self._loader

    # ========================================================================
    # PERBAIKAN: _generate_csr menjadi async dengan asyncio.to_thread
    # ========================================================================
    async def _generate_csr(self, private_key: rsa.RSAPrivateKey) -> tuple[str, str]:
        """
        Generate Certificate Signing Request.
        Args:
            private_key: RSA private key
        Returns:
            Tuple of (csr_pem_string, csr_der_bytes_base64)
        """
        csr_config = self.config.get("csr_config", DEFAULT_CSR_CONFIG)

        def _generate_sync():
            # Build subject
            subject = x509.Name(
                [
                    x509.NameAttribute(NameOID.COUNTRY_NAME, csr_config.get("country", "ID")),
                    x509.NameAttribute(
                        NameOID.STATE_OR_PROVINCE_NAME, csr_config.get("state", "Jakarta")
                    ),
                    x509.NameAttribute(
                        NameOID.LOCALITY_NAME, csr_config.get("locality", "Jakarta Selatan")
                    ),
                    x509.NameAttribute(
                        NameOID.ORGANIZATION_NAME,
                        csr_config.get("organization", "ERP Accounting Engine"),
                    ),
                    x509.NameAttribute(
                        NameOID.COMMON_NAME, csr_config.get("common_name", "erp.internal")
                    ),
                ]
            )

            # Build CSR
            csr = (
                x509.CertificateSigningRequestBuilder()
                .subject_name(subject)
                .sign(private_key, hashes.SHA256(), default_backend())
            )

            # Serialize CSR
            csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("utf-8")
            csr_der = csr.public_bytes(serialization.Encoding.DER)
            csr_base64 = base64.b64encode(csr_der).decode("ascii")
            return csr_pem, csr_base64

        return await asyncio.to_thread(_generate_sync)

    async def _submit_csr_to_ca(self, csr_pem: str) -> str:
        """
        Submit CSR to CA and get signed certificate.
        Returns:
            Signed certificate in PEM format
        """
        ca_type = self.config.get("ca_type", "internal")
        ca_endpoint = self.config.get("ca_endpoint")

        if ca_type == "internal":
            return await self._sign_with_internal_ca(csr_pem)
        elif ca_type == "vault":
            return await self._sign_with_vault(csr_pem)
        elif ca_type == "acme":
            return await self._sign_with_acme(csr_pem)
        else:
            raise CARequestError(f"Unsupported CA type: {ca_type}")

    # ========================================================================
    # PERBAIKAN: _sign_with_internal_ca - membaca file secara async dengan aiofiles
    # ========================================================================
    async def _sign_with_internal_ca(self, csr_pem: str) -> str:
        """
        Sign CSR with internal CA (for development/testing).
        """
        ca_cert_path = self.config.get("ca_cert_path", "/secrets/mtls/ca.crt")
        ca_key_path = self.config.get("ca_key_path", "/secrets/mtls/ca.key")

        # Baca file CA cert dan key secara async
        async with aiofiles.open(ca_cert_path, "rb") as f:
            ca_cert_pem = await f.read()
        async with aiofiles.open(ca_key_path, "rb") as f:
            ca_key_pem = await f.read()

        def _sign_sync(cert_pem_bytes: bytes, key_pem_bytes: bytes, csr_pem_str: str) -> str:
            ca_cert = x509.load_pem_x509_certificate(cert_pem_bytes, default_backend())
            ca_key = serialization.load_pem_private_key(
                key_pem_bytes, password=None, backend=default_backend()
            )

            # Load CSR
            csr = x509.load_pem_x509_csr(csr_pem_str.encode(), default_backend())

            # Build certificate
            cert = (
                x509.CertificateBuilder()
                .subject_name(csr.subject)
                .issuer_name(ca_cert.subject)
                .public_key(csr.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.now(UTC))
                .not_valid_after(datetime.now(UTC) + timedelta(days=365))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(
                    x509.KeyUsage(
                        digital_signature=True,
                        key_encipherment=True,
                        key_agreement=False,
                        key_cert_sign=False,
                        crl_sign=False,
                        content_commitment=False,
                        data_encipherment=False,
                        decipher_only=False,
                        encipher_only=False,
                    ),
                    critical=True,
                )
                .sign(ca_key, hashes.SHA256(), default_backend())
            )

            return cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")

        try:
            cert_pem = await asyncio.to_thread(_sign_sync, ca_cert_pem, ca_key_pem, csr_pem)
            return cert_pem
        except Exception as e:
            logger.error(f"Internal CA signing failed: {e}")
            raise CARequestError(f"Internal CA signing failed: {e}") from e

    async def _sign_with_vault(self, csr_pem: str) -> str:
        """
        Sign CSR with Vault PKI.
        """
        try:
            vault = await get_key_management_vault()
            if hasattr(vault, "sign_csr"):
                cert = await vault.sign_csr(csr_pem)
            else:
                raise CARequestError(
                    "Vault PKI sign_csr method not implemented in KeyManagementVault"
                )
            return cert
        except Exception as e:
            logger.error(f"Vault signing failed: {e}")
            raise CARequestError(f"Vault signing failed: {e}") from e

    async def _sign_with_acme(self, csr_pem: str) -> str:
        """
        Sign CSR with ACME (Let's Encrypt).
        """
        # For production, implement ACME client
        # For now, raise error
        raise CARequestError("ACME signing not yet implemented")

    # ========================================================================
    # PERBAIKAN: _save_certificate menggunakan aiofiles
    # ========================================================================
    async def _save_certificate(self, cert_pem: str) -> None:
        """
        Save signed certificate to file.
        """
        cert_path = self.config.get("cert_file", "/secrets/mtls/client.crt")
        cert_file = Path(cert_path)

        # Backup old certificate (rename blocking, gunakan asyncio.to_thread)
        if cert_file.exists():
            backup_path = cert_file.with_suffix(".crt.bak")
            await asyncio.to_thread(lambda: cert_file.rename(backup_path))
            logger.info(f"Backed up old certificate to {backup_path}")

        # Write new certificate (async dengan aiofiles)
        async with aiofiles.open(cert_file, "w") as f:
            await f.write(cert_pem)

        logger.info(f"New certificate saved to {cert_file}")

    # ========================================================================
    # PERBAIKAN: renew_certificate menggunakan aiofiles / thread untuk key generation
    # ========================================================================
    async def renew_certificate(self, force: bool = False) -> dict[str, Any]:
        """
        Renew mTLS certificate.

        Args:
            force: Force renewal even if not yet expiring

        Returns:
            Renewal result
        """
        if not self.config.get("enabled", True) and not force:
            logger.info("Certificate renewal is disabled")
            return {"renewed": False, "reason": "disabled"}

        try:
            loader = await self._get_loader()

            # Get current certificate info
            cert_info = loader.get_certificate_info()

            if not cert_info.get("loaded"):
                logger.warning("No certificate loaded, attempting to load")
                await loader.load_certificate()
                cert_info = loader.get_certificate_info()

            days_until_expiry = cert_info.get("days_until_expiry", 0)
            renewal_threshold = self.config.get(
                "renewal_days_before_expiry", DEFAULT_RENEWAL_DAYS_BEFORE_EXPIRY
            )

            # Check if renewal is needed
            if not force and days_until_expiry > renewal_threshold:
                logger.info(
                    f"Certificate still valid for {days_until_expiry} days, skipping renewal"
                )
                return {
                    "renewed": False,
                    "reason": f"not_expiring_yet ({days_until_expiry} days remaining)",
                    "days_until_expiry": days_until_expiry,
                }

            logger.info(f"Starting certificate renewal (days until expiry: {days_until_expiry})")

            # Generate new private key (blocking, but fast)
            def _gen_key_sync():
                return rsa.generate_private_key(
                    public_exponent=65537, key_size=2048, backend=default_backend()
                )
            new_private_key = await asyncio.to_thread(_gen_key_sync)

            # Generate CSR (async)
            csr_pem, csr_base64 = await self._generate_csr(new_private_key)
            logger.info("CSR generated")

            # Submit CSR to CA (async)
            cert_pem = await self._submit_csr_to_ca(csr_pem)
            logger.info("Certificate signed by CA")

            # Save new private key (blocking I/O)
            key_path = self.config.get("key_file", "/secrets/mtls/client.key")
            key_file = Path(key_path)

            # Backup old key (rename)
            if key_file.exists():
                backup_key_path = key_file.with_suffix(".key.bak")
                await asyncio.to_thread(lambda: key_file.rename(backup_key_path))

            # Write new private key (async dengan aiofiles)
            key_pem = new_private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            async with aiofiles.open(key_file, "wb") as f:
                await f.write(key_pem)
            logger.info(f"New private key saved to {key_file}")

            # Save certificate (async)
            await self._save_certificate(cert_pem)

            # Trigger hot reload
            await loader.reload()

            self._renewal_count += 1
            self._last_renewal = datetime.now(UTC)

            result = {
                "renewed": True,
                "new_cert_expiry_days": loader.get_certificate_info().get("days_until_expiry", 0),
                "renewed_at": self._last_renewal.isoformat(),
                "renewal_count": self._renewal_count,
            }

            logger.info(f"Certificate renewal completed successfully: {result}")

            await trigger_alert(
                title="mTLS Certificate Renewed",
                message=f"Certificate renewed successfully. New expiry: {result['new_cert_expiry_days']} days",
                severity="info",
                source="MTLSClientCertificateRenewer",
            )

            return result

        except Exception as e:
            logger.error(f"Certificate renewal failed: {e}")
            await trigger_alert(
                title="mTLS Certificate Renewal Failed",
                message=f"Certificate renewal failed: {e!s}",
                severity="critical",
                source="MTLSClientCertificateRenewer",
            )
            raise CertificateRenewalError(f"Renewal failed: {e}") from e

    async def start_periodic_check(self, interval_hours: int = 24) -> None:
        """
        Start periodic check for certificate expiry and auto-renewal.
        """
        if self._renewal_task is not None:
            logger.warning("Periodic renewal check already running")
            return

        self._running = True
        self._renewal_task = asyncio.create_task(self._renewal_loop(interval_hours))
        logger.info(f"Periodic certificate renewal check started (interval: {interval_hours}h)")

    async def _renewal_loop(self, interval_hours: int) -> None:
        """
        Background loop for certificate renewal check.
        """
        while self._running:
            try:
                await asyncio.sleep(interval_hours * 3600)
                await self.renew_certificate()
            except asyncio.CancelledError:
                logger.debug("Certificate renewal loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in certificate renewal check: {e}")

    async def stop_periodic_check(self) -> None:
        """
        Stop periodic renewal check.
        """
        self._running = False
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                logger.debug("Certificate renewal task cancelled during stop")
                # Expected cancellation; continue
            self._renewal_task = None
        logger.info("Periodic certificate renewal check stopped")

    async def get_status(self) -> dict[str, Any]:
        """
        Get renewal status.
        """
        loader = await self._get_loader()
        cert_info = loader.get_certificate_info()

        return {
            "enabled": self.config.get("enabled", True),
            "running": self._running,
            "renewal_count": self._renewal_count,
            "last_renewal": self._last_renewal.isoformat() if self._last_renewal else None,
            "certificate_info": cert_info,
            "renewal_days_before_expiry": self.config.get(
                "renewal_days_before_expiry", DEFAULT_RENEWAL_DAYS_BEFORE_EXPIRY
            ),
            "ca_type": self.config.get("ca_type", "internal"),
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_certificate_renewer: MTLSClientCertificateRenewer | None = None


async def get_mtls_certificate_renewer() -> MTLSClientCertificateRenewer:
    """Get singleton instance of MTLSClientCertificateRenewer."""
    global _certificate_renewer
    if _certificate_renewer is None:
        _certificate_renewer = MTLSClientCertificateRenewer()
    return _certificate_renewer


async def start_certificate_renewer() -> None:
    """Start the certificate renewer."""
    renewer = await get_mtls_certificate_renewer()
    await renewer.start_periodic_check()


async def stop_certificate_renewer() -> None:
    """Stop the certificate renewer."""
    global _certificate_renewer
    if _certificate_renewer:
        await _certificate_renewer.stop_periodic_check()
        _certificate_renewer = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CARequestError",
    "CSRGenerationError",
    "CertificateRenewalError",
    "MTLSClientCertificateRenewer",
    "get_mtls_certificate_renewer",
    "start_certificate_renewer",
    "stop_certificate_renewer",
]
