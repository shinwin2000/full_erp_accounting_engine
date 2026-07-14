import json
import tempfile
from io import StringIO

import pandas as pd
import pytest


class TestFormatConverterCSVJSON:
    @pytest.fixture
    def setup_converter(self):
        """Setup FormatConverterCSVJSON instance for testing"""
        from reports.format_converter_csv_json import FormatConverterCSVJSON
        converter = FormatConverterCSVJSON()
        return converter

    def test_init_defaults(self, setup_converter):
        """Test initialization with default settings"""
        converter = setup_converter

        assert hasattr(converter, '_config') or hasattr(converter, 'config')

    @pytest.mark.asyncio
    async def test_csv_to_json_basic_conversion(self, setup_converter):
        """Test basic CSV to JSON conversion"""
        converter = setup_converter

        csv_data = "name,age,city\nJohn,30,New York\nJane,25,Los Angeles"

        df = pd.read_csv(StringIO(csv_data))

        result = await converter.csv_to_json(df)

        parsed_json = json.loads(result)
        assert len(parsed_json) == 2
        assert parsed_json[0]['name'] == 'John'

    @pytest.mark.asyncio
    async def test_json_to_csv_basic_conversion(self, setup_converter):
        """Test basic JSON to CSV conversion"""
        converter = setup_converter

        json_data = [
            {"name": "John", "age": 30},
            {"name": "Jane", "age": 25}
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as temp_file:
            output_path = temp_file.name

        result_df = await converter.json_to_csv(json_data, output_path)

        assert isinstance(result_df, pd.DataFrame)
        assert len(result_df) == 2

    def test_validate_csv_structure(self, setup_converter):
        """Test CSV structure validation"""
        converter = setup_converter

        csv_data = "name,age\nJohn,30\nJane,25"

        df = pd.read_csv(StringIO(csv_data))
        is_valid = converter._validate_csv_structure(df)
        assert is_valid is True

    def test_validate_json_structure(self, setup_converter):
        """Test JSON structure validation"""
        converter = setup_converter

        json_data = [{"name": "John", "age": 30}]
        is_valid = converter._validate_json_structure(json_data)
        assert is_valid is True

        invalid_json = {"name": "John"}
        is_valid = converter._validate_json_structure(invalid_json)
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_handle_special_characters(self, setup_converter):
        """Test handling special characters in data"""
        converter = setup_converter

        csv_data = 'name,description\nJohn,"Lives in New York"\nMaria,"Habla espanol"'

        df = pd.read_csv(StringIO(csv_data))
        result = await converter.csv_to_json(df)

        parsed_json = json.loads(result)
        assert parsed_json[0]['name'] == 'John'
