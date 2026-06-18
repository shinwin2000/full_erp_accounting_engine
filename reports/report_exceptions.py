#!/usr/bin/env python3
"""
Module: report_exceptions.py
Layer: Reports
Responsibility: Mendefinisikan semua exception untuk module reports.
"""

from __future__ import annotations


class ReportError(Exception):
    """Base exception untuk reports."""
    pass


class ReportGeneratorError(ReportError):
    """Error saat generate report."""
    pass


class UnsupportedFormatError(ReportGeneratorError):
    """Format laporan tidak didukung."""
    pass


class TemplateNotFoundError(ReportGeneratorError):
    """Template tidak ditemukan."""
    pass


class ReportSchedulerError(ReportError):
    """Error pada report scheduler."""
    pass


class JobNotFoundError(ReportSchedulerError):
    """Job tidak ditemukan."""
    pass


class DistributionError(ReportError):
    """Error saat distribusi report."""
    pass


class EmailSendError(DistributionError):
    """Error saat mengirim email."""
    pass


class WhatsAppSendError(DistributionError):
    """Error saat mengirim WhatsApp."""
    pass


class XBRLExportError(ReportError):
    """Error saat ekspor XBRL."""
    pass


class OJKFormatBuilderError(ReportError):
    """Error saat membangun format OJK."""
    pass


class AuditPackageError(ReportError):
    """Error saat membuat paket audit."""
    pass


class PackageTooLargeError(AuditPackageError):
    """Paket melebihi batas ukuran."""
    pass


class FormatConverterError(ReportError):
    """Error pada format converter."""
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


__all__ = [
    "AuditPackageError",
    "CSVParseError",
    "DistributionError",
    "EmailSendError",
    "FormatConverterError",
    "JSONParseError",
    "JobNotFoundError",
    "OJKFormatBuilderError",
    "PackageTooLargeError",
    "ReportError",
    "ReportGeneratorError",
    "ReportSchedulerError",
    "SchemaValidationError",
    "TemplateNotFoundError",
    "UnsupportedFormatError",
    "WhatsAppSendError",
    "XBRLExportError",
]
