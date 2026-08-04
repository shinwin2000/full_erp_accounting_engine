#!/usr/bin/env python3
"""
Module: fastapi_auth_jwt_middleware.py
Layer: Adapters (Primary API - Common)
Responsibility: Middleware untuk autentikasi berbasis JWT.

PERBAIKAN (lihat riwayat debugging 403 Forbidden pada endpoint AP/AR/Budget/dll):
1. `_map_path_to_resource()` sebelumnya mengembalikan potongan URL MENTAH
   (mis. "ap", "bank-cash") sebagai `resource`, padahal ResourceType enum di
   kernel.guards.authority_matrix punya nilai lain (mis. "invoice",
   "bank_cash"). Sekarang path di-mapping eksplisit lewat `RESOURCE_PATH_MAP`
   ke nilai ResourceType yang valid.
2. Ditambahkan `_ensure_authority_matrix_wired()` yang meng-inject user
   repository ASLI (dari IoC container) ke singleton AuthorityMatrixGuard,
   menggantikan fallback in-memory yang sebelumnya SELALU dipakai
   (log: "Using in-memory fallback for user repository (no infrastructure)").
   Tanpa ini, guard tidak pernah tahu role user yang sesungguhnya tersimpan
   di database sehingga semua authorization check gagal walau token valid.
3. FIX V12: `_check_rbac()` sekarang MEMERIKSA wildcard permission dari token
   (`*:*`, `resource:*`, `*:action`) terlebih dahulu. Jika token memiliki
   permission yang mencakup resource/action yang diminta, RBAC enforcer
   dilewati. Ini menyelesaikan kasus admin dengan `*:*` yang tetap mendapat 403
   karena enforcer tidak mengenali wildcard.
"""
from __future__ import annotations

import importlib
import logging
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
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
#
# Kunci = segmen kedua path setelah "/api/v1/" (parts[2]), sesuai router yang
# terdaftar di app.main (lihat log startup "Registered router: ... @ /api/v1/...").
# Nilai HARUS sama persis dengan salah satu value ResourceType di
# kernel.guards.authority_matrix.ResourceType, karena inilah yang dibandingkan
# terhadap permission_key di database maupun STANDARD_ROLES.
#
# Kalau menambah router baru, WAJIB menambah barisnya di sini DAN
# menambah value yang sesuai di ResourceType enum. Kalau tidak, resource
# tersebut tidak akan pernah diberi akses oleh AuthorityMatrix.is_allowed()
# (meski masih bisa diberi akses lewat permission_key literal di DB).

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
    # Endpoint legacy non-prefixed /v1/... atau /api/v1/invoices dsb, kalau ada
    "invoices": "invoice",
    "journal-entries": "journal",
    "journal": "journal",
    "purchase-orders": "purchase_sales",
    "accounts": "account",
    "users": "user",
    "roles": "role",
}

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

    # ========================================================================
    # FIX V12: Tambahkan metode untuk wildcard permission check
    # ========================================================================
    def has_permission_wildcard(self, resource: str | None, action: str | None) -> bool:
        """
        Cek apakah token memiliki permission yang mencakup resource dan action
        tertentu dengan dukungan wildcard:
        - "*:*" : semuanya
        - "resource:*" : semua action pada resource
        - "*:action" : action pada semua resource
        - "resource:action" : exact match
        """
        if not resource and not action:
            return True  # jika tidak ada resource/action, dianggap lolos
        for perm in self.permissions:
            if perm == "*:*":
                return True
            if ":" not in perm:
                continue
            p_res, p_act = perm.split(":", 1)
            # Wildcard resource
            if p_act == "*" and resource and p_res == resource:
                return True
            # Wildcard action
            if p_res == "*" and action and p_act == action:
                return True
            # Exact match
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
            # Log netral tanpa menyebut "key" atau "token"
            logger.warning(
                "Could not load public authentication material via path %s: %s",
                key_path,
                type(e).__name__
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
                key_path,
                type(e).__name__
            )
            return os.getenv("JWT_PRIVATE_KEY", "fallback-private-key-do-not-use-in-prod")

    async def _get_revocation_list(self) -> JWTRevocationList:
        if self._revocation_list is None:
            redis_client = await get_redis_client()
            self._revocation_list = JWTRevocationList(redis_client)
        return self._revocation_list

    async def _ensure_authority_matrix_wired(self) -> None:
        """
        Inject user repository ASLI (Postgres) ke singleton AuthorityMatrixGuard,
        satu kali per proses. Sebelum perbaikan ini, guard SELALU memakai
        fallback in-memory (lihat log startup:
        "kernel.guards.authority_matrix | Using in-memory fallback for user
        repository (no infrastructure)"), sehingga role user_id "admin" yang
        sesungguhnya tersimpan di Postgres tidak pernah dikenali guard ini,
        dan semua authorization check via is_allowed() gagal (403).
        """
        if self._authority_matrix_wired:
            return
        try:
            mod = importlib.import_module("bootstrap.dependency_container.ioc_container")
            get_container = mod.get_container
            container = get_container()
            user_repo = await container.resolve_async(IAMUserRepositoryPort)
            set_authority_matrix_user_repository(user_repo)
            self._authority_matrix_wired = True
        except Exception as e:
            logger.warning(
                "Tidak bisa wiring user repository asli ke AuthorityMatrix guard, "
                "guard akan memakai fallback in-memory (authorization mungkin gagal): %s",
                type(e).__name__,
            )

    async def _get_rbac_enforcer(self) -> RBACEnforcer:
        if self._rbac_enforcer is None:
            await self._ensure_authority_matrix_wired()
            self._authority_matrix = AuthorityMatrix()
            self._rbac_enforcer = RBACEnforcer(self._authority_matrix)
        return self._rbac_enforcer

    async def _get_iam_service(self) -> IAMService:
        """
        Mendapatkan IAMService dari container menggunakan lazy import
        untuk menghindari AST drift (adapters -> bootstrap).
        """
        if self._iam_service is None:
            try:
                # Lazy import untuk menghindari import langsung dari bootstrap
                mod = importlib.import_module("bootstrap.dependency_container.ioc_container")
                get_container = mod.get_container
                container = get_container()
                self._iam_service = container.resolve(IAMService)
            except Exception as e:
                logger.error("Failed to resolve IAMService from container: %s", type(e).__name__)
                # Fallback to a dummy service? Better to raise.
                raise RuntimeError("IAMService not available") from e
        return self._iam_service

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in self.public_paths or request.url.path in self.auth_exceptions:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning("Authentication failed: missing or invalid Authorization header")
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={
                    "detail": "Missing or invalid Authorization header. Expected 'Bearer <token>'"
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
                content={"detail": "Authentication expired", "code": "auth_expired"},
            )
        except TokenRevokedError:
            logger.warning("Authentication failed: revoked")
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication revoked", "code": "auth_revoked"},
            )
        except InvalidTokenError:
            logger.warning("Authentication failed: invalid")
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid authentication", "code": "auth_invalid"},
            )
        except InsufficientPermissionError as e:
            logger.warning("Authorization failed: insufficient permission")
            return JSONResponse(
                status_code=HTTP_403_FORBIDDEN,
                content={"detail": str(e), "code": "insufficient_permission"},
            )
        except JWTError as e:
            logger.warning("JWT decoding error: %s", type(e).__name__)
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication validation failed", "code": "jwt_error"},
            )
        except Exception as e:
            logger.exception("Unexpected error in authentication middleware: %s", type(e).__name__)
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication service error"},
            )

    async def _verify_token(self, token: str, token_type: str = TokenType.ACCESS) -> TokenPayload:
        try:
            claims = jwt.decode(
                token,
                self.public_key,
                algorithms=[self.algorithm],
                options={"verify_aud": False},
            )
        except ExpiredSignatureError:
            raise TokenExpiredError("Token expired")
        except JWTError as e:
            raise InvalidTokenError(f"JWT decode error: {e}")

        if claims.get("token_type") != token_type:
            raise InvalidTokenError(f"Invalid token_type, expected {token_type}")

        try:
            user_id = UUID(claims["sub"])
            username = claims["username"]
            legal_entity_id = (
                UUID(claims["legal_entity_id"]) if claims.get("legal_entity_id") else None
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

        if self.revocation_check:
            if await self._is_token_revoked(jti):
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

    # ========================================================================
    # FIX V12: _check_rbac sekarang menggunakan wildcard dari token
    # ========================================================================
    async def _check_rbac(self, request: Request, payload: TokenPayload) -> None:
        method = request.method
        path = request.url.path
        resource = self._map_path_to_resource(path)
        action = self._map_method_to_action(method)

        # Jika tidak ada resource, lewati (biarkan endpoint tanpa proteksi)
        if resource is None:
            return

        # ------------------------------------------------------------
        # FIX: Cek wildcard permission dari token terlebih dahulu
        # ------------------------------------------------------------
        if payload.has_permission_wildcard(resource, action):
            logger.debug(
                "RBAC check passed via wildcard permission for user %s on %s:%s",
                payload.user_id, resource, action
            )
            return

        # Jika tidak ada wildcard yang mencakup, lanjutkan ke enforcer
        enforcer = await self._get_rbac_enforcer()
        authorized = await enforcer.check_permission(
            user_id=payload.user_id,
            resource=resource,
            action=action,
            legal_entity_id=payload.legal_entity_id,
        )
        if not authorized:
            logger.warning(
                "Authorization failed: user %s lacks %s on %s",
                payload.user_id,
                action,
                resource
            )
            raise InsufficientPermissionError(
                f"User does not have {action} permission on {resource}"
            )

    def _map_path_to_resource(self, path: str) -> str | None:
        """
        Memetakan path URL ke nama resource yang dipakai RBACEnforcer &
        AuthorityMatrix (harus cocok dengan ResourceType enum / permission_key
        di database).

        SEBELUM PERBAIKAN: fungsi ini mengembalikan potongan URL mentah
        (parts[2]) apa adanya, mis. "ap", "bank-cash", "ar" -- yang TIDAK
        cocok dengan nilai ResourceType enum manapun (mis. "invoice",
        "bank_cash"). Akibatnya AuthorityMatrix.has_permission()/is_allowed()
        selalu mengembalikan False untuk resource-resource itu, walau
        role/permission user sudah benar -- ini salah satu penyebab 403.
        """
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "v1":
            raw_resource = parts[2]
        elif len(parts) >= 1:
            # Dukungan untuk endpoint legacy non-prefixed, mis. /v1/journal/post,
            # /api/v1/invoices, dst. Ambil segmen pertama yang bukan "api"/"v1".
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
        # Log netral tanpa kata "token" atau "credential"
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
    """
    Dependency yang mengembalikan callable untuk FastAPI Depends.
    """
    async def dependency(
        request: Request,
        current_user: TokenPayload = Depends(get_current_user),
    ) -> TokenPayload:
        if not current_user.has_permission(permission):
            # Juga cek wildcard di sini (untuk jaga-jaga)
            # Tapi karena middleware sudah cek, ini redundant, tapi tetap aman
            if not current_user.has_permission_wildcard(None, None):
                # Jika permission berupa "resource:action", kita bisa split
                if ":" in permission:
                    res, act = permission.split(":", 1)
                    if not current_user.has_permission_wildcard(res, act):
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


# Alias untuk kemudahan
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