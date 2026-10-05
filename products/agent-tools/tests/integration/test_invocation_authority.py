"""Real SQLite claims with controlled trusted ports; no provider invocation."""
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import json
import pickle
from threading import Barrier

import pytest

from ordessa_environment_api import RequestKey
from ordessa_environment_api.errors import UnknownResultError
from ordessa_environment_api.operations import OperationIntent, StepIntent, safe_json
from ordessa_persistence_sqlite import SqliteStorePort
from pacthold.agents.directory import DirectoryBindingRef
from pacthold.agents.invocation import (
    InvocationGrant, InvocationCurrentState, InvocationIssuer,
    InvocationAuthorityRefused, InvocationContext,
)


class Authority:
    def __init__(self):
        self.issuer_ref = {"environmentNamespace": "env", "issuerId": "controlled-authority"}
        self.revision = "rev-1"
        self.expiry = 100
        self.allowed = True
        self.failure = False
        self.overrides = {}
        self.revalidate_calls = 0

    def authorize(self, request, actions, target_ref, delegation_ref):
        if self.failure:
            raise RuntimeError("credential-do-not-leak")
        if not self.allowed:
            raise PermissionError("not authorized")
        fields = dict(principal_scope=request.principal_scope, actions=actions, target_ref=target_ref,
                      delegation_ref=delegation_ref, authority_revision=self.revision,
                      expires_at=self.expiry, issuer_ref=self.issuer_ref)
        fields.update(self.overrides)
        return InvocationGrant(**fields)

    def revalidate(self, grant, request, actions, target_ref):
        self.revalidate_calls += 1
        return self.authorize(request, actions, target_ref, grant.delegation_ref)


class CurrentState:
    def __init__(self, provider, directory, target):
        self.provider = provider
        self.directory = directory
        self.target = target
        self.active = True
        self.epoch = 0
        self.permitted = True
        self.acquired = None
        self.evidence = None
        self.failure = False
        self.inspect_calls = 0
        self.fail_on = None

    def inspect(self, request, pinned_provider_ref, context_ref, target_ref, action):
        self.inspect_calls += 1
        if self.failure or self.inspect_calls == self.fail_on:
            raise RuntimeError("credential-do-not-leak")
        return InvocationCurrentState(self.provider, self.active, self.epoch, self.directory,
                                      self.permitted, self.acquired, self.evidence)


def setup(tmp_path, action="apply", cleanup=False, delegation=None):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request = RequestKey("env", "user:fixture", "r")
    provider = {"environmentNamespace": "env", "providerId": "fixture", "generation": 1,
                "contractVersion": "1", "implementationDigest": "sha256:" + "1" * 64}
    target = {"environmentNamespace": "env", "hostId": "fixture", "nativeRealm": "fixture",
              "objectId": "target", "scope": "unit", "generation": 1}
    directory = DirectoryBindingRef("env", "binding", 1, "sha256:" + "0" * 64)
    binding = {"action": action, "targetRef": target, "delegationRef": delegation, "cleanup": cleanup}
    step = StepIntent("work", provider, "fixed-input", "fixed-correlation")
    intent = OperationIntent("operation", "controlled-contract-fixture", None,
                             {"environmentNamespace": "env", "directoryBindingRef": directory.to_dict(),
                              "invocationBindings": {"work": binding}}, (step,))
    store.reserve_operation(request, "digest", intent)
    authority = Authority()
    current = CurrentState(provider, directory, target)
    clock = [50]
    issuer = InvocationIssuer(store, authority, current, clock=lambda: clock[0])
    return store, request, intent, authority, current, clock, issuer


def issue(parts, **changes):
    _, request, intent, _, _, _, issuer = parts
    binding = intent.context_ref["invocationBindings"]["work"]
    fields = dict(action=binding["action"], target_ref=binding["targetRef"],
                  delegation_ref=binding["delegationRef"], cleanup=binding["cleanup"])
    fields.update(changes)
    return issuer.issue(request, "digest", "work", **fields)


def verify(parts, context, **changes):
    _, _, intent, _, _, _, issuer = parts
    binding = intent.context_ref["invocationBindings"]["work"]
    fields = dict(action=binding["action"], provider_ref=intent.steps[0].pinned_provider_ref,
                  target_ref=binding["targetRef"], input_digest="fixed-input")
    fields.update(changes)
    return issuer.verify_and_consume(context, **fields)


def test_real_claim_and_one_consumption_with_immutable_context(tmp_path):
    parts = setup(tmp_path)
    store, request, _, _, _, _, _ = parts
    try:
        context = issue(parts)
        assert store.read_operation_step(request, "work").outcome == "possibly-dispatched"
        assert context.facts["grant"]["actions"] == ("apply",)
        with pytest.raises(TypeError):
            context.facts["targetRef"]["objectId"] = "other"
        facts = verify(parts, context)
        assert facts["request"]["principalScope"] == request.principal_scope
        with pytest.raises(UnknownResultError):
            verify(parts, context)
        with pytest.raises(UnknownResultError):
            issue(parts)
        assert store.read_operation_step(request, "work").revision == 1
    finally:
        store.close()


@pytest.mark.parametrize("forgery", ["dict", "dataclass", "copy", "deepcopy", "tamper", "cross-issuer"])
def test_context_provenance_cannot_be_forged(tmp_path, forgery):
    parts = setup(tmp_path)
    store, _, _, authority, current, clock, issuer = parts
    try:
        context = issue(parts)
        if forgery == "dict":
            candidate = dict(context.facts)
        elif forgery == "dataclass":
            @dataclass(frozen=True)
            class Fake:
                facts: object
            candidate = Fake(context.facts)
        elif forgery == "copy":
            candidate = copy.copy(context)
        elif forgery == "deepcopy":
            candidate = copy.deepcopy(context)
        elif forgery == "tamper":
            candidate = context
            facts = json.loads(context._payload)
            facts["action"] = "start"
            object.__setattr__(candidate, "_payload", safe_json(facts))
        else:
            candidate = context
            parts = (*parts[:6], InvocationIssuer(store, authority, current, clock=lambda: clock[0]))
        with pytest.raises(InvocationAuthorityRefused):
            verify(parts, candidate)
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 1
    finally:
        store.close()


def test_context_replace_construction_and_serialization_are_not_credentials(tmp_path):
    parts = setup(tmp_path)
    try:
        context = issue(parts)
        with pytest.raises(TypeError):
            InvocationContext(facts=context.facts)
        with pytest.raises(TypeError):
            replace(context, action="start")
        with pytest.raises(TypeError):
            pickle.dumps(context)
        assert verify(parts, context)["action"] == "apply"
    finally:
        parts[0].close()


@pytest.mark.parametrize("field", ["action", "target", "delegation", "cleanup"])
def test_issue_parameters_must_mirror_frozen_binding_before_claim(tmp_path, field):
    parts = setup(tmp_path)
    try:
        changes = {"action": "start"} if field == "action" else {"cleanup": True} if field == "cleanup" else (
            {"target_ref": {"environmentNamespace": "env", "objectId": "different"}} if field == "target" else
            {"delegation_ref": {"environmentNamespace": "env", "delegationId": "different"}})
        with pytest.raises(InvocationAuthorityRefused):
            issue(parts, **changes)
        assert parts[0].read_operation_step(parts[1], "work") is None
    finally:
        parts[0].close()


@pytest.mark.parametrize("field", ["expiry", "revision", "issuer", "provider", "inactive", "epoch", "directory", "port-exception"])
def test_current_grant_and_state_revalidation_refuses_without_redispatch(tmp_path, field):
    parts = setup(tmp_path)
    store, request, _, authority, current, clock, _ = parts
    try:
        context = issue(parts)
        if field == "expiry":
            clock[0] = 101
        elif field == "revision":
            authority.revision = "rev-2"
        elif field == "issuer":
            authority.issuer_ref = {"environmentNamespace": "env", "issuerId": "different"}
        elif field == "provider":
            current.provider = {**current.provider, "generation": 2}
        elif field == "inactive":
            current.active = False
        elif field == "epoch":
            current.epoch = 1
        elif field == "directory":
            current.permitted = False
        else:
            authority.failure = True
        with pytest.raises(InvocationAuthorityRefused) as caught:
            verify(parts, context)
        assert "credential-do-not-leak" not in str(caught.value)
        assert store.read_operation_step(request, "work").outcome == "possibly-dispatched"
        assert store.read_operation_step(request, "work").revision == 1
    finally:
        store.close()


@pytest.mark.parametrize("overrides", [
    {"principal_scope": "other"}, {"actions": ("apply", "start")},
    {"target_ref": {"environmentNamespace": "other", "targetId": "x"}},
    {"issuer_ref": {"environmentNamespace": "other", "issuerId": "x"}},
    {"delegation_ref": {"environmentNamespace": "other", "delegationId": "x"}},
])
def test_bad_authority_grant_scope_is_refused_before_claim(tmp_path, overrides):
    parts = setup(tmp_path)
    try:
        parts[3].overrides = overrides
        with pytest.raises(InvocationAuthorityRefused):
            issue(parts)
        assert parts[0].read_operation_step(parts[1], "work") is None
    finally:
        parts[0].close()


def test_revalidation_cannot_silently_extend_expiry(tmp_path):
    parts = setup(tmp_path)
    authority = parts[3]
    original = authority.revalidate
    def extend(*args):
        authority.expiry = 200
        return original(*args)
    authority.revalidate = extend
    try:
        with pytest.raises(InvocationAuthorityRefused):
            issue(parts)
        assert parts[0].read_operation_step(parts[1], "work") is None
    finally:
        parts[0].close()


def test_post_claim_failure_remains_spent_and_restart_cannot_reissue(tmp_path):
    parts = setup(tmp_path)
    store, request, _, authority, current, clock, _ = parts
    current.fail_on = 2
    try:
        with pytest.raises(InvocationAuthorityRefused):
            issue(parts)
        assert store.read_operation_step(request, "work").outcome == "possibly-dispatched"
        current.fail_on = None
        restarted = InvocationIssuer(store, authority, current, clock=lambda: clock[0])
        with pytest.raises(UnknownResultError):
            issue((*parts[:6], restarted))
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 1
    finally:
        store.close()


def test_unknown_has_separately_authorized_current_epoch_query(tmp_path):
    parts = setup(tmp_path)
    store, request, intent, authority, current, _, issuer = parts
    try:
        effect = issue(parts)
        store.record_operation_step(request, "digest", "work", "fixed-input", 1, "unknown", {})
        current.epoch = 1
        before = store.read_operation(request)
        with pytest.raises(InvocationAuthorityRefused):
            verify(parts, effect)
        query = issuer.issue_query(request, "digest", "work")
        assert query.facts["managementEpoch"] == 1 and query.facts["query"]
        assert query.facts["grant"]["actions"] == ("query",)
        assert verify(parts, query, action="query")["action"] == "query"
        assert verify(parts, query, action="query")["action"] == "query"
        with pytest.raises(InvocationAuthorityRefused):
            verify(parts, query, action="apply")
        assert store.read_operation(request) == before
        assert store.read_operation_step(request, "work").revision == 2
        authority.allowed = False
        with pytest.raises(InvocationAuthorityRefused):
            issuer.issue_query(request, "digest", "work")
    finally:
        store.close()


@pytest.mark.parametrize("missing", ["authority", "state", "directory"])
def test_missing_guarantees_refuse_without_claim(tmp_path, missing):
    parts = setup(tmp_path)
    store, request, _, authority, current, clock, _ = parts
    try:
        with pytest.raises(InvocationAuthorityRefused):
            if missing == "directory":
                current.permitted = False
                issue(parts)
            else:
                InvocationIssuer(store, None if missing == "authority" else authority,
                                 None if missing == "state" else current, clock=lambda: clock[0])
        assert store.read_operation_step(request, "work") is None
    finally:
        store.close()


@pytest.mark.parametrize("missing", ["target", "evidence", "cross-environment"])
def test_cleanup_requires_trusted_acquisition_and_cannot_grant_start(tmp_path, missing):
    parts = setup(tmp_path, action="stop", cleanup=True)
    store, request, intent, _, current, _, _ = parts
    current.acquired = current.target
    current.evidence = {"environmentNamespace": "env", "evidenceId": "durable-acquisition-fixture"}
    try:
        with pytest.raises(InvocationAuthorityRefused):
            issue(parts, action="start")
        if missing == "target":
            current.acquired = None
        elif missing == "evidence":
            current.evidence = None
        else:
            current.evidence = {"environmentNamespace": "other", "evidenceId": "not-this-environment"}
        with pytest.raises(InvocationAuthorityRefused):
            issue(parts)
        assert store.read_operation_step(request, "work") is None
        current.acquired = current.target
        current.evidence = {"environmentNamespace": "env", "evidenceId": "durable-acquisition-fixture"}
        assert verify(parts, issue(parts))["cleanup"] is True
    finally:
        store.close()


def test_concurrent_consumption_has_exactly_one_winner(tmp_path):
    parts = setup(tmp_path)
    barrier = Barrier(8)
    try:
        context = issue(parts)
        def compete(_):
            barrier.wait(timeout=5)
            try:
                verify(parts, context)
                return "granted"
            except UnknownResultError:
                return "spent"
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(compete, range(8)))
        assert results.count("granted") == 1 and results.count("spent") == 7
    finally:
        parts[0].close()


@pytest.mark.parametrize("port", ["state", "authority"])
def test_trusted_port_callback_reentry_cannot_consume_twice(tmp_path, port):
    parts = setup(tmp_path)
    store, request, _, authority, current, _, _ = parts
    seen = []
    try:
        context = issue(parts)
        owner = current if port == "state" else authority
        method = "inspect" if port == "state" else "revalidate"
        original = getattr(owner, method)
        def callback(*args):
            with pytest.raises(UnknownResultError):
                verify(parts, context)
            seen.append("reentry refused")
            return original(*args)
        setattr(owner, method, callback)
        assert verify(parts, context)["action"] == "apply"
        assert seen == ["reentry refused"] * (2 if port == "authority" else 1)
        with pytest.raises(UnknownResultError):
            verify(parts, context)
        assert store.read_operation_step(request, "work").outcome == "possibly-dispatched"
    finally:
        store.close()


def test_failed_verification_does_not_restore_effect_ticket(tmp_path):
    parts = setup(tmp_path)
    try:
        context = issue(parts)
        parts[4].failure = True
        with pytest.raises(InvocationAuthorityRefused):
            verify(parts, context)
        parts[4].failure = False
        with pytest.raises(UnknownResultError):
            verify(parts, context)
        assert parts[0].read_operation_step(parts[1], "work").outcome == "possibly-dispatched"
    finally:
        parts[0].close()


def test_bounded_ticket_cache_refuses_before_claim_and_reclaims_expired_reads(tmp_path):
    parts = setup(tmp_path)
    store, request, _, authority, current, clock, _ = parts
    issuer = InvocationIssuer(store, authority, current, clock=lambda: clock[0], max_contexts=1)
    small_parts = (*parts[:6], issuer)
    try:
        read = issuer.issue_query(request, "digest", "work")
        with pytest.raises(InvocationAuthorityRefused):
            issue(small_parts)
        assert store.read_operation_step(request, "work") is None
        clock[0], authority.expiry = 101, 200
        effect = issue(small_parts)
        assert len(issuer._issued) == 1
        with pytest.raises(InvocationAuthorityRefused):
            verify(small_parts, read, action="query")
        verify(small_parts, effect)
        with pytest.raises(InvocationAuthorityRefused):
            issuer.issue_query(request, "digest", "work")
        assert issuer.verified_consumption(effect) is True
        # Active continuation is retained. Only the actual known step result
        # makes its process-local proof reclaimable; no additional dispatch.
        store.record_operation_step(request, "digest", "work", "fixed-input", 1,
                                    "concluded", {"evidenceRef": "controlled-result"})
        replacement_read = issuer.issue_query(request, "digest", "work")
        assert len(issuer._issued) == 1
        with pytest.raises(InvocationAuthorityRefused):
            verify(small_parts, effect)
        assert verify(small_parts, replacement_read, action="query")["query"]
        with pytest.raises(UnknownResultError):
            # Clear the read ticket by expiry; an existing effect claim is still spent.
            clock[0], authority.expiry = 201, 300
            issue(small_parts)
    finally:
        store.close()


@pytest.mark.parametrize("port", ["authorize", "revalidate", "inspect"])
def test_missing_port_response_is_typed_refusal(tmp_path, port):
    parts = setup(tmp_path)
    try:
        owner = parts[4] if port == "inspect" else parts[3]
        setattr(owner, port, lambda *args: None)
        with pytest.raises(InvocationAuthorityRefused):
            issue(parts)
        assert parts[0].read_operation_step(parts[1], "work") is None
    finally:
        parts[0].close()


def test_provider_verifier_has_no_issuance_entrypoint(tmp_path):
    parts = setup(tmp_path)
    try:
        verifier = parts[6].verifier()
        assert not hasattr(verifier, "issue") and not hasattr(verifier, "issue_query")
        context = issue(parts)
        assert verifier.verify_and_consume(context, "apply", parts[2].steps[0].pinned_provider_ref,
                                          parts[4].target, "fixed-input")["action"] == "apply"
    finally:
        parts[0].close()


def test_independent_issuers_compete_on_one_real_sqlite_claim(tmp_path):
    parts = setup(tmp_path)
    store, request, _, authority, current, clock, _ = parts
    barrier = Barrier(8)
    try:
        def compete(_):
            issuer = InvocationIssuer(store, authority, current, clock=lambda: clock[0])
            barrier.wait(timeout=5)
            try:
                issue((*parts[:6], issuer))
                return "issued"
            except UnknownResultError:
                return "spent"
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(compete, range(8)))
        assert results.count("issued") == 1 and results.count("spent") == 7
        assert store.read_operation_step(request, "work").revision == 1
        assert store.read_operation(request).revision == 2
    finally:
        store.close()


def test_late_durable_unknown_during_callback_refuses_context(tmp_path):
    parts = setup(tmp_path)
    store, request, _, authority, _, _, _ = parts
    try:
        context = issue(parts)
        original = authority.revalidate
        def callback(*args):
            current = store.read_operation(request)
            store.record_operation_outcome(request, "digest", current.revision, "unknown", {})
            return original(*args)
        authority.revalidate = callback
        with pytest.raises(InvocationAuthorityRefused):
            verify(parts, context)
        assert store.read_operation(request).status == "unknown"
        assert store.read_operation_step(request, "work").outcome == "possibly-dispatched"
    finally:
        store.close()


def test_cleanup_acquisition_evidence_is_frozen_and_revalidated(tmp_path):
    parts = setup(tmp_path, action="release", cleanup=True)
    current = parts[4]
    current.acquired = current.target
    current.evidence = {"environmentNamespace": "env", "evidenceId": "original-acquisition"}
    try:
        context = issue(parts)
        current.evidence = {"environmentNamespace": "env", "evidenceId": "different-acquisition"}
        with pytest.raises(InvocationAuthorityRefused):
            verify(parts, context)
        assert parts[0].read_operation_step(parts[1], "work").outcome == "possibly-dispatched"
    finally:
        parts[0].close()


def test_ticket_capacity_is_reserved_before_reentrant_authority_calls(tmp_path):
    parts = setup(tmp_path)
    store, request, _, authority, current, clock, _ = parts
    issuer = InvocationIssuer(store, authority, current, clock=lambda: clock[0], max_contexts=1)
    parts = (*parts[:6], issuer)
    original = current.inspect
    seen = []
    def callback(*args):
        with pytest.raises(InvocationAuthorityRefused):
            issuer.issue_query(request, "digest", "work")
        seen.append("capacity refused")
        return original(*args)
    current.inspect = callback
    try:
        context = issue(parts)
        assert len(issuer._issued) == 1 and issuer._issuing == 0
        assert seen == ["capacity refused", "capacity refused"]
        verify(parts, context)
        assert len(issuer._issued) == 1 and issuer._issuing == 0
        assert store.read_operation_step(request, "work").outcome == "possibly-dispatched"
    finally:
        store.close()


@pytest.mark.parametrize("clock_value", [float("nan"), float("inf"), -1, "50", None, True])
def test_invalid_clock_refuses_before_durable_claim(tmp_path, clock_value):
    parts = setup(tmp_path)
    store, request, _, authority, current, _, _ = parts
    issuer = InvocationIssuer(store, authority, current, clock=lambda: clock_value)
    try:
        with pytest.raises(InvocationAuthorityRefused):
            issue((*parts[:6], issuer))
        assert store.read_operation_step(request, "work") is None
    finally:
        store.close()
