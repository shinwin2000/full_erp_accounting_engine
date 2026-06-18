#!/usr/bin/env python3
"""
Unit: Journal Service
Menguji service untuk jurnal: create, validate, post, reverse.
Menggunakan mock implementation untuk menghindari dependency pada domain nyata.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

# ============================================================================
# MOCK DOMAIN CLASSES
# ============================================================================


class MockJournalLine:
    def __init__(self, account: str, debit: Decimal, credit: Decimal):
        self.account = account
        self.debit = debit
        self.credit = credit


class MockJournalAggregate:
    def __init__(self, journal_id: str | None = None, description: str = ""):
        self.journal_id = journal_id or str(uuid4())
        self.description = description
        self.lines: list[MockJournalLine] = []
        self.status = "DRAFT"
        self.is_reversal = False
        self.reversal_of = None

    def create(self, description: str):
        self.description = description

    def add_line(self, account: str, debit: Decimal, credit: Decimal):
        self.lines.append(MockJournalLine(account, debit, credit))

    def post(self):
        if sum(line.debit for line in self.lines) != sum(line.credit for line in self.lines):
            raise ValueError("Debit and credit totals are not equal")
        self.status = "POSTED"

    def reverse(self, reason: str):
        reversed_journal = MockJournalAggregate()
        reversed_journal.is_reversal = True
        reversed_journal.reversal_of = self.journal_id
        return reversed_journal


# ============================================================================
# MOCK REPOSITORY & UNIT OF WORK
# ============================================================================


class MockJournalRepository:
    def __init__(self):
        self._store: dict[str, MockJournalAggregate] = {}
        self.add_called = False
        self.update_called = False
        self.get_called_with = None

    def add(self, journal: MockJournalAggregate):
        self.add_called = True
        self._store[journal.journal_id] = journal

    def get(self, journal_id: str) -> MockJournalAggregate | None:
        self.get_called_with = journal_id
        return self._store.get(journal_id)

    def update(self, journal: MockJournalAggregate):
        self.update_called = True
        self._store[journal.journal_id] = journal


class MockUnitOfWork:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


# ============================================================================
# MOCK JOURNAL SERVICE
# ============================================================================


class MockJournalService:
    def __init__(self, repository: MockJournalRepository, uow: MockUnitOfWork):
        self.repo = repository
        self.uow = uow

    def create_journal(self, description: str, created_by: str = "") -> MockJournalAggregate:
        journal = MockJournalAggregate(description=description)
        with self.uow:
            self.repo.add(journal)
            self.uow.commit()
        return journal

    def add_line(self, journal_id: str, account: str, debit: Decimal, credit: Decimal):
        with self.uow:
            journal = self.repo.get(journal_id)
            if not journal:
                raise ValueError("Journal not found")
            journal.add_line(account, debit, credit)
            self.repo.update(journal)
            self.uow.commit()

    def post(self, journal_id: str):
        with self.uow:
            journal = self.repo.get(journal_id)
            if not journal:
                raise ValueError("Journal not found")
            journal.post()
            self.repo.update(journal)
            self.uow.commit()

    def reverse(self, journal_id: str, reason: str) -> MockJournalAggregate:
        with self.uow:
            journal = self.repo.get(journal_id)
            if not journal:
                raise ValueError("Journal not found")
            reversed_journal = journal.reverse(reason)
            self.repo.add(reversed_journal)
            self.uow.commit()
            return reversed_journal


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_repo():
    return MockJournalRepository()


@pytest.fixture
def mock_uow():
    return MockUnitOfWork()


@pytest.fixture
def service(mock_repo, mock_uow):
    return MockJournalService(repository=mock_repo, uow=mock_uow)


# ============================================================================
# TESTS
# ============================================================================


def test_create_journal(service, mock_repo, mock_uow):
    journal = service.create_journal(description="Test entry", created_by="user1")
    assert journal.journal_id is not None
    assert journal.status == "DRAFT"
    assert mock_repo.add_called is True
    assert mock_uow.committed is True


def test_add_line_to_journal(service, mock_repo):
    # Simpan jurnal terlebih dahulu
    journal = MockJournalAggregate(journal_id="JRN-001", description="Test")
    mock_repo.add(journal)

    service.add_line(
        journal_id="JRN-001", account="101", debit=Decimal("1000000"), credit=Decimal("0")
    )
    assert len(journal.lines) == 1
    assert mock_repo.update_called is True


def test_post_journal_validation_fails_if_unbalanced(service, mock_repo, mock_uow):
    journal = MockJournalAggregate(journal_id="JRN-002")
    journal.create("Unbalanced")
    journal.add_line(account="101", debit=Decimal("1000000"), credit=Decimal("0"))
    mock_repo.add(journal)

    with pytest.raises(ValueError, match="Debit and credit totals are not equal"):
        service.post(journal_id="JRN-002")
    assert mock_uow.committed is False


def test_post_journal_success(service, mock_repo, mock_uow):
    journal = MockJournalAggregate(journal_id="JRN-003")
    journal.create("Balanced")
    journal.add_line(account="101", debit=Decimal("1000000"), credit=Decimal("0"))
    journal.add_line(account="201", debit=Decimal("0"), credit=Decimal("1000000"))
    mock_repo.add(journal)

    service.post(journal_id="JRN-003")
    assert journal.status == "POSTED"
    assert mock_repo.update_called is True
    assert mock_uow.committed is True


def test_reverse_journal(service, mock_repo):
    journal = MockJournalAggregate(journal_id="JRN-003")
    journal.create("Original")
    journal.add_line(account="101", debit=Decimal("1000"), credit=Decimal("0"))
    journal.add_line(account="201", debit=Decimal("0"), credit=Decimal("1000"))
    journal.post()
    mock_repo.add(journal)

    reversed_journal = service.reverse(journal_id="JRN-003", reason="Error correction")
    assert reversed_journal.is_reversal is True
    assert reversed_journal.reversal_of == "JRN-003"
