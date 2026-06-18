# saga_exceptions.py - Hardened version (already good, minor improvements)

#!/usr/bin/env python3
from __future__ import annotations

"""
Module: saga_exceptions.py
Layer: 8 - Application / Sagas
Responsibility: Mendefinisikan domain exception khusus untuk subsistem Saga Orchestrator.
"""


class SagaException(Exception):
    """
    Base exception untuk semua kesalahan di dalam konteks Saga Orchestration.
    """

    def __init__(self, message: str, *args):
        super().__init__(message, *args)
        self.message = message


class SagaStepExecutionError(SagaException):
    """
    Dilemparkan ketika eksekusi langkah maju (forward step) dalam alur Saga mengalami kegagalan.
    """

    pass


class SagaCompensationError(SagaException):
    """
    Dilemparkan ketika eksekusi langkah kompensasi (backward step) mengalami kegagalan.
    Ini adalah kondisi CRITICAL/FATAL.
    """

    pass


class SagaNotFoundError(SagaException):
    """
    Dilemparkan jika instansiasi Saga berdasar UUID yang dicari tidak ditemukan.
    """

    pass


class SagaAlreadyCompletedError(SagaException):
    """
    Dilemparkan ketika ada instruksi untuk menjalankan kembali transaksi Saga yang sudah selesai.
    """

    pass


class SagaStateStoreError(SagaException):
    """
    Dilemparkan ketika terjadi kegagalan infrastruktur pada layer persistensi database.
    """

    pass


class SagaInvalidStateError(SagaException):
    """
    Dilemparkan ketika saga berada dalam state yang tidak valid untuk operasi yang diminta.
    """

    pass


class SagaStepNotFoundError(SagaException):
    """
    Dilemparkan ketika step yang diminta tidak ditemukan dalam registrasi.
    """

    pass


__all__ = [
    "SagaAlreadyCompletedError",
    "SagaCompensationError",
    "SagaException",
    "SagaInvalidStateError",
    "SagaNotFoundError",
    "SagaStateStoreError",
    "SagaStepExecutionError",
    "SagaStepNotFoundError",
]
