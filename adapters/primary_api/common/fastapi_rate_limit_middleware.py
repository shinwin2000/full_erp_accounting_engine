#!/usr/bin/env python3
"""
Module: fastapi_rate_limit_middleware.py
Layer: Adapters (Primary API - Common)
Responsibility: Middleware untuk rate limiting berbasis sliding window dengan
               backend Redis (fallback ke memory jika Redis tidak tersedia).
               Melindungi API dari abuse, DoS, dan memastikan fairness antar user.
Dependencies:
- starlette
- redis (optional, async)
- time, asyncio, hashlib
- infrastructure.caching.redis_manager
- kernel.guards.authority_matrix (untuk pengecualian berdasarkan role)
Audit: Setiap pelanggaran rate limit dicatat ke audit log (melalui AuditMiddleware).
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict, deque
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

# Internal imports
try:
    from infrastructure.caching.redis_manager import get_redis_client

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    get_redis_client = None

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class RateLimitStrategy:
    """Strategi rate limiting yang didukung."""

    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    TOKEN_BUCKET = "token_bucket"


DEFAULT_STRATEGY = RateLimitStrategy.SLIDING_WINDOW
DEFAULT_CALLS_PER_MINUTE = 60  # 60 request per menit per user (default)
DEFAULT_BURST = 10  # tambahan burst untuk token bucket

# Key prefixes untuk Redis
REDIS_PREFIX = "ratelimit:"
REDIS_SLIDING_WINDOW_PREFIX = "rl:sw:"
REDIS_FIXED_WINDOW_PREFIX = "rl:fw:"
REDIS_TOKEN_BUCKET_PREFIX = "rl:tb:"

# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================


class RateLimitExceeded(Exception):
    """Exception ketika rate limit terlampaui."""

    def __init__(self, limit: int, remaining: int, reset_time: float):
        self.limit = limit
        self.remaining = remaining
        self.reset_time = reset_time
        super().__init__(f"Rate limit exceeded. Limit: {limit}, Reset at: {reset_time}")


# ============================================================================
# RATE LIMITER BACKENDS
# ============================================================================


class SlidingWindowRateLimiter:
    """
    Implementasi sliding window rate limiter.
    Menggunakan Redis sorted set untuk menyimpan timestamp setiap request.
    Kompleksitas: O(log N) per request.
    """

    def __init__(self, redis_client: Any | None = None, fallback_to_memory: bool = True):
        self.redis = redis_client
        self.fallback_to_memory = fallback_to_memory
        self._memory_store: dict[str, deque] = defaultdict(lambda: deque())
        self._use_redis = redis_client is not None

    async def is_allowed(
        self, key: str, limit: int, window_seconds: int
    ) -> tuple[bool, int, float]:
        """
        Periksa apakah request diizinkan.
        Returns: (allowed, remaining_requests, reset_time_unix)
        """
        if self._use_redis and self.redis:
            return await self._check_redis(key, limit, window_seconds)
        elif self.fallback_to_memory:
            return self._check_memory(key, limit, window_seconds)
        else:
            # Jika tidak ada fallback, izinkan semua (tapi catat warning)
            logger.warning(
                f"Rate limiter has no backend and fallback disabled. Allowing all requests for {key}"
            )
            return True, limit - 1, time.time() + window_seconds

    async def _check_redis(
        self, key: str, limit: int, window_seconds: int
    ) -> tuple[bool, int, float]:
        """Implementasi sliding window dengan Redis sorted set."""
        now = time.time()
        window_start = now - window_seconds
        redis_key = f"{REDIS_SLIDING_WINDOW_PREFIX}{key}"

        # Gunakan pipeline untuk atomicity
        pipe = self.redis.pipeline()
        # Hapus timestamp di luar window
        pipe.zremrangebyscore(redis_key, 0, window_start)
        # Dapatkan jumlah request dalam window
        pipe.zcard(redis_key)
        # Tambahkan timestamp request sekarang
        pipe.zadd(redis_key, {str(now): now})
        # Set expiry pada key
        pipe.expire(redis_key, window_seconds + 1)
        # Eksekusi pipeline
        results = await pipe.execute()

        # Hasil: [zremrangebyscore, zcard, zadd, expire]
        current_count = results[1]

        if current_count <= limit:
            remaining = limit - current_count
            reset_time = now + window_seconds
            return True, remaining, reset_time
        else:
            # Dapatkan waktu reset (timestamp tertua dalam window)
            oldest = await self.redis.zrange(redis_key, 0, 0, withscores=True)
            if oldest:
                oldest_ts = oldest[0][1]
                reset_time = oldest_ts + window_seconds
            else:
                reset_time = now + window_seconds
            return False, 0, reset_time

    def _check_memory(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, float]:
        """Implementasi sliding window in-memory (untuk development atau fallback)."""
        now = time.time()
        window_start = now - window_seconds
        deque_store = self._memory_store[key]

        # Bersihkan timestamp di luar window
        while deque_store and deque_store[0] < window_start:
            deque_store.popleft()

        current_count = len(deque_store)
        if current_count < limit:
            deque_store.append(now)
            remaining = limit - (current_count + 1)
            reset_time = now + window_seconds
            return True, remaining, reset_time
        else:
            oldest = deque_store[0] if deque_store else now
            reset_time = oldest + window_seconds
            return False, 0, reset_time


class FixedWindowRateLimiter:
    """
    Implementasi fixed window rate limiter (sederhana, tetapi rawan burst di batas window).
    """

    def __init__(self, redis_client: Any | None = None, fallback_to_memory: bool = True):
        self.redis = redis_client
        self.fallback_to_memory = fallback_to_memory
        self._memory_store: dict[str, tuple[int, float]] = {}  # key -> (count, window_start)
        self._use_redis = redis_client is not None

    async def is_allowed(
        self, key: str, limit: int, window_seconds: int
    ) -> tuple[bool, int, float]:
        if self._use_redis and self.redis:
            return await self._check_redis(key, limit, window_seconds)
        elif self.fallback_to_memory:
            return self._check_memory(key, limit, window_seconds)
        else:
            return True, limit - 1, time.time() + window_seconds

    async def _check_redis(
        self, key: str, limit: int, window_seconds: int
    ) -> tuple[bool, int, float]:
        now = time.time()
        window_number = int(now // window_seconds)
        redis_key = f"{REDIS_FIXED_WINDOW_PREFIX}{key}:{window_number}"

        # Gunakan INCR dengan expiry
        count = await self.redis.incr(redis_key)
        if count == 1:
            await self.redis.expire(redis_key, window_seconds)

        if count <= limit:
            remaining = limit - count
            reset_time = (window_number + 1) * window_seconds
            return True, remaining, reset_time
        else:
            reset_time = (window_number + 1) * window_seconds
            return False, 0, reset_time

    def _check_memory(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, float]:
        now = time.time()
        window_number = int(now // window_seconds)
        window_start = window_number * window_seconds

        count, last_window = self._memory_store.get(key, (0, window_start))
        if last_window != window_start:
            count = 0
            last_window = window_start

        if count < limit:
            self._memory_store[key] = (count + 1, last_window)
            remaining = limit - (count + 1)
            reset_time = (window_number + 1) * window_seconds
            return True, remaining, reset_time
        else:
            reset_time = (window_number + 1) * window_seconds
            return False, 0, reset_time


class TokenBucketRateLimiter:
    """
    Token bucket algorithm: memberikan kapasitas burst.
    Setiap request mengkonsumsi token; token direfill dengan rate tertentu.
    """

    def __init__(self, redis_client: Any | None = None, fallback_to_memory: bool = True):
        self.redis = redis_client
        self.fallback_to_memory = fallback_to_memory
        self._memory_store: dict[str, dict[str, Any]] = {}
        self._use_redis = redis_client is not None

    async def is_allowed(
        self, key: str, capacity: int, refill_rate: float, refill_interval_seconds: int = 1
    ) -> tuple[bool, int, float]:
        """
        capacity: jumlah token maksimal (burst)
        refill_rate: token yang ditambahkan per interval (misal 10 token per detik)
        """
        if self._use_redis and self.redis:
            return await self._check_redis(key, capacity, refill_rate, refill_interval_seconds)
        elif self.fallback_to_memory:
            return self._check_memory(key, capacity, refill_rate, refill_interval_seconds)
        else:
            return True, capacity - 1, time.time() + refill_interval_seconds

    async def _check_redis(
        self, key: str, capacity: int, refill_rate: float, interval: int
    ) -> tuple[bool, int, float]:
        redis_key = f"{REDIS_TOKEN_BUCKET_PREFIX}{key}"
        now = time.time()

        # Lua script untuk atomic update token bucket
        lua_script = """
        local key = KEYS[1]
        local capacity = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local interval = tonumber(ARGV[3])
        local now = tonumber(ARGV[4])
        
        local bucket = redis.call('hmget', key, 'tokens', 'last_refill')
        local tokens = tonumber(bucket[1])
        local last_refill = tonumber(bucket[2])
        
        if tokens == nil then
            tokens = capacity
            last_refill = now
        else
            local elapsed = now - last_refill
            local refill = math.floor(elapsed / interval) * refill_rate
            tokens = math.min(capacity, tokens + refill)
            last_refill = last_refill + (math.floor(elapsed / interval) * interval)
        end
        
        if tokens >= 1 then
            tokens = tokens - 1
            local ttl = math.ceil(capacity / refill_rate) * interval + 5
            redis.call('hmset', key, 'tokens', tokens, 'last_refill', last_refill)
            redis.call('expire', key, ttl)
            return {1, tokens, last_refill + (capacity - tokens) / refill_rate * interval}
        else
            local reset_time = last_refill + (capacity - tokens) / refill_rate * interval
            return {0, tokens, reset_time}
        end
        """
        # Register script (cached by redis)
        script = self.redis.register_script(lua_script)
        result = await script(keys=[redis_key], args=[capacity, refill_rate, interval, now])
        allowed = result[0] == 1
        remaining = int(result[1]) if allowed else 0
        reset_time = float(result[2])
        return allowed, remaining, reset_time

    def _check_memory(
        self, key: str, capacity: int, refill_rate: float, interval: int
    ) -> tuple[bool, int, float]:
        now = time.time()
        bucket = self._memory_store.get(key, {"tokens": capacity, "last_refill": now})
        tokens = bucket["tokens"]
        last_refill = bucket["last_refill"]

        elapsed = now - last_refill
        refill = int(elapsed / interval) * refill_rate
        tokens = min(capacity, tokens + refill)
        last_refill = last_refill + int(elapsed / interval) * interval

        if tokens >= 1:
            tokens -= 1
            self._memory_store[key] = {"tokens": tokens, "last_refill": last_refill}
            reset_time = last_refill + (capacity - tokens) / refill_rate * interval
            return True, int(tokens), reset_time
        else:
            reset_time = last_refill + (capacity - tokens) / refill_rate * interval
            return False, 0, reset_time


# ============================================================================
# MAIN MIDDLEWARE CLASS
# ============================================================================


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware untuk rate limiting.

    Fitur:
    - Mendukung sliding window, fixed window, dan token bucket
    - Rate limit per user (berdasarkan user_id), per IP, atau kombinasi
    - Pengecualian untuk role tertentu (misal admin, service account)
    - Header response: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, Retry-After
    - Fallback Redis ke memory jika Redis down
    """

    def __init__(
        self,
        app,
        calls_per_minute: int = DEFAULT_CALLS_PER_MINUTE,
        calls_per_second: int = 10,  # untuk burst
        strategy: str = DEFAULT_STRATEGY,
        key_by: str = "user",  # "user", "ip", "user_ip"
        exclude_paths: list[str] | None = None,
        exclude_roles: list[str] | None = None,
        redis_client: Any | None = None,
        fallback_to_memory: bool = True,
    ):
        super().__init__(app)
        self.calls_per_minute = calls_per_minute
        self.calls_per_second = calls_per_second
        self.strategy = strategy
        self.key_by = key_by
        self.exclude_paths = set(
            exclude_paths or ["/api/health", "/api/ready", "/api/docs", "/api/openapi.json"]
        )
        self.exclude_roles = set(exclude_roles or ["admin", "system", "auditor"])

        # Inisialisasi rate limiter sesuai strategi
        self._limiter: Any = None
        self._init_limiter(redis_client, fallback_to_memory)

        # Cache untuk key generation
        self._key_cache: dict[
            str, tuple[str, float]
        ] = {}  # simple cache untuk mapping IP->user (30 detik)

    def _init_limiter(self, redis_client: Any | None, fallback: bool):
        if self.strategy == RateLimitStrategy.SLIDING_WINDOW:
            self._limiter = SlidingWindowRateLimiter(redis_client, fallback)
        elif self.strategy == RateLimitStrategy.FIXED_WINDOW:
            self._limiter = FixedWindowRateLimiter(redis_client, fallback)
        elif self.strategy == RateLimitStrategy.TOKEN_BUCKET:
            self._limiter = TokenBucketRateLimiter(redis_client, fallback)
        else:
            # Default sliding window
            self._limiter = SlidingWindowRateLimiter(redis_client, fallback)

    def _get_rate_limit_key(self, request: Request) -> str:
        """
        Menghasilkan key unik untuk rate limiting berdasarkan metode key_by.
        """
        # Jika path exclude, return None (tidak perlu rate limit)
        if request.url.path in self.exclude_paths:
            return None

        # Ekstrak identitas
        user_id = self._get_user_id(request)
        client_ip = self._get_client_ip(request)
        role = self._get_user_role(request)

        # Pengecualian berdasarkan role
        if role and role.lower() in self.exclude_roles:
            return None

        # Bangun key
        if self.key_by == "user" and user_id:
            key = f"user:{user_id}"
        elif self.key_by == "ip":
            key = f"ip:{client_ip}"
        elif self.key_by == "user_ip":
            if user_id:
                key = f"user:{user_id}:ip:{client_ip}"
            else:
                key = f"ip:{client_ip}"
        else:
            # Fallback ke IP
            key = f"ip:{client_ip}"

        # Hash key untuk keamanan dan panjang
        hashed = hashlib.sha256(key.encode()).hexdigest()[:32]
        return hashed

    def _get_user_id(self, request: Request) -> str | None:
        if hasattr(request.state, "user_id"):
            uid = request.state.user_id
            if uid:
                return str(uid)
        if hasattr(request.state, "user") and hasattr(request.state.user, "user_id"):
            return str(request.state.user.user_id)
        return None

    def _get_user_role(self, request: Request) -> str | None:
        if hasattr(request.state, "user") and hasattr(request.state.user, "roles"):
            roles = request.state.user.roles
            if roles and len(roles) > 0:
                return roles[0]
        return None

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        client = request.client
        return client.host if client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Proses rate limiting.
        """
        rate_key = self._get_rate_limit_key(request)

        # Jika tidak perlu rate limit (exclude path atau role khusus)
        if rate_key is None:
            return await call_next(request)

        # Tentukan parameter limit berdasarkan path atau user (bisa dinamis)
        limit = self.calls_per_minute
        window_seconds = 60  # 1 menit
        # Jika token bucket, capacity dan refill rate
        capacity = self.calls_per_minute
        refill_rate = self.calls_per_second

        try:
            if self.strategy == RateLimitStrategy.TOKEN_BUCKET:
                allowed, remaining, reset_time = await self._limiter.is_allowed(
                    rate_key, capacity, refill_rate, 1
                )
            else:
                # Untuk sliding/fixed window, gunakan calls_per_minute
                allowed, remaining, reset_time = await self._limiter.is_allowed(
                    rate_key, limit, window_seconds
                )

            if not allowed:
                # Rate limit exceeded
                retry_after = max(1, int(reset_time - time.time()))
                response = JSONResponse(
                    status_code=HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": "Rate limit exceeded. Please retry later.",
                        "limit": limit,
                        "remaining": remaining,
                        "reset": reset_time,
                        "retry_after": retry_after,
                    },
                    headers={
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": str(remaining),
                        "X-RateLimit-Reset": str(int(reset_time)),
                        "Retry-After": str(retry_after),
                    },
                )
                # Catat ke audit (melalui logger, nanti middleware audit akan menangkap)
                logger.warning(f"Rate limit exceeded for key {rate_key}, limit {limit}")
                return response

            # Lanjutkan request, tambahkan header rate limit di response nanti
            response = await call_next(request)
            # Tambahkan header rate limit ke response (jika response bukan streaming)
            if hasattr(response, "headers"):
                response.headers["X-RateLimit-Limit"] = str(limit)
                response.headers["X-RateLimit-Remaining"] = str(remaining)
                response.headers["X-RateLimit-Reset"] = str(int(reset_time))
            return response

        except Exception as e:
            # Jika rate limiter gagal (misal Redis down dan fallback tidak ada), jangan blok request
            logger.error(f"Rate limiter error: {e}. Allowing request without rate limiting.")
            return await call_next(request)


# ============================================================================
# HELPER FUNCTIONS FOR DEPENDENCY
# ============================================================================


async def get_redis_rate_limiter() -> Any | None:
    """Dependency untuk mendapatkan Redis client untuk rate limiting."""
    if REDIS_AVAILABLE and get_redis_client is not None:
        try:
            return await get_redis_client()
        except Exception as e:
            logger.warning(f"Failed to get Redis client for rate limiter: {e}")
    return None


def create_rate_limit_middleware(app, config: dict[str, Any]) -> RateLimitMiddleware:
    """
    Factory untuk membuat RateLimitMiddleware dengan konfigurasi.
    """
    return RateLimitMiddleware(
        app,
        calls_per_minute=config.get("rate_limit_calls_per_minute", DEFAULT_CALLS_PER_MINUTE),
        calls_per_second=config.get("rate_limit_calls_per_second", 10),
        strategy=config.get("rate_limit_strategy", DEFAULT_STRATEGY),
        key_by=config.get("rate_limit_key_by", "user"),
        exclude_paths=config.get("rate_limit_exclude_paths", []),
        exclude_roles=config.get("rate_limit_exclude_roles", ["admin"]),
        redis_client=None,  # akan di-resolve di runtime
        fallback_to_memory=config.get("rate_limit_fallback_memory", True),
    )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "FixedWindowRateLimiter",
    "RateLimitExceeded",
    "RateLimitMiddleware",
    "RateLimitStrategy",
    "SlidingWindowRateLimiter",
    "TokenBucketRateLimiter",
    "create_rate_limit_middleware",
    "get_redis_rate_limiter",
]
