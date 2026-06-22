from __future__ import annotations

"""
Package: adapters.primary_api
"""

__version__ = "1.0.0"

# Import router dari berbagai adapter
from adapters.primary_api.batch_job_scheduler_adapter import (
    BatchJob,
    BatchJobScheduler,
    get_batch_scheduler,
    get_scheduler,
)
from adapters.primary_api.webhook_receiver_adapter import router as webhook_router

__all__ = [
    "BatchJob",
    "BatchJobScheduler",
    "__version__",
    "get_batch_scheduler",
    "get_scheduler",
    "webhook_router",
]
