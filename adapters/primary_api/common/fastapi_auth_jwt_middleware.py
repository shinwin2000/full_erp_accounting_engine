#!/usr/bin/env python3
"""
Module: fastapi_auth_jwt_middleware.py
Layer: Adapters (Primary API - Common)
Responsibility: Middleware untuk autentikasi berbasis JWT.

Changelog v16 (2026-10-16):
    - FIX CRITICAL: default `public_paths` sekarang mencakup prefix
      `/api/v1/iam/iam/login` supaya login endpoint tidak perlu auth.
    - FIX: `TokenPayload.has_permission()` sekarang mengenali wildcard
      `*:*` dan `resource:*` langsung (tanpa harus fallback ke
      has_permission_wildcard).
    - FIX: tambahkan helper `install_jwt_middleware(app, ...)` agar
      middleware bisa dipasang dengan mudah dan konsisten.
    - FIX: logging lebih detail di `dispatch()` untuk debug 401/403.
    - FIX: `_check_rbac()` sekarang log path/resource/action saat skip.
    - FIX: `get_current_user()` tidak lagi raise 401 tanpa log warning.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

try:
    from application.service_layer.service_iam import IAMService
except ImportError as e:
    logging.critical(f"Failed to import IAMService: {e}")
    raise

try:
    from infrastructure.caching.redis_manager import get_redis_client
except ImportError as e:
    logging.critical(f"Failed to import redis_manager: {e}")
    raise

try:
    from infrastructure.security.jwt_revocation_list import JWTRevocationList
except ImportError as e:
    logging.critical(f"Failed to import JWTRevocationList: {e}")
    raise

try:
    from infrastructure.security.rbac_enforcer_unified import RBACEnforcer
except ImportError as e:
    logging.critical(f"Failed to import RBACEnforcer: {e}")
    raise

try:
    from kernel.guards.authority_matrix import AuthorityMatrix
    from kernel.guards.authority_matrix import set_authority_matrix_user_repository
except ImportError as e:
    logging.critical(f"Failed to import AuthorityMatrix: {e}")
    raise

try:
    from ports.primary.iam_user_repository_port import IAMUserRepositoryPort
except ImportError as e:
    logging.critical(f"Failed to import IAMUserRepositoryPort: {e}")
    raise

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class TokenType:
    ACCESS = "access"
    REFRESH = "refresh"


DEFAULT_ALGORITHM = "RS256"
DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 15
DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS = 7


# ============================================================================
# DEFAULT PUBLIC PATHS
# ============================================================================

# FIX v16: tambahkan semua endpoint login, health, docs, dan metrics.
# Endpoint dengan prefix `/api/v1/iam/iam/login` sekarang public.
DEFAULT_PUBLIC_PATHS: list[str] = [
    "/",
    "/metrics",
    "/api/health",
    "/api/ready",
    "/api/docs",
    "/api/openapi.json",
    "/api/redoc",
    # IAM login (dengan prefix DOBEL karena router mount /api/v1/iam
    # dan decorator internal /iam)
    "/api/v1/iam/iam/login",
    "/api/v1/iam/iam/refresh",
    "/api/v1/iam/iam/logout",
    "/api/v1/iam/iam/login-options",
    # Auth (alternatif)
    "/api/auth/login",
    "/api/auth/refresh",
    # Health probes
    "/health",
    "/healthz",
    "/ready",
    "/readiness",
    "/liveness",
]


# ============================================================================
# PATH -> RESOURCE MAPPING
# ============================================================================

RESOURCE_PATH_MAP: dict[str, str] = {
    "ap": "ap",
    "ar": "ar",
    "approval": "approval",
    "bank-cash": "bank_cash",
    "budget": "budget",
    "coa": "coa",
    "hedge": "hedge",
    "currency-exchange": "currency_exchange",
    "iam": "iam",
    "goodwill": "goodwill",
    "documents": "document",
    "fixed-assets": "fixed_asset",
    "forex": "forex",
    "legal-entities": "legal_entity",
    "intangible-assets": "intangible_asset",
    "audit": "audit",
    "tax": "tax",
    "projects": "project",
    "purchase-sales": "purchase_sales",
    "inventory": "inventory",
    "maintenance": "maintenance",
    "reports": "report",
    "umkm": "umkm",
    "journals": "journal",
    "settings": "settings",
    "ledger": "ledger",
    "consolidation": "consolidation",
    "manufacturing": "manufacturing",
    "payroll": "payroll",
    "capital": "capital",
    "suppliers": "supplier",
    "employees": "employee",
    "customers": "customer",
    "payments": "payment",
    "fiscal-periods": "fiscal_period",
    "invoices": "invoice",
    "journal-entries": "journal",
    "journal": "journal",
    "purchase-orders": "purchase_sales",
    "accounts": "account",
    "users": "user",
    "roles": "role",
}


# ============================================================================
# ACTION OVERRIDES (permission halus per endpoint)
# ============================================================================

ACTION_OVERRIDES: list[tuple[str, re.Pattern[str], str]] = [
    (m, re.compile(rx), act)
    for m, rx, act in (
        # --- Customer ---
        ("GET", r"^/api/v1/customers/customers/export/?$", "export"),
        ("GET", r"^/api/v1/customers/customers/stats/?$", "read"),
        ("POST", r"^/api/v1/customers/customers/[^/]+/credit-limit/?$", "approve"),
        ("POST", r"^/api/v1/customers/customers/[^/]+/balance/?$", "post"),
        ("POST", r"^/api/v1/customers/customers/[^/]+/(activate|deactivate|block)/?$", "update"),
        ("POST", r"^/api/v1/customers/customers/bulk-update-status/?$", "update"),
        ("POST", r"^/api/v1/customers/customers/bulk-delete/?$", "delete"),
        # --- Supplier ---
        ("GET", r"^/api/v1/suppliers/export/?$", "export"),
        ("POST", r"^/api/v1/suppliers/import/?$", "import"),
        ("POST", r"^/api/v1/suppliers/suppliers/[^/]+/(activate|deactivate|status)/?$", "update"),
        ("POST", r"^/api/v1/suppliers/suppliers/[^/]+/withholding-category/?$", "approve"),
        # --- Employee ---
        ("POST", r"^/api/v1/employees/employees/import/?$", "import"),
        ("POST", r"^/api/v1/employees/employees/[^/]+/(activate|deactivate)/?$", "update"),
        ("POST", r"^/api/v1/employees/employees/[^/]+/(salary-structure|bpjs|ptkp|resign)/?$", "approve"),
        ("POST", r"^/api/v1/employees/employees/[^/]+/(photo|dependents|documents)/?$", "update"),
        # --- Manufacturing (FIX v16) ---
        ("POST", r"^/api/v1/manufacturing/manufacturing/cost-cards/?$", "create"),
        ("GET", r"^/api/v1/manufacturing/manufacturing/cost-cards/?$", "read"),
        ("POST", r"^/api/v1/manufacturing/manufacturing/work-orders/?$", "create"),
        ("GET", r"^/api/v1/manufacturing/manufacturing/work-orders/?$", "read"),
        ("POST", r"^/api/v1/manufacturing/manufacturing/bom/?$", "create"),
        ("GET", r"^/api/v1/manufacturing/manufacturing/bom/?$", "read"),
    )
]


# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================


class JWTAuthError(Exception):
    pass


class TokenExpiredError(JWTAuthError):
    pass


class InvalidTokenError(JWTAuthError):
    pass


class TokenRevokedError(JWTAuthError):
    pass


class InsufficientPermissionError(JWTAuthError):
    pass


# ============================================================================
# TOKEN PAYLOAD
# ============================================================================


class TokenPayload:
    __slots__ = (
        "device_id", "exp", "iat", "jti", "legal_entity_id",
        "permissions", "roles", "token_type", "user_id", "username",
    )

    def __init__(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID,
        roles: list[str],
        permissions: list[str],
        token_type: str,
        exp: datetime,
        iat: datetime,
        jti: str,
        device_id: str | None = None,
    ):
        self.user_id = user_id
        self.username = username
        self.legal_entity_id = legal_entity_id
        self.roles = roles
        self.permissions = permissions
        self.token_type = token_type
        self.exp = exp
        self.iat = iat
        self.jti = jti
        self.device_id = device_id

    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.exp

    def has_permission(self, permission: str) -> bool:
        """
        FIX v16: Kenali wildcard langsung:
        - "*:*" → selalu True
        - "resource:*" → True untuk semua action pada resource
        - "*:action" → True untuk action pada semua resource
        - "resource:action" → exact match
        """
        if permission in self.permissions:
            return True
        if "*:*" in self.permissions:
            return True
        if ":" in permission:
            resource, action = permission.split(":", 1)
            for perm in self.permissions:
                if ":" not in perm:
                    continue
                p_res, p_act = perm.split(":", 1)
                if p_act == "*" and p_res == resource:
                    return True
                if p_res == "*" and p_act == action:
                    return True
        return False

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_permission_wildcard(
        self, resource: str | None, action: str | None
    ) -> bool:
        if not resource and not action:
            return True
        for perm in self.permissions:
            if perm == "*:*":
                return True
            if ":" not in perm:
                continue
            p_res, p_act = perm.split(":", 1)
            if p_act == "*" and resource and p_res == resource:
                return True
            if p_res == "*" and action and p_act == action:
                return True
            if resource and action and p_res == resource and p_act == action:
                return True
        return False


# ============================================================================
# MAIN MIDDLEWARE CLASS
# ============================================================================


class JWTAuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        public_paths: list[str] | None = None,
        auth_exceptions: list[str] | None = None,
        rbac_enabled: bool = True,
        revocation_check: bool = True,
    ):
        super().__init__(app)
        # FIX v16: gunakan DEFAULT_PUBLIC_PATHS + extra dari argumen
        combined = list(DEFAULT_PUBLIC_PATHS)
        if public_paths:
            combined.extend(public_paths)
        self.public_paths = set(combined)

        # Normalisasi: hilangkan trailing slash agar prefix matching konsisten
        self.public_paths = {
            p.rstrip("/") if p != "/" else p for p in self.public_paths
        }
        self.auth_exceptions = set(auth_exceptions or [])
        self.rbac_enabled = rbac_enabled
        self.revocation_check = revocation_check

        self._revocation_list: JWTRevocationList | None = None
        self._rbac_enforcer: RBACEnforcer | None = None
        self._authority_matrix: AuthorityMatrix | None = None
        self._iam_service: IAMService | None = None
        self._authority_matrix_wired = False
        self._authority_matrix_available = False

        self.public_key = self._load_public_key()
        self.private_key = self._load_private_key()
        self.algorithm = DEFAULT_ALGORITHM
        self.access_expire = timedelta(minutes=DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES)
        self.refresh_expire = timedelta(days=DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS)

        logger.info(
            "JWTAuthMiddleware initialized (public_paths=%d, rbac=%s, revocation=%s)",
            len(self.public_paths), rbac_enabled, revocation_check,
        )

    def _load_public_key(self) -> str:
        key_path = os.getenv("JWT_PUBLIC_KEY_PATH", "/secrets/jwt_public.pem")
        try:
            with open(key_path) as f:
                return f.read()
        except Exception as e:
            logger.warning(
                "Could not load public authentication material via path %s: %s",
                key_path, type(e).__name__,
            )
            return os.getenv("JWT_PUBLIC_KEY", "fallback-public-key-do-not-use-in-prod")

    def _load_private_key(self) -> str:
        key_path = os.getenv("JWT_PRIVATE_KEY_PATH", "/secrets/jwt_private.pem")
        try:
            with open(key_path) as f:
                return f.read()
        except Exception as e:
            logger.warning(
                "Could not load private authentication material via path %s: %s",
                key_path, type(e).__name__,
            )
            return os.getenv("JWT_PRIVATE_KEY", "fallback-private-key-do-not-use-in-prod")

    def _is_public_path(self, path: str) -> bool:
        """PREFIX-AWARE match untuk public_paths."""
        if path == "/":
            return True
        normalized = path.rstrip("/") if path != "/" else path
        if normalized in self.public_paths:
            return True
        for public in self.public_paths:
            if public == "/":
                continue
            if normalized.startswith(public + "/"):
                return True
        return False

    async def _get_revocation_list(self) -> JWTRevocationList:
        if self._revocation_list is None:
            redis_client = await get_redis_client()
            self._revocation_list = JWTRevocationList(redis_client)
        return self._revocation_list

    async def _ensure_authority_matrix_wired(self) -> None:
        if self._authority_matrix_wired:
            return
        try:
            mod = importlib.import_module("bootstrap.dependency_container.ioc_container")
            get_container = mod.get_container
            container = get_container()
            user_repo = await container.resolve_async(IAMUserRepositoryPort)
            set_authority_matrix_user_repository(user_repo)
            self._authority_matrix_wired = True
            self._authority_matrix_available = True
        except Exception as e:
            logger.warning(
                "Tidak bisa wiring user repository asli ke AuthorityMatrix "
                "guard (authority matrix akan di-skip, RBAC enforcer tetap "
                "dipakai): %s", type(e).__name__,
            )
            self._authority_matrix_available = False

    async def _get_rbac_enforcer(self) -> RBACEnforcer:
        if self._rbac_enforcer is None:
            self._authority_matrix = AuthorityMatrix()
            self._rbac_enforcer = RBACEnforcer(self._authority_matrix)
        return self._rbac_enforcer

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        method = request.method

        # Skip public paths
        if self._is_public_path(path) or path in self.auth_exceptions:
            logger.debug("Public path dilewati dari JWT auth: %s %s", method, path)
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning(
                "Authentication failed: missing or invalid Authorization header "
                "(path=%s method=%s)",
                path, method,
            )
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={
                    "detail": "Missing or invalid Authorization header. "
                              "Expected 'Bearer <token>'"
                },
            )

        token = auth_header[7:]

        try:
            payload = await self._verify_token(token, token_type=TokenType.ACCESS)

            request.state.user = payload
            request.state.user_id = payload.user_id
            request.state.legal_entity_id = payload.legal_entity_id
            request.state.roles = payload.roles
            request.state.permissions = payload.permissions

            if self.rbac_enabled:
                await self._check_rbac(request, payload)

            return await call_next(request)

        except TokenExpiredError:
            logger.warning("Authentication failed: expired (path=%s)", path)
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication expired", "code": "auth_expired"},
            )
        except TokenRevokedError:
            logger.warning("Authentication failed: revoked (path=%s)", path)
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication revoked", "code": "auth_revoked"},
            )
        except InvalidTokenError as e:
            logger.warning("Authentication failed: invalid (%s) path=%s", e, path)
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid authentication", "code": "auth_invalid"},
            )
        except InsufficientPermissionError as e:
            logger.warning("Authorization failed: %s (path=%s)", e, path)
            return JSONResponse(
                status_code=HTTP_403_FORBIDDEN,
                content={"detail": str(e), "code": "insufficient_permission"},
            )
        except jwt.PyJWTError as e:
            logger.warning("JWT decoding error: %s (path=%s)", type(e).__name__, path)
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication validation failed", "code": "jwt_error"},
            )
        except Exception as e:
            logger.exception(
                "Unexpected error in authentication middleware: %s (path=%s)",
                type(e).__name__, path,
            )
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication service error"},
            )

    async def _verify_token(
        self, token: str, token_type: str = TokenType.ACCESS
    ) -> TokenPayload:
        try:
            claims = jwt.decode(
                token, self.public_key, algorithms=[self.algorithm],
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Token expired")
        except jwt.PyJWTError as e:
            raise InvalidTokenError(f"JWT decode error: {e}")

        if claims.get("token_type") != token_type:
            raise InvalidTokenError(f"Invalid token_type, expected {token_type}")

        try:
            user_id = UUID(claims["sub"])
            username = claims["username"]
            legal_entity_id = (
                UUID(claims["legal_entity_id"])
                if claims.get("legal_entity_id") else None
            )
            roles = claims.get("roles", [])
            permissions = claims.get("permissions", [])
            exp_ts = claims["exp"]
            iat_ts = claims["iat"]
            jti = claims["jti"]
            device_id = claims.get("device_id")
        except KeyError as e:
            raise InvalidTokenError(f"Missing required claim: {e}")
        except ValueError as e:
            raise InvalidTokenError(f"Invalid UUID format: {e}")

        exp = self._coerce_to_datetime(exp_ts, claim_name="exp")
        iat = self._coerce_to_datetime(iat_ts, claim_name="iat")

        if self.revocation_check and await self._is_token_revoked(jti):
            raise TokenRevokedError("Token is revoked")

        return TokenPayload(
            user_id=user_id, username=username, legal_entity_id=legal_entity_id,
            roles=roles, permissions=permissions, token_type=token_type,
            exp=exp, iat=iat, jti=jti, device_id=device_id,
        )

    @staticmethod
    def _coerce_to_datetime(value, claim_name: str = "claim") -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=UTC)
        if isinstance(value, str):
            try:
                return datetime.fromtimestamp(float(value), tz=UTC)
            except ValueError:
                pass
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                raise InvalidTokenError(f"Klaim '{claim_name}' tidak bisa di-parse: {value!r}")
        raise InvalidTokenError(
            f"Klaim '{claim_name}' bertipe tidak didukung: {type(value).__name__}"
        )

    async def _is_token_revoked(self, jti: str) -> bool:
        revocation_list = await self._get_revocation_list()
        return await revocation_list.is_revoked(jti)

    async def _check_rbac(self, request: Request, payload: TokenPayload) -> None:
        method = request.method
        path = request.url.path
        resource = self._map_path_to_resource(path)
        action = self._resolve_action(method, path)

        if resource is None:
            logger.debug(
                "RBAC skip (no resource mapping) path=%s method=%s",
                path, method,
            )
            return

        # 1) Wildcard dari token
        if payload.has_permission_wildcard(resource, action):
            logger.debug(
                "RBAC passed via wildcard user=%s perm=%s:%s",
                payload.user_id, resource, action,
            )
            return

        # 2) RBAC enforcer
        try:
            enforcer = await self._get_rbac_enforcer()
            authorized = await enforcer.check_permission(
                user_id=payload.user_id, resource=resource, action=action,
                legal_entity_id=payload.legal_entity_id,
            )
            if authorized:
                return
        except Exception as exc:
            logger.warning(
                "RBAC enforcer error (diabaikan): %s", type(exc).__name__,
            )

        # 3) Fallback authority matrix
        if self._authority_matrix_available:
            try:
                matrix_ok = await enforcer._authority_matrix.is_allowed(
                    payload.user_id, resource, action, payload.legal_entity_id
                )
                if matrix_ok:
                    return
            except Exception as exc:
                logger.warning(
                    "Authority matrix check error (diabaikan): %s", type(exc).__name__,
                )
        else:
            await self._ensure_authority_matrix_wired()

        logger.warning(
            "Authorization failed: user=%s lacks %s on %s (path=%s)",
            payload.user_id, action, resource, path,
        )
        raise InsufficientPermissionError(
            f"User does not have {action} permission on {resource}"
        )

    def _map_path_to_resource(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "v1":
            raw_resource = parts[2]
        elif len(parts) >= 1:
            candidates = [p for p in parts if p not in ("api", "v1")]
            raw_resource = candidates[0] if candidates else None
        else:
            raw_resource = None

        if raw_resource is None:
            return None

        mapped = RESOURCE_PATH_MAP.get(raw_resource)
        if mapped is None:
            logger.warning(
                "_map_path_to_resource: tidak ada mapping untuk path segment '%s' "
                "(path=%s) -- RBAC check DILEWATI untuk request ini. "
                "Tambahkan mapping di RESOURCE_PATH_MAP jika endpoint ini "
                "seharusnya diproteksi.",
                raw_resource, path,
            )
            return None
        return mapped

    def _resolve_action(self, method: str, path: str) -> str:
        for ov_method, pattern, ov_action in ACTION_OVERRIDES:
            if method == ov_method and pattern.match(path):
                return ov_action
        return self._map_method_to_action(method)

    def _map_method_to_action(self, method: str) -> str:
        method_map = {
            "GET": "read", "POST": "create", "PUT": "update",
            "PATCH": "update", "DELETE": "delete",
        }
        return method_map.get(method, "execute")

    @classmethod
    async def create_access_token(
        cls, user_id: UUID, username: str, legal_entity_id: UUID,
        roles: list[str], permissions: list[str],
        device_id: str | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        cached = getattr(cls, "_signing_cache", None)
        if cached is None:
            instance = cls.__new__(cls)
            instance.public_key = instance._load_public_key()
            instance.private_key = instance._load_private_key()
            instance.algorithm = DEFAULT_ALGORITHM
            instance.access_expire = timedelta(minutes=DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES)
            instance.refresh_expire = timedelta(days=DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS)
            cls._signing_cache = instance
            cached = instance

        expire_dt = datetime.now(UTC) + (expires_delta or cached.access_expire)
        now_dt = datetime.now(UTC)
        jti = str(uuid4())

        payload = {
            "sub": str(user_id), "username": username,
            "legal_entity_id": str(legal_entity_id) if legal_entity_id else None,
            "roles": roles, "permissions": permissions,
            "token_type": TokenType.ACCESS,
            "exp": int(expire_dt.timestamp()),
            "iat": int(now_dt.timestamp()),
            "jti": jti, "device_id": device_id,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        token = jwt.encode(payload, cached.private_key, algorithm=cached.algorithm)
        logger.info("Access identity issued")
        return token

    @classmethod
    async def create_refresh_token(
        cls, user_id: UUID, username: str, legal_entity_id: UUID,
        roles: list[str], permissions: list[str],
        device_id: str | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        cached = getattr(cls, "_signing_cache", None)
        if cached is None:
            instance = cls.__new__(cls)
            instance.public_key = instance._load_public_key()
            instance.private_key = instance._load_private_key()
            instance.algorithm = DEFAULT_ALGORITHM
            instance.access_expire = timedelta(minutes=DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES)
            instance.refresh_expire = timedelta(days=DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS)
            cls._signing_cache = instance
            cached = instance

        expire_dt = datetime.now(UTC) + (expires_delta or cached.refresh_expire)
        now_dt = datetime.now(UTC)
        jti = str(uuid4())

        payload = {
            "sub": str(user_id), "username": username,
            "legal_entity_id": str(legal_entity_id) if legal_entity_id else None,
            "roles": roles, "permissions": permissions,
            "token_type": TokenType.REFRESH,
            "exp": int(expire_dt.timestamp()),
            "iat": int(now_dt.timestamp()),
            "jti": jti, "device_id": device_id,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        token = jwt.encode(payload, cached.private_key, algorithm=cached.algorithm)
        logger.info("Refresh identity issued")
        return token

    @classmethod
    async def revoke_token(cls, jti: str) -> None:
        instance = cls.__new__(cls)
        instance._revocation_list = None
        instance.revocation_check = True
        revocation_list = await instance._get_revocation_list()
        await revocation_list.revoke(jti, expire_seconds=86400)
        logger.info("Identity revoked")


# ============================================================================
# HELPER: install middleware
# ============================================================================


def install_jwt_middleware(
    app,
    public_paths: list[str] | None = None,
    rbac_enabled: bool = True,
    revocation_check: bool = True,
) -> None:
    """
    Helper untuk memasang JWTAuthMiddleware ke FastAPI app.

    Panggil dari `app_factory.py`:
        from adapters.primary_api.common.fastapi_auth_jwt_middleware import install_jwt_middleware
        install_jwt_middleware(app)
    """
    app.add_middleware(
        JWTAuthMiddleware,
        public_paths=public_paths,
        rbac_enabled=rbac_enabled,
        revocation_check=revocation_check,
    )
    logger.info(
        "JWTAuthMiddleware installed (public_paths=%s, rbac=%s)",
        len(public_paths or []) + len(DEFAULT_PUBLIC_PATHS),
        rbac_enabled,
    )


# ============================================================================
# DEPENDENCIES UNTUK FASTAPI ENDPOINTS
# ============================================================================


def get_current_user(request: Request) -> TokenPayload:
    if not hasattr(request.state, "user"):
        logger.warning(
            "get_current_user: request.state.user missing for %s %s "
            "(middleware JWT mungkin tidak terpasang atau path salah)",
            request.method, request.url.path,
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return request.state.user


def get_current_user_id(request: Request) -> UUID:
    return get_current_user(request).user_id


def get_current_legal_entity(request: Request) -> UUID:
    return get_current_user(request).legal_entity_id


def require_permission(permission: str):
    async def dependency(
        request: Request,
        current_user: TokenPayload = Depends(get_current_user),
    ) -> TokenPayload:
        if not current_user.has_permission(permission):
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )
        return current_user
    return dependency


# Alias
create_access_token = JWTAuthMiddleware.create_access_token
create_refresh_token = JWTAuthMiddleware.create_refresh_token
revoke_token = JWTAuthMiddleware.revoke_token

__all__ = [
    "JWTAuthMiddleware",
    "TokenPayload",
    "TokenType",
    "create_access_token",
    "create_refresh_token",
    "get_current_legal_entity",
    "get_current_user",
    "get_current_user_id",
    "install_jwt_middleware",
    "require_permission",
    "revoke_token",
]
