#!/usr/bin/env python3
"""
Module: file_storage_exceptions.py
Layer: Infrastructure (File Storage)
Responsibility: Mendefinisikan semua exception untuk file storage.
"""

from __future__ import annotations


class FileStorageError(Exception):
    """Base exception untuk file storage."""

    pass


class FileNotFoundError(FileStorageError):
    """File tidak ditemukan."""

    pass


class FileUploadError(FileStorageError):
    """Error saat upload file."""

    pass


class FileDownloadError(FileStorageError):
    """Error saat download file."""

    pass


class FileStorageNotConfiguredError(FileStorageError):
    """File storage belum dikonfigurasi."""

    pass


class EvidenceUploadError(FileStorageError):
    """Error saat upload evidence."""

    pass


class EvidenceNotFoundError(FileStorageError):
    """Evidence tidak ditemukan."""

    pass


class InvalidFileTypeError(FileStorageError):
    """Tipe file tidak diizinkan."""

    pass


class FileTooLargeError(FileStorageError):
    """File melebihi batas ukuran."""

    pass


class ArchiveError(FileStorageError):
    """Error saat archive."""

    pass


__all__ = [
    "ArchiveError",
    "EvidenceNotFoundError",
    "EvidenceUploadError",
    "FileDownloadError",
    "FileNotFoundError",
    "FileStorageError",
    "FileStorageNotConfiguredError",
    "FileTooLargeError",
    "FileUploadError",
    "InvalidFileTypeError",
]
