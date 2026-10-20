"""Process-local wakeup for SSE subscribers."""
from __future__ import annotations

import threading


class EventNotifier:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._generation = 0

    def notify(self) -> None:
        with self._condition:
            self._generation += 1
            self._condition.notify_all()

    def generation(self) -> int:
        with self._condition:
            return self._generation

    def wait_after(self, generation: int, timeout: float = 15.0) -> int:
        with self._condition:
            self._condition.wait_for(lambda: self._generation != generation, timeout)
            return self._generation
