"""Public scheduler entry points.

These are thin delegators to the configured :class:`SchedulerPort` adapter
(see :func:`taxflow.providers.get_scheduler_port`). The scheduler construction
and the three cron-job registrations live in
``taxflow.adapters.scheduler.apscheduler``; ``main.py`` and
``routers/health.py`` call these functions and stay unchanged.
"""

from __future__ import annotations

from taxflow import providers


def start_scheduler() -> None:
    providers.get_scheduler_port().start()


def stop_scheduler() -> None:
    providers.get_scheduler_port().stop()


def is_running() -> bool:
    return providers.get_scheduler_port().is_running()
