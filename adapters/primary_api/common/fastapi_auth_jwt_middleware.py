#!/usr/bin/env python3
"""
Module: fastapi_auth_jwt_middleware.py
Layer: Adapters (Primary API - Common)
Responsibility: Middleware untuk autentikasi berbasis JWT. Memverifikasi token,
               mengelola blacklist, mengekstrak claims, dan mengisi request state
               dengan informasi user. Juga mencatat percobaan login gagal.
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

from application.service_layer.service_iam import IAMService
from infrastructure.caching.redis_manager import get_redis_client
from infrastructure.security.jwt_revocation_list import JWTRevocationList
from infrastructure.security.rbac_enforcer_unified import RBACEnforcer
from kernel.guards.authority_matrix import AuthorityMatrix

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

    async def _get_rbac_enforcer(self) -> RBACEnforcer:
        if self._rbac_enforcer is None:
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
                get_container = getattr(mod, "get_container")
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

    async def _check_rbac(self, request: Request, payload: TokenPayload) -> None:
        method = request.method
        path = request.url.path
        resource = self._map_path_to_resource(path)
        action = self._map_method_to_action(method)

        if resource is None:
            return

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
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "v1":
            return parts[2]
        return None

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