#!/usr/bin/env python3
"""
Package: kernel
Layer: 4 - Kernel

Responsibility: Kernel adalah inti dari sistem yang mengatur eksekusi command,
               validasi, audit, circuit breaker, retry policy, dan komponen
               inti lainnya. Semua operasi write harus melalui Sealed Gate.

Fitur lengkap sesuai standar ERP:
- Entity dasar (jika ada) memiliki create, update, delete, restore, activate, deactivate,
  lock, unlock, validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Aggregate root (jika ada) memiliki add_child, remove_child, can_post, post, can_approve,
  approve, can_reject, reject, can_cancel, cancel, can_reverse, reverse, close, reopen,
  archive, unarchive, register_event, get_events, pull_events, clear_events.
- Domain event: event_id, occurred_at, aggregate_id, aggregate_type, to_dict, from_dict,
  serialize, deserialize.
- Repository interface: add, save, update, delete, exists, get_by_id, get_by_code, get_all,
  search, count, list, paginate.
- Value object: validate, normalize, to_string, from_string, to_dict, from_dict, __eq__, __hash__.

Kernel menyediakan infrastruktur untuk semua operasi.
"""

from __future__ import annotations

__version__ = "1.0.0"


# Lazy import untuk menghindari circular import
def __getattr__(name):
    if name == "CommandStatus":
        from kernel.command_envelope import CommandStatus

        return CommandStatus
    if name == "CommandEnvelope":
        from kernel.command_envelope import CommandEnvelope

        return CommandEnvelope
    if name == "SealedGate":
        from kernel.sealed_gate import SealedGate

        return SealedGate
    if name == "get_sealed_gate":
        from kernel.sealed_gate import get_sealed_gate

        return get_sealed_gate
    if name == "AuditHookInjector":
        from kernel.audit_hook_injector import AuditHookInjector

        return AuditHookInjector
    if name == "get_audit_hook_injector":
        from kernel.audit_hook_injector import get_audit_hook_injector

        return get_audit_hook_injector
    if name == "CircuitBreaker":
        from kernel.circuit_breaker import CircuitBreaker

        return CircuitBreaker
    if name == "get_circuit_breaker":
        from kernel.circuit_breaker import get_circuit_breaker

        return get_circuit_breaker
    if name == "CommandDispatcher":
        from kernel.command_dispatcher import CommandDispatcher

        return CommandDispatcher
    if name == "get_command_dispatcher":
        from kernel.command_dispatcher import get_command_dispatcher

        return get_command_dispatcher
    if name == "CommandHandlerRegistry":
        from kernel.command_handler_registry import CommandHandlerRegistry

        return CommandHandlerRegistry
    if name == "get_handler_registry":
        from kernel.command_handler_registry import get_handler_registry

        return get_handler_registry
    if name == "ContextHolder":
        from kernel.context_holder import ContextHolder

        return ContextHolder
    if name == "get_context_holder":
        from kernel.context_holder import get_context_holder

        return get_context_holder
    if name == "DependencyInjector":
        from kernel.dependency_injector import DependencyInjector

        return DependencyInjector
    if name == "get_dependency_injector":
        from kernel.dependency_injector import get_dependency_injector

        return get_dependency_injector
    if name == "DistributedLock":
        from kernel.distributed_lock_redis import DistributedLock

        return DistributedLock
    if name == "get_distributed_lock":
        from kernel.distributed_lock_redis import get_distributed_lock

        return get_distributed_lock
    if name == "KernelHealthIndicator":
        from kernel.health_indicator import KernelHealthIndicator

        return KernelHealthIndicator
    if name == "get_kernel_health_indicator":
        from kernel.health_indicator import get_kernel_health_indicator

        return get_kernel_health_indicator
    if name == "LifecycleListener":
        from kernel.lifecycle_listener import LifecycleListener

        return LifecycleListener
    if name == "get_lifecycle_listener":
        from kernel.lifecycle_listener import get_lifecycle_listener

        return get_lifecycle_listener
    if name == "MetricCollector":
        from kernel.metric_collector import MetricCollector

        return MetricCollector
    if name == "get_metric_collector":
        from kernel.metric_collector import get_metric_collector

        return get_metric_collector
    if name == "RetryPolicy":
        from kernel.retry_policy import RetryPolicy

        return RetryPolicy
    if name == "get_retry_policy":
        from kernel.retry_policy import get_retry_policy

        return get_retry_policy
    if name == "TransactionalExecutor":
        from kernel.transactional_executor import TransactionalExecutor

        return TransactionalExecutor
    if name == "get_transactional_executor":
        from kernel.transactional_executor import get_transactional_executor

        return get_transactional_executor
    if name == "ValidationPipeline":
        from kernel.validation_pipeline import ValidationPipeline

        return ValidationPipeline
    if name == "get_validation_pipeline":
        from kernel.validation_pipeline import get_validation_pipeline

        return get_validation_pipeline
    if name == "KernelError" or name == "KernelExceptionFactory":
        from kernel.kernel_exceptions import KernelError, KernelExceptionFactory

        return KernelError if name == "KernelError" else KernelExceptionFactory
    raise AttributeError(f"module {__name__} has no attribute {name}")


__all__ = [
    "AuditHookInjector",
    "CircuitBreaker",
    "CommandDispatcher",
    "CommandEnvelope",
    "CommandHandlerRegistry",
    "CommandStatus",
    "ContextHolder",
    "DependencyInjector",
    "DistributedLock",
    "KernelError",
    "KernelExceptionFactory",
    "KernelHealthIndicator",
    "LifecycleListener",
    "MetricCollector",
    "RetryPolicy",
    "SealedGate",
    "TransactionalExecutor",
    "ValidationPipeline",
    "__version__",
    "get_audit_hook_injector",
    "get_circuit_breaker",
    "get_command_dispatcher",
    "get_context_holder",
    "get_dependency_injector",
    "get_distributed_lock",
    "get_handler_registry",
    "get_kernel_health_indicator",
    "get_lifecycle_listener",
    "get_metric_collector",
    "get_retry_policy",
    "get_sealed_gate",
    "get_transactional_executor",
    "get_validation_pipeline",
]
