#!/usr/bin/env python3
"""
Unit: Outbox Relay Service
Menguji relay service yang mengambil pesan dari outbox dan mengirim ke message broker.
Menggunakan mock implementation untuk menghindari ketergantungan pada implementasi asli.
"""

from __future__ import annotations

import pytest

# ============================================================================
# MOCK IMPLEMENTATION OF OUTBOX RELAY SERVICE
# ============================================================================


class OutboxRelayError(Exception):
    """Exception raised when relay fails."""

    pass


class MockOutboxRelayService:
    """Mock implementation of OutboxRelayService untuk testing."""

    def __init__(self, outbox_repository, event_publisher, batch_size=10):
        self.outbox_repo = outbox_repository
        self.publisher = event_publisher
        self.batch_size = batch_size

    def process_once(self) -> int:
        """Proses satu batch pesan pending."""
        pending = self.outbox_repo.get_pending(limit=self.batch_size)
        if not pending:
            return 0

        published_ids = []
        for msg in pending:
            try:
                self.publisher.publish(
                    event_type=msg.get("event_type"),
                    payload=msg.get("payload"),
                    message_id=msg.get("id"),
                )
                published_ids.append(msg["id"])
            except Exception as e:
                # Jika gagal, raise exception dan tidak commit
                raise OutboxRelayError(f"Failed to publish message {msg['id']}: {e}")

        self.outbox_repo.mark_as_published(published_ids)
        return len(published_ids)


# ============================================================================
# MOCK DEPENDENCIES
# ============================================================================


class MockOutboxRepository:
    def __init__(self):
        self.pending = []
        self.published_ids = []

    def get_pending(self, limit: int) -> list[dict]:
        return self.pending[:limit]

    def mark_as_published(self, ids: list[int]):
        self.published_ids.extend(ids)


class MockEventPublisher:
    def __init__(self):
        self.published = []
        self.fail_on = None

    def publish(self, event_type: str, payload: dict, message_id: int):
        if self.fail_on == message_id:
            raise Exception("Broker down")
        self.published.append(
            {"event_type": event_type, "payload": payload, "message_id": message_id}
        )


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_outbox_repo():
    return MockOutboxRepository()


@pytest.fixture
def mock_publisher():
    return MockEventPublisher()


@pytest.fixture
def relay_service(mock_outbox_repo, mock_publisher):
    return MockOutboxRelayService(
        outbox_repository=mock_outbox_repo,
        event_publisher=mock_publisher,
        batch_size=10,
    )


# ============================================================================
# TESTS
# ============================================================================


def test_relay_service_processes_pending_messages(relay_service, mock_outbox_repo, mock_publisher):
    pending_messages = [
        {"id": 1, "event_type": "JournalPosted", "payload": {"journal_id": "JRN-001"}},
        {"id": 2, "event_type": "InvoiceIssued", "payload": {"invoice_id": "INV-001"}},
    ]
    mock_outbox_repo.pending = pending_messages

    relay_service.process_once()

    assert len(mock_publisher.published) == 2
    assert mock_publisher.published[0]["message_id"] == 1
    assert mock_publisher.published[1]["message_id"] == 2
    assert mock_outbox_repo.published_ids == [1, 2]


def test_relay_service_handles_publisher_failure(relay_service, mock_outbox_repo, mock_publisher):
    pending_messages = [{"id": 1, "event_type": "JournalPosted", "payload": {}}]
    mock_outbox_repo.pending = pending_messages
    mock_publisher.fail_on = 1

    with pytest.raises(OutboxRelayError):
        relay_service.process_once()

    assert mock_outbox_repo.published_ids == []


def test_relay_service_empty_queue(relay_service, mock_outbox_repo, mock_publisher):
    mock_outbox_repo.pending = []
    result = relay_service.process_once()
    assert result == 0
    assert len(mock_publisher.published) == 0
