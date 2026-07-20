#!/usr/bin/env python3
"""
tests/application/test_app_factory.py
Test untuk application/app_factory.py
Mencakup: ContainerProtocol, DummyContainer, ApplicationFactory,
create_app, shutdown_app
"""

from unittest.mock import MagicMock

import pytest

from application.app_factory import (
    ApplicationFactory,
    ContainerProtocol,
    DummyContainer,
    create_app,
    shutdown_app,
)


class TestContainerProtocol:
    def test_class_defined(self):
        assert ContainerProtocol is not None
        # ContainerProtocol should be a class (or protocol)
        assert isinstance(ContainerProtocol, type) or hasattr(ContainerProtocol, "__abstractmethods__")


class TestDummyContainer:
    def test_construction(self):
        instance = DummyContainer()
        assert isinstance(instance, DummyContainer)

    def test_resolve_returns_default(self):
        instance = DummyContainer()
        default = MagicMock()
        result = instance.resolve(name="non_existent", default=default)
        assert result is default

    def test_get_registered_types_returns_dict(self):
        instance = DummyContainer()
        result = instance.get_registered_types()
        assert isinstance(result, dict)

    def test_register_instance_returns_true(self):
        instance = DummyContainer()
        mock_obj = MagicMock()
        result = instance.register_instance(key="test_key", instance=mock_obj)
        assert result is True
        # Check that it was stored (assuming resolve can retrieve it)
        retrieved = instance.resolve(name="test_key")
        assert retrieved is mock_obj

    def test_register_singleton_returns_true(self):
        instance = DummyContainer()
        result = instance.register_singleton(key="singleton_key")
        assert result is True
        # Resolve twice should return same object
        obj1 = instance.resolve(name="singleton_key")
        obj2 = instance.resolve(name="singleton_key")
        assert obj1 is obj2


class TestApplicationFactory:
    @pytest.fixture
    def factory(self):
        return ApplicationFactory(config={"test": "value"}, container=DummyContainer())

    def test_construction(self, factory):
        assert isinstance(factory, ApplicationFactory)
        assert factory.config == {"test": "value"}
        assert isinstance(factory.container, DummyContainer)

    @pytest.mark.asyncio
    async def test_initialize_returns_self(self, factory):
        result = await factory.initialize()
        assert result is factory
        # Check that container now has some registered items (if any)
        # At minimum, container should have some registrations
        registered = factory.container.get_registered_types()
        assert isinstance(registered, dict)

    @pytest.mark.asyncio
    async def test_shutdown_returns_true(self, factory):
        await factory.initialize()  # ensure initialized
        result = await factory.shutdown()
        assert result is True


@pytest.mark.asyncio
async def test_create_app_returns_application_factory():
    container = DummyContainer()
    config = {"env": "test"}
    app = await create_app(config=config, container=container)
    assert isinstance(app, ApplicationFactory)
    assert app.config == config
    assert app.container is container


@pytest.mark.asyncio
async def test_shutdown_app_returns_true():
    container = DummyContainer()
    result = await shutdown_app(container=container)
    assert result is True
