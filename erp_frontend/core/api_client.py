"""
core/api_client.py
===================
Klien HTTP sinkron untuk Sovereign ERP Accounting Engine REST API.
Didesain untuk dijalankan di dalam worker thread (lihat core/workers.py)
agar UI thread PySide6 tidak pernah blocking.

Semua endpoint backend berada di bawah prefix /api/v1/{module}, contoh:
    /api/v1/journals, /api/v1/coa, /api/v1/ar, /api/v1/ap, dst.

Autentikasi: Bearer JWT (access_token). legal_entity_id sudah ter-embed
di dalam token saat login, jadi tidak perlu header tambahan.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

import requests

from core.config import settings
from core.session import session

logger = logging.getLogger("erp_frontend.api")


class ApiError(Exception):
    """Error terstruktur dari API (mencakup status code & detail)."""

    def __init__(self, status_code: int, detail: Any, url: str = ""):
        self.status_code = status_code
        self.detail = detail
        self.url = url
        super().__init__(self.human_message())

    def human_message(self) -> str:
        if isinstance(self.detail, str):
            msg = self.detail
        elif isinstance(self.detail, list):
            # FastAPI/Pydantic validation error format
            parts = []
            for item in self.detail:
                if isinstance(item, dict):
                    loc = ".".join(str(x) for x in item.get("loc", []) if x != "body")
                    parts.append(f"{loc}: {item.get('msg', item)}")
                else:
                    parts.append(str(item))
            msg = "; ".join(parts) if parts else str(self.detail)
        elif isinstance(self.detail, dict):
            msg = self.detail.get("detail") or self.detail.get("message") or str(self.detail)
        else:
            msg = str(self.detail)
        return f"[{self.status_code}] {msg}"


class ConnectionFailedError(Exception):
    """Server tidak bisa dihubungi sama sekali (network/DNS/timeout)."""


class AuthRequiredError(Exception):
    """Sesi habis dan refresh token gagal — user harus login ulang."""


class ApiClient:
    """
    Wrapper tipis di atas `requests`. Thread-safe untuk penggunaan dari
    banyak worker thread sekaligus (satu instance global `api_client`).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._http = requests.Session()

    # ------------------------------------------------------------------
    @property
    def base_url(self) -> str:
        return settings.api_base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if session.access_token:
            headers["Authorization"] = f"Bearer {session.access_token}"
        return headers

    # ------------------------------------------------------------------
    def _ensure_fresh_token(self) -> None:
        """Refresh access token proaktif jika hampir kadaluarsa."""
        if not session.refresh_token:
            return
        if session.is_token_expiring:
            self.refresh_token()

    def refresh_token(self) -> None:
        with self._lock:
            if not session.refresh_token:
                raise AuthRequiredError("Tidak ada refresh token tersimpan.")
            try:
                resp = self._http.post(
                    f"{self.base_url}/iam/refresh",
                    json={"refresh_token": session.refresh_token},
                    timeout=settings.request_timeout,
                    verify=settings.verify_ssl,
                )
            except requests.exceptions.RequestException as exc:
                raise ConnectionFailedError(str(exc)) from exc
            if resp.status_code >= 400:
                session.clear()
                raise AuthRequiredError("Sesi berakhir, silakan login kembali.")
            session.apply_refresh_response(resp.json())

    # ------------------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        retry_on_401: bool = True,
        raw: bool = False,
    ) -> Any:
        """
        Melakukan satu request HTTP. `path` boleh berupa path relatif
        (mis. "/journals/") atau path absolut yang sudah diawali '/api/v1'.
        """
        if session.access_token:
            self._ensure_fresh_token()

        url = path if path.startswith("http") else f"{self.base_url}{path}"
        try:
            resp = self._http.request(
                method=method.upper(),
                url=url,
                params=params,
                json=json_body,
                headers=self._headers(),
                timeout=settings.request_timeout,
                verify=settings.verify_ssl,
            )
        except requests.exceptions.RequestException as exc:
            logger.error("Connection failed: %s %s -> %s", method, url, exc)
            raise ConnectionFailedError(
                f"Tidak dapat terhubung ke server ({self.base_url}).\nDetail: {exc}"
            ) from exc

        if resp.status_code == 401 and retry_on_401 and session.refresh_token:
            try:
                self.refresh_token()
            except AuthRequiredError:
                raise
            return self.request(method, path, params, json_body, retry_on_401=False, raw=raw)

        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text or resp.reason
            raise ApiError(resp.status_code, detail, url=url)

        if raw:
            return resp
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # ------------------------------------------------------------------
    # Shortcut methods
    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json_body: Optional[Any] = None, params: Optional[dict[str, Any]] = None) -> Any:
        return self.request("POST", path, params=params, json_body=json_body)

    def put(self, path: str, json_body: Optional[Any] = None) -> Any:
        return self.request("PUT", path, json_body=json_body)

    def patch(self, path: str, json_body: Optional[Any] = None) -> Any:
        return self.request("PATCH", path, json_body=json_body)

    def delete(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        return self.request("DELETE", path, params=params)

    # ------------------------------------------------------------------
    def login(
        self,
        username: str,
        password: str,
        mfa_code: Optional[str] = None,
        legal_entity_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = {"username": username, "password": password}
        if mfa_code:
            body["mfa_code"] = mfa_code
        if legal_entity_id:
            body["legal_entity_id"] = legal_entity_id
        data = self.request("POST", "/iam/login", json_body=body, retry_on_401=False)
        session.apply_login_response(data)
        return data

    def logout(self) -> None:
        try:
            if session.access_token:
                self.request("POST", "/iam/logout", retry_on_401=False)
        except (ApiError, ConnectionFailedError):
            pass
        finally:
            session.clear()

    def check_connection(self) -> bool:
        try:
            self._http.get(f"{self.base_url.rsplit('/api', 1)[0]}/", timeout=5)
            return True
        except requests.exceptions.RequestException:
            return False


# Instance global — dipakai di seluruh aplikasi
api_client = ApiClient()
