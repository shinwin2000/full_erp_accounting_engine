#!/usr/bin/env python3
"""Unit test untuk Coretax API client adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError, CoreTaxOAuth2Client


class TestCoreTaxApiClient:
    @pytest.mark.asyncio
    async def test_get_token_success(self):
        # Mock redis client agar cache miss (return None)
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        # Patch method _get_redis dan _initialize_secrets (yang memanggil asyncio.run)
        with patch.object(CoreTaxOAuth2Client, "_get_redis", AsyncMock(return_value=mock_redis)):
            with patch.object(CoreTaxOAuth2Client, "_initialize_secrets", return_value=None):
                client = CoreTaxOAuth2Client(env="sandbox")
                with patch.object(
                    client, "_fetch_new_token", AsyncMock(return_value=("abc123", 3600))
                ):
                    token = await client.get_access_token()
                    assert token == "abc123"

                    @pytest.mark.asyncio
                    async def test_get_token_failure(self):
                        mock_redis = AsyncMock()
                        mock_redis.get = AsyncMock(return_value=None)

                        with patch.object(
                            CoreTaxOAuth2Client, "_get_redis", AsyncMock(return_value=mock_redis)
                        ), patch.object(
                            CoreTaxOAuth2Client, "_initialize_secrets", return_value=None
                        ):
                            client = CoreTaxOAuth2Client(env="sandbox")
                            with (
                                patch.object(
                                    client,
                                    "_fetch_new_token",
                                    AsyncMock(
                                        side_effect=CoretaxAuthError("Failed to obtain token")
                                    ),
                                ),
                                pytest.raises(CoretaxAuthError, match="Failed to obtain token"),
                            ):
                                await client.get_access_token()
