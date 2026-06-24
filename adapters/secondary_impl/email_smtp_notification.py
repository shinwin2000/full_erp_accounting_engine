#!/usr/bin/env python3
"""
Module: email_smtp_notification.py
Layer: Adapters (Secondary)
Responsibility: Implementasi NotificationPort dengan SMTP dan logging.
"""

import asyncio
import logging
import os
import smtplib
from datetime import datetime, UTC
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4

from ports.primary.notification_port import NotificationPort, NotificationPriority

logger = logging.getLogger(__name__)


class EmailSMTPNotification(NotificationPort):
    """Implementasi NotificationPort dengan SMTP dan fallback logging."""

    def __init__(self):
        self._smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self._smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self._smtp_user = os.getenv("SMTP_USER", "")
        self._smtp_password = os.getenv("SMTP_PASSWORD", "")
        self._from_email = os.getenv("SMTP_FROM_EMAIL", self._smtp_user)
        self._from_name = os.getenv("SMTP_FROM_NAME", "ERP Accounting Engine")
        self._history: List[Dict] = []
        self._templates: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()
        self._enabled = bool(self._smtp_user and self._smtp_password)
        self._worker_running = False
        self._channel_configs: Dict[str, Dict] = {
            "email": {"enabled": True},
            "sms": {"enabled": False},
            "whatsapp": {"enabled": False},
            "push": {"enabled": False},
            "slack": {"enabled": False},
            "webhook": {"enabled": False},
        }
        if not self._enabled:
            logger.warning("SMTP not configured. Email notifications will be logged only.")

    # ========== CORE METHODS ==========
    async def send_email(
        self,
        to: str | List[str],
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        attachments: Optional[List[Dict]] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> Dict:
        if isinstance(to, str):
            to_list = [to]
        else:
            to_list = to
        nid = str(uuid4())
        ts = datetime.now(UTC)

        if not self._enabled:
            async with self._lock:
                self._history.append({
                    "id": nid, "channel": "email", "to": to_list,
                    "subject": subject, "body": body[:500],
                    "status": "logged", "timestamp": ts.isoformat(),
                    "priority": priority.value
                })
            logger.info(f"[NOTIFICATION] Email to {to_list}: {subject}")
            return {"id": nid, "status": "logged", "message": "SMTP not configured", "timestamp": ts.isoformat()}

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = f"{self._from_name} <{self._from_email}>"
            msg["To"] = ", ".join(to_list)
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            if html_body:
                msg.attach(MIMEText(html_body, "html"))
            if attachments:
                for att in attachments:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(att.get("content", b""))
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename={att.get('filename', 'attachment.bin')}")
                    msg.attach(part)
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                server.starttls()
                server.login(self._smtp_user, self._smtp_password)
                server.sendmail(self._from_email, to_list, msg.as_string())
            status = "sent"
            logger.info(f"[EMAIL] Sent to {to_list}: {subject}")
        except Exception as e:
            status = "failed"
            logger.error(f"[EMAIL] Failed: {e}")

        async with self._lock:
            self._history.append({
                "id": nid, "channel": "email", "to": to_list,
                "subject": subject, "body": body[:500],
                "status": status, "timestamp": ts.isoformat(),
                "priority": priority.value
            })
        return {"id": nid, "status": status, "message": f"Email {status}", "timestamp": ts.isoformat()}

    async def send_sms(self, phone_number: str, message: str, priority: NotificationPriority = NotificationPriority.NORMAL) -> Dict:
        nid = str(uuid4())
        ts = datetime.now(UTC)
        async with self._lock:
            self._history.append({
                "id": nid, "channel": "sms", "to": phone_number,
                "body": message[:160], "status": "logged",
                "timestamp": ts.isoformat(), "priority": priority.value
            })
        logger.info(f"[SMS] To {phone_number}: {message[:100]}")
        return {"id": nid, "status": "logged", "message": "SMS provider not configured", "timestamp": ts.isoformat()}

    async def send_whatsapp(self, phone_number: str, message: str, priority: NotificationPriority = NotificationPriority.NORMAL) -> Dict:
        nid = str(uuid4())
        ts = datetime.now(UTC)
        async with self._lock:
            self._history.append({
                "id": nid, "channel": "whatsapp", "to": phone_number,
                "body": message[:500], "status": "logged",
                "timestamp": ts.isoformat(), "priority": priority.value
            })
        logger.info(f"[WHATSAPP] To {phone_number}: {message[:100]}")
        return {"id": nid, "status": "logged", "message": "WhatsApp provider not configured", "timestamp": ts.isoformat()}

    async def send_push_notification(
        self,
        user_id: UUID,
        title: str,
        body: str,
        data: Optional[Dict] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> Dict:
        nid = str(uuid4())
        ts = datetime.now(UTC)
        async with self._lock:
            self._history.append({
                "id": nid, "channel": "push", "user_id": str(user_id),
                "title": title, "body": body[:500], "data": data,
                "status": "logged", "timestamp": ts.isoformat(),
                "priority": priority.value
            })
        logger.info(f"[PUSH] To user {user_id}: {title}")
        return {"id": nid, "status": "logged", "message": "Push provider not configured", "timestamp": ts.isoformat()}

    # ========== EXTRA METHODS FOR COMPLETE CONTRACT ==========
    async def add_template(self, template_id: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
        """Menambahkan template notifikasi."""
        async with self._lock:
            self._templates[template_id] = {
                "subject": subject,
                "body": body,
                "html_body": html_body,
                "created_at": datetime.now(UTC).isoformat()
            }
        logger.info(f"[TEMPLATE] Added: {template_id}")
        return True

    async def get_template(self, template_id: str) -> Optional[Dict]:
        """Mendapatkan template notifikasi."""
        async with self._lock:
            return self._templates.get(template_id)

    async def cancel_notification(self, notification_id: str) -> bool:
        """Membatalkan notifikasi (jika masih pending)."""
        async with self._lock:
            for n in self._history:
                if n.get("id") == notification_id and n.get("status") in ("pending", "logged"):
                    n["status"] = "cancelled"
                    return True
        return False

    async def get_notification_history(
        self,
        user_id: Optional[UUID] = None,
        channel: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """Mengambil history notifikasi."""
        async with self._lock:
            result = self._history.copy()
        if user_id:
            result = [n for n in result if n.get("user_id") == str(user_id)]
        if channel:
            result = [n for n in result if n.get("channel") == channel]
        result.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return result[offset:offset+limit]

    async def mark_as_read(self, notification_id: str) -> bool:
        """Menandai notifikasi sebagai sudah dibaca."""
        async with self._lock:
            for n in self._history:
                if n.get("id") == notification_id:
                    n["read"] = True
                    return True
        return False

    async def get_unread_count(self, user_id: UUID) -> int:
        """Mendapatkan jumlah notifikasi belum dibaca."""
        async with self._lock:
            return sum(1 for n in self._history if n.get("user_id") == str(user_id) and not n.get("read", False))

    async def health_check(self) -> Dict:
        """Cek kesehatan service."""
        return {
            "status": "healthy",
            "smtp_configured": self._enabled,
            "total_history": len(self._history),
            "total_templates": len(self._templates),
        }

    # ========== NEW MISSING METHODS ==========

    async def delete_template(self, template_id: str) -> bool:
        """Hapus template notifikasi."""
        async with self._lock:
            if template_id in self._templates:
                del self._templates[template_id]
                logger.info(f"[TEMPLATE] Deleted: {template_id}")
                return True
        logger.warning(f"[TEMPLATE] Delete failed: {template_id} not found")
        return False

    async def get_audit_log(
        self,
        limit: int = 100,
        offset: int = 0,
        channel: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict]:
        """Dapatkan audit log notifikasi (mirip history dengan filter tambahan)."""
        async with self._lock:
            result = self._history.copy()
        if channel:
            result = [n for n in result if n.get("channel") == channel]
        if status:
            result = [n for n in result if n.get("status") == status]
        result.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return result[offset:offset+limit]

    async def get_failed_notifications(self, limit: int = 100) -> List[Dict]:
        """Dapatkan notifikasi yang gagal."""
        async with self._lock:
            failed = [n for n in self._history if n.get("status") == "failed"]
        failed.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return failed[:limit]

    async def get_notification(self, notification_id: str) -> Optional[Dict]:
        """Dapatkan notifikasi berdasarkan ID."""
        async with self._lock:
            for n in self._history:
                if n.get("id") == notification_id:
                    return n
        return None

    async def get_notifications(
        self,
        user_id: Optional[UUID] = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """Dapatkan daftar notifikasi dengan filter."""
        # Reuse get_audit_log with similar signature
        return await self.get_audit_log(limit=limit, offset=offset, channel=channel, status=status)

    async def get_pending_count(self) -> int:
        """Dapatkan jumlah notifikasi yang pending (belum terkirim)."""
        # In this implementation we never have pending, only logged/sent/failed.
        return 0

    async def get_statistics(self) -> Dict[str, Any]:
        """Dapatkan statistik notifikasi."""
        async with self._lock:
            total = len(self._history)
            by_channel = {}
            by_status = {}
            for n in self._history:
                ch = n.get("channel", "unknown")
                st = n.get("status", "unknown")
                by_channel[ch] = by_channel.get(ch, 0) + 1
                by_status[st] = by_status.get(st, 0) + 1
        return {
            "total": total,
            "by_channel": by_channel,
            "by_status": by_status,
            "templates": len(self._templates),
            "smtp_enabled": self._enabled,
        }

    async def render_template(self, template_id: str, context: Dict[str, Any]) -> Dict[str, str]:
        """Render template dengan context."""
        template = await self.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        # Simple string formatting
        try:
            subject = template["subject"].format(**context)
            body = template["body"].format(**context)
            html_body = template.get("html_body")
            if html_body:
                html_body = html_body.format(**context)
        except KeyError as e:
            logger.error(f"Missing context key for template {template_id}: {e}")
            raise
        return {"subject": subject, "body": body, "html_body": html_body}

    async def send_push(
        self,
        user_id: UUID,
        title: str,
        body: str,
        data: Optional[Dict] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> Dict:
        """Alias untuk send_push_notification."""
        return await self.send_push_notification(user_id, title, body, data, priority)

    async def send_slack(
        self,
        webhook_url: str,
        message: str,
        channel: Optional[str] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> Dict:
        """Kirim notifikasi ke Slack (stub)."""
        nid = str(uuid4())
        ts = datetime.now(UTC)
        async with self._lock:
            self._history.append({
                "id": nid, "channel": "slack", "to": webhook_url,
                "body": message[:500], "status": "logged",
                "timestamp": ts.isoformat(), "priority": priority.value
            })
        logger.info(f"[SLACK] To webhook {webhook_url}: {message[:100]}")
        return {"id": nid, "status": "logged", "message": "Slack provider not configured", "timestamp": ts.isoformat()}

    async def send_webhook(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str = "POST",
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> Dict:
        """Kirim notifikasi melalui webhook (stub)."""
        nid = str(uuid4())
        ts = datetime.now(UTC)
        async with self._lock:
            self._history.append({
                "id": nid, "channel": "webhook", "to": url,
                "body": str(payload)[:500], "status": "logged",
                "timestamp": ts.isoformat(), "priority": priority.value
            })
        logger.info(f"[WEBHOOK] To {url}: {method} {payload}")
        return {"id": nid, "status": "logged", "message": "Webhook provider not configured", "timestamp": ts.isoformat()}

    async def send_with_template(
        self,
        template_id: str,
        context: Dict[str, Any],
        to: str | List[str],
        priority: NotificationPriority = NotificationPriority.NORMAL,
        attachments: Optional[List[Dict]] = None,
    ) -> Dict:
        """Kirim notifikasi menggunakan template."""
        rendered = await self.render_template(template_id, context)
        # Kirim sebagai email
        return await self.send_email(
            to=to,
            subject=rendered["subject"],
            body=rendered["body"],
            html_body=rendered.get("html_body"),
            attachments=attachments,
            priority=priority,
        )

    async def start_worker(self) -> None:
        """Mulai worker background untuk proses notifikasi (stub)."""
        self._worker_running = True
        logger.info("[WORKER] Started")

    async def stop_worker(self) -> None:
        """Hentikan worker (stub)."""
        self._worker_running = False
        logger.info("[WORKER] Stopped")

    async def update_channel_config(self, channel: str, config: Dict[str, Any]) -> bool:
        """Perbarui konfigurasi channel notifikasi."""
        if channel not in self._channel_configs:
            logger.warning(f"Unknown channel: {channel}")
            return False
        async with self._lock:
            self._channel_configs[channel].update(config)
        logger.info(f"[CONFIG] Updated {channel}: {config}")
        return True