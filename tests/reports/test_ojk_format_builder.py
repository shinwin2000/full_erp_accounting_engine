
import pytest


class TestOJKFormatBuilder:
    @pytest.fixture
    def setup_builder(self):
        """Setup OJKFormatBuilder instance for testing"""
        from reports.ojk_format_builder import OJKFormatBuilder

        builder = OJKFormatBuilder()
        return builder

    def test_init_with_default_config(self, setup_builder):
        """Test initialization with default configuration"""
        builder = setup_builder

        assert hasattr(builder, '_config') or hasattr(builder, 'config')

    @pytest.mark.asyncio
    async def test_build_basic_loan_data(self, setup_builder):
        """Test building basic loan data in OJK format"""
        builder = setup_builder

        loan_data = {
            'loan_id': 'LN001',
            'borrower_name': 'John Doe',
            'loan_amount': 100000000,
            'interest_rate': 12.5
        }

        result = await builder.build_loan_data(loan_data)

        assert result is not None

    @pytest.mark.asyncio
    async def test_validate_required_fields_present(self, setup_builder):
        """Test validation when all required fields are present"""
        builder = setup_builder

        complete_data = {
            'loan_id': 'LN001',
            'borrower_name': 'John Doe',
            'loan_amount': 100000000,
            'interest_rate': 12.5
        }

        is_valid, errors = await builder.validate_format(complete_data)
        assert is_valid is True
        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_validate_missing_required_fields(self, setup_builder):
        """Test validation when required fields are missing"""
        builder = setup_builder

        incomplete_data = {
            'loan_id': 'LN001',
            'borrower_name': 'John Doe'
        }

        is_valid, errors = await builder.validate_format(incomplete_data)
        assert is_valid is False
        assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_build_multiple_loan_records(self, setup_builder):
        """Test building multiple loan records in OJK format"""
        builder = setup_builder

        loans_data = [
            {'loan_id': 'LN001', 'borrower_name': 'John Doe', 'loan_amount': 100000000},
            {'loan_id': 'LN002', 'borrower_name': 'Jane Smith', 'loan_amount': 150000000}
        ]

        result = await builder.build_multiple_loans(loans_data)

        assert len(result) == 2

    def test_apply_business_rules(self, setup_builder):
        """Test application of business rules during formatting"""
        builder = setup_builder

        loan_data = {
            'loan_id': 'LN001',
            'borrower_name': 'John Doe',
            'loan_amount': 100000000,
            'interest_rate': 12.5
        }

        processed = builder.apply_business_rules(loan_data)

        assert processed is not None

    @pytest.mark.asyncio
    async def test_format_for_ojk_submission(self, setup_builder):
        """Test final formatting for OJK submission requirements"""
        builder = setup_builder

        raw_data = {
            'loans': [
                {'loan_id': 'LN001', 'borrower_name': 'John Doe', 'loan_amount': 100000000}
            ]
        }

        submission_ready = await builder.format_for_submission(raw_data)

        assert isinstance(submission_ready, dict)
