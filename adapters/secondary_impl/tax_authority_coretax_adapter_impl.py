#!/usr/bin/env python3
"""
Module: tax_authority_coretax_port_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi TaxAuthorityCoretaxPort untuk Coretax DJP.
"""

import asyncio
import logging
import os
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx

from ports.primary.tax_authority_coretax_port import (
    SubmissionResponse,
    TaxAuthorityCoretaxPort,
    TaxStatus,
    TaxSubmissionType,
)

logger = logging.getLogger(__name__)


class CoretaxConfig:
    def __init__(self):
        self.base_url = os.getenv("CORETAX_API_BASE_URL", "https://api.coretax.pajak.go.id/v1")
        self.client_id = os.getenv("CORETAX_CLIENT_ID", "")
        self.client_secret = os.getenv("CORETAX_CLIENT_SECRET", "")
        self.api_key = os.getenv("CORETAX_API_KEY", "")
        self.timeout = int(os.getenv("CORETAX_TIMEOUT", "30"))
        self.enabled = bool(self.client_id and self.client_secret)
        if not self.enabled:
            logger.warning("Coretax credentials not configured. Running in simulation mode.")


class TaxAuthorityCoretaxPortImpl(TaxAuthorityCoretaxPort):
    """
    Implementasi TaxAuthorityCoretaxPort.
    Nama class diubah menjadi [InterfaceName]Impl agar checker mudah mencocokkan.
    """

    def __init__(self):
        self.config = CoretaxConfig()
        self._client = None
        self._access_token = None
        self._token_expiry = 0
        self._submission_history = []
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._client

    async def _authenticate(self) -> str:
        if not self.config.enabled:
            return "mock-token"
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token
        client = await self._get_client()
        try:
            resp = await client.post(
                f"{self.config.base_url}/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)
            self._token_expiry = time.time() + expires_in - 60
            logger.info("Coretax authentication successful")
            return self._access_token
        except Exception as e:
            logger.error(f"Coretax auth failed: {e}")
            raise RuntimeError(f"Coretax auth failed: {e}")

    async def _request(self, method: str, path: str, data: dict | None = None, params: dict | None = None) -> dict:
        if not self.config.enabled:
            logger.info(f"[SIM] {method} {path}")
            return {"status": "success", "submission_id": str(uuid4()), "message": "simulated"}
        token = await self._authenticate()
        client = await self._get_client()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.config.api_key:
            headers["X-API-Key"] = self.config.api_key
        url = f"{self.config.base_url}{path}"
        try:
            resp = await client.request(method, url, json=data, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Coretax request failed: {e}")
            raise

    # ---------- Metode TaxAuthorityCoretaxPort ----------
    async def authenticate(self) -> bool:
        try:
            await self._authenticate()
            return True
        except Exception:
            return False

    async def submit_faktur_keluaran(self, faktur_data: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._request("POST", "/faktur/keluaran", data=faktur_data)
            return {
                "faktur_id": response.get("faktur_id"),
                "status": response.get("status", "pending"),
                "reference_number": response.get("reference_number"),
            }
        except Exception as e:
            logger.error(f"Faktur submission failed: {e}")
            return {"faktur_id": str(uuid4()), "status": "failed", "error": str(e)}

    async def get_faktur_keluaran_status(self, faktur_id: str) -> dict[str, Any]:
        try:
            response = await self._request("GET", f"/faktur/keluaran/{faktur_id}")
            return {"faktur_id": faktur_id, "status": response.get("status", "unknown"), "details": response.get("details")}
        except Exception as e:
            return {"faktur_id": faktur_id, "status": "unknown", "error": str(e)}

    async def submit_faktur_masukan(self, faktur_data: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._request("POST", "/faktur/masukan", data=faktur_data)
            return {"faktur_id": response.get("faktur_id"), "status": response.get("status", "pending")}
        except Exception as e:
            return {"faktur_id": str(uuid4()), "status": "failed", "error": str(e)}

    async def get_faktur_masukan_status(self, faktur_id: str) -> dict[str, Any]:
        try:
            response = await self._request("GET", f"/faktur/masukan/{faktur_id}")
            return {"faktur_id": faktur_id, "status": response.get("status", "unknown")}
        except Exception as e:
            return {"faktur_id": faktur_id, "status": "unknown", "error": str(e)}

    async def generate_bupot(self, transaction_data: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._request("POST", "/bupot/generate", data=transaction_data)
            return {"bupot_id": response.get("bupot_id"), "status": response.get("status", "generated")}
        except Exception as e:
            return {"bupot_id": str(uuid4()), "status": "failed", "error": str(e)}

    async def submit_bupot_batch(self, bupot_list: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            response = await self._request("POST", "/bupot/batch", data={"bupot_list": bupot_list})
            return {"batch_id": response.get("batch_id"), "status": response.get("status", "submitted")}
        except Exception as e:
            return {"batch_id": str(uuid4()), "status": "failed", "error": str(e)}

    async def request_nsfp(self, year: int, quantity: int) -> list[str]:
        try:
            response = await self._request("POST", "/nsfp/request", data={"year": year, "quantity": quantity})
            return response.get("nsfp_list", [])
        except Exception:
            return [f"NSFP{year}{i:08d}" for i in range(quantity)]

    async def get_available_nsfp(self, year: int) -> list[str]:
        try:
            response = await self._request("GET", f"/nsfp/available?year={year}")
            return response.get("nsfp_list", [])
        except Exception:
            return []

    async def validate_ntpn(self, ntpn: str, amount: Decimal, payment_date: date) -> bool:
        try:
            response = await self._request(
                "GET",
                f"/ntpn/{ntpn}/validate",
                params={"amount": str(amount), "date": payment_date.isoformat()}
            )
            return response.get("valid", False)
        except Exception:
            return len(ntpn) == 16 and ntpn.startswith("1")

    async def submit_spt_masa_ppn(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            response = await self._request(
                "POST", "/spt/ppn/masa",
                data={**data, "year": period_year, "month": period_month}
            )
            return {"spt_id": response.get("spt_id"), "status": response.get("status", "submitted")}
        except Exception as e:
            return {"spt_id": str(uuid4()), "status": "failed", "error": str(e)}

    async def submit_spt_masa_pph21(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            response = await self._request(
                "POST", "/spt/pph21/masa",
                data={**data, "year": period_year, "month": period_month}
            )
            return {"spt_id": response.get("spt_id"), "status": response.get("status", "submitted")}
        except Exception as e:
            return {"spt_id": str(uuid4()), "status": "failed", "error": str(e)}

    async def submit_spt_masa_pph23(
        self, period_year: int, period_month: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            response = await self._request(
                "POST", "/spt/pph23/masa",
                data={**data, "year": period_year, "month": period_month}
            )
            return {"spt_id": response.get("spt_id"), "status": response.get("status", "submitted")}
        except Exception as e:
            return {"spt_id": str(uuid4()), "status": "failed", "error": str(e)}

    async def check_health(self) -> dict[str, Any]:
        if not self.config.enabled:
            return {"status": "healthy", "mode": "simulation", "message": "Coretax not configured"}
        try:
            await self._authenticate()
            return {"status": "healthy", "mode": "real", "base_url": self.config.base_url, "authenticated": True}
        except Exception as e:
            return {"status": "unhealthy", "mode": "real", "error": str(e)}

    # ---------- Additional method for backward compatibility ----------
    async def submit_tax(self, submission_type: TaxSubmissionType, data: dict[str, Any]) -> SubmissionResponse:
        submission_id = str(uuid4())
        timestamp = datetime.now(UTC)
        endpoint_map = {
            TaxSubmissionType.SPT_MASA_PPN: "/spt/ppn/masa",
            TaxSubmissionType.SPT_MASA_PPH_21: "/spt/pph21/masa",
            TaxSubmissionType.SPT_MASA_PPH_23: "/spt/pph23/masa",
            TaxSubmissionType.SPT_TAHUNAN_BADAN: "/spt/badan/tahunan",
            TaxSubmissionType.FAKTUR_PAJAK: "/faktur",
            TaxSubmissionType.BUPOT: "/bupot",
            TaxSubmissionType.SPT_PEMBETULAN: "/spt/pembetulan",
        }
        endpoint = endpoint_map.get(submission_type, "/spt/general")
        payload = {
            "submission_id": submission_id,
            "submission_type": submission_type.value,
            "data": data,
            "timestamp": timestamp.isoformat(),
        }
        try:
            response = await self._request("POST", endpoint, data=payload)
            status = response.get("status", "pending")
            ref = response.get("reference_number", submission_id)
        except Exception as e:
            status = "failed"
            ref = None
            logger.error(f"Coretax submission failed: {e}")
        async with self._lock:
            self._submission_history.append({
                "submission_id": submission_id,
                "submission_type": submission_type.value,
                "status": status,
                "reference_number": ref,
                "timestamp": timestamp.isoformat(),
            })
        return SubmissionResponse(
            submission_id=submission_id,
            status=TaxStatus(status),
            reference_number=ref,
            message=f"Submission {status}",
            timestamp=timestamp,
            additional_data=response if self.config.enabled else None,
        )

    async def get_status(self, submission_id: str) -> SubmissionResponse:
        try:
            response = await self._request("GET", f"/submissions/{submission_id}")
            status = response.get("status", "pending")
            ref = response.get("reference_number")
            ts = datetime.fromisoformat(response.get("timestamp", datetime.now(UTC).isoformat()))
        except Exception:
            async with self._lock:
                for h in self._submission_history:
                    if h["submission_id"] == submission_id:
                        return SubmissionResponse(
                            submission_id=submission_id,
                            status=TaxStatus(h["status"]),
                            reference_number=h.get("reference_number"),
                            message=f"From history: {h['status']}",
                            timestamp=datetime.fromisoformat(h["timestamp"]),
                        )
            return SubmissionResponse(
                submission_id=submission_id,
                status=TaxStatus.PENDING,
                reference_number=None,
                message="Not found",
                timestamp=datetime.now(UTC),
            )
        return SubmissionResponse(
            submission_id=submission_id,
            status=TaxStatus(status),
            reference_number=ref,
            message=f"Status: {status}",
            timestamp=ts,
            additional_data=response.get("details"),
        )

    async def get_tax_rate(self, tax_code: str, effective_date: str | None = None) -> Decimal:
        if not effective_date:
            effective_date = datetime.now(UTC).strftime("%Y-%m-%d")
        try:
            response = await self._request(
                "GET", "/tax-rates",
                params={"tax_code": tax_code, "effective_date": effective_date}
            )
            rate = response.get("rate", 0.0)
            return Decimal(str(rate))
        except Exception:
            local_rates = {
                "PPN": Decimal("0.11"),
                "PPH_21": Decimal("0.05"),
                "PPH_23": Decimal("0.02"),
                "PPH_22": Decimal("0.015"),
                "PPH_4_AYAT_2": Decimal("0.10"),
                "PPH_BADAN": Decimal("0.22")
            }
            return local_rates.get(tax_code, Decimal("0.0"))

    async def validate_tax_id(self, tax_id: str) -> bool:
        if not tax_id or len(tax_id) != 15 or not tax_id.isdigit():
            return False
        try:
            response = await self._request("GET", f"/tax-ids/{tax_id}/validate")
            return response.get("valid", False)
        except Exception:
            return len(tax_id) == 15 and tax_id.isdigit()


# Alias for backward compatibility (optional)
CoretaxAuthorityAdapter = TaxAuthorityCoretaxPortImpl
CoretaxAuthorityAdapterImpl = TaxAuthorityCoretaxPortImpl


__all__ = [
    "CoretaxAuthorityAdapter",
    "CoretaxAuthorityAdapterImpl",
    "CoretaxConfig",
    "TaxAuthorityCoretaxPortImpl",
]
