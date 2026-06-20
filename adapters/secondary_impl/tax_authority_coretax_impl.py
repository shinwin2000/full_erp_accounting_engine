#!/usr/bin/env python3
"""
Module: coretax_authority_adapter_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi adapter untuk Coretax DJP (tax authority).
Menggunakan API client yang sudah ada di adapters/coretax_djp/.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

# Import adapter dari coretax_djp
from adapters.coretax_djp.api_oauth2_client import CoretaxOAuth2Client
from adapters.coretax_djp.e_bupot_generator import EBupotGenerator
from adapters.coretax_djp.faktur_keluaran_generator import FakturKeluaranGenerator
from adapters.coretax_djp.faktur_masukan_processor import FakturMasukanProcessor

# FIXED: Import kelas yang benar, bukan HealthDashboard yang tidak ada
from adapters.coretax_djp.health_dashboard import CoretaxHealthChecker, get_health_checker
from adapters.coretax_djp.nsfp_manager import NSFPManager
from adapters.coretax_djp.ntpn_validator import NTPNValidator
from adapters.coretax_djp.spt_masa_pph_21_builder import SPTMasaPph21Builder
from adapters.coretax_djp.spt_masa_pph_23_builder import SPTMasaPph23Builder
from adapters.coretax_djp.spt_masa_ppn_builder import SPTMasaPpnBuilder
from ports.primary.tax_authority_coretax_port import TaxAuthorityCoretaxPort


class CoretaxAuthorityAdapter(TaxAuthorityCoretaxPort):
    """Implementasi adapter untuk komunikasi dengan Coretax DJP."""

    def __init__(self, config: dict[str, Any]):
        self._oauth_client = CoretaxOAuth2Client(config)
        self._faktur_keluaran = FakturKeluaranGenerator(self._oauth_client)
        self._faktur_masukan = FakturMasukanProcessor(self._oauth_client)
        self._bupot_generator = EBupotGenerator(self._oauth_client)
        self._nsfp_manager = NSFPManager(self._oauth_client)
        self._ntpn_validator = NTPNValidator(self._oauth_client)
        self._spt_ppn = SPTMasaPpnBuilder(self._oauth_client)
        self._spt_pph21 = SPTMasaPph21Builder(self._oauth_client)
        self._spt_pph23 = SPTMasaPph23Builder(self._oauth_client)
        # Gunakan CoretaxHealthChecker untuk health check
        self._health_checker: CoretaxHealthChecker | None = None

    async def _get_health_checker(self) -> CoretaxHealthChecker:
        """Get or create health checker instance."""
        if self._health_checker is None:
            self._health_checker = await get_health_checker()
        return self._health_checker

    async def authenticate(self) -> bool:
        """Authenticate ke Coretax API."""
        return await self._oauth_client.authenticate()

    # ========== Faktur Pajak ==========
    async def submit_faktur_keluaran(self, faktur_data: dict[str, Any]) -> dict[str, Any]:
        """Submit faktur keluaran (output tax invoice) ke Coretax."""
        return await self._faktur_keluaran.submit(faktur_data)

    async def get_faktur_keluaran_status(self, faktur_id: str) -> dict[str, Any]:
        """Cek status faktur keluaran."""
        return await self._faktur_keluaran.get_status(faktur_id)

    async def submit_faktur_masukan(self, faktur_data: dict[str, Any]) -> dict[str, Any]:
        """Submit faktur masukan (input tax invoice) untuk dikreditkan."""
        return await self._faktur_masukan.submit(faktur_data)

    async def get_faktur_masukan_status(self, faktur_id: str) -> dict[str, Any]:
        return await self._faktur_masukan.get_status(faktur_id)

    # ========== e-Bupot ==========
    async def generate_bupot(self, transaction_data: dict[str, Any]) -> dict[str, Any]:
        """Generate Bukti Pemotongan (PPh 23/26)."""
        return await self._bupot_generator.generate(transaction_data)

    async def submit_bupot_batch(self, bupot_list: list[dict[str, Any]]) -> dict[str, Any]:
        """Submit multiple bupot sekaligus."""
        return await self._bupot_generator.submit_batch(bupot_list)

    # ========== NSFP Management ==========
    async def request_nsfp(self, year: int, quantity: int) -> list[str]:
        """Request Nomor Seri Faktur Pajak dari DJP."""
        return await self._nsfp_manager.request(year, quantity)

    async def get_available_nsfp(self, year: int) -> list[str]:
        """Get remaining available NSFP."""
        return await self._nsfp_manager.get_available(year)

    # ========== NTPN Validation ==========
    async def validate_ntpn(self, ntpn: str, amount: Decimal, payment_date: date) -> bool:
        """Validate NTPN (Nomor Transaksi Penerimaan Negara)."""
        return await self._ntpn_validator.validate(ntpn, amount, payment_date)

    # ========== SPT Filing ==========
    async def submit_spt_masa_ppn(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Submit SPT Masa PPN."""
        return await self._spt_ppn.submit(period_year, period_month, data)

    async def submit_spt_masa_pph21(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Submit SPT Masa PPh 21."""
        return await self._spt_pph21.submit(period_year, period_month, data)

    async def submit_spt_masa_pph23(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Submit SPT Masa PPh 23/26."""
        return await self._spt_pph23.submit(period_year, period_month, data)

    # ========== Health Check ==========
    async def check_health(self) -> dict[str, Any]:
        """
        Check kesehatan koneksi ke Coretax.
        Mengembalikan dictionary dengan status dan detail.
        """
        try:
            checker = await self._get_health_checker()
            # Ambil dashboard lengkap untuk mendapatkan status komponen
            dashboard = await checker.get_full_dashboard()
            # Bangun response yang kompatibel dengan yang diharapkan
            return {
                "status": dashboard.overall_status.value,
                "components": {
                    name: {
                        "status": comp.status.value,
                        "message": comp.message,
                        "latency_ms": comp.latency_ms,
                    }
                    for name, comp in dashboard.components.items()
                },
                "timestamp": dashboard.timestamp.isoformat(),
                "version": dashboard.version,
                "uptime_seconds": dashboard.uptime_seconds,
            }
        except Exception as e:
            return {
                "status": "down",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }


__all__ = ["CoretaxAuthorityAdapter"]
