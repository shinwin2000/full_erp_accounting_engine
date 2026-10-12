#!/usr/bin/env python3
"""
Module: fastapi_auth_jwt_middleware.py
Layer: Adapters (Primary API - Common)
Responsibility: Middleware untuk autentikasi berbasis JWT.

PERBAIKAN:
- _map_path_to_resource() memetakan path ke ResourceType (bukan potongan URL mentah).
- _ensure_authority_matrix_wired() meng-inject user repository ke AuthorityMatrixGuard.
- FIX V12: _check_rbac() memeriksa wildcard permission dari token terlebih dahulu.
- FIX V13: Bila authority matrix belum di-wire (session_maker belum diset),
  lewati pemanggilan matrix sebagai hard-requirement. RBACEnforcer dianggap SUDAH CUKUP.
- FIX V14 (2026-10-12): ACTION_OVERRIDES untuk /customers/export disesuaikan
  dengan pola DOUBLE endpoint (/api/v1/customers/customers/export), plus
  /customers/stats ditambahkan.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException
import jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

# --- Import dengan penanganan error ---
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
except ImportError as e:
    logging.critical(f"Failed to import AuthorityMatrix: {e}")
    raise

try:
    from kernel.guards.authority_matrix import set_authority_matrix_user_repository
except ImportError as e:
    logging.critical(f"Failed to import set_authority_matrix_user_repository: {e}")
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
        # --- Customer (DOUBLE prefix karena router mount di /api/v1/customers) ---
        ("GET", r"^/api/v1/customers/customers/export/?$", "export"),
        ("GET", r"^/api/v1/customers/customers/stats/?$", "read"),
        ("POST", r"^/api/v1/customers/customers/[^/]+/credit-limit/?$", "approve"),
        ("POST", r"^/api/v1/customers/customers/[^/]+/balance/?$", "post"),
        (
            "POST",
            r"^/api/v1/customers/customers/[^/]+/(activate|deactivate|block)/?$",
            "update",
        ),
        ("POST", r"^/api/v1/customers/customers/bulk-update-status/?$", "update"),
        ("POST", r"^/api/v1/customers/customers/bulk-delete/?$", "delete"),
        # --- Supplier ---
        ("GET", r"^/api/v1/suppliers/export/?$", "export"),
        ("POST", r"^/api/v1/suppliers/import/?$", "import"),
        (
            "POST",
            r"^/api/v1/suppliers/suppliers/[^/]+/(activate|deactivate|status)/?$",
            "update",
        ),
        (
            "POST",
            r"^/api/v1/suppliers/suppliers/[^/]+/withholding-category/?$",
            "approve",
        ),
        # --- Employee ---
        ("POST", r"^/api/v1/employees/employees/import/?$", "import"),
        (
            "POST",
            r"^/api/v1/employees/employees/[^/]+/(activate|deactivate)/?$",
            "update",
        ),
        (
            "POST",
            r"^/api/v1/employees/employees/[^/]+/(salary-structure|bpjs|ptkp|resign)/?$",
            "approve",
        ),
        (
            "POST",
            r"^/api/v1/employees/employees/[^/]+/(photo|dependents|documents)/?$",
            "update",
        ),
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
# VALUE OBJECTS
# ============================================================================


class TokenPayload:
    __slots__ = (
        "device_id",
        "exp",
        "iat",
        "jti",
        "legal_entity_id",
        "permissions",
        "roles",
        "token_type",
        "user_id",
        "username",
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
        return permission in self.permissions

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_permission_wildcard(
        self, resource: str | None, action: str | None
    ) -> bool:
        """
        Cek apakah token memiliki permission yang mencakup resource dan action
        tertentu dengan dukungan wildcard:
        - "*:*" : semuanya
        - "resource:*" : semua action pada resource
        - "*:action" : action pada semua resource
        - "resource:action" : exact match
        """
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
        self.public_paths = set(
            public_paths
            or [
                "/api/health",
                "/api/ready",
                "/api/docs",
                "/api/openapi.json",
                "/api/auth/login",
                "/api/auth/refresh",
                "/metrics",
                "/",
            ]
        )
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

    def _load_public_key(self) -> str:
        key_path = os.getenv("JWT_PUBLIC_KEY_PATH", "/secrets/jwt_public.pem")
        try:
            with open(key_path) as f:
                return f.read()
        except Exception as e:
            logger.warning(
                "Could not load public authentication material via path %s: %s",
                key_path,
                type(e).__name__,
            )
            return os.getenv(
                "JWT_PUBLIC_KEY", "fallback-public-key-do-not-use-in-prod"
            )

    def _load_private_key(self) -> str:
        key_path = os.getenv("JWT_PRIVATE_KEY_PATH", "/secrets/jwt_private.pem")
        try:
            with open(key_path) as f:
                return f.read()
        except Exception as e:
            logger.warning(
                "Could not load private authentication material via path %s: %s",
                key_path,
                type(e).__name__,
            )
            return os.getenv(
                "JWT_PRIVATE_KEY", "fallback-private-key-do-not-use-in-prod"
            )

    async def _get_revocation_list(self) -> JWTRevocationList:
        if self._revocation_list is None:
            redis_client = await get_redis_client()
            self._revocation_list = JWTRevocationList(redis_client)
        return self._revocation_list

    async def _ensure_authority_matrix_wired(self) -> None:
        """
        Inject user repository ke singleton AuthorityMatrixGuard.
        TIDAK fatal bila gagal: authority matrix hanya jadi second-opinion.
        """
        if self._authority_matrix_wired:
            return
        try:
            mod = importlib.import_module(
                "bootstrap.dependency_container.ioc_container"
            )
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
                "dipakai): %s",
                type(e).__name__,
            )
            self._authority_matrix_available = False

    async def _get_rbac_enforcer(self) -> RBACEnforcer:
        if self._rbac_enforcer is None:
            self._authority_matrix = AuthorityMatrix()
            self._rbac_enforcer = RBACEnforcer(self._authority_matrix)
        return self._rbac_enforcer

    async def _get_iam_service(self) -> IAMService:
        if self._iam_service is None:
            try:
                mod = importlib.import_module(
                    "bootstrap.dependency_container.ioc_container"
                )
                get_container = mod.get_container
                container = get_container()
                self._iam_service = await container.resolve_async(IAMService)
            except Exception as e:
                logger.error(
                    "Failed to resolve IAMService from container: %s",
                    type(e).__name__,
                )
                raise RuntimeError("IAMService not available") from e
        return self._iam_service

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if (
            request.url.path in self.public_paths
            or request.url.path in self.auth_exceptions
        ):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning(
                "Authentication failed: missing or invalid Authorization header"
            )
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={
                    "detail": (
                        "Missing or invalid Authorization header. "
                        "Expected 'Bearer <token>'"
                    )
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
            logger.warning("Authentication failed: expired")
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={
                    "detail": "Authentication expired",
                    "code": "auth_expired",
                },
            )
        except TokenRevokedError:
            logger.warning("Authentication failed: revoked")
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={
                    "detail": "Authentication revoked",
                    "code": "auth_revoked",
                },
            )
        except InvalidTokenError:
            logger.warning("Authentication failed: invalid")
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={
                    "detail": "Invalid authentication",
                    "code": "auth_invalid",
                },
            )
        except InsufficientPermissionError as e:
            logger.warning("Authorization failed: insufficient permission")
            return JSONResponse(
                status_code=HTTP_403_FORBIDDEN,
                content={
                    "detail": str(e),
                    "code": "insufficient_permission",
                },
            )
        except jwt.PyJWTError as e:
            logger.warning("JWT decoding error: %s", type(e).__name__)
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={
                    "detail": "Authentication validation failed",
                    "code": "jwt_error",
                },
            )
        except Exception as e:
            logger.exception(
                "Unexpected error in authentication middleware: %s",
                type(e).__name__,
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
                token,
                self.public_key,
                algorithms=[self.algorithm],
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
                if claims.get("legal_entity_id")
                else None
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

        exp = datetime.fromtimestamp(exp_ts, tz=UTC)
        iat = datetime.fromtimestamp(iat_ts, tz=UTC)

        if self.revocation_check and await self._is_token_revoked(jti):
            raise TokenRevokedError("Token is revoked")

        return TokenPayload(
            user_id=user_id,
            username=username,
            legal_entity_id=legal_entity_id,
            roles=roles,
            permissions=permissions,
            token_type=token_type,
            exp=exp,
            iat=iat,
            jti=jti,
            device_id=device_id,
        )

    async def _is_token_revoked(self, jti: str) -> bool:
        revocation_list = await self._get_revocation_list()
        return await revocation_list.is_revoked(jti)

    async def _check_rbac(self, request: Request, payload: TokenPayload) -> None:
        """
        FIX V13:
        - Wildcard token langsung lolos.
        - RBAC enforcer (permission DB) dicek.
        - Authority matrix HANYA jadi second-opinion (opsional).
        """
        method = request.method
        path = request.url.path
        resource = self._map_path_to_resource(path)
        action = self._resolve_action(method, path)

        if resource is None:
            return

        # 1) Wildcard dari token
        if payload.has_permission_wildcard(resource, action):
            logger.debug(
                "RBAC check passed via wildcard permission for user %s on %s:%s",
                payload.user_id,
                resource,
                action,
            )
            return

        # 2) Cek via RBAC enforcer
        enforcer = await self._get_rbac_enforcer()
        authorized = await enforcer.check_permission(
            user_id=payload.user_id,
            resource=resource,
            action=action,
            legal_entity_id=payload.legal_entity_id,
        )
        if authorized:
            return

        # 3) Fallback: authority matrix (opsional)
        if self._authority_matrix_available:
            try:
                matrix_ok = await enforcer._authority_matrix.is_allowed(
                    payload.user_id, resource, action, payload.legal_entity_id
                )
                if matrix_ok:
                    logger.debug(
                        "RBAC check passed via authority matrix for user %s on %s:%s",
                        payload.user_id,
                        resource,
                        action,
                    )
                    return
            except Exception as exc:
                logger.warning(
                    "Authority matrix check error (diabaikan, RBAC sudah deny): %s",
                    type(exc).__name__,
                )
        else:
            await self._ensure_authority_matrix_wired()

        logger.warning(
            "Authorization failed: user %s lacks %s on %s",
            payload.user_id,
            action,
            resource,
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
                raw_resource,
                path,
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
            "GET": "read",
            "POST": "create",
            "PUT": "update",
            "PATCH": "update",
            "DELETE": "delete",
        }
        return method_map.get(method, "execute")

    @classmethod
    async def create_access_token(
        cls,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID,
        roles: list[str],
        permissions: list[str],
        device_id: str | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        instance = cls(None)
        expire = datetime.now(UTC) + (expires_delta or instance.access_expire)
        jti = str(uuid4())

        payload = {
            "sub": str(user_id),
            "username": username,
            "legal_entity_id": str(legal_entity_id) if legal_entity_id else None,
            "roles": roles,
            "permissions": permissions,
            "token_type": TokenType.ACCESS,
            "exp": expire,
            "iat": datetime.now(UTC),
            "jti": jti,
            "device_id": device_id,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        token = jwt.encode(payload, instance.private_key, algorithm=instance.algorithm)
        logger.info("Access identity issued")
        return token

    @classmethod
    async def create_refresh_token(
        cls,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID,
        roles: list[str],
        permissions: list[str],
        device_id: str | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        instance = cls(None)
        expire = datetime.now(UTC) + (expires_delta or instance.refresh_expire)
        jti = str(uuid4())

        payload = {
            "sub": str(user_id),
            "username": username,
            "legal_entity_id": str(legal_entity_id) if legal_entity_id else None,
            "roles": roles,
            "permissions": permissions,
            "token_type": TokenType.REFRESH,
            "exp": expire,
            "iat": datetime.now(UTC),
            "jti": jti,
            "device_id": device_id,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        token = jwt.encode(payload, instance.private_key, algorithm=instance.algorithm)
        logger.info("Refresh identity issued")
        return token

    @classmethod
    async def revoke_token(cls, jti: str) -> None:
        instance = cls(None)
        revocation_list = await instance._get_revocation_list()
        await revocation_list.revoke(jti, expire_seconds=86400)
        logger.info("Identity revoked")


# ============================================================================
# DEPENDENCIES UNTUK FASTAPI ENDPOINTS
# ============================================================================


def get_current_user(request: Request) -> TokenPayload:
    if not hasattr(request.state, "user"):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Not authenticated")
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
            if ":" in permission:
                resource, action = permission.split(":", 1)
                if not current_user.has_permission_wildcard(resource, action):
                    raise HTTPException(
                        status_code=HTTP_403_FORBIDDEN,
                        detail=f"Missing permission: {permission}",
                    )
            else:
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
    "require_permission",
    "revoke_token",
]
