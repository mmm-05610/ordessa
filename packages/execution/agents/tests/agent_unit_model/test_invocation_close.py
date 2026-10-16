"""Original SQLite/issuer fixtures; close revokes permission, not native IO."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from ordessa_units.public import InvocationAuthorityRefused


from agent_tools_fixtures import invocation_authority as original


def test_closed_issuer_refuses_before_claim_and_store_read(tmp_path):
    parts = original.setup(tmp_path)
    store, request, _, _, _, _, issuer = parts
    assert store.read_operation_step(request, "work") is None
    issuer.close()
    issuer.close()
    with pytest.raises(InvocationAuthorityRefused, match="closed"):
        original.issue(parts)
    assert store.read_operation_step(request, "work") is None
    store.close()
    with pytest.raises(InvocationAuthorityRefused, match="closed"):
        issuer.issue_query(request, "digest", "work")


@pytest.mark.parametrize("consume", (False, True))
def test_close_preserves_spent_claim_and_revokes_original_ticket(tmp_path, consume):
    parts = original.setup(tmp_path)
    store, request, intent, _, _, _, issuer = parts
    try:
        context = original.issue(parts)
        if consume:
            original.verify(parts, context)
            assert issuer.verified_consumption(context)
        claim = store.read_operation_step(request, "work")
        issuer.close()
        assert not issuer.verified_consumption(context)
        assert not issuer.verified_observation(context)
        with pytest.raises(InvocationAuthorityRefused):
            original.verify(parts, context)
        with pytest.raises(InvocationAuthorityRefused):
            issuer.verify_continuation(context, "apply", intent.steps[0].pinned_provider_ref,
                                      intent.context_ref["invocationBindings"]["work"]["targetRef"], "fixed-input")
        assert store.read_operation_step(request, "work") == claim
    finally:
        store.close()


@pytest.mark.parametrize("query", (False, True))
def test_close_during_current_state_recheck_cannot_return_valid_permission(tmp_path, query):
    parts = original.setup(tmp_path)
    store, request, _, _, current, _, issuer = parts
    entered, resume = Event(), Event()
    try:
        context = (issuer.issue_query(request, "digest", "work") if query else original.issue(parts))
        claim = store.read_operation_step(request, "work")
        inspect = current.inspect
        def waiting_inspect(*args):
            entered.set()
            assert resume.wait(5), "test did not release the state recheck"
            return inspect(*args)
        current.inspect = waiting_inspect
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(original.verify, parts, context, action="query" if query else "apply")
            try:
                assert entered.wait(5), "verification did not reach the trusted state port"
                issuer.close()
            finally:
                resume.set()
            with pytest.raises(InvocationAuthorityRefused):
                future.result(timeout=5)
        assert not issuer.verified_consumption(context)
        assert not issuer.verified_observation(context)
        assert store.read_operation_step(request, "work") == claim
    finally:
        resume.set()
        store.close()


def test_reentrant_close_after_claim_does_not_publish_context_or_reset_claim(tmp_path):
    parts = original.setup(tmp_path)
    store, request, _, _, current, _, issuer = parts
    inspect = current.inspect
    def closing_inspect(*args):
        result = inspect(*args)
        if current.inspect_calls == 2:
            issuer.close()
        return result
    current.inspect = closing_inspect
    try:
        with pytest.raises(InvocationAuthorityRefused):
            original.issue(parts)
        claim = store.read_operation_step(request, "work")
        assert claim.outcome == "possibly-dispatched"
        assert claim.revision == 1
        with pytest.raises(InvocationAuthorityRefused):
            original.issue(parts)
        assert store.read_operation_step(request, "work") == claim
    finally:
        store.close()


def test_final_grant_serialization_close_cannot_publish_new_ticket(tmp_path):
    parts = original.setup(tmp_path)
    store, request, _, authority, _, _, issuer = parts
    calls = []
    class ClosingGrant(original.InvocationGrant):
        def to_dict(self):
            calls.append(1)
            if len(calls) == 5:  # Two original revalidations, then final payload.
                issuer.close()
            return super().to_dict()
    authorize = authority.authorize
    def closing_authorize(*args):
        return ClosingGrant(**vars(authorize(*args)))
    authority.authorize = closing_authorize
    try:
        with pytest.raises(InvocationAuthorityRefused):
            original.issue(parts)
        assert len(calls) == 5
        assert store.read_operation_step(request, "work").outcome == "possibly-dispatched"
        assert store.read_operation_step(request, "work").revision == 1
    finally:
        store.close()
