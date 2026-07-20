from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

# Adapter untuk repository (berada di adapters)
from adapters.secondary_impl.dummy_iam import IAMRepositoryAdapter
from application.service_layer.service_iam import IAMService
from ports.primary.iam_repository_port import IAMRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("erp_engine")


class DummyTokenIssuer:
    async def create_access_token(self, user_id, username, legal_entity_id, roles, permissions, expires_delta=None):
        return "dummy_access_token"

    async def create_refresh_token(self, user_id, username, legal_entity_id, roles, permissions, expires_delta=None):
        return "dummy_refresh_token"

    async def verify_token(self, token, token_type="access"):
        return {
            "sub": str(uuid.uuid4()),
            "username": "dummy",
            "legal_entity_id": None,
            "roles": [],
            "permissions": []
        }


class DummyUOW:
    async def commit(self):
        pass

    async def rollback(self):
        pass


async def setup_iam_service(app: FastAPI) -> None:
    """
    Inisialisasi IAMService dan attach ke app.state.iam_service.
    Mengambil repository dan UOW dari container yang sudah ada di app.state.container.
    """
    try:
        container = app.state.container

        # 1. Resolve IAMRepositoryPort
        raw_repo = await container.resolve_async(IAMRepositoryPort)
        logger.info(f"Resolved repository: {type(raw_repo).__name__}")

        # 2. Bungkus dengan adapter jika repository tidak memiliki method 'get'
        if not hasattr(raw_repo, 'get'):
            logger.warning("Repository does not have 'get' method. Wrapping with adapter.")
            iam_repo = IAMRepositoryAdapter(raw_repo)
        else:
            iam_repo = raw_repo

        # 3. Resolve UnitOfWorkPort
        try:
            uow = await container.resolve_async(UnitOfWorkPort)
            if not hasattr(uow, 'commit'):
                logger.warning("UOW has no commit method. Using dummy.")
                uow = DummyUOW()
        except Exception as e:
            logger.warning(f"UOW not found in container: {e}. Using dummy.")
            uow = DummyUOW()

        # 4. Komponen lain (dummy untuk sementara)
        token_issuer = DummyTokenIssuer()
        event_publisher = None
        cache = None

        # 5. Buat IAMService
        iam_service = IAMService(
            iam_repo=iam_repo,
            uow=uow,
            event_publisher=event_publisher,
            token_issuer=token_issuer,
            cache=cache,
        )
        app.state.iam_service = iam_service
        logger.info("IAMService initialized successfully ✓")

    except Exception as e:
        logger.error(f"Failed to initialize IAMService: {e}", exc_info=True)
        app.state.iam_service = None
