from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.session_factory_sqlalchemy import (
    get_session_factory_sync,
)


def async_session_maker():
    """
    Compatibility adapter untuk legacy consumers.
    """
    factory = get_session_factory_sync()
    session_maker = factory.get_session_factory()

    if session_maker is None:
        raise RuntimeError(
            "SQLAlchemy async session factory belum diinisialisasi"
        )

    session: AsyncSession = session_maker()
    return session


__all__ = ["async_session_maker"]
