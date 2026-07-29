#!/usr/bin/env python3
"""
tests/bootstrap/dependency_container/test_adapter_registry.py
Comprehensive tests for bootstrap/dependency_container/adapter_registry.py

Covers:
- AdapterRegistry: __init__, set_container, register_all
- Private methods: _discover_ports, _discover_implementations, _find_implementation_by_name,
  _match_port_to_implementation, _match_by_base_name, _build_factory, _build_stub_factory
- Singleton accessors: get_adapter_registry, set_adapter_registry_instance
- Edge cases: container not set, already registered, manual mapping, auto matching, stub generation
- Factory building with special cases (CoreTaxPort, SnapshotStorePort, HashChainServicePort)
- Error conditions: port not found, implementations not found, abstract class detection
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bootstrap.dependency_container.adapter_registry import (
    AdapterRegistry,
    get_adapter_registry,
    set_adapter_registry_instance,
)
from bootstrap.dependency_container.ioc_container import IoCContainer

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_container():
    container = MagicMock(spec=IoCContainer)
    container.has_registration.return_value = False
    container.remove.return_value = None
    container.register_singleton.return_value = None
    return container


@pytest.fixture
def registry(mock_container):
    return AdapterRegistry(container=mock_container)


@pytest.fixture
def mock_path():
    with patch("bootstrap.dependency_container.adapter_registry.Path") as mock_path:
        # Mock the root Path
        root = MagicMock(spec=Path)
        root.exists.return_value = True
        root.glob.return_value = []
        mock_path.return_value.resolve.return_value.parent.parent.parent = root
        mock_path.return_value = root
        yield root


# ============================================================================
# Tests for AdapterRegistry
# ============================================================================

class TestAdapterRegistryInit:
    def test_init_with_container(self, mock_container):
        reg = AdapterRegistry(container=mock_container)
        assert reg._container is mock_container
        assert reg._is_registered is False
        assert reg._registered_ports == set()
        assert isinstance(reg._manual_mapping, dict)
        assert "CoreTaxPort" in reg._manual_mapping

    def test_init_without_container(self):
        reg = AdapterRegistry()
        assert reg._container is None
        assert reg._is_registered is False

    def test_set_container(self, registry, mock_container):
        registry.set_container(mock_container)
        assert registry._container is mock_container


class TestAdapterRegistryRegisterAll:
    def test_register_all_container_not_set(self, registry):
        registry._container = None
        with pytest.raises(RuntimeError, match="Container not set"):
            registry.register_all()

    def test_register_all_already_registered(self, registry, mock_container):
        registry._is_registered = True
        registry.register_all()
        # Should return early, no actions
        assert registry._is_registered is True
        mock_container.register_singleton.assert_not_called()

    def test_register_all_with_no_ports(self, registry, mock_container):
        with patch.object(registry, "_discover_ports", return_value=[]):
            with patch.object(registry, "_discover_implementations", return_value=[]):
                registry.register_all()
                assert registry._is_registered is True
                mock_container.register_singleton.assert_not_called()

    def test_register_all_with_manual_mapping(self, registry, mock_container):
        # Create a mock port
        class MyPort:
            pass

        # Create a mock implementation
        class MyImpl:
            pass

        ports = [MyPort]
        implementations = [MyImpl]
        registry._manual_mapping["MyPort"] = "MyImpl"

        with patch.object(registry, "_discover_ports", return_value=ports):
            with patch.object(registry, "_discover_implementations", return_value=implementations):
                with patch.object(registry, "_build_factory", return_value=lambda: MyImpl()) as mock_factory:
                    registry.register_all()
                    mock_container.register_singleton.assert_called_once_with(MyPort, factory=mock_factory.return_value)
                    assert MyPort in registry._registered_ports

    def test_register_all_with_auto_matching(self, registry, mock_container):
        class MyPort:
            pass

        class MyRepository:
            pass

        ports = [MyPort]
        implementations = [MyRepository]

        with patch.object(registry, "_discover_ports", return_value=ports):
            with patch.object(registry, "_discover_implementations", return_value=implementations):
                with patch.object(registry, "_match_port_to_implementation", return_value=MyRepository):
                    with patch.object(registry, "_build_factory", return_value=lambda: MyRepository()) as mock_factory:
                        registry.register_all()
                        mock_container.register_singleton.assert_called_once_with(MyPort, factory=mock_factory.return_value)

    def test_register_all_direct_match(self, registry, mock_container):
        class MyPort:
            pass

        ports = [MyPort]
        implementations = [MyPort]  # same name

        with patch.object(registry, "_discover_ports", return_value=ports):
            with patch.object(registry, "_discover_implementations", return_value=implementations):
                with patch.object(registry, "_match_port_to_implementation", return_value=None):
                    with patch.object(registry, "_find_implementation_by_name", return_value=MyPort):
                        with patch.object(registry, "_build_factory", return_value=lambda: MyPort()) as mock_factory:
                            registry.register_all()
                            mock_container.register_singleton.assert_called_once_with(MyPort, factory=mock_factory.return_value)

    def test_register_all_stub_generation(self, registry, mock_container):
        class MyPort:
            pass

        ports = [MyPort]
        implementations = []

        with patch.object(registry, "_discover_ports", return_value=ports):
            with patch.object(registry, "_discover_implementations", return_value=implementations):
                with patch.object(registry, "_build_stub_factory", return_value=lambda: MyPort()) as mock_stub:
                    registry.register_all()
                    mock_container.register_singleton.assert_called_once_with(MyPort, factory=mock_stub.return_value)

    def test_register_all_removes_existing_registration(self, registry, mock_container):
        class MyPort:
            pass

        mock_container.has_registration.return_value = True
        ports = [MyPort]
        implementations = []

        with patch.object(registry, "_discover_ports", return_value=ports):
            with patch.object(registry, "_discover_implementations", return_value=implementations):
                with patch.object(registry, "_build_stub_factory", return_value=lambda: MyPort()):
                    registry.register_all()
                    mock_container.remove.assert_called_once_with(MyPort)
                    mock_container.register_singleton.assert_called_once()


class TestAdapterRegistryPrivateDiscovery:
    def test_discover_ports(self, registry, mock_path):
        # Mock files
        file1 = MagicMock(spec=Path)
        file1.name = "test_port.py"
        file1.glob.return_value = [file1]
        file1.relative_to.return_value.with_suffix.return_value = Path("ports/primary/test_port")

        root = mock_path
        root.glob.return_value = [file1]
        # We need to mock the base directories
        with patch("bootstrap.dependency_container.adapter_registry.Path") as mock_path_cls:
            mock_path_cls.return_value.resolve.return_value.parent.parent.parent = root
            # We need to mock the import_module
            with patch("bootstrap.dependency_container.adapter_registry.importlib.import_module") as mock_import:
                # Create a mock module with a class
                class MyPort:
                    pass
                # Make it abstract
                MyPort.__abstractmethods__ = frozenset(["method"])
                mock_module = MagicMock()
                mock_module.MyPort = MyPort
                mock_import.return_value = mock_module

                ports = registry._discover_ports()
                assert len(ports) == 1
                assert ports[0] is MyPort

    def test_discover_ports_skips_init(self, registry, mock_path):
        file_init = MagicMock(spec=Path)
        file_init.name = "__init__.py"
        mock_path.glob.return_value = [file_init]
        with patch("bootstrap.dependency_container.adapter_registry.importlib.import_module") as mock_import:
            ports = registry._discover_ports()
            assert ports == []
            mock_import.assert_not_called()

    def test_discover_ports_skips_non_abstract(self, registry, mock_path):
        file1 = MagicMock(spec=Path)
        file1.name = "test_port.py"
        mock_path.glob.return_value = [file1]
        with patch("bootstrap.dependency_container.adapter_registry.importlib.import_module") as mock_import:
            class ConcretePort:
                pass
            mock_module = MagicMock()
            mock_module.ConcretePort = ConcretePort
            mock_import.return_value = mock_module
            ports = registry._discover_ports()
            assert ports == []

    def test_discover_ports_exclude_keywords(self, registry, mock_path):
        file1 = MagicMock(spec=Path)
        file1.name = "test_port.py"
        mock_path.glob.return_value = [file1]
        with patch("bootstrap.dependency_container.adapter_registry.importlib.import_module") as mock_import:
            class InMemoryPort:
                pass
            InMemoryPort.__abstractmethods__ = frozenset(["method"])
            mock_module = MagicMock()
            mock_module.InMemoryPort = InMemoryPort
            mock_import.return_value = mock_module
            ports = registry._discover_ports()
            assert ports == []

    def test_discover_implementations(self, registry, mock_path):
        # We'll mock the search directories
        with patch("bootstrap.dependency_container.adapter_registry.Path") as mock_path_cls:
            root = MagicMock(spec=Path)
            root.exists.return_value = True
            root.glob.return_value = []
            mock_path_cls.return_value.resolve.return_value.parent.parent.parent = root

            # Simulate some files in adapters
            file1 = MagicMock(spec=Path)
            file1.name = "my_impl.py"
            file1.relative_to.return_value.with_suffix.return_value = Path("adapters/my_impl")

            root.glob.return_value = [file1]

            with patch("bootstrap.dependency_container.adapter_registry.importlib.import_module") as mock_import:
                class MyImplementation:
                    pass
                mock_module = MagicMock()
                mock_module.MyImplementation = MyImplementation
                mock_import.return_value = mock_module

                impls = registry._discover_implementations()
                assert len(impls) == 1
                assert impls[0] is MyImplementation

    def test_discover_implementations_skips_abstract(self, registry, mock_path):
        with patch("bootstrap.dependency_container.adapter_registry.Path") as mock_path_cls:
            root = MagicMock(spec=Path)
            root.exists.return_value = True
            root.glob.return_value = []
            mock_path_cls.return_value.resolve.return_value.parent.parent.parent = root

            file1 = MagicMock(spec=Path)
            file1.name = "my_impl.py"
            root.glob.return_value = [file1]

            with patch("bootstrap.dependency_container.adapter_registry.importlib.import_module") as mock_import:
                class AbstractImpl:
                    __abstractmethods__ = frozenset(["method"])
                mock_module = MagicMock()
                mock_module.AbstractImpl = AbstractImpl
                mock_import.return_value = mock_module

                impls = registry._discover_implementations()
                assert impls == []

    def test_discover_implementations_skips_keywords(self, registry, mock_path):
        with patch("bootstrap.dependency_container.adapter_registry.Path") as mock_path_cls:
            root = MagicMock(spec=Path)
            root.exists.return_value = True
            root.glob.return_value = []
            mock_path_cls.return_value.resolve.return_value.parent.parent.parent = root

            file1 = MagicMock(spec=Path)
            file1.name = "my_impl.py"
            root.glob.return_value = [file1]

            with patch("bootstrap.dependency_container.adapter_registry.importlib.import_module") as mock_import:
                class StubImpl:
                    pass
                mock_module = MagicMock()
                mock_module.StubImpl = StubImpl
                mock_import.return_value = mock_module

                impls = registry._discover_implementations()
                assert impls == []

    def test_find_implementation_by_name(self, registry):
        class ImplA:
            pass
        class ImplB:
            pass
        impls = [ImplA, ImplB]
        found = registry._find_implementation_by_name(impls, "ImplA")
        assert found is ImplA
        found = registry._find_implementation_by_name(impls, "Missing")
        assert found is None

    def test_match_port_to_implementation(self, registry):
        class MyPort:
            pass
        class MyRepository:
            pass
        class MyAdapter:
            pass
        class MyImpl:
            pass

        impls = [MyRepository, MyAdapter, MyImpl]
        with patch.object(registry, "_match_by_base_name", return_value=MyRepository) as mock_match:
            result = registry._match_port_to_implementation(MyPort, impls)
            assert result is MyRepository
            mock_match.assert_called_once_with("MyPort", impls)

        # Test with Protocol suffix
        class MyProtocol:
            pass
        with patch.object(registry, "_match_by_base_name", return_value=MyAdapter) as mock_match:
            result = registry._match_port_to_implementation(MyProtocol, impls)
            assert result is MyAdapter
            mock_match.assert_called_once_with("My", impls)  # "MyProtocol" -> remove "Protocol" -> "My"

    def test_match_by_base_name(self, registry):
        class SQLAlchemyMyRepository:
            pass
        class MyRepository:
            pass
        class MyAdapter:
            pass
        class MyImpl:
            pass
        class MyOther:
            pass
        class MyPort:
            pass

        impls = [SQLAlchemyMyRepository, MyRepository, MyAdapter, MyImpl, MyOther, MyPort]

        # Test SQLAlchemy priority (score 10)
        result = registry._match_by_base_name("My", impls)
        assert result is SQLAlchemyMyRepository

        # Test without SQLAlchemy
        impls_no_sql = [MyRepository, MyAdapter, MyImpl, MyOther]
        result = registry._match_by_base_name("My", impls_no_sql)
        assert result is MyRepository  # score 8

        # Test when only Adapter exists
        impls_adapter = [MyAdapter]
        result = registry._match_by_base_name("My", impls_adapter)
        assert result is MyAdapter  # score 7

        # Test when only Impl exists
        impls_impl = [MyImpl]
        result = registry._match_by_base_name("My", impls_impl)
        assert result is MyImpl  # score 6

        # Test when only exact match exists but not ending with Repository
        impls_exact = [MyOther]
        result = registry._match_by_base_name("MyOther", impls_exact)
        assert result is MyOther  # score 5

        # Test no match
        impls_empty = []
        result = registry._match_by_base_name("My", impls_empty)
        assert result is None

        # Test with empty base name
        result = registry._match_by_base_name("", impls)
        assert result is None

    def test_build_factory_general(self, registry):
        class MyImpl:
            def __init__(self, session=None):
                self.session = session

        port = MagicMock()
        port.__name__ = "MyPort"
        factory = registry._build_factory(port, MyImpl)
        assert callable(factory)
        instance = factory()
        assert isinstance(instance, MyImpl)

        # With required parameters
        class MyImplRequired:
            def __init__(self, required_param):
                self.required = required_param

        factory = registry._build_factory(port, MyImplRequired)
        instance = factory()
        assert instance.required is None  # because we pass None for required params

    def test_build_factory_special_cases(self, registry):
        # CoreTaxPort special case
        class TaxAuthorityCoretaxAdapter:
            def __init__(self, session=None):
                self.session = session

        port = MagicMock()
        port.__name__ = "CoreTaxPort"
        factory = registry._build_factory(port, TaxAuthorityCoretaxAdapter)
        instance = factory()
        assert isinstance(instance, TaxAuthorityCoretaxAdapter)

        # With session required (no default)
        class TaxAuthorityCoretaxAdapterNoDefault:
            def __init__(self, session):
                self.session = session

        factory = registry._build_factory(port, TaxAuthorityCoretaxAdapterNoDefault)
        instance = factory()
        assert instance.session is None

        # SnapshotStorePort special case
        class PostgresSnapshotStore:
            pass

        port2 = MagicMock()
        port2.__name__ = "SnapshotStorePort"
        factory = registry._build_factory(port2, PostgresSnapshotStore)
        instance = factory()
        assert isinstance(instance, PostgresSnapshotStore)

        # HashChainServicePort special case
        class HashChainServiceAdapter:
            def __init__(self, chain_type, chain_id):
                self.chain_type = chain_type
                self.chain_id = chain_id

        port3 = MagicMock()
        port3.__name__ = "HashChainServicePort"
        factory = registry._build_factory(port3, HashChainServiceAdapter)
        instance = factory()
        assert instance.chain_type == "default"
        assert instance.chain_id == "default"

    def test_build_factory_raises_if_impl_is_port(self, registry):
        port = MagicMock()
        port.__name__ = "MyPort"
        impl = MagicMock()
        impl.__name__ = "MyPort"
        with pytest.raises(RuntimeError, match="CRITICAL"):
            registry._build_factory(port, impl)

    def test_build_stub_factory(self, registry):
        # Create an abstract port with abstract methods
        class MyPort:
            __abstractmethods__ = frozenset(["method1", "method2"])
            def method1(self):
                pass
            def method2(self):
                pass

        # Mock the port module
        with patch("bootstrap.dependency_container.adapter_registry.importlib.import_module") as mock_import:
            mock_module = MagicMock()
            mock_module.MyPort = MyPort
            mock_import.return_value = mock_module

            factory = registry._build_stub_factory(MyPort)
            assert callable(factory)
            instance = factory()
            # Check that the stub class has the abstract methods
            assert hasattr(instance, "method1")
            assert hasattr(instance, "method2")
            # Calling should raise NotImplementedError
            with pytest.raises(NotImplementedError, match="method1"):
                instance.method1()

    def test_build_stub_factory_handles_inherited_abstractmethods(self, registry):
        # Create base with abstract methods
        class BasePort:
            __abstractmethods__ = frozenset(["base_method"])

        class MyPort(BasePort):
            __abstractmethods__ = frozenset(["my_method"])

        with patch("bootstrap.dependency_container.adapter_registry.importlib.import_module") as mock_import:
            mock_module = MagicMock()
            mock_module.MyPort = MyPort
            mock_import.return_value = mock_module

            factory = registry._build_stub_factory(MyPort)
            instance = factory()
            assert hasattr(instance, "base_method")
            assert hasattr(instance, "my_method")

    def test_reset(self, registry):
        registry._registered_ports.add("test")
        registry._is_registered = True
        registry.reset()
        assert registry._registered_ports == set()
        assert registry._is_registered is False

    def test_get_registered_ports(self, registry):
        registry._registered_ports.add("port1")
        assert registry.get_registered_ports() == ["port1"]


# ============================================================================
# Tests for singleton accessors
# ============================================================================

class TestSingletonAccessors:
    @patch("bootstrap.dependency_container.adapter_registry.get_container")
    def test_get_adapter_registry(self, mock_get_container):
        mock_container = MagicMock()
        mock_get_container.return_value = mock_container

        # First call creates registry
        reg1 = get_adapter_registry()
        assert isinstance(reg1, AdapterRegistry)
        assert reg1._container is mock_container

        # Second call returns same instance
        reg2 = get_adapter_registry()
        assert reg1 is reg2

        # Should have called register_all (we can check if _is_registered is True)
        assert reg1._is_registered is True

    def test_set_adapter_registry_instance(self):
        mock_registry = MagicMock(spec=AdapterRegistry)
        set_adapter_registry_instance(mock_registry)
        # Check that the global is set
        from bootstrap.dependency_container.adapter_registry import _adapter_registry
        assert _adapter_registry is mock_registry

        # Reset global for other tests
        set_adapter_registry_instance(None)


# ============================================================================
# Integration / Edge Cases
# ============================================================================

class TestEdgeCases:
    def test_register_all_with_manual_mapping_but_impl_not_found(self, registry, mock_container):
        class MyPort:
            pass

        registry._manual_mapping["MyPort"] = "MissingImpl"
        ports = [MyPort]
        implementations = []

        with patch.object(registry, "_discover_ports", return_value=ports):
            with patch.object(registry, "_discover_implementations", return_value=implementations):
                # It should fall back to stub generation
                with patch.object(registry, "_build_stub_factory", return_value=lambda: MyPort()) as mock_stub:
                    registry.register_all()
                    mock_container.register_singleton.assert_called_once_with(MyPort, factory=mock_stub.return_value)

    def test_register_all_with_auto_matching_returns_interface(self, registry, mock_container):
        class MyPort:
            pass

        # Simulate a bug where matching returns the port itself
        ports = [MyPort]
        implementations = [MyPort]  # same name, but it's an interface

        with patch.object(registry, "_discover_ports", return_value=ports):
            with patch.object(registry, "_discover_implementations", return_value=implementations):
                with patch.object(registry, "_match_port_to_implementation", return_value=MyPort):
                    # Should raise because factory will detect it's a port
                    with pytest.raises(RuntimeError, match="CRITICAL"):
                        registry.register_all()

    def test_build_factory_with_required_params_and_no_session(self, registry):
        class MyImpl:
            def __init__(self, param1, param2):
                self.p1 = param1
                self.p2 = param2

        port = MagicMock()
        port.__name__ = "MyPort"
        factory = registry._build_factory(port, MyImpl)
        instance = factory()
        assert instance.p1 is None
        assert instance.p2 is None

    def test_register_all_logs_debug_when_already_registered(self, registry, caplog):
        registry._is_registered = True
        with caplog.at_level(logging.DEBUG):
            registry.register_all()
        assert "Adapter registration already completed" in caplog.text

    def test_discover_ports_handles_import_error(self, registry, mock_path):
        file1 = MagicMock(spec=Path)
        file1.name = "bad_port.py"
        mock_path.glob.return_value = [file1]

        with patch("bootstrap.dependency_container.adapter_registry.importlib.import_module") as mock_import:
            mock_import.side_effect = ImportError("module not found")
            with caplog.at_level(logging.DEBUG):
                ports = registry._discover_ports()
                assert ports == []
                assert "Could not scan" in caplog.text

    def test_discover_implementations_handles_import_error(self, registry, mock_path):
        file1 = MagicMock(spec=Path)
        file1.name = "bad_impl.py"
        mock_path.glob.return_value = [file1]

        with patch("bootstrap.dependency_container.adapter_registry.importlib.import_module") as mock_import:
            mock_import.side_effect = ImportError("module not found")
            with caplog.at_level(logging.DEBUG):
                impls = registry._discover_implementations()
                assert impls == []
                assert "Could not scan" in caplog.text
