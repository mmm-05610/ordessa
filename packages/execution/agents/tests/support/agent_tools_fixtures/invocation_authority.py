"""Real SQLite claims with controlled trusted ports; no provider invocation."""
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import json
import pickle
from threading import Barrier

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment.errors import UnknownResultError
from ordessa_execution_api.environment.operations import OperationIntent, StepIntent, safe_json
from ordessa_units.persistence.sqlite.store import SqliteUnitStore
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.admission.invocation import (
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
    store = SqliteUnitStore(tmp_path / "state.sqlite")
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


