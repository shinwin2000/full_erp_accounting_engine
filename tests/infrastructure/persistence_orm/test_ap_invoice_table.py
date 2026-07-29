# tests/infrastructure/persistence_orm/test_ap_invoice_table.py
# Comprehensive tests for APInvoiceTable ORM model

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.ap_invoice_table import APInvoiceTable


class TestAPInvoiceTable:
    """Tests for the APInvoiceTable ORM table model."""

    def test_tablename_defined(self):
        """ORM model declares a table name."""
        assert hasattr(APInvoiceTable, "__tablename__")
        assert isinstance(APInvoiceTable.__tablename__, str)
        assert len(APInvoiceTable.__tablename__) > 0

    def test_instantiation(self):
        """ORM model can be instantiated in-memory."""
        instance = APInvoiceTable(
            id=uuid4(),
            invoice_number="INV-001",
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            invoice_number_vendor="VEND-001",
            vendor_id=uuid4(),
            total_amount=Decimal("1000000"),
            paid_amount=Decimal(0),
            tax_amount=Decimal("100000"),
            discount_amount=Decimal("50000"),
            currency="IDR",
            status="draft",
        )
        assert isinstance(instance, APInvoiceTable)
        assert instance.invoice_number == "INV-001"
        assert instance.total_amount == Decimal("1000000")

    # -------------------- Fixtures --------------------
    @pytest.fixture
    def base_invoice(self):
        return APInvoiceTable(
            id=uuid4(),
            invoice_number="INV-001",
            invoice_date=date(2026, 1, 1),
            due_date=date(2026, 2, 1),
            invoice_number_vendor="V-001",
            vendor_id=uuid4(),
            total_amount=Decimal("1000000"),
            paid_amount=Decimal(0),
            tax_amount=Decimal("100000"),
            discount_amount=Decimal("50000"),
            currency="IDR",
            status="draft",
            version=1,
        )

    @pytest.fixture
    def submitted_invoice(self, base_invoice):
        base_invoice.status = "submitted"
        return base_invoice

    @pytest.fixture
    def approved_invoice(self, base_invoice):
        base_invoice.status = "approved"
        return base_invoice

    @pytest.fixture
    def partially_paid_invoice(self, base_invoice):
        base_invoice.status = "partially_paid"
        base_invoice.paid_amount = Decimal("300000")
        return base_invoice

    @pytest.fixture
    def paid_invoice(self, base_invoice):
        base_invoice.status = "paid"
        base_invoice.paid_amount = Decimal("1000000")
        return base_invoice

    # -------------------- Property Tests --------------------
    def test_outstanding_amount(self, base_invoice):
        assert base_invoice.outstanding_amount == Decimal("1000000")
        base_invoice.paid_amount = Decimal("300000")
        assert base_invoice.outstanding_amount == Decimal("700000")

    def test_is_paid(self, base_invoice, paid_invoice):
        assert base_invoice.is_paid is False
        assert paid_invoice.is_paid is True
        # also if paid_amount >= total
        base_invoice.paid_amount = Decimal("1000000")
        assert base_invoice.is_paid is True

    def test_is_partially_paid(self, base_invoice, partially_paid_invoice):
        assert base_invoice.is_partially_paid is False
        assert partially_paid_invoice.is_partially_paid is True
        # if paid_amount > 0 but < total
        base_invoice.paid_amount = Decimal("500000")
        assert base_invoice.is_partially_paid is True
        # if paid_amount == total -> not partial
        base_invoice.paid_amount = Decimal("1000000")
        assert base_invoice.is_partially_paid is False

    def test_is_approved(self, base_invoice, approved_invoice):
        assert base_invoice.is_approved is False
        assert approved_invoice.is_approved is True

    def test_is_3way_match(self, base_invoice):
        base_invoice.three_way_match_status = "match"
        assert base_invoice.is_3way_match is True
        base_invoice.three_way_match_status = "pending"
        assert base_invoice.is_3way_match is False

    def test_is_3way_mismatch(self, base_invoice):
        base_invoice.three_way_match_status = "mismatch"
        assert base_invoice.is_3way_mismatch is True
        base_invoice.three_way_match_status = "pending"
        assert base_invoice.is_3way_mismatch is False

    def test_days_until_due(self, base_invoice):
        # Mock date.today to a known date
        with patch("infrastructure.persistence_orm.ap_invoice_table.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 15)
            # due_date is 2026-02-01, delta = 17 days
            assert base_invoice.days_until_due == 17
            # if due date passed
            mock_date.today.return_value = date(2026, 2, 15)
            assert base_invoice.days_until_due == -14

    def test_is_overdue(self, base_invoice, paid_invoice):
        with patch("infrastructure.persistence_orm.ap_invoice_table.date") as mock_date:
            mock_date.today.return_value = date(2026, 2, 15)  # after due date
            assert base_invoice.is_overdue is True
            # paid invoice not overdue
            assert paid_invoice.is_overdue is False

    def test_payment_percentage(self, base_invoice):
        # total = 1,000,000, paid = 0 -> 0%
        assert base_invoice.payment_percentage == Decimal("0.0")
        base_invoice.paid_amount = Decimal("300000")
        assert base_invoice.payment_percentage == Decimal("30.0")
        base_invoice.paid_amount = Decimal("1000000")
        assert base_invoice.payment_percentage == Decimal("100.0")
        # total = 0 -> 100% (edge case)
        base_invoice.total_amount = Decimal(0)
        assert base_invoice.payment_percentage == Decimal("100.0")

    # -------------------- State Transition Tests --------------------
    def test_submit_from_draft(self, base_invoice):
        base_invoice.submit()
        assert base_invoice.status == "submitted"
        assert base_invoice.version == 2
        events = base_invoice.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "Submitted"

    def test_submit_from_invalid_status_raises(self, submitted_invoice):
        with pytest.raises(ValueError, match="Cannot submit invoice with status submitted"):
            submitted_invoice.submit()

    def test_approve_from_submitted(self, submitted_invoice):
        approver_id = uuid4()
        with patch("infrastructure.persistence_orm.ap_invoice_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 15, 12, 0, 0)
            mock_dt.utcnow.return_value = fixed_now
            submitted_invoice.approve(approver_id)
        assert submitted_invoice.status == "approved"
        assert submitted_invoice.approved_by == approver_id
        assert submitted_invoice.approved_at == fixed_now
        assert submitted_invoice.version == 2
        events = submitted_invoice.get_events()
        assert events[-1]["event_type"] == "Approved"

    def test_approve_from_invalid_status_raises(self, base_invoice):
        with pytest.raises(ValueError, match="Cannot approve invoice with status draft"):
            base_invoice.approve(uuid4())

    def test_reject_from_submitted(self, submitted_invoice):
        submitted_invoice.reject()
        assert submitted_invoice.status == "draft"
        assert submitted_invoice.version == 2
        events = submitted_invoice.get_events()
        assert events[-1]["event_type"] == "Rejected"

    def test_reject_from_invalid_status_raises(self, base_invoice):
        with pytest.raises(ValueError, match="Cannot reject invoice with status draft"):
            base_invoice.reject()

    def test_record_payment_positive_amount(self, base_invoice):
        base_invoice.record_payment(Decimal("300000"))
        assert base_invoice.status == "partially_paid"
        assert base_invoice.paid_amount == Decimal("300000")
        assert base_invoice.version == 2
        events = base_invoice.get_events()
        assert events[-1]["event_type"] == "PaymentRecorded"

    def test_record_payment_exact_full(self, base_invoice):
        base_invoice.record_payment(Decimal("1000000"))
        assert base_invoice.status == "paid"
        assert base_invoice.paid_amount == Decimal("1000000")

    def test_record_payment_exceeds_total(self, base_invoice):
        # Should cap at total
        base_invoice.record_payment(Decimal("1200000"))
        assert base_invoice.status == "paid"
        assert base_invoice.paid_amount == Decimal("1000000")

    def test_record_payment_zero_or_negative_raises(self, base_invoice):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            base_invoice.record_payment(Decimal(0))
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            base_invoice.record_payment(Decimal("-100"))

    def test_record_payment_on_paid_invoice_raises(self, paid_invoice):
        with pytest.raises(ValueError, match="Invoice already paid"):
            paid_invoice.record_payment(Decimal("100"))

    def test_apply_credit_note_valid(self, base_invoice):
        base_invoice.apply_credit_note(Decimal("200000"), "CN-001")
        assert base_invoice.total_amount == Decimal("800000")
        assert base_invoice.paid_amount == Decimal(0)  # not paid
        assert base_invoice.status == "draft"  # still draft
        assert base_invoice.version == 2
        events = base_invoice.get_events()
        assert events[-1]["event_type"] == "CreditNoteApplied"

    def test_apply_credit_note_with_existing_payment(self, base_invoice):
        base_invoice.paid_amount = Decimal("300000")
        base_invoice.apply_credit_note(Decimal("200000"), "CN-001")
        assert base_invoice.total_amount == Decimal("800000")
        assert base_invoice.paid_amount == Decimal("300000")  # unchanged, but capped
        # now paid amount (300k) > total (800k) - actually 300k < 800k, so still partial
        # Let's test case where credit reduces total below paid amount
        base_invoice2 = APInvoiceTable(total_amount=Decimal("1000000"), paid_amount=Decimal("800000"))
        base_invoice2.apply_credit_note(Decimal("300000"), "CN-002")
        assert base_invoice2.total_amount == Decimal("700000")
        assert base_invoice2.paid_amount == Decimal("700000")  # capped to total
        assert base_invoice2.status == "paid"

    def test_apply_credit_note_invalid_amount_raises(self, base_invoice):
        with pytest.raises(ValueError, match="Credit note amount must be positive"):
            base_invoice.apply_credit_note(Decimal(0), "CN-001")
        with pytest.raises(ValueError, match="Credit note amount must be positive"):
            base_invoice.apply_credit_note(Decimal("-100"), "CN-001")

    def test_apply_credit_note_exceeds_outstanding_raises(self, base_invoice):
        # outstanding = 1,000,000, try 1,200,000
        with pytest.raises(ValueError, match="Credit note amount exceeds outstanding amount"):
            base_invoice.apply_credit_note(Decimal("1200000"), "CN-001")

    def test_apply_credit_note_on_paid_invoice_raises(self, paid_invoice):
        with pytest.raises(ValueError, match="Cannot apply credit note to paid invoice"):
            paid_invoice.apply_credit_note(Decimal("100000"), "CN-001")

    def test_write_off_valid(self, base_invoice):
        base_invoice.write_off("Obsolete")
        assert base_invoice.status == "written_off"
        assert base_invoice.paid_amount == Decimal("1000000")  # total paid
        assert base_invoice.version == 2
        events = base_invoice.get_events()
        assert events[-1]["event_type"] == "WrittenOff"
        assert events[-1]["data"]["reason"] == "Obsolete"

    def test_write_off_paid_invoice_raises(self, paid_invoice):
        with pytest.raises(ValueError, match="Cannot write off a paid invoice"):
            paid_invoice.write_off("Test")

    def test_write_off_cancelled_raises(self, base_invoice):
        base_invoice.status = "cancelled"
        with pytest.raises(ValueError, match="Cannot write off cancelled invoice"):
            base_invoice.write_off("Test")

    def test_cancel_valid(self, base_invoice, submitted_invoice, approved_invoice):
        base_invoice.cancel()
        assert base_invoice.status == "cancelled"
        assert base_invoice.version == 2
        events = base_invoice.get_events()
        assert events[-1]["event_type"] == "Cancelled"

        submitted_invoice.cancel()
        assert submitted_invoice.status == "cancelled"

        approved_invoice.cancel()
        assert approved_invoice.status == "cancelled"

    def test_cancel_paid_raises(self, paid_invoice):
        with pytest.raises(ValueError, match="Cannot cancel paid invoice"):
            paid_invoice.cancel()

    def test_cancel_already_cancelled_raises(self, base_invoice):
        base_invoice.status = "cancelled"
        with pytest.raises(ValueError, match="Cannot cancel invoice with status cancelled"):
            base_invoice.cancel()

    def test_cancel_written_off_raises(self, base_invoice):
        base_invoice.status = "written_off"
        with pytest.raises(ValueError, match="Cannot cancel invoice with status written_off"):
            base_invoice.cancel()

    # -------------------- 3-Way Match Status --------------------
    def test_set_3way_match_status_valid(self, base_invoice):
        base_invoice.set_3way_match_status("match")
        assert base_invoice.three_way_match_status == "match"
        assert base_invoice.version == 2
        events = base_invoice.get_events()
        assert events[-1]["event_type"] == "3WayMatchStatusChanged"

        base_invoice.set_3way_match_status("mismatch")
        assert base_invoice.three_way_match_status == "mismatch"

    def test_set_3way_match_status_invalid_raises(self, base_invoice):
        with pytest.raises(ValueError, match="Invalid 3-way match status"):
            base_invoice.set_3way_match_status("invalid")

    # -------------------- Link to Payment Run --------------------
    def test_link_to_payment_run(self, base_invoice):
        run_id = uuid4()
        base_invoice.link_to_payment_run(run_id)
        assert base_invoice.payment_run_id == run_id
        assert base_invoice.version == 2
        events = base_invoice.get_events()
        assert events[-1]["event_type"] == "LinkedToPaymentRun"

    # -------------------- Event Recording --------------------
    def test_record_event(self, base_invoice):
        base_invoice._record_event("TestEvent", {"key": "value"})
        events = base_invoice.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "TestEvent"
        assert events[0]["aggregate_id"] == str(base_invoice.id)
        assert "timestamp" in events[0]
        assert events[0]["data"] == {"key": "value"}

    def test_clear_events(self, base_invoice):
        base_invoice._record_event("Event1", {})
        base_invoice._record_event("Event2", {})
        assert len(base_invoice.get_events()) == 2
        base_invoice.clear_events()
        assert len(base_invoice.get_events()) == 0

    def test_get_events_returns_copy(self, base_invoice):
        base_invoice._record_event("Test", {})
        events = base_invoice.get_events()
        events.append({"fake": True})  # modify copy
        assert len(base_invoice.get_events()) == 1  # original unchanged

    # -------------------- Reconstruct --------------------
    def test_reconstruct_from_events(self):
        invoice_id = uuid4()
        vendor_id = uuid4()
        events = [
            {
                "event_type": "Created",
                "data": {
                    "id": str(invoice_id),
                    "invoice_number": "INV-002",
                    "invoice_date": "2026-01-01",
                    "due_date": "2026-02-01",
                    "invoice_number_vendor": "V-002",
                    "vendor_id": str(vendor_id),
                    "total_amount": "1000000",
                    "paid_amount": "0",
                    "tax_amount": "100000",
                    "discount_amount": "50000",
                    "currency": "IDR",
                    "status": "draft",
                    "description": "",
                }
            },
            {
                "event_type": "PaymentRecorded",
                "data": {"amount": "300000"}
            },
            {
                "event_type": "CreditNoteApplied",
                "data": {"amount": "200000", "credit_note_id": "CN-001"}
            },
            {
                "event_type": "WrittenOff",
                "data": {"reason": "Obsolete"}
            },
            {
                "event_type": "StatusChanged",
                "data": {"new_status": "written_off"}
            }
        ]
        invoice = APInvoiceTable.reconstruct(events)
        assert invoice.id == invoice_id
        assert invoice.invoice_number == "INV-002"
        assert invoice.total_amount == Decimal("800000")  # after credit note
        assert invoice.paid_amount == Decimal("1000000")  # after payment and write-off (capped)
        assert invoice.status == "written_off"
        # Check events not replayed? Not stored in events list.
        # We don't assert events, as reconstruct doesn't set events.

    def test_reconstruct_empty_events_raises_or_default(self):
        # If no events, reconstruct should still create instance with default values?
        # The implementation assumes at least one event, but we can test it.
        invoice = APInvoiceTable.reconstruct([])
        # It will create with default values; we can test that it's an instance
        assert isinstance(invoice, APInvoiceTable)

    # -------------------- Version Increment --------------------
    def test_version_increment_on_all_mutations(self, base_invoice):
        base_invoice.submit()
        assert base_invoice.version == 2
        base_invoice.approve(uuid4())
        assert base_invoice.version == 3
        base_invoice.record_payment(Decimal("100000"))
        assert base_invoice.version == 4
        base_invoice.set_3way_match_status("match")
        assert base_invoice.version == 5
        base_invoice.link_to_payment_run(uuid4())
        assert base_invoice.version == 6
