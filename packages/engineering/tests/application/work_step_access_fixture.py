"""Explicit Work-step operations for the labelled source-only access double.

The production Interface authority is tested with real leases separately. Keep
this adaptation outside the immutable source-review fixture capture.
"""
from contextlib import contextmanager
from dataclasses import replace


def enable_controlled_work_steps(monkeypatch):
    from test_real_source_chain import ControlledLocalAccess

    def check(self, context, operation):
        self.require(context, operation)

    @contextmanager
    def admit(self, context, operation, *, request_id):
        self.require(context, operation)
        yield replace(context, request_id=request_id)

    monkeypatch.setattr(ControlledLocalAccess, 'check_work_capability', check, raising=False)
    monkeypatch.setattr(ControlledLocalAccess, 'admit_work_step', admit, raising=False)
