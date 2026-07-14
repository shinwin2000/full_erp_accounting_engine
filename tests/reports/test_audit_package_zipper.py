import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest


class TestAuditPackageZipper:
    @pytest.fixture
    def setup_zipper(self):
        """Setup AuditPackageZipper instance for testing"""
        with patch('reports.audit_package_zipper.DEFAULT_CONFIG', {'output_dir': '/tmp/audit_packages'}):
            from reports.audit_package_zipper import AuditPackageZipper
            zipper = AuditPackageZipper()
            return zipper

    def test_init_with_default_config(self):
        """Test initialization with default configuration"""
        from reports.audit_package_zipper import AuditPackageZipper

        with patch('reports.audit_package_zipper.DEFAULT_CONFIG', {'output_dir': '/tmp/audit_packages'}):
            zipper = AuditPackageZipper()

            assert hasattr(zipper, '_output_dir')
            assert hasattr(zipper, '_max_size_bytes')

    def test_init_with_custom_config(self):
        """Test initialization with custom configuration"""
        from reports.audit_package_zipper import AuditPackageZipper

        with patch('reports.audit_package_zipper.load_yaml_config') as mock_load:
            mock_load.return_value = {
                'audit_package': {
                    'output_dir': '/custom/path',
                    'max_package_size_mb': 100
                }
            }
            zipper = AuditPackageZipper()

            assert str(zipper._output_dir) == '/custom/path'
            assert zipper._max_size_bytes == 100 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_compute_file_hash(self, setup_zipper):
        """Test computing SHA-256 hash of a file"""
        zipper = setup_zipper

        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
            temp_file.write("test content")
            temp_path = Path(temp_file.name)

        try:
            hash_result = await zipper._compute_file_hash(temp_path)

            assert isinstance(hash_result, str)
            assert len(hash_result) == 64  # SHA-256 produces 64 hex characters
        finally:
            temp_path.unlink()

    def test_package_too_large_error(self):
        """Test PackageTooLargeError exception"""
        from reports.audit_package_zipper import AuditPackageError, PackageTooLargeError

        error = PackageTooLargeError("Package exceeds size limit")

        assert isinstance(error, AuditPackageError)
        assert "exceeds size limit" in str(error)

    def test_audit_package_error(self):
        """Test AuditPackageError exception"""
        from reports.audit_package_zipper import AuditPackageError

        error = AuditPackageError("Test error message")

        assert "Test error message" in str(error)

    def test_constants_defined(self):
        """Test that required constants are defined"""
        from reports.audit_package_zipper import DEFAULT_CONFIG, MANIFEST_VERSION

        assert DEFAULT_CONFIG is not None
        assert isinstance(DEFAULT_CONFIG, dict)
        assert MANIFEST_VERSION is not None

    @pytest.mark.asyncio
    async def test_get_report_generator_lazy_loading(self, setup_zipper):
        """Test lazy loading of report generator"""
        zipper = setup_zipper

        assert zipper._report_generator is None

        with patch('reports.audit_package_zipper.get_report_generator', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = Mock()

            result = await zipper._get_report_generator()

            assert result is not None
            assert zipper._report_generator is not None
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_ojk_builder_lazy_loading(self, setup_zipper):
        """Test lazy loading of OJK builder"""
        zipper = setup_zipper

        assert zipper._ojk_builder is None

        with patch('reports.audit_package_zipper.get_ojk_builder', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = Mock()

            result = await zipper._get_ojk_builder()

            assert result is not None
            assert zipper._ojk_builder is not None
            mock_get.assert_called_once()

    def test_config_has_required_keys(self):
        """Test that default config has required keys"""
        from reports.audit_package_zipper import DEFAULT_CONFIG

        required_keys = ['output_dir', 'max_package_size_mb']

        for key in required_keys:
            assert key in DEFAULT_CONFIG

    def test_output_dir_creation(self):
        """Test that output directory is created during initialization"""
        from reports.audit_package_zipper import AuditPackageZipper

        with patch('reports.audit_package_zipper.DEFAULT_CONFIG', {'output_dir': '/tmp/test_audit_dir'}), \
             patch('pathlib.Path.mkdir') as mock_mkdir:

            AuditPackageZipper()

            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
