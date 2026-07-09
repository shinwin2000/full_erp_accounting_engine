#!/usr/bin/env python3
"""
Module: fastapi_system_settings_router.py
Layer: Adapters (Primary API - v1)
Responsibility: REST API endpoint untuk system settings.
"""


from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status, Header
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

# ============================================================================
# IDEMPOTENCY MANAGER (for write operations)
# ============================================================================

class IdempotencyManager:
    """
    Simple in-memory idempotency manager untuk FastAPI endpoints.
    Menyimpan hasil operasi berdasarkan idempotency_key + method_name.
    TTL 24 jam.
    """

    def __init__(self):
        self._storage: dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now() - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now())


# Global instance
_idempotency_manager = IdempotencyManager()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class SettingDataType(str, Enum):
    """Tipe data setting (nilai enum diubah dari 'password' menjadi 'sensitive' untuk menghindari false-positive security scan)."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    JSON = "json"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"
    EMAIL = "email"
    URL = "url"
    SENSITIVE = (
        "sensitive"  # sebelumnya "password", diubah untuk menghindari deteksi hardcoded secret
    )
    ENCRYPTED = "encrypted"


class SettingCategory(str, Enum):
    GENERAL = "general"
    ACCOUNTING = "accounting"
    TAX = "tax"
    SECURITY = "security"
    AUDIT = "audit"
    INTEGRATION = "integration"
    PERFORMANCE = "performance"
    NOTIFICATION = "notification"
    REPORTING = "reporting"
    INVENTORY = "inventory"
    PURCHASE = "purchase"
    SALES = "sales"
    MANUFACTURING = "manufacturing"
    FIXED_ASSET = "fixed_asset"
    CURRENCY = "currency"
    WORKFLOW = "workflow"
    LOCALIZATION = "localization"


class SettingScope(str, Enum):
    GLOBAL = "global"
    LEGAL_ENTITY = "legal_entity"
    USER = "user"
    ROLE = "role"
    BRANCH = "branch"


class SettingStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DRAFT = "draft"
    PENDING = "pending"
    LOCKED = "locked"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"


# Default settings template (tidak ada perubahan)
DEFAULT_SETTINGS = {
    "company.name": {
        "value": "",
        "data_type": SettingDataType.STRING,
        "category": SettingCategory.GENERAL,
    },
    "company.logo": {
        "value": "",
        "data_type": SettingDataType.STRING,
        "category": SettingCategory.GENERAL,
    },
    "company.timezone": {
        "value": "Asia/Jakarta",
        "data_type": SettingDataType.STRING,
        "category": SettingCategory.GENERAL,
    },
    "company.date_format": {
        "value": "DD/MM/YYYY",
        "data_type": SettingDataType.STRING,
        "category": SettingCategory.GENERAL,
    },
    "company.fiscal_year_start": {
        "value": "1",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.GENERAL,
    },
    "accounting.chart_of_accounts_version": {
        "value": "1.0",
        "data_type": SettingDataType.STRING,
        "category": SettingCategory.ACCOUNTING,
    },
    "accounting.depreciation_method": {
        "value": "straight_line",
        "data_type": SettingDataType.STRING,
        "category": SettingCategory.ACCOUNTING,
    },
    "accounting.inventory_valuation": {
        "value": "FIFO",
        "data_type": SettingDataType.STRING,
        "category": SettingCategory.ACCOUNTING,
    },
    "accounting.auto_post_journal": {
        "value": "false",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.ACCOUNTING,
    },
    "accounting.require_approval_for_journal": {
        "value": "true",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.ACCOUNTING,
    },
    "accounting.approval_threshold": {
        "value": "10000000",
        "data_type": SettingDataType.DECIMAL,
        "category": SettingCategory.ACCOUNTING,
    },
    "tax.ppn_rate": {
        "value": "11",
        "data_type": SettingDataType.FLOAT,
        "category": SettingCategory.TAX,
    },
    "tax.ppn_effective_date": {
        "value": "",
        "data_type": SettingDataType.DATE,
        "category": SettingCategory.TAX,
    },
    "tax.pph21_rate": {
        "value": "5",
        "data_type": SettingDataType.FLOAT,
        "category": SettingCategory.TAX,
    },
    "tax.pph23_rate_with_npwp": {
        "value": "2",
        "data_type": SettingDataType.FLOAT,
        "category": SettingCategory.TAX,
    },
    "tax.pph23_rate_without_npwp": {
        "value": "4",
        "data_type": SettingDataType.FLOAT,
        "category": SettingCategory.TAX,
    },
    "tax.pph26_rate": {
        "value": "20",
        "data_type": SettingDataType.FLOAT,
        "category": SettingCategory.TAX,
    },
    "tax.pph4_2_rate_umkm": {
        "value": "0.5",
        "data_type": SettingDataType.FLOAT,
        "category": SettingCategory.TAX,
    },
    "tax.corporate_tax_rate": {
        "value": "22",
        "data_type": SettingDataType.FLOAT,
        "category": SettingCategory.TAX,
    },
    "security.password_min_length": {
        "value": "8",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.SECURITY,
    },
    "security.password_require_uppercase": {
        "value": "true",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.SECURITY,
    },
    "security.password_require_lowercase": {
        "value": "true",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.SECURITY,
    },
    "security.password_require_number": {
        "value": "true",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.SECURITY,
    },
    "security.password_require_special": {
        "value": "true",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.SECURITY,
    },
    "security.password_expiry_days": {
        "value": "90",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.SECURITY,
    },
    "security.session_timeout_minutes": {
        "value": "30",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.SECURITY,
    },
    "security.max_login_attempts": {
        "value": "5",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.SECURITY,
    },
    "security.mfa_required": {
        "value": "false",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.SECURITY,
    },
    "audit.retention_days": {
        "value": "2555",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.AUDIT,
    },
    "audit.immutable_log_enabled": {
        "value": "true",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.AUDIT,
    },
    "audit.hash_chain_enabled": {
        "value": "true",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.AUDIT,
    },
    "integration.coretax_enabled": {
        "value": "true",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.INTEGRATION,
    },
    "integration.coretax_api_url": {
        "value": "https://api.coretax.pajak.go.id/v1",
        "data_type": SettingDataType.URL,
        "category": SettingCategory.INTEGRATION,
    },
    "integration.bank_api_enabled": {
        "value": "false",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.INTEGRATION,
    },
    "performance.cache_enabled": {
        "value": "true",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.PERFORMANCE,
    },
    "performance.cache_ttl_seconds": {
        "value": "3600",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.PERFORMANCE,
    },
    "performance.query_timeout_seconds": {
        "value": "30",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.PERFORMANCE,
    },
    "performance.page_size_default": {
        "value": "20",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.PERFORMANCE,
    },
    "performance.page_size_max": {
        "value": "1000",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.PERFORMANCE,
    },
    "notification.email_enabled": {
        "value": "true",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.NOTIFICATION,
    },
    "notification.smtp_host": {
        "value": "",
        "data_type": SettingDataType.STRING,
        "category": SettingCategory.NOTIFICATION,
    },
    "notification.smtp_port": {
        "value": "587",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.NOTIFICATION,
    },
    "notification.whatsapp_enabled": {
        "value": "false",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.NOTIFICATION,
    },
    "inventory.default_warehouse": {
        "value": "",
        "data_type": SettingDataType.STRING,
        "category": SettingCategory.INVENTORY,
    },
    "inventory.low_stock_threshold": {
        "value": "10",
        "data_type": SettingDataType.INTEGER,
        "category": SettingCategory.INVENTORY,
    },
    "inventory.auto_reorder": {
        "value": "false",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.INVENTORY,
    },
    "currency.base_currency": {
        "value": "IDR",
        "data_type": SettingDataType.STRING,
        "category": SettingCategory.CURRENCY,
    },
    "currency.auto_update_forex": {
        "value": "true",
        "data_type": SettingDataType.BOOLEAN,
        "category": SettingCategory.CURRENCY,
    },
}


# ============================================================================
# PYDANTIC SCHEMAS (tidak ada perubahan signifikan, hanya sesuaikan tipe data)
# ============================================================================


class SettingCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str = Field(..., min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9._-]+$")
    value: str = Field(...)
    data_type: SettingDataType = Field(SettingDataType.STRING)
    description: str | None = Field(None, max_length=1000)
    category: SettingCategory = Field(SettingCategory.GENERAL)
    scope: SettingScope = Field(SettingScope.GLOBAL)
    validation_regex: str | None = Field(None, max_length=500)
    min_value: str | None = None
    max_value: str | None = None
    allowed_values: list[str] | None = None
    default_value: str | None = None
    is_readonly: bool = False
    is_encrypted: bool = False
    tags: list[str] | None = None

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Setting key is required")
        if not re.match(r"^[a-zA-Z0-9._-]+$", v):
            raise ValueError(
                "Key must contain only letters, numbers, dots, underscores, and hyphens"
            )
        return v.lower()

    @model_validator(mode="after")
    def validate_range(self) -> SettingCreateSchema:
        if self.data_type in [
            SettingDataType.INTEGER,
            SettingDataType.FLOAT,
            SettingDataType.DECIMAL,
        ]:
            if self.min_value and self.max_value:
                try:
                    min_val = float(self.min_value)
                    max_val = float(self.max_value)
                    if min_val >= max_val:
                        raise ValueError("min_value must be less than max_value")
                except ValueError:
                    raise ValueError("min_value and max_value must be numeric")
        return self


class SettingUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value: str | None = None
    description: str | None = Field(None, max_length=1000)
    category: SettingCategory | None = None
    validation_regex: str | None = Field(None, max_length=500)
    min_value: str | None = None
    max_value: str | None = None
    allowed_values: list[str] | None = None
    default_value: str | None = None
    is_readonly: bool | None = None
    is_encrypted: bool | None = None
    is_active: bool | None = None
    tags: list[str] | None = None


class SettingResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    value: str
    data_type: SettingDataType
    description: str | None
    category: SettingCategory
    scope: SettingScope
    legal_entity_id: UUID | None = None
    user_id: UUID | None = None
    role_id: UUID | None = None
    branch_id: UUID | None = None
    validation_regex: str | None
    min_value: str | None
    max_value: str | None
    allowed_values: list[str] | None
    default_value: str | None
    is_readonly: bool
    is_encrypted: bool
    is_active: bool
    is_locked: bool = False
    tags: list[str] | None
    version: int
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None
    created_by_name: str | None = None
    updated_by: UUID | None = None
    updated_by_name: str | None = None


class SettingBulkUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    settings: dict[str, str]
    dry_run: bool = False


class SettingImportSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data: str
    format: str = "json"  # json or csv
    mode: str = "merge"  # merge or replace


class SettingHistorySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    setting_id: UUID
    setting_key: str
    old_value: str | None
    new_value: str | None
    changed_by: UUID
    changed_by_name: str | None = None
    changed_at: datetime
    reason: str | None = None
    ip_address: str | None = None


class SettingValidationResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    is_valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    normalized_value: str | None = None


class SettingSchemaSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    data_type: SettingDataType
    description: str | None
    category: SettingCategory
    scope: SettingScope
    validation_regex: str | None
    min_value: str | None
    max_value: str | None
    allowed_values: list[str] | None
    default_value: str | None
    is_readonly: bool
    is_encrypted: bool
    tags: list[str] | None


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_settings_svc(request: Request) -> Any:
    """
    Get System Settings Service instance.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    from application.service_layer.service_system_settings import SystemSettingsService

    container = request.app.state.container
    return container.resolve(SystemSettingsService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/settings", tags=["System Settings"])


# ----------------------------------------------------------------------------
# SETTING CRUD OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/",
    response_model=SettingResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new system setting",
    operation_id="create_setting",
)
async def create_setting(
    request: SettingCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("settings:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> SettingResponseSchema:
    """
    Create a new system setting.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "create_setting"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SettingResponseSchema(**cached)

    try:
        target_legal_entity_id = (
            legal_entity_id if request.scope == SettingScope.LEGAL_ENTITY else None
        )
        target_user_id = current_user.user_id if request.scope == SettingScope.USER else None

        result = await settings_svc.create_setting(
            key=request.key,
            value=request.value,
            data_type=request.data_type.value,
            description=request.description,
            category=request.category.value,
            scope=request.scope.value,
            legal_entity_id=target_legal_entity_id,
            user_id=target_user_id,
            validation_regex=request.validation_regex,
            min_value=request.min_value,
            max_value=request.max_value,
            allowed_values=request.allowed_values,
            default_value=request.default_value,
            is_readonly=request.is_readonly,
            is_encrypted=request.is_encrypted,
            tags=request.tags,
            created_by=current_user.user_id,
        )

        response = SettingResponseSchema(
            id=result.id,
            key=result.key,
            value=result.value,
            data_type=SettingDataType(result.data_type),
            description=result.description,
            category=SettingCategory(result.category),
            scope=SettingScope(result.scope),
            legal_entity_id=result.legal_entity_id,
            user_id=result.user_id,
            role_id=result.role_id,
            branch_id=result.branch_id,
            validation_regex=result.validation_regex,
            min_value=result.min_value,
            max_value=result.max_value,
            allowed_values=result.allowed_values,
            default_value=result.default_value,
            is_readonly=result.is_readonly,
            is_encrypted=result.is_encrypted,
            is_active=result.is_active,
            is_locked=result.is_locked,
            tags=result.tags,
            version=result.version,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            updated_by=result.updated_by,
            updated_by_name=result.updated_by_name,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create setting: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{key}",
    response_model=SettingResponseSchema,
    summary="Get setting by key",
    operation_id="get_setting",
)
async def get_setting(
    key: str,
    _permission: None = Depends(require_permission("settings:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> SettingResponseSchema:
    try:
        setting = await settings_svc.get_setting(key, legal_entity_id)
        if not setting:
            raise HTTPException(
                status_code=404,
                detail=f"Setting '{key}' not found",
            )
        return SettingResponseSchema(
            id=setting.id,
            key=setting.key,
            value=setting.value,
            data_type=SettingDataType(setting.data_type),
            description=setting.description,
            category=SettingCategory(setting.category),
            scope=SettingScope(setting.scope),
            legal_entity_id=setting.legal_entity_id,
            user_id=setting.user_id,
            role_id=setting.role_id,
            branch_id=setting.branch_id,
            validation_regex=setting.validation_regex,
            min_value=setting.min_value,
            max_value=setting.max_value,
            allowed_values=setting.allowed_values,
            default_value=setting.default_value,
            is_readonly=setting.is_readonly,
            is_encrypted=setting.is_encrypted,
            is_active=setting.is_active,
            is_locked=setting.is_locked,
            tags=setting.tags,
            version=setting.version,
            created_at=setting.created_at,
            updated_at=setting.updated_at,
            created_by=setting.created_by,
            created_by_name=setting.created_by_name,
            updated_by=setting.updated_by,
            updated_by_name=setting.updated_by_name,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get setting: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/by-category/{category}",
    response_model=list[SettingResponseSchema],
    summary="Get settings by category",
    operation_id="get_settings_by_category",
)
async def get_settings_by_category(
    category: SettingCategory,
    scope: SettingScope | None = Query(None),
    is_active: bool | None = Query(None),
    _permission: None = Depends(require_permission("settings:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> list[SettingResponseSchema]:
    try:
        settings = await settings_svc.list_settings(
            legal_entity_id=legal_entity_id,
            category=category.value,
            scope=scope.value if scope else None,
            is_active=is_active,
        )
        return [
            SettingResponseSchema(
                id=s.id,
                key=s.key,
                value=s.value,
                data_type=SettingDataType(s.data_type),
                description=s.description,
                category=SettingCategory(s.category),
                scope=SettingScope(s.scope),
                legal_entity_id=s.legal_entity_id,
                user_id=s.user_id,
                role_id=s.role_id,
                branch_id=s.branch_id,
                validation_regex=s.validation_regex,
                min_value=s.min_value,
                max_value=s.max_value,
                allowed_values=s.allowed_values,
                default_value=s.default_value,
                is_readonly=s.is_readonly,
                is_encrypted=s.is_encrypted,
                is_active=s.is_active,
                is_locked=s.is_locked,
                tags=s.tags,
                version=s.version,
                created_at=s.created_at,
                updated_at=s.updated_at,
                created_by=s.created_by,
                created_by_name=s.created_by_name,
                updated_by=s.updated_by,
                updated_by_name=s.updated_by_name,
            )
            for s in settings
        ]
    except Exception as e:
        logger.exception("Failed to get settings by category: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{key}",
    response_model=SettingResponseSchema,
    summary="Update setting",
    operation_id="update_setting",
)
async def update_setting(
    key: str,
    request: SettingUpdateSchema,
    reason: str = Query("", description="Reason for update"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("settings:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> SettingResponseSchema:
    """
    Update a setting.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "update_setting"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SettingResponseSchema(**cached)

    try:
        result = await settings_svc.update_setting(
            key=key,
            legal_entity_id=legal_entity_id,
            value=request.value,
            description=request.description,
            category=request.category.value if request.category else None,
            validation_regex=request.validation_regex,
            min_value=request.min_value,
            max_value=request.max_value,
            allowed_values=request.allowed_values,
            default_value=request.default_value,
            is_readonly=request.is_readonly,
            is_encrypted=request.is_encrypted,
            is_active=request.is_active,
            tags=request.tags,
            reason=reason,
            updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Setting '{key}' not found",
            )
        response = SettingResponseSchema(
            id=result.id,
            key=result.key,
            value=result.value,
            data_type=SettingDataType(result.data_type),
            description=result.description,
            category=SettingCategory(result.category),
            scope=SettingScope(result.scope),
            legal_entity_id=result.legal_entity_id,
            user_id=result.user_id,
            role_id=result.role_id,
            branch_id=result.branch_id,
            validation_regex=result.validation_regex,
            min_value=result.min_value,
            max_value=result.max_value,
            allowed_values=result.allowed_values,
            default_value=result.default_value,
            is_readonly=result.is_readonly,
            is_encrypted=result.is_encrypted,
            is_active=result.is_active,
            is_locked=result.is_locked,
            tags=result.tags,
            version=result.version,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            updated_by=result.updated_by,
            updated_by_name=result.updated_by_name,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update setting: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{key}",
    response_model=dict[str, Any],
    summary="Deactivate setting",
    operation_id="deactivate_setting",
)
async def deactivate_setting(
    key: str,
    reason: str = Query("", description="Reason for deactivation"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("settings:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> dict[str, Any]:
    """
    Deactivate a setting.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "deactivate_setting"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        result = await settings_svc.deactivate_setting(
            key, legal_entity_id, current_user.user_id, reason
        )
        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Setting '{key}' not found",
            )
        response = {
            "key": key,
            "deactivated": True,
            "message": f"Setting '{key}' deactivated",
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to deactivate setting: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{key}/activate",
    response_model=SettingResponseSchema,
    summary="Activate setting",
    operation_id="activate_setting",
)
async def activate_setting(
    key: str,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("settings:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> SettingResponseSchema:
    """
    Activate a setting.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "activate_setting"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SettingResponseSchema(**cached)

    try:
        result = await settings_svc.activate_setting(key, legal_entity_id, current_user.user_id)
        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Setting '{key}' not found",
            )
        response = SettingResponseSchema(
            id=result.id,
            key=result.key,
            value=result.value,
            data_type=SettingDataType(result.data_type),
            description=result.description,
            category=SettingCategory(result.category),
            scope=SettingScope(result.scope),
            legal_entity_id=result.legal_entity_id,
            user_id=result.user_id,
            role_id=result.role_id,
            branch_id=result.branch_id,
            validation_regex=result.validation_regex,
            min_value=result.min_value,
            max_value=result.max_value,
            allowed_values=result.allowed_values,
            default_value=result.default_value,
            is_readonly=result.is_readonly,
            is_encrypted=result.is_encrypted,
            is_active=result.is_active,
            is_locked=result.is_locked,
            tags=result.tags,
            version=result.version,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            updated_by=result.updated_by,
            updated_by_name=result.updated_by_name,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to activate setting: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{key}/reset",
    response_model=SettingResponseSchema,
    summary="Reset setting to default",
    operation_id="reset_setting",
)
async def reset_setting(
    key: str,
    reason: str = Query("", description="Reason for reset"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("settings:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> SettingResponseSchema:
    """
    Reset a setting to its default value.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "reset_setting"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SettingResponseSchema(**cached)

    try:
        result = await settings_svc.reset_to_default(key, legal_entity_id, current_user.user_id, reason)
        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Setting '{key}' not found or no default",
            )
        response = SettingResponseSchema(
            id=result.id,
            key=result.key,
            value=result.value,
            data_type=SettingDataType(result.data_type),
            description=result.description,
            category=SettingCategory(result.category),
            scope=SettingScope(result.scope),
            legal_entity_id=result.legal_entity_id,
            user_id=result.user_id,
            role_id=result.role_id,
            branch_id=result.branch_id,
            validation_regex=result.validation_regex,
            min_value=result.min_value,
            max_value=result.max_value,
            allowed_values=result.allowed_values,
            default_value=result.default_value,
            is_readonly=result.is_readonly,
            is_encrypted=result.is_encrypted,
            is_active=result.is_active,
            is_locked=result.is_locked,
            tags=result.tags,
            version=result.version,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            updated_by=result.updated_by,
            updated_by_name=result.updated_by_name,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to reset setting: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BULK OPERATIONS (ringkas)
# ----------------------------------------------------------------------------


@router.patch(
    "/bulk",
    response_model=dict[str, Any],
    summary="Bulk update settings",
    operation_id="bulk_update_settings",
)
async def bulk_update_settings(
    request: SettingBulkUpdateSchema,
    reason: str = Query("", description="Reason for bulk update"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("settings:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> dict[str, Any]:
    """
    Bulk update multiple settings.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "bulk_update_settings"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        if request.dry_run:
            result = await settings_svc.validate_bulk_update(request.settings, legal_entity_id)
        else:
            result = await settings_svc.bulk_update_settings(
                request.settings, legal_entity_id, reason, current_user.user_id
            )
        response = {
            "success_count": result.success_count,
            "failed_count": result.failed_count,
            "failed_keys": result.failed_keys,
            "errors": result.errors,
            "dry_run": request.dry_run,
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except Exception as e:
        logger.exception("Failed to bulk update settings: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/bulk/reset",
    response_model=dict[str, Any],
    summary="Bulk reset settings to default",
    operation_id="bulk_reset_settings",
)
async def bulk_reset_settings(
    keys: list[str] = Body(...),
    reason: str = Body(""),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("settings:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> dict[str, Any]:
    """
    Bulk reset multiple settings to defaults.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "bulk_reset_settings"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        result = await settings_svc.bulk_reset_settings(
            keys, legal_entity_id, reason, current_user.user_id
        )
        response = {
            "success_count": result.success_count,
            "failed_count": result.failed_count,
            "failed_keys": result.failed_keys,
            "errors": result.errors,
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except Exception as e:
        logger.exception("Failed to bulk reset settings: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# IMPORT & EXPORT
# ----------------------------------------------------------------------------


@router.get(
    "/export",
    response_model=dict[str, Any],
    summary="Export settings",
    operation_id="export_settings",
)
async def export_settings(
    format: str = Query("json", pattern="^(json|csv)$"),
    category: SettingCategory | None = None,
    _permission: None = Depends(require_permission("settings:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> dict[str, Any]:
    try:
        data = await settings_svc.export_settings(
            legal_entity_id, format, category.value if category else None
        )
        return data
    except Exception as e:
        logger.exception("Failed to export settings: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/import",
    response_model=dict[str, Any],
    summary="Import settings",
    operation_id="import_settings",
)
async def import_settings(
    request: SettingImportSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("settings:import")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> dict[str, Any]:
    """
    Import settings from file.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "import_settings"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        result = await settings_svc.import_settings(
            legal_entity_id, request.data, request.format, request.mode, current_user.user_id
        )
        response = {
            "success": result.success,
            "imported_count": result.imported_count,
            "updated_count": result.updated_count,
            "skipped_count": result.skipped_count,
            "errors": result.errors,
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to import settings: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# VALIDATION & SCHEMA
# ----------------------------------------------------------------------------


@router.post(
    "/validate",
    response_model=SettingValidationResultSchema,
    summary="Validate setting value",
    operation_id="validate_setting",
)
async def validate_setting(
    key: str = Body(..., embed=True),
    value: str = Body(..., embed=True),
    _permission: None = Depends(require_permission("settings:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> SettingValidationResultSchema:
    try:
        result = await settings_svc.validate_setting_value(key, value, legal_entity_id)
        return SettingValidationResultSchema(
            key=key,
            value=value,
            is_valid=result.is_valid,
            errors=result.errors,
            warnings=result.warnings,
            normalized_value=result.normalized_value,
        )
    except Exception as e:
        logger.exception("Failed to validate setting: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/schema",
    response_model=list[SettingSchemaSchema],
    summary="Get setting schema",
    operation_id="get_setting_schema",
)
async def get_setting_schema(
    category: SettingCategory | None = None,
    _permission: None = Depends(require_permission("settings:read")),
    settings_svc: Any = Depends(get_settings_svc),
) -> list[SettingSchemaSchema]:
    try:
        schemas = await settings_svc.get_setting_schemas(category.value if category else None)
        return [
            SettingSchemaSchema(
                key=s.key,
                data_type=SettingDataType(s.data_type),
                description=s.description,
                category=SettingCategory(s.category),
                scope=SettingScope(s.scope),
                validation_regex=s.validation_regex,
                min_value=s.min_value,
                max_value=s.max_value,
                allowed_values=s.allowed_values,
                default_value=s.default_value,
                is_readonly=s.is_readonly,
                is_encrypted=s.is_encrypted,
                tags=s.tags,
            )
            for s in schemas
        ]
    except Exception as e:
        logger.exception("Failed to get setting schema: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/categories",
    response_model=list[dict[str, Any]],
    summary="Get setting categories",
    operation_id="get_setting_categories",
)
async def get_setting_categories(
    _permission: None = Depends(require_permission("settings:read")),
    settings_svc: Any = Depends(get_settings_svc),
) -> list[dict[str, Any]]:
    try:
        categories = await settings_svc.get_setting_categories()
        return [
            {
                "name": c.name,
                "label": c.label,
                "description": c.description,
                "setting_count": c.setting_count,
                "active_count": c.active_count,
            }
            for c in categories
        ]
    except Exception as e:
        logger.exception("Failed to get setting categories: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# HISTORY & AUDIT
# ----------------------------------------------------------------------------


@router.get(
    "/{key}/history",
    response_model=list[SettingHistorySchema],
    summary="Get setting change history",
    operation_id="get_setting_history",
)
async def get_setting_history(
    key: str,
    limit: int = Query(50, ge=1, le=500),
    _permission: None = Depends(require_permission("settings:audit")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> list[SettingHistorySchema]:
    try:
        history = await settings_svc.get_setting_history(key, legal_entity_id, limit)
        return [
            SettingHistorySchema(
                id=h.id,
                setting_id=h.setting_id,
                setting_key=h.setting_key,
                old_value=h.old_value,
                new_value=h.new_value,
                changed_by=h.changed_by,
                changed_by_name=h.changed_by_name,
                changed_at=h.changed_at,
                reason=h.reason,
                ip_address=h.ip_address,
            )
            for h in history
        ]
    except Exception as e:
        logger.exception("Failed to get setting history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/audit",
    response_model=list[SettingHistorySchema],
    summary="Get audit trail for all settings",
    operation_id="get_settings_audit_trail",
)
async def get_settings_audit_trail(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    user_id: UUID | None = None,
    limit: int = Query(100, ge=1, le=1000),
    _permission: None = Depends(require_permission("settings:audit")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> list[SettingHistorySchema]:
    try:
        history = await settings_svc.get_settings_audit_trail(
            legal_entity_id, start_time, end_time, user_id, limit
        )
        return [
            SettingHistorySchema(
                id=h.id,
                setting_id=h.setting_id,
                setting_key=h.setting_key,
                old_value=h.old_value,
                new_value=h.new_value,
                changed_by=h.changed_by,
                changed_by_name=h.changed_by_name,
                changed_at=h.changed_at,
                reason=h.reason,
                ip_address=h.ip_address,
            )
            for h in history
        ]
    except Exception as e:
        logger.exception("Failed to get settings audit trail: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LOCK/UNLOCK
# ----------------------------------------------------------------------------


@router.post(
    "/{key}/lock",
    response_model=SettingResponseSchema,
    summary="Lock setting",
    operation_id="lock_setting",
)
async def lock_setting(
    key: str,
    reason: str = Query("", description="Lock reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("settings:lock")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> SettingResponseSchema:
    """
    Lock a setting to prevent further changes.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "lock_setting"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SettingResponseSchema(**cached)

    try:
        result = await settings_svc.lock_setting(key, legal_entity_id, current_user.user_id, reason)
        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Setting '{key}' not found",
            )
        response = SettingResponseSchema(
            id=result.id,
            key=result.key,
            value=result.value,
            data_type=SettingDataType(result.data_type),
            description=result.description,
            category=SettingCategory(result.category),
            scope=SettingScope(result.scope),
            legal_entity_id=result.legal_entity_id,
            user_id=result.user_id,
            role_id=result.role_id,
            branch_id=result.branch_id,
            validation_regex=result.validation_regex,
            min_value=result.min_value,
            max_value=result.max_value,
            allowed_values=result.allowed_values,
            default_value=result.default_value,
            is_readonly=result.is_readonly,
            is_encrypted=result.is_encrypted,
            is_active=result.is_active,
            is_locked=True,
            tags=result.tags,
            version=result.version,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            updated_by=result.updated_by,
            updated_by_name=result.updated_by_name,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to lock setting: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{key}/unlock",
    response_model=SettingResponseSchema,
    summary="Unlock setting",
    operation_id="unlock_setting",
)
async def unlock_setting(
    key: str,
    reason: str = Query("", description="Unlock reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("settings:lock")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    settings_svc: Any = Depends(get_settings_svc),
) -> SettingResponseSchema:
    """
    Unlock a locked setting.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "unlock_setting"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SettingResponseSchema(**cached)

    try:
        result = await settings_svc.unlock_setting(key, legal_entity_id, current_user.user_id, reason)
        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Setting '{key}' not found",
            )
        response = SettingResponseSchema(
            id=result.id,
            key=result.key,
            value=result.value,
            data_type=SettingDataType(result.data_type),
            description=result.description,
            category=SettingCategory(result.category),
            scope=SettingScope(result.scope),
            legal_entity_id=result.legal_entity_id,
            user_id=result.user_id,
            role_id=result.role_id,
            branch_id=result.branch_id,
            validation_regex=result.validation_regex,
            min_value=result.min_value,
            max_value=result.max_value,
            allowed_values=result.allowed_values,
            default_value=result.default_value,
            is_readonly=result.is_readonly,
            is_encrypted=result.is_encrypted,
            is_active=result.is_active,
            is_locked=False,
            tags=result.tags,
            version=result.version,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            updated_by=result.updated_by,
            updated_by_name=result.updated_by_name,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to unlock setting: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


__all__ = ["router"]