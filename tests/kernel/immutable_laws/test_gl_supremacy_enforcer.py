# tests/kernel/immutable_laws/test_gl_supremacy_enforcer.py
# Comprehensive tests for kernel/immutable_laws/gl_supremacy_enforcer.py

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from kernel.immutable_laws.gl_supremacy_enforcer import (
    GLSupremacyEnforcer,
    ReconciliationHistory,
    ReconciliationResult,
    ReconciliationStatus,
    SubledgerType,
    _FallbackLedgerRepository,
    _FallbackSubledgerRepository,
    get_gl_supremacy_enforcer,
)
from kernel.immutable_laws.law_violation_exceptions import (
    GLSupremacyViolation,
    LawViolationSeverity,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fixed_now():
    return datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_now):
    with patch("kernel.immutable_laws.gl_supremacy_enforcer.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def ledger_repo():
    return _FallbackLedgerRepository()


@pytest.fixture
def subledger_repo():
    return _FallbackSubledgerRepository()


@pytest.fixture
def enforcer(ledger_repo, subledger_repo):
    return GLSupremacyEnforcer(ledger_repo, subledger_repo)


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def period_id():
    return uuid4()


@pytest.fixture
def user_id():
    return "test_user"


# ============================================================================
# Tests for Enums & Dataclasses
# ============================================================================

class TestSubledgerType:
    def test_members(self):
        assert SubledgerType.ACCOUNTS_RECEIVABLE.value == "AR"
        assert SubledgerType.ACCOUNTS_PAYABLE.value == "AP"
        assert SubledgerType.INVENTORY.value == "INVENTORY"
        assert SubledgerType.FIXED_ASSET.value == "FIXED_ASSET"


class TestReconciliationStatus:
    def test_members(self):
        assert ReconciliationStatus.MATCHED.value == "matched"
        assert ReconciliationStatus.MISMATCHED.value == "mismatched"
        assert ReconciliationStatus.PENDING.value == "pending"
        assert ReconciliationStatus.ADJUSTMENT_NEEDED.value == "adjustment_needed"


class TestReconciliationResult:
    def test_compute_hash(self):
        result = ReconciliationResult(
            reconciliation_id=uuid4(),
            legal_entity_id=uuid4(),
            period_id=uuid4(),
            subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
            gl_balance=Decimal("1000"),
            subledger_balance=Decimal("1000"),
            difference=Decimal("0"),
            tolerance=Decimal("0.01"),
            status=ReconciliationStatus.MATCHED,
            reconciled_by="user",
            reconciled_at=datetime.now(UTC),
        )
        h = result.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64  # SHA3-256

    def test_hash_mismatch_raises(self):
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            ReconciliationResult(
                reconciliation_id=uuid4(),
                legal_entity_id=uuid4(),
                period_id=uuid4(),
                subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
                gl_balance=Decimal("1000"),
                subledger_balance=Decimal("1000"),
                difference=Decimal("0"),
                tolerance=Decimal("0.01"),
                status=ReconciliationStatus.MATCHED,
                reconciled_by="user",
                reconciled_at=datetime.now(UTC),
                cryptographic_hash="invalid_hash",
            )

    def test_is_matched(self):
        result = ReconciliationResult(
            reconciliation_id=uuid4(),
            legal_entity_id=uuid4(),
            period_id=uuid4(),
            subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
            gl_balance=Decimal("1000"),
            subledger_balance=Decimal("1000"),
            difference=Decimal("0"),
            tolerance=Decimal("0.01"),
            status=ReconciliationStatus.MATCHED,
            reconciled_by="user",
            reconciled_at=datetime.now(UTC),
        )
        assert result.is_matched() is True
        result.status = ReconciliationStatus.MISMATCHED
        assert result.is_matched() is False

    def test_to_dict(self):
        result = ReconciliationResult(
            reconciliation_id=uuid4(),
            legal_entity_id=uuid4(),
            period_id=uuid4(),
            subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
            gl_balance=Decimal("1000"),
            subledger_balance=Decimal("1000"),
            difference=Decimal("0"),
            tolerance=Decimal("0.01"),
            status=ReconciliationStatus.MATCHED,
            reconciled_by="user",
            reconciled_at=datetime.now(UTC),
            notes="Test notes",
        )
        d = result.to_dict()
        assert d["subledger_type"] == "AR"
        assert d["gl_balance"] == "1000"
        assert d["status"] == "matched"
        assert d["is_matched"] is True   # ← sekarang ada
        assert "notes" in d


class TestReconciliationHistory:
    def test_to_dict(self):
        result = ReconciliationResult(
            reconciliation_id=uuid4(),
            legal_entity_id=uuid4(),
            period_id=uuid4(),
            subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
            gl_balance=Decimal("1000"),
            subledger_balance=Decimal("1000"),
            difference=Decimal("0"),
            tolerance=Decimal("0.01"),
            status=ReconciliationStatus.MATCHED,
            reconciled_by="user",
            reconciled_at=datetime.now(UTC),
        )
        history = ReconciliationHistory(
            period_id=uuid4(),
            legal_entity_id=uuid4(),
            reconciliations=[result],
            total_gl_balance=Decimal("1000"),
            total_subledger_balance=Decimal("1000"),
            total_difference=Decimal("0"),
            all_matched=True,
            last_reconciled_at=datetime.now(UTC),
            last_reconciled_by="user",
        )
        d = history.to_dict()
        assert d["reconciliations_count"] == 1
        assert d["total_gl_balance"] == "1000"
        assert d["all_matched"] is True
        assert "last_reconciled_at" in d


# ============================================================================
# Tests for Fallback Repositories
# ============================================================================

class TestFallbackLedgerRepository:
    @pytest.mark.asyncio
    async def test_set_and_get_balance(self, ledger_repo, legal_entity_id, period_id):
        ledger_repo.set_balance(legal_entity_id, period_id, "1.1.01", Decimal("5000"))
        bal = await ledger_repo.get_balance(legal_entity_id, period_id, "1.1.01")
        assert bal == Decimal("5000")

    @pytest.mark.asyncio
    async def test_get_balance_history(self, ledger_repo, legal_entity_id, period_id):
        pid2 = uuid4()
        ledger_repo.set_balance(legal_entity_id, period_id, "1.1.01", Decimal("1000"))
        ledger_repo.set_balance(legal_entity_id, pid2, "1.1.01", Decimal("2000"))
        history = await ledger_repo.get_balance_history(
            legal_entity_id, "1.1.01", period_id, pid2
        )
        assert history[period_id] == Decimal("1000")
        assert history[pid2] == Decimal("2000")

    @pytest.mark.asyncio
    async def test_record_and_get_reconciliations(self, ledger_repo, legal_entity_id, period_id):
        await ledger_repo.record_reconciliation(
            legal_entity_id, period_id, "AR_TO_GL", {"status": "ok"}, "user"
        )
        recs = await ledger_repo.get_reconciliations(legal_entity_id, period_id)
        assert len(recs) == 1
        assert recs[0]["reconciliation_type"] == "AR_TO_GL"

    @pytest.mark.asyncio
    async def test_get_account_balance_summary(self, ledger_repo, legal_entity_id, period_id):
        ledger_repo.set_balance(legal_entity_id, period_id, "1.1.01", Decimal("100"))
        ledger_repo.set_balance(legal_entity_id, period_id, "1.1.02", Decimal("200"))
        ledger_repo.set_balance(legal_entity_id, period_id, "2.1.01", Decimal("300"))
        summary = await ledger_repo.get_account_balance_summary(legal_entity_id, period_id, "1.1")
        assert summary["1.1.01"] == Decimal("100")
        assert summary["1.1.02"] == Decimal("200")
        assert "2.1.01" not in summary

    def test_register_account(self, ledger_repo):
        ledger_repo.register_account("1.1.01", "AR Control", "Asset", True, "AR")
        assert ledger_repo._accounts["1.1.01"]["account_name"] == "AR Control"

    def test_clear(self, ledger_repo, legal_entity_id, period_id):
        ledger_repo.set_balance(legal_entity_id, period_id, "1.1.01", Decimal("100"))
        ledger_repo.clear()
        assert len(ledger_repo._balances) == 0


class TestFallbackSubledgerRepository:
    @pytest.mark.asyncio
    async def test_set_and_get_balances(self, subledger_repo, legal_entity_id, period_id):
        subledger_repo.set_balance(legal_entity_id, period_id, "AR", Decimal("1000"))
        bal = await subledger_repo.get_ar_balance(legal_entity_id, period_id)
        assert bal == Decimal("1000")

        subledger_repo.set_balance(legal_entity_id, period_id, "AP", Decimal("2000"))
        bal2 = await subledger_repo.get_ap_balance(legal_entity_id, period_id)
        assert bal2 == Decimal("2000")

        subledger_repo.set_balance(legal_entity_id, period_id, "INVENTORY", Decimal("3000"))
        bal3 = await subledger_repo.get_inventory_balance(legal_entity_id, period_id)
        assert bal3 == Decimal("3000")

        subledger_repo.set_balance(legal_entity_id, period_id, "FIXED_ASSET", Decimal("4000"))
        bal4 = await subledger_repo.get_fixed_asset_balance(legal_entity_id, period_id)
        assert bal4 == Decimal("4000")

    @pytest.mark.asyncio
    async def test_aging_methods(self, subledger_repo, legal_entity_id):
        aging = await subledger_repo.get_ar_aging(legal_entity_id, datetime.now(UTC))
        assert aging["total_outstanding"] == Decimal(0)

    @pytest.mark.asyncio
    async def test_details_methods(self, subledger_repo, legal_entity_id, period_id):
        subledger_repo.add_ar_detail(period_id, {"invoice": "INV001"})
        details = await subledger_repo.get_ar_details(legal_entity_id, period_id)
        assert len(details) == 1
        assert details[0]["invoice"] == "INV001"

        subledger_repo.add_ap_detail(period_id, {"invoice": "AP001"})
        ap_details = await subledger_repo.get_ap_details(legal_entity_id, period_id)
        assert ap_details[0]["invoice"] == "AP001"

        subledger_repo.add_inventory_detail(period_id, {"item": "ITEM001"})
        inv_details = await subledger_repo.get_inventory_details(legal_entity_id, period_id)
        assert inv_details[0]["item"] == "ITEM001"

    def test_clear(self, subledger_repo, legal_entity_id, period_id):
        subledger_repo.set_balance(legal_entity_id, period_id, "AR", Decimal("100"))
        subledger_repo.clear()
        assert len(subledger_repo._ar_balances) == 0


# ============================================================================
# Tests for GLSupremacyEnforcer
# ============================================================================

class TestGLSupremacyEnforcer:
    def test_initialization(self, enforcer):
        assert enforcer._enabled is True
        assert enforcer._tolerance == Decimal("0.01")
        assert enforcer._auto_correct_threshold == Decimal("1000")
        assert enforcer._version == 1

    def test_enable(self, enforcer):
        enforcer.enable(False)
        assert enforcer._enabled is False
        enforcer.enable(True)
        assert enforcer._enabled is True
        assert enforcer._audit_trail[-1]["action"] == "ENABLE"

    def test_set_tolerance(self, enforcer):
        enforcer.set_tolerance(Decimal("0.5"))
        assert enforcer._tolerance == Decimal("0.5")
        with pytest.raises(ValueError, match="Tolerance cannot be negative"):
            enforcer.set_tolerance(Decimal("-1"))

    def test_set_auto_correct_threshold(self, enforcer):
        enforcer.set_auto_correct_threshold(Decimal("2000"))
        assert enforcer._auto_correct_threshold == Decimal("2000")

    def test_get_subledger_type_from_account(self, enforcer):
        assert enforcer._get_subledger_type_from_account("1.1.01") == SubledgerType.ACCOUNTS_RECEIVABLE
        assert enforcer._get_subledger_type_from_account("1.1") == SubledgerType.ACCOUNTS_RECEIVABLE
        assert enforcer._get_subledger_type_from_account("2.1.02") == SubledgerType.ACCOUNTS_PAYABLE
        assert enforcer._get_subledger_type_from_account("1.3.01") == SubledgerType.INVENTORY
        assert enforcer._get_subledger_type_from_account("1.6.01") == SubledgerType.FIXED_ASSET
        assert enforcer._get_subledger_type_from_account("5.1") is None

    # ---- enforce_gl_supremacy ----
    @pytest.mark.asyncio
    async def test_enforce_gl_supremacy_disabled(self, enforcer, legal_entity_id, period_id):
        enforcer.enable(False)
        result = await enforcer.enforce_gl_supremacy(
            legal_entity_id, period_id, "1.1.01", user_id="user"
        )
        assert result.status == ReconciliationStatus.MATCHED
        assert result.notes == "Enforcer disabled"

    @pytest.mark.asyncio
    async def test_enforce_gl_supremacy_non_subledger_account(self, enforcer, legal_entity_id, period_id):
        result = await enforcer.enforce_gl_supremacy(
            legal_entity_id, period_id, "5.1.01", user_id="user"
        )
        assert result.status == ReconciliationStatus.MATCHED
        assert "Non-subledger account" in result.notes

    @pytest.mark.asyncio
    async def test_enforce_gl_supremacy_matched(self, enforcer, legal_entity_id, period_id, ledger_repo, subledger_repo):
        # Set balances to match
        ledger_repo.set_balance(legal_entity_id, period_id, "1.1.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "AR", Decimal("1000"))

        result = await enforcer.enforce_gl_supremacy(
            legal_entity_id, period_id, "1.1.01", user_id="user"
        )
        assert result.status == ReconciliationStatus.MATCHED
        assert result.gl_balance == Decimal("1000")
        assert result.subledger_balance == Decimal("1000")
        assert result.difference == Decimal("0")
        assert result.cryptographic_hash == result.compute_hash()
        # Check recorded reconciliation
        recs = await ledger_repo.get_reconciliations(legal_entity_id, period_id)
        assert len(recs) == 1

    @pytest.mark.asyncio
    async def test_enforce_gl_supremacy_mismatch_raises(self, enforcer, legal_entity_id, period_id, ledger_repo, subledger_repo):
        ledger_repo.set_balance(legal_entity_id, period_id, "1.1.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "AR", Decimal("500"))

        with pytest.raises(GLSupremacyViolation, match="GL/Subledger mismatch"):
            await enforcer.enforce_gl_supremacy(
                legal_entity_id, period_id, "1.1.01", user_id="user", auto_correct=False
            )
        # Check violation recorded
        violations = enforcer.get_violations()
        assert len(violations) == 1
        assert violations[0].account_code == "1.1.01"
        assert violations[0].severity == LawViolationSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_enforce_gl_supremacy_auto_correct_within_threshold(self, enforcer, legal_entity_id, period_id, ledger_repo, subledger_repo):
        ledger_repo.set_balance(legal_entity_id, period_id, "1.1.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "AR", Decimal("800"))  # diff 200, within 1000 threshold

        result = await enforcer.enforce_gl_supremacy(
            legal_entity_id, period_id, "1.1.01", user_id="user", auto_correct=True
        )
        assert result.status == ReconciliationStatus.ADJUSTMENT_NEEDED
        assert result.adjustment_journal_id is not None
        assert result.difference == Decimal("200")
        # No violation should be raised
        violations = enforcer.get_violations()
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_enforce_gl_supremacy_auto_correct_exceeds_threshold_raises(self, enforcer, legal_entity_id, period_id, ledger_repo, subledger_repo):
        # Set threshold low
        enforcer.set_auto_correct_threshold(Decimal("50"))
        ledger_repo.set_balance(legal_entity_id, period_id, "1.1.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "AR", Decimal("800"))  # diff 200 > 50

        with pytest.raises(GLSupremacyViolation, match="GL/Subledger mismatch"):
            await enforcer.enforce_gl_supremacy(
                legal_entity_id, period_id, "1.1.01", user_id="user", auto_correct=True
            )

    # ---- Specific reconcile methods ----
    @pytest.mark.asyncio
    async def test_reconcile_ar_to_gl(self, enforcer, legal_entity_id, period_id, ledger_repo, subledger_repo):
        ledger_repo.set_balance(legal_entity_id, period_id, "1.1.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "AR", Decimal("1000"))
        result = await enforcer.reconcile_ar_to_gl(legal_entity_id, period_id, "user")
        assert result.status == ReconciliationStatus.MATCHED
        assert result.subledger_type == SubledgerType.ACCOUNTS_RECEIVABLE

    @pytest.mark.asyncio
    async def test_reconcile_ap_to_gl(self, enforcer, legal_entity_id, period_id, ledger_repo, subledger_repo):
        ledger_repo.set_balance(legal_entity_id, period_id, "2.1.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "AP", Decimal("1000"))
        result = await enforcer.reconcile_ap_to_gl(legal_entity_id, period_id, "user")
        assert result.status == ReconciliationStatus.MATCHED
        assert result.subledger_type == SubledgerType.ACCOUNTS_PAYABLE

    @pytest.mark.asyncio
    async def test_reconcile_inventory_to_gl(self, enforcer, legal_entity_id, period_id, ledger_repo, subledger_repo):
        ledger_repo.set_balance(legal_entity_id, period_id, "1.3.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "INVENTORY", Decimal("1000"))
        result = await enforcer.reconcile_inventory_to_gl(legal_entity_id, period_id, "user")
        assert result.status == ReconciliationStatus.MATCHED
        assert result.subledger_type == SubledgerType.INVENTORY

    @pytest.mark.asyncio
    async def test_reconcile_fixed_asset_to_gl(self, enforcer, legal_entity_id, period_id, ledger_repo, subledger_repo):
        ledger_repo.set_balance(legal_entity_id, period_id, "1.6.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "FIXED_ASSET", Decimal("1000"))
        result = await enforcer.reconcile_fixed_asset_to_gl(legal_entity_id, period_id, "user")
        assert result.status == ReconciliationStatus.MATCHED
        assert result.subledger_type == SubledgerType.FIXED_ASSET

    @pytest.mark.asyncio
    async def test_reconcile_all_subledgers(self, enforcer, legal_entity_id, period_id, ledger_repo, subledger_repo):
        # Set all balances to match
        ledger_repo.set_balance(legal_entity_id, period_id, "1.1.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "AR", Decimal("1000"))
        ledger_repo.set_balance(legal_entity_id, period_id, "2.1.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "AP", Decimal("1000"))
        ledger_repo.set_balance(legal_entity_id, period_id, "1.3.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "INVENTORY", Decimal("1000"))
        ledger_repo.set_balance(legal_entity_id, period_id, "1.6.01", Decimal("1000"))
        subledger_repo.set_balance(legal_entity_id, period_id, "FIXED_ASSET", Decimal("1000"))

        results = await enforcer.reconcile_all_subledgers(legal_entity_id, period_id, "user")
        assert len(results) == 4
        for r in results:
            assert r.status == ReconciliationStatus.MATCHED

    # ---- get_reconciliation_status ----
    @pytest.mark.asyncio
    async def test_get_reconciliation_status(self, enforcer, legal_entity_id, period_id, ledger_repo):
        # Record a reconciliation
        await ledger_repo.record_reconciliation(
            legal_entity_id,
            period_id,
            "AR_TO_GL",
            {
                "reconciliation_id": str(uuid4()),
                "subledger_type": "AR",
                "gl_balance": "1000",
                "subledger_balance": "1000",
                "is_matched": True,
                "notes": "OK",
            },
            "user",
        )
        status = await enforcer.get_reconciliation_status(legal_entity_id, period_id)
        assert status.period_id == period_id
        assert status.total_gl_balance == Decimal("1000")
        assert status.total_subledger_balance == Decimal("1000")
        assert status.all_matched is True
        assert len(status.reconciliations) == 1

    # ---- get_reconciliation_details ----
    @pytest.mark.asyncio
    async def test_get_reconciliation_details(self, enforcer, legal_entity_id, period_id, subledger_repo):
        subledger_repo.add_ar_detail(period_id, {"invoice": "INV001", "amount": "100"})
        details = await enforcer.get_reconciliation_details(
            legal_entity_id, period_id, SubledgerType.ACCOUNTS_RECEIVABLE
        )
        assert len(details) == 1
        assert details[0]["invoice"] == "INV001"

    # ---- create_adjustment_journal ----
    @pytest.mark.asyncio
    async def test_create_adjustment_journal(self, enforcer, legal_entity_id, period_id):
        result = ReconciliationResult(
            reconciliation_id=uuid4(),
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
            gl_balance=Decimal("1000"),
            subledger_balance=Decimal("800"),
            difference=Decimal("200"),
            tolerance=Decimal("0.01"),
            status=ReconciliationStatus.ADJUSTMENT_NEEDED,
            reconciled_by="user",
            reconciled_at=datetime.now(UTC),
        )
        journal_id = await enforcer.create_adjustment_journal(
            result, Decimal("200"), "Adjustment", "admin"
        )
        assert isinstance(journal_id, UUID)
        # Check audit trail
        assert enforcer._audit_trail[-1]["action"] == "CREATE_ADJUSTMENT_JOURNAL"

    # ---- get_reconciliation_history ----
    def test_get_reconciliation_history(self, enforcer, legal_entity_id, period_id):
        result = ReconciliationResult(
            reconciliation_id=uuid4(),
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
            gl_balance=Decimal("1000"),
            subledger_balance=Decimal("1000"),
            difference=Decimal("0"),
            tolerance=Decimal("0.01"),
            status=ReconciliationStatus.MATCHED,
            reconciled_by="user",
            reconciled_at=datetime.now(UTC),
        )
        enforcer._reconciliation_history.append(result)
        history = enforcer.get_reconciliation_history(limit=10)
        assert len(history) == 1

        # Filter by legal_entity_id
        filtered = enforcer.get_reconciliation_history(legal_entity_id=legal_entity_id)
        assert len(filtered) == 1
        filtered2 = enforcer.get_reconciliation_history(legal_entity_id=uuid4())
        assert len(filtered2) == 0

        # Filter by period_id
        filtered3 = enforcer.get_reconciliation_history(period_id=period_id)
        assert len(filtered3) == 1
        filtered4 = enforcer.get_reconciliation_history(period_id=uuid4())
        assert len(filtered4) == 0

        # Filter only mismatched
        result2 = ReconciliationResult(
            reconciliation_id=uuid4(),
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
            gl_balance=Decimal("1000"),
            subledger_balance=Decimal("500"),
            difference=Decimal("500"),
            tolerance=Decimal("0.01"),
            status=ReconciliationStatus.MISMATCHED,
            reconciled_by="user",
            reconciled_at=datetime.now(UTC),
        )
        enforcer._reconciliation_history.append(result2)
        mismatched = enforcer.get_reconciliation_history(only_mismatched=True)
        assert len(mismatched) == 1

    # ---- get_violations ----
    def test_get_violations(self, enforcer):
        # Buat violation secara sync tanpa argumen severity/details di constructor
        violation = GLSupremacyViolation(
            message="Test violation",
            account_code="1.1.01",
            gl_balance="1000",
            subledger_balance="500",
        )
        # Set attributes setelah object dibuat
        violation.severity = LawViolationSeverity.CRITICAL
        violation.details = {"key": "value"}
        enforcer._violation_history.append(violation)

        violations = enforcer.get_violations()
        assert len(violations) == 1
        # Filter by account_code
        filtered = enforcer.get_violations(account_code="1.1.01")
        assert len(filtered) == 1
        filtered2 = enforcer.get_violations(account_code="2.1.01")
        assert len(filtered2) == 0

    # ---- get_statistics ----
    def test_get_statistics_empty(self, enforcer):
        stats = enforcer.get_statistics()
        assert stats["total_reconciliations"] == 0

    def test_get_statistics_with_data(self, enforcer, legal_entity_id, period_id):
        # Add some reconciliations
        result_matched = ReconciliationResult(
            reconciliation_id=uuid4(),
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
            gl_balance=Decimal("1000"),
            subledger_balance=Decimal("1000"),
            difference=Decimal("0"),
            tolerance=Decimal("0.01"),
            status=ReconciliationStatus.MATCHED,
            reconciled_by="user",
            reconciled_at=datetime.now(UTC),
        )
        result_mismatch = ReconciliationResult(
            reconciliation_id=uuid4(),
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            subledger_type=SubledgerType.ACCOUNTS_PAYABLE,
            gl_balance=Decimal("1000"),
            subledger_balance=Decimal("800"),
            difference=Decimal("200"),
            tolerance=Decimal("0.01"),
            status=ReconciliationStatus.MISMATCHED,
            reconciled_by="user",
            reconciled_at=datetime.now(UTC),
        )
        enforcer._reconciliation_history = [result_matched, result_mismatch]
        stats = enforcer.get_statistics()
        assert stats["total_reconciliations"] == 2
        assert stats["matched_count"] == 1
        assert stats["mismatched_count"] == 1
        assert stats["by_subledger"]["AR"] == 1
        assert stats["by_subledger"]["AP"] == 1
        assert stats["avg_mismatch_amount"] == "200"
        assert stats["match_rate"] == 0.5
        assert stats["version"] == 1

    # ---- reset ----
    def test_reset(self, enforcer, legal_entity_id, period_id):
        enforcer._reconciliation_history.append(
            ReconciliationResult(
                reconciliation_id=uuid4(),
                legal_entity_id=legal_entity_id,
                period_id=period_id,
                subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
                gl_balance=Decimal("1000"),
                subledger_balance=Decimal("1000"),
                difference=Decimal("0"),
                tolerance=Decimal("0.01"),
                status=ReconciliationStatus.MATCHED,
                reconciled_by="user",
                reconciled_at=datetime.now(UTC),
            )
        )
        enforcer.reset()
        assert len(enforcer._reconciliation_history) == 0
        assert len(enforcer._violation_history) == 0
        assert enforcer._tolerance == enforcer.DEFAULT_TOLERANCE
        assert enforcer._auto_correct_threshold == enforcer.AUTO_CORRECT_THRESHOLD
        assert enforcer._enabled is True
        assert enforcer._version > 1
        assert len(enforcer._audit_trail) == 0

    # ---- Entity methods ----
    def test_validate(self, enforcer):
        result = enforcer.validate()
        assert result["is_valid"] is True
        # Make invalid
        enforcer._max_history = -1
        result2 = enforcer.validate()
        assert result2["is_valid"] is False
        assert "max_history must be positive" in result2["errors"]

    def test_to_dict(self, enforcer):
        d = enforcer.to_dict()
        assert d["enabled"] is True
        assert d["tolerance"] == "0.01"
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "enabled": False,
            "tolerance": "0.5",
            "auto_correct_threshold": "2000",
            "max_history": 500,
            "version": 5,
        }
        instance = GLSupremacyEnforcer.from_dict(data)
        assert instance._enabled is False
        assert instance._tolerance == Decimal("0.5")
        assert instance._auto_correct_threshold == Decimal("2000")
        assert instance._max_history == 500
        assert instance._version == 5

    def test_clone(self, enforcer):
        enforcer.set_tolerance(Decimal("0.5"))
        clone = enforcer.clone()
        assert clone is not enforcer
        assert clone._enabled == enforcer._enabled
        assert clone._tolerance == enforcer._tolerance
        assert clone._auto_correct_threshold == enforcer._auto_correct_threshold
        assert clone._version == enforcer._version + 1

    def test_snapshot(self, enforcer, legal_entity_id, period_id):
        enforcer._reconciliation_history.append(
            ReconciliationResult(
                reconciliation_id=uuid4(),
                legal_entity_id=legal_entity_id,
                period_id=period_id,
                subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
                gl_balance=Decimal("1000"),
                subledger_balance=Decimal("1000"),
                difference=Decimal("0"),
                tolerance=Decimal("0.01"),
                status=ReconciliationStatus.MATCHED,
                reconciled_by="user",
                reconciled_at=datetime.now(UTC),
            )
        )
        snap = enforcer.snapshot()
        assert snap["version"] == 1
        assert snap["reconciliations_count"] == 1
        assert snap["enabled"] is True

    def test_version(self, enforcer):
        assert enforcer.version() == 1
        enforcer._version = 3
        assert enforcer.version() == 3

    def test_audit_trail(self, enforcer):
        enforcer._record_audit("ACTION", "user", {"key": "value"})
        trail = enforcer.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "ACTION"

    def test_touch(self, enforcer):
        old_ver = enforcer._version
        enforcer.touch("admin")
        assert enforcer._version == old_ver + 1
        assert enforcer._audit_trail[-1]["action"] == "TOUCH"

    # ---- check method ----
    def test_check_valid(self, enforcer, legal_entity_id, period_id):
        context = {
            "legal_entity_id": str(legal_entity_id),
            "period_id": str(period_id),
            "account_code": "1.1.01",
        }
        errors = enforcer.check(context)
        assert errors == []

    def test_check_missing_fields(self, enforcer):
        errors = enforcer.check({})
        assert "legal_entity_id is required" in errors
        assert "period_id is required" in errors
        assert "account_code is required" in errors

    def test_check_invalid_uuid(self, enforcer):
        context = {
            "legal_entity_id": "invalid",
            "period_id": "invalid",
            "account_code": "1.1.01",
        }
        errors = enforcer.check(context)
        assert any("valid UUID" in e for e in errors)


# ============================================================================
# Tests for Singleton Accessor
# ============================================================================

def test_get_gl_supremacy_enforcer():
    e1 = get_gl_supremacy_enforcer()
    e2 = get_gl_supremacy_enforcer()
    assert e1 is e2
    assert isinstance(e1, GLSupremacyEnforcer)


# ============================================================================
# Tests with real async integration
# ============================================================================

class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_reconciliation_workflow(self, legal_entity_id, period_id):
        enforcer = GLSupremacyEnforcer()
        # Set balances
        enforcer._ledger_repo.set_balance(legal_entity_id, period_id, "1.1.01", Decimal("1000"))
        enforcer._subledger_repo.set_balance(legal_entity_id, period_id, "AR", Decimal("1000"))

        # Enforce
        result = await enforcer.enforce_gl_supremacy(
            legal_entity_id, period_id, "1.1.01", user_id="user"
        )
        assert result.status == ReconciliationStatus.MATCHED

        # Check status
        status = await enforcer.get_reconciliation_status(legal_entity_id, period_id)
        assert status.all_matched is True

        # Now create mismatch
        enforcer._subledger_repo.set_balance(legal_entity_id, period_id, "AR", Decimal("800"))
        with pytest.raises(GLSupremacyViolation, match="GL/Subledger mismatch"):
            await enforcer.enforce_gl_supremacy(
                legal_entity_id, period_id, "1.1.01", user_id="user", auto_correct=False
            )
        violations = enforcer.get_violations()
        assert len(violations) == 1

        # Auto-correct
        enforcer.set_auto_correct_threshold(Decimal("500"))
        result2 = await enforcer.enforce_gl_supremacy(
            legal_entity_id, period_id, "1.1.01", user_id="user", auto_correct=True
        )
        assert result2.status == ReconciliationStatus.ADJUSTMENT_NEEDED
        assert result2.adjustment_journal_id is not None

        # Statistics
        stats = enforcer.get_statistics()
        assert stats["total_reconciliations"] == 3  # matched, mismatch, auto-corrected
        assert stats["adjusted_count"] == 1
