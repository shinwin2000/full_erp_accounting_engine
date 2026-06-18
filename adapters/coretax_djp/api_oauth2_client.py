#!/usr/bin/env python3
"""
Module: api_oauth2_client.py
Layer: Adapters (Coretax DJP)
Responsibility: OAuth2 client untuk autentikasi ke API Coretax DJP.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import datetime
from enum import Enum
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import BaseModel, Field

from infrastructure.caching.redis_manager import get_redis_client
from infrastructure.security.vault_dynamic_secret_provider import VaultSecretProvider

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

CORETAX_CONFIG_PATH = "config_files/coretax_djp_api_config.yaml"
TOKEN_CACHE_KEY_PREFIX = "coretax:token:"
RATE_LIMIT_KEY_PREFIX = "coretax:ratelimit:"
CIRCUIT_BREAKER_KEY_PREFIX = "coretax:circuit:"

DEFAULT_TOKEN_EXPIRY_LEEWAY = 60
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_FACTOR = 2.0
DEFAULT_RETRY_STATUS_CODES = [429, 500, 502, 503, 504]

SANDBOX_BASE_URL = "https://api.sandbox.coretax.pajak.go.id/v1"
PRODUCTION_BASE_URL = "https://api.coretax.pajak.go.id/v1"
MOCK_BASE_URL = "http://localhost:8080/mock"


class Environment(str, Enum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"
    MOCK = "mock"


class GrantType(str, Enum):
    CLIENT_CREDENTIALS = "client_credentials"
    PRIVATE_KEY_JWT = "private_key_jwt"
    REFRESH_TOKEN = "refresh_token"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str | None = None
    scope: str | None = None
    issued_at: float = Field(default_factory=time.time)

    @property
    def expires_at(self) -> float:
        return self.issued_at + self.expires_in

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at - DEFAULT_TOKEN_EXPIRY_LEEWAY

    @property
    def time_to_expiry(self) -> float:
        return max(0, self.expires_at - time.time())


class RateLimitStatus(BaseModel):
    limit: int
    remaining: int
    reset_at: float
    retry_after: int | None = None


class ClientMetrics(BaseModel):
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0
    average_latency_ms: float = 0
    token_refreshes: int = 0
    token_refresh_failures: int = 0
    circuit_breaker_trips: int = 0
    last_request_time: datetime | None = None
    last_error: str | None = None


class CoretaxAuthError(Exception):
    pass


class CoretaxTokenExpired(CoretaxAuthError):
    pass


class CoretaxRateLimitError(CoretaxAuthError):
    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class CoretaxNetworkError(CoretaxAuthError):
    pass


class CoretaxCircuitBreakerOpenError(CoretaxAuthError):
    pass


class CoretaxInvalidResponseError(CoretaxAuthError):
    pass


class CircuitBreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._state_changed_at: float = time.time()

    @property
    def state(self) -> CircuitBreakerState:
        return self._state

    @property
    def is_open(self) -> bool:
        if self._state == CircuitBreakerState.OPEN:
            if time.time() - self._state_changed_at > self.recovery_timeout:
                self._transition_to_half_open()
            return self._state == CircuitBreakerState.OPEN
        return False

    def _transition_to_closed(self) -> None:
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0
        self._state_changed_at = time.time()
        logger.info(f"Circuit breaker '{self.name}' transitioned to CLOSED")

    def _transition_to_open(self) -> None:
        self._state = CircuitBreakerState.OPEN
        self._state_changed_at = time.time()
        logger.warning(
            f"Circuit breaker '{self.name}' transitioned to OPEN after {self._failure_count} failures"
        )

    def _transition_to_half_open(self) -> None:
        self._state = CircuitBreakerState.HALF_OPEN
        self._half_open_calls = 0
        self._state_changed_at = time.time()
        logger.info(f"Circuit breaker '{self.name}' transitioned to HALF_OPEN")

    def record_success(self) -> None:
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._transition_to_closed()
        elif self._state == CircuitBreakerState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._transition_to_open()
        elif self._state == CircuitBreakerState.CLOSED:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._transition_to_open()

    def can_execute(self) -> bool:
        if self._state == CircuitBreakerState.CLOSED:
            return True
        if self._state == CircuitBreakerState.OPEN:
            return False
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._half_open_calls += 1
            return self._half_open_calls <= self.half_open_max_calls
        return False


class CoretaxOAuth2Client:
    def __init__(self, env: str = "production", config: dict | None = None):
        self.env = Environment(env.lower())
        # Gunakan config yang diberikan, jika None beri dict kosong (caller wajib menyediakan)
        self._config = config or {}
        self._fallback_config = self._build_fallback_config()  # fallback jika config kosong

        self.client_id: str = ""
        self.client_secret: str = ""
        self.private_key: rsa.RSAPrivateKey | None = None
        self.private_key_id: str = ""
        self.token_endpoint: str = ""
        self.base_url: str = ""
        self.grant_type: GrantType = GrantType.PRIVATE_KEY_JWT

        self._redis = None
        self._http_client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._current_token: TokenResponse | None = None
        self._circuit_breaker = CircuitBreaker("coretax_api")
        self._metrics = ClientMetrics()
        self._rate_limit_status: dict[str, RateLimitStatus] = {}

        self._initialize_secrets_sync()
        self._initialize_client()

    def _build_fallback_config(self) -> dict[str, Any]:
        """Fallback default config jika tidak diberikan dari luar."""
        return {
            "coretax_djp": {
                "base_url": PRODUCTION_BASE_URL,
                "token_endpoint": "/oauth2/token",
                "auth_method": "private_key_jwt",
                "token_expiry_seconds": 3600,
                "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
                "retry": {
                    "max_attempts": DEFAULT_MAX_RETRIES,
                    "backoff_factor": DEFAULT_RETRY_BACKOFF_FACTOR,
                },
                "rate_limit": {
                    "enabled": True,
                    "default_limit": 1000,
                },
                "circuit_breaker": {
                    "failure_threshold": 5,
                    "recovery_timeout": 60,
                }
            }
        }

    def _get_config_section(self) -> dict[str, Any]:
        """Ambil bagian coretax_djp dari config, atau fallback jika kosong."""
        if self._config and "coretax_djp" in self._config:
            return self._config["coretax_djp"]
        return self._fallback_config["coretax_djp"]

    def _initialize_secrets_sync(self):
        """Inisialisasi parameter autentikasi secara sinkron (diadaptasi)."""
        coretax_config = self._get_config_section()
        base_url = coretax_config.get("base_url", PRODUCTION_BASE_URL)
        if self.env == Environment.SANDBOX:
            base_url = coretax_config.get("sandbox_base_url", SANDBOX_BASE_URL)
        elif self.env == Environment.MOCK:
            base_url = coretax_config.get("mock_base_url", MOCK_BASE_URL)

        token_path = coretax_config.get("token_endpoint", "/oauth2/token")
        self.token_endpoint = urljoin(base_url, token_path)
        self.base_url = base_url

        # Load dari Vault atau env
        try:
            # Kita panggil sync? Sebaiknya kita buat async terpisah, tapi untuk sederhana kita baca dari env
            import os
            self.client_id = os.environ.get("CORETAX_CLIENT_ID", "")
            self.client_secret = os.environ.get("CORETAX_CLIENT_SECRET", "")
            private_key_pem = os.environ.get("CORETAX_PRIVATE_KEY", "")
            self.private_key_id = os.environ.get("CORETAX_KID", "")
            if private_key_pem:
                self.private_key = serialization.load_pem_private_key(
                    private_key_pem.encode(), password=None, backend=default_backend()
                )
        except Exception as e:
            logger.warning("Could not load Coretax credentials from env: %s", type(e).__name__)

        # Catatan: VaultSecretProvider tetap async, kita tidak panggil di sini.
        # Untuk production, sebaiknya gunakan factory async.

    def _initialize_client(self):
        cb_config = self._get_config_section().get("circuit_breaker", {})
        self._circuit_breaker = CircuitBreaker(
            name="coretax_api",
            failure_threshold=cb_config.get("failure_threshold", 5),
            recovery_timeout=cb_config.get("recovery_timeout", 60.0),
        )

    async def _get_redis(self):
        if self._redis is None:
            self._redis = await get_redis_client()
        return self._redis

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            timeout = self._get_config_section().get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
            self._http_client = httpx.AsyncClient(timeout=timeout, limits=limits)
        return self._http_client

    async def close(self):
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    def _generate_client_assertion(self) -> str:
        now = int(time.time())
        payload = {
            "iss": self.client_id,
            "sub": self.client_id,
            "aud": self.token_endpoint,
            "iat": now,
            "exp": now + 300,
            "jti": f"{self.client_id}-{now}-{uuid4().hex[:8]}",
        }
        headers = {"typ": "JWT", "alg": "RS256"}
        if self.private_key_id:
            headers["kid"] = self.private_key_id

        if self.private_key is None:
            raise CoretaxAuthError("Private key not configured")

        token = jwt.encode(payload, self.private_key, algorithm="RS256", headers=headers)
        return token

    async def _fetch_new_token(self) -> TokenResponse:
        client_assertion = self._generate_client_assertion()

        if self.grant_type == GrantType.PRIVATE_KEY_JWT:
            data = {
                "grant_type": "client_credentials",
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": client_assertion,
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }
        else:
            auth_header = base64.b64encode(
                f"{self.client_id}:{self.client_secret}".encode()
            ).decode()
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Authorization": f"Basic {auth_header}",
            }
            data = {"grant_type": "client_credentials"}

        client = await self._get_http_client()
        retry_config = self._get_config_section().get("retry", {})
        max_retries = retry_config.get("max_attempts", DEFAULT_MAX_RETRIES)
        backoff = retry_config.get("backoff_factor", DEFAULT_RETRY_BACKOFF_FACTOR)

        for attempt in range(max_retries):
            try:
                response = await client.post(self.token_endpoint, data=data, headers=headers)

                if response.status_code == 200:
                    token_data = response.json()
                    token_response = TokenResponse(
                        access_token=token_data.get("access_token"),
                        expires_in=token_data.get("expires_in", 3600),
                        refresh_token=token_data.get("refresh_token"),
                        scope=token_data.get("scope"),
                    )
                    logger.info("Coretax OAuth2 session obtained successfully")
                    self._metrics.token_refreshes += 1
                    return token_response

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise CoretaxRateLimitError(
                        f"Rate limited: HTTP {response.status_code}", retry_after
                    )

                logger.warning(
                    f"Auth request failed (attempt {attempt + 1}): HTTP {response.status_code}"
                )
                if attempt == max_retries - 1:
                    raise CoretaxAuthError(f"Failed to get auth session: HTTP {response.status_code}")
                await asyncio.sleep(backoff * (2**attempt))

            except CoretaxRateLimitError:
                raise
            except httpx.RequestError as e:
                logger.warning(
                    f"Network error during auth request (attempt {attempt + 1}): {type(e).__name__}"
                )
                if attempt == max_retries - 1:
                    raise CoretaxNetworkError(f"Network error after retries: {type(e).__name__}")
                await asyncio.sleep(backoff * (2**attempt))
            except Exception as e:
                logger.warning(
                    f"Unexpected error during auth request (attempt {attempt + 1}): {type(e).__name__}"
                )
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(backoff * (2**attempt))

        raise CoretaxAuthError("Maximum retries exceeded")

    async def get_access_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._current_token and not self._current_token.is_expired:
            return self._current_token.access_token

        cache_key = f"{TOKEN_CACHE_KEY_PREFIX}{self.client_id}"
        redis = await self._get_redis()

        if not force_refresh:
            try:
                cached = await redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    token_response = TokenResponse(**data)
                    if not token_response.is_expired:
                        self._current_token = token_response
                        return token_response.access_token
            except Exception as e:
                logger.warning(f"Redis cache read failed: {type(e).__name__}")

        async with self._lock:
            if not force_refresh:
                try:
                    cached = await redis.get(cache_key)
                    if cached:
                        data = json.loads(cached)
                        token_response = TokenResponse(**data)
                        if not token_response.is_expired:
                            self._current_token = token_response
                            return token_response.access_token
                except Exception:
                    pass

            token_response = await self._fetch_new_token()
            self._current_token = token_response

            try:
                ttl = token_response.expires_in - DEFAULT_TOKEN_EXPIRY_LEEWAY
                await redis.setex(cache_key, max(ttl, 60), json.dumps(token_response.dict()))
            except Exception as e:
                logger.warning(f"Redis cache write failed: {type(e).__name__}")

            logger.info("Coretax access session cached")
            return token_response.access_token

    async def refresh_token(self) -> str:
        return await self.get_access_token(force_refresh=True)

    async def invalidate_token(self):
        self._current_token = None
        redis = await self._get_redis()
        cache_key = f"{TOKEN_CACHE_KEY_PREFIX}{self.client_id}"
        await redis.delete(cache_key)
        logger.info("Coretax auth session invalidated")

    async def is_token_valid(self) -> bool:
        if not self._current_token:
            return False
        return not self._current_token.is_expired

    async def get_token_expiry(self) -> float | None:
        if self._current_token:
            return self._current_token.expires_at
        return None

    async def clear_cache(self):
        self._current_token = None
        redis = await self._get_redis()
        cache_key = f"{TOKEN_CACHE_KEY_PREFIX}{self.client_id}"
        await redis.delete(cache_key)
        logger.info("Coretax auth session cache cleared")

    async def _update_rate_limit(self, response: httpx.Response):
        limit = response.headers.get("X-RateLimit-Limit")
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        retry_after = response.headers.get("Retry-After")

        if limit and remaining:
            status = RateLimitStatus(
                limit=int(limit),
                remaining=int(remaining),
                reset_at=float(reset) if reset else time.time() + 60,
                retry_after=int(retry_after) if retry_after else None,
            )
            endpoint = str(response.request.url)
            self._rate_limit_status[endpoint] = status

    async def _handle_retry(
        self,
        attempt: int,
        max_retries: int,
        backoff: float,
        exception: Exception,
    ) -> bool:
        if attempt >= max_retries - 1:
            return False
        wait_time = backoff * (2**attempt)
        logger.warning(
            f"Request failed (attempt {attempt + 1}/{max_retries}): {type(exception).__name__}. Retrying in {wait_time}s"
        )
        await asyncio.sleep(wait_time)
        return True

    async def _record_metrics(self, success: bool, latency_ms: float, error: str | None = None):
        self._metrics.total_requests += 1
        if success:
            self._metrics.successful_requests += 1
        else:
            self._metrics.failed_requests += 1

        self._metrics.total_latency_ms += latency_ms
        self._metrics.average_latency_ms = (
            self._metrics.total_latency_ms / self._metrics.total_requests
        )
        self._metrics.last_request_time = datetime.now()
        if error:
            if error and ("Bearer" in error or "access_token" in error or "secret" in error):
                error = "Sensitive error suppressed"
            self._metrics.last_error = error

    async def request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        headers: dict | None = None,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        start_time = time.time()

        if not self._circuit_breaker.can_execute():
            self._circuit_breaker.record_failure()
            raise CoretaxCircuitBreakerOpenError("Circuit breaker is open")

        url = f"{self.base_url}{endpoint}"
        token = await self.get_access_token()

        default_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ERP-Accounting-Engine/1.0",
        }
        if headers:
            default_headers.update(headers)

        client = await self._get_http_client()
        retry_config = self._get_config_section().get("retry", {})
        max_retries = retry_config.get("max_attempts", DEFAULT_MAX_RETRIES)
        backoff = retry_config.get("backoff_factor", DEFAULT_RETRY_BACKOFF_FACTOR)

        for attempt in range(max_retries):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    json=data if method in ("POST", "PUT", "PATCH") else None,
                    params=data if method == "GET" else None,
                    headers=default_headers,
                )

                await self._update_rate_limit(response)

                if response.status_code == 401 and retry_auth:
                    logger.warning("Received 401 from Coretax, refreshing auth session...")
                    await self.invalidate_token()
                    token = await self.get_access_token(force_refresh=True)
                    default_headers["Authorization"] = f"Bearer {token}"
                    continue

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise CoretaxRateLimitError("Rate limited: HTTP 429", retry_after)

                if response.status_code >= 400:
                    sanitized_endpoint = endpoint.split("?")[0]
                    logger.error(
                        f"Coretax API error: HTTP {response.status_code} for {method} {sanitized_endpoint}"
                    )
                    if 400 <= response.status_code < 500 and response.status_code != 401:
                        self._circuit_breaker.record_failure()
                        raise CoretaxAuthError(f"API error HTTP {response.status_code}")

                    if attempt == max_retries - 1:
                        self._circuit_breaker.record_failure()
                        raise CoretaxAuthError(
                            f"API error after retries: HTTP {response.status_code}"
                        )

                    await asyncio.sleep(backoff * (2**attempt))
                    continue

                self._circuit_breaker.record_success()
                latency_ms = (time.time() - start_time) * 1000
                await self._record_metrics(True, latency_ms)

                if response.status_code == 204:
                    return {}

                return response.json()

            except CoretaxRateLimitError as e:
                latency_ms = (time.time() - start_time) * 1000
                await self._record_metrics(False, latency_ms, "Rate limit error")
                if attempt == max_retries - 1:
                    self._circuit_breaker.record_failure()
                    raise
                await asyncio.sleep(e.retry_after or backoff * (2**attempt))
                continue

            except httpx.RequestError as e:
                latency_ms = (time.time() - start_time) * 1000
                await self._record_metrics(False, latency_ms, type(e).__name__)
                if await self._handle_retry(attempt, max_retries, backoff, e):
                    continue
                self._circuit_breaker.record_failure()
                raise CoretaxNetworkError(f"Network error after retries: {type(e).__name__}")

            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                await self._record_metrics(False, latency_ms, type(e).__name__)
                if attempt == max_retries - 1:
                    self._circuit_breaker.record_failure()
                    raise
                logger.warning(f"Request failed (attempt {attempt + 1}): {type(e).__name__}")
                await asyncio.sleep(backoff * (2**attempt))
                continue

        self._circuit_breaker.record_failure()
        raise CoretaxAuthError("Max retries exceeded")

    async def get(self, endpoint: str, params: dict | None = None) -> dict[str, Any]:
        return await self.request("GET", endpoint, data=params)

    async def post(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", endpoint, data=data)

    async def put(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PUT", endpoint, data=data)

    async def patch(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PATCH", endpoint, data=data)

    async def delete(self, endpoint: str) -> dict[str, Any]:
        return await self.request("DELETE", endpoint)

    async def get_rate_limit_status(self, endpoint: str | None = None) -> dict[str, Any]:
        if endpoint:
            status = self._rate_limit_status.get(endpoint)
            return status.dict() if status else {}
        return {ep: s.dict() for ep, s in self._rate_limit_status.items()}

    async def get_metrics(self) -> dict[str, Any]:
        return {
            "total_requests": self._metrics.total_requests,
            "successful_requests": self._metrics.successful_requests,
            "failed_requests": self._metrics.failed_requests,
            "success_rate": self._metrics.successful_requests
            / max(1, self._metrics.total_requests),
            "average_latency_ms": self._metrics.average_latency_ms,
            "token_refreshes": self._metrics.token_refreshes,
            "token_refresh_failures": self._metrics.token_refresh_failures,
            "circuit_breaker_trips": self._metrics.circuit_breaker_trips,
            "circuit_breaker_state": self._circuit_breaker.state.value,
            "last_request_time": self._metrics.last_request_time.isoformat()
            if self._metrics.last_request_time
            else None,
            "last_error": self._metrics.last_error,
        }

    async def health_check(self) -> dict[str, Any]:
        start_time = time.time()
        try:
            token = await self.get_access_token()
            latency_ms = (time.time() - start_time) * 1000
            return {
                "status": "healthy",
                "token_valid": bool(token),
                "latency_ms": latency_ms,
                "circuit_breaker_state": self._circuit_breaker.state.value,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": type(e).__name__,
                "circuit_breaker_state": self._circuit_breaker.state.value,
            }

    async def set_timeout(self, timeout_seconds: float):
        if self._http_client:
            self._http_client.timeout = timeout_seconds
        else:
            self._config["coretax_djp"]["timeout_seconds"] = timeout_seconds

    async def set_retry_policy(self, max_attempts: int, backoff_factor: float):
        self._config["coretax_djp"]["retry"] = {
            "max_attempts": max_attempts,
            "backoff_factor": backoff_factor,
        }

    async def reset_circuit_breaker(self):
        self._circuit_breaker = CircuitBreaker(
            name="coretax_api",
            failure_threshold=self._circuit_breaker.failure_threshold,
            recovery_timeout=self._circuit_breaker.recovery_timeout,
        )
        logger.info("Circuit breaker reset")


_core_client: CoretaxOAuth2Client | None = None


async def get_coretax_client(env: str = "production", config: dict | None = None) -> CoretaxOAuth2Client:
    global _core_client
    if _core_client is None:
        _core_client = CoretaxOAuth2Client(env=env, config=config)
    return _core_client


async def close_coretax_client():
    global _core_client
    if _core_client:
        await _core_client.close()
        _core_client = None


async def reset_coretax_client():
    global _core_client
    if _core_client:
        await _core_client.close()
    _core_client = None


async def get_coretax_api():
    client = await get_coretax_client()
    try:
        yield client
    finally:
        pass


CoreTaxOAuth2Client = CoretaxOAuth2Client

__all__ = [
    "ClientMetrics",
    "CoreTaxOAuth2Client",
    "CoretaxAuthError",
    "CoretaxCircuitBreakerOpenError",
    "CoretaxInvalidResponseError",
    "CoretaxNetworkError",
    "CoretaxOAuth2Client",
    "CoretaxRateLimitError",
    "CoretaxTokenExpired",
    "Environment",
    "GrantType",
    "RateLimitStatus",
    "TokenResponse",
    "close_coretax_client",
    "get_coretax_api",
    "get_coretax_client",
    "reset_coretax_client",
]