#!/usr/bin/env python3
"""
Package: kernel
Layer: 4 - Kernel
"""

from __future__ import annotations

__version__ = "1.0.0"

# Import eksplisit untuk memastikan pytest mengenali submodul
# Kita import langsung modulnya, bukan lewat __getattr__ agar lebih stabil saat testing
try:
    from kernel import (
        audit_hook_injector,
        circuit_breaker,
        command_dispatcher,
        command_envelope,
        command_handler_registry,
        context_holder,
        dependency_injector,
        distributed_lock_redis,
        health_indicator,
        immutable_laws,
        kernel_exceptions,
        lifecycle_listener,
        metric_collector,
        retry_policy,
        sealed_gate,
        transactional_executor,
        validation_pipeline,
    )
except ImportError:
    # Abaikan error saat import awal jika ada dependensi yang belum siap
    # Penting: Jangan raise error di sini agar pytest bisa mulai berjalan
    pass

__all__ = [
    "__version__",
]
