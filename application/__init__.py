from __future__ import annotations

"""
Package: application
Use cases, services, command/query buses, sagas, outbox.
"""


from application.lifecycle_handler import LifecycleHandler

__all__ = [
    "ApplicationFactory",
    "LifecycleHandler",
    "create_app",
    "shutdown_app",
]
