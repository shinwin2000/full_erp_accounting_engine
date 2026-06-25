#!/usr/bin/env python3
"""
Module: distributor_email_whatsapp.py
Layer: Reports
Responsibility: Mendistribusikan laporan yang sudah dihasilkan ke berbagai channel:
               email (SMTP), WhatsApp (via API gateway), Slack, dan penyimpanan cloud.
               Mendukung multiple recipients, attachment, dan template email.
               Juga menyediakan fungsi untuk retry dan logging distribusi.
Dependencies:
- aiosmtplib (email), aiohttp (WhatsApp/Slack webhook), asyncio, logging
- reports.generator_pdf_excel_html (ReportGenerator)
- infrastructure.telemetry.structured_json_logging
- config.loader_yaml -> DIINJEKSI DARI LUAR (tidak diimpor langsung)
Audit: Setiap distribusi laporan dicatat, termasuk penerima, channel, dan status.
"""

from __future__ import annotations

import asyncio
import email.utils
import mimetypes
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Optional

# Email sending
try:
    import aiosmtplib

    SMTP_AVAILABLE = True
except ImportError:
    SMTP_AVAILABLE = False
    aiosmtplib = None

# HTTP client for WhatsApp/Slack webhooks
try:
    import aiohttp

    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False
    aiohttp = None

# Internal dependencies
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_CONFIG = {
    "email": {
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "use_tls": True,
        "username": None,
        "password": None,
        "from_email": "reports@erp.internal",
        "from_name": "ERP Accounting Engine",
    },
    "whatsapp": {"api_url": None, "api_token": None, "enabled": False},
    "slack": {"webhook_url": None, "enabled": False},
    "retry": {"max_attempts": 3, "delay_seconds": [5, 30, 120]},
}

# Delivery methods
DELIVERY_EMAIL = "email"
DELIVERY_WHATSAPP = "whatsapp"
DELIVERY_SLACK = "slack"
DELIVERY_CLOUD = "cloud"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class DistributionError(Exception):
    """Base exception untuk report distributor."""

    pass


class EmailSendError(DistributionError):
    """Error saat mengirim email."""

    pass


class WhatsAppSendError(DistributionError):
    """Error saat mengirim WhatsApp."""

    pass


# ============================================================================
# REPORT DISTRIBUTOR
# ============================================================================


class ReportDistributor:
    """
    Distributor laporan ke berbagai channel.

    Fitur:
    - Mengirim email dengan attachment (PDF, Excel, HTML)
    - Mengirim pesan WhatsApp dengan link atau file attachment
    - Mengirim ke Slack channel
    - Upload ke cloud storage dan share link
    - Retry dengan exponential backoff
    - Tracking distribusi
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """
        Inisialisasi distributor dengan konfigurasi yang diinjeksi.

        Args:
            config: Dictionary konfigurasi (jika None, gunakan DEFAULT_CONFIG)
        """
        self.config = self._prepare_config(config)
        self._email_config = self.config.get("email", DEFAULT_CONFIG["email"])
        self._whatsapp_config = self.config.get("whatsapp", DEFAULT_CONFIG["whatsapp"])
        self._slack_config = self.config.get("slack", DEFAULT_CONFIG["slack"])
        self._retry_config = self.config.get("retry", DEFAULT_CONFIG["retry"])
        self._session: Optional[aiohttp.ClientSession] = None

    def _prepare_config(self, config: Optional[dict]) -> dict:
        """Siapkan konfigurasi dari parameter atau default."""
        if config is not None:
            # Merge dengan default untuk memastikan semua key ada
            result = DEFAULT_CONFIG.copy()
            for key, value in config.items():
                if key in result and isinstance(value, dict):
                    result[key].update(value)
                else:
                    result[key] = value
            return result
        return DEFAULT_CONFIG.copy()

    async def _get_session(self) -> aiohttp.ClientSession:
        if not HTTP_AVAILABLE:
            raise DistributionError("aiohttp not available")
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ========================================================================
    # EMAIL DISTRIBUTION
    # ========================================================================

    async def send_email(
        self,
        to_emails: list[str],
        subject: str,
        body: str,
        attachment_path: Path | None = None,
        attachment_name: str | None = None,
        cc_emails: list[str] | None = None,
        bcc_emails: list[str] | None = None,
    ) -> bool:
        """
        Send email with optional attachment.

        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            body: Email body (HTML or plain text)
            attachment_path: Path to file to attach
            attachment_name: Custom attachment name
            cc_emails: CC recipients
            bcc_emails: BCC recipients

        Returns:
            True if sent successfully
        """
        if not SMTP_AVAILABLE or not aiosmtplib:
            logger.warning("aiosmtplib not available, email sending disabled")
            return False

        if not to_emails:
            logger.warning("No recipient emails provided")
            return False

        smtp_host = self._email_config.get("smtp_host")
        smtp_port = self._email_config.get("smtp_port", 587)
        username = self._email_config.get("username")
        password = self._email_config.get("password")
        use_tls = self._email_config.get("use_tls", True)
        from_email = self._email_config.get("from_email")
        from_name = self._email_config.get("from_name", "ERP Accounting Engine")

        if not smtp_host or not username or not password:
            logger.error("SMTP configuration incomplete")
            return False

        # Build email message
        msg = EmailMessage()
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = ", ".join(to_emails)
        if cc_emails:
            msg["Cc"] = ", ".join(cc_emails)
        if bcc_emails:
            msg["Bcc"] = ", ".join(bcc_emails)
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate()

        msg.set_content(body)  # Plain text fallback
        msg.add_alternative(body, subtype="html")  # HTML version

        # Add attachment
        if attachment_path and attachment_path.exists():
            content_type, _encoding = mimetypes.guess_type(str(attachment_path))
            if content_type is None:
                content_type = "application/octet-stream"

            with open(attachment_path, "rb") as f:
                file_data = f.read()

            display_name = attachment_name or attachment_path.name
            msg.add_attachment(
                file_data,
                maintype=content_type.split("/")[0],
                subtype=content_type.split("/")[-1],
                filename=display_name,
            )

        # Send with retry
        max_attempts = self._retry_config.get("max_attempts", 3)
        delays = self._retry_config.get("delay_seconds", [5, 30, 120])

        for attempt in range(max_attempts):
            try:
                async with aiosmtplib.SMTP(
                    hostname=smtp_host, port=smtp_port, use_tls=use_tls
                ) as smtp:
                    await smtp.login(username, password)
                    await smtp.send_message(msg)

                logger.info(f"Email sent to {', '.join(to_emails)}: {subject}")
                return True

            except Exception as e:
                logger.warning(f"Email send attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                else:
                    logger.error(f"Failed to send email after {max_attempts} attempts: {e}")
                    await trigger_alert(
                        title="Report Email Distribution Failed",
                        message=f"Failed to send email to {', '.join(to_emails)}: {e}",
                        severity="warning",
                        source="ReportDistributor",
                    )
                    return False
        return False

    # ========================================================================
    # WHATSAPP DISTRIBUTION
    # ========================================================================

    async def send_whatsapp(
        self, to_numbers: list[str], message: str, attachment_url: str | None = None
    ) -> bool:
        """
        Send WhatsApp message (via API gateway).

        Args:
            to_numbers: List of phone numbers with country code
            message: Text message
            attachment_url: URL to attached file (optional)

        Returns:
            True if sent successfully
        """
        if not self._whatsapp_config.get("enabled", False):
            logger.info("WhatsApp distribution disabled")
            return False

        api_url = self._whatsapp_config.get("api_url")
        api_token = self._whatsapp_config.get("api_token")

        if not api_url or not api_token:
            logger.error("WhatsApp API configuration incomplete")
            return False

        session = await self._get_session()

        max_attempts = self._retry_config.get("max_attempts", 3)
        delays = self._retry_config.get("delay_seconds", [5, 30, 120])

        for attempt in range(max_attempts):
            try:
                for number in to_numbers:
                    payload = {"to": number, "text": message, "type": "text"}
                    if attachment_url:
                        payload["type"] = "document"
                        payload["document"] = {"url": attachment_url}

                    headers = {
                        "Authorization": f"Bearer {api_token}",
                        "Content-Type": "application/json",
                    }

                    async with session.post(api_url, json=payload, headers=headers) as resp:
                        if resp.status in (200, 201):
                            logger.info(f"WhatsApp message sent to {number}")
                        else:
                            error_text = await resp.text()
                            logger.warning(f"WhatsApp API returned {resp.status}: {error_text}")
                            raise WhatsAppSendError(f"API error: {resp.status}")

                return True

            except Exception as e:
                logger.warning(f"WhatsApp send attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                else:
                    logger.error(f"Failed to send WhatsApp after {max_attempts} attempts: {e}")
                    return False
        return False

    # ========================================================================
    # SLACK DISTRIBUTION
    # ========================================================================

    async def send_slack(self, channel: str, message: str, file_url: str | None = None) -> bool:
        """
        Send message to Slack channel.

        Args:
            channel: Slack channel name or ID
            message: Text message (supports markdown)
            file_url: URL to attached file (optional)

        Returns:
            True if sent successfully
        """
        if not self._slack_config.get("enabled", False):
            logger.info("Slack distribution disabled")
            return False

        webhook_url = self._slack_config.get("webhook_url")
        if not webhook_url:
            logger.error("Slack webhook URL not configured")
            return False

        session = await self._get_session()

        payload = {"channel": channel, "text": message, "mrkdwn": True}

        if file_url:
            payload["attachments"] = [
                {
                    "title": "Report Attachment",
                    "title_link": file_url,
                    "text": "Click the link to download the report.",
                }
            ]

        max_attempts = self._retry_config.get("max_attempts", 3)
        delays = self._retry_config.get("delay_seconds", [5, 30, 120])

        for attempt in range(max_attempts):
            try:
                async with session.post(webhook_url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info(f"Slack message sent to channel {channel}")
                        return True
                    else:
                        error_text = await resp.text()
                        logger.warning(f"Slack webhook returned {resp.status}: {error_text}")
                        raise DistributionError(f"Slack error: {resp.status}")
            except Exception as e:
                logger.warning(f"Slack send attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                else:
                    logger.error(f"Failed to send Slack after {max_attempts} attempts: {e}")
                    return False
        return False

    # ========================================================================
    # GENERIC DISTRIBUTE METHOD
    # ========================================================================

    async def distribute(
        self,
        file_path: Path,
        file_name: str,
        recipients: list[str],
        delivery_method: str = "email",
        subject: str | None = None,
        message: str | None = None,
        upload_to_cloud: bool = True,
    ) -> dict[str, Any]:
        """
        Generic method to distribute report.

        Args:
            file_path: Path to the generated report file
            file_name: Display name of the file
            recipients: List of recipient identifiers (emails, phone numbers, or slack channels)
            delivery_method: "email", "whatsapp", "slack", "cloud"
            subject: Email subject or message title
            message: Email body or message text
            upload_to_cloud: If True, upload to cloud and send link instead of attachment

        Returns:
            Distribution result
        """
        result = {
            "method": delivery_method,
            "recipients": recipients,
            "success": False,
            "message": "",
            "file_url": None,
        }

        # Optionally upload to cloud and get shareable link
        file_url = None
        if upload_to_cloud:
            try:
                from infrastructure.file_storage.s3_adapter import get_s3_storage_adapter

                storage = await get_s3_storage_adapter()
                with open(file_path, "rb") as f:
                    uri = await storage.upload(
                        file_content=f, file_name=file_name, bucket="erp-reports"
                    )
                # Generate presigned URL for access
                file_url = await storage.generate_presigned_url(uri, expiration_seconds=7 * 86400)
                result["file_url"] = file_url
            except Exception as e:
                logger.warning(f"Failed to upload report to cloud: {e}")

        if delivery_method == DELIVERY_EMAIL:
            if not subject:
                subject = f"ERP Report: {file_name}"
            if not message:
                message = f"Please find attached the report <b>{file_name}</b>.<br><br>Generated by ERP Accounting Engine."

            # If file_url is available, we can send link instead of attachment
            if file_url:
                message += f"<br><br>Download link: <a href='{file_url}'>{file_url}</a>"
                success = await self.send_email(
                    to_emails=recipients, subject=subject, body=message, attachment_path=None
                )
            else:
                success = await self.send_email(
                    to_emails=recipients,
                    subject=subject,
                    body=message,
                    attachment_path=file_path,
                    attachment_name=file_name,
                )
            result["success"] = success
            result["message"] = "Email sent" if success else "Email sending failed"

        elif delivery_method == DELIVERY_WHATSAPP:
            if not message:
                message = f"ERP Report: {file_name}\nGenerated by ERP Accounting Engine."
            if file_url:
                message += f"\nDownload: {file_url}"
            success = await self.send_whatsapp(
                to_numbers=recipients, message=message, attachment_url=file_url
            )
            result["success"] = success
            result["message"] = "WhatsApp sent" if success else "WhatsApp sending failed"

        elif delivery_method == DELIVERY_SLACK:
            if not message:
                message = f"*ERP Report: {file_name}*\nGenerated by ERP Accounting Engine."
            success = await self.send_slack(
                channel=recipients[0] if recipients else "general",
                message=message,
                file_url=file_url,
            )
            result["success"] = success
            result["message"] = "Slack sent" if success else "Slack sending failed"

        elif delivery_method == DELIVERY_CLOUD:
            if file_url:
                result["success"] = True
                result["message"] = f"Report uploaded to cloud: {file_url}"
            else:
                result["success"] = False
                result["message"] = "Cloud upload failed"

        else:
            result["success"] = False
            result["message"] = f"Unknown delivery method: {delivery_method}"

        # Log distribution
        logger.info(f"Report distribution: {result}")
        return result

    async def distribute_batch(self, distributions: list[dict]) -> list[dict]:
        """
        Distribute multiple reports in batch.

        Args:
            distributions: List of distribution config dictionaries

        Returns:
            List of results
        """
        results = []
        for dist in distributions:
            result = await self.distribute(
                file_path=Path(dist["file_path"]),
                file_name=dist["file_name"],
                recipients=dist["recipients"],
                delivery_method=dist.get("delivery_method", "email"),
                subject=dist.get("subject"),
                message=dist.get("message"),
                upload_to_cloud=dist.get("upload_to_cloud", True),
            )
            results.append(result)
            # Small delay to avoid rate limiting
            await asyncio.sleep(1)
        return results


# ============================================================================
# SINGLETON INSTANCE dengan injeksi konfigurasi dari luar
# ============================================================================

_report_distributor: Optional[ReportDistributor] = None
_distributor_config: Optional[dict] = None


def set_distributor_config(config: dict) -> None:
    """Set konfigurasi untuk distributor (harus dipanggil sebelum get_report_distributor)."""
    global _distributor_config
    _distributor_config = config


async def get_report_distributor() -> ReportDistributor:
    """Get singleton instance of ReportDistributor."""
    global _report_distributor
    if _report_distributor is None:
        _report_distributor = ReportDistributor(config=_distributor_config)
    return _report_distributor


async def shutdown_report_distributor() -> None:
    """Shutdown report distributor."""
    global _report_distributor
    if _report_distributor:
        await _report_distributor.close()
        _report_distributor = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DistributionError",
    "EmailSendError",
    "ReportDistributor",
    "WhatsAppSendError",
    "get_report_distributor",
    "shutdown_report_distributor",
    "set_distributor_config",
]