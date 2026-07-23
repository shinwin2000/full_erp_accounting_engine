# tests/adapters/coretax_djp/test_spt_masa_pph_23_builder.py
"""
Comprehensive unit tests for SPT Masa PPh 23 Builder.
Covers all public methods, negative paths, and uses mocks to avoid flakiness.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

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
    SPT23ValidationError,
    SPT23XMLGenerationError,
    SPTMasaPPH23,
    SPTMasaPPH23Builder,
    SPTStatus,
    SPTType,
    _FallbackSPT23Repository,
    get_spt_pph23_builder,
)

# Fixed datetime to avoid flaky tests
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("adapters.coretax_djp.spt_masa_pph_23_builder.datetime") as mock_dt:
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
    SPT23Error,
    SPT23NotFoundError,
    SPT23AlreadyExistsError,
    SPT23InvalidStateError,
    SPT23ValidationError,
    SPT23LockedError,
    SPT23XMLGenerationError,
])
class TestSPT23Exceptions:
    def test_instantiation(self, exc_class):
        e = exc_class("message")
        assert isinstance(e, Exception)
        assert str(e) == "message"


# ============================================================================
# SPTMasaPPH23 entity tests
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
            total_dpp=Decimal("5000.00"),
            total_pph_dipotong=Decimal("100.00"),
            total_bayar=Decimal("100.00"),
            ntpn="1234567890123456",
        )

    def test_construction(self, spt):
        assert spt.npwp_pemotong == "123456789012345"
        assert spt.tahun == 2024
        assert spt.bulan == 1
        assert spt.jenis_pajak == "23"
        assert spt.jenis_pajak_desc == "PPh Pasal 23"
        assert spt.masa_pajak == "2024-01"
        assert spt.total_dpp == Decimal("5000.00")
        assert spt.total_pph_dipotong == Decimal("100.00")
        assert spt.total_bayar == Decimal("100.00")
        assert spt.kompensasi == Decimal(0)
        assert spt.ntpn == "1234567890123456"
        assert spt.status == SPTStatus.DRAFT
        assert spt.version == 1
        assert spt.is_locked is False
        assert spt.is_active is True

    def test_kurang_bayar_lebih_bayar(self, spt):
        # balanced
        assert spt.kurang_bayar == Decimal(0)
        assert spt.lebih_bayar == Decimal(0)

        # underpaid
        spt._total_pph_dipotong = Decimal("150")
        assert spt.kurang_bayar == Decimal("50")
        assert spt.lebih_bayar == Decimal(0)

        # overpaid
        spt._total_bayar = Decimal("200")
        assert spt.kurang_bayar == Decimal(0)
        assert spt.lebih_bayar == Decimal("50")

        # kompensasi affects both
        spt._kompensasi = Decimal("10")
        assert spt.kurang_bayar == Decimal(0)
        assert spt.lebih_bayar == Decimal("60")

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
        assert any(e["event_type"] == "spt_pph23_created" for e in events)
        assert events[-1]["data"]["created_by"] == str(user)

    def test_update(self, spt):
        user = uuid4()
        spt.create(user)
        old_version = spt.version
        data = {
            "total_dpp": "6000",
            "total_pph_dipotong": "120",
            "total_bayar": "120",
            "kompensasi": "5",
            "ntpn": "9876543210987654",
        }
        spt.update(data, user)
        assert spt.total_dpp == Decimal("6000")
        assert spt.total_pph_dipotong == Decimal("120")
        assert spt.total_bayar == Decimal("120")
        assert spt.kompensasi == Decimal("5")
        assert spt.ntpn == "9876543210987654"
        assert spt.version == old_version + 1
        events = spt.get_events()
        assert any(e["event_type"] == "spt_pph23_updated" for e in events)

    def test_update_locked_raises(self, spt):
        spt.lock(uuid4())
        with pytest.raises(SPT23LockedError):
            spt.update({}, uuid4())

    def test_delete_and_restore(self, spt):
        user = uuid4()
        spt.delete(user, permanent=False)
        assert spt.status == SPTStatus.ARCHIVED
        spt.restore(user)
        assert spt.status == SPTStatus.DRAFT
        spt.delete(user, permanent=True)
        assert spt.status == SPTStatus.VOID

    def test_activate_deactivate(self, spt):
        user = uuid4()
        spt.activate(user)
        assert spt.status == SPTStatus.PENDING
        spt.deactivate(user)
        assert spt.status == SPTStatus.DRAFT

    def test_validate_success(self, spt):
        # set valid data
        spt._total_dpp = Decimal("5000")
        spt._total_pph_dipotong = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._jenis_pajak = "23"
        spt._detail_bupot = [{"dpp": "5000", "pph_dipotong": "100"}]
        spt._ntpn = "1234567890123456"  # to avoid NTPN error
        spt.validate(uuid4())
        assert spt.status == SPTStatus.VALIDATED

    def test_validate_negative_dpp(self, spt):
        spt._total_dpp = Decimal("-100")
        with pytest.raises(SPT23ValidationError, match="Total DPP tidak boleh negatif"):
            spt.validate(uuid4())

    def test_validate_invalid_month(self, spt):
        spt._bulan = 13
        with pytest.raises(SPT23ValidationError, match="Bulan pajak tidak valid"):
            spt.validate(uuid4())

    def test_validate_invalid_ntpn(self, spt):
        spt._total_pph_dipotong = Decimal("150")
        spt._total_bayar = Decimal("100")
        spt._ntpn = "invalid"
        with pytest.raises(SPT23ValidationError, match="Format NTPN tidak valid"):
            spt.validate(uuid4())

    def test_submit(self, spt):
        user = uuid4()
        spt._total_dpp = Decimal("5000")
        spt._total_pph_dipotong = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._jenis_pajak = "23"
        spt._detail_bupot = [{"dpp": "5000", "pph_dipotong": "100"}]
        spt._ntpn = "1234567890123456"
        spt.submit(user)
        assert spt.status == SPTStatus.SUBMITTED
        assert spt.submitted_at is not None
        assert spt.xml_content != ""

    def test_cancel_and_void(self, spt):
        user = uuid4()
        spt.cancel(user, "test cancel")
        assert spt.status == SPTStatus.CANCELLED
        assert spt.cancellation_reason == "test cancel"
        spt.void(user, "test void")
        assert spt.status == SPTStatus.VOID

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

    def test_transition(self, spt):
        user = uuid4()
        spt.transition(SPTStatus.PENDING, user)
        assert spt.status == SPTStatus.PENDING
        history = spt.get_history()
        assert len(history) == 1
        assert history[0]["from_status"] == "draft"
        assert history[0]["to_status"] == "pending"

        with pytest.raises(SPT23InvalidStateError):
            spt.transition(SPTStatus.APPROVED, user)

    def test_get_status(self, spt):
        status = spt.get_status()
        assert status["status"] == "draft"
        assert status["is_locked"] is False
        assert status["masa_pajak"] == "2024-01"
        assert status["jenis_pajak"] == "PPh Pasal 23"

    def test_calculate_rates(self, spt):
        # PPh23 with NPWP
        assert spt.calculate_pph23_rate("01", True) == PPh23_RATE_WITH_NPWP
        assert spt.calculate_pph23_rate("01", False) == PPh23_RATE_WITHOUT_NPWP
        assert spt.calculate_pph23_rate("01", True, is_construction=True) == Decimal("0.03")

        # PPh26
        assert spt.calculate_pph26_rate(False, None) == PPh26_RATE_DEFAULT
        assert spt.calculate_pph26_rate(True, None) == Decimal("0.10")
        assert spt.calculate_pph26_rate(False, Decimal("0.15")) == Decimal("0.15")

    def test_collect_bupot_data(self, spt):
        bupots = [
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
        spt.collect_bupot_data(bupots)
        assert spt.bupot_count == 2
        assert spt.total_dpp == Decimal("3000")
        assert spt.total_pph_dipotong == Decimal("60")
        assert spt.total_bayar == Decimal("60")
        assert spt.detail_bupot[0]["bupot_number"] == "B001"
        assert spt.detail_bupot[0]["jenis_penghasilan_text"] == PPh23_OBJECTS["02"]

    def test_set_ntpn(self, spt):
        spt.set_ntpn("1234567890123456")
        assert spt.ntpn == "1234567890123456"
        with pytest.raises(SPT23ValidationError):
            spt.set_ntpn("invalid")

    def test_set_kompensasi(self, spt):
        spt.set_kompensasi(Decimal("50.00"))
        assert spt.kompensasi == Decimal("50.00")

    def test_to_dict_from_dict(self, spt):
        d = spt.to_dict()
        assert d["npwp_pemotong"] == "123456789012345"
        assert d["tahun"] == 2024
        new_spt = SPTMasaPPH23.from_dict(d)
        assert new_spt.npwp_pemotong == spt.npwp_pemotong
        assert new_spt.tahun == spt.tahun
        assert new_spt.bulan == spt.bulan

    def test_snapshot(self, spt):
        snap = spt.snapshot()
        assert snap["spt_id"] == str(spt.spt_id)
        assert "total_dpp" in snap

    def test_audit_trail_and_events(self, spt):
        user = uuid4()
        spt.create(user)
        spt.transition(SPTStatus.PENDING, user)
        assert len(spt.get_events()) == 2
        assert len(spt.get_history()) == 1
        assert spt.audit_trail() == spt.get_history()


# ============================================================================
# Fallback repository tests
# ============================================================================
class TestFallbackSPT23Repository:
    @pytest.fixture
    def repo(self):
        return _FallbackSPT23Repository()

    @pytest.fixture
    def spt(self):
        return SPTMasaPPH23(
            npwp_pemotong="123456789012345",
            tahun=2024,
            bulan=1,
            jenis_pajak="23",
            total_dpp=Decimal("5000"),
            total_pph_dipotong=Decimal("100"),
            total_bayar=Decimal("100"),
            ntpn="1234567890123456",
        )

    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self, repo, spt):
        await repo.add(spt)
        found = await repo.get_by_id(spt.spt_id)
        assert found is spt

    @pytest.mark.asyncio
    async def test_save_and_update(self, repo, spt):
        await repo.add(spt)
        spt._total_pph_dipotong = Decimal("200")
        await repo.save(spt)
        updated = await repo.get_by_id(spt.spt_id)
        assert updated.total_pph_dipotong == Decimal("200")

        spt._total_pph_dipotong = Decimal("300")
        await repo.update(spt)
        updated2 = await repo.get_by_id(spt.spt_id)
        assert updated2.total_pph_dipotong == Decimal("300")

    @pytest.mark.asyncio
    async def test_delete(self, repo, spt):
        await repo.add(spt)
        await repo.delete(spt.spt_id)
        assert await repo.get_by_id(spt.spt_id) is None

    @pytest.mark.asyncio
    async def test_get_by_npwp_period(self, repo, spt):
        await repo.add(spt)
        found = await repo.get_by_npwp_period("123456789012345", 2024, 1, "23")
        assert found is spt
        not_found = await repo.get_by_npwp_period("999", 2024, 1, "23")
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
        assert await repo.exists("123456789012345", 2024, 1, "23") is True
        assert await repo.exists("999", 2024, 1, "23") is False


# ============================================================================
# Builder tests
# ============================================================================
class TestSPTMasaPPH23Builder:
    @pytest.fixture
    def mock_repo(self):
        return AsyncMock(spec=_FallbackSPT23Repository)

    @pytest.fixture
    def builder(self, mock_repo):
        b = SPTMasaPPH23Builder(config={})
        b._repository = mock_repo
        return b

    @pytest.fixture
    def spt(self):
        return SPTMasaPPH23(
            npwp_pemotong="123456789012345",
            tahun=2024,
            bulan=1,
            jenis_pajak="23",
            total_dpp=Decimal("5000"),
            total_pph_dipotong=Decimal("100"),
            total_bayar=Decimal("100"),
            ntpn="1234567890123456",
        )

    @pytest.mark.asyncio
    async def test_create_new(self, builder, mock_repo):
        mock_repo.get_by_npwp_period.return_value = None
        mock_repo.add.return_value = None
        result = await builder.create("123456789012345", 2024, 1, "23", uuid4())
        assert result["success"] is True
        assert "spt_id" in result
        assert result["status"] == "draft"
        mock_repo.add.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_already_exists(self, builder, mock_repo, spt):
        mock_repo.get_by_npwp_period.return_value = spt
        result = await builder.create("123456789012345", 2024, 1, "23", uuid4())
        assert result["success"] is False
        assert "already exists" in result["error"]
        mock_repo.add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_collect_data(self, builder):
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
        assert data["total_dpp"] == Decimal("3000")
        assert data["total_pph_dipotong"] == Decimal("60")
        assert data["total_bayar"] == Decimal("60")
        assert data["kompensasi"] == Decimal("10")
        assert data["ntpn"] == "1234567890123456"
        assert data["bupot_count"] == 2

    @pytest.mark.asyncio
    async def test_collect_data_error(self, builder):
        mock_tax = AsyncMock()
        mock_tax.get_bupot_list.side_effect = Exception("Service error")
        with patch.object(builder, "_get_tax_service", return_value=mock_tax):
            data = await builder.collect_data("123", 2024, 1, "23")
        assert "error" in data
        assert data["total_dpp"] == Decimal(0)

    @pytest.mark.asyncio
    async def test_build_creates_new(self, builder, mock_repo):
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
            "kompensasi": Decimal(0),
            "ntpn": None,
            "detail_bupot": [],
            "bupot_count": 0,
        }):
            result = await builder.build("123", 2024, 1, "23", uuid4())
        assert result["success"] is True
        assert "spt_id" in result

    @pytest.mark.asyncio
    async def test_build_updates_existing(self, builder, mock_repo, spt):
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
        assert spt.ntpn == "9876543210987654"
        mock_repo.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_validate_spt_ok(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        mock_repo.update.return_value = None
        spt._total_dpp = Decimal("5000")
        spt._total_pph_dipotong = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._jenis_pajak = "23"
        spt._detail_bupot = [{"dpp": "5000", "pph_dipotong": "100"}]
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
    async def test_validate_spt_fails(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        spt._total_dpp = Decimal("-100")
        result = await builder.validate_spt(spt.spt_id, uuid4())
        assert result["success"] is False
        assert "Validasi gagal" in result["error"]
        mock_repo.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_submit_spt_success(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        mock_repo.update.return_value = None
        spt._total_dpp = Decimal("5000")
        spt._total_pph_dipotong = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._jenis_pajak = "23"
        spt._detail_bupot = [{"dpp": "5000", "pph_dipotong": "100"}]
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
        assert result["tracking_id"] == "TRK123"
        assert result["status"] == SPTStatus.SUBMITTED.value
        mock_client.post.assert_awaited_once_with(
            CORETAX_SPT_PPH23_ENDPOINT,
            {
                "spt_xml": spt._generate_xml(),
                "npwp": spt.npwp_pemotong,
                "tahun": spt.tahun,
                "bulan": spt.bulan,
                "spt_type": SPTType.NORMAL.value,
                "correction_number": 0,
                "tax_type": spt.jenis_pajak,
            }
        )

    @pytest.mark.asyncio
    async def test_submit_spt_auth_error(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        spt._total_dpp = Decimal("5000")
        spt._total_pph_dipotong = Decimal("100")
        spt._total_bayar = Decimal("100")
        spt._bulan = 5
        spt._tahun = 2024
        spt._jenis_pajak = "23"
        spt._detail_bupot = [{"dpp": "5000", "pph_dipotong": "100"}]
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
    async def test_cancel_spt(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        mock_repo.update.return_value = None
        spt._tracking_id = "TRK123"
        mock_client = AsyncMock()
        mock_client.post.return_value = {"status": "cancelled"}
        with patch.object(builder, "_get_coretax_client", return_value=mock_client):
            result = await builder.cancel_spt(spt.spt_id, uuid4(), "test")
        assert result["success"] is True
        assert result["cancelled"] is True
        assert spt.status == SPTStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_submit_bupot(self, builder):
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

    @pytest.mark.asyncio
    async def test_submit_bupot_batch(self, builder):
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
    async def test_get_by_id(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        result = await builder.get_by_id(spt.spt_id)
        assert result is spt

    @pytest.mark.asyncio
    async def test_get_by_npwp_period(self, builder, mock_repo, spt):
        mock_repo.get_by_npwp_period.return_value = spt
        result = await builder.get_by_npwp_period("123456789012345", 2024, 1, "23")
        assert result is spt

    @pytest.mark.asyncio
    async def test_get_status(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        result = await builder.get_status(spt.spt_id)
        assert result["status"] == "draft"

    @pytest.mark.asyncio
    async def test_get_history(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        spt._history.append({"event": "test"})
        result = await builder.get_history(spt.spt_id)
        assert result["success"] is True
        assert len(result["history"]) == 1

    @pytest.mark.asyncio
    async def test_snapshot(self, builder, mock_repo, spt):
        mock_repo.get_by_id.return_value = spt
        snap = await builder.snapshot(spt.spt_id)
        assert snap["spt_id"] == str(spt.spt_id)


# ============================================================================
# Module-level getter
# ============================================================================
@pytest.mark.asyncio
async def test_get_spt_pph23_builder():
    builder1 = await get_spt_pph23_builder(config={"test": True})
    builder2 = await get_spt_pph23_builder()
    assert builder1 is builder2
    assert isinstance(builder1, SPTMasaPPH23Builder)