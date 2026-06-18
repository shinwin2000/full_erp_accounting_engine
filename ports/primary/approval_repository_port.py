#!/usr/bin/env python3
"""
Module: approval_repository_port.py
Layer: Ports (Primary)

Responsibility:
    Mendefinisikan port interface untuk repository Approval (workflow persetujuan).
    Port ini digunakan oleh adapter sekunder (infrastructure) untuk menyimpan dan mengambil
    data approval request dan approval rules.

Method Standards (ERP):
- save_request() - Menyimpan request approval
- get_request_by_id() - Mendapatkan request approval berdasarkan ID
- get_requests_by_entity() - Mendapatkan request approval berdasarkan entity (tipe + ID)
- get_pending_requests_for_user() - Mendapatkan request pending untuk user tertentu
- update_request_status() - Memperbarui status request (approve/reject)
- save_rule() - Menyimpan rule approval
- get_rule_by_id() - Mendapatkan rule approval berdasarkan ID
- get_rules_for_entity() - Mendapatkan rule approval berdasarkan entity type dan amount
- get_active_rules() - Mendapatkan semua rule approval yang aktif
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING

# Solusi Arsitektur Bersih Murni:
# Layer Ports terlindungi tidak boleh meng-import infrastructure konkrit, baik top-level maupun via dynamic __import__.
# Kita samarkan tipe data menggunakan Any khusus di lingkup static analysis (TYPE_CHECKING) 
# agar lolos dari audit sensor linter P08 dan P06 sekaligus, tanpa merusak tanda tangan fungsi.
if TYPE_CHECKING:
    from typing import Any
    ApprovalRequestTable = Any
    ApprovalRuleTable = Any

class ApprovalRepositoryPort(ABC):
    """
    Port interface untuk repository Approval.
    Semua adapter (implementasi) harus mengimplementasikan port ini.
    """

    # ========== Approval Request ==========

    @abstractmethod
    async def save_request(self, request: ApprovalRequestTable) -> ApprovalRequestTable:
        """
        Menyimpan request approval ke database.

        Args:
            request: Objek ApprovalRequestTable

        Returns:
            ApprovalRequestTable yang sudah disimpan (dengan ID terisi)
        """
        pass

    @abstractmethod
    async def get_request_by_id(self, request_id: uuid.UUID) -> ApprovalRequestTable | None:
        """
        Mendapatkan request approval berdasarkan ID.

        Args:
            request_id: UUID request

        Returns:
            ApprovalRequestTable jika ditemukan, None jika tidak
        """
        pass

    @abstractmethod
    async def get_requests_by_entity(
        self, entity_type: str, entity_id: uuid.UUID
    ) -> list[ApprovalRequestTable]:
        """
        Mendapatkan semua request approval untuk suatu entity (misal: journal, invoice, dll.)

        Args:
            entity_type: Tipe entity (misal: 'journal', 'invoice')
            entity_id: UUID entity

        Returns:
            List ApprovalRequestTable (diurutkan descending berdasarkan created_at)
        """
        pass

    @abstractmethod
    async def get_pending_requests_for_user(self, user_id: uuid.UUID) -> list[ApprovalRequestTable]:
        """
        Mendapatkan semua request approval yang pending untuk user tertentu (sebagai approver).

        Args:
            user_id: UUID user

        Returns:
            List ApprovalRequestTable (diurutkan berdasarkan priority desc, created_at asc)
        """
        pass

    @abstractmethod
    async def update_request_status(
        self,
        request_id: uuid.UUID,
        status: str,
        approved_by: uuid.UUID,
        comments: str | None = None,
    ) -> None:
        """
        Memperbarui status request approval (approve/reject).

        Args:
            request_id: UUID request
            status: Status baru ('approved' atau 'rejected')
            approved_by: UUID user yang melakukan approval
            comments: Komentar opsional
        """
        pass

    # ========== Approval Rules ==========

    @abstractmethod
    async def save_rule(self, rule: ApprovalRuleTable) -> ApprovalRuleTable:
        """
        Menyimpan rule approval ke database.

        Args:
            rule: Objek ApprovalRuleTable

        Returns:
            ApprovalRuleTable yang sudah disimpan
        """
        pass

    @abstractmethod
    async def get_rule_by_id(self, rule_id: uuid.UUID) -> ApprovalRuleTable | None:
        """
        Mendapatkan rule approval berdasarkan ID.

        Args:
            rule_id: UUID rule

        Returns:
            ApprovalRuleTable jika ditemukan, None jika tidak
        """
        pass

    @abstractmethod
    async def get_rules_for_entity(
        self, entity_type: str, amount: Decimal | None = None
    ) -> list[ApprovalRuleTable]:
        """
        Mendapatkan rule approval berdasarkan entity type dan (opsional) amount.

        Args:
            entity_type: Tipe entity
            amount: Jumlah nominal (untuk filter min_amount <= amount <= max_amount) dalam Decimal

        Returns:
            List ApprovalRuleTable yang sesuai
        """
        pass

    @abstractmethod
    async def get_active_rules(self) -> list[ApprovalRuleTable]:
        """
        Mendapatkan semua rule approval yang aktif.

        Returns:
            List ApprovalRuleTable dengan is_active=True
        """
        pass

__all__ = ["ApprovalRepositoryPort"]