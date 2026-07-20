#!/usr/bin/env python3
"""
Module: notification_port.py
Layer: Ports (Primary)
Responsibility: Port untuk notification service multi-channel.
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ==================== ENUMS & DOMAIN MODELS ====================

class NotificationChannel(Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    SMS = "sms"
    SLACK = "slack"
    PUSH = "push"
    WEBHOOK = "webhook"


class NotificationPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class NotificationStatus(Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRY = "retry"
    CANCELLED = "cancelled"


class NotificationTemplateType(Enum):
    JOURNAL_POSTED = "journal_posted"
    INVOICE_CREATED = "invoice_created"
    PAYMENT_RECEIVED = "payment_received"
    PERIOD_CLOSED = "period_closed"
    APPROVAL_REQUIRED = "approval_required"
    TAX_SUBMISSION = "tax_submission"
    SYSTEM_ALERT = "system_alert"
    DAILY_SUMMARY = "daily_summary"


@dataclass
class Notification:
    id: UUID
    channel: NotificationChannel
    recipient: str
    subject: str | None
    body: str
    priority: NotificationPriority
    status: NotificationStatus
    retry_count: int
    scheduled_at: datetime | None
    sent_at: datetime | None
    delivered_at: datetime | None
    error_message: str | None
    metadata: dict[str, Any]
    created_at: datetime
    created_by: UUID
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "channel": self.channel.value,
            "recipient": self.recipient,
            "subject": self.subject,
            "body_preview": self.body[:100],
            "priority": self.priority.value,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "error_message": self.error_message,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
        }


@dataclass
class NotificationTemplate:
    id: UUID
    template_type: NotificationTemplateType
    channel: NotificationChannel
    subject_template: str | None
    body_template: str
    variables: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class NotificationConfig:
    channel: NotificationChannel
    enabled: bool
    config: dict[str, Any]


# ==================== PORT (INTERFACE) ====================

class NotificationPort(abc.ABC):
    """Port untuk notification service."""

    @abc.abstractmethod
    async def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> list[UUID]:
        """Kirim email ke multiple recipients."""
        ...

    @abc.abstractmethod
    async def send_whatsapp(
        self,
        to: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        """Kirim WhatsApp."""
        ...

    @abc.abstractmethod
    async def send_sms(
        self,
        to: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        """Kirim SMS."""
        ...

    @abc.abstractmethod
    async def send_slack(
        self,
        channel: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        """Kirim Slack message."""
        ...

    @abc.abstractmethod
    async def send_push(
        self,
        device_token: str,
        title: str,
        body: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        """Kirim push notification."""
        ...

    @abc.abstractmethod
    async def send_webhook(
        self,
        url: str,
        payload: dict[str, Any],
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        """Kirim webhook."""
        ...

    @abc.abstractmethod
    async def send_with_template(
        self,
        template_type: NotificationTemplateType,
        channel: NotificationChannel,
        recipient: str,
        variables: dict[str, Any],
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID | None:
        """Kirim notifikasi menggunakan template."""
        ...

    @abc.abstractmethod
    async def get_template(
        self, template_type: NotificationTemplateType, channel: NotificationChannel
    ) -> NotificationTemplate | None:
        """Ambil template."""
        ...

    @abc.abstractmethod
    async def render_template(
        self, template: NotificationTemplate, variables: dict[str, Any]
    ) -> tuple[str | None, str]:
        """Render template dengan variabel."""
        ...

    @abc.abstractmethod
    async def get_notification(self, notification_id: UUID) -> Notification | None:
        """Ambil notifikasi berdasarkan ID."""
        ...

    @abc.abstractmethod
    async def get_notifications(
        self,
        status: NotificationStatus | None = None,
        channel: NotificationChannel | None = None,
        recipient: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Notification]:
        """Daftar notifikasi dengan filter."""
        ...

    @abc.abstractmethod
    async def get_failed_notifications(self, limit: int = 100) -> list[Notification]:
        """Ambil notifikasi gagal."""
        ...

    @abc.abstractmethod
    async def get_pending_count(self) -> int:
        """Jumlah notifikasi pending."""
        ...

    @abc.abstractmethod
    async def update_channel_config(
        self, channel: NotificationChannel, enabled: bool, config: dict[str, Any]
    ) -> None:
        """Update konfigurasi channel."""
        ...

    @abc.abstractmethod
    async def add_template(
        self,
        template_type: NotificationTemplateType,
        channel: NotificationChannel,
        subject_template: str | None,
        body_template: str,
        variables: list[str],
        created_by: UUID,
    ) -> UUID:
        """Tambah template baru."""
        ...

    @abc.abstractmethod
    async def delete_template(self, template_id: UUID) -> bool:
        """Hapus template."""
        ...

    @abc.abstractmethod
    async def cancel_notification(self, notification_id: UUID) -> bool:
        """Batalkan notifikasi pending/retry."""
        ...

    @abc.abstractmethod
    async def start_worker(self, concurrency: int = 5):
        """Start background worker."""
        ...

    @abc.abstractmethod
    async def stop_worker(self):
        """Stop background worker."""
        ...

    @abc.abstractmethod
    async def get_statistics(self) -> dict[str, Any]:
        """Statistik notifikasi."""
        ...

    @abc.abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Ambil audit log."""
        ...

    @abc.abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check."""
        ...


# ==================== IMPLEMENTASI IN-MEMORY ====================

class InMemoryNotification(NotificationPort):
    """
    In-memory notification service dengan multi-channel.
    Kelas ini TIDAK akan didaftarkan oleh container karena mengandung kata "InMemory".
    """

    def __init__(self):
        self._notifications: dict[UUID, Notification] = {}
        self._templates: dict[UUID, NotificationTemplate] = {}
        self._template_index: dict[tuple[NotificationTemplateType, NotificationChannel], NotificationTemplate] = {}
        self._configs: dict[NotificationChannel, NotificationConfig] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._running = False
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._rate_limiters: dict[NotificationChannel, dict[str, list[datetime]]] = {}
        self._default_templates_loaded = False
        self._pending_tasks: list[asyncio.Task] = []

        init_task1 = asyncio.create_task(self._init_default_configs())
        init_task2 = asyncio.create_task(self._init_default_templates())
        self._add_pending_task(init_task1)
        self._add_pending_task(init_task2)

    def _add_pending_task(self, task: asyncio.Task) -> None:
        self._pending_tasks.append(task)
        task.add_done_callback(
            lambda t: self._pending_tasks.remove(t) if t in self._pending_tasks else None
        )

    async def _init_default_configs(self):
        self._configs = {
            NotificationChannel.EMAIL: NotificationConfig(
                channel=NotificationChannel.EMAIL,
                enabled=True,
                config={"smtp_host": "smtp.gmail.com", "smtp_port": 587, "from_email": "noreply@erp.com"},
            ),
            NotificationChannel.WHATSAPP: NotificationConfig(
                channel=NotificationChannel.WHATSAPP,
                enabled=True,
                config={"api_key": "dummy_whatsapp_key", "phone_number_id": "123456"},
            ),
            NotificationChannel.SMS: NotificationConfig(
                channel=NotificationChannel.SMS,
                enabled=True,
                config={"provider": "twilio", "account_sid": "dummy", "auth_token": "dummy"},
            ),
            NotificationChannel.SLACK: NotificationConfig(
                channel=NotificationChannel.SLACK,
                enabled=True,
                config={"webhook_url": "https://hooks.slack.com/services/dummy"},
            ),
            NotificationChannel.PUSH: NotificationConfig(
                channel=NotificationChannel.PUSH,
                enabled=True,
                config={"fcm_server_key": "dummy_fcm_key"},
            ),
            NotificationChannel.WEBHOOK: NotificationConfig(
                channel=NotificationChannel.WEBHOOK,
                enabled=True,
                config={"default_url": "https://webhook.site/dummy"},
            ),
        }

    async def _init_default_templates(self):
        if self._default_templates_loaded:
            return
        templates = [
            (NotificationTemplateType.JOURNAL_POSTED, NotificationChannel.EMAIL, "[ERP] Journal {voucher_number} Posted", "Journal {voucher_number} for {amount} has been posted. Date: {date}", ["voucher_number", "amount", "date"]),
            (NotificationTemplateType.INVOICE_CREATED, NotificationChannel.EMAIL, "Invoice {invoice_number} Created", "Invoice {invoice_number} for {customer} amount {amount} is due on {due_date}.", ["invoice_number", "customer", "amount", "due_date"]),
            (NotificationTemplateType.PAYMENT_RECEIVED, NotificationChannel.EMAIL, "Payment Received - {invoice_number}", "Payment of {amount} received for invoice {invoice_number}.", ["invoice_number", "amount"]),
            (NotificationTemplateType.APPROVAL_REQUIRED, NotificationChannel.SLACK, None, "Approval required: {document_type} {document_number} by {requester}. Please review.", ["document_type", "document_number", "requester"]),
            (NotificationTemplateType.SYSTEM_ALERT, NotificationChannel.SLACK, None, "⚠️ {alert_level}: {message}", ["alert_level", "message"]),
            (NotificationTemplateType.TAX_SUBMISSION, NotificationChannel.EMAIL, "Tax Submission {tax_type} {period}", "Tax {tax_type} for period {period} has been submitted. Status: {status}.", ["tax_type", "period", "status"]),
        ]
        for tt, ch, subj, body, vars_list in templates:
            template = NotificationTemplate(
                id=uuid4(),
                template_type=tt,
                channel=ch,
                subject_template=subj,
                body_template=body,
                variables=vars_list,
                is_active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self._templates[template.id] = template
            self._template_index[(tt, ch)] = template
        self._default_templates_loaded = True
        logger.info("Default notification templates loaded")

    async def _log_audit(self, action: str, notification_id: UUID, details: dict[str, Any]):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "notification_id": str(notification_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"NOTIFICATION AUDIT: {action} on {notification_id}")

    async def _check_rate_limit(self, channel: NotificationChannel, recipient: str) -> bool:
        key = f"{channel.value}:{recipient}"
        now = datetime.now(UTC)
        limit = 10
        window = timedelta(minutes=1)
        if key not in self._rate_limiters:
            self._rate_limiters[key] = []
        self._rate_limiters[key] = [ts for ts in self._rate_limiters[key] if now - ts < window]
        if len(self._rate_limiters[key]) >= limit:
            logger.warning(f"Rate limit exceeded for {key}")
            return False
        self._rate_limiters[key].append(now)
        return True

    async def _send_email(self, notification: Notification) -> bool:
        config = self._configs.get(NotificationChannel.EMAIL)
        if not config or not config.enabled:
            return False
        await asyncio.sleep(0.05)
        if secrets.randbelow(100) < 99:
            logger.info(f"EMAIL sent to {notification.recipient}: {notification.subject}")
            return True
        else:
            raise Exception("Simulated email delivery failure")

    async def _send_whatsapp(self, notification: Notification) -> bool:
        config = self._configs.get(NotificationChannel.WHATSAPP)
        if not config or not config.enabled:
            return False
        await asyncio.sleep(0.05)
        if secrets.randbelow(100) < 98:
            logger.info(f"WHATSAPP sent to {notification.recipient}: {notification.body[:50]}")
            return True
        else:
            raise Exception("Simulated WhatsApp failure")

    async def _send_sms(self, notification: Notification) -> bool:
        config = self._configs.get(NotificationChannel.SMS)
        if not config or not config.enabled:
            return False
        await asyncio.sleep(0.03)
        if secrets.randbelow(100) < 97:
            logger.info(f"SMS sent to {notification.recipient}: {notification.body[:50]}")
            return True
        else:
            raise Exception("Simulated SMS failure")

    async def _send_slack(self, notification: Notification) -> bool:
        config = self._configs.get(NotificationChannel.SLACK)
        if not config or not config.enabled:
            return False
        await asyncio.sleep(0.02)
        if secrets.randbelow(100) < 99:
            logger.info(f"SLACK sent to {notification.recipient}: {notification.body[:50]}")
            return True
        else:
            raise Exception("Simulated Slack failure")

    async def _send_push(self, notification: Notification) -> bool:
        config = self._configs.get(NotificationChannel.PUSH)
        if not config or not config.enabled:
            return False
        await asyncio.sleep(0.02)
        if secrets.randbelow(100) < 98:
            logger.info(f"PUSH sent to {notification.recipient}")
            return True
        else:
            raise Exception("Simulated push failure")

    async def _send_webhook(self, notification: Notification) -> bool:
        config = self._configs.get(NotificationChannel.WEBHOOK)
        if not config or not config.enabled:
            return False
        await asyncio.sleep(0.01)
        if secrets.randbelow(100) < 99:
            logger.info(f"WEBHOOK sent to {notification.recipient}")
            return True
        else:
            raise Exception("Simulated webhook failure")

    async def _send_notification(self, notification: Notification) -> bool:
        if notification.channel == NotificationChannel.EMAIL:
            return await self._send_email(notification)
        elif notification.channel == NotificationChannel.WHATSAPP:
            return await self._send_whatsapp(notification)
        elif notification.channel == NotificationChannel.SMS:
            return await self._send_sms(notification)
        elif notification.channel == NotificationChannel.SLACK:
            return await self._send_slack(notification)
        elif notification.channel == NotificationChannel.PUSH:
            return await self._send_push(notification)
        elif notification.channel == NotificationChannel.WEBHOOK:
            return await self._send_webhook(notification)
        else:
            raise ValueError(f"Unknown channel: {notification.channel}")

    async def start_worker(self, concurrency: int = 5):
        if self._running:
            logger.warning("Worker already running")
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop(concurrency))
        self._add_pending_task(self._worker_task)
        logger.info("Notification worker started")

    async def _worker_loop(self, concurrency: int):
        semaphore = asyncio.Semaphore(concurrency)
        while self._running:
            try:
                notification = await self._queue.get()
                async with semaphore:
                    task = asyncio.create_task(self._process_notification(notification))
                    self._add_pending_task(task)
            except asyncio.CancelledError:
                logger.debug("Notification worker loop cancelled")
                break
            except Exception as e:
                logger.error(f"Worker error: {e}")

    async def _process_notification(self, notification: Notification):
        try:
            if not await self._check_rate_limit(notification.channel, notification.recipient):
                notification.status = NotificationStatus.FAILED
                notification.error_message = "Rate limit exceeded"
                await self._update_notification(notification)
                await self._log_audit("RATE_LIMITED", notification.id, {"recipient": notification.recipient})
                return
            success = await self._send_notification(notification)
            if success:
                notification.status = NotificationStatus.DELIVERED
                notification.delivered_at = datetime.now(UTC)
                notification.error_message = None
                await self._update_notification(notification)
                await self._log_audit("DELIVERED", notification.id, {"channel": notification.channel.value})
            else:
                raise Exception("Send failed")
        except Exception as e:
            notification.retry_count += 1
            notification.error_message = str(e)
            if notification.retry_count >= 3:
                notification.status = NotificationStatus.FAILED
                await self._update_notification(notification)
                await self._log_audit("FAILED", notification.id, {"error": str(e), "retries": notification.retry_count})
            else:
                delay = min(2 ** (notification.retry_count - 1) * 5, 300)
                notification.status = NotificationStatus.RETRY
                notification.scheduled_at = datetime.now(UTC) + timedelta(seconds=delay)
                await self._update_notification(notification)
                task = asyncio.create_task(self._schedule_retry(notification, delay))
                self._add_pending_task(task)
                await self._log_audit("RETRY_SCHEDULED", notification.id, {"delay": delay, "retry_count": notification.retry_count})

    async def _schedule_retry(self, notification: Notification, delay: float):
        await asyncio.sleep(delay)
        await self._queue.put(notification)

    async def _update_notification(self, notification: Notification):
        notification.updated_at = datetime.now(UTC)
        async with self._lock:
            self._notifications[notification.id] = notification

    async def stop_worker(self):
        self._running = False
        if self._pending_tasks:
            for task in self._pending_tasks:
                if not task.done():
                    task.cancel()
            if self._pending_tasks:
                await asyncio.gather(*self._pending_tasks, return_exceptions=True)
                self._pending_tasks.clear()
        if self._worker_task:
            self._worker_task = None
        logger.info("Notification worker stopped")

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> list[UUID]:
        ids = []
        for recipient in to:
            nid = await self._send_raw(
                NotificationChannel.EMAIL, recipient, subject, body, priority, metadata, created_by
            )
            ids.append(nid)
        return ids

    async def send_whatsapp(
        self,
        to: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        return await self._send_raw(
            NotificationChannel.WHATSAPP, to, None, message, priority, metadata, created_by
        )

    async def send_sms(
        self,
        to: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        return await self._send_raw(
            NotificationChannel.SMS, to, None, message, priority, metadata, created_by
        )

    async def send_slack(
        self,
        channel: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        return await self._send_raw(
            NotificationChannel.SLACK, channel, None, message, priority, metadata, created_by
        )

    async def send_push(
        self,
        device_token: str,
        title: str,
        body: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        full_body = f"{title}\n{body}"
        return await self._send_raw(
            NotificationChannel.PUSH, device_token, title, full_body, priority, metadata, created_by
        )

    async def send_webhook(
        self,
        url: str,
        payload: dict[str, Any],
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        body = json.dumps(payload)
        return await self._send_raw(
            NotificationChannel.WEBHOOK, url, None, body, priority, metadata, created_by
        )

    async def _send_raw(
        self,
        channel: NotificationChannel,
        recipient: str,
        subject: str | None,
        body: str,
        priority: NotificationPriority,
        metadata: dict[str, Any] | None,
        created_by: UUID | None,
    ) -> UUID:
        nid = uuid4()
        now = datetime.now(UTC)
        notification = Notification(
            id=nid,
            channel=channel,
            recipient=recipient,
            subject=subject,
            body=body,
            priority=priority,
            status=NotificationStatus.PENDING,
            retry_count=0,
            scheduled_at=None,
            sent_at=None,
            delivered_at=None,
            error_message=None,
            metadata=metadata or {},
            created_at=now,
            created_by=created_by or UUID(int=0),
            updated_at=now,
        )
        async with self._lock:
            self._notifications[nid] = notification
        await self._queue.put(notification)
        await self._log_audit("ENQUEUED", nid, {"channel": channel.value, "recipient": recipient})
        return nid

    async def get_template(
        self, template_type: NotificationTemplateType, channel: NotificationChannel
    ) -> NotificationTemplate | None:
        return self._template_index.get((template_type, channel))

    async def render_template(
        self, template: NotificationTemplate, variables: dict[str, Any]
    ) -> tuple[str | None, str]:
        subject = None
        if template.subject_template:
            subject = template.subject_template.format(**variables)
        body = template.body_template.format(**variables)
        return subject, body

    async def send_with_template(
        self,
        template_type: NotificationTemplateType,
        channel: NotificationChannel,
        recipient: str,
        variables: dict[str, Any],
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID | None:
        template = await self.get_template(template_type, channel)
        if not template or not template.is_active:
            logger.warning(f"Template {template_type}/{channel.value} not found or inactive")
            return None
        subject, body = await self.render_template(template, variables)
        return await self._send_raw(channel, recipient, subject, body, priority, metadata, created_by)

    async def get_notification(self, notification_id: UUID) -> Notification | None:
        return self._notifications.get(notification_id)

    async def get_notifications(
        self,
        status: NotificationStatus | None = None,
        channel: NotificationChannel | None = None,
        recipient: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Notification]:
        result = list(self._notifications.values())
        if status:
            result = [n for n in result if n.status == status]
        if channel:
            result = [n for n in result if n.channel == channel]
        if recipient:
            result = [n for n in result if n.recipient == recipient]
        result.sort(key=lambda x: x.created_at, reverse=True)
        return result[offset : offset + limit]

    async def get_failed_notifications(self, limit: int = 100) -> list[Notification]:
        return [n for n in self._notifications.values() if n.status == NotificationStatus.FAILED][:limit]

    async def get_pending_count(self) -> int:
        return sum(1 for n in self._notifications.values() if n.status == NotificationStatus.PENDING)

    async def update_channel_config(
        self, channel: NotificationChannel, enabled: bool, config: dict[str, Any]
    ) -> None:
        async with self._lock:
            if channel not in self._configs:
                self._configs[channel] = NotificationConfig(channel=channel, enabled=enabled, config=config)
            else:
                self._configs[channel].enabled = enabled
                self._configs[channel].config.update(config)
        await self._log_audit("UPDATE_CONFIG", UUID(int=0), {"channel": channel.value, "enabled": enabled})

    async def add_template(
        self,
        template_type: NotificationTemplateType,
        channel: NotificationChannel,
        subject_template: str | None,
        body_template: str,
        variables: list[str],
        created_by: UUID,
    ) -> UUID:
        tid = uuid4()
        now = datetime.now(UTC)
        template = NotificationTemplate(
            id=tid,
            template_type=template_type,
            channel=channel,
            subject_template=subject_template,
            body_template=body_template,
            variables=variables,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._templates[tid] = template
            self._template_index[(template_type, channel)] = template
        await self._log_audit("ADD_TEMPLATE", tid, {"type": template_type.value, "channel": channel.value})
        return tid

    async def delete_template(self, template_id: UUID) -> bool:
        template = self._templates.get(template_id)
        if not template:
            return False
        async with self._lock:
            key = (template.template_type, template.channel)
            if key in self._template_index:
                del self._template_index[key]
            del self._templates[template_id]
        await self._log_audit("DELETE_TEMPLATE", template_id, {})
        return True

    async def cancel_notification(self, notification_id: UUID) -> bool:
        notification = self._notifications.get(notification_id)
        if not notification or notification.status not in (NotificationStatus.PENDING, NotificationStatus.RETRY):
            return False
        notification.status = NotificationStatus.CANCELLED
        notification.updated_at = datetime.now(UTC)
        await self._update_notification(notification)
        await self._log_audit("CANCEL", notification_id, {})
        return True

    async def get_statistics(self) -> dict[str, Any]:
        all_notifications = list(self._notifications.values())
        total = len(all_notifications)
        sent = sum(1 for n in all_notifications if n.status == NotificationStatus.DELIVERED)
        failed = sum(1 for n in all_notifications if n.status == NotificationStatus.FAILED)
        pending = sum(1 for n in all_notifications if n.status == NotificationStatus.PENDING)
        retry = sum(1 for n in all_notifications if n.status == NotificationStatus.RETRY)
        by_channel = {ch.value: sum(1 for n in all_notifications if n.channel == ch) for ch in NotificationChannel}
        return {
            "total_notifications": total,
            "delivered": sent,
            "failed": failed,
            "pending": pending,
            "retry": retry,
            "by_channel": by_channel,
            "active_templates": len(self._templates),
            "queue_size": self._queue.qsize(),
            "worker_running": self._running,
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_notifications": len(self._notifications),
            "pending_count": await self.get_pending_count(),
            "worker_running": self._running,
            "channels_enabled": {ch.value: cfg.enabled for ch, cfg in self._configs.items()},
            "templates_count": len(self._templates),
            "audit_log_size": len(self._audit_log),
        }


# ==================== ALIAS UNTUK DI CONTAINER ====================

# Alias untuk kepatuhan terhadap nama yang diharapkan DI container
NotificationPortImpl = InMemoryNotification


# ==================== EXPORTS ====================

__all__ = [
    "InMemoryNotification",
    "Notification",
    "NotificationChannel",
    "NotificationConfig",
    "NotificationPort",
    "NotificationPortImpl",
    "NotificationPriority",
    "NotificationStatus",
    "NotificationTemplate",
    "NotificationTemplateType",
]
