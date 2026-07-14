from unittest.mock import AsyncMock, patch

import pytest


class TestDistributorEmailWhatsApp:
    @pytest.fixture
    def setup_distributor(self):
        """Setup ReportDistributor instance for testing"""
        from reports.distributor_email_whatsapp import ReportDistributor

        config = {
            'smtp_server': 'smtp.test.com',
            'whatsapp_api_url': 'https://api.whatsapp.com/v1',
            'email_from': 'test@example.com'
        }

        distributor = ReportDistributor(config=config)
        return distributor

    def test_init_with_default_config(self):
        """Test initialization with default configuration"""
        from reports.distributor_email_whatsapp import ReportDistributor

        distributor = ReportDistributor()

        assert hasattr(distributor, '_config')
        assert isinstance(distributor._config, dict)

    def test_init_with_custom_config(self, setup_distributor):
        """Test initialization with custom configuration"""
        distributor = setup_distributor

        assert distributor._config['smtp_server'] == 'smtp.test.com'
        assert distributor._config['whatsapp_api_url'] == 'https://api.whatsapp.com/v1'

    @pytest.mark.asyncio
    async def test_send_email_success(self, setup_distributor):
        """Test successful email sending"""
        distributor = setup_distributor

        recipient_data = {
            'to': ['user@test.com'],
            'subject': 'Test Report',
            'body': '<p>Your report is ready</p>'
        }

        with patch('aiohttp.ClientSession') as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_response

            result = await distributor.send_email(**recipient_data)

            assert result is True

    @pytest.mark.asyncio
    async def test_send_whatsapp_success(self, setup_distributor):
        """Test successful WhatsApp message sending"""
        distributor = setup_distributor

        recipient_data = {
            'phone': '+1234567890',
            'message': 'Your report is ready'
        }

        with patch('aiohttp.ClientSession') as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={'status': 'sent'})
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_response

            result = await distributor.send_whatsapp(**recipient_data)

            assert result is True

    @pytest.mark.asyncio
    async def test_send_slack_success(self, setup_distributor):
        """Test successful Slack message sending"""
        distributor = setup_distributor

        with patch('aiohttp.ClientSession') as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_response

            result = await distributor.send_slack(
                channel='#general',
                message='Test message'
            )

            assert result is True

    def test_distribution_error_exception(self):
        """Test DistributionError exception"""
        from reports.distributor_email_whatsapp import DistributionError

        error = DistributionError("Distribution failed")

        assert "Distribution failed" in str(error)

    def test_email_send_error_exception(self):
        """Test EmailSendError exception"""
        from reports.distributor_email_whatsapp import DistributionError, EmailSendError

        error = EmailSendError("SMTP error")

        assert isinstance(error, DistributionError)
        assert "SMTP error" in str(error)

    def test_whatsapp_send_error_exception(self):
        """Test WhatsAppSendError exception"""
        from reports.distributor_email_whatsapp import DistributionError, WhatsAppSendError

        error = WhatsAppSendError("API error")

        assert isinstance(error, DistributionError)
        assert "API error" in str(error)

    @pytest.mark.asyncio
    async def test_close_session(self, setup_distributor):
        """Test closing the HTTP session"""
        distributor = setup_distributor

        mock_session = AsyncMock()
        distributor._session = mock_session

        await distributor.close()

        mock_session.close.assert_called_once()

    def test_prepare_config_merges_defaults(self):
        """Test that _prepare_config merges defaults with custom config"""
        from reports.distributor_email_whatsapp import ReportDistributor

        custom_config = {'smtp_server': 'custom.smtp.com'}

        distributor = ReportDistributor(config=custom_config)

        assert distributor._config['smtp_server'] == 'custom.smtp.com'

    @pytest.mark.asyncio
    async def test_distribute_method_exists(self, setup_distributor):
        """Test that distribute method exists and is callable"""
        distributor = setup_distributor

        assert hasattr(distributor, 'distribute')
        assert callable(distributor.distribute)

    @pytest.mark.asyncio
    async def test_distribute_batch_method_exists(self, setup_distributor):
        """Test that distribute_batch method exists and is callable"""
        distributor = setup_distributor

        assert hasattr(distributor, 'distribute_batch')
        assert callable(distributor.distribute_batch)
