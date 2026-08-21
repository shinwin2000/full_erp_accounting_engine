#!/usr/bin/env python3

"""
Module: coretax_submission_request.py

Layer: 8 - Application / DTO Objects

Responsibility:
    Data Transfer Objects untuk komunikasi dengan Coretax DJP.

Fitur:
    - NPWP, NTPN, MasaPajak, TahunPajak value objects
    - Faktur Pajak Keluaran/Masukan
    - SPT Masa PPN, PPh 21, PPh 23
    - SPT Tahunan Badan
    - Coretax authentication, query, retrieval
    - Serialisasi/deserialisasi ke format Coretax DJP
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

# === 1. CONSTANTS ===

CORETAX_DATE_FORMAT = "%Y-%m-%d"
CORETAX_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


# === 2. ENUMS ===


class FakturPajakKode(Enum):
    PENJUALAN_DPP_TERHITUNG = "01"
    PENJUALAN_NORMAL = "02"
    PENJUALAN_PERTAMBANGAN = "03"
    PENJUALAN_AGRO = "04"
    KODE_LAIN = "05"


class JenisLaporan(Enum):
    SPT_MASA_PPN = "1111"
    SPT_MASA_PPH_21 = "1121"
    SPT_MASA_PPH_22 = "1122"
    SPT_MASA_PPH_23 = "1123"
    SPT_MASA_PPH_4_AYAT_2 = "1124"
    SPT_MASA_PPH_26 = "1126"
    SPT_TAHUNAN_BADAN = "1112"
    SPT_TAHUNAN_ORANG_PRIBADI = "1113"


class StatusCoretaxSubmission(Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    SENT = "SENT"
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_REVISION = "NEEDS_REVISION"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


class JenisPajak(Enum):
    PPN = "PPN"
    PPH_21 = "PPH21"
    PPH_22 = "PPH22"
    PPH_23 = "PPH23"
    PPH_4_AYAT_2 = "PPH4_2"
    PPH_26 = "PPH26"
    PPH_BADAN = "PPH_BADAN"
    BEA_METERAI = "BEA_METERAI"


class LampiranSPTPPN(Enum):
    LAMPIRAN_A1 = "A1"
    LAMPIRAN_A2 = "A2"
    LAMPIRAN_B1 = "B1"
    LAMPIRAN_B2 = "B2"
    LAMPIRAN_B3 = "B3"


class KodeObjekPajak(Enum):
    """Kode objek pajak untuk PPh 23"""

    SEWA = "24-100-01"
    JASA_TEKNIK = "24-100-02"
    JASA_MANAJEMEN = "24-100-03"
    JASA_KONSULTAN = "24-100-04"
    JASA_LAINNYA = "24-100-99"


# === 3. VALUE OBJECTS ===


@dataclass(frozen=True, kw_only=True)
class NPWP:
    value: str

    def __post_init__(self) -> None:
        cleaned = "".join(filter(str.isdigit, self.value))
        if len(cleaned) not in (15, 16):
            raise ValueError(f"NPWP harus 15 atau 16 digit, mendapat {len(cleaned)}")
        object.__setattr__(self, "value", cleaned)

    def formatted(self) -> str:
        v = self.value.rjust(15, "0")[:15]
        return f"{v[0:2]}.{v[2:5]}.{v[5:8]}.{v[8:9]}-{v[9:12]}.{v[12:15]}"

    def to_dict(self) -> dict:
        return {"npwp": self.value, "npwpFormatted": self.formatted()}

    @classmethod
    def from_string(cls, s: str) -> NPWP:
        return cls(value=s)


@dataclass(frozen=True, kw_only=True)
class NTPN:
    value: str

    def __post_init__(self) -> None:
        if not self.value.isdigit() or len(self.value) != 6:
            raise ValueError(f"NTPN harus 6 digit, mendapat {self.value}")

    @classmethod
    def from_string(cls, s: str) -> NTPN:
        return cls(value=s)


# Alias untuk backward compatibility (beberapa kode mengimpor NTPNReference)
NTPNReference = NTPN


@dataclass(frozen=True, kw_only=True)
class MasaPajak:
    tahun: int
    bulan: int

    def __post_init__(self) -> None:
        if not 1 <= self.bulan <= 12:
            raise ValueError(f"Bulan harus 1-12, mendapat {self.bulan}")
        if self.tahun < 2000 or self.tahun > 2100:
            raise ValueError(f"Tahun tidak valid: {self.tahun}")

    def to_str(self) -> str:
        return f"{self.tahun}{self.bulan:02d}"

    @classmethod
    def from_str(cls, s: str) -> MasaPajak:
        if len(s) != 6:
            raise ValueError("Masa pajak harus 6 digit (YYYYMM)")
        tahun = int(s[:4])
        bulan = int(s[4:])
        return cls(tahun=tahun, bulan=bulan)


@dataclass(frozen=True, kw_only=True)
class TahunPajak:
    tahun: int

    def __post_init__(self) -> None:
        if self.tahun < 2000 or self.tahun > 2100:
            raise ValueError(f"Tahun tidak valid: {self.tahun}")

    def to_str(self) -> str:
        return str(self.tahun)


# === 4. CORE DTOs ===


@dataclass(frozen=True, kw_only=True)
class FakturPajakKeluaranDTO:
    npwp_penjual: NPWP
    npwp_pembeli: NPWP
    nama_pembeli: str
    alamat_pembeli: str
    tanggal_faktur: date
    dpp: Decimal
    ppn: Decimal
    id: UUID = field(default_factory=uuid4)
    ppnbm: Decimal = Decimal("0")
    kode_dokumen: FakturPajakKode = FakturPajakKode.PENJUALAN_NORMAL
    seri_faktur: str = ""
    status: StatusCoretaxSubmission = StatusCoretaxSubmission.DRAFT
    qr_code: str = ""
    approval_code: str = ""

    def total_pajak(self) -> Decimal:
        return (self.ppn + self.ppnbm).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def to_coretax_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "penjual": {"npwp": self.npwp_penjual.value},
            "pembeli": {
                "npwp": self.npwp_pembeli.value,
                "nama": self.nama_pembeli,
                "alamat": self.alamat_pembeli,
            },
            "tanggalFaktur": self.tanggal_faktur.strftime(CORETAX_DATE_FORMAT),
            "dpp": float(self.dpp),
            "ppn": float(self.ppn),
            "ppnbm": float(self.ppnbm),
            "kodeDokumen": self.kode_dokumen.value,
        }

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "npwp_penjual": self.npwp_penjual.value,
            "npwp_pembeli": self.npwp_pembeli.value,
            "nama_pembeli": self.nama_pembeli,
            "alamat_pembeli": self.alamat_pembeli,
            "tanggal_faktur": self.tanggal_faktur.isoformat(),
            "dpp": str(self.dpp),
            "ppn": str(self.ppn),
            "ppnbm": str(self.ppnbm),
            "kode_dokumen": self.kode_dokumen.value,
            "seri_faktur": self.seri_faktur,
            "status": self.status.value,
            "qr_code": self.qr_code,
            "approval_code": self.approval_code,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FakturPajakKeluaranDTO:
        return cls(
            id=UUID(data["id"]) if "id" in data else uuid4(),
            npwp_penjual=NPWP(value=data["npwp_penjual"]),
            npwp_pembeli=NPWP(value=data["npwp_pembeli"]),
            nama_pembeli=data["nama_pembeli"],
            alamat_pembeli=data["alamat_pembeli"],
            tanggal_faktur=date.fromisoformat(data["tanggal_faktur"]),
            dpp=Decimal(data["dpp"]),
            ppn=Decimal(data["ppn"]),
            ppnbm=Decimal(data.get("ppnbm", "0")),
            kode_dokumen=FakturPajakKode(data.get("kode_dokumen", "02")),
            seri_faktur=data.get("seri_faktur", ""),
            status=StatusCoretaxSubmission(data.get("status", "DRAFT")),
            qr_code=data.get("qr_code", ""),
            approval_code=data.get("approval_code", ""),
        )


@dataclass(frozen=True, kw_only=True)
class FakturPajakMasukanDTO:
    npwp_pembeli: NPWP
    npwp_penjual: NPWP
    nama_penjual: str
    alamat_penjual: str
    tanggal_faktur: date
    dpp: Decimal
    ppn: Decimal
    faktur_pajak_keluaran_id: str
    id: UUID = field(default_factory=uuid4)
    ppnbm: Decimal = Decimal("0")
    kode_dokumen: FakturPajakKode = FakturPajakKode.PENJUALAN_NORMAL
    seri_faktur: str = ""
    status: StatusCoretaxSubmission = StatusCoretaxSubmission.DRAFT
    masa_pajak_pengakuan: MasaPajak = field(
        default_factory=lambda: MasaPajak(tahun=datetime.now().year, bulan=datetime.now().month)
    )

    def total_pajak(self) -> Decimal:
        return (self.ppn + self.ppnbm).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def to_coretax_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "pembeli": {"npwp": self.npwp_pembeli.value},
            "penjual": {
                "npwp": self.npwp_penjual.value,
                "nama": self.nama_penjual,
                "alamat": self.alamat_penjual,
            },
            "tanggalFaktur": self.tanggal_faktur.strftime(CORETAX_DATE_FORMAT),
            "dpp": float(self.dpp),
            "ppn": float(self.ppn),
            "ppnbm": float(self.ppnbm),
            "kodeDokumen": self.kode_dokumen.value,
            "fakturPajakKeluaranId": self.faktur_pajak_keluaran_id,
        }

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "npwp_pembeli": self.npwp_pembeli.value,
            "npwp_penjual": self.npwp_penjual.value,
            "nama_penjual": self.nama_penjual,
            "alamat_penjual": self.alamat_penjual,
            "tanggal_faktur": self.tanggal_faktur.isoformat(),
            "dpp": str(self.dpp),
            "ppn": str(self.ppn),
            "ppnbm": str(self.ppnbm),
            "kode_dokumen": self.kode_dokumen.value,
            "seri_faktur": self.seri_faktur,
            "status": self.status.value,
            "faktur_pajak_keluaran_id": self.faktur_pajak_keluaran_id,
            "masa_pajak_pengakuan": self.masa_pajak_pengakuan.to_str(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> FakturPajakMasukanDTO:
        return cls(
            id=UUID(data["id"]) if "id" in data else uuid4(),
            npwp_pembeli=NPWP(value=data["npwp_pembeli"]),
            npwp_penjual=NPWP(value=data["npwp_penjual"]),
            nama_penjual=data["nama_penjual"],
            alamat_penjual=data["alamat_penjual"],
            tanggal_faktur=date.fromisoformat(data["tanggal_faktur"]),
            dpp=Decimal(data["dpp"]),
            ppn=Decimal(data["ppn"]),
            ppnbm=Decimal(data.get("ppnbm", "0")),
            kode_dokumen=FakturPajakKode(data.get("kode_dokumen", "02")),
            seri_faktur=data.get("seri_faktur", ""),
            status=StatusCoretaxSubmission(data.get("status", "DRAFT")),
            faktur_pajak_keluaran_id=data["faktur_pajak_keluaran_id"],
            masa_pajak_pengakuan=MasaPajak.from_str(
                data.get("masa_pajak_pengakuan", f"{datetime.now().year}{datetime.now().month:02d}")
            ),
        )


# === 5. SPT DTOs ===


@dataclass(frozen=True, kw_only=True)
class SPTMasaPpnRequest:
    npwp_pemilik: NPWP
    masa_pajak: MasaPajak
    id: UUID = field(default_factory=uuid4)
    status: StatusCoretaxSubmission = StatusCoretaxSubmission.READY
    total_penyerahan_dpp: Decimal = Decimal("0")
    total_ppn_keluaran: Decimal = Decimal("0")
    total_ppn_masukan: Decimal = Decimal("0")
    kompensasi_dari_masa_sebelumnya: Decimal = Decimal("0")
    restitusi_diminta: Decimal = Decimal("0")
    lampiran: list[LampiranSPTPPN] = field(default_factory=list)
    tanda_tangan_digital: str = ""
    idempotency_key: str = field(default_factory=lambda: str(uuid4()))

    def net_ppn_terutang(self) -> Decimal:
        ppn_kurang = self.total_ppn_keluaran - self.total_ppn_masukan
        return max(ppn_kurang - self.kompensasi_dari_masa_sebelumnya, Decimal("0"))

    def to_coretax_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "npwp": self.npwp_pemilik.value,
            "masaPajak": self.masa_pajak.to_str(),
            "totalPenyerahanDPP": float(self.total_penyerahan_dpp),
            "totalPPNKeluaran": float(self.total_ppn_keluaran),
            "totalPPNMasukan": float(self.total_ppn_masukan),
            "kompensasiDariMasaSebelumnya": float(self.kompensasi_dari_masa_sebelumnya),
            "restitusiDiminta": float(self.restitusi_diminta),
            "lampiran": [lamp.value for lamp in self.lampiran],  # E741 fix
            "tandaTanganDigital": self.tanda_tangan_digital,
            "idempotencyKey": self.idempotency_key,
        }

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "npwp_pemilik": self.npwp_pemilik.value,
            "masa_pajak": self.masa_pajak.to_str(),
            "status": self.status.value,
            "total_penyerahan_dpp": str(self.total_penyerahan_dpp),
            "total_ppn_keluaran": str(self.total_ppn_keluaran),
            "total_ppn_masukan": str(self.total_ppn_masukan),
            "kompensasi_dari_masa_sebelumnya": str(self.kompensasi_dari_masa_sebelumnya),
            "restitusi_diminta": str(self.restitusi_diminta),
            "lampiran": [lamp.value for lamp in self.lampiran],  # E741 fix
            "tanda_tangan_digital": self.tanda_tangan_digital,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SPTMasaPpnRequest:
        return cls(
            id=UUID(data["id"]) if "id" in data else uuid4(),
            npwp_pemilik=NPWP(value=data["npwp_pemilik"]),
            masa_pajak=MasaPajak.from_str(data["masa_pajak"]),
            status=StatusCoretaxSubmission(data.get("status", "READY")),
            total_penyerahan_dpp=Decimal(data.get("total_penyerahan_dpp", "0")),
            total_ppn_keluaran=Decimal(data.get("total_ppn_keluaran", "0")),
            total_ppn_masukan=Decimal(data.get("total_ppn_masukan", "0")),
            kompensasi_dari_masa_sebelumnya=Decimal(
                data.get("kompensasi_dari_masa_sebelumnya", "0")
            ),
            restitusi_diminta=Decimal(data.get("restitusi_diminta", "0")),
            lampiran=[LampiranSPTPPN(lamp) for lamp in data.get("lampiran", [])],  # E741 fix
            tanda_tangan_digital=data.get("tanda_tangan_digital", ""),
            idempotency_key=data.get("idempotency_key", str(uuid4())),
        )


@dataclass(frozen=True, kw_only=True)
class SPTMasaPph21Request:
    npwp_pemotong: NPWP
    masa_pajak: MasaPajak
    id: UUID = field(default_factory=uuid4)
    status: StatusCoretaxSubmission = StatusCoretaxSubmission.READY
    total_bruto: Decimal = Decimal("0")
    total_pph_dipotong: Decimal = Decimal("0")
    total_ssp_disetor: Decimal = Decimal("0")
    jumlah_bukti_potong: int = 0
    tanda_tangan_digital: str = ""
    idempotency_key: str = field(default_factory=lambda: str(uuid4()))

    def kurang_bayar(self) -> Decimal:
        return max(self.total_pph_dipotong - self.total_ssp_disetor, Decimal("0"))

    def to_coretax_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "npwp": self.npwp_pemotong.value,
            "masaPajak": self.masa_pajak.to_str(),
            "totalBruto": float(self.total_bruto),
            "totalPPhDipotong": float(self.total_pph_dipotong),
            "totalSSPDisetor": float(self.total_ssp_disetor),
            "jumlahBuktiPotong": self.jumlah_bukti_potong,
            "tandaTanganDigital": self.tanda_tangan_digital,
            "idempotencyKey": self.idempotency_key,
        }

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "npwp_pemotong": self.npwp_pemotong.value,
            "masa_pajak": self.masa_pajak.to_str(),
            "status": self.status.value,
            "total_bruto": str(self.total_bruto),
            "total_pph_dipotong": str(self.total_pph_dipotong),
            "total_ssp_disetor": str(self.total_ssp_disetor),
            "jumlah_bukti_potong": self.jumlah_bukti_potong,
            "tanda_tangan_digital": self.tanda_tangan_digital,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SPTMasaPph21Request:
        return cls(
            id=UUID(data["id"]) if "id" in data else uuid4(),
            npwp_pemotong=NPWP(value=data["npwp_pemotong"]),
            masa_pajak=MasaPajak.from_str(data["masa_pajak"]),
            status=StatusCoretaxSubmission(data.get("status", "READY")),
            total_bruto=Decimal(data.get("total_bruto", "0")),
            total_pph_dipotong=Decimal(data.get("total_pph_dipotong", "0")),
            total_ssp_disetor=Decimal(data.get("total_ssp_disetor", "0")),
            jumlah_bukti_potong=data.get("jumlah_bukti_potong", 0),
            tanda_tangan_digital=data.get("tanda_tangan_digital", ""),
            idempotency_key=data.get("idempotency_key", str(uuid4())),
        )


@dataclass(frozen=True, kw_only=True)
class SPTMasaPph23Request:
    npwp_pemotong: NPWP
    masa_pajak: MasaPajak
    id: UUID = field(default_factory=uuid4)
    status: StatusCoretaxSubmission = StatusCoretaxSubmission.READY
    total_bruto: Decimal = Decimal("0")
    total_pph_dipotong: Decimal = Decimal("0")
    total_ssp_disetor: Decimal = Decimal("0")
    jumlah_bukti_potong: int = 0
    rincian_objek_pajak: list[dict] = field(default_factory=list)
    tanda_tangan_digital: str = ""
    idempotency_key: str = field(default_factory=lambda: str(uuid4()))

    def kurang_bayar(self) -> Decimal:
        return max(self.total_pph_dipotong - self.total_ssp_disetor, Decimal("0"))

    def to_coretax_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "npwp": self.npwp_pemotong.value,
            "masaPajak": self.masa_pajak.to_str(),
            "totalBruto": float(self.total_bruto),
            "totalPPhDipotong": float(self.total_pph_dipotong),
            "totalSSPDisetor": float(self.total_ssp_disetor),
            "jumlahBuktiPotong": self.jumlah_bukti_potong,
            "rincianObjekPajak": self.rincian_objek_pajak,
            "tandaTanganDigital": self.tanda_tangan_digital,
            "idempotencyKey": self.idempotency_key,
        }

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "npwp_pemotong": self.npwp_pemotong.value,
            "masa_pajak": self.masa_pajak.to_str(),
            "status": self.status.value,
            "total_bruto": str(self.total_bruto),
            "total_pph_dipotong": str(self.total_pph_dipotong),
            "total_ssp_disetor": str(self.total_ssp_disetor),
            "jumlah_bukti_potong": self.jumlah_bukti_potong,
            "rincian_objek_pajak": self.rincian_objek_pajak,
            "tanda_tangan_digital": self.tanda_tangan_digital,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SPTMasaPph23Request:
        return cls(
            id=UUID(data["id"]) if "id" in data else uuid4(),
            npwp_pemotong=NPWP(value=data["npwp_pemotong"]),
            masa_pajak=MasaPajak.from_str(data["masa_pajak"]),
            status=StatusCoretaxSubmission(data.get("status", "READY")),
            total_bruto=Decimal(data.get("total_bruto", "0")),
            total_pph_dipotong=Decimal(data.get("total_pph_dipotong", "0")),
            total_ssp_disetor=Decimal(data.get("total_ssp_disetor", "0")),
            jumlah_bukti_potong=data.get("jumlah_bukti_potong", 0),
            rincian_objek_pajak=data.get("rincian_objek_pajak", []),
            tanda_tangan_digital=data.get("tanda_tangan_digital", ""),
            idempotency_key=data.get("idempotency_key", str(uuid4())),
        )


@dataclass(frozen=True, kw_only=True)
class SPTTahunanBadanRequest:
    npwp_wajib_pajak: NPWP
    tahun_pajak: TahunPajak
    id: UUID = field(default_factory=uuid4)
    status: StatusCoretaxSubmission = StatusCoretaxSubmission.READY
    peredaran_bruto: Decimal = Decimal("0")
    penghasilan_netto: Decimal = Decimal("0")
    kompensasi_kerugian: Decimal = Decimal("0")
    penghasilan_kena_pajak: Decimal = Decimal("0")
    pph_terutang: Decimal = Decimal("0")
    kredit_pajak_luar_negeri: Decimal = Decimal("0")
    pajak_dipotong_dipungut: Decimal = Decimal("0")
    pph_dibayar_sendiri: Decimal = Decimal("0")
    pph_kurang_bayar: Decimal = Decimal("0")
    pph_lebih_bayar: Decimal = Decimal("0")
    restitusi_diminta: Decimal = Decimal("0")
    lampiran: list[str] = field(default_factory=list)
    tanda_tangan_digital: str = ""
    idempotency_key: str = field(default_factory=lambda: str(uuid4()))

    def to_coretax_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "npwp": self.npwp_wajib_pajak.value,
            "tahunPajak": self.tahun_pajak.to_str(),
            "peredaranBruto": float(self.peredaran_bruto),
            "penghasilanNetto": float(self.penghasilan_netto),
            "kompensasiKerugian": float(self.kompensasi_kerugian),
            "penghasilanKenaPajak": float(self.penghasilan_kena_pajak),
            "pphTerutang": float(self.pph_terutang),
            "kreditPajakLuarNegeri": float(self.kredit_pajak_luar_negeri),
            "pajakDipotongDipungut": float(self.pajak_dipotong_dipungut),
            "pphDibayarSendiri": float(self.pph_dibayar_sendiri),
            "pphKurangBayar": float(self.pph_kurang_bayar),
            "pphLebihBayar": float(self.pph_lebih_bayar),
            "restitusiDiminta": float(self.restitusi_diminta),
            "lampiran": self.lampiran,
            "tandaTanganDigital": self.tanda_tangan_digital,
            "idempotencyKey": self.idempotency_key,
        }

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "npwp_wajib_pajak": self.npwp_wajib_pajak.value,
            "tahun_pajak": self.tahun_pajak.to_str(),
            "status": self.status.value,
            "peredaran_bruto": str(self.peredaran_bruto),
            "penghasilan_netto": str(self.penghasilan_netto),
            "kompensasi_kerugian": str(self.kompensasi_kerugian),
            "penghasilan_kena_pajak": str(self.penghasilan_kena_pajak),
            "pph_terutang": str(self.pph_terutang),
            "kredit_pajak_luar_negeri": str(self.kredit_pajak_luar_negeri),
            "pajak_dipotong_dipungut": str(self.pajak_dipotong_dipungut),
            "pph_dibayar_sendiri": str(self.pph_dibayar_sendiri),
            "pph_kurang_bayar": str(self.pph_kurang_bayar),
            "pph_lebih_bayar": str(self.pph_lebih_bayar),
            "restitusi_diminta": str(self.restitusi_diminta),
            "lampiran": self.lampiran,
            "tanda_tangan_digital": self.tanda_tangan_digital,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SPTTahunanBadanRequest:
        return cls(
            id=UUID(data["id"]) if "id" in data else uuid4(),
            npwp_wajib_pajak=NPWP(value=data["npwp_wajib_pajak"]),
            tahun_pajak=TahunPajak(tahun=int(data["tahun_pajak"])),
            status=StatusCoretaxSubmission(data.get("status", "READY")),
            peredaran_bruto=Decimal(data.get("peredaran_bruto", "0")),
            penghasilan_netto=Decimal(data.get("penghasilan_netto", "0")),
            kompensasi_kerugian=Decimal(data.get("kompensasi_kerugian", "0")),
            penghasilan_kena_pajak=Decimal(data.get("penghasilan_kena_pajak", "0")),
            pph_terutang=Decimal(data.get("pph_terutang", "0")),
            kredit_pajak_luar_negeri=Decimal(data.get("kredit_pajak_luar_negeri", "0")),
            pajak_dipotong_dipungut=Decimal(data.get("pajak_dipotong_dipungut", "0")),
            pph_dibayar_sendiri=Decimal(data.get("pph_dibayar_sendiri", "0")),
            pph_kurang_bayar=Decimal(data.get("pph_kurang_bayar", "0")),
            pph_lebih_bayar=Decimal(data.get("pph_lebih_bayar", "0")),
            restitusi_diminta=Decimal(data.get("restitusi_diminta", "0")),
            lampiran=data.get("lampiran", []),
            tanda_tangan_digital=data.get("tanda_tangan_digital", ""),
            idempotency_key=data.get("idempotency_key", str(uuid4())),
        )


# === 6. BuktiPotong DTOs ===


@dataclass(frozen=True, kw_only=True)
class BuktiPotongPPh23DTO:
    npwp_pemotong: NPWP
    npwp_penerima_penghasilan: NPWP
    nama_penerima_penghasilan: str
    alamat_penerima_penghasilan: str
    masa_pajak: MasaPajak
    tanggal_bukti_potong: date
    kode_objek_pajak: KodeObjekPajak
    jumlah_bruto: Decimal
    tarif: Decimal
    pph_dipotong: Decimal
    id: UUID = field(default_factory=uuid4)
    ntpn: NTPN | None = None
    status: StatusCoretaxSubmission = StatusCoretaxSubmission.DRAFT
    idempotency_key: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self):
        if self.pph_dipotong != (self.jumlah_bruto * self.tarif / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        ):
            raise ValueError("PPh dipotong tidak sesuai dengan jumlah bruto * tarif")

    def to_coretax_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "pemotong": {"npwp": self.npwp_pemotong.value},
            "penerimaPenghasilan": {
                "npwp": self.npwp_penerima_penghasilan.value,
                "nama": self.nama_penerima_penghasilan,
                "alamat": self.alamat_penerima_penghasilan,
            },
            "masaPajak": self.masa_pajak.to_str(),
            "tanggalBuktiPotong": self.tanggal_bukti_potong.strftime(CORETAX_DATE_FORMAT),
            "kodeObjekPajak": self.kode_objek_pajak.value,
            "jumlahBruto": float(self.jumlah_bruto),
            "tarif": float(self.tarif),
            "pphDipotong": float(self.pph_dipotong),
            "ntpn": self.ntpn.value if self.ntpn else None,
            "idempotencyKey": self.idempotency_key,
        }

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "npwp_pemotong": self.npwp_pemotong.value,
            "npwp_penerima_penghasilan": self.npwp_penerima_penghasilan.value,
            "nama_penerima_penghasilan": self.nama_penerima_penghasilan,
            "alamat_penerima_penghasilan": self.alamat_penerima_penghasilan,
            "masa_pajak": self.masa_pajak.to_str(),
            "tanggal_bukti_potong": self.tanggal_bukti_potong.isoformat(),
            "kode_objek_pajak": self.kode_objek_pajak.value,
            "jumlah_bruto": str(self.jumlah_bruto),
            "tarif": str(self.tarif),
            "pph_dipotong": str(self.pph_dipotong),
            "ntpn": self.ntpn.value if self.ntpn else None,
            "status": self.status.value,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BuktiPotongPPh23DTO:
        return cls(
            id=UUID(data["id"]) if "id" in data else uuid4(),
            npwp_pemotong=NPWP(value=data["npwp_pemotong"]),
            npwp_penerima_penghasilan=NPWP(value=data["npwp_penerima_penghasilan"]),
            nama_penerima_penghasilan=data["nama_penerima_penghasilan"],
            alamat_penerima_penghasilan=data["alamat_penerima_penghasilan"],
            masa_pajak=MasaPajak.from_str(data["masa_pajak"]),
            tanggal_bukti_potong=date.fromisoformat(data["tanggal_bukti_potong"]),
            kode_objek_pajak=KodeObjekPajak(data["kode_objek_pajak"]),
            jumlah_bruto=Decimal(data["jumlah_bruto"]),
            tarif=Decimal(data["tarif"]),
            pph_dipotong=Decimal(data["pph_dipotong"]),
            ntpn=NTPN(value=data["ntpn"]) if data.get("ntpn") else None,
            status=StatusCoretaxSubmission(data.get("status", "DRAFT")),
            idempotency_key=data.get("idempotency_key", str(uuid4())),
        )


# === 7. Coretax request/response DTOs ===


@dataclass(frozen=True, kw_only=True)
class CoretaxAuthRequest:
    client_id: str
    client_secret: str
    grant_type: str = "client_credentials"

    def to_dict(self) -> dict:
        return {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": self.grant_type,
        }


@dataclass(frozen=True, kw_only=True)
class CoretaxQueryRequest:
    nomor_identitas: str
    jenis_identitas: str = "NPWP"

    def to_dict(self) -> dict:
        return {
            "nomorIdentitas": self.nomor_identitas,
            "jenisIdentitas": self.jenis_identitas,
        }


@dataclass(frozen=True, kw_only=True)
class CoretaxRetrievalRequest:
    nomor_faktur_pajak: str
    tahun: int

    def to_dict(self) -> dict:
        return {
            "nomorFakturPajak": self.nomor_faktur_pajak,
            "tahun": self.tahun,
        }


@dataclass(frozen=True, kw_only=True)
class CoretaxSubmissionResponse:
    submission_id: str
    status: StatusCoretaxSubmission
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    reference_number: str | None = None
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "submission_id": self.submission_id,
            "status": self.status.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "reference_number": self.reference_number,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CoretaxSubmissionResponse:
        return cls(
            submission_id=data["submission_id"],
            status=StatusCoretaxSubmission(data["status"]),
            message=data["message"],
            timestamp=datetime.fromisoformat(data["timestamp"])
            if "timestamp" in data
            else datetime.now(UTC),
            reference_number=data.get("reference_number"),
            errors=data.get("errors", []),
        )


# === 8. Simple DTO for test compatibility ===


@dataclass(frozen=True, kw_only=True)
class CoretaxSubmissionRequest:
    """Simple submission request DTO for unit tests."""

    npwp_pemotong: str
    masa_pajak: int
    tahun_pajak: int
    total_pph: Decimal

    def __post_init__(self) -> None:
        cleaned_npwp = "".join(filter(str.isdigit, self.npwp_pemotong))
        if len(cleaned_npwp) not in (15, 16):
            raise ValueError("NPWP harus 15 atau 16 digit")
        if not 1 <= self.masa_pajak <= 12:
            raise ValueError("Masa pajak harus 1-12")
        if self.tahun_pajak < 2000 or self.tahun_pajak > 2100:
            raise ValueError("Tahun pajak tidak valid")
        if self.total_pph <= 0:
            raise ValueError("Total PPH harus > 0")

    def to_json(self) -> str:
        data = {
            "npwpPemotong": self.npwp_pemotong,
            "masaPajak": self.masa_pajak,
            "tahunPajak": self.tahun_pajak,
            "totalPPh": float(self.total_pph),
        }
        return json.dumps(data)

    def validate(self) -> dict[str, str]:
        errors = {}
        cleaned_npwp = "".join(filter(str.isdigit, self.npwp_pemotong))
        if len(cleaned_npwp) not in (15, 16):
            errors["npwp_pemotong"] = "NPWP harus 15 atau 16 digit"
        if not 1 <= self.masa_pajak <= 12:
            errors["masa_pajak"] = "Masa pajak harus antara 1 dan 12"
        return errors


# === 9. Validators ===


class CoretaxDTOValidationError(Exception):
    pass


class CoretaxDTOValidator:
    @staticmethod
    def validate_npwp(npwp: str) -> bool:
        cleaned = "".join(filter(str.isdigit, npwp))
        return len(cleaned) in (15, 16)

    @staticmethod
    def validate_ntpn(ntpn: str) -> bool:
        return ntpn.isdigit() and len(ntpn) == 6

    @staticmethod
    def validate_masa_pajak(tahun: int, bulan: int) -> bool:
        return 2000 <= tahun <= 2100 and 1 <= bulan <= 12


class CoretaxSerializationError(Exception):
    pass


def serialize_coretax_request(dto: Any) -> str:
    """Serialize a coretax DTO to JSON string."""
    try:
        if hasattr(dto, "to_coretax_payload"):
            payload = dto.to_coretax_payload()
        elif hasattr(dto, "to_dict"):
            payload = dto.to_dict()
        else:
            raise CoretaxSerializationError(f"Object {type(dto)} does not support serialization")
        return json.dumps(payload, default=str)
    except Exception as e:
        raise CoretaxSerializationError(f"Serialization failed: {e}")


def deserialize_coretax_response(json_str: str, dto_class: Any) -> Any:
    """Deserialize a coretax response JSON to a DTO instance."""
    try:
        data = json.loads(json_str)
        if hasattr(dto_class, "from_dict"):
            return dto_class.from_dict(data)
        elif hasattr(dto_class, "from_coretax_payload"):
            return dto_class.from_coretax_payload(data)
        else:
            raise CoretaxSerializationError(f"Class {dto_class} does not support deserialization")
    except Exception as e:
        raise CoretaxSerializationError(f"Deserialization failed: {e}")


# === 10. EXPORTS ===

__all__ = [
    "CORETAX_DATETIME_FORMAT",
    "CORETAX_DATE_FORMAT",
    "NPWP",
    "NTPN",
    "BuktiPotongPPh23DTO",
    "CoretaxAuthRequest",
    "CoretaxDTOValidationError",
    "CoretaxDTOValidator",
    "CoretaxQueryRequest",
    "CoretaxRetrievalRequest",
    "CoretaxSerializationError",
    "CoretaxSubmissionRequest",
    "CoretaxSubmissionResponse",
    "FakturPajakKeluaranDTO",
    "FakturPajakKode",
    "FakturPajakMasukanDTO",
    "JenisLaporan",
    "JenisPajak",
    "KodeObjekPajak",
    "LampiranSPTPPN",
    "MasaPajak",
    "NTPNReference",
    "SPTMasaPph21Request",
    "SPTMasaPph23Request",
    "SPTMasaPpnRequest",
    "SPTTahunanBadanRequest",
    "StatusCoretaxSubmission",
    "TahunPajak",
    "deserialize_coretax_response",
    "serialize_coretax_request",
]
