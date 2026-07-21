# tests/adapters/coretax_djp/test_spt_masa_pph_23_builder.py
# Perbaikan kualitas assertions:
# - Semua async test diberi @pytest.mark.asyncio
# - Dead test di TestSPT23RepositoryPort di-skip dengan alasan jelas
# - Duplikasi exception test diganti dengan parametrize
# - Flaky tests menggunakan mock datetime
# - Assertion diperkuat, tidak ada assert True kosong

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from uuid import UUID, uuid4

from adapters.coretax_djp.spt_masa_pph_23_builder import (
    CORETAX_SPT_PPH23_ENDPOINT,
    PPh23_OBJECTS,
    PPh23_RATE_WITHOUT_NPWP,
    PPh23_RATE_WITH_NPWP,
    PPh26_RATE_DEFAULT,
    SPT23AlreadyExistsError,
    SPT23Error,
    SPT23InvalidStateError,
    SPT23LockedError,
    SPT23NotFoundError,
    SPT23RepositoryPort,
    SPT23ValidationError,
    SPT23XMLGenerationError,
    SPTMasaPPH23,
    SPTMasaPPH23Builder,
    SPTStatus,
    SPTType,
    _FallbackSPT23Repository,
    get_spt_pph23_builder,
)

# ============================================================================
# FIXED DATETIME - untuk menghindari flaky tests
# ============================================================================
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now() untuk menghindari flaky tests."""
    with patch("adapters.coretax_djp.spt_masa_pph_23_builder.datetime") as mock_dt:
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
    SPT23Error,
    SPT23NotFoundError,
    SPT23AlreadyExistsError,
    SPT23InvalidStateError,
    SPT23ValidationError,
    SPT23LockedError,
    SPT23XMLGenerationError,
])
class TestSPT23Exceptions:
    def test_construction(self, exception_class):
        instance = exception_class()
        assert isinstance(instance, exception_class)
        assert isinstance(instance, Exception)


# ============================================================================
# Entity: SPTMasaPPH23
# ============================================================================
class TestSPTMasaPPH23:
    @pytest.fixture
    def spt(self) -> SPTMasaPPH23:
        return SPTMasaPPH23(
            npwp_pemotong="123456789012345",
            tahun=2024,
            bulan=1,
            jenis_pajak="23",
            spt_type=SPTType.NORMAL,
            correction_number=0,
            total_dpp=Decimal("5000.00"),
            total_pph_dipotong=Decimal("100.00"),
            total_bayar=Decimal("100.00"),
            kompensasi=Decimal("0"),
            ntpn="1234567890123456",
            spt_id=uuid4(),
            status=SPTStatus.DRAFT,
            version=1,
        )

    def test_construction(self, spt: SPTMasaPPH23):
        assert isinstance(spt, SPTMasaPPH23)
        assert spt.npwp_pemotong == "123456789012345"
        assert spt.tahun == 2024
        assert spt.bulan == 1
        assert spt.jenis_pajak == "23"
        assert spt.jenis_pajak_desc == "PPh Pasal 23"
        assert spt.spt_type == SPTType.NORMAL
        assert spt.correction_number == 0
        assert spt.total_dpp == Decimal("5000.00")
        assert spt.total_pph_dipotong == Decimal("100.00")
        assert spt.total_bayar == Decimal("100.00")
        assert spt.kompensasi == Decimal("0")
        assert spt.ntpn == "1234567890123456"
        assert spt.status == SPTStatus.DRAFT
        assert spt.version == 1

    def test_masa_pajak(self, spt: SPTMasaPPH23):
        assert spt.masa_pajak == "2024-01"

    def test_kurang_bayar(self, spt: SPTMasaPPH23):
        # total_pph_dipotong == total_bayar => kurang bayar 0
        assert spt.kurang_bayar == Decimal(0)

        spt._total_pph_dipotong = Decimal("150.00")
        assert spt.kurang_bayar == Decimal("50.00")

        # kompensasi mengurangi kurang bayar
        spt._kompensasi = Decimal("20.00")
        assert spt.kurang_bayar == Decimal("30.00")

    def test_lebih_bayar(self, spt: SPTMasaPPH23):
        assert spt.lebih_bayar == Decimal(0)
        spt._total_bayar = Decimal("200.00")
        spt._total_pph_dipotong = Decimal("100.00")
        assert spt.lebih_bayar == Decimal("100.00")

        # kompensasi menambah lebih bayar
        spt._kompensasi = Decimal("50.00")
        assert spt.lebih_bayar == Decimal("150.00")

    def test_ntpn_masked(self, spt: SPTMasaPPH23):
        assert spt.ntpn_masked == "12345678...3456"
        spt._ntpn = None
        assert spt.ntpn_masked is None
        spt._ntpn = "123"
        assert spt.ntpn_masked == "123"

    def test_properties_is_locked_and_is_active(self, spt: SPTMasaPPH23):
        assert not spt.is_locked
        assert spt.is_active

        spt._locked_at = FIXED_NOW
        assert spt.is_locked

        spt._status = SPTStatus.CANCELLED
        assert not spt.is_active

    def test_create_method(self, spt: SPTMasaPPH23):
        user_id = uuid4()
        result = spt.create(created_by=user_id)
        assert result is spt
        assert spt.status == SPTStatus.DRAFT
        assert spt.version == 2
        events = spt.get_events()
        assert any(e["event_type"] == "spt_pph23_created" for e in events)
        assert events[-1]["data"]["created_by"] == str(user_id)

    def test_update_method(self, spt: SPTMasaPPH23):
        user_id = uuid4()
        spt.create(user_id)  # set status draft
        old_version = spt.version
        data = {
            "total_dpp": "6000.00",
            "total_pph_dipotong": "120.00",
            "total_bayar": "120.00",
            "kompensasi": "10.00",
            "ntpn": "9876543210987654",
        }
        spt.update(data, user_id)
        assert spt.total_dpp == Decimal("6000.00")
        assert spt.total_pph_dipotong == Decimal("120.00")
        assert spt.total_bayar == Decimal("120.00")
        assert spt.kompensasi == Decimal("10.00")
        assert spt.ntpn == "9876543210987654"
        assert spt.version == old_version + 1
        events = spt.get_events()
        assert any(e["event_type"] == "spt_pph23_updated" for e in events)

    def test_update_locked_raises(self, spt: SPTMasaPPH23):
        spt._locked_at = FIXED_NOW
        with pytest.raises(SPT23LockedError):
            spt.update({}, uuid4())

    def test_delete_method(self, spt: SPTMasaPPH23):
        user_id = uuid4()
        spt.delete(user_id, permanent=False)
        assert spt.status == SPTStatus.ARCHIVED
        assert spt.cancelled_at is not None
        events = spt.get_events()
        assert any(e["event_type"] == "spt_pph23_deleted" for e in events)

        spt.restore(user_id)
        assert spt.status == SPTStatus.DRAFT
        assert spt.cancelled_at is None

        spt.delete(user_id, permanent=True)
        assert spt.status == SPTStatus.VOID

    def test_activate_deactivate(self, spt: SPTMasaPPH23):
        user = uuid4()
        spt.activate(user)
        assert spt.status == SPTStatus.PENDING
        spt.deactivate(user)
        assert spt.status == SPTStatus.DRAFT

    def test_validate_method_ok(self, spt: SPTMasaPPH23):
        user = uuid4()
        # set kondisi valid
        spt._total_dpp = Decimal("5000")
        spt._total_pph_dipotong = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._ntpn = None
        spt._bulan = 5
        spt._tahun = 2024
        spt._jenis_pajak = "23"
        # tambahkan bupot agar konsisten
        spt._detail_bupot = [
            {"dpp": "5000", "pph_dipotong": "100"}
        ]
        spt.validate(user)
        assert spt.status == SPTStatus.VALIDATED

    def test_validate_invalid_negative(self, spt: SPTMasaPPH23):
        spt._total_dpp = Decimal("-100")
        with pytest.raises(SPT23ValidationError, match="Total DPP tidak boleh negatif"):
            spt.validate(uuid4())

    def test_submit_method(self, spt: SPTMasaPPH23):
        user = uuid4()
        spt._total_dpp = Decimal("5000")
        spt._total_pph_dipotong = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._jenis_pajak = "23"
        spt._detail_bupot = [{"dpp": "5000", "pph_dipotong": "100"}]
        spt.submit(user)
        assert spt.status == SPTStatus.SUBMITTED
        assert spt.submitted_at is not None
        assert spt.xml_content != ""

    def test_cancel_and_void(self, spt: SPTMasaPPH23):
        user = uuid4()
        spt.cancel(user, "reason")
        assert spt.status == SPTStatus.CANCELLED
        assert spt.cancellation_reason == "reason"

        spt.void(user, "void reason")
        assert spt.status == SPTStatus.VOID

    def test_lock_unlock(self, spt: SPTMasaPPH23):
        user = uuid4()
        spt.lock(user)
        assert spt.is_locked
        assert spt.locked_by == user
        assert spt.status == SPTStatus.LOCKED

        spt.unlock(user)
        assert not spt.is_locked
        assert spt.locked_by is None
        assert spt.status == SPTStatus.PENDING

    def test_transition(self, spt: SPTMasaPPH23):
        user = uuid4()
        spt.transition(SPTStatus.PENDING, user)
        assert spt.status == SPTStatus.PENDING
        history = spt.get_history()
        assert len(history) == 1
        assert history[0]["from_status"] == "draft"
        assert history[0]["to_status"] == "pending"

        with pytest.raises(SPT23InvalidStateError):
            spt.transition(SPTStatus.APPROVED, user)

    def test_get_status(self, spt: SPTMasaPPH23):
        status = spt.get_status()
        assert status["status"] == "draft"
        assert status["is_locked"] is False
        assert status["is_active"] is True
        assert status["masa_pajak"] == "2024-01"
        assert status["jenis_pajak"] == "PPh Pasal 23"

    def test_calculate_pph23_rate(self, spt: SPTMasaPPH23):
        # with NPWP
        assert spt.calculate_pph23_rate("01", True) == PPh23_RATE_WITH_NPWP
        assert spt.calculate_pph23_rate("01", False) == PPh23_RATE_WITHOUT_NPWP
        # konstruksi
        assert spt.calculate_pph23_rate("01", True, is_construction=True) == Decimal("0.03")

    def test_calculate_pph26_rate(self, spt: SPTMasaPPH23):
        assert spt.calculate_pph26_rate(False, None) == PPh26_RATE_DEFAULT
        assert spt.calculate_pph26_rate(True, None) == Decimal("0.10")
        assert spt.calculate_pph26_rate(False, Decimal("0.15")) == Decimal("0.15")

    def test_collect_bupot_data(self, spt: SPTMasaPPH23):
        bupot_list = [
            {
                "bupot_id": "b1",
                "bupot_number": "B001",
                "npwp_penerima": "111",
                "nama_penerima": "A",
                "object_type": "02",
                "dpp": "1000",
                "rate": 0.02,
                "pph_dipotong": "20",
                "withholding_date": date(2024, 1, 15),
                "invoice_number": "INV001",
            },
            {
                "bupot_id": "b2",
                "bupot_number": "B002",
                "npwp_penerima": "222",
                "nama_penerima": "B",
                "object_type": "03",
                "dpp": "2000",
                "rate": 0.02,
                "pph_dipotong": "40",
                "withholding_date": date(2024, 1, 20),
                "invoice_number": "INV002",
            },
        ]
        spt.collect_bupot_data(bupot_list)
        assert spt.bupot_count == 2
        assert spt.total_dpp == Decimal("3000")
        assert spt.total_pph_dipotong == Decimal("60")
        assert spt.total_bayar == Decimal("60")
        assert len(spt.detail_bupot) == 2
        assert spt.detail_bupot[0]["bupot_number"] == "B001"
        assert spt.detail_bupot[0]["jenis_penghasilan_text"] == PPh23_OBJECTS["02"]

    def test_set_ntpn(self, spt: SPTMasaPPH23):
        spt.set_ntpn("1234567890123456")
        assert spt.ntpn == "1234567890123456"

        with pytest.raises(SPT23ValidationError):
            spt.set_ntpn("invalid")

    def test_set_kompensasi(self, spt: SPTMasaPPH23):
        spt.set_kompensasi(Decimal("50.00"))
        assert spt.kompensasi == Decimal("50.00")

    def test_to_dict_and_from_dict(self, spt: SPTMasaPPH23):
        d = spt.to_dict()
        assert d["npwp_pemotong"] == "123456789012345"
        assert d["tahun"] == 2024
        assert "spt_id" in d

        new_spt = SPTMasaPPH23.from_dict(d)
        assert new_spt.npwp_pemotong == spt.npwp_pemotong
        assert new_spt.tahun == spt.tahun
        assert new_spt.bulan == spt.bulan
        assert new_spt.jenis_pajak == spt.jenis_pajak

    def test_snapshot(self, spt: SPTMasaPPH23):
        snap = spt.snapshot()
        assert snap["spt_id"] == str(spt.spt_id)
        assert "total_dpp" in snap

    def test_audit_trail_and_events(self, spt: SPTMasaPPH23):
        user = uuid4()
        spt.create(user)
        events = spt.get_events()
        assert len(events) > 0
        assert spt.audit_trail() == spt.get_history()  # history initially empty
        spt.transition(SPTStatus.PENDING, user)
        assert len(spt.get_history()) == 1


# ============================================================================
# Repository interface (abstract) - di-skip karena tidak ada implementasi
# ============================================================================
class TestSPT23RepositoryPort:
    @pytest.mark.skip(reason="SPT23RepositoryPort is an abstract interface, not meant to be instantiated.")
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
class Test_FallbackSPT23Repository:
    @pytest.fixture
    def repo(self) -> _FallbackSPT23Repository:
        return _FallbackSPT23Repository()

    @pytest.fixture
    def spt(self) -> SPTMasaPPH23:
        return SPTMasaPPH23(
            npwp_pemotong="123456789012345",
            tahun=2024,
            bulan=1,
            jenis_pajak="23",
            spt_type=SPTType.NORMAL,
            correction_number=0,
            total_dpp=Decimal("5000.00"),
            total_pph_dipotong=Decimal("100.00"),
            total_bayar=Decimal("100.00"),
            kompensasi=Decimal("0"),
            ntpn="1234567890123456",
            spt_id=uuid4(),
            status=SPTStatus.DRAFT,
            version=1,
        )

    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self, repo: _FallbackSPT23Repository, spt: SPTMasaPPH23):
        await repo.add(spt)
        stored = await repo.get_by_id(spt.spt_id)
        assert stored is spt
        assert stored.npwp_pemotong == spt.npwp_pemotong

    @pytest.mark.asyncio
    async def test_save(self, repo: _FallbackSPT23Repository, spt: SPTMasaPPH23):
        await repo.add(spt)
        spt._total_pph_dipotong = Decimal("200")
        await repo.save(spt)
        stored = await repo.get_by_id(spt.spt_id)
        assert stored.total_pph_dipotong == Decimal("200")

    @pytest.mark.asyncio
    async def test_update(self, repo: _FallbackSPT23Repository, spt: SPTMasaPPH23):
        await repo.add(spt)
        spt._total_pph_dipotong = Decimal("300")
        await repo.update(spt)
        stored = await repo.get_by_id(spt.spt_id)
        assert stored.total_pph_dipotong == Decimal("300")

    @pytest.mark.asyncio
    async def test_delete(self, repo: _FallbackSPT23Repository, spt: SPTMasaPPH23):
        await repo.add(spt)
        await repo.delete(spt.spt_id)
        stored = await repo.get_by_id(spt.spt_id)
        assert stored is None

    @pytest.mark.asyncio
    async def test_get_by_npwp_period(self, repo: _FallbackSPT23Repository, spt: SPTMasaPPH23):
        await repo.add(spt)
        found = await repo.get_by_npwp_period("123456789012345", 2024, 1, "23")
        assert found is spt
        not_found = await repo.get_by_npwp_period("999", 2024, 1, "23")
        assert not_found is None

    @pytest.mark.asyncio
    async def test_get_by_tracking_id(self, repo: _FallbackSPT23Repository, spt: SPTMasaPPH23):
        spt._tracking_id = "TRK123"
        await repo.add(spt)
        found = await repo.get_by_tracking_id("TRK123")
        assert found is spt
        assert await repo.get_by_tracking_id("missing") is None

    @pytest.mark.asyncio
    async def test_get_by_status(self, repo: _FallbackSPT23Repository, spt: SPTMasaPPH23):
        await repo.add(spt)
        drafts = await repo.get_by_status(SPTStatus.DRAFT)
        assert drafts == [spt]
        pendings = await repo.get_by_status(SPTStatus.PENDING)
        assert pendings == []

    @pytest.mark.asyncio
    async def test_get_pending_submissions(self, repo: _FallbackSPT23Repository, spt: SPTMasaPPH23):
        await repo.add(spt)
        pending = await repo.get_pending_submissions()
        assert spt in pending

    @pytest.mark.asyncio
    async def test_exists(self, repo: _FallbackSPT23Repository, spt: SPTMasaPPH23):
        await repo.add(spt)
        assert await repo.exists("123456789012345", 2024, 1, "23") is True
        assert await repo.exists("999", 2024, 1, "23") is False


# ============================================================================
# Builder
# ============================================================================
class TestSPTMasaPPH23Builder:
    @pytest.fixture
    def mock_repo(self) -> AsyncMock:
        return AsyncMock(spec=SPT23RepositoryPort)

    @pytest.fixture
    def builder(self, mock_repo: AsyncMock) -> SPTMasaPPH23Builder:
        b = SPTMasaPPH23Builder(config={})
        b._repository = mock_repo  # inject mock
        return b

    @pytest.fixture
    def spt(self) -> SPTMasaPPH23:
        return SPTMasaPPH23(
            npwp_pemotong="123456789012345",
            tahun=2024,
            bulan=1,
            jenis_pajak="23",
            spt_type=SPTType.NORMAL,
            correction_number=0,
            total_dpp=Decimal("5000.00"),
            total_pph_dipotong=Decimal("100.00"),
            total_bayar=Decimal("100.00"),
            kompensasi=Decimal("0"),
            ntpn="1234567890123456",
            spt_id=uuid4(),
            status=SPTStatus.DRAFT,
            version=1,
        )

    @pytest.mark.asyncio
    async def test_create_new(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock):
        mock_repo.get_by_npwp_period.return_value = None
        mock_repo.add.return_value = None

        result = await builder.create("123456789012345", 2024, 1, "23", uuid4())
        assert result["success"] is True
        assert "spt_id" in result
        assert result["status"] == "draft"
        assert result["jenis_pajak"] == "PPh Pasal 23"
        mock_repo.add.assert_awaited_once()
        mock_repo.get_by_npwp_period.assert_awaited_once_with("123456789012345", 2024, 1, "23")

    @pytest.mark.asyncio
    async def test_create_already_exists(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
        mock_repo.get_by_npwp_period.return_value = spt
        result = await builder.create("123456789012345", 2024, 1, "23", uuid4())
        assert result["success"] is False
        assert "already exists" in result["error"]
        mock_repo.add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_collect_data(self, builder: SPTMasaPPH23Builder):
        # Mock tax_service
        mock_tax = AsyncMock()
        mock_tax.get_bupot_list.return_value = [
            {
                "id": "b1",
                "bupot_number": "B001",
                "npwp_penerima": "111",
                "nama_penerima": "A",
                "object_type": "02",
                "dpp": "1000",
                "rate": 0.02,
                "pph_amount": "20",
                "withholding_date": date(2024, 1, 15),
                "invoice_number": "INV001",
            },
            {
                "id": "b2",
                "bupot_number": "B002",
                "npwp_penerima": "222",
                "nama_penerima": "B",
                "object_type": "03",
                "dpp": "2000",
                "rate": 0.02,
                "pph_amount": "40",
                "withholding_date": date(2024, 1, 20),
                "invoice_number": "INV002",
            },
        ]
        mock_tax.get_kompensasi_pph23.return_value = Decimal("10")
        mock_tax.get_ntpn_for_period.return_value = {"ntpn": "1234567890123456"}

        with patch.object(builder, "_get_tax_service", return_value=mock_tax):
            data = await builder.collect_data("123456789012345", 2024, 1, "23")

        assert data["npwp_pemotong"] == "123456789012345"
        assert data["tahun"] == 2024
        assert data["bulan"] == 1
        assert data["jenis_pajak"] == "23"
        assert data["total_dpp"] == Decimal("3000")
        assert data["total_pph_dipotong"] == Decimal("60")
        assert data["total_bayar"] == Decimal("60")
        assert data["kompensasi"] == Decimal("10")
        assert data["ntpn"] == "1234567890123456"
        assert data["bupot_count"] == 2
        assert len(data["detail_bupot"]) == 2

    @pytest.mark.asyncio
    async def test_build_creates_new(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock):
        mock_repo.get_by_npwp_period.return_value = None
        mock_repo.add.return_value = None

        with patch.object(builder, "collect_data", return_value={
            "npwp_pemotong": "123",
            "tahun": 2024,
            "bulan": 1,
            "jenis_pajak": "23",
            "total_dpp": Decimal("1000"),
            "total_pph_dipotong": Decimal("20"),
            "total_bayar": Decimal("20"),
            "kompensasi": Decimal("0"),
            "ntpn": None,
            "detail_bupot": [],
            "bupot_count": 0,
        }):
            result = await builder.build("123", 2024, 1, "23", uuid4())
        assert result["success"] is True
        assert "spt_id" in result

    @pytest.mark.asyncio
    async def test_build_updates_existing(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
        mock_repo.get_by_npwp_period.return_value = spt
        mock_repo.update.return_value = None

        with patch.object(builder, "collect_data", return_value={
            "npwp_pemotong": "123456789012345",
            "tahun": 2024,
            "bulan": 1,
            "jenis_pajak": "23",
            "total_dpp": Decimal("6000"),
            "total_pph_dipotong": Decimal("120"),
            "total_bayar": Decimal("120"),
            "kompensasi": Decimal("5"),
            "ntpn": "9876543210987654",
            "detail_bupot": [{"dpp": "6000", "pph_dipotong": "120"}],
            "bupot_count": 1,
        }):
            result = await builder.build("123456789012345", 2024, 1, "23", uuid4())
        assert result["success"] is True
        assert spt.total_dpp == Decimal("6000")
        assert spt.total_pph_dipotong == Decimal("120")
        assert spt.total_bayar == Decimal("120")
        assert spt.kompensasi == Decimal("5")
        assert spt.ntpn == "9876543210987654"
        assert len(spt.detail_bupot) == 1
        mock_repo.update.assert_awaited_once_with(spt)

    @pytest.mark.asyncio
    async def test_validate_spt_ok(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
        mock_repo.get_by_id.return_value = spt
        mock_repo.update.return_value = None
        # set valid
        spt._total_dpp = Decimal("5000")
        spt._total_pph_dipotong = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._jenis_pajak = "23"
        spt._detail_bupot = [{"dpp": "5000", "pph_dipotong": "100"}]

        result = await builder.validate_spt(spt.spt_id, uuid4())
        assert result["success"] is True
        assert result["valid"] is True
        assert result["status"] == SPTStatus.VALIDATED.value
        mock_repo.update.assert_awaited_once_with(spt)

    @pytest.mark.asyncio
    async def test_validate_spt_not_found(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock):
        mock_repo.get_by_id.return_value = None
        result = await builder.validate_spt(uuid4(), uuid4())
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_spt_validation_fails(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
        mock_repo.get_by_id.return_value = spt
        # buat invalid
        spt._total_dpp = Decimal("-100")
        result = await builder.validate_spt(spt.spt_id, uuid4())
        assert result["success"] is False
        assert "Validasi gagal" in result["error"]
        mock_repo.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_submit_spt(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
        mock_repo.get_by_id.return_value = spt
        mock_repo.update.return_value = None
        # set data valid
        spt._total_dpp = Decimal("5000")
        spt._total_pph_dipotong = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._jenis_pajak = "23"
        spt._detail_bupot = [{"dpp": "5000", "pph_dipotong": "100"}]

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
        assert result["tracking_id"] == "TRK123"
        assert result["status"] == SPTStatus.SUBMITTED.value

        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == CORETAX_SPT_PPH23_ENDPOINT
        assert "spt_xml" in call_args[0][1]
        assert call_args[0][1]["spt_xml"] is not None
        assert call_args[0][1]["npwp"] == "123456789012345"
        assert call_args[0][1]["tahun"] == 2024
        assert call_args[0][1]["bulan"] == 5

    @pytest.mark.asyncio
    async def test_submit_spt_auth_failure(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
        mock_repo.get_by_id.return_value = spt
        spt._total_dpp = Decimal("5000")
        spt._total_pph_dipotong = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._jenis_pajak = "23"
        spt._detail_bupot = [{"dpp": "5000", "pph_dipotong": "100"}]

        mock_client = AsyncMock()
        from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError
        mock_client.post.side_effect = CoretaxAuthError("auth failed")

        with patch.object(builder, "_get_coretax_client", return_value=mock_client):
            result = await builder.submit_spt(spt.spt_id, uuid4())
        assert result["success"] is False
        assert "Coretax authentication failed" in result["error"]
        assert spt.status == SPTStatus.ERROR

    @pytest.mark.asyncio
    async def test_check_spt_status(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
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
    async def test_cancel_spt(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
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
    async def test_submit_bupot(self, builder: SPTMasaPPH23Builder):
        mock_client = AsyncMock()
        mock_client.post.return_value = {"bupot_id": "b1", "bupot_number": "B001", "status": "success"}

        bupot_data = {
            "npwp_pemotong": "123",
            "npwp_penerima": "111",
            "nama_penerima": "A",
            "object_type": "02",
            "dpp": Decimal("1000"),
            "rate": 0.02,
            "pph_amount": Decimal("20"),
            "withholding_date": date(2024, 1, 15),
            "bulan": 1,
            "tahun": 2024,
            "invoice_number": "INV001",
        }

        with patch.object(builder, "_get_coretax_client", return_value=mock_client):
            result = await builder.submit_bupot(bupot_data)
        assert result["success"] is True
        assert result["bupot_id"] == "b1"
        assert result["bupot_number"] == "B001"

    @pytest.mark.asyncio
    async def test_submit_bupot_batch(self, builder: SPTMasaPPH23Builder):
        mock_client = AsyncMock()
        mock_client.post.return_value = {"submitted_count": 2, "failed_count": 0, "results": []}

        bupot_list = [
            {"npwp_pemotong": "123", "npwp_penerima": "111", "nama_penerima": "A", "object_type": "02",
             "dpp": "1000", "rate": 0.02, "pph_amount": "20", "withholding_date": date(2024, 1, 15),
             "bulan": 1, "tahun": 2024},
            {"npwp_pemotong": "123", "npwp_penerima": "222", "nama_penerima": "B", "object_type": "03",
             "dpp": "2000", "rate": 0.02, "pph_amount": "40", "withholding_date": date(2024, 1, 20),
             "bulan": 1, "tahun": 2024},
        ]

        with patch.object(builder, "_get_coretax_client", return_value=mock_client):
            result = await builder.submit_bupot_batch(bupot_list)
        assert result["success"] is True
        assert result["submitted_count"] == 2

    @pytest.mark.asyncio
    async def test_get_by_id(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
        mock_repo.get_by_id.return_value = spt
        result = await builder.get_by_id(spt.spt_id)
        assert result is spt

    @pytest.mark.asyncio
    async def test_get_by_npwp_period(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
        mock_repo.get_by_npwp_period.return_value = spt
        result = await builder.get_by_npwp_period("123456789012345", 2024, 1, "23")
        assert result is spt

    @pytest.mark.asyncio
    async def test_get_status(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
        mock_repo.get_by_id.return_value = spt
        result = await builder.get_status(spt.spt_id)
        assert result["status"] == "draft"
        assert result["masa_pajak"] == "2024-01"

    @pytest.mark.asyncio
    async def test_get_history(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
        mock_repo.get_by_id.return_value = spt
        spt._history.append({"event": "test"})
        result = await builder.get_history(spt.spt_id)
        assert result["success"] is True
        assert len(result["history"]) == 1

    @pytest.mark.asyncio
    async def test_snapshot(self, builder: SPTMasaPPH23Builder, mock_repo: AsyncMock, spt: SPTMasaPPH23):
        mock_repo.get_by_id.return_value = spt
        snap = await builder.snapshot(spt.spt_id)
        assert snap["spt_id"] == str(spt.spt_id)


# ============================================================================
# Module-level getter
# ============================================================================
@pytest.mark.asyncio
async def test_get_spt_pph23_builder():
    builder = await get_spt_pph23_builder(config={})
    assert isinstance(builder, SPTMasaPPH23Builder)
    # panggil lagi, harus mengembalikan instance yang sama
    builder2 = await get_spt_pph23_builder()
    assert builder2 is builder