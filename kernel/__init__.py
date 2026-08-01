#!/usr/bin/env python3
"""
Package: kernel
Layer: 4 - Kernel
"""

from __future__ import annotations

import contextlib

__version__ = "1.0.0"

# Import eksplisit untuk memastikan pytest mengenali submodul
# Kita import langsung modulnya, bukan lewat __getattr__ agar lebih stabil saat testing
# Menggunakan contextlib.suppress untuk menangani ImportError tanpa try/except/pass
with contextlib.suppress(ImportError):
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

# Semua modul yang diimpor dimasukkan ke __all__ agar tidak dianggap unused (F401)
# dan juga diekspos sebagai bagian dari package
__all__ = [
    "__version__",
    "audit_hook_injector",
    "circuit_breaker",
    "command_dispatcher",
    "command_envelope",
    "command_handler_registry",
    "context_holder",
    "dependency_injector",
    "distributed_lock_redis",
    "health_indicator",
    "immutable_laws",
    "kernel_exceptions",
    "lifecycle_listener",
    "metric_collector",
    "retry_policy",
    "sealed_gate",
    "transactional_executor",
    "validation_pipeline",
]
