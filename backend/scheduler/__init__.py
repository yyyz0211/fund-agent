"""Process-local Scheduler lifecycle API."""
from __future__ import annotations

from backend.scheduler.runtime import (
    get_scheduler,
    shutdown_scheduler,
    start_scheduler,
)

__all__ = [
    "start_scheduler",
    "get_scheduler",
    "shutdown_scheduler",
]
