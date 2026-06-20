#!/usr/bin/env python3
"""
Module: iam_role_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Alias untuk IAMRoleTable (forward compatibility)
"""

from __future__ import annotations

from .iam_user_table import IAMRoleTable

__all__ = ["IAMRoleTable"]