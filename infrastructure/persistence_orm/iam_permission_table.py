#!/usr/bin/env python3
"""
Module: iam_permission_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Alias untuk IAMPermissionTable (forward compatibility)
"""

from __future__ import annotations

from .iam_user_table import IAMPermissionTable

__all__ = ["IAMPermissionTable"]
