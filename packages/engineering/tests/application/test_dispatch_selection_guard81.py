"""Engineering must hold/recheck the selected package/Unit port at dispatch cuts.

The selection peer below is deliberately synthetic. It verifies the existing
DispatchSelectionPort seam; it is not a production Unit selection provider.
"""
from contextlib import contextmanager
import asyncio

import pytest

from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteEngineeringUoW
from ordessa_engineering.application.contracts.errors import ApplicationError
from test_implementation_dispatch import UNIT, _context, _dispatch, _setup


class _SelectionPeer:
    def __init__(self, *, refuse_at=None):
        self.calls = 0
        self.refuse_at = refuse_at
        self.seen = []
        self.active = False

    @contextmanager
    def guard_selection(self, context, package, unit_ref):
        self.calls += 1
        self.seen.append((context, package, unit_ref))
        if self.calls == self.refuse_at:
            raise ApplicationError("TEST_SELECTION_REVOKED")
        self.active = True
        try:
            yield {"fixture_selection": self.calls}
        finally:
            self.active = False


class _SnapshotPeer:
    @contextmanager
    def guard_commit_snapshot(self, context, package, unit_ref):
        yield {
            "contract": "unit-live-source-snapshot/1",
            "sourceCut": "observed-live-owner",
            "permissionCut": "authorized-read-time",
            "observedAt": "fixture-observation",
            "authorizedAt": "fixture-authorization",
            "authorityRevision": 1,
            "managementEpoch": 1,
            "unitRef": unit_ref,
            "nodeRef": {"fixture": "node"},
            "publicationRevision": 1,
            "profileRevision": 1,
            "preparationOperationRef": "fixture-prepare",
            "preparationOperationRevision": 1,
            "directoryBindingRef": {"fixture": "directory"},
            "localDirectory": {"fixture": "path"},
            "queryOperationRef": "fixture-query",
            "queryInputDigest": "fixture-digest",
            "currentThroughCommit": False,
            "liveDispatchAuthorized": False,
            "checkoutBaselineVerified": False,
        }


class _Admission:
    @contextmanager
    def guard_intent(self, *args):
        yield object()

    @contextmanager
    def guard_evidence(self, *args):
        yield object()

    @contextmanager
    def gates(self, *args):
        yield ("synthetic-gate-decision",)


class _Approvals:
    def __init__(self, factory):
        self.factory = factory

    def _admission(self):
        return _Admission()

    @contextmanager
    def _gates(self, *args):
        yield ("synthetic-gate-decision",)

    def _check_gates(self, uow, decisions):
        assert decisions == ("synthetic-gate-decision",)


def _restore_production_guards(service, selection):
    # The legacy dispatch fixture replaces this method so it can isolate the
    # approval/write CAS. Restore the real method for this port regression.
    del service._guards
    service.selection = selection
    service.source_snapshots = _SnapshotPeer()
    service.approvals = _Approvals(service.factory)


def test_missing_selection_refuses_before_freeze_or_dispatch_write(tmp_path, monkeypatch):
    library, factory, service, execution, _calls, _grant, _package, intent = _setup(
        tmp_path, monkeypatch)
    try:
        context = _context(intent.scope, _package.created_by)
        service.selection = None
        with pytest.raises(ApplicationError, match="DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE"):
            _dispatch(service, context)
        assert execution.send_calls == []
        with factory.begin(intent.scope, "read") as uow:
            with pytest.raises(ApplicationError, match="NOT_FOUND"):
                uow.dispatch.get("run-1", "source_review", 1, intent.scope)
    finally:
        library.close()


def test_selection_replacement_between_dispatch_commits_refuses_native_send(tmp_path, monkeypatch):
    library, factory, service, execution, _calls, _grant, package, intent = _setup(
        tmp_path, monkeypatch)
    try:
        context = _context(intent.scope, package.created_by)
        selection = _SelectionPeer(refuse_at=2)
        _restore_production_guards(service, selection)
        with pytest.raises(ApplicationError, match="TEST_SELECTION_REVOKED"):
            _dispatch(service, context)
        assert selection.calls == 2
        assert all(item[0] is context and item[1] is package and item[2] == UNIT
                   for item in selection.seen)
        assert execution.send_calls == []
        with factory.begin(intent.scope, "read") as uow:
            row = uow.dispatch.get("run-1", "source_review", 1, intent.scope)
        # The first business COMMIT is durable; replacement at the second
        # guarded cut leaves it reserved and never sends native bytes.
        assert row["dispatch_phase"] == "reserved"
    finally:
        library.close()


def test_selection_guard_is_active_during_both_original_write_commits(tmp_path, monkeypatch):
    library, factory, service, execution, _calls, _grant, package, intent = _setup(
        tmp_path, monkeypatch, send_error=True)
    original_commit = SQLiteEngineeringUoW.commit
    selection = _SelectionPeer()
    commit_guard_state = []
    effect_guard_state = []
    effect_guard_errors = []
    try:
        context = _context(intent.scope, package.created_by)
        _restore_production_guards(service, selection)
        # The fixture grant has a historical validity interval. Exercise the
        # real expiry guard inside that interval without changing production TTL.
        from ordessa_engineering.application.usecases.support import clock
        monkeypatch.setattr(clock, "utc_now", lambda: _grant.intent.not_before)

        def observe_original_commit(uow):
            if uow._library is library and uow._mode == "write":
                commit_guard_state.append(selection.active)
            return original_commit(uow)

        monkeypatch.setattr(SQLiteEngineeringUoW, "commit", observe_original_commit)

        def send_through_original_effect_guard(binding, *, timeout):
            execution.send_calls.append(binding)
            identity = {"unitRef": UNIT, "operationRef": binding.execution_operation_ref,
                "inputDigest": "sha256:" + binding.prompt_input_digest.hex,
                "requestId": "selection-effect-test", "frameDigest": "sha256:" + "a" * 64}

            async def invoke_guard():
                loop = asyncio.get_running_loop()
                async with service._acquire_effect_write_cut(
                        context, binding, identity, loop.time() + 5):
                    # The stub marks the bounded write location; it sends no bytes.
                    effect_guard_state.append(selection.active)

            try:
                asyncio.run(invoke_guard())
            except BaseException as exc:
                effect_guard_errors.append(exc)
                raise
            raise OSError("explicit test peer leaves native outcome unknown")

        execution.send = send_through_original_effect_guard
        result = _dispatch(service, context)

        assert result["phase"] == "unknown"
        assert selection.calls == 3
        # Reserve, possibly_written, and the original effect-write cut all
        # commit while selection is entered. The unknown-result commit follows.
        assert commit_guard_state == [True, True, True, False]
        assert effect_guard_state == [True]
        assert effect_guard_errors == []
        assert execution.send_calls
    finally:
        library.close()
