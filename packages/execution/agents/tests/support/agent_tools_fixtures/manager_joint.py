"""Real Manager/Node owner fixture with a controlled Local ACP peer.

The fixture uses one UnitAdmissionContext, Harness declaration, issuer,
UnitRecords and UnitManager. Its authority is controlled test authority; it
makes no model or production-human-grant claim.
"""
from contextlib import contextmanager
import os
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
import sys

import pytest

UNIT_TESTS = Path(__file__).resolve().parents[4] / "units" / "tests"
if str(UNIT_TESTS) not in sys.path:
    sys.path.insert(0, str(UNIT_TESTS))
from test_unit_instance import Provider, Preparation, Scope

from agent_tools_fixtures.invocation_authority import Authority, CurrentState
from agent_tools_fixtures.node_publication import Policy
from ordessa_execution_agents.harness.definitions.runtime_providers import RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.definitions.admission_identity import AdmissionNamespace
from ordessa_execution_agents.harness.providers.registry.definition_admission import (
    HarnessDefinitionDescriptor, HarnessDefinitionDeclaration,
    HarnessInstallationObservation, HarnessAdmission, HarnessCatalog,
)
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.admission.owner_ports import AgentOwnerPorts, AgentProviderView
from ordessa_units.admission.invocation import InvocationIssuer
from ordessa_units.admission.connection import ConnectionLeasePort
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.bindings.assembly import PreparationContext
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.records import UnitRecords, OperationJournal
from ordessa_units.records.unit_records import UnitRecordsRefused
from ordessa_units.sessions.evidence import AcpUnitEvidence
from ordessa_units.public import AgentOwnerInputs, FreshUnitFactory, bind_unit_manager, unit_services
from ordessa_units.persistence.sqlite import SqliteUnitStore
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac


class _JointScope(Scope):
    """Keep historical target-to-scope conversion explicitly unavailable."""

    def map_legacy_scope(self, target):
        raise UnitRecordsRefused("historical configuration scope conversion is unavailable")


@contextmanager
def build_joint_owner(tmp_path, *, acp_turn_opt_in=False, effect_write_guard_factory=None):
    """Build and own one fresh Manager-backed product test environment."""
    if type(acp_turn_opt_in) is not bool:
        raise TypeError("ACP turn opt-in must be an explicit bool")
    policy = Policy()
    store = SqliteUnitStore(tmp_path / "environment.sqlite")
    admission_lock = RLock()
    context_owner = {}

    def retirement_guard(owner_id, generation):
        return context_owner["context"].provider_retirement_guard(owner_id, generation)

    def harness_retirement_guard(owner_id, generation):
        return context_owner["context"].harness_provider_retirement_guard(owner_id, generation)

    harness_catalog = HarnessCatalog(
        "env", policy=policy, principal_scope="principal", admission_lock=admission_lock,
        retirement_guard=harness_retirement_guard,
    )
    material_catalog = MaterialCatalog(
        "env", admission_lock=admission_lock, retirement_guard=retirement_guard,
    )
    context = UnitAdmissionContext(
        "env", store=store, policy=policy,
        fingerprint_port=ProtectedFingerprintHmac({"fixture": b"joint-manager"}, active_key_id="fixture"),
        harness_catalog=harness_catalog, material_catalog=material_catalog,
        principal_scope="principal", admission_lock=admission_lock,
    )
    context_owner["context"] = context
    units = []
    local = None
    issuer = None
    try:
        definition = {"environmentNamespace": "env", "definitionId": "controlled", "revision": "1"}
        declaration = HarnessDefinitionDeclaration(
            HarnessDefinitionDescriptor(
                "controlled", definition, "sha256:" + "a" * 64, "acp/v1", "controlled-peer",
                capabilities=("existingChannel",),
            ),
            lambda _: HarnessInstallationObservation("present"),
        )
        registration = harness_catalog.stage(
            "fixture.plugin", 1, "fixture.plugin", "a" * 64, (declaration,),
        )
        admitted_definition, = registration.commit()
        pin = HarnessAdmission(context).describe(definition).provider_ref
        directory = DirectoryBindingRef("env", "controlled-directory", 1, "sha256:" + "d" * 64)
        authority = Authority()
        current = CurrentState(pin, directory, None)
        issuer = InvocationIssuer(store, authority, current, clock=lambda: 50)
        verifier = issuer.verifier()
        events = []
        root = tmp_path / "local-provider" / "root"
        root.parent.mkdir()
        local = Provider(root, events)
        evidence = AcpUnitEvidence(
            preparation_authority=lambda plan, facts: plan["context"]["privateRootFacts"],
            start_authority=lambda unit, context: verifier.verify_continuation(
                context, "start", unit.facts["providerRef"], unit.facts["nodeRef"],
                context.facts["inputDigest"],
            ),
        )
        journal_path = tmp_path / "original-unit.sqlite"
        descriptor_fd = os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor_fd)
        journal = OperationJournal(journal_path, acp_turn_opt_in=acp_turn_opt_in)
        scope = _JointScope()
        epoch = SimpleNamespace(current_epoch=lambda _: 0)
        records = UnitRecords(
            journal, scope_authority=scope, native_evidence=evidence,
            verifier=verifier, epoch_port=epoch,
            termination_evidence=evidence,
            acp_turn_opt_in=acp_turn_opt_in,
        )
        evidence.attach_owner(records)
        descriptor = RuntimeProviderDescriptor(
            "controlled", RUNTIME_PROVIDER_VERSION, definition, "sha256:" + "a" * 64,
            ("plan_preparation", "prepare", "start", "connect", "describe_access", "stop", "release"),
        )
        factory_calls = []

        def materialize(agent, environment, facts, snapshot):
            from ordessa_execution_agents.preparation import ConfigurationResources
            directory_path = environment.files.ensure(
                str(Path(agent.harness.resources.location).relative_to(root))
            )
            (Path(directory_path) / "settings.json").write_text("{}")
            return ConfigurationResources(agent.harness.resources.kind, directory_path, True)

        def create_instance(environment_id, plan, provider_view):
            if environment_id != AdmissionNamespace("env") or provider_view.records is not records or provider_view.verifier is not verifier:
                raise ValueError("fixture factory requires the original Environment and owner view")
            factory_calls.append((environment_id, plan, provider_view))
            from ordessa_execution_agents.profiles import decode_revision_ref
            from ordessa_units.management import UnitInstance
            unit = UnitInstance(
                descriptor=descriptor, agent_id="controlled-agent",
                profile_revision=decode_revision_ref(dict(plan["profileSnapshot"]["ref"])),
                environment_instance=local, environment_sharing=True,
                environment_reference={"environmentId": local.identity},
                preparation=Preparation(events), materializer=materialize,
                records=records, projection=evidence, verifier=verifier,
                lease_port=ConnectionLeasePort(), termination_evidence=evidence, timeout=2,
                effect_write_guard_factory=effect_write_guard_factory,
            )
            units.append(unit)
            return unit

        class Context:
            def resolve(self, request, manifest, admitted, node, context, options):
                roots = {key: str(root / key) for key in ("home", "cwd", "profile")}
                return PreparationContext(
                    directory,
                    {"installationRef": {"environmentNamespace": "env", "installationId": "fixture.plugin",
                                          "sourceRevision": "a" * 64}},
                    {"nodeRef": dict(node), "privateRootFacts": roots},
                )

        view = AgentProviderView(records, verifier)
        inputs = AgentOwnerInputs(
            authority=authority, current_state=current, scope_authority=scope,
            native_session_evidence=evidence, management_epoch=epoch,
            node_evidence_port=None, preparation_context_port=Context(),
            preparation_observation_port=None, provider_factory=None,
            fresh_unit_factory=FreshUnitFactory(create_instance=create_instance),
            acp_turn_opt_in=acp_turn_opt_in,
            lifecycle_observation_port=None, termination_evidence=evidence,
        )
        manager = bind_unit_manager(inputs, environment_id=AdmissionNamespace("env"), provider_view=view)
        bundle = AgentOwnerPorts(issuer, view, preparation_context_port=inputs.preparation_context_port,
                                 unit_manager=manager)
        services = unit_services(context, owner_ports=bundle)
        original_record = services.lifecycle._record

        def record(*args, **kwargs):
            if args[3] == "unknown" and sys.exception() is not None:
                import traceback
                traceback.print_exception(sys.exception())
            return original_record(*args, **kwargs)

        services.lifecycle._record = record
        entry = services.profiles.create(
            profile_id="joint", name="Joint",
            content={"schemaVersion": "1", "harnessDefinitionRef": definition, "declarations": []},
            request=RequestKey("env", "principal", "profile"),
        )
        state = SimpleNamespace(
            env=context, store=store, issuer=issuer, records=records, manager=manager,
            services=services, profile=entry.current_revision, events=events, local=local,
            activation=admitted_definition.owner_activation, units=units, current=current, bundle=bundle,
            inputs=inputs, view=view, factory_calls=factory_calls,
        )
        yield state
    finally:
        for unit in units:
            use = unit.channel_factory.environment
            if use is not None and use.identity in local.release_receipts:
                continue
            record = unit.channel_factory.owned_record
            if record is not None:
                unit.channel_factory.close(record.entry)
                unit.channel_factory.release(record.entry)
            if unit.channel_factory.environment is not None:
                unit.channel_factory.release_environment()
        try:
            # The staged owner catalog may still be held by deliberately
            # unresolved test records; it is fixture-local and dies with this
            # context. Close only the empty local material catalog and exact
            # original SQLite writer. Do not reach into any external service.
            material_catalog.close()
        finally:
            if issuer is not None:
                issuer.close()
            if store._conn.in_transaction:
                store._conn.rollback()
            store.close()


@pytest.fixture
def joint(tmp_path):
    with build_joint_owner(tmp_path) as state:
        yield state
