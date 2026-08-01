"""
Patch script v2: perbaiki endpoint refresh_token di fastapi_iam_router.py.

Cara pakai:
    cd E:\\full_erp_accounting_engine
    python patch_refresh2.py
"""
from pathlib import Path

TARGET = Path("adapters/primary_api/v1/fastapi_iam_router.py")

OLD_SCHEMA = (
    'class RefreshTokenRequestSchema(BaseModel):\n'
    '    """Schema untuk refresh token."""\n'
    '\n'
    '    model_config = ConfigDict(from_attributes=True)\n'
    '\n'
    '    refresh_token: str = Field(..., description="Refresh token")\n'
)

NEW_SCHEMA = (
    'class RefreshTokenRequestSchema(BaseModel):\n'
    '    """Schema untuk refresh token."""\n'
    '\n'
    '    model_config = ConfigDict(from_attributes=True)\n'
    '\n'
    '    refresh_token: str = Field(..., description="Refresh token")\n'
    '\n'
    '\n'
    'class TokenRefreshResponseSchema(BaseModel):\n'
    '    """Schema respons untuk refresh token (hanya token baru, bukan seluruh user)."""\n'
    '\n'
    '    access_token: str\n'
    '    refresh_token: str\n'
    '    token_type: str = "bearer"\n'
    '    expires_in: int = 3600\n'
)

OLD_ENDPOINT = (
    '@router.post(\n'
    '    "/refresh",\n'
    '    response_model=LoginResponseSchema,\n'
    '    summary="Refresh access token",\n'
    '    operation_id="refresh_token",\n'
    ')\n'
    'async def refresh_token(\n'
    '    request: RefreshTokenRequestSchema,\n'
    '    service: Any = Depends(get_iam_service),\n'
    ') -> LoginResponseSchema:\n'
    '    """Refresh access token using refresh token."""\n'
    '    try:\n'
    '        result = await service.refresh_access_token(request.refresh_token)\n'
    '\n'
    '        # FIX: Jangan log token\n'
    '        logger.info("Session refreshed successfully")\n'
    '\n'
    '        return LoginResponseSchema(\n'
    '            access_token=result.access_token,\n'
    '            refresh_token=result.refresh_token,\n'
    '            expires_in=result.expires_in,\n'
    '            user=UserResponseSchema(\n'
    '                id=result.user.id,\n'
    '                username=result.user.username,\n'
    '                email=result.user.email,\n'
    '                full_name=result.user.full_name,\n'
    '                department=result.user.department,\n'
    '                job_title=result.user.job_title,\n'
    '                phone_number=result.user.phone_number,\n'
    '                status=result.user.status,\n'
    '                is_active=result.user.is_active,\n'
    '                is_locked=result.user.is_locked,\n'
    '                is_superuser=result.user.is_superuser,\n'
    '                must_change_password=result.user.must_change_password,\n'
    '                mfa_enabled=result.user.mfa_enabled,\n'
    '                last_login_at=result.user.last_login_at,\n'
    '                last_password_change=result.user.last_password_change,\n'
    '                legal_entity_ids=result.user.legal_entity_ids,\n'
    '                role_ids=result.user.role_ids,\n'
    '                notes=result.user.notes,\n'
    '                created_at=result.user.created_at,\n'
    '                updated_at=result.user.updated_at,\n'
    '                created_by=result.user.created_by,\n'
    '                created_by_name=result.user.created_by_name,\n'
    '                version=result.user.version,\n'
    '            ),\n'
    '        )\n'
    '    except ValueError'
)

NEW_ENDPOINT = (
    '@router.post(\n'
    '    "/refresh",\n'
    '    response_model=TokenRefreshResponseSchema,\n'
    '    summary="Refresh access token",\n'
    '    operation_id="refresh_token",\n'
    ')\n'
    'async def refresh_token(\n'
    '    request: RefreshTokenRequestSchema,\n'
    '    service: Any = Depends(get_iam_service),\n'
    ') -> TokenRefreshResponseSchema:\n'
    '    """Refresh access token using refresh token."""\n'
    '    try:\n'
    '        new_access_token = await service.refresh_access_token(request.refresh_token)\n'
    '\n'
    '        # FIX: Jangan log token\n'
    '        logger.info("Session refreshed successfully")\n'
    '\n'
    '        return TokenRefreshResponseSchema(\n'
    '            access_token=new_access_token,\n'
    '            refresh_token=request.refresh_token,\n'
    '        )\n'
    '    except ValueError'
)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    if OLD_SCHEMA not in text:
        print("GAGAL: blok schema lama tidak ditemukan persis.")
    else:
        text = text.replace(OLD_SCHEMA, NEW_SCHEMA, 1)
        print("Schema TokenRefreshResponseSchema berhasil ditambahkan.")

    if OLD_ENDPOINT not in text:
        print("GAGAL: blok endpoint refresh_token lama tidak ditemukan persis.")
        return
    else:
        text = text.replace(OLD_ENDPOINT, NEW_ENDPOINT, 1)
        print("Endpoint refresh_token berhasil diperbaiki.")

    TARGET.write_text(text, encoding="utf-8")
    print("Selesai. File tersimpan:", TARGET)


if __name__ == "__main__":
    main()
