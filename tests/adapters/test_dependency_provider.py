# tests/unit/adapters/test_dependency_provider.py
"""
Unit tests for adapters/dependency_provider.py
===============================================
Testing get_service and get_service_by_key functions.
"""

from unittest.mock import MagicMock, Mock

import pytest
from fastapi import Request

from adapters.dependency_provider import get_service, get_service_by_key

# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_container():
    """Fixture untuk membuat mock IoC container."""
    container = Mock()
    return container


@pytest.fixture
def mock_app_state(mock_container):
    """Fixture untuk membuat mock app.state dengan container."""
    state = Mock()
    state.container = mock_container
    return state


@pytest.fixture
def mock_app(mock_app_state):
    """Fixture untuk membuat mock FastAPI app."""
    app = Mock()
    app.state = mock_app_state
    return app


@pytest.fixture
def mock_request(mock_app):
    """Fixture untuk membuat mock FastAPI Request."""
    request = Mock(spec=Request)
    request.app = mock_app
    return request


@pytest.fixture
def service_class_fixture():
    """Fixture untuk parameter 'service_class'."""
    # Membuat mock service class
    class MockService:
        def __init__(self):
            self.name = "MockService"

        def do_something(self):
            return "done"

    return MockService


@pytest.fixture
def service_key_fixture():
    """Fixture untuk parameter 'service_key'."""
    return "test_service_key"


@pytest.fixture
def mock_service_instance():
    """Fixture untuk membuat mock service instance yang akan di-return oleh container."""
    instance = Mock()
    instance.name = "TestServiceInstance"
    instance.do_something = Mock(return_value="something_done")
    return instance


# ============================================================
# Tests for get_service
# ============================================================

class TestGetService:
    """Test suite untuk fungsi get_service."""

    def test_get_service_success(self, mock_request, mock_container,
                                  service_class_fixture, mock_service_instance):
        """Test skenario sukses untuk get_service."""
        # Arrange
        mock_container.resolve = Mock(return_value=mock_service_instance)

        # Act
        dependency_fn = get_service(service_class_fixture)
        result = dependency_fn(mock_request)

        # Assert
        assert result is mock_service_instance
        mock_container.resolve.assert_called_once_with(service_class_fixture)

    def test_get_service_raises_runtime_error_when_container_is_none(
            self, mock_request, mock_app_state, service_class_fixture):
        """Test bahwa get_service melempar RuntimeError ketika container adalah None."""
        # Arrange - set container ke None
        mock_app_state.container = None

        # Act & Assert
        dependency_fn = get_service(service_class_fixture)
        with pytest.raises(RuntimeError) as exc_info:
            dependency_fn(mock_request)

        # Verify error message
        assert "IoC Container belum diinisialisasi di app.state" in str(exc_info.value)

    def test_get_service_callable_returns_correct_type(
            self, mock_request, mock_container, service_class_fixture, mock_service_instance):
        """Test bahwa callable yang dikembalikan memiliki tipe yang benar."""
        # Arrange
        mock_container.resolve = Mock(return_value=mock_service_instance)

        # Act
        dependency_fn = get_service(service_class_fixture)

        # Assert - dependency_fn harus callable
        assert callable(dependency_fn)

        # Call dan verify result
        result = dependency_fn(mock_request)
        assert isinstance(result, Mock)  # mock_service_instance adalah Mock
        assert result.name == "TestServiceInstance"

    def test_get_service_multiple_calls(
            self, mock_request, mock_container, service_class_fixture, mock_service_instance):
        """Test multiple calls ke dependency provider."""
        # Arrange
        mock_container.resolve = Mock(return_value=mock_service_instance)
        dependency_fn = get_service(service_class_fixture)

        # Act - call multiple times
        result1 = dependency_fn(mock_request)
        result2 = dependency_fn(mock_request)

        # Assert
        assert result1 is mock_service_instance
        assert result2 is mock_service_instance
        assert mock_container.resolve.call_count == 2


# ============================================================
# Tests for get_service_by_key
# ============================================================

class TestGetServiceByKey:
    """Test suite untuk fungsi get_service_by_key."""

    def test_get_service_by_key_success(self, mock_request, mock_container,
                                         service_key_fixture, mock_service_instance):
        """Test skenario sukses untuk get_service_by_key."""
        # Arrange
        mock_container.get = Mock(return_value=mock_service_instance)

        # Act
        dependency_fn = get_service_by_key(service_key_fixture)
        result = dependency_fn(mock_request)

        # Assert
        assert result is mock_service_instance
        mock_container.get.assert_called_once_with(service_key_fixture)

    def test_get_service_by_key_raises_runtime_error_when_container_is_none(
            self, mock_request, mock_app_state, service_key_fixture):
        """Test bahwa get_service_by_key melempar RuntimeError ketika container adalah None."""
        # Arrange - set container ke None
        mock_app_state.container = None

        # Act & Assert
        dependency_fn = get_service_by_key(service_key_fixture)
        with pytest.raises(RuntimeError) as exc_info:
            dependency_fn(mock_request)

        # Verify error message
        assert "IoC Container belum diinisialisasi di app.state" in str(exc_info.value)

    def test_get_service_by_key_callable_returns_correct_type(
            self, mock_request, mock_container, service_key_fixture, mock_service_instance):
        """Test bahwa callable yang dikembalikan memiliki tipe yang benar."""
        # Arrange
        mock_container.get = Mock(return_value=mock_service_instance)

        # Act
        dependency_fn = get_service_by_key(service_key_fixture)

        # Assert - dependency_fn harus callable
        assert callable(dependency_fn)

        # Call dan verify result
        result = dependency_fn(mock_request)
        assert result is mock_service_instance

    def test_get_service_by_key_with_different_keys(
            self, mock_request, mock_container, mock_service_instance):
        """Test get_service_by_key dengan berbagai key."""
        # Arrange
        mock_container.get = Mock(return_value=mock_service_instance)

        # Act & Assert
        keys = ["service_a", "service_b", "budget_service", "journal_service"]
        for key in keys:
            dependency_fn = get_service_by_key(key)
            result = dependency_fn(mock_request)
            assert result is mock_service_instance
            mock_container.get.assert_called_with(key)


# ============================================================
# Integration-style tests with realistic mocks
# ============================================================

class TestDependencyProviderIntegration:
    """Integration-style tests dengan mock yang lebih realistis."""

    def test_get_service_with_realistic_container_mock(
            self, service_class_fixture, mock_service_instance):
        """Test get_service dengan container mock yang lebih realistis."""
        # Arrange - buat container dengan method resolve
        container = MagicMock()
        container.resolve = Mock(return_value=mock_service_instance)

        # Buat app dengan state yang berisi container
        app = MagicMock()
        app.state.container = container

        # Buat request dengan app
        request = MagicMock(spec=Request)
        request.app = app

        # Act
        dependency_fn = get_service(service_class_fixture)
        result = dependency_fn(request)

        # Assert
        assert result is mock_service_instance
        container.resolve.assert_called_once_with(service_class_fixture)

    def test_get_service_by_key_with_realistic_container_mock(
            self, service_key_fixture, mock_service_instance):
        """Test get_service_by_key dengan container mock yang lebih realistis."""
        # Arrange - buat container dengan method get
        container = MagicMock()
        container.get = Mock(return_value=mock_service_instance)

        # Buat app dengan state yang berisi container
        app = MagicMock()
        app.state.container = container

        # Buat request dengan app
        request = MagicMock(spec=Request)
        request.app = app

        # Act
        dependency_fn = get_service_by_key(service_key_fixture)
        result = dependency_fn(request)

        # Assert
        assert result is mock_service_instance
        container.get.assert_called_once_with(service_key_fixture)

    def test_get_service_preserves_request_flow(
            self, service_class_fixture, mock_service_instance):
        """Test bahwa request flow diproses dengan benar."""
        # Arrange
        container = MagicMock()
        container.resolve = Mock(return_value=mock_service_instance)

        app = MagicMock()
        app.state.container = container

        request = MagicMock(spec=Request)
        request.app = app

        # Act
        dependency_fn = get_service(service_class_fixture)

        # Simulasi FastAPI calling the dependency
        result = dependency_fn(request)

        # Assert
        assert result.name == "TestServiceInstance"
        assert request.app.state.container is container
        container.resolve.assert_called_once()
