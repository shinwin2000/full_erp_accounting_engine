#!/usr/bin/env python3
"""
Module: coretax_authority_adapter.py
Layer: Adapters (Secondary)
Responsibility: Implementasi TaxAuthorityCoretaxPort untuk Coretax DJP.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, UTC
from typing import Dict, Any, Optional, List
from uuid import uuid4

import httpx

from ports.primary.tax_authority_coretax_port import (
    TaxAuthorityCoretaxPort,
    TaxSubmissionType,
    TaxStatus,
    SubmissionResponse,
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


class CoretaxAuthorityAdapter(TaxAuthorityCoretaxPort):
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

    async def _request(self, method: str, path: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
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

    async def submit_tax(self, submission_type: TaxSubmissionType, data: Dict[str, Any]) -> SubmissionResponse:
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

    async def get_tax_rate(self, tax_code: str, effective_date: Optional[str] = None) -> float:
        if not effective_date:
            effective_date = datetime.now(UTC).strftime("%Y-%m-%d")
        try:
            response = await self._request("GET", "/tax-rates", params={"tax_code": tax_code, "effective_date": effective_date})
            return float(response.get("rate", 0.0))
        except Exception:
            local_rates = {"PPN": 0.11, "PPH_21": 0.05, "PPH_23": 0.02, "PPH_22": 0.015, "PPH_4_AYAT_2": 0.10, "PPH_BADAN": 0.22}
            return local_rates.get(tax_code, 0.0)

    async def validate_tax_id(self, tax_id: str) -> bool:
        if not tax_id or len(tax_id) != 15 or not tax_id.isdigit():
            return False
        try:
            response = await self._request("GET", f"/tax-ids/{tax_id}/validate")
            return response.get("valid", False)
        except Exception:
            return len(tax_id) == 15 and tax_id.isdigit()

    async def submit_faktur(self, faktur_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = await self._request("POST", "/faktur", data=faktur_data)
            return {"faktur_id": response.get("faktur_id"), "status": response.get("status", "pending"), "reference_number": response.get("reference_number")}
        except Exception as e:
            logger.error(f"Faktur submission failed: {e}")
            return {"faktur_id": str(uuid4()), "status": "failed", "error": str(e)}

    async def get_faktur_status(self, faktur_id: str) -> Dict[str, Any]:
        try:
            response = await self._request("GET", f"/faktur/{faktur_id}")
            return {"faktur_id": faktur_id, "status": response.get("status", "unknown"), "details": response.get("details")}
        except Exception as e:
            return {"faktur_id": faktur_id, "status": "unknown", "error": str(e)}

    async def submit_spt(self, spt_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = await self._request("POST", "/spt", data=spt_data)
            return {"spt_id": response.get("spt_id"), "status": response.get("status", "pending"), "reference_number": response.get("reference_number")}
        except Exception as e:
            return {"spt_id": str(uuid4()), "status": "failed", "error": str(e)}

    async def get_spt_status(self, spt_id: str) -> Dict[str, Any]:
        try:
            response = await self._request("GET", f"/spt/{spt_id}")
            return {"spt_id": spt_id, "status": response.get("status", "unknown"), "details": response.get("details")}
        except Exception as e:
            return {"spt_id": spt_id, "status": "unknown", "error": str(e)}

    async def get_notification(self) -> List[Dict[str, Any]]:
        try:
            response = await self._request("GET", "/notifications")
            return response.get("notifications", [])
        except Exception:
            return []

    async def health_check(self) -> Dict[str, Any]:
        if not self.config.enabled:
            return {"status": "healthy", "mode": "simulation", "message": "Coretax not configured"}
        try:
            await self._authenticate()
            return {"status": "healthy", "mode": "real", "base_url": self.config.base_url, "authenticated": True}
        except Exception as e:
            return {"status": "unhealthy", "mode": "real", "error": str(e)}