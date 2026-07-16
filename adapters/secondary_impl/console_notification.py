#!/usr/bin/env python3
"""
Module: console_notification.py
Layer: Adapters (Secondary)
Responsibility: Implementasi NotificationPort yang hanya mencetak notifikasi ke console.
Digunakan untuk development, testing, atau fallback jika layanan notifikasi nyata belum siap.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ports.primary.notification_port import (
    Notification,
    NotificationChannel,
    NotificationConfig,
    NotificationPort,
    NotificationPriority,
    NotificationStatus,
    NotificationTemplate,
    NotificationTemplateType,
)

logger = logging.getLogger(__name__)


class ConsoleNotification(NotificationPort):
    """
    Implementasi NotificationPort yang mencetak semua notifikasi ke console.
    Tidak mengirim ke layanan eksternal, hanya log untuk debugging.
    """

    def __init__(self):
        self._notifications: dict[UUID, Notification] = {}
        self._templates: dict[UUID, NotificationTemplate] = {}
        self._template_index: dict[tuple[NotificationTemplateType, NotificationChannel], NotificationTemplate] = {}
        self._configs: dict[NotificationChannel, NotificationConfig] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        # Inisialisasi konfigurasi default (semua channel enabled dengan dummy config)
        self._init_default_configs()
        # Inisialisasi template default (opsional)
        self._init_default_templates()

    def _init_default_configs(self):
        """Set konfigurasi default untuk semua channel."""
        self._configs = {
            NotificationChannel.EMAIL: NotificationConfig(
                channel=NotificationChannel.EMAIL,
                enabled=True,
                config={"from_email": "console@erp.local", "smtp_host": "localhost"}
            ),
            NotificationChannel.WHATSAPP: NotificationConfig(
                channel=NotificationChannel.WHATSAPP,
                enabled=True,
                config={"api_key": "console_dummy"}
            ),
            NotificationChannel.SMS: NotificationConfig(
                channel=NotificationChannel.SMS,
                enabled=True,
                config={"provider": "console"}
            ),
            NotificationChannel.SLACK: NotificationConfig(
                channel=NotificationChannel.SLACK,
                enabled=True,
                config={"webhook_url": "console://dummy"}
            ),
            NotificationChannel.PUSH: NotificationConfig(
                channel=NotificationChannel.PUSH,
                enabled=True,
                config={"fcm_key": "console_dummy"}
            ),
            NotificationChannel.WEBHOOK: NotificationConfig(
                channel=NotificationChannel.WEBHOOK,
                enabled=True,
                config={"default_url": "console://dummy"}
            ),
        }

    def _init_default_templates(self):
        """(Opsional) tambahkan beberapa template default untuk demonstrasi."""
        templates = [
            (NotificationTemplateType.JOURNAL_POSTED, NotificationChannel.EMAIL,
             "[ERP] Journal {voucher_number} Posted",
             "Journal {voucher_number} for {amount} has been posted on {date}.",
             ["voucher_number", "amount", "date"]),
            (NotificationTemplateType.INVOICE_CREATED, NotificationChannel.EMAIL,
             "Invoice {invoice_number} Created",
             "Invoice {invoice_number} for {customer} amount {amount} is due on {due_date}.",
             ["invoice_number", "customer", "amount", "due_date"]),
            (NotificationTemplateType.PAYMENT_RECEIVED, NotificationChannel.EMAIL,
             "Payment Received - {invoice_number}",
             "Payment of {amount} received for invoice {invoice_number}.",
             ["invoice_number", "amount"]),
            (NotificationTemplateType.APPROVAL_REQUIRED, NotificationChannel.SLACK,
             None,
             "Approval required: {document_type} {document_number} by {requester}. Please review.",
             ["document_type", "document_number", "requester"]),
            (NotificationTemplateType.SYSTEM_ALERT, NotificationChannel.SLACK,
             None,
             "⚠️ {alert_level}: {message}",
             ["alert_level", "message"]),
        ]
        for tt, ch, subj, body, vars_list in templates:
            tid = uuid.uuid4()
            template = NotificationTemplate(
                id=tid,
                template_type=tt,
                channel=ch,
                subject_template=subj,
                body_template=body,
                variables=vars_list,
                is_active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self._templates[tid] = template
            self._template_index[(tt, ch)] = template

    async def _log_audit(self, action: str, notification_id: UUID, details: dict[str, Any]):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "notification_id": str(notification_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"CONSOLE NOTIFICATION AUDIT: {action} on {notification_id}")

    async def _send_raw(self, notification: Notification) -> bool:
        """Cetak notifikasi ke console dan tandai sebagai delivered."""
        # Print dengan format yang rapi
        print("\n" + "=" * 60)
        print(f"📨 NOTIFICATION [{notification.channel.value.upper()}]")
        print(f"   To       : {notification.recipient}")
        if notification.subject:
            print(f"   Subject  : {notification.subject}")
        print(f"   Body     : {notification.body[:200]}{'...' if len(notification.body) > 200 else ''}")
        print(f"   Priority : {notification.priority.name}")
        print(f"   Metadata : {json.dumps(notification.metadata, indent=2)}")
        print("=" * 60 + "\n")
        return True

    # ==================== PUBLIC METHODS ====================

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
            nid = await self._create_and_send(
                channel=NotificationChannel.EMAIL,
                recipient=recipient,
                subject=subject,
                body=body,
                priority=priority,
                metadata=metadata,
                created_by=created_by,
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
        return await self._create_and_send(
            channel=NotificationChannel.WHATSAPP,
            recipient=to,
            subject=None,
            body=message,
            priority=priority,
            metadata=metadata,
            created_by=created_by,
        )

    async def send_sms(
        self,
        to: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        return await self._create_and_send(
            channel=NotificationChannel.SMS,
            recipient=to,
            subject=None,
            body=message,
            priority=priority,
            metadata=metadata,
            created_by=created_by,
        )

    async def send_slack(
        self,
        channel: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        return await self._create_and_send(
            channel=NotificationChannel.SLACK,
            recipient=channel,
            subject=None,
            body=message,
            priority=priority,
            metadata=metadata,
            created_by=created_by,
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
        return await self._create_and_send(
            channel=NotificationChannel.PUSH,
            recipient=device_token,
            subject=title,
            body=full_body,
            priority=priority,
            metadata=metadata,
            created_by=created_by,
        )

    async def send_webhook(
        self,
        url: str,
        payload: dict[str, Any],
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> UUID:
        body = json.dumps(payload, indent=2)
        return await self._create_and_send(
            channel=NotificationChannel.WEBHOOK,
            recipient=url,
            subject=None,
            body=body,
            priority=priority,
            metadata=metadata,
            created_by=created_by,
        )

    async def _create_and_send(
        self,
        channel: NotificationChannel,
        recipient: str,
        subject: str | None,
        body: str,
        priority: NotificationPriority,
        metadata: dict[str, Any] | None,
        created_by: UUID | None,
    ) -> UUID:
        nid = uuid.uuid4()
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

        # Kirim (langsung sukses)
        success = await self._send_raw(notification)
        if success:
            notification.status = NotificationStatus.DELIVERED
            notification.delivered_at = datetime.now(UTC)
            notification.sent_at = datetime.now(UTC)
        else:
            notification.status = NotificationStatus.FAILED
            notification.error_message = "Console send failed (simulated)"

        async with self._lock:
            self._notifications[nid] = notification

        await self._log_audit("SEND", nid, {"channel": channel.value, "recipient": recipient})
        return nid

    # ==================== TEMPLATE METHODS ====================

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
        return await self._create_and_send(
            channel=channel,
            recipient=recipient,
            subject=subject,
            body=body,
            priority=priority,
            metadata=metadata,
            created_by=created_by,
        )

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

    # ==================== QUERY METHODS ====================

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

    # ==================== CONFIG & TEMPLATE MANAGEMENT ====================

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
        tid = uuid.uuid4()
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
        async with self._lock:
            self._notifications[notification_id] = notification
        await self._log_audit("CANCEL", notification_id, {})
        return True

    # ==================== WORKER (dummy) ====================

    async def start_worker(self, concurrency: int = 5):
        logger.info("ConsoleNotification worker started (no-op)")

    async def stop_worker(self):
        logger.info("ConsoleNotification worker stopped (no-op)")

    # ==================== STATISTICS & AUDIT ====================

    async def get_statistics(self) -> dict[str, Any]:
        all_notifications = list(self._notifications.values())
        total = len(all_notifications)
        delivered = sum(1 for n in all_notifications if n.status == NotificationStatus.DELIVERED)
        failed = sum(1 for n in all_notifications if n.status == NotificationStatus.FAILED)
        pending = sum(1 for n in all_notifications if n.status == NotificationStatus.PENDING)
        retry = sum(1 for n in all_notifications if n.status == NotificationStatus.RETRY)
        by_channel = {ch.value: sum(1 for n in all_notifications if n.channel == ch) for ch in NotificationChannel}
        return {
            "total_notifications": total,
            "delivered": delivered,
            "failed": failed,
            "pending": pending,
            "retry": retry,
            "by_channel": by_channel,
            "active_templates": len(self._templates),
            "worker_running": False,  # no real worker
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_notifications": len(self._notifications),
            "pending_count": await self.get_pending_count(),
            "worker_running": False,
            "channels_enabled": {ch.value: cfg.enabled for ch, cfg in self._configs.items()},
            "templates_count": len(self._templates),
            "audit_log_size": len(self._audit_log),
        }


__all__ = ["ConsoleNotification"]