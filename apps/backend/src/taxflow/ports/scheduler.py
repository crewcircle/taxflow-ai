"""Port Protocol for the periodic-job scheduler."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SchedulerPort(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def is_running(self) -> bool: ...
