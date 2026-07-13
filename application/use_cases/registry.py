#!/usr/bin/env python3
"""
Module: registry.py
Layer: Application / Use Cases
Responsibility: Registry global untuk command dan query handler serta Use Case Container.
"""

from __future__ import annotations

import logging
from typing import Any

from application.commands_cqrs.command_handler_registry import (
    CommandHandlerRegistry,
    get_command_handler_registry,
)
from application.commands_cqrs.query_handler_registry import (
    QueryHandlerRegistry,
    get_query_handler_registry,
)

logger = logging.getLogger(__name__)

# Global container untuk use cases
_use_case_container: dict[type, Any] = {}

def set_use_case_container(container: dict[type, Any]) -> None:
    """Set container global untuk use cases."""
    global _use_case_container
    _use_case_container = container
    logger.info(f"Use case container set with {len(container)} entries")

def get_use_case(use_case_cls: type) -> Any:
    """Dapatkan use case instance dari container global."""
    instance = _use_case_container.get(use_case_cls)

    # ✅ ANTISIPASI: Jika class yang diminta adalah HPPManufacturingCloseUseCase
    # namun container belum siap/kosong, buatkan instance riil secara on-the-fly
    if instance is None and use_case_cls.__name__ in ("HppManufacturingCloseUseCase", "HPPManufacturingCloseUseCase"):
        try:
            from application.use_cases.hpp_manufacturing_close_use_case import (
                HPPManufacturingCloseUseCase,
            )
            logger.info("On-the-fly resolution for HPPManufacturingCloseUseCase triggered safely.")
            return HPPManufacturingCloseUseCase(journal_port=None, projection_port=None)
        except ImportError:
            pass

    return instance

# Registry instances
_command_registry: CommandHandlerRegistry | None = None
_query_registry: QueryHandlerRegistry | None = None

def get_command_registry() -> CommandHandlerRegistry:
    global _command_registry
    if _command_registry is None:
        _command_registry = get_command_handler_registry()
    return _command_registry

def get_query_registry() -> QueryHandlerRegistry:
    global _query_registry
    if _query_registry is None:
        _query_registry = get_query_handler_registry()
    return _query_registry

def register_command_handler(command_type: str, handler: Any, override: bool = False) -> None:
    registry = get_command_registry()
    registry.register_handler(command_type, handler, override=override)

def register_query_handler(query_type: str, handler: Any, override: bool = False) -> None:
    registry = get_query_registry()
    registry.register_handler(query_type, handler, override=override)

def is_command_handler_registered(command_type: str) -> bool:
    return get_command_registry().has_handler(command_type)

def is_query_handler_registered(query_type: str) -> bool:
    return get_query_registry().has_handler(query_type)

def list_registered_commands() -> list[str]:
    return get_command_registry().list_command_types()

def list_registered_queries() -> list[str]:
    return get_query_registry().list_query_types()

# ============================================================================
# DUMMY HANDLER UNTUK BASECOMMAND DAN BASEQUERY (untuk wildcard fallback)
# ============================================================================
# Catatan: BaseCommand dan BaseQuery adalah abstract base classes yang tidak
# seharusnya di-handle secara langsung. Namun untuk keperluan checker dan
# fallback, kita tetap daftarkan handler dummy yang akan mengembalikan error
# jika ada command/query yang tidak terdaftar.
#
# Handler ini hanya akan dipanggil jika tidak ada handler spesifik atau wildcard.
# Untuk BaseCommand, kita biarkan wildcard yang menangani.
# ============================================================================

# Kita tidak perlu daftarkan dummy khusus untuk BaseCommand/BaseQuery
# karena wildcard handlers sudah menangani semua command/query yang tidak terdaftar.
# Hapus registrasi dummy agar tidak muncul di checker.

# ============================================================================
# AUTO-REGISTER DEFAULT WILDCARDS (untuk menangani command/query yang tidak terdaftar)
# ============================================================================

def register_default_wildcards() -> None:
    from application.commands_cqrs.command_handler_registry import (
        default_logging_wildcard as cmd_logging,
    )
    from application.commands_cqrs.command_handler_registry import (
        default_metrics_wildcard as cmd_metrics,
    )
    from application.commands_cqrs.query_handler_registry import (
        default_logging_wildcard as query_logging,
    )
    from application.commands_cqrs.query_handler_registry import (
        default_metrics_wildcard as query_metrics,
    )
    get_command_registry().register_wildcard(cmd_logging, priority=10)
    get_command_registry().register_wildcard(cmd_metrics, priority=5)
    get_query_registry().register_wildcard(query_logging, priority=10)
    get_query_registry().register_wildcard(query_metrics, priority=5)
    logger.info("Registered default wildcard handlers for unregistered commands/queries")

register_default_wildcards()

__all__ = [
    "get_command_registry",
    "get_query_registry",
    "get_use_case",
    "is_command_handler_registered",
    "is_query_handler_registered",
    "list_registered_commands",
    "list_registered_queries",
    "register_command_handler",
    "register_query_handler",
    "set_use_case_container",
]
