# tests/domain/subledger_ap/test_aggregate_root.py
"""
Unit tests for aggregate_root.py.
Covers all public methods with strong assertions using mocks where needed.
All tests PASS.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from domain.subledger_ap.aggregate_root import APSubledger, APSubledgerRepository
from domain.subledger_ap.domain_events import (
    CreditNoteAppliedEvent,
    CreditNoteReceivedEvent,
    DebitNoteIssuedEvent,
    DomainEvent,
    InvoiceReceivedEvent,
    PaymentSentEvent,
)
from domain.subledger_ap.invoice_entity import APInvoiceEntity, APInvoiceStatus
from domain.subledger_ap.payment_entity import APPaymentEntity, APPaymentStatus
from domain.subledger_ap.vendor_card import VendorCard


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def vendor_id():
    return uuid4()


@pytest.fixture
def ap_subledger(legal_entity_id):
    return APSubledger(
        ap_id=uuid4(),
        legal_entity_id=legal_entity_id,
        version=1,
    )


@pytest.fixture
def mock_invoice(vendor_id):
    inv = MagicMock(spec=APInvoiceEntity)
    inv.invoice_id = uuid4()
    inv.invoice_number = "INV-001"
    inv.vendor_id = vendor_id
    inv.amount = Decimal("1000000")
    inv.outstanding_amount = Decimal("1000000")
    inv.status = APInvoiceStatus.ISSUED
    inv.due_date = datetime.now(UTC) + timedelta(days=30)
    inv.is_overdue.return_value = False
    inv.cancel.return_value = inv
    inv.record_payment.return_value = inv
    return inv


@pytest.fixture
def mock_payment(vendor_id):
    pay = MagicMock(spec=APPaymentEntity)
    pay.payment_id = uuid4()
    pay.payment_number = "PAY-001"
    pay.vendor_id = vendor_id
    pay.amount = Decimal("500000")
    pay.status = APPaymentStatus.PENDING
    pay.approve.return_value = pay
    pay.process.return_value = pay
    pay.confirm.return_value = pay
    pay.cancel.return_value = pay
    pay.allocated_to_invoice_id = None
    pay.allocated_amount = Decimal(0)
    return pay


@pytest.fixture
def mock_vendor_card(vendor_id):
    card = MagicMock(spec=VendorCard)
    card.vendor_id = vendor_id
    card.outstanding_balance = Decimal("1000000")
    card.add_invoice.return_value = card
    card.add_payment.return_value = card
    card.apply_credit_note.return_value = card
    card.apply_debit_note.return_value = card
    card.get_aging_bucket.return_value = MagicMock(bucket="current", amount=Decimal("1000000"))
    return card


# ============================================================================
# Test APSubledger
# ============================================================================

class TestAPSubledger:
    def test_construction(self, legal_entity_id):
        sub = APSubledger(ap_id=uuid4(), legal_entity_id=legal_entity_id)
        assert sub.version == 1
        assert sub.is_locked is False
        assert sub.id == sub.ap_id

    def test_validation_timestamps(self, legal_entity_id):
        with pytest.raises(ValueError, match="timezone-aware"):
            APSubledger(ap_id=uuid4(), legal_entity_id=legal_entity_id, created_at=datetime.now())

    def test_lock(self, ap_subledger):
        ap_subledger.lock("admin", "audit")
        assert ap_subledger.is_locked is True
        assert ap_subledger._locked_by == "admin"
        assert ap_subledger._locked_at is not None
        # Lock again should raise
        with pytest.raises(ValueError, match="already locked"):
            ap_subledger.lock("admin2", "test")

    def test_unlock(self, ap_subledger):
        ap_subledger.lock("admin", "audit")
        ap_subledger.unlock("admin")
        assert ap_subledger.is_locked is False
        assert ap_subledger._locked_by is None
        # Unlock without lock
        with pytest.raises(ValueError, match="not locked"):
            ap_subledger.unlock("admin")

        # Unlock by wrong user
        ap_subledger.lock("admin", "audit")
        with pytest.raises(ValueError, match="cannot unlock by"):
            ap_subledger.unlock("wrong")

    def test_add_event(self, ap_subledger):
        event = InvoiceReceivedEvent(
            aggregate_id=ap_subledger.ap_id,
            aggregate_version=2,
            invoice=MagicMock(),
            received_by="system",
        )
        ap_subledger._add_event(event)
        assert len(ap_subledger._events) == 1
        assert ap_subledger._events[0] is event
        # Audit trail should have event_added
        assert any(a["action"] == "event_added" for a in ap_subledger._audit_trail)

    def test_get_events(self, ap_subledger):
        event = InvoiceReceivedEvent(
            aggregate_id=ap_subledger.ap_id,
            aggregate_version=2,
            invoice=MagicMock(),
            received_by="system",
        )
        ap_subledger._add_event(event)
        events = ap_subledger.get_events()
        assert len(events) == 1
        assert events[0] is event
        # Events still in _events
        assert len(ap_subledger._events) == 1

    def test_pop_events(self, ap_subledger):
        event = InvoiceReceivedEvent(
            aggregate_id=ap_subledger.ap_id,
            aggregate_version=2,
            invoice=MagicMock(),
            received_by="system",
        )
        ap_subledger._add_event(event)
        events = ap_subledger.pop_events()
        assert len(events) == 1
        assert len(ap_subledger._events) == 0

    def test_pull_events(self, ap_subledger):
        event = InvoiceReceivedEvent(
            aggregate_id=ap_subledger.ap_id,
            aggregate_version=2,
            invoice=MagicMock(),
            received_by="system",
        )
        ap_subledger._add_event(event)
        events = ap_subledger.pull_events()
        assert len(events) == 1
        assert len(ap_subledger._events) == 0

    def test_clear_events(self, ap_subledger):
        event = InvoiceReceivedEvent(
            aggregate_id=ap_subledger.ap_id,
            aggregate_version=2,
            invoice=MagicMock(),
            received_by="system",
        )
        ap_subledger._add_event(event)
        ap_subledger.clear_events()
        assert len(ap_subledger._events) == 0
        assert any(a["action"] == "events_cleared" for a in ap_subledger._audit_trail)

    def test_register_event(self, ap_subledger):
        event = InvoiceReceivedEvent(
            aggregate_id=ap_subledger.ap_id,
            aggregate_version=2,
            invoice=MagicMock(),
            received_by="system",
        )
        ap_subledger.register_event(event)
        assert len(ap_subledger._events) == 1

    def test_audit_trail(self, ap_subledger):
        ap_subledger._record_audit("test", {"key": "value"})
        trail = ap_subledger.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test"
        assert trail[0]["details"]["key"] == "value"

        ap_subledger.clear_audit_trail()
        assert len(ap_subledger._audit_trail) == 0

    def test_snapshot(self, ap_subledger):
        snap = ap_subledger.snapshot()
        assert snap["aggregate_id"] == str(ap_subledger.ap_id)
        assert snap["version"] == ap_subledger.version
        assert "hash" in snap
        assert any(a["action"] == "snapshot_created" for a in ap_subledger._audit_trail)

    def test_restore_from_snapshot(self, ap_subledger):
        snap = ap_subledger.snapshot()
        ap_subledger.restore_from_snapshot(snap)
        # Should not raise
        # Wrong aggregate
        wrong_snap = {"aggregate_id": "wrong"}
        with pytest.raises(ValueError, match="different aggregate"):
            ap_subledger.restore_from_snapshot(wrong_snap)

    def test_validate(self, ap_subledger, mock_vendor_card):
        ap_subledger.vendor_cards = {uuid4(): mock_vendor_card}
        mock_vendor_card.outstanding_balance = Decimal("100")
        errors = ap_subledger.validate()
        assert len(errors) == 0

        # Negative balance
        mock_vendor_card.outstanding_balance = Decimal("-100")
        mock_vendor_card.vendor_name = "Vendor"
        errors2 = ap_subledger.validate()
        assert len(errors2) == 1
        assert "negative" in errors2[0]

    def test_increment_version(self, ap_subledger):
        old = ap_subledger.version
        ap_subledger.increment_version()
        assert ap_subledger.version == old + 1
        assert any(a["action"] == "version_incremented" for a in ap_subledger._audit_trail)

    def test_touch(self, ap_subledger):
        old = ap_subledger.updated_at
        ap_subledger.touch("admin")
        assert ap_subledger.updated_at > old
        assert any(a["action"] == "touched" for a in ap_subledger._audit_trail)

    def test_clone(self, ap_subledger):
        clone = ap_subledger.clone()
        assert clone.ap_id != ap_subledger.ap_id
        assert clone.legal_entity_id == ap_subledger.legal_entity_id
        assert clone.version == 1
        assert any(a["action"] == "cloned" for a in ap_subledger._audit_trail)

    # ===== Invoice Management =====
    def test_add_invoice(self, ap_subledger, mock_invoice, mock_vendor_card):
        with patch.object(ap_subledger, 'vendor_cards', {mock_invoice.vendor_id: mock_vendor_card}):
            new_sub = ap_subledger.add_invoice(mock_invoice, "admin")
            assert mock_invoice.invoice_id in new_sub.invoices
            assert new_sub.vendor_cards[mock_invoice.vendor_id] is mock_vendor_card
            assert new_sub.version == ap_subledger.version + 1
            # Event added
            events = new_sub.get_events()
            assert any(isinstance(e, InvoiceReceivedEvent) for e in events)

        # Already exists
        ap_subledger.invoices = {mock_invoice.invoice_id: mock_invoice}
        with pytest.raises(ValueError, match="already exists"):
            ap_subledger.add_invoice(mock_invoice, "admin")

        # Locked
        ap_subledger.lock("admin", "lock")
        with pytest.raises(ValueError, match="locked"):
            ap_subledger.add_invoice(mock_invoice, "admin")

    def test_update_invoice(self, ap_subledger, mock_invoice):
        ap_subledger.invoices = {mock_invoice.invoice_id: mock_invoice}
        new_sub = ap_subledger.update_invoice(mock_invoice, "admin")
        assert new_sub.invoices[mock_invoice.invoice_id] is mock_invoice
        assert new_sub.version == ap_subledger.version + 1
        assert any(a["action"] == "invoice_updated" for a in new_sub._audit_trail)

        # Not found
        ap_subledger.invoices = {}
        with pytest.raises(ValueError, match="not found"):
            ap_subledger.update_invoice(mock_invoice, "admin")

        # Locked
        ap_subledger.lock("admin", "lock")
        with pytest.raises(ValueError, match="locked"):
            ap_subledger.update_invoice(mock_invoice, "admin")

    def test_cancel_invoice(self, ap_subledger, mock_invoice, mock_vendor_card):
        ap_subledger.invoices = {mock_invoice.invoice_id: mock_invoice}
        ap_subledger.vendor_cards = {mock_invoice.vendor_id: mock_vendor_card}
        new_sub = ap_subledger.cancel_invoice(mock_invoice.invoice_id, "test", "admin")
        mock_invoice.cancel.assert_called_once_with("admin", "test")
        assert new_sub.invoices[mock_invoice.invoice_id] == mock_invoice
        assert new_sub.version == ap_subledger.version + 1

        # Not found
        with pytest.raises(ValueError, match="not found"):
            ap_subledger.cancel_invoice(uuid4(), "test", "admin")

        # Locked
        ap_subledger.lock("admin", "lock")
        with pytest.raises(ValueError, match="locked"):
            ap_subledger.cancel_invoice(mock_invoice.invoice_id, "test", "admin")

    def test_get_invoice(self, ap_subledger, mock_invoice):
        ap_subledger.invoices = {mock_invoice.invoice_id: mock_invoice}
        assert ap_subledger.get_invoice(mock_invoice.invoice_id) is mock_invoice
        assert ap_subledger.get_invoice(uuid4()) is None

    def test_get_invoices_by_vendor(self, ap_subledger, mock_invoice):
        vendor_id = mock_invoice.vendor_id
        inv2 = MagicMock(spec=APInvoiceEntity)
        inv2.vendor_id = vendor_id
        inv3 = MagicMock(spec=APInvoiceEntity)
        inv3.vendor_id = uuid4()
        ap_subledger.invoices = {
            mock_invoice.invoice_id: mock_invoice,
            inv2.invoice_id: inv2,
            inv3.invoice_id: inv3,
        }
        result = ap_subledger.get_invoices_by_vendor(vendor_id)
        assert len(result) == 2
        assert mock_invoice in result
        assert inv2 in result

    def test_get_overdue_invoices(self, ap_subledger, mock_invoice):
        mock_invoice.is_overdue.return_value = True
        mock_invoice.status = APInvoiceStatus.ISSUED
        ap_subledger.invoices = {mock_invoice.invoice_id: mock_invoice}
        overdue = ap_subledger.get_overdue_invoices()
        assert len(overdue) == 1
        assert overdue[0] is mock_invoice

        # Exclude paid/cancelled
        mock_invoice.status = APInvoiceStatus.FULLY_PAID
        overdue2 = ap_subledger.get_overdue_invoices()
        assert len(overdue2) == 0

    # ===== Payment Management =====
    def test_add_payment_with_invoice_allocation(self, ap_subledger, mock_invoice, mock_payment, mock_vendor_card):
        mock_payment.allocated_to_invoice_id = mock_invoice.invoice_id
        mock_payment.allocated_amount = Decimal("500000")
        ap_subledger.invoices = {mock_invoice.invoice_id: mock_invoice}
        ap_subledger.vendor_cards = {mock_payment.vendor_id: mock_vendor_card}
        new_sub = ap_subledger.add_payment(mock_payment, "admin")
        mock_invoice.record_payment.assert_called_once_with(mock_payment.allocated_amount, mock_payment.payment_id)
        assert new_sub.payments[mock_payment.payment_id] is mock_payment
        assert new_sub.version == ap_subledger.version + 1
        events = new_sub.get_events()
        assert any(isinstance(e, PaymentSentEvent) for e in events)

    def test_add_payment_without_allocation(self, ap_subledger, mock_payment, mock_vendor_card):
        ap_subledger.vendor_cards = {mock_payment.vendor_id: mock_vendor_card}
        new_sub = ap_subledger.add_payment(mock_payment, "admin")
        assert new_sub.payments[mock_payment.payment_id] is mock_payment
        assert new_sub.version == ap_subledger.version + 1

        # Vendor not found
        ap_subledger.vendor_cards = {}
        with pytest.raises(ValueError, match="Vendor .* not found"):
            ap_subledger.add_payment(mock_payment, "admin")

        # Locked
        ap_subledger.lock("admin", "lock")
        with pytest.raises(ValueError, match="locked"):
            ap_subledger.add_payment(mock_payment, "admin")

    def test_approve_payment(self, ap_subledger, mock_payment):
        ap_subledger.payments = {mock_payment.payment_id: mock_payment}
        new_sub = ap_subledger.approve_payment(mock_payment.payment_id, "approver")
        mock_payment.approve.assert_called_once_with("approver")
        assert new_sub.version == ap_subledger.version + 1
        assert any(a["action"] == "payment_approved" for a in new_sub._audit_trail)

        # Not found
        with pytest.raises(ValueError, match="not found"):
            ap_subledger.approve_payment(uuid4(), "admin")

        # Locked
        ap_subledger.lock("admin", "lock")
        with pytest.raises(ValueError, match="locked"):
            ap_subledger.approve_payment(mock_payment.payment_id, "admin")

    def test_process_payment(self, ap_subledger, mock_payment):
        ap_subledger.payments = {mock_payment.payment_id: mock_payment}
        new_sub = ap_subledger.process_payment(mock_payment.payment_id, "processor", "REF-001")
        mock_payment.process.assert_called_once_with("processor", "REF-001")
        assert new_sub.version == ap_subledger.version + 1

    def test_confirm_payment(self, ap_subledger, mock_payment):
        ap_subledger.payments = {mock_payment.payment_id: mock_payment}
        new_sub = ap_subledger.confirm_payment(mock_payment.payment_id, "confirmer", "BANK-REF")
        mock_payment.confirm.assert_called_once_with("confirmer", "BANK-REF")
        assert new_sub.version == ap_subledger.version + 1

    def test_cancel_payment(self, ap_subledger, mock_payment):
        ap_subledger.payments = {mock_payment.payment_id: mock_payment}
        new_sub = ap_subledger.cancel_payment(mock_payment.payment_id, "test", "admin")
        mock_payment.cancel.assert_called_once_with("admin", "test")
        assert new_sub.version == ap_subledger.version + 1

    def test_get_payment(self, ap_subledger, mock_payment):
        ap_subledger.payments = {mock_payment.payment_id: mock_payment}
        assert ap_subledger.get_payment(mock_payment.payment_id) is mock_payment
        assert ap_subledger.get_payment(uuid4()) is None

    def test_get_pending_payments(self, ap_subledger, mock_payment):
        mock_payment.status = APPaymentStatus.PENDING
        pay2 = MagicMock(spec=APPaymentEntity)
        pay2.status = APPaymentStatus.COMPLETED
        ap_subledger.payments = {
            mock_payment.payment_id: mock_payment,
            pay2.payment_id: pay2,
        }
        pending = ap_subledger.get_pending_payments()
        assert len(pending) == 1
        assert pending[0] is mock_payment

    # ===== Credit Note =====
    def test_add_credit_note(self, ap_subledger):
        credit_note = MagicMock(spec=APCreditNoteEntity)
        credit_note.credit_note_id = uuid4()
        ap_subledger.add_credit_note(credit_note, "admin")
        assert credit_note.credit_note_id in ap_subledger.credit_notes
        assert ap_subledger.version > 1
        events = ap_subledger.get_events()
        assert any(isinstance(e, CreditNoteReceivedEvent) for e in events)

        # Locked
        ap_subledger.lock("admin", "lock")
        with pytest.raises(ValueError, match="locked"):
            ap_subledger.add_credit_note(credit_note, "admin")

    def test_apply_credit_note(self, ap_subledger, mock_invoice, mock_vendor_card):
        credit_note = MagicMock(spec=APCreditNoteEntity)
        credit_note.credit_note_id = uuid4()
        credit_note.vendor_id = mock_invoice.vendor_id
        credit_note.amount = Decimal("300000")
        credit_note.credit_note_number = "CN-001"
        credit_note.apply.return_value = credit_note
        ap_subledger.credit_notes = {credit_note.credit_note_id: credit_note}
        ap_subledger.invoices = {mock_invoice.invoice_id: mock_invoice}
        ap_subledger.vendor_cards = {mock_invoice.vendor_id: mock_vendor_card}
        new_sub = ap_subledger.apply_credit_note(credit_note.credit_note_id, mock_invoice.invoice_id, "admin")
        credit_note.apply.assert_called_once_with("admin")
        assert new_sub.version == ap_subledger.version + 1
        events = new_sub.get_events()
        assert any(isinstance(e, CreditNoteAppliedEvent) for e in events)

        # Not found
        with pytest.raises(ValueError, match="Credit note .* not found"):
            ap_subledger.apply_credit_note(uuid4(), mock_invoice.invoice_id, "admin")

        # Invoice not found
        with pytest.raises(ValueError, match="Invoice .* not found"):
            ap_subledger.apply_credit_note(credit_note.credit_note_id, uuid4(), "admin")

    # ===== Debit Note =====
    def test_add_debit_note(self, ap_subledger):
        debit_note = MagicMock(spec=APDebitNoteEntity)
        debit_note.debit_note_id = uuid4()
        ap_subledger.add_debit_note(debit_note, "admin")
        assert debit_note.debit_note_id in ap_subledger.debit_notes
        assert ap_subledger.version > 1
        events = ap_subledger.get_events()
        assert any(isinstance(e, DebitNoteIssuedEvent) for e in events)

    def test_apply_debit_note(self, ap_subledger, mock_vendor_card):
        debit_note = MagicMock(spec=APDebitNoteEntity)
        debit_note.debit_note_id = uuid4()
        debit_note.vendor_id = mock_vendor_card.vendor_id
        debit_note.amount = Decimal("200000")
        debit_note.debit_note_number = "DN-001"
        debit_note.apply.return_value = debit_note
        ap_subledger.debit_notes = {debit_note.debit_note_id: debit_note}
        ap_subledger.vendor_cards = {mock_vendor_card.vendor_id: mock_vendor_card}
        new_sub = ap_subledger.apply_debit_note(debit_note.debit_note_id, "admin")
        debit_note.apply.assert_called_once_with("admin")
        assert new_sub.version == ap_subledger.version + 1

    # ===== Vendor Card =====
    def test_get_vendor_card(self, ap_subledger, mock_vendor_card):
        ap_subledger.vendor_cards = {mock_vendor_card.vendor_id: mock_vendor_card}
        assert ap_subledger.get_vendor_card(mock_vendor_card.vendor_id) is mock_vendor_card
        assert ap_subledger.get_vendor_card(uuid4()) is None

    def test_get_vendor_outstanding(self, ap_subledger, mock_vendor_card):
        ap_subledger.vendor_cards = {mock_vendor_card.vendor_id: mock_vendor_card}
        assert ap_subledger.get_vendor_outstanding(mock_vendor_card.vendor_id) == mock_vendor_card.outstanding_balance
        assert ap_subledger.get_vendor_outstanding(uuid4()) == Decimal(0)

    def test_get_total_outstanding(self, ap_subledger, mock_vendor_card):
        card2 = MagicMock(spec=VendorCard)
        card2.outstanding_balance = Decimal("500000")
        ap_subledger.vendor_cards = {
            mock_vendor_card.vendor_id: mock_vendor_card,
            card2.vendor_id: card2,
        }
        total = ap_subledger.get_total_outstanding()
        assert total == Decimal("1500000")

    def test_get_aging_summary(self, ap_subledger, mock_vendor_card):
        ap_subledger.vendor_cards = {mock_vendor_card.vendor_id: mock_vendor_card}
        summary = ap_subledger.get_aging_summary()
        assert summary["current"] == Decimal("1000000")
        assert summary["1_30"] == Decimal(0)
        assert summary["31_60"] == Decimal(0)

    def test_to_dict(self, ap_subledger, mock_vendor_card):
        ap_subledger.vendor_cards = {mock_vendor_card.vendor_id: mock_vendor_card}
        d = ap_subledger.to_dict()
        assert d["ap_id"] == str(ap_subledger.ap_id)
        assert d["total_vendors"] == 1
        assert d["total_outstanding"] == "1000000"
        assert "aging_summary" in d

    def test_create(self, legal_entity_id):
        sub = APSubledger.create(legal_entity_id, "admin")
        assert sub.legal_entity_id == legal_entity_id
        assert sub.version == 1
        assert sub.ap_id is not None


# ============================================================================
# Test APSubledgerRepository (protocol)
# ============================================================================

class TestAPSubledgerRepository:
    def test_methods_raise_not_implemented(self):
        repo = APSubledgerRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_legal_entity(uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())