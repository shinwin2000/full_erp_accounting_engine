from unittest.mock import Mock, patch

import pandas as pd
import pytest


class TestGeneratorPDFExcelHTML:
    @pytest.fixture
    def setup_generator(self):
        """Setup ReportGenerator instance for testing"""
        from reports.generator_pdf_excel_html import ReportGenerator

        generator = ReportGenerator()
        return generator

    def test_init_with_default_config(self, setup_generator):
        """Test initialization with default configuration"""
        generator = setup_generator

        assert hasattr(generator, '_config') or hasattr(generator, 'config')

    @pytest.mark.asyncio
    async def test_generate_pdf_basic(self, setup_generator):
        """Test basic PDF generation"""
        generator = setup_generator

        data = {
            'title': 'Sales Report',
            'data': [
                {'product': 'A', 'sales': 1000},
                {'product': 'B', 'sales': 1500}
            ]
        }

        with patch('reports.generator_pdf_excel_html.fpdf.FPDF') as mock_pdf:
            mock_instance = Mock()
            mock_pdf.return_value = mock_instance

            result = await generator.generate_pdf(data)

            assert result is not None

    @pytest.mark.asyncio
    async def test_generate_excel_basic(self, setup_generator):
        """Test basic Excel generation"""
        generator = setup_generator

        data = pd.DataFrame([
            {'product': 'A', 'sales': 1000},
            {'product': 'B', 'sales': 1500}
        ])

        with patch('pandas.ExcelWriter') as mock_writer:
            mock_instance = Mock()
            mock_writer.return_value.__enter__.return_value = mock_instance

            result = await generator.generate_excel(data)

            assert result is not None

    @pytest.mark.asyncio
    async def test_generate_html_basic(self, setup_generator):
        """Test basic HTML generation"""
        generator = setup_generator

        data = {
            'title': 'Sales Report',
            'data': [
                {'product': 'A', 'sales': 1000},
                {'product': 'B', 'sales': 1500}
            ]
        }

        html_content = await generator.generate_html(data)

        assert '<html>' in html_content.lower() or '<table' in html_content.lower()

    def test_validate_data_structure(self, setup_generator):
        """Test data structure validation before generation"""
        generator = setup_generator

        valid_data = {'title': 'Report', 'data': []}
        is_valid = generator._validate_data_structure(valid_data)
        assert is_valid is True

        invalid_data = 'not a dict'
        is_valid = generator._validate_data_structure(invalid_data)
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_generate_batch_reports(self, setup_generator):
        """Test generating multiple reports in batch"""
        generator = setup_generator

        batch_data = [
            {'format': 'pdf', 'data': {'title': 'Report 1', 'data': []}},
            {'format': 'excel', 'data': pd.DataFrame([{'A': 1}])},
            {'format': 'html', 'data': {'title': 'Report 3', 'data': []}}
        ]

        results = await generator.generate_batch(batch_data)

        assert len(results) == 3
