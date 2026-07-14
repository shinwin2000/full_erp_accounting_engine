
import pytest


class TestXBRLIFRSExporter:
    @pytest.fixture
    def setup_exporter(self):
        """Setup XBRLIFRSExporter instance for testing"""
        from reports.xbrl_ifrs_exporter import XBRLIFRSExporter

        exporter = XBRLIFRSExporter()
        return exporter

    def test_init_with_default_config(self, setup_exporter):
        """Test initialization with default configuration"""
        exporter = setup_exporter

        assert hasattr(exporter, '_config') or hasattr(exporter, 'schema_version')

    @pytest.mark.asyncio
    async def test_validate_ifrs_data_compliance(self, setup_exporter):
        """Test validation of IFRS data compliance"""
        exporter = setup_exporter

        compliant_data = {
            'assets': 1000000,
            'liabilities': 500000,
            'equity': 500000,
            'revenue': 2000000
        }

        is_compliant, issues = await exporter.validate_ifrs_compliance(compliant_data)
        assert is_compliant is True
        assert len(issues) == 0

    @pytest.mark.asyncio
    async def test_build_xbrl_instance_document(self, setup_exporter):
        """Test building XBRL instance document"""
        exporter = setup_exporter

        financial_data = {
            'balance_sheet': {
                'assets': {'current_assets': 500000},
                'liabilities': {'current_liabilities': 250000}
            },
            'income_statement': {
                'revenue': 2000000
            }
        }

        xbrl_doc = await exporter.build_xbrl_document(financial_data)

        root = xbrl_doc.getroot()
        assert root.tag.endswith('xbrl') or root.tag.startswith('{')

    def test_map_ifrs_concepts_to_xbrl_elements(self, setup_exporter):
        """Test mapping IFRS concepts to XBRL elements"""
        exporter = setup_exporter

        ifrs_concept = 'Assets'
        xbrl_element = exporter.map_ifrs_to_xbrl(ifrs_concept)

        assert xbrl_element is not None
        assert 'asset' in xbrl_element.lower()

    def test_create_contexts_for_xbrl(self, setup_exporter):
        """Test creation of XBRL contexts"""
        exporter = setup_exporter

        period_info = {
            'start_date': '2023-01-01',
            'end_date': '2023-12-31',
            'entity': 'Test Company Inc.'
        }

        context = exporter.create_context(period_info)

        assert context is not None

    @pytest.mark.asyncio
    async def test_export_complete_financial_statements(self, setup_exporter):
        """Test export of complete financial statements to XBRL"""
        exporter = setup_exporter

        complete_fs = {
            'balance_sheet': {
                'assets': {'total_assets': 1000000},
                'liabilities': {'total_liabilities': 600000},
                'equity': {'total_equity': 400000}
            },
            'income_statement': {
                'revenue': 2000000,
                'net_income': 500000
            }
        }

        xbrl_output = await exporter.export_financial_statements(complete_fs)

        assert isinstance(xbrl_output, str)
        assert '<?xml' in xbrl_output
