#!/usr/bin/env python3
"""
Integration: Transactional Outbox Pattern (Pure Mock Version)
Menguji konsep outbox pattern dengan mock, tanpa database atau broker nyata.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest


# ============================================================================
# 1. Mock domain Journal
# ============================================================================
class MockJournal:
    def __init__(self, journal_id: str):
        self.journal_id = journal_id
        self.events = []

    def create(self, description: str):
        self.events.append(
            MagicMock(
                to_dict=MagicMock(
                    return_value={"type": "JournalCreated", "journal_id": self.journal_id}
                )
            )
        )

    def add_line(self, account: str, debit: Decimal = Decimal(0), credit: Decimal = Decimal(0)):
        pass

    def post(self):
        self.events.append(
            MagicMock(
                to_dict=MagicMock(
                    return_value={"type": "JournalPosted", "journal_id": self.journal_id}
                )
            )
        )


# ============================================================================
# 2. Mock Unit of Work (mendukung context manager)
# ============================================================================
class MockUnitOfWork:
    def __init__(self, session):
        self.session = session
        self.committed = False
        self.rolled_back = False
        self.journals = MagicMock()
        self.outbox_messages = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rolled_back = True
        else:
            self.committed = True

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def add_outbox_message(self, msg: dict):
        self.outbox_messages.append(msg)
        self.session.append(msg)  # juga simpan ke session untuk relay


# ============================================================================
# 3. Mock Outbox Relay Service
# ============================================================================
class MockOutboxRelayService:
    def __init__(self, session_factory, kafka_broker: str | None = None):
        self.session_factory = session_factory
        self.kafka_broker = kafka_broker
        self.published = []

    def process_pending_messages(self, batch_size: int = 100) -> int:
        session = self.session_factory()
        pending = [msg for msg in session if msg.get("status") == "PENDING"]
        count = 0
        for msg in pending:
            msg["status"] = "PUBLISHED"
            self.published.append(msg)
            count += 1
        return count


# ============================================================================
# 4. Fixtures
# ============================================================================
@pytest.fixture
def session():
    """Shared session (list) untuk semua komponen."""
    return []


@pytest.fixture
def session_factory(session):
    def factory():
        return session

    return factory


@pytest.fixture
def uow(session):
    return MockUnitOfWork(session)


@pytest.fixture
def relay_service(session_factory):
    return MockOutboxRelayService(session_factory)


# ============================================================================
# 5. Test Cases
# ============================================================================
def test_outbox_message_stored_in_transaction(uow):
    """
    Test bahwa event dalam transaksi menyebabkan outbox message tersimpan.
    """
    journal = MockJournal("JRN-001")
    journal.create("Test")
    journal.add_line("101", Decimal("1000000"))
    journal.add_line("201", Decimal("0"), Decimal("1000000"))
    journal.post()

    with uow:
        uow.journals.add(journal)
        for event in journal.events:
            msg = {
                "aggregate_id": journal.journal_id,
                "event_type": event.to_dict()["type"],
                "payload": event.to_dict(),
                "status": "PENDING",
            }
            uow.add_outbox_message(msg)
        uow.commit()

    assert len(uow.outbox_messages) == len(journal.events)
    for msg in uow.outbox_messages:
        assert msg["status"] == "PENDING"
        assert msg["aggregate_id"] == "JRN-001"
    assert len(uow.session) == len(journal.events)  # session juga berisi pesan


def test_outbox_relay_publishes_messages(session, relay_service):
    """
    Test bahwa relay service mengubah status PENDING menjadi PUBLISHED.
    """
    # Tambahkan pesan ke session
    session.append(
        {
            "id": 1,
            "event_type": "JournalPosted",
            "payload": {"journal_id": "JRN-001"},
            "status": "PENDING",
        }
    )
    session.append(
        {
            "id": 2,
            "event_type": "JournalPosted",
            "payload": {"journal_id": "JRN-002"},
            "status": "PENDING",
        }
    )

    processed = relay_service.process_pending_messages(batch_size=10)

    assert processed == 2
    assert len(relay_service.published) == 2
    for msg in session:
        assert msg["status"] == "PUBLISHED"
