#!/usr/bin/env python3
"""
Module: employee_repository_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk repository Employee.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


class EmployeeRepositoryPort(ABC):
    """
    Port interface untuk operasi data Employee.
    """

    @abstractmethod
    async def add(self, employee: Any) -> None:
        """Tambah karyawan baru."""
        pass

    @abstractmethod
    async def update(self, employee: Any) -> None:
        """Update karyawan."""
        pass

    @abstractmethod
    async def save(self, employee: Any) -> None:
        """Simpan atau update karyawan."""
        pass

    @abstractmethod
    async def get_by_id(self, employee_id: UUID) -> Any | None:
        """Cari berdasarkan ID."""
        pass

    @abstractmethod
    async def get_by_code(self, employee_code: str, legal_entity_id: UUID) -> Any | None:
        """Cari berdasarkan kode karyawan."""
        pass

    @abstractmethod
    async def get_by_email(self, email: str) -> Any | None:
        """Cari berdasarkan email."""
        pass

    @abstractmethod
    async def get_by_nik(self, nik: str, legal_entity_id: UUID) -> Any | None:
        """Cari berdasarkan NIK (KTP)."""
        pass

    @abstractmethod
    async def delete(self, employee_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """Hapus karyawan (soft atau hard)."""
        pass

    @abstractmethod
    async def restore(self, employee_id: UUID, user_id: UUID) -> bool:
        """Restore karyawan yang di‑soft delete."""
        pass

    @abstractmethod
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, is_active: bool | None = None
    ) -> list[Any]:
        """Daftar karyawan untuk legal entity."""
        pass

    @abstractmethod
    async def get_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        """Daftar semua karyawan dengan paginasi."""
        pass

    @abstractmethod
    async def find_by_name_contains(
        self, name_fragment: str, legal_entity_id: UUID, limit: int = 50
    ) -> list[Any]:
        """Cari karyawan berdasarkan nama (partial match)."""
        pass

    @abstractmethod
    async def find_by_department(
        self, department: str, legal_entity_id: UUID
    ) -> list[Any]:
        """Cari berdasarkan departemen."""
        pass

    @abstractmethod
    async def find_by_status(
        self, status: str, legal_entity_id: UUID
    ) -> list[Any]:
        """Cari berdasarkan status kepegawaian (active, resigned, dll)."""
        pass

    @abstractmethod
    async def find_by_employment_status(
        self, status: str, legal_entity_id: UUID
    ) -> list[Any]:
        """Alias untuk find_by_status."""
        pass

    @abstractmethod
    async def find_by_supervisor(
        self, supervisor_id: UUID, legal_entity_id: UUID
    ) -> list[Any]:
        """Cari bawahan dari supervisor."""
        pass

    @abstractmethod
    async def get_by_supervisor(
        self, supervisor_id: UUID, legal_entity_id: UUID
    ) -> list[Any]:
        """Alias untuk find_by_supervisor."""
        pass

    @abstractmethod
    async def resign(self, employee_id: UUID, resignation_date: datetime, reason: str) -> bool:
        """Tandai karyawan sebagai resign."""
        pass

    @abstractmethod
    async def update_status(self, employee_id: UUID, is_active: bool) -> None:
        """Update status aktif karyawan."""
        pass

    @abstractmethod
    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Statistik karyawan."""
        pass

    @abstractmethod
    async def get_total_salary_cost(
        self, legal_entity_id: UUID, month: int, year: int
    ) -> Decimal:
        """Total biaya gaji bulanan."""
        pass

    @abstractmethod
    async def get_ptkp_value(self, employee_id: UUID, year: int) -> Decimal:
        """Nilai PTKP untuk karyawan."""
        pass

    @abstractmethod
    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        """Ekspor ke CSV."""
        pass

    @abstractmethod
    async def import_from_csv(
        self, csv_content: str, legal_entity_id: UUID, created_by: UUID
    ) -> int:
        """Impor dari CSV."""
        pass

    @abstractmethod
    async def get_audit_log(
        self, employee_id: UUID | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Ambil audit log."""
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check repository."""
        pass


__all__ = ["EmployeeRepositoryPort"]
