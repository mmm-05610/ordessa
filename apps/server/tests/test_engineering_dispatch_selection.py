"""Strong Server selection adapter over the original live Unit owner.

The test package is a typed controlled value. Unit selection itself uses the
actual LocalUnitOwner, UnitServices, records, query issuer and live fence; no
native/model provider is invoked.
"""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.changes.repository_baseline import seal_repository_baseline
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope as EngineeringScope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.models import (
    ImplementationPackage, ImplementationPackagePayload, PackageCoverage,
    PackageDerivation, package_manifest_digest,
)
from ordessa_engineering.adapters.native_records import OriginalDispatchSelection
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant, InstanceAccessAuthority,
)
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.public import unit_services
from ordessa_infrastructure.identifiers import RequestKey


ROOT = Path(__file__).resolve().parents[3]
UNIT_TESTS = ROOT / "packages/execution/units/tests"
if str(UNIT_TESTS) not in sys.path:
    sys.path.insert(0, str(UNIT_TESTS))
from test_local_owner import live_owner


DISPATCH = "engineering.executions.dispatch"
WIRE_SCOPE = WireScope("env", "project")
ENG_SCOPE = EngineeringScope("env", "project")
NOW = "2026-10-13T12:00:00.000000Z"


def _digest(label):
    return Digest("sha256", sha256(label.encode()).hexdigest())


def _blob(label):
    raw = label.encode()
    return BlobRef(_digest(label), len(raw), "application/octet-stream", "selection-" + label)


def _package(scope, profile):
    proposal = ProposalRef(scope.realm_id, scope.project_id, "selection-change",
                           "selection-proposal", _digest("proposal"))
    design = ArtifactRevisionRef(scope.realm_id, scope.project_id,
                                 "selection-design", "revision-1", _digest("design"))
    baseline = seal_repository_baseline(scope, "selection-repo", "none", None, ()).ref
    environment = EnvironmentRef(profile.environment_namespace, profile.profile_id,
                                 Digest("sha256", profile.digest.removeprefix("sha256:")))
    coverage = PackageCoverage(proposal, (_blob("instructions"),), (), (), (design,))
    payload = ImplementationPackagePayload(
        "selection-intent", ChangeSet((proposal,)), (design,),
        (ApprovalRef(scope.realm_id, scope.project_id, "selection-approval", _digest("approval")),),
        MethodRef("selection-method", "1.0.0", 1, _digest("method")), (), (baseline,), (),
        _blob("package-instructions"), (), environment, ("run_checks",), (),
        (coverage,), None,
        PackageDerivation(_digest("intent"), (_blob("generator-input"),),
                          "selection-fixture", "1", package_manifest_digest(())),
    )
    return ImplementationPackage(scope, "selection-package", NOW,
        ActorRef("controlled-service", "service", "selection-fixture"), payload)


def _issued_context():
    authority = InstanceAccessAuthority(
        lambda: "controlled-selection-bearer",
        principal_id="controlled-selection-caller",
        grants=(AccessGrant(WIRE_SCOPE, (DISPATCH,)),),
        legacy_principal=None,
    )
    caller = authority.authenticate("Bearer controlled-selection-bearer")
    return authority, caller, EngineeringCommandAccess(authority)


def _directory_from_original_query(world, unit_ref, invocation):
    reservation = world.records.resolve_unit_reference(
        unit_ref, invocation, input_digest=invocation.facts["inputDigest"],
    )
    assert reservation.public_ref == unit_ref
    read_binding = invocation.facts["contextRef"]["acpTurnRead"]
    assert read_binding["unitRef"] == unit_ref
    directory_value = invocation.facts["contextRef"]["directoryBindingRef"]
    return DirectoryBindingRef.from_dict(dict(directory_value))


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_selection_adapter_holds_same_original_live_unit_owner(live_owner):
    world = live_owner
    unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    original_instance = world.owner.native_unit(unit, world.owner.authorization())
    services = unit_services(world.admission, owner_ports=world.owner._ports)
    assert services.unit_manager is world.original_manager
    assert services.unit_manager.records is world.records

    session_id = original_instance.projection.read_session(unit.identity).native_facts["sessionId"]
    prompt = {"sessionId": session_id, "prompt": [{"type": "text", "text": "selection guard"}]}
    prompt_digest = world.records.acp_prompt_input_digest(unit.identity, prompt)
    invocation = world.owner.authorize_acp_turn_query(
        world.owner.authorization(),
        RequestKey("env", world.permission.principal_scope, "selection-query"),
        unit.identity, "selection-operation",
        expected_prompt_input_digest=prompt_digest,
    )
    directory = _directory_from_original_query(world, unit.identity, invocation)
    profile = world.permission.profile_revision
    package = _package(ENG_SCOPE, profile)
    resolver_calls = []

    def binding_resolver(context, actual_package, full_unit_ref):
        resolver_calls.append((context, actual_package, full_unit_ref))
        return profile, directory, invocation, invocation.facts["inputDigest"]

    selection = OriginalDispatchSelection(
        services, profile, binding_resolver=binding_resolver,
    )
    _authority, caller, access = _issued_context()
    with access.admit(caller, WIRE_SCOPE, DISPATCH,
                      request_id="selection-command-1", trace_id="selection-command-1") as context:
        with selection.guard_selection(context, package, unit.identity) as lease:
            assert lease is not None
            assert resolver_calls == [(context, package, unit.identity)]
            pending = unit.close(world.owner.authorization())
            assert pending["state"] == "pending" and pending["unresolved"] is True
            assert world.records.owner_read_termination(unit.identity["unitId"], "stop") is None
            assert world.environment.snapshot.active_uses == 1
            assert original_instance.channel_factory.owned_record.process.observe().state == "running"
        assert unit.close(world.owner.authorization())["state"] == "confirmed"
    assert world.environment.snapshot.active_uses == 0


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
@pytest.mark.parametrize("refusal", ["profile", "scope", "missing_read"])
def test_selection_adapter_refuses_profile_scope_and_missing_original_read(live_owner, refusal):
    world = live_owner
    unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    original_instance = world.owner.native_unit(unit, world.owner.authorization())
    services = unit_services(world.admission, owner_ports=world.owner._ports)
    profile = world.permission.profile_revision
    session_id = original_instance.projection.read_session(unit.identity).native_facts["sessionId"]
    prompt = {"sessionId": session_id, "prompt": [{"type": "text", "text": "negative selection"}]}
    prompt_digest = world.records.acp_prompt_input_digest(unit.identity, prompt)
    invocation = world.owner.authorize_acp_turn_query(
        world.owner.authorization(),
        RequestKey("env", world.permission.principal_scope, "selection-negative-query"),
        unit.identity, "selection-negative-operation",
        expected_prompt_input_digest=prompt_digest,
    )
    directory = _directory_from_original_query(world, unit.identity, invocation)
    package_scope = EngineeringScope("foreign-env", "project") if refusal == "scope" else ENG_SCOPE
    package_profile = (replace(profile, digest="sha256:" + "e" * 64)
                       if refusal == "profile" else profile)
    package = _package(package_scope, package_profile)

    def binding_resolver(_context, _package, _unit_ref):
        query = None if refusal == "missing_read" else invocation
        return profile, directory, query, invocation.facts["inputDigest"]

    selection = OriginalDispatchSelection(
        services, profile, binding_resolver=binding_resolver,
    )
    _authority, caller, access = _issued_context()
    with access.admit(caller, WIRE_SCOPE, DISPATCH,
                      request_id="selection-negative-command", trace_id="selection-negative-command") as context:
        expected = ("DISPATCH_SELECTION_PROFILE_MISMATCH" if refusal == "profile"
                    else "DISPATCH_SELECTION_BINDING_INVALID" if refusal == "scope"
                    else "DISPATCH_SELECTION_BINDING_UNAVAILABLE")
        with pytest.raises(ApplicationError, match=expected):
            with selection.guard_selection(context, package, unit.identity):
                pytest.fail("invalid selection unexpectedly entered original owner guard")
    assert world.records.owner_read_termination(unit.identity["unitId"], "stop") is None
    assert unit.close(world.owner.authorization())["state"] == "confirmed"
