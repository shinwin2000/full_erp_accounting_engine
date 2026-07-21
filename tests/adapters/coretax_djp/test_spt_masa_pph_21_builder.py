# tests/adapters/coretax_djp/test_spt_masa_pph_21_builder.py
# Perbaikan kualitas assertions:
# - Semua async test diberi @pytest.mark.asyncio
# - Dead test di TestSPTRepositoryPort di-skip dengan alasan jelas (abstract interface)
# - Duplikasi exception test diganti dengan parametrize
# - Flaky tests menggunakan mock datetime
# - Assertion diperkuat, tidak ada assert True kosong

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from uuid import UUID, uuid4

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
# FIXED DATETIME - untuk menghindari flaky tests
# ============================================================================
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now() untuk menghindari flaky tests."""
    with patch("adapters.coretax_djp.spt_masa_pph_21_builder.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        yield mock_dt


# ============================================================================
# Enum tests
# ============================================================================
class TestSPTType:
    def test_members_exist(self):
        assert hasattr(SPTType, "NORMAL")
        assert hasattr(SPTType, "CORRECTION")
        assert hasattr(SPTType, "VOID")

    def test_member_is_instance(self):
        assert isinstance(SPTType.NORMAL, SPTType)


class TestSPTStatus:
    def test_members_exist(self):
        expected = [
            "DRAFT",
            "PENDING",
            "VALIDATED",
            "SUBMITTED",
            "APPROVED",
            "REJECTED",
            "CANCELLED",
            "VOID",
            "POSTED",
            "CLOSED",
            "ARCHIVED",
            "LOCKED",
            "ERROR",
            "SYNCED",
        ]
        for name in expected:
            assert hasattr(SPTStatus, name)

    def test_member_is_instance(self):
        assert isinstance(SPTStatus.DRAFT, SPTStatus)


# ============================================================================
# Custom exception classes - parametrized untuk menghindari duplikasi
# ============================================================================
@pytest.mark.parametrize("exception_class", [
    SPTError,
    SPTNotFoundError,
    SPTAlreadyExistsError,
    SPTInvalidStateError,
    SPTValidationError,
    SPTLockedError,
    SPTXMLGenerationError,
])
class TestSPTExceptions:
    def test_construction(self, exception_class):
        instance = exception_class()
        assert isinstance(instance, exception_class)
        assert isinstance(instance, Exception)


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
            correction_number=0,
            total_bruto=Decimal("1000.00"),
            total_pph_terutang=Decimal("100.00"),
            total_bayar=Decimal("100.00"),
            ntpn="1234567890123456",
            spt_id=uuid4(),
            status=SPTStatus.DRAFT,
            version=1,
        )

    def test_construction(self, spt: SPTMasaPPH21):
        assert isinstance(spt, SPTMasaPPH21)
        assert spt.npwp_pemotong == "123456789012345"
        assert spt.tahun == 2024
        assert spt.bulan == 1
        assert spt.spt_type == SPTType.NORMAL
        assert spt.correction_number == 0
        assert spt.total_bruto == Decimal("1000.00")
        assert spt.total_pph_terutang == Decimal("100.00")
        assert spt.total_bayar == Decimal("100.00")
        assert spt.ntpn == "1234567890123456"
        assert spt.status == SPTStatus.DRAFT
        assert spt.version == 1

    def test_masa_pajak(self, spt: SPTMasaPPH21):
        assert spt.masa_pajak == "2024-01"

    def test_total_bruto(self, spt: SPTMasaPPH21):
        assert spt.total_bruto == Decimal("1000.00")

    def test_total_pph_terutang(self, spt: SPTMasaPPH21):
        assert spt.total_pph_terutang == Decimal("100.00")

    def test_total_bayar(self, spt: SPTMasaPPH21):
        assert spt.total_bayar == Decimal("100.00")

    def test_kurang_bayar(self, spt: SPTMasaPPH21):
        # total_pph_terutang == total_bayar => kurang bayar 0
        assert spt.kurang_bayar == Decimal(0)

        spt._total_pph_terutang = Decimal("150.00")
        assert spt.kurang_bayar == Decimal("50.00")

    def test_lebih_bayar(self, spt: SPTMasaPPH21):
        assert spt.lebih_bayar == Decimal(0)
        spt._total_bayar = Decimal("200.00")
        spt._total_pph_terutang = Decimal("100.00")
        assert spt.lebih_bayar == Decimal("100.00")

    def test_ntpn_masked(self, spt: SPTMasaPPH21):
        assert spt.ntpn_masked == "12345678...3456"
        spt._ntpn = None
        assert spt.ntpn_masked is None
        spt._ntpn = "123"
        assert spt.ntpn_masked == "123"

    def test_properties_is_locked_and_is_active(self, spt: SPTMasaPPH21):
        assert not spt.is_locked
        assert spt.is_active

        spt._locked_at = FIXED_NOW
        assert spt.is_locked

        spt._status = SPTStatus.CANCELLED
        assert not spt.is_active

    def test_create_method(self, spt: SPTMasaPPH21):
        user_id = uuid4()
        result = spt.create(created_by=user_id)
        assert result is spt
        assert spt.status == SPTStatus.DRAFT
        assert spt.version == 2
        events = spt.get_events()
        assert any(e["event_type"] == "spt_pph21_created" for e in events)
        assert events[-1]["data"]["created_by"] == str(user_id)

    def test_update_method(self, spt: SPTMasaPPH21):
        user_id = uuid4()
        spt.create(user_id)  # set status draft
        old_version = spt.version
        data = {
            "total_bruto": "2000.00",
            "total_pph_terutang": "200.00",
            "total_bayar": "200.00",
            "ntpn": "9876543210987654",
            "detail_karyawan": [{"npwp": "123", "nama": "A"}],
        }
        spt.update(data, user_id)
        assert spt.total_bruto == Decimal("2000.00")
        assert spt.total_pph_terutang == Decimal("200.00")
        assert spt.total_bayar == Decimal("200.00")
        assert spt.ntpn == "9876543210987654"
        assert len(spt.detail_karyawan) == 1
        assert spt.version == old_version + 1
        events = spt.get_events()
        assert any(e["event_type"] == "spt_pph21_updated" for e in events)

    def test_update_locked_raises(self, spt: SPTMasaPPH21):
        spt._locked_at = FIXED_NOW
        with pytest.raises(SPTLockedError):
            spt.update({}, uuid4())

    def test_delete_method(self, spt: SPTMasaPPH21):
        user_id = uuid4()
        spt.delete(user_id, permanent=False)
        assert spt.status == SPTStatus.ARCHIVED
        assert spt.cancelled_at is not None
        events = spt.get_events()
        assert any(e["event_type"] == "spt_pph21_deleted" for e in events)

        spt.restore(user_id)
        assert spt.status == SPTStatus.DRAFT
        assert spt.cancelled_at is None

        spt.delete(user_id, permanent=True)
        assert spt.status == SPTStatus.VOID

    def test_activate_deactivate(self, spt: SPTMasaPPH21):
        user = uuid4()
        spt.activate(user)
        assert spt.status == SPTStatus.PENDING
        spt.deactivate(user)
        assert spt.status == SPTStatus.DRAFT

    def test_validate_method_ok(self, spt: SPTMasaPPH21):
        user = uuid4()
        # set kondisi valid
        spt._total_bruto = Decimal("1000")
        spt._total_pph_terutang = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._ntpn = None
        spt._bulan = 5
        spt._tahun = 2024
        spt.validate(user)
        assert spt.status == SPTStatus.VALIDATED

    def test_validate_invalid_negative(self, spt: SPTMasaPPH21):
        spt._total_bruto = Decimal("-100")
        with pytest.raises(SPTValidationError, match="total bruto tidak boleh negatif"):
            spt.validate(uuid4())

    def test_submit_method(self, spt: SPTMasaPPH21):
        user = uuid4()
        spt._total_bruto = Decimal("1000")
        spt._total_pph_terutang = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt.submit(user)
        assert spt.status == SPTStatus.SUBMITTED
        assert spt.submitted_at is not None
        assert spt.xml_content != ""

    def test_cancel_and_void(self, spt: SPTMasaPPH21):
        user = uuid4()
        spt.cancel(user, "reason")
        assert spt.status == SPTStatus.CANCELLED
        assert spt.cancellation_reason == "reason"

        spt.void(user, "void reason")
        assert spt.status == SPTStatus.VOID

    def test_lock_unlock(self, spt: SPTMasaPPH21):
        user = uuid4()
        spt.lock(user)
        assert spt.is_locked
        assert spt.locked_by == user
        assert spt.status == SPTStatus.LOCKED

        spt.unlock(user)
        assert not spt.is_locked
        assert spt.locked_by is None
        assert spt.status == SPTStatus.PENDING

    def test_transition(self, spt: SPTMasaPPH21):
        user = uuid4()
        spt.transition(SPTStatus.PENDING, user)
        assert spt.status == SPTStatus.PENDING
        history = spt.get_history()
        assert len(history) == 1
        assert history[0]["from_status"] == "draft"
        assert history[0]["to_status"] == "pending"

        with pytest.raises(SPTInvalidStateError):
            spt.transition(SPTStatus.APPROVED, user)

    def test_get_status(self, spt: SPTMasaPPH21):
        status = spt.get_status()
        assert status["status"] == "draft"
        assert status["is_locked"] is False
        assert status["is_active"] is True
        assert "masa_pajak" in status

    def test_calculate_tax(self, spt: SPTMasaPPH21):
        # test bracket 5%
        assert spt.calculate_tax(Decimal("50000000")) == Decimal("2500000.00")
        # test campuran
        netto = Decimal("100000000")  # 60jt 5%, 40jt 15%
        expected = Decimal("60000000") * Decimal("0.05") + Decimal("40000000") * Decimal("0.15")
        assert spt.calculate_tax(netto) == expected.quantize(Decimal("0.01"))

    def test_calculate_ptkp(self, spt: SPTMasaPPH21):
        assert spt.calculate_ptkp("TK/0") == Decimal("54000000")
        assert spt.calculate_ptkp("K/3") == Decimal("72000000")
        assert spt.calculate_ptkp("INVALID") == Decimal("54000000")

    def test_collect_employee_data(self, spt: SPTMasaPPH21):
        employees = [
            {"npwp": "111", "name": "A", "ptkp_status": "TK/0", "gross": "1000", "pph21": "50"},
            {"npwp": "222", "name": "B", "ptkp_status": "K/1", "gross": "2000", "pph21": "100"},
        ]
        spt.collect_employee_data(employees)
        assert spt.employee_count == 2
        assert spt.total_bruto == Decimal("3000")
        assert spt.total_pph_terutang == Decimal("150")
        assert spt.total_bayar == Decimal("150")
        assert len(spt.detail_karyawan) == 2
        assert spt.detail_karyawan[0]["npwp"] == "111"

    def test_set_ntpn(self, spt: SPTMasaPPH21):
        spt.set_ntpn("1234567890123456", validated=True)
        assert spt.ntpn == "1234567890123456"
        assert spt.status == SPTStatus.VALIDATED

        with pytest.raises(SPTValidationError):
            spt.set_ntpn("invalid")

    def test_to_dict_and_from_dict(self, spt: SPTMasaPPH21):
        d = spt.to_dict()
        assert d["npwp_pemotong"] == "123456789012345"
        assert d["tahun"] == 2024
        assert "spt_id" in d

        new_spt = SPTMasaPPH21.from_dict(d)
        assert new_spt.npwp_pemotong == spt.npwp_pemotong
        assert new_spt.tahun == spt.tahun
        assert new_spt.bulan == spt.bulan

    def test_snapshot(self, spt: SPTMasaPPH21):
        snap = spt.snapshot()
        assert snap["spt_id"] == str(spt.spt_id)
        assert "total_bruto" in snap

    def test_audit_trail_and_events(self, spt: SPTMasaPPH21):
        user = uuid4()
        spt.create(user)
        events = spt.get_events()
        assert len(events) > 0
        # history awal kosong
        assert spt.get_history() == []
        spt.transition(SPTStatus.PENDING, user)
        assert len(spt.get_history()) == 1


# ============================================================================
# Repository interface (abstract) - di-skip karena tidak ada implementasi
# ============================================================================
class TestSPTRepositoryPort:
    @pytest.mark.skip(reason="SPTRepositoryPort is an abstract interface, not meant to be instantiated.")
    def test_construction(self):
        pass

    @pytest.mark.skip(reason="Abstract method, tidak diimplementasikan")
    async def test_add_smoke(self):
        pass

    @pytest.mark.skip(reason="Abstract method, tidak diimplementasikan")
    async def test_save_smoke(self):
        pass

    @pytest.mark.skip(reason="Abstract method, tidak diimplementasikan")
    async def test_update_smoke(self):
        pass

    @pytest.mark.skip(reason="Abstract method, tidak diimplementasikan")
    async def test_delete_smoke(self):
        pass


# ============================================================================
# Fallback in-memory repository
# ============================================================================
class Test_FallbackSPTRepository:
    @pytest.fixture
    def repo(self) -> _FallbackSPTRepository:
        return _FallbackSPTRepository()

    @pytest.fixture
    def spt(self) -> SPTMasaPPH21:
        return SPTMasaPPH21(
            npwp_pemotong="123456789012345",
            tahun=2024,
            bulan=1,
            spt_type=SPTType.NORMAL,
            correction_number=0,
            total_bruto=Decimal("1000.00"),
            total_pph_terutang=Decimal("100.00"),
            total_bayar=Decimal("100.00"),
            ntpn="1234567890123456",
            spt_id=uuid4(),
            status=SPTStatus.DRAFT,
            version=1,
        )

    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self, repo: _FallbackSPTRepository, spt: SPTMasaPPH21):
        await repo.add(spt)
        stored = await repo.get_by_id(spt.spt_id)
        assert stored is spt
        assert stored.npwp_pemotong == spt.npwp_pemotong

    @pytest.mark.asyncio
    async def test_save(self, repo: _FallbackSPTRepository, spt: SPTMasaPPH21):
        await repo.add(spt)
        spt._total_pph_terutang = Decimal("200")
        await repo.save(spt)
        stored = await repo.get_by_id(spt.spt_id)
        assert stored.total_pph_terutang == Decimal("200")

    @pytest.mark.asyncio
    async def test_update(self, repo: _FallbackSPTRepository, spt: SPTMasaPPH21):
        await repo.add(spt)
        spt._total_pph_terutang = Decimal("300")
        await repo.update(spt)
        stored = await repo.get_by_id(spt.spt_id)
        assert stored.total_pph_terutang == Decimal("300")

    @pytest.mark.asyncio
    async def test_delete(self, repo: _FallbackSPTRepository, spt: SPTMasaPPH21):
        await repo.add(spt)
        await repo.delete(spt.spt_id)
        stored = await repo.get_by_id(spt.spt_id)
        assert stored is None

    @pytest.mark.asyncio
    async def test_get_by_npwp_period(self, repo: _FallbackSPTRepository, spt: SPTMasaPPH21):
        await repo.add(spt)
        found = await repo.get_by_npwp_period("123456789012345", 2024, 1)
        assert found is spt
        not_found = await repo.get_by_npwp_period("999", 2024, 1)
        assert not_found is None

    @pytest.mark.asyncio
    async def test_get_by_tracking_id(self, repo: _FallbackSPTRepository, spt: SPTMasaPPH21):
        spt._tracking_id = "TRK123"
        await repo.add(spt)
        found = await repo.get_by_tracking_id("TRK123")
        assert found is spt
        assert await repo.get_by_tracking_id("missing") is None

    @pytest.mark.asyncio
    async def test_get_by_status(self, repo: _FallbackSPTRepository, spt: SPTMasaPPH21):
        await repo.add(spt)
        drafts = await repo.get_by_status(SPTStatus.DRAFT)
        assert drafts == [spt]
        pendings = await repo.get_by_status(SPTStatus.PENDING)
        assert pendings == []

    @pytest.mark.asyncio
    async def test_get_pending_submissions(self, repo: _FallbackSPTRepository, spt: SPTMasaPPH21):
        await repo.add(spt)
        pending = await repo.get_pending_submissions()
        assert spt in pending

    @pytest.mark.asyncio
    async def test_exists(self, repo: _FallbackSPTRepository, spt: SPTMasaPPH21):
        await repo.add(spt)
        assert await repo.exists("123456789012345", 2024, 1) is True
        assert await repo.exists("999", 2024, 1) is False


# ============================================================================
# Builder
# ============================================================================
class TestSPTMasaPPH21Builder:
    @pytest.fixture
    def mock_repo(self) -> AsyncMock:
        repo = AsyncMock(spec=SPTRepositoryPort)
        return repo

    @pytest.fixture
    def builder(self, mock_repo: AsyncMock) -> SPTMasaPPH21Builder:
        b = SPTMasaPPH21Builder(config={})
        b._repository = mock_repo  # inject mock
        return b

    @pytest.fixture
    def spt(self) -> SPTMasaPPH21:
        return SPTMasaPPH21(
            npwp_pemotong="123456789012345",
            tahun=2024,
            bulan=1,
            spt_type=SPTType.NORMAL,
            correction_number=0,
            total_bruto=Decimal("1000.00"),
            total_pph_terutang=Decimal("100.00"),
            total_bayar=Decimal("100.00"),
            ntpn="1234567890123456",
            spt_id=uuid4(),
            status=SPTStatus.DRAFT,
            version=1,
        )

    @pytest.mark.asyncio
    async def test_create_new(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock):
        mock_repo.get_by_npwp_period.return_value = None
        mock_repo.add.return_value = None

        result = await builder.create("123456789012345", 2024, 1, uuid4())
        assert result["success"] is True
        assert "spt_id" in result
        assert result["status"] == "draft"
        mock_repo.add.assert_awaited_once()
        mock_repo.get_by_npwp_period.assert_awaited_once_with("123456789012345", 2024, 1)

    @pytest.mark.asyncio
    async def test_create_already_exists(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
        mock_repo.get_by_npwp_period.return_value = spt
        result = await builder.create("123456789012345", 2024, 1, uuid4())
        assert result["success"] is False
        assert "already exists" in result["error"]
        mock_repo.add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_collect_data(self, builder: SPTMasaPPH21Builder):
        # Mock payroll_service dan tax_service
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

        assert data["npwp_pemotong"] == "123456789012345"
        assert data["tahun"] == 2024
        assert data["bulan"] == 1
        assert data["total_bruto"] == Decimal("3000")
        assert data["total_pph_terutang"] == Decimal("150")
        assert data["total_bayar"] == Decimal("150")
        assert data["ntpn"] == "1234567890123456"
        assert data["employee_count"] == 2
        assert len(data["detail_karyawan"]) == 2

    @pytest.mark.asyncio
    async def test_build_creates_new(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock):
        mock_repo.get_by_npwp_period.return_value = None
        mock_repo.add.return_value = None

        # patch collect_data and create to return success
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
    async def test_build_updates_existing(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
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
        assert spt.total_pph_terutang == Decimal("200")
        assert spt.total_bayar == Decimal("200")
        assert spt.ntpn == "9876543210987654"
        assert len(spt.detail_karyawan) == 1
        mock_repo.update.assert_awaited_once_with(spt)

    @pytest.mark.asyncio
    async def test_validate_spt_ok(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
        mock_repo.get_by_id.return_value = spt
        mock_repo.update.return_value = None

        result = await builder.validate_spt(spt.spt_id, uuid4())
        assert result["success"] is True
        assert result["valid"] is True
        assert result["status"] == SPTStatus.VALIDATED.value
        mock_repo.update.assert_awaited_once_with(spt)

    @pytest.mark.asyncio
    async def test_validate_spt_not_found(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock):
        mock_repo.get_by_id.return_value = None
        result = await builder.validate_spt(uuid4(), uuid4())
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_spt_validation_fails(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
        mock_repo.get_by_id.return_value = spt
        # buat invalid
        spt._total_bruto = Decimal("-100")
        result = await builder.validate_spt(spt.spt_id, uuid4())
        assert result["success"] is False
        assert "Validasi gagal" in result["error"]
        mock_repo.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_submit_spt(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
        mock_repo.get_by_id.return_value = spt
        mock_repo.update.return_value = None

        # set data valid
        spt._total_bruto = Decimal("1000")
        spt._total_pph_terutang = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024

        # mock coretax client
        mock_client = AsyncMock()
        mock_client.post.return_value = {
            "spt_number": "SPT001",
            "tracking_id": "TRK123",
            "coretax_id": "CTX456",
            "status": "success",
            "message": "OK",
        }

        with patch.object(builder, "_get_coretax_client", return_value=mock_client):
            with patch.object(builder, "_file_storage", None):  # skip file storage
                result = await builder.submit_spt(spt.spt_id, uuid4())

        assert result["success"] is True
        assert result["spt_number"] == "SPT001"
        assert result["tracking_id"] == "TRK123"
        assert result["status"] == SPTStatus.SUBMITTED.value
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == CORETAX_SPT_PPH21_ENDPOINT
        assert "spt_xml" in call_args[0][1]
        assert call_args[0][1]["spt_xml"] is not None
        assert call_args[0][1]["npwp"] == "123456789012345"
        assert call_args[0][1]["tahun"] == 2024
        assert call_args[0][1]["bulan"] == 5

    @pytest.mark.asyncio
    async def test_submit_spt_auth_failure(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
        mock_repo.get_by_id.return_value = spt
        spt._total_bruto = Decimal("1000")
        spt._total_pph_terutang = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024

        mock_client = AsyncMock()
        from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError
        mock_client.post.side_effect = CoretaxAuthError("auth failed")

        with patch.object(builder, "_get_coretax_client", return_value=mock_client):
            result = await builder.submit_spt(spt.spt_id, uuid4())
        assert result["success"] is False
        assert "Coretax authentication failed" in result["error"]
        assert spt.status == SPTStatus.ERROR

    @pytest.mark.asyncio
    async def test_check_spt_status(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
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
        assert result["approval_date"] == "2024-01-01"
        mock_client.get.assert_awaited_once_with("/api/v1/spt/status/TRK123")

    @pytest.mark.asyncio
    async def test_cancel_spt(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
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
    async def test_get_by_id(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
        mock_repo.get_by_id.return_value = spt
        result = await builder.get_by_id(spt.spt_id)
        assert result is spt

    @pytest.mark.asyncio
    async def test_get_by_npwp_period(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
        mock_repo.get_by_npwp_period.return_value = spt
        result = await builder.get_by_npwp_period("123456789012345", 2024, 1)
        assert result is spt

    @pytest.mark.asyncio
    async def test_get_status(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
        mock_repo.get_by_id.return_value = spt
        result = await builder.get_status(spt.spt_id)
        assert result["status"] == "draft"
        assert result["masa_pajak"] == "2024-01"

    @pytest.mark.asyncio
    async def test_get_history(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
        mock_repo.get_by_id.return_value = spt
        # tambahkan history
        spt._history.append({"event": "test"})
        result = await builder.get_history(spt.spt_id)
        assert result["success"] is True
        assert len(result["history"]) == 1

    @pytest.mark.asyncio
    async def test_snapshot(self, builder: SPTMasaPPH21Builder, mock_repo: AsyncMock, spt: SPTMasaPPH21):
        mock_repo.get_by_id.return_value = spt
        snap = await builder.snapshot(spt.spt_id)
        assert snap["spt_id"] == str(spt.spt_id)


# ============================================================================
# Module-level getter
# ============================================================================
@pytest.mark.asyncio
async def test_get_spt_pph21_builder():
    builder = await get_spt_pph21_builder(config={})
    assert isinstance(builder, SPTMasaPPH21Builder)
    # panggil lagi, harus mengembalikan instance yang sama
    builder2 = await get_spt_pph21_builder()
    assert builder2 is builder