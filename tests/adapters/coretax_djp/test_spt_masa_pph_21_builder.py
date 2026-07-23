# tests/adapters/coretax_djp/test_spt_masa_pph_21_builder.py
"""
Comprehensive unit tests for SPT Masa PPh 21 Builder.
Covers all public methods, negative paths, edge cases, and uses mocks to avoid flakiness.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from adapters.coretax_djp.spt_masa_pph_21_builder import (
    CORETAX_SPT_PPH21_ENDPOINT,
    SPTAlreadyExistsError,
    SPTError,
    SPTInvalidStateError,
    SPTLockedError,
    SPTMasaPPH21,
    SPTMasaPPH21Builder,
    SPTNotFoundError,
    SPTRepositoryPort,
    SPTStatus,
    SPTType,
    SPTValidationError,
    SPTXMLGenerationError,
    _FallbackSPTRepository,
    get_spt_pph21_builder,
)

# ============================================================================
# FIXED DATETIME - to avoid flaky tests
# ============================================================================
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now() to avoid flaky tests."""
    with patch("adapters.coretax_djp.spt_masa_pph_21_builder.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        yield mock_dt


# ============================================================================
# Enum tests
# ============================================================================
class TestSPTType:
    def test_members(self):
        assert SPTType.NORMAL.value == "normal"
        assert SPTType.CORRECTION.value == "pembetulan"
        assert SPTType.VOID.value == "batal"


class TestSPTStatus:
    def test_members(self):
        expected = [
            "DRAFT", "PENDING", "VALIDATED", "SUBMITTED", "APPROVED", "REJECTED",
            "CANCELLED", "VOID", "POSTED", "CLOSED", "ARCHIVED", "LOCKED", "ERROR", "SYNCED"
        ]
        for name in expected:
            assert hasattr(SPTStatus, name)


# ============================================================================
# Exception classes - parametrized
# ============================================================================
@pytest.mark.parametrize("exc_class", [
    SPTError,
    SPTNotFoundError,
    SPTAlreadyExistsError,
    SPTInvalidStateError,
    SPTValidationError,
    SPTLockedError,
    SPTXMLGenerationError,
])
class TestSPTExceptions:
    def test_instantiation(self, exc_class):
        e = exc_class("test message")
        assert isinstance(e, Exception)
        assert str(e) == "test message"


# ============================================================================
# Entity: SPTMasaPPH21
# ============================================================================
class TestSPTMasaPPH21:
    @pytest.fixture
    def spt(self) -> SPTMasaPPH21:
        return SPTMasaPPH21(
            npwp_pemotong="123456789012345",
            tahun=2024,
            bulan=1,
            spt_type=SPTType.NORMAL,
            total_bruto=Decimal("1000.00"),
            total_pph_terutang=Decimal("100.00"),
            total_bayar=Decimal("100.00"),
            ntpn="1234567890123456",
        )

    def test_construction(self, spt):
        assert spt.npwp_pemotong == "123456789012345"
        assert spt.tahun == 2024
        assert spt.bulan == 1
        assert spt.masa_pajak == "2024-01"
        assert spt.spt_type == SPTType.NORMAL
        assert spt.correction_number == 0
        assert spt.total_bruto == Decimal("1000.00")
        assert spt.total_pph_terutang == Decimal("100.00")
        assert spt.total_bayar == Decimal("100.00")
        assert spt.ntpn == "1234567890123456"
        assert spt.status == SPTStatus.DRAFT
        assert spt.version == 1
        assert spt.is_locked is False
        assert spt.is_active is True
        assert spt.employee_count == 0

    def test_kurang_bayar_lebih_bayar(self, spt):
        # balanced
        assert spt.kurang_bayar == Decimal(0)
        assert spt.lebih_bayar == Decimal(0)

        # underpaid
        spt._total_pph_terutang = Decimal("150")
        assert spt.kurang_bayar == Decimal("50")
        assert spt.lebih_bayar == Decimal(0)

        # overpaid
        spt._total_bayar = Decimal("200")
        assert spt.kurang_bayar == Decimal(0)
        assert spt.lebih_bayar == Decimal("50")

    def test_ntpn_masked(self, spt):
        assert spt.ntpn_masked == "12345678...3456"
        spt._ntpn = None
        assert spt.ntpn_masked is None
        spt._ntpn = "123"
        assert spt.ntpn_masked == "123"

    def test_create(self, spt):
        user = uuid4()
        spt.create(user)
        assert spt.status == SPTStatus.DRAFT
        assert spt.version == 2
        events = spt.get_events()
        assert any(e["event_type"] == "spt_pph21_created" for e in events)
        assert events[-1]["data"]["created_by"] == str(user)

    def test_update(self, spt):
        user = uuid4()
        spt.create(user)
        old_version = spt.version
        data = {
            "total_bruto": "2000",
            "total_pph_terutang": "200",
            "total_bayar": "200",
            "ntpn": "9876543210987654",
            "detail_karyawan": [{"npwp": "123", "nama": "A"}],
        }
        spt.update(data, user)
        assert spt.total_bruto == Decimal("2000")
        assert spt.total_pph_terutang == Decimal("200")
        assert spt.total_bayar == Decimal("200")
        assert spt.ntpn == "9876543210987654"
        assert len(spt.detail_karyawan) == 1
        assert spt.version == old_version + 1
        events = spt.get_events()
        assert any(e["event_type"] == "spt_pph21_updated" for e in events)

    def test_update_locked_raises(self, spt):
        spt.lock(uuid4())
        with pytest.raises(SPTLockedError):
            spt.update({}, uuid4())

    def test_update_invalid_state(self, spt):
        spt._status = SPTStatus.SUBMITTED
        with pytest.raises(SPTInvalidStateError, match="Cannot modify SPT"):
            spt.update({}, uuid4())

    def test_delete_and_restore(self, spt):
        user = uuid4()
        spt.delete(user, permanent=False)
        assert spt.status == SPTStatus.ARCHIVED
        spt.restore(user)
        assert spt.status == SPTStatus.DRAFT
        spt.delete(user, permanent=True)
        assert spt.status == SPTStatus.VOID

    def test_delete_locked_raises(self, spt):
        spt.lock(uuid4())
        with pytest.raises(SPTLockedError):
            spt.delete(uuid4())

    def test_restore_invalid_state(self, spt):
        with pytest.raises(SPTInvalidStateError, match="Cannot restore"):
            spt.restore(uuid4())

    def test_activate_deactivate(self, spt):
        user = uuid4()
        spt.activate(user)
        assert spt.status == SPTStatus.PENDING
        spt.deactivate(user)
        assert spt.status == SPTStatus.DRAFT

    def test_activate_invalid_state(self, spt):
        spt._status = SPTStatus.PENDING
        with pytest.raises(SPTInvalidStateError, match="Cannot activate"):
            spt.activate(uuid4())

    def test_deactivate_invalid_state(self, spt):
        with pytest.raises(SPTInvalidStateError, match="Cannot deactivate"):
            spt.deactivate(uuid4())

    def test_validate_success(self, spt):
        spt._total_bruto = Decimal("1000")
        spt._total_pph_terutang = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt.validate(uuid4())
        assert spt.status == SPTStatus.VALIDATED

    def test_validate_negative_bruto(self, spt):
        spt._total_bruto = Decimal("-100")
        with pytest.raises(SPTValidationError, match="total bruto tidak boleh negatif"):
            spt.validate(uuid4())

    def test_validate_negative_pph(self, spt):
        spt._total_pph_terutang = Decimal("-100")
        with pytest.raises(SPTValidationError, match="PPh terutang tidak boleh negatif"):
            spt.validate(uuid4())

    def test_validate_negative_bayar(self, spt):
        spt._total_bayar = Decimal("-100")
        with pytest.raises(SPTValidationError, match="Total bayar tidak boleh negatif"):
            spt.validate(uuid4())

    def test_validate_invalid_month(self, spt):
        spt._bulan = 13
        with pytest.raises(SPTValidationError, match="Bulan pajak tidak valid"):
            spt.validate(uuid4())

    def test_validate_invalid_year(self, spt):
        spt._tahun = 1999
        with pytest.raises(SPTValidationError, match="Tahun pajak tidak valid"):
            spt.validate(uuid4())

    def test_validate_missing_ntpn(self, spt):
        spt._total_pph_terutang = Decimal("150")
        spt._total_bayar = Decimal("100")
        spt._ntpn = None
        with pytest.raises(SPTValidationError, match="kurang bayar tetapi tidak ada NTPN"):
            spt.validate(uuid4())

    def test_validate_invalid_ntpn_format(self, spt):
        spt._total_pph_terutang = Decimal("150")
        spt._total_bayar = Decimal("100")
        spt._ntpn = "invalid"
        with pytest.raises(SPTValidationError, match="Format NTPN tidak valid"):
            spt.validate(uuid4())

    def test_validate_locked(self, spt):
        spt.lock(uuid4())
        with pytest.raises(SPTLockedError):
            spt.validate(uuid4())

    def test_validate_invalid_state(self, spt):
        spt._status = SPTStatus.SUBMITTED
        with pytest.raises(SPTInvalidStateError, match="Cannot validate"):
            spt.validate(uuid4())

    def test_submit(self, spt):
        user = uuid4()
        spt._total_bruto = Decimal("1000")
        spt._total_pph_terutang = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._ntpn = "1234567890123456"
        spt.submit(user)
        assert spt.status == SPTStatus.SUBMITTED
        assert spt.submitted_at is not None
        assert spt.xml_content != ""

    def test_submit_invalid_state(self, spt):
        spt._status = SPTStatus.APPROVED
        with pytest.raises(SPTInvalidStateError, match="Cannot submit"):
            spt.submit(uuid4())

    def test_approve(self, spt):
        spt._status = SPTStatus.SUBMITTED
        user = uuid4()
        spt.approve(user, "ok")
        assert spt.status == SPTStatus.APPROVED
        assert spt.approved_at is not None

    def test_approve_invalid_state(self, spt):
        with pytest.raises(SPTInvalidStateError, match="Cannot approve"):
            spt.approve(uuid4())

    def test_reject(self, spt):
        spt._status = SPTStatus.PENDING
        user = uuid4()
        spt.reject(user, "reason")
        assert spt.status == SPTStatus.REJECTED
        assert spt.rejection_reason == "reason"

    def test_reject_invalid_state(self, spt):
        spt._status = SPTStatus.DRAFT
        with pytest.raises(SPTInvalidStateError, match="Cannot reject"):
            spt.reject(uuid4(), "reason")

    def test_cancel_and_void(self, spt):
        user = uuid4()
        spt.cancel(user, "test cancel")
        assert spt.status == SPTStatus.CANCELLED
        assert spt.cancellation_reason == "test cancel"
        spt.void(user, "test void")
        assert spt.status == SPTStatus.VOID

    def test_cancel_invalid_state(self, spt):
        spt._status = SPTStatus.CANCELLED
        with pytest.raises(SPTInvalidStateError, match="Cannot cancel"):
            spt.cancel(uuid4(), "reason")

    def test_lock_unlock(self, spt):
        user = uuid4()
        spt.lock(user)
        assert spt.is_locked
        assert spt.locked_by == user
        assert spt.status == SPTStatus.LOCKED
        spt.unlock(user)
        assert not spt.is_locked
        assert spt.locked_by is None
        assert spt.status == SPTStatus.PENDING

    def test_lock_already_locked(self, spt):
        spt.lock(uuid4())
        with pytest.raises(SPTLockedError, match="already locked"):
            spt.lock(uuid4())

    def test_unlock_not_locked(self, spt):
        with pytest.raises(SPTLockedError, match="not locked"):
            spt.unlock(uuid4())

    def test_transition(self, spt):
        user = uuid4()
        spt.transition(SPTStatus.PENDING, user)
        assert spt.status == SPTStatus.PENDING
        history = spt.get_history()
        assert len(history) == 1
        assert history[0]["from_status"] == "draft"
        assert history[0]["to_status"] == "pending"

    def test_transition_invalid(self, spt):
        with pytest.raises(SPTInvalidStateError, match="Status transition invalid"):
            spt.transition(SPTStatus.APPROVED, uuid4())

    def test_get_status(self, spt):
        status = spt.get_status()
        assert status["status"] == "draft"
        assert status["is_locked"] is False
        assert status["masa_pajak"] == "2024-01"

    def test_calculate_tax(self, spt):
        # test bracket 5%
        assert spt.calculate_tax(Decimal("50000000")) == Decimal("2500000.00")
        # test mixed: 60jt at 5%, 40jt at 15%
        netto = Decimal("100000000")
        expected = Decimal("60000000") * Decimal("0.05") + Decimal("40000000") * Decimal("0.15")
        assert spt.calculate_tax(netto) == expected.quantize(Decimal("0.01"))

    def test_calculate_ptkp(self, spt):
        assert spt.calculate_ptkp("TK/0") == Decimal("54000000")
        assert spt.calculate_ptkp("TK/1") == Decimal("58500000")
        assert spt.calculate_ptkp("K/3") == Decimal("72000000")
        assert spt.calculate_ptkp("INVALID") == Decimal("54000000")  # default

    def test_collect_employee_data(self, spt):
        employees = [
            {"npwp": "111", "name": "A", "ptkp_status": "TK/0", "gross": "1000", "pph21": "50"},
            {"npwp": "222", "name": "B", "ptkp_status": "K/1", "gross": "2000", "pph21": "100"},
        ]
        spt.collect_employee_data(employees)
        assert spt.employee_count == 2
        assert spt.total_bruto == Decimal("3000")
        assert spt.total_pph_terutang == Decimal("150")
        assert spt.total_bayar == Decimal("150")
        assert spt.detail_karyawan[0]["npwp"] == "111"
        assert spt.detail_karyawan[0]["bruto"] == "1000"
        assert spt.detail_karyawan[0]["pph21"] == "50"

    def test_set_ntpn(self, spt):
        spt.set_ntpn("1234567890123456", validated=True)
        assert spt.ntpn == "1234567890123456"
        assert spt.status == SPTStatus.VALIDATED

        # test without validated
        spt._status = SPTStatus.DRAFT
        spt.set_ntpn("9876543210987654", validated=False)
        assert spt.ntpn == "9876543210987654"
        assert spt.status == SPTStatus.DRAFT  # status unchanged

        # invalid NTPN
        with pytest.raises(SPTValidationError, match="Invalid NTPN format"):
            spt.set_ntpn("invalid")

    def test_set_coretax_response(self, spt):
        response = {
            "spt_number": "SPT001",
            "tracking_id": "TRK123",
            "coretax_id": "CTX456",
            "status": "success",
        }
        spt.set_coretax_response(response)
        assert spt.spt_number == "SPT001"
        assert spt.tracking_id == "TRK123"
        assert spt.coretax_id == "CTX456"
        assert spt.status == SPTStatus.SUBMITTED

        # failure response
        spt._status = SPTStatus.DRAFT
        response2 = {"status": "error"}
        spt.set_coretax_response(response2)
        assert spt.status == SPTStatus.DRAFT  # unchanged

    def test_to_dict_from_dict(self, spt):
        d = spt.to_dict()
        assert d["npwp_pemotong"] == spt.npwp_pemotong
        assert d["tahun"] == spt.tahun
        assert d["bulan"] == spt.bulan
        assert d["total_bruto"] == str(spt.total_bruto)
        assert "spt_id" in d

        new_spt = SPTMasaPPH21.from_dict(d)
        assert new_spt.npwp_pemotong == spt.npwp_pemotong
        assert new_spt.tahun == spt.tahun
        assert new_spt.bulan == spt.bulan
        assert new_spt.total_bruto == spt.total_bruto

    def test_snapshot(self, spt):
        snap = spt.snapshot()
        assert snap["spt_id"] == str(spt.spt_id)
        assert snap["npwp_pemotong"] == spt.npwp_pemotong
        assert "total_bruto" in snap

    def test_audit_trail_and_events(self, spt):
        user = uuid4()
        spt.create(user)
        assert len(spt.get_events()) == 1
        spt.transition(SPTStatus.PENDING, user)
        assert len(spt.get_history()) == 1
        assert spt.audit_trail() == spt.get_history()


# ============================================================================
# Abstract repository interface - skipped with clear reason
# ============================================================================
class TestSPTRepositoryPort:
    """SPTRepositoryPort is an abstract interface, not meant to be instantiated."""
    @pytest.mark.skip(reason="Abstract interface, not meant to be instantiated.")
    def test_abstract_interface(self):
        pass


# ============================================================================
# Fallback in-memory repository
# ============================================================================
class TestFallbackSPTRepository:
    @pytest.fixture
    def repo(self):
        return _FallbackSPTRepository()

    @pytest.fixture
    def spt(self):
        return SPTMasaPPH21(
            npwp_pemotong="123456789012345",
            tahun=2024,
            bulan=1,
            total_bruto=Decimal("1000"),
            total_pph_terutang=Decimal("100"),
            total_bayar=Decimal("100"),
            ntpn="1234567890123456",
        )

    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self, repo, spt):
        await repo.add(spt)
        found = await repo.get_by_id(spt.spt_id)
        assert found is spt

    @pytest.mark.asyncio
    async def test_save(self, repo, spt):
        await repo.add(spt)
        spt._total_pph_terutang = Decimal("200")
        await repo.save(spt)
        updated = await repo.get_by_id(spt.spt_id)
        assert updated.total_pph_terutang == Decimal("200")

    @pytest.mark.asyncio
    async def test_update(self, repo, spt):
        await repo.add(spt)
        spt._total_pph_terutang = Decimal("300")
        await repo.update(spt)
        updated = await repo.get_by_id(spt.spt_id)
        assert updated.total_pph_terutang == Decimal("300")

    @pytest.mark.asyncio
    async def test_delete(self, repo, spt):
        await repo.add(spt)
        await repo.delete(spt.spt_id)
        assert await repo.get_by_id(spt.spt_id) is None

    @pytest.mark.asyncio
    async def test_get_by_npwp_period(self, repo, spt):
        await repo.add(spt)
        found = await repo.get_by_npwp_period("123456789012345", 2024, 1)
        assert found is spt
        not_found = await repo.get_by_npwp_period("999", 2024, 1)
        assert not_found is None

    @pytest.mark.asyncio
    async def test_get_by_tracking_id(self, repo, spt):
        spt._tracking_id = "TRK123"
        await repo.add(spt)
        found = await repo.get_by_tracking_id("TRK123")
        assert found is spt
        assert await repo.get_by_tracking_id("missing") is None

    @pytest.mark.asyncio
    async def test_get_by_status(self, repo, spt):
        await repo.add(spt)
        drafts = await repo.get_by_status(SPTStatus.DRAFT)
        assert drafts == [spt]
        pendings = await repo.get_by_status(SPTStatus.PENDING)
        assert pendings == []

    @pytest.mark.asyncio
    async def test_get_pending_submissions(self, repo, spt):
        await repo.add(spt)
        pending = await repo.get_pending_submissions()
        assert spt in pending

    @pytest.mark.asyncio
    async def test_exists(self, repo, spt):
        await repo.add(spt)
        assert await repo.exists("123456789012345", 2024, 1) is True
        assert await repo.exists("999", 2024, 1) is False


# ============================================================================
# Builder tests
# ============================================================================
class TestSPTMasaPPH21Builder:
    @pytest.fixture
    def mock_repo(self):
        return AsyncMock(spec=SPTRepositoryPort)

    @pytest.fixture
    def builder(self, mock_repo):
        b = SPTMasaPPH21Builder(config={})
        b._repository = mock_repo
        return b

    @pytest.fixture
    def spt(self):
        return SPTMasaPPH21(
            npwp_pemotong="123456789012345",
            tahun=2024,
            bulan=1,
            total_bruto=Decimal("1000"),
            total_pph_terutang=Decimal("100"),
            total_bayar=Decimal("100"),
            ntpn="1234567890123456",
        )

    @pytest.mark.asyncio
    async def test_create_new(self, builder, mock_repo):
        mock_repo.get_by_npwp_period.return_value = None
        mock_repo.add.return_value = None
        result = await builder.create("123456789012345", 2024, 1, uuid4())
        assert result["success"] is True
        assert "spt_id" in result
        assert result["status"] == "draft"
        mock_repo.add.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_already_exists(self, builder, mock_repo, spt):
        mock_repo.get_by_npwp_period.return_value = spt
        result = await builder.create("123456789012345", 2024, 1, uuid4())
        assert result["success"] is False
        assert "already exists" in result["error"]
        mock_repo.add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_error_with_rollback(self, builder, mock_repo):
        mock_repo.get_by_npwp_period.side_effect = Exception("DB error")
        result = await builder.create("123", 2024, 1, uuid4())
        assert result["success"] is False
        assert "DB error" in result["error"]

    @pytest.mark.asyncio
    async def test_collect_data_success(self, builder):
        mock_payroll = AsyncMock()
        mock_payroll.get_employees_with_pph21.return_value = [
            {"employee_id": "e1", "npwp": "111", "name": "A", "ptkp_status": "TK/0"},
            {"employee_id": "e2", "npwp": "222", "name": "B", "ptkp_status": "K/1"},
        ]
        mock_payroll.get_gross_income.side_effect = [Decimal("1000"), Decimal("2000")]
        mock_payroll.calculate_pph21.side_effect = [Decimal("50"), Decimal("100")]

        mock_tax = AsyncMock()
        mock_tax.get_ntpn_for_period.return_value = {"ntpn": "1234567890123456"}

        with patch.object(builder, "_get_payroll_service", return_value=mock_payroll):
            with patch.object(builder, "_get_tax_service", return_value=mock_tax):
                data = await builder.collect_data("123456789012345", 2024, 1)

        assert data["total_bruto"] == Decimal("3000")
        assert data["total_pph_terutang"] == Decimal("150")
        assert data["total_bayar"] == Decimal("150")
        assert data["ntpn"] == "1234567890123456"
        assert data["employee_count"] == 2
        assert len(data["detail_karyawan"]) == 2

    @pytest.mark.asyncio
    async def test_collect_data_error(self, builder):
        mock_payroll = AsyncMock()
        mock_payroll.get_employees_with_pph21.side_effect = Exception("Service error")

        with patch.object(builder, "_get_payroll_service", return_value=mock_payroll):
            with patch.object(builder, "_get_tax_service", return_value=AsyncMock()):
                data = await builder.collect_data("123", 2024, 1)

        assert "error" in data
        assert data["total_bruto"] == Decimal(0)
        assert data["employee_count"] == 0

    @pytest.mark.asyncio
    async def test_build_creates_new(self, builder, mock_repo):
        mock_repo.get_by_npwp_period.return_value = None
        mock_repo.add.return_value = None

        with patch.object(builder, "collect_data", return_value={
            "npwp_pemotong": "123", "tahun": 2024, "bulan": 1,
            "total_bruto": Decimal("1000"), "total_pph_terutang": Decimal("100"),
            "total_bayar": Decimal("100"), "ntpn": None,
            "detail_karyawan": [], "employee_count": 0
        }):
            result = await builder.build("123", 2024, 1, uuid4())
        assert result["success"] is True
        assert "spt_id" in result

    @pytest.mark.asyncio
    async def test_build_updates_existing(self, builder, mock_repo, spt):
        mock_repo.get_by_npwp_period.return_value = spt
        mock_repo.update.return_value = None

        with patch.object(builder, "collect_data", return_value={
            "npwp_pemotong": "123456789012345", "tahun": 2024, "bulan": 1,
            "total_bruto": Decimal("2000"), "total_pph_terutang": Decimal("200"),
            "total_bayar": Decimal("200"), "ntpn": "9876543210987654",
            "detail_karyawan": [{"npwp": "111", "nama": "A"}], "employee_count": 1
        }):
            result = await builder.build("123456789012345", 2024, 1, uuid4())
        assert result["success"] is True
        assert spt.total_bruto == Decimal("2000")
        assert spt.ntpn == "9876543210987654"
        assert len(spt.detail_karyawan) == 1
        mock_repo.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_build_error_rollback(self, builder, mock_repo):
        mock_repo.get_by_npwp_period.side_effect = Exception("DB error")
        result = await builder.build("123", 2024, 1, uuid4())
        assert result["success"] is False
        assert "DB error" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_spt_ok(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        mock_repo.update.return_value = None
        spt._total_bruto = Decimal("1000")
        spt._total_pph_terutang = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._ntpn = "1234567890123456"

        result = await builder.validate_spt(spt.spt_id, uuid4())
        assert result["success"] is True
        assert result["valid"] is True
        assert result["status"] == SPTStatus.VALIDATED.value
        mock_repo.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_validate_spt_not_found(self, builder, mock_repo):
        mock_repo.get_by_id.return_value = None
        result = await builder.validate_spt(uuid4(), uuid4())
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_spt_validation_fails(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        spt._total_bruto = Decimal("-100")
        result = await builder.validate_spt(spt.spt_id, uuid4())
        assert result["success"] is False
        assert "Validasi gagal" in result["error"]
        mock_repo.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_validate_spt_locked(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        spt.lock(uuid4())
        result = await builder.validate_spt(spt.spt_id, uuid4())
        assert result["success"] is False
        assert "locked" in result["error"]
        mock_repo.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_submit_spt_success(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        mock_repo.update.return_value = None
        spt._total_bruto = Decimal("1000")
        spt._total_pph_terutang = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._ntpn = "1234567890123456"

        mock_client = AsyncMock()
        mock_client.post.return_value = {
            "spt_number": "SPT001",
            "tracking_id": "TRK123",
            "coretax_id": "CTX456",
            "status": "success",
            "message": "OK",
        }

        with patch.object(builder, "_get_coretax_client", return_value=mock_client):
            with patch.object(builder, "_file_storage", None):
                result = await builder.submit_spt(spt.spt_id, uuid4())

        assert result["success"] is True
        assert result["spt_number"] == "SPT001"
        assert result["status"] == SPTStatus.SUBMITTED.value
        mock_client.post.assert_awaited_once_with(
            CORETAX_SPT_PPH21_ENDPOINT,
            {
                "spt_xml": spt._generate_xml(),
                "npwp": spt.npwp_pemotong,
                "tahun": spt.tahun,
                "bulan": spt.bulan,
                "spt_type": SPTType.NORMAL.value,
                "correction_number": 0,
            }
        )

    @pytest.mark.asyncio
    async def test_submit_spt_auth_error(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        spt._total_bruto = Decimal("1000")
        spt._total_pph_terutang = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._ntpn = "1234567890123456"

        mock_client = AsyncMock()
        from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError
        mock_client.post.side_effect = CoretaxAuthError("auth failed")

        with patch.object(builder, "_get_coretax_client", return_value=mock_client):
            result = await builder.submit_spt(spt.spt_id, uuid4())

        assert result["success"] is False
        assert "Coretax authentication failed" in result["error"]
        assert spt.status == SPTStatus.ERROR

    @pytest.mark.asyncio
    async def test_submit_spt_validation_fails(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        spt._total_bruto = Decimal("-100")  # invalid
        result = await builder.submit_spt(spt.spt_id, uuid4())
        assert result["success"] is False
        assert "Validasi" in result["error"]

    @pytest.mark.asyncio
    async def test_check_spt_status(self, builder, mock_repo, spt):
        spt._tracking_id = "TRK123"
        mock_repo.get_by_id.return_value = spt
        mock_repo.update.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = {
            "status": "approved",
            "approval_date": "2024-01-01",
            "rejection_reason": None,
        }

        with patch.object(builder, "_get_coretax_client", return_value=mock_client):
            result = await builder.check_spt_status(spt.spt_id)

        assert result["success"] is True
        assert result["status"] == SPTStatus.APPROVED.value
        assert result["coretax_status"] == "approved"
        mock_client.get.assert_awaited_once_with("/api/v1/spt/status/TRK123")

    @pytest.mark.asyncio
    async def test_check_spt_status_not_found(self, builder, mock_repo):
        mock_repo.get_by_id.return_value = None
        result = await builder.check_spt_status(uuid4())
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_check_spt_status_no_tracking_id(self, builder, mock_repo, spt):
        spt._tracking_id = None
        mock_repo.get_by_id.return_value = spt
        result = await builder.check_spt_status(spt.spt_id)
        assert result["success"] is True
        assert result["message"] == "Not yet submitted to Coretax"

    @pytest.mark.asyncio
    async def test_cancel_spt(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        mock_repo.update.return_value = None
        spt._tracking_id = "TRK123"

        mock_client = AsyncMock()
        mock_client.post.return_value = {"status": "cancelled"}

        with patch.object(builder, "_get_coretax_client", return_value=mock_client):
            result = await builder.cancel_spt(spt.spt_id, uuid4(), "test reason")

        assert result["success"] is True
        assert result["cancelled"] is True
        assert spt.status == SPTStatus.CANCELLED
        mock_client.post.assert_awaited_once_with("/api/v1/spt/cancel", {"tracking_id": "TRK123", "reason": "test reason"})

    @pytest.mark.asyncio
    async def test_cancel_spt_not_found(self, builder, mock_repo):
        mock_repo.get_by_id.return_value = None
        result = await builder.cancel_spt(uuid4(), uuid4(), "reason")
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_cancel_spt_locked(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        spt.lock(uuid4())
        result = await builder.cancel_spt(spt.spt_id, uuid4(), "reason")
        assert result["success"] is False
        assert "locked" in result["error"]

    @pytest.mark.asyncio
    async def test_get_by_id(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        result = await builder.get_by_id(spt.spt_id)
        assert result is spt

    @pytest.mark.asyncio
    async def test_get_by_npwp_period(self, builder, mock_repo, spt):
        mock_repo.get_by_npwp_period.return_value = spt
        result = await builder.get_by_npwp_period("123456789012345", 2024, 1)
        assert result is spt

    @pytest.mark.asyncio
    async def test_get_status(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        result = await builder.get_status(spt.spt_id)
        assert result["status"] == "draft"
        assert result["masa_pajak"] == "2024-01"

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, builder, mock_repo):
        mock_repo.get_by_id.return_value = None
        result = await builder.get_status(uuid4())
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_get_history(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        spt._history.append({"event": "test"})
        result = await builder.get_history(spt.spt_id)
        assert result["success"] is True
        assert len(result["history"]) == 1

    @pytest.mark.asyncio
    async def test_get_history_not_found(self, builder, mock_repo):
        mock_repo.get_by_id.return_value = None
        result = await builder.get_history(uuid4())
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_snapshot(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        snap = await builder.snapshot(spt.spt_id)
        assert snap["spt_id"] == str(spt.spt_id)

    @pytest.mark.asyncio
    async def test_snapshot_not_found(self, builder, mock_repo):
        mock_repo.get_by_id.return_value = None
        result = await builder.snapshot(uuid4())
        assert result["success"] is False
        assert "not found" in result["error"]


# ============================================================================
# Module-level getter
# ============================================================================
@pytest.mark.asyncio
async def test_get_spt_pph21_builder():
    builder1 = await get_spt_pph21_builder(config={"test": True})
    builder2 = await get_spt_pph21_builder()
    assert builder1 is builder2
    assert isinstance(builder1, SPTMasaPPH21Builder)