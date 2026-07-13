#!/usr/bin/env python3
"""
Module: format_converter_csv_json.py
Layer: Reports
Responsibility: Mengonversi data laporan antara format CSV dan JSON. Mendukung
               import/export data ke/dari file CSV dan JSON, dengan dukungan
               untuk mapping field, tipe data kustom (decimal, date), dan
               validasi schema. Berguna untuk integrasi dengan sistem eksternal
               dan proses ETL.
Dependencies:
- csv, json, decimal, datetime, asyncio, pathlib, io
- config.loader_yaml -> DIINJEKSI DARI LUAR
- infrastructure.telemetry.structured_json_logging
Audit: Setiap konversi dicatat. Data yang diekspor dapat digunakan untuk audit trail.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import csv
import json
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import aiofiles  # <-- Tambahan untuk async file I/O

# Internal dependencies
from infrastructure.telemetry.structured_json_logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_CONFIG = {
    "csv_delimiter": ",",
    "csv_quotechar": '"',
    "csv_encoding": "utf-8",
    "json_indent": 2,
    "date_format": "%Y-%m-%d",
    "datetime_format": "%Y-%m-%dT%H:%M:%S.%fZ",
    "decimal_format": "str",
}

# Built-in type converters
TYPE_CONVERTERS = {
    "string": lambda x: str(x) if x is not None else "",
    "integer": lambda x: int(x) if x is not None and x != "" else 0,
    "float": lambda x: float(x) if x is not None and x != "" else 0.0,
    "decimal": lambda x: Decimal(str(x)) if x is not None and x != "" else Decimal(0),
    "boolean": lambda x: str(x).lower() in ("true", "1", "yes", "on") if x is not None else False,
    "date": lambda x: datetime.strptime(x, DEFAULT_CONFIG["date_format"]).date() if x else None,
    "datetime": lambda x: datetime.strptime(x, DEFAULT_CONFIG["datetime_format"]) if x else None,
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class FormatConverterError(Exception):
    """Base exception untuk format converter."""

    pass


class CSVParseError(FormatConverterError):
    """Error saat parsing CSV."""

    pass


class JSONParseError(FormatConverterError):
    """Error saat parsing JSON."""

    pass


class SchemaValidationError(FormatConverterError):
    """Error validasi schema."""

    pass


# ============================================================================
# FORMAT CONVERTER
# ============================================================================


class FormatConverterCSVJSON:
    """
    Konverter antara format CSV dan JSON.

    Fitur:
    - CSV ke JSON (dengan atau tanpa header)
    - JSON ke CSV (flatten atau nested)
    - Schema validation
    - Type conversion berdasarkan mapping
    - Streaming untuk file besar
    - Batch processing
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Inisialisasi converter dengan konfigurasi yang diinjeksi.

        Args:
            config: Dictionary konfigurasi (jika None, gunakan DEFAULT_CONFIG)
        """
        self.config = self._prepare_config(config)
        self._csv_delimiter = self.config.get("csv_delimiter", DEFAULT_CONFIG["csv_delimiter"])
        self._csv_quotechar = self.config.get("csv_quotechar", DEFAULT_CONFIG["csv_quotechar"])
        self._csv_encoding = self.config.get("csv_encoding", DEFAULT_CONFIG["csv_encoding"])
        self._json_indent = self.config.get("json_indent", DEFAULT_CONFIG["json_indent"])
        self._date_format = self.config.get("date_format", DEFAULT_CONFIG["date_format"])
        self._datetime_format = self.config.get("datetime_format", DEFAULT_CONFIG["datetime_format"])
        self._decimal_format = self.config.get("decimal_format", DEFAULT_CONFIG["decimal_format"])

    def _prepare_config(self, config: dict | None) -> dict:
        """Siapkan konfigurasi dari parameter atau default."""
        if config is not None:
            result = DEFAULT_CONFIG.copy()
            result.update(config)
            return result
        return DEFAULT_CONFIG.copy()

    # ========================================================================
    # CSV TO JSON
    # ========================================================================

    # ========================================================================
    # PERBAIKAN: csv_to_json menggunakan aiofiles dan asyncio.to_thread
    # ========================================================================
    async def csv_to_json(
        self,
        csv_file: Path,
        has_header: bool = True,
        encoding: str | None = None,
        type_mapping: dict[str, str] | None = None,
    ) -> list[dict]:
        """
        Mengonversi file CSV ke list of JSON objects.

        Args:
            csv_file: Path to CSV file
            has_header: Whether CSV has header row (if False, uses column indexes as keys)
            encoding: File encoding (default from config)
            type_mapping: Dict mapping column name/idx to type ("string", "integer", "decimal", "date", etc.)

        Returns:
            List of dictionaries
        """
        enc = encoding or self._csv_encoding
        delimiter = self._csv_delimiter
        quotechar = self._csv_quotechar

        def _parse_csv_sync(content: str):
            """Parse CSV content synchronously in thread pool."""
            import io
            reader = csv.reader(
                io.StringIO(content),
                delimiter=delimiter,
                quotechar=quotechar
            )
            rows = list(reader)
            if not rows:
                return []

            if has_header:
                headers = rows[0]
                data_rows = rows[1:]
            else:
                headers = [f"col_{i}" for i in range(len(rows[0]))]
                data_rows = rows

            result = []
            for row_num, row in enumerate(data_rows, start=1):
                if len(row) != len(headers):
                    continue
                obj = {}
                for i, header in enumerate(headers):
                    value = row[i] if i < len(row) else ""
                    if type_mapping and header in type_mapping:
                        converter = TYPE_CONVERTERS.get(type_mapping[header])
                        if converter:
                            try:
                                value = converter(value)
                            except Exception as e:
                                logger.warning(f"Type conversion error for {header}: {e}")
                    obj[header] = value
                result.append(obj)
            return result

        try:
            # Baca file secara async
            async with aiofiles.open(csv_file, encoding=enc) as f:
                content = await f.read()

            # Parse CSV di thread pool (CPU-bound)
            result = await asyncio.to_thread(_parse_csv_sync, content)

            logger.info(f"Converted CSV to JSON: {len(result)} records from {csv_file}")
            return result

        except Exception as e:
            logger.error(f"CSV to JSON conversion failed: {e}")
            raise CSVParseError(f"Failed to parse CSV: {e}") from e

    # ========================================================================
    # JSON TO CSV
    # ========================================================================

    # ========================================================================
    # PERBAIKAN: json_to_csv menggunakan aiofiles dan asyncio.to_thread
    # ========================================================================
    async def json_to_csv(
        self,
        json_data: list[dict],
        output_file: Path,
        fields: list[str] | None = None,
        encoding: str | None = None,
    ) -> None:
        """
        Mengonversi list of JSON objects ke file CSV.

        Args:
            json_data: List of dictionaries
            output_file: Output CSV file path
            fields: List of field names to include (in order). If None, uses all keys from first object.
            encoding: File encoding
        """
        if not json_data:
            logger.warning("No data to convert")
            return

        enc = encoding or self._csv_encoding
        if fields is None:
            fields = list(json_data[0].keys())

        delimiter = self._csv_delimiter
        quotechar = self._csv_quotechar
        date_format = self._date_format
        datetime_format = self._datetime_format
        decimal_format = self._decimal_format

        def _write_csv_sync():
            """Write CSV synchronously in thread pool."""
            import io
            output = io.StringIO()
            writer = csv.DictWriter(
                output,
                fieldnames=fields,
                delimiter=delimiter,
                quotechar=quotechar,
                quoting=csv.QUOTE_MINIMAL,
            )
            writer.writeheader()
            for row in json_data:
                csv_row = {}
                for field in fields:
                    val = row.get(field)
                    if val is None:
                        csv_row[field] = ""
                    elif isinstance(val, (datetime, date)):
                        fmt = datetime_format if isinstance(val, datetime) else date_format
                        csv_row[field] = val.strftime(fmt)
                    elif isinstance(val, Decimal):
                        if decimal_format == "str":
                            csv_row[field] = str(val)
                        else:
                            csv_row[field] = float(val)
                    else:
                        csv_row[field] = str(val)
                writer.writerow(csv_row)
            return output.getvalue()

        try:
            csv_content = await asyncio.to_thread(_write_csv_sync)

            # Tulis ke file secara async
            async with aiofiles.open(output_file, "w", newline="", encoding=enc) as f:
                await f.write(csv_content)

            logger.info(f"Converted JSON to CSV: {len(json_data)} records to {output_file}")

        except Exception as e:
            logger.error(f"JSON to CSV conversion failed: {e}")
            raise FormatConverterError(f"Failed to write CSV: {e}") from e

    # ========================================================================
    # STREAMING (for large files)
    # ========================================================================

    # ========================================================================
    # PERBAIKAN: stream_csv_to_json menggunakan aiofiles dan asyncio.to_thread
    # ========================================================================
    async def stream_csv_to_json(
        self,
        csv_file: Path,
        callback,
        batch_size: int = 1000,
        has_header: bool = True,
        type_mapping: dict | None = None,
    ) -> int:
        """
        Streaming CSV reader, memproses batch per batch.

        Args:
            csv_file: Path to CSV file
            callback: Async function that receives list of records
            batch_size: Number of rows per batch
            has_header: Whether CSV has header
            type_mapping: Type mapping dictionary

        Returns:
            Total records processed
        """
        enc = self._csv_encoding
        delimiter = self._csv_delimiter
        quotechar = self._csv_quotechar

        def _parse_batch_sync(content: str, offset: int, limit: int):
            """Parse a batch of CSV rows synchronously."""
            import io
            reader = csv.reader(
                io.StringIO(content),
                delimiter=delimiter,
                quotechar=quotechar
            )
            rows = list(reader)
            if not rows:
                return [], 0

            if has_header:
                headers = rows[0]
                data_rows = rows[1:]
            else:
                headers = [f"col_{i}" for i in range(len(rows[0]))]
                data_rows = rows

            # Apply offset and limit
            start = offset
            end = offset + limit if limit > 0 else len(data_rows)
            batch_rows = data_rows[start:end]

            result = []
            for row in batch_rows:
                if len(row) != len(headers):
                    continue
                obj = {}
                for i, header in enumerate(headers):
                    value = row[i] if i < len(row) else ""
                    if type_mapping and header in type_mapping:
                        conv = TYPE_CONVERTERS.get(type_mapping[header])
                        if conv:
                            with contextlib.suppress(builtins.BaseException):
                                value = conv(value)
                    obj[header] = value
                result.append(obj)
            return result, len(batch_rows)

        try:
            async with aiofiles.open(csv_file, encoding=enc) as f:
                content = await f.read()

            total = 0
            offset = 0
            while True:
                batch, count = await asyncio.to_thread(_parse_batch_sync, content, offset, batch_size)
                if not batch:
                    break
                await callback(batch)
                total += count
                offset += count
                if count < batch_size:
                    break

            logger.info(f"Streamed CSV to JSON: {total} records processed")
            return total

        except Exception as e:
            logger.error(f"Streaming CSV conversion failed: {e}")
            raise CSVParseError(f"Failed to stream CSV: {e}") from e

    # ========================================================================
    # SCHEMA VALIDATION
    # ========================================================================

    async def validate_json_schema(self, json_data: list[dict], schema: dict) -> bool:
        """
        Memvalidasi JSON data terhadap schema (sederhana).

        Args:
            json_data: List of objects
            schema: Dict with "required_fields" and "field_types"

        Returns:
            True if valid
        """
        required_fields = schema.get("required_fields", [])
        field_types = schema.get("field_types", {})

        errors = []
        for i, record in enumerate(json_data):
            for field in required_fields:
                if field not in record or record[field] is None or record[field] == "":
                    errors.append(f"Record {i}: missing required field '{field}'")

            for field, expected_type in field_types.items():
                if field in record and record[field] is not None:
                    value = record[field]
                    if expected_type == "string" and not isinstance(value, str):
                        errors.append(
                            f"Record {i}: field '{field}' expected string, got {type(value).__name__}"
                        )
                    elif expected_type == "number" and not isinstance(value, (int, float, Decimal)):
                        errors.append(
                            f"Record {i}: field '{field}' expected number, got {type(value).__name__}"
                        )
                    elif expected_type == "integer" and not isinstance(value, int):
                        errors.append(
                            f"Record {i}: field '{field}' expected integer, got {type(value).__name__}"
                        )
                    elif expected_type == "boolean" and not isinstance(value, bool):
                        errors.append(
                            f"Record {i}: field '{field}' expected boolean, got {type(value).__name__}"
                        )

        if errors:
            logger.warning(f"Schema validation failed: {len(errors)} errors")
            for err in errors[:10]:
                logger.warning(err)
            return False

        return True

    # ========================================================================
    # UTILITY
    # ========================================================================

    async def export_to_csv(self, data: list[dict], output_file: Path) -> None:
        """Alias untuk json_to_csv dengan data langsung."""
        await self.json_to_csv(data, output_file)

    # ========================================================================
    # PERBAIKAN: export_to_json menggunakan aiofiles dan asyncio.to_thread
    # ========================================================================
    async def export_to_json(self, data: list[dict], output_file: Path) -> None:
        """Mengekspor data ke file JSON."""
        try:
            indent = self._json_indent
            serializer = self._json_serializer

            def _dump_json_sync():
                return json.dumps(data, indent=indent, default=serializer)

            json_content = await asyncio.to_thread(_dump_json_sync)

            async with aiofiles.open(output_file, "w", encoding="utf-8") as f:
                await f.write(json_content)

            logger.info(f"Exported {len(data)} records to {output_file}")
        except Exception as e:
            logger.error(f"Failed to export JSON: {e}")
            raise JSONParseError(f"JSON export failed: {e}") from e

    def _json_serializer(self, obj):
        """Custom JSON serializer for non-standard types."""
        if isinstance(obj, Decimal):
            return str(obj) if self._decimal_format == "str" else float(obj)
        if isinstance(obj, datetime):
            return obj.strftime(self._datetime_format)
        if isinstance(obj, date):
            return obj.strftime(self._date_format)
        if isinstance(obj, UUID):
            return str(obj)
        raise TypeError(f"Type {type(obj)} not serializable")


# ============================================================================
# SINGLETON INSTANCE dengan injeksi konfigurasi dari luar
# ============================================================================

_format_converter: FormatConverterCSVJSON | None = None
_converter_config: dict | None = None


def set_format_converter_config(config: dict) -> None:
    """Set konfigurasi untuk format converter (harus dipanggil sebelum get_format_converter)."""
    global _converter_config
    _converter_config = config


async def get_format_converter() -> FormatConverterCSVJSON:
    """Get singleton instance of FormatConverterCSVJSON."""
    global _format_converter
    if _format_converter is None:
        _format_converter = FormatConverterCSVJSON(config=_converter_config)
    return _format_converter


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CSVParseError",
    "FormatConverterCSVJSON",
    "FormatConverterError",
    "JSONParseError",
    "SchemaValidationError",
    "get_format_converter",
    "set_format_converter_config",
]
