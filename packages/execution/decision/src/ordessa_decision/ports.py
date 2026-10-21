"""F1.1 ports: single-use permit, call context and decision provider."""
from __future__ import annotations

import asyncio
import inspect
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from .definitions.models import DecisionAnswer, DecisionQuestion
from .definitions.values import DecisionError, name


def _require_sync_exit(value):
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value):
            value.close()
        raise DecisionError("permit_refused")


class CallPermit:
    __slots__ = ("_run_id", "_question_digest", "_settings_digest", "_deadline", "_claimed",
                 "_claim_guard", "_guard_thread", "_guard_task")

    def __init__(self, run_id, question_digest, settings_digest, deadline):
        self._run_id, self._question_digest = run_id, question_digest
        self._settings_digest, self._deadline = settings_digest, deadline
        self._claimed = False
        self._claim_guard = None
        self._guard_thread = self._guard_task = None

    def bind_claim_guard(self, guard):
        """Bind one trusted synchronous pre-send check in this task/thread.

        Host Python composition only. A guard is never serialized as authority,
        rebound or inferred from job data. Entry failure refuses without consumption; exit failure stays consumed.
        """
        if self._claimed or self._claim_guard is not None or not callable(guard):
            raise DecisionError("permit_refused")
        self._claim_guard = guard
        self._guard_thread = threading.get_ident()
        try:
            self._guard_task = asyncio.current_task()
        except RuntimeError:
            self._guard_task = None

    def claim(self, *, run_id, question_digest, settings_digest):
        if (self._claimed or run_id != self._run_id
                or question_digest != self._question_digest
                or settings_digest != self._settings_digest
                or time.monotonic() >= self._deadline):
            raise DecisionError("permit_refused")
        if self._claim_guard is not None:
            try:
                task = asyncio.current_task()
            except RuntimeError:
                task = None
            if threading.get_ident() != self._guard_thread or task is not self._guard_task:
                raise DecisionError("permit_refused")
            outcome = self._claim_guard()
            if inspect.isawaitable(outcome):
                if inspect.iscoroutine(outcome):
                    outcome.close()
                raise DecisionError("permit_refused")
            if outcome is not None:
                if (not callable(getattr(outcome, "__enter__", None))
                        or not callable(getattr(outcome, "__exit__", None))
                        or inspect.iscoroutinefunction(outcome.__enter__)
                        or inspect.iscoroutinefunction(outcome.__exit__)):
                    raise DecisionError("permit_refused")
                # A trusted synchronous guard may keep its original authority
                # lock through this exact consumption point. Exit failure does
                # not undo consumption or authorize another dispatch.
                admission = outcome.__enter__()
                try:
                    if inspect.isawaitable(admission):
                        if inspect.iscoroutine(admission):
                            admission.close()
                        raise DecisionError("permit_refused")
                    if time.monotonic() >= self._deadline:
                        raise DecisionError("permit_refused")
                    self._claimed = True
                except BaseException as error:
                    exit_result = outcome.__exit__(type(error), error, error.__traceback__)
                    _require_sync_exit(exit_result)
                    # A context manager cannot suppress an admission refusal
                    # and thereby turn an unconsumed permit into a send right.
                    raise
                else:
                    _require_sync_exit(outcome.__exit__(None, None, None))
                if not self._claimed:
                    raise DecisionError("permit_refused")
                return
            if time.monotonic() >= self._deadline:
                raise DecisionError("permit_refused")
        self._claimed = True

    def __repr__(self):
        return "<CallPermit>"


@dataclass(frozen=True, repr=False)
class ModelCallContext:
    run_id: str
    call_id: str
    attempt_no: int
    question_digest: str
    provider_settings_digest: str
    monotonic_deadline: float
    permit: CallPermit

    def __post_init__(self):
        for value in (self.run_id, self.call_id):
            name(value)
        if (type(self.attempt_no) is not int or self.attempt_no < 1
                or type(self.monotonic_deadline) not in (int, float)
                or type(self.permit) is not CallPermit):
            raise DecisionError("invalid_call_context")

    def claim(self, question, settings_digest):
        self.permit.claim(run_id=self.run_id,
                          question_digest=question.question_digest,
                          settings_digest=settings_digest)

    def __repr__(self):
        return "<ModelCallContext>"


class DecisionProvider(Protocol):
    binding_ref: str
    settings_digest: str

    async def decide(self, question: DecisionQuestion,
                     model_context: ModelCallContext) -> DecisionAnswer: ...

    async def close(self) -> None: ...
