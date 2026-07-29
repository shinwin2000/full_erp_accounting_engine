# test_value_objects.py
# ======================
# Comprehensive tests for domain/tax_transaction/value_objects.py.
# Covers all value objects: NPWP, NSFP, KodeFaktur, MasaPajak, TarifPajak, KodeBilling,
# and their methods: validate, normalize (for NPWP), to_string, from_string, to_dict,
# from_dict, clone, snapshot, version, audit_trail, touch, __eq__, __hash__.

from datetime import date
from decimal import Decimal

import pytest

from domain.tax_transaction.value_objects import (
    NPWP,
    NSFP,
    KodeBilling,
    KodeFaktur,
    MasaPajak,
    TarifPajak,
    TaxStatus,
)


# ----------------------------------------------------------------------
# TaxStatus Enum
# ----------------------------------------------------------------------
class TestTaxStatus:
    def test_members_exist(self):
        assert hasattr(TaxStatus, "ACTIVE")
        assert hasattr(TaxStatus, "INACTIVE")
        assert hasattr(TaxStatus, "PENDING")
        assert hasattr(TaxStatus, "SUBMITTED")
        assert hasattr(TaxStatus, "FAILED")
        assert hasattr(TaxStatus, "APPROVED")
        assert hasattr(TaxStatus, "REJECTED")
        assert hasattr(TaxStatus, "PAID")

    def test_member_is_instance(self):
        assert isinstance(TaxStatus.ACTIVE, TaxStatus)


# ----------------------------------------------------------------------
# NPWP
# ----------------------------------------------------------------------
class TestNPWP:
    def test_construction_valid(self):
        npwp = NPWP("12.345.678.9-012.345")
        assert npwp.npwp == "12.345.678.9-012.345"
        assert npwp.value == "12.345.678.9-012.345"  # property

    def test_construction_valid_without_formatting(self):
        npwp = NPWP("123456789012345")
        assert npwp.npwp == "123456789012345"

    def test_construction_invalid_too_short(self):
        with pytest.raises(ValueError, match="Invalid NPWP format"):
            NPWP("12345")

    def test_construction_invalid_too_long(self):
        with pytest.raises(ValueError, match="Invalid NPWP format"):
            NPWP("1234567890123456")

    def test_construction_invalid_non_digit(self):
        with pytest.raises(ValueError, match="Invalid NPWP format"):
            NPWP("abcdeabcdeabcde")

    def test_normalize(self):
        npwp = NPWP("123456789012345")
        normalized = npwp.normalize()
        assert normalized.npwp == "12.345.678.9-012.345"

    def test_normalize_already_formatted(self):
        npwp = NPWP("12.345.678.9-012.345")
        normalized = npwp.normalize()
        assert normalized.npwp == "12.345.678.9-012.345"

    def test_to_string(self):
        npwp = NPWP("12.345.678.9-012.345")
        assert npwp.to_string() == "12.345.678.9-012.345"

    def test_from_string(self):
        npwp = NPWP.from_string("123456789012345")
        assert npwp.npwp == "123456789012345"

    def test_to_dict(self):
        npwp = NPWP("12.345.678.9-012.345")
        d = npwp.to_dict()
        assert d["npwp"] == "12.345.678.9-012.345"

    def test_from_dict(self):
        data = {"npwp": "12.345.678.9-012.345"}
        npwp = NPWP.from_dict(data)
        assert npwp.npwp == "12.345.678.9-012.345"

    def test_clone(self):
        original = NPWP("12.345.678.9-012.345")
        cloned = original.clone()
        assert cloned == original
        assert cloned is not original

    def test_snapshot(self):
        npwp = NPWP("12.345.678.9-012.345")
        snap = npwp.snapshot()
        assert snap["npwp"] == "12.345.678.9-012.345"
        assert "timestamp" in snap

    def test_version(self):
        npwp = NPWP("12.345.678.9-012.345")
        assert npwp.version() == 1

    def test_audit_trail(self):
        npwp = NPWP("12.345.678.9-012.345")
        trail = npwp.audit_trail()
        assert trail == [npwp.to_dict()]

    def test_touch(self):
        npwp = NPWP("12.345.678.9-012.345")
        touched = npwp.touch("system")
        assert touched == npwp
        assert touched is not npwp  # clone returns new instance

    def test_validate(self):
        npwp = NPWP("12.345.678.9-012.345")
        result = npwp.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_equality(self):
        npwp1 = NPWP("12.345.678.9-012.345")
        npwp2 = NPWP("12.345.678.9-012.345")
        npwp3 = NPWP("12.345.678.9-012.346")
        assert npwp1 == npwp2
        assert npwp1 != npwp3
        assert npwp1 != "12.345.678.9-012.345"

    def test_equality_ignores_formatting(self):
        npwp1 = NPWP("123456789012345")
        npwp2 = NPWP("12.345.678.9-012.345")
        assert npwp1 == npwp2

    def test_hash(self):
        npwp1 = NPWP("12.345.678.9-012.345")
        npwp2 = NPWP("12.345.678.9-012.345")
        npwp3 = NPWP("12.345.678.9-012.346")
        assert hash(npwp1) == hash(npwp2)
        assert hash(npwp1) != hash(npwp3)


# ----------------------------------------------------------------------
# NSFP
# ----------------------------------------------------------------------
class TestNSFP:
    def test_construction_valid(self):
        nsfp = NSFP(2025, 1, 1000, 2000)
        assert nsfp.tahun == 2025
        assert nsfp.bulan == 1
        assert nsfp.nomor_awal == 1000
        assert nsfp.nomor_akhir == 2000

    def test_construction_invalid_year(self):
        with pytest.raises(ValueError, match="Invalid year"):
            NSFP(1999, 1, 1000, 2000)

    def test_construction_invalid_month(self):
        with pytest.raises(ValueError, match="Invalid month"):
            NSFP(2025, 13, 1000, 2000)

    def test_construction_invalid_range(self):
        with pytest.raises(ValueError, match="Invalid nomor range"):
            NSFP(2025, 1, 2000, 1000)

    def test_construction_nomor_exceeds_limit(self):
        with pytest.raises(ValueError, match="exceed 99,999,999"):
            NSFP(2025, 1, 1, 100000000)

    def test_includes_true(self):
        nsfp = NSFP(2025, 1, 1000, 2000)
        assert nsfp.includes(1500) is True
        assert nsfp.includes(1000) is True
        assert nsfp.includes(2000) is True

    def test_includes_false(self):
        nsfp = NSFP(2025, 1, 1000, 2000)
        assert nsfp.includes(999) is False
        assert nsfp.includes(2001) is False

    def test_to_string(self):
        nsfp = NSFP(2025, 1, 1234, 5678)
        assert nsfp.to_string() == "2025.01.00001234-00005678"

    def test_from_string_valid(self):
        nsfp = NSFP.from_string("2025.01.00001234-00005678")
        assert nsfp.tahun == 2025
        assert nsfp.bulan == 1
        assert nsfp.nomor_awal == 1234
        assert nsfp.nomor_akhir == 5678

    def test_from_string_with_dot_separator(self):
        nsfp = NSFP.from_string("2025.01.1234-5678")
        assert nsfp.tahun == 2025
        assert nsfp.bulan == 1
        assert nsfp.nomor_awal == 1234
        assert nsfp.nomor_akhir == 5678

    def test_from_string_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid NSFP format"):
            NSFP.from_string("2025-01-1234")

    def test_to_dict(self):
        nsfp = NSFP(2025, 1, 1234, 5678)
        d = nsfp.to_dict()
        assert d["tahun"] == 2025
        assert d["bulan"] == 1
        assert d["nomor_awal"] == 1234
        assert d["nomor_akhir"] == 5678

    def test_from_dict(self):
        data = {"tahun": 2025, "bulan": 1, "nomor_awal": 1234, "nomor_akhir": 5678}
        nsfp = NSFP.from_dict(data)
        assert nsfp.tahun == 2025
        assert nsfp.bulan == 1
        assert nsfp.nomor_awal == 1234
        assert nsfp.nomor_akhir == 5678

    def test_clone(self):
        original = NSFP(2025, 1, 1000, 2000)
        cloned = original.clone()
        assert cloned == original
        assert cloned is not original

    def test_snapshot(self):
        nsfp = NSFP(2025, 1, 1000, 2000)
        snap = nsfp.snapshot()
        assert snap["tahun"] == 2025
        assert snap["bulan"] == 1
        assert snap["nomor_awal"] == 1000
        assert snap["nomor_akhir"] == 2000

    def test_version(self):
        nsfp = NSFP(2025, 1, 1000, 2000)
        assert nsfp.version() == 1

    def test_audit_trail(self):
        nsfp = NSFP(2025, 1, 1000, 2000)
        trail = nsfp.audit_trail()
        assert trail == [nsfp.to_dict()]

    def test_touch(self):
        nsfp = NSFP(2025, 1, 1000, 2000)
        touched = nsfp.touch("system")
        assert touched == nsfp
        assert touched is not nsfp

    def test_validate(self):
        nsfp = NSFP(2025, 1, 1000, 2000)
        result = nsfp.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_equality(self):
        nsfp1 = NSFP(2025, 1, 1000, 2000)
        nsfp2 = NSFP(2025, 1, 1000, 2000)
        nsfp3 = NSFP(2025, 1, 1000, 2001)
        assert nsfp1 == nsfp2
        assert nsfp1 != nsfp3
        assert nsfp1 != "2025.01.00001000-00002000"

    def test_hash(self):
        nsfp1 = NSFP(2025, 1, 1000, 2000)
        nsfp2 = NSFP(2025, 1, 1000, 2000)
        nsfp3 = NSFP(2025, 1, 1000, 2001)
        assert hash(nsfp1) == hash(nsfp2)
        assert hash(nsfp1) != hash(nsfp3)


# ----------------------------------------------------------------------
# KodeFaktur
# ----------------------------------------------------------------------
class TestKodeFaktur:
    def test_construction_valid(self):
        kode = KodeFaktur("01")
        assert kode.faktur == "01"
        assert kode.value == "01"  # property

    def test_construction_invalid_not_two_digits(self):
        with pytest.raises(ValueError, match="Kode faktur must be 2 digits"):
            KodeFaktur("1")

    def test_construction_invalid_non_digit(self):
        with pytest.raises(ValueError, match="Kode faktur must be 2 digits"):
            KodeFaktur("ab")

    def test_to_string(self):
        kode = KodeFaktur("02")
        assert kode.to_string() == "02"

    def test_from_string(self):
        kode = KodeFaktur.from_string("03")
        assert kode.faktur == "03"

    def test_to_dict(self):
        kode = KodeFaktur("04")
        d = kode.to_dict()
        assert d["kode_faktur"] == "04"

    def test_from_dict(self):
        data = {"kode_faktur": "05"}
        kode = KodeFaktur.from_dict(data)
        assert kode.faktur == "05"

    def test_clone(self):
        original = KodeFaktur("06")
        cloned = original.clone()
        assert cloned == original
        assert cloned is not original

    def test_snapshot(self):
        kode = KodeFaktur("07")
        snap = kode.snapshot()
        assert snap["kode_faktur"] == "07"

    def test_version(self):
        kode = KodeFaktur("08")
        assert kode.version() == 1

    def test_audit_trail(self):
        kode = KodeFaktur("09")
        trail = kode.audit_trail()
        assert trail == [kode.to_dict()]

    def test_touch(self):
        kode = KodeFaktur("10")
        touched = kode.touch("system")
        assert touched == kode
        assert touched is not kode

    def test_validate(self):
        kode = KodeFaktur("11")
        result = kode.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_equality(self):
        k1 = KodeFaktur("12")
        k2 = KodeFaktur("12")
        k3 = KodeFaktur("13")
        assert k1 == k2
        assert k1 != k3
        assert k1 != "12"

    def test_hash(self):
        k1 = KodeFaktur("12")
        k2 = KodeFaktur("12")
        k3 = KodeFaktur("13")
        assert hash(k1) == hash(k2)
        assert hash(k1) != hash(k3)


# ----------------------------------------------------------------------
# MasaPajak
# ----------------------------------------------------------------------
class TestMasaPajak:
    def test_construction_valid(self):
        masa = MasaPajak(2025, 6)
        assert masa.tahun == 2025
        assert masa.bulan == 6

    def test_construction_invalid_year(self):
        with pytest.raises(ValueError, match="Invalid tax year"):
            MasaPajak(1999, 6)

    def test_construction_invalid_month(self):
        with pytest.raises(ValueError, match="Month must be 1-12"):
            MasaPajak(2025, 13)

    def test_to_string(self):
        masa = MasaPajak(2025, 6)
        assert masa.to_string() == "2025-06"

    def test_from_string_valid(self):
        masa = MasaPajak.from_string("2025-06")
        assert masa.tahun == 2025
        assert masa.bulan == 6

    def test_from_string_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid masa pajak format"):
            MasaPajak.from_string("2025/06")

    def test_to_dict(self):
        masa = MasaPajak(2025, 6)
        d = masa.to_dict()
        assert d["tahun"] == 2025
        assert d["bulan"] == 6

    def test_from_dict(self):
        data = {"tahun": 2025, "bulan": 6}
        masa = MasaPajak.from_dict(data)
        assert masa.tahun == 2025
        assert masa.bulan == 6

    def test_clone(self):
        original = MasaPajak(2025, 6)
        cloned = original.clone()
        assert cloned == original
        assert cloned is not original

    def test_snapshot(self):
        masa = MasaPajak(2025, 6)
        snap = masa.snapshot()
        assert snap["tahun"] == 2025
        assert snap["bulan"] == 6

    def test_version(self):
        masa = MasaPajak(2025, 6)
        assert masa.version() == 1

    def test_audit_trail(self):
        masa = MasaPajak(2025, 6)
        trail = masa.audit_trail()
        assert trail == [masa.to_dict()]

    def test_touch(self):
        masa = MasaPajak(2025, 6)
        touched = masa.touch("system")
        assert touched == masa
        assert touched is not masa

    def test_validate(self):
        masa = MasaPajak(2025, 6)
        result = masa.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_equality(self):
        m1 = MasaPajak(2025, 6)
        m2 = MasaPajak(2025, 6)
        m3 = MasaPajak(2025, 7)
        assert m1 == m2
        assert m1 != m3
        assert m1 != "2025-06"

    def test_hash(self):
        m1 = MasaPajak(2025, 6)
        m2 = MasaPajak(2025, 6)
        m3 = MasaPajak(2025, 7)
        assert hash(m1) == hash(m2)
        assert hash(m1) != hash(m3)


# ----------------------------------------------------------------------
# TarifPajak
# ----------------------------------------------------------------------
class TestTarifPajak:
    def test_construction_valid(self):
        mulai = date(2025, 1, 1)
        tarif = TarifPajak(Decimal("11"), "PPN", mulai)
        assert tarif.value == Decimal("11")
        assert tarif.jenis_pajak == "PPN"
        assert tarif.berlaku_mulai == mulai

    def test_construction_invalid_negative(self):
        with pytest.raises(ValueError, match="Tarif must be between 0 and 100"):
            TarifPajak(Decimal("-1"), "PPN", date.today())

    def test_construction_invalid_above_100(self):
        with pytest.raises(ValueError, match="Tarif must be between 0 and 100"):
            TarifPajak(Decimal("101"), "PPN", date.today())

    def test_construction_empty_jenis_pajak(self):
        with pytest.raises(ValueError, match="Jenis pajak is required"):
            TarifPajak(Decimal("11"), "", date.today())

    def test_as_decimal(self):
        tarif = TarifPajak(Decimal("11"), "PPN", date.today())
        assert tarif.as_decimal() == Decimal("0.11")

    def test_to_string(self):
        tarif = TarifPajak(Decimal("11"), "PPN", date.today())
        assert tarif.to_string() == "11%"

    def test_from_string(self):
        mulai = date(2025, 1, 1)
        tarif = TarifPajak.from_string("11%", "PPN", mulai)
        assert tarif.value == Decimal("11")
        assert tarif.jenis_pajak == "PPN"
        assert tarif.berlaku_mulai == mulai

    def test_to_dict(self):
        mulai = date(2025, 1, 1)
        tarif = TarifPajak(Decimal("11"), "PPN", mulai)
        d = tarif.to_dict()
        assert d["value"] == "11"
        assert d["jenis_pajak"] == "PPN"
        assert d["berlaku_mulai"] == "2025-01-01"

    def test_from_dict(self):
        data = {"value": "11", "jenis_pajak": "PPN", "berlaku_mulai": "2025-01-01"}
        tarif = TarifPajak.from_dict(data)
        assert tarif.value == Decimal("11")
        assert tarif.jenis_pajak == "PPN"
        assert tarif.berlaku_mulai == date(2025, 1, 1)

    def test_clone(self):
        mulai = date(2025, 1, 1)
        original = TarifPajak(Decimal("11"), "PPN", mulai)
        cloned = original.clone()
        assert cloned == original
        assert cloned is not original

    def test_snapshot(self):
        tarif = TarifPajak(Decimal("11"), "PPN", date.today())
        snap = tarif.snapshot()
        assert snap["value"] == "11"
        assert snap["jenis_pajak"] == "PPN"

    def test_version(self):
        tarif = TarifPajak(Decimal("11"), "PPN", date.today())
        assert tarif.version() == 1

    def test_audit_trail(self):
        tarif = TarifPajak(Decimal("11"), "PPN", date.today())
        trail = tarif.audit_trail()
        assert trail == [tarif.to_dict()]

    def test_touch(self):
        tarif = TarifPajak(Decimal("11"), "PPN", date.today())
        touched = tarif.touch("system")
        assert touched == tarif
        assert touched is not tarif

    def test_validate(self):
        tarif = TarifPajak(Decimal("11"), "PPN", date.today())
        result = tarif.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_equality(self):
        mulai = date(2025, 1, 1)
        t1 = TarifPajak(Decimal("11"), "PPN", mulai)
        t2 = TarifPajak(Decimal("11"), "PPN", mulai)
        t3 = TarifPajak(Decimal("12"), "PPN", mulai)
        assert t1 == t2
        assert t1 != t3
        assert t1 != "11%"

    def test_hash(self):
        mulai = date(2025, 1, 1)
        t1 = TarifPajak(Decimal("11"), "PPN", mulai)
        t2 = TarifPajak(Decimal("11"), "PPN", mulai)
        t3 = TarifPajak(Decimal("12"), "PPN", mulai)
        assert hash(t1) == hash(t2)
        assert hash(t1) != hash(t3)


# ----------------------------------------------------------------------
# KodeBilling
# ----------------------------------------------------------------------
class TestKodeBilling:
    def test_construction_valid(self):
        kode = KodeBilling("1234567890123456")
        assert kode.billing == "1234567890123456"
        assert kode.value == "1234567890123456"  # property

    def test_construction_invalid_not_16_digits(self):
        with pytest.raises(ValueError, match="Kode Billing must be 16 digits"):
            KodeBilling("1234")

    def test_construction_invalid_non_digit(self):
        with pytest.raises(ValueError, match="Kode Billing must be 16 digits"):
            KodeBilling("abcdeabcdeabcdeabcde")

    def test_to_string(self):
        kode = KodeBilling("1234567890123456")
        assert kode.to_string() == "1234567890123456"

    def test_from_string(self):
        kode = KodeBilling.from_string("1234567890123456")
        assert kode.billing == "1234567890123456"

    def test_to_dict(self):
        kode = KodeBilling("1234567890123456")
        d = kode.to_dict()
        assert d["kode_billing"] == "1234567890123456"

    def test_from_dict(self):
        data = {"kode_billing": "1234567890123456"}
        kode = KodeBilling.from_dict(data)
        assert kode.billing == "1234567890123456"

    def test_clone(self):
        original = KodeBilling("1234567890123456")
        cloned = original.clone()
        assert cloned == original
        assert cloned is not original

    def test_snapshot(self):
        kode = KodeBilling("1234567890123456")
        snap = kode.snapshot()
        assert snap["kode_billing"] == "1234567890123456"

    def test_version(self):
        kode = KodeBilling("1234567890123456")
        assert kode.version() == 1

    def test_audit_trail(self):
        kode = KodeBilling("1234567890123456")
        trail = kode.audit_trail()
        assert trail == [kode.to_dict()]

    def test_touch(self):
        kode = KodeBilling("1234567890123456")
        touched = kode.touch("system")
        assert touched == kode
        assert touched is not kode

    def test_validate(self):
        kode = KodeBilling("1234567890123456")
        result = kode.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_equality(self):
        k1 = KodeBilling("1234567890123456")
        k2 = KodeBilling("1234567890123456")
        k3 = KodeBilling("1234567890123457")
        assert k1 == k2
        assert k1 != k3
        assert k1 != "1234567890123456"

    def test_hash(self):
        k1 = KodeBilling("1234567890123456")
        k2 = KodeBilling("1234567890123456")
        k3 = KodeBilling("1234567890123457")
        assert hash(k1) == hash(k2)
        assert hash(k1) != hash(k3)
