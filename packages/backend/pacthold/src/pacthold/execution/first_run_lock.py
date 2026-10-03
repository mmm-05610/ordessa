"""Order 80: the per-library first-run lock for whole-db shared stores.

First-hand (order 66's real-harness race, 2026-09-18): a fresh shared library
plus two concurrent first runs with the real OpenCode binary fails 6/7 (five
`database is locked`, one workspace foreign-key race, exit 1 in ~0.7 s), while
concurrency after initialisation is 3/3 green. The harness's own initialisation
cannot be fixed from here; the *creation window* can be serialised from here:
the first run on a library is exclusive - later runs wait for it, bounded -
and every run after that passes through.

Why the key is coarse: a key that is too fine silently stops locking anything
(a false pass-through is the one failure this module must not have), while a
key that is too coarse only ever costs one extra, one-time wait. The caller
therefore keys on `(placement, family)`.
"""
from __future__ import annotations

import threading

#: How long a turn waits for another turn's first run on the same library
#: before failing typed instead of blocking forever.
FIRST_RUN_WAIT_SECONDS = 300.0


class FirstRunLockTimeout(RuntimeError):
    """The bounded wait for the library's first run expired."""

    code = "FIRST_RUN_LOCK_TIMEOUT"

    def __init__(self, key: str, seconds: float) -> None:
        super().__init__(
            f"another first run on {key} did not finish within {seconds:g}s")
        self.key = key
        self.wait_seconds = seconds


class _Hold:
    """The exclusive hold the first run keeps until its terminal."""

    def __init__(self, gate: "FirstRunGate", key: str, event: threading.Event) -> None:
        self._gate = gate
        self.key = key
        self._event = event
        self._released = False

    def release(self) -> None:
        """Mark the library ready; idempotent, so every exit path may call it."""
        if self._released:
            return
        self._released = True
        self._gate._finish(self._event)

    @property
    def released(self) -> bool:
        return self._released


class FirstRunGate:
    """One exclusive first run per key; later runs pass through once ready."""

    def __init__(self, wait_seconds: float = FIRST_RUN_WAIT_SECONDS) -> None:
        self.wait_seconds = wait_seconds
        self._registry = threading.Lock()
        self._states: dict[str, threading.Event] = {}

    def acquire(self, key: str) -> _Hold | None:
        """Return the first run's exclusive hold, or None when it may pass through.

        The first caller for a key becomes its owner; concurrent callers wait
        (bounded) until the owner's terminal, then pass through; every later
        caller passes through immediately. A timed-out wait is typed - the
        library is never entered unguarded just because someone was slow.
        """
        with self._registry:
            event = self._states.get(key)
            if event is None:
                event = threading.Event()
                self._states[key] = event
                return _Hold(self, key, event)
            if event.is_set():
                return None
        if not event.wait(self.wait_seconds):
            raise FirstRunLockTimeout(key, self.wait_seconds)
        return None

    def _finish(self, event: threading.Event) -> None:
        # The (now set) event stays in the registry as this key's "ready"
        # marker, so later acquires take the immediate pass-through branch.
        event.set()

    def release_all(self) -> None:
        """Force every in-flight first run ready (shutdown, fresh runtime)."""
        with self._registry:
            for event in self._states.values():
                event.set()

    def reset(self) -> None:
        """Forget every key, so the next run on it is a first run again (tests)."""
        self.release_all()
        with self._registry:
            self._states.clear()

    def in_flight(self, key: str) -> bool:
        with self._registry:
            event = self._states.get(key)
        return event is not None and not event.is_set()


_GATE = FirstRunGate()


def first_run_gate() -> FirstRunGate:
    return _GATE


__all__ = [
    "FIRST_RUN_WAIT_SECONDS",
    "FirstRunGate",
    "FirstRunLockTimeout",
    "first_run_gate",
]
